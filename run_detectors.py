"""
End-to-end deadreckon pipeline: fetch ML lineage from DataHub, run D1-D3
(plan-pracy-undertow.md Sec.4), score findings (Sec.5), and write risk
assessments back into the graph next to the models they concern.

Usage:
    python run_detectors.py            # fetch, detect, score, write back
    python run_detectors.py --dry-run  # fetch, detect, score, print only
"""

import argparse
from datetime import datetime, timezone

from datahub.ingestion.graph.client import get_default_graph

from detectors import d1_frozen_source, d2_schema_drift, d3_semantic_drift
from detectors.fetch import fetch_all_model_snapshots, fetch_dataset_snapshots
from detectors.models import Finding, ModelSnapshot
from detectors.scoring import score_model
from detectors.writeback import ensure_writeback_definitions, write_risk_assessment


def collect_dataset_urns(models: list[ModelSnapshot]) -> set[str]:
    urns = {f.source_dataset_urn for m in models for f in m.features}
    urns |= {u for m in models for r in m.training_runs for u in r.input_dataset_urns}
    return urns


def run_detectors(model: ModelSnapshot, datasets: dict, now: datetime) -> list[Finding]:
    findings = []
    findings += d1_frozen_source.detect(model, datasets, now)
    findings += d2_schema_drift.detect(model, datasets, now)
    findings += d3_semantic_drift.detect(model, datasets, now)
    return findings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="skip writeback, print findings only")
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

    print()
    any_findings = False
    for model in models:
        findings = run_detectors(model, datasets, now)
        risk = score_model(model, findings)
        if risk is None:
            print(f"{model.name}: no findings")
            continue

        any_findings = True
        print(f"{model.name}: {risk.severity} (score={risk.score}, blast_radius={risk.blast_radius})")
        for finding in findings:
            print(f"  [{finding.detector}] {finding.summary}")

        if not args.dry_run:
            doc_urn = write_risk_assessment(graph, model, risk, now)
            print(f"  -> wrote {doc_urn}, tagged undertow:at-risk, set riskScore/lastAssessedAt")

    if not any_findings:
        print("No findings across any model.")


if __name__ == "__main__":
    main()
