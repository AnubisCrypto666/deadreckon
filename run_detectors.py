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
import json
from datetime import datetime
from pathlib import Path

from datahub.ingestion.graph.client import get_default_graph

from detectors import clock, d1_frozen_source, d2_schema_drift, d3_semantic_drift
from detectors.fetch import fetch_all_model_snapshots, fetch_dataset_snapshots
from detectors.models import DetectorResult, DetectorStatus, ModelSnapshot
from detectors.report import build_report
from detectors.scoring import MAX_POSSIBLE_SCORE, ModelRiskScore, is_at_risk, score_model
from detectors.writeback import FRONTEND_BASE_URL, ensure_writeback_definitions, write_risk_assessment

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


# How far the freshest seeded dataset may lag "now" before the matrix
# stops matching the one the seed was built to produce. D1's own
# threshold is the real limit - past it, a dataset the seed made fresh
# starts reading as stale purely because time passed since seeding.
SEED_STALENESS_WARNING_DAYS = d1_frozen_source.DEFAULT_FRESHNESS_THRESHOLD_DAYS


def warn_if_seed_is_stale(datasets: dict, now: datetime) -> None:
    """Make seed drift loud rather than silent.

    Freshness is wall-clock relative, so a graph seeded days ago yields a
    different matrix than the same seed run today - which would mean a
    judge sees something other than the demo. Rather than let that pass
    quietly, say so and name the fix.
    """
    timestamps = [ds.last_updated for ds in datasets.values() if ds.last_updated is not None]
    if not timestamps:
        return
    age_days = (now - max(timestamps)).days
    if age_days >= SEED_STALENESS_WARNING_DAYS:
        print(f"  WARNING: freshest dataset in the graph is {age_days}d old. The seed anchors "
              f"timestamps to when it runs, so results will differ from a freshly seeded graph.")
        print("           Re-run seed/ (see README) for the reproducible matrix.")


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
    parser.add_argument("--as-of", type=str, default=None,
                         help="ISO timestamp to assess against (default: DEADRECKON_NOW, else real now)")
    parser.add_argument("--json", type=str, default=None, metavar="PATH",
                         help="write the full run as JSON (see docs/output-schema.md)")
    parser.add_argument("--datahub-url", type=str, default=FRONTEND_BASE_URL,
                         help="DataHub UI base URL used to build entity links in --json output")
    args = parser.parse_args()

    now = clock.now(args.as_of)
    graph = get_default_graph()

    print("Fetching model lineage from DataHub...")
    models = fetch_all_model_snapshots(graph)
    print(f"  {len(models)} model(s) found")

    dataset_urns = collect_dataset_urns(models)
    datasets = fetch_dataset_snapshots(graph, dataset_urns, now)
    # D3 needs snapshots for upstream transformation datasets too, which
    # aren't feature sources or training inputs themselves.
    transform_urns = {u for ds in datasets.values() for u in ds.upstream_transformation_urns}
    datasets.update(fetch_dataset_snapshots(graph, transform_urns - datasets.keys(), now))
    print(f"  {len(datasets)} dataset(s) fetched for detector input")
    warn_if_seed_is_stale(datasets, now)
    if clock.is_overridden():
        print(f"  (clock overridden via {clock.NOW_ENV_VAR}: assessing as of {now.isoformat()})")

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

    if args.json:
        report = build_report(scored, now, args.datahub_url, datasets, clock.is_overridden())
        Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(f"\nWrote {args.json} (schema {report['schema_version']})")


if __name__ == "__main__":
    main()
