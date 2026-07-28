"""
End-to-end deadreckon pipeline: fetch ML lineage from DataHub, run D1-D3
(plan-pracy-undertow.md Sec.4), score findings (Sec.5), and write risk
assessments back into the graph next to the models they concern.

Usage:
    python run_detectors.py            # fetch, detect, score, write back
    python run_detectors.py --dry-run  # fetch, detect, score, print only
    python run_detectors.py --matrix   # add the model x detector state matrix
"""

import argparse
from datetime import datetime, timezone

from datahub.ingestion.graph.client import get_default_graph

from detectors import d1_frozen_source, d2_schema_drift, d3_semantic_drift
from detectors.fetch import fetch_all_model_snapshots, fetch_dataset_snapshots
from detectors.models import DetectorResult, DetectorStatus, ModelSnapshot
from detectors.scoring import MAX_POSSIBLE_SCORE, ModelRiskScore, is_at_risk, score_model
from detectors.writeback import ensure_writeback_definitions, write_risk_assessment

DETECTOR_ORDER = ("D1", "D2", "D3")
STATUS_GLYPHS = {
    DetectorStatus.PASS: "PASS",
    DetectorStatus.FINDING: "FINDING",
    DetectorStatus.INSUFFICIENT_DATA: "NO-DATA",
}


def collect_dataset_urns(models: list[ModelSnapshot]) -> set[str]:
    urns = {f.source_dataset_urn for m in models for f in m.features}
    urns |= {u for m in models for r in m.training_runs for u in r.input_dataset_urns}
    return urns


def run_detectors(model: ModelSnapshot, datasets: dict, now: datetime) -> list[DetectorResult]:
    return [
        d1_frozen_source.detect(model, datasets, now),
        d2_schema_drift.detect(model, datasets, now),
        d3_semantic_drift.detect(model, datasets, now),
    ]


def print_matrix(rows: list[tuple[ModelSnapshot, list[DetectorResult], ModelRiskScore]]) -> None:
    name_width = max(len(m.name) for m, _, _ in rows)
    header = (f"{'model'.ljust(name_width)}  " + "  ".join(d.ljust(7) for d in DETECTOR_ORDER)
              + "  score  severity  coverage")
    print(header)
    print("-" * len(header))
    for model, results, risk in rows:
        by_detector = {r.detector: r for r in results}
        cells = "  ".join(STATUS_GLYPHS[by_detector[d].status].ljust(7) for d in DETECTOR_ORDER)
        print(f"{model.name.ljust(name_width)}  {cells}  "
              f"{str(risk.score).rjust(5)}  {risk.severity.ljust(8)}  {risk.coverage}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="skip writeback, print findings only")
    parser.add_argument("--matrix", action="store_true", help="print the model x detector state matrix")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    graph = get_default_graph()

    print("Fetching model lineage from DataHub...")
    models = fetch_all_model_snapshots(graph)
    print(f"  {len(models)} model(s) found")

    dataset_urns = collect_dataset_urns(models)
    datasets = fetch_dataset_snapshots(graph, dataset_urns)
    # D3 needs snapshots for upstream transformation datasets too, which
    # aren't feature sources or training inputs themselves.
    transform_urns = {u for ds in datasets.values() for u in ds.upstream_transformation_urns}
    datasets.update(fetch_dataset_snapshots(graph, transform_urns - datasets.keys()))
    print(f"  {len(datasets)} dataset(s) fetched for detector input")

    if not args.dry_run:
        ensure_writeback_definitions(graph)

    scored = [(model, results, score_model(model, results))
              for model in models
              for results in [run_detectors(model, datasets, now)]]
    # Ranked risk table: score first, finding count breaks ties (see
    # ModelRiskScore.sort_key for why multiplicity lives here rather than
    # inside the score itself).
    scored.sort(key=lambda row: row[2].sort_key)

    print()
    for model, results, risk in scored:
        if risk.findings:
            print(f"{model.name}: {risk.severity} (score={risk.score}/{MAX_POSSIBLE_SCORE}, "
                  f"blast_radius={risk.blast_radius}, coverage={risk.coverage})")
            for finding in risk.findings:
                print(f"  [{finding.detector}] {finding.summary}")
        elif risk.coverage.is_unassessable:
            print(f"{model.name}: NOT ASSESSED (coverage={risk.coverage})")
        else:
            print(f"{model.name}: no findings (coverage={risk.coverage})")

        for signal in risk.coverage.missing:
            print(f"  [gap] missing {signal.missing} - {signal.detail}")

        if not args.dry_run:
            doc_urn = write_risk_assessment(graph, model, risk, now)
            tags = []
            if is_at_risk(risk.severity):
                tags.append("undertow:at-risk")
            if risk.coverage.is_unassessable:
                tags.append("undertow:unassessable")
            tag_note = f"tagged {', '.join(tags)}" if tags else "no tags (below MEDIUM, assessable)"
            print(f"  -> wrote {doc_urn}, {tag_note}, set riskScore/findingCount/coverage/lastAssessedAt")

    if args.matrix:
        print()
        print_matrix(scored)


if __name__ == "__main__":
    main()
