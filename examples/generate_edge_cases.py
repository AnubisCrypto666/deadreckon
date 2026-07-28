"""
Generates examples/sample-run-edge-cases.json - states the live fixture
cannot reach, emitted in the same schema as a real run.

Why this exists: reviewing the contract, the dashboard's author derived
`at_risk` as "has findings" from sample-run.json, because every model in
that dump with a finding happens to be at risk. That derivation is wrong -
`at_risk` is gated on *severity*, not on finding count - and a dashboard
built on it would paint a red flag where the graph has none. The dump, not
the reviewer, was at fault: it never showed the divergence.

Producing these states from the seeded fixture would mean changing the
demo matrix, which is deliberately fixed. So they are constructed
synthetically here instead, from the same dataclasses and the same
serializer a real run uses - nothing about the shape is hand-written.

Run: python examples/generate_edge_cases.py
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detectors.models import (  # noqa: E402
    DatasetSnapshot,
    DetectorResult,
    DetectorStatus,
    Feature,
    Finding,
    MissingSignal,
    ModelSnapshot,
    TrainingRun,
)
from detectors.report import build_report  # noqa: E402
from detectors.scoring import score_model  # noqa: E402

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
BASE_URL = "http://localhost:9002"

DATASET_URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,acme.warehouse.analytics.sessions,PROD)"
TRANSFORM_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,acme.warehouse.analytics.sessions,PROD)"
FEATURE_URN = "urn:li:mlFeature:(session_features,session_length_p95)"
RUN_URN = "urn:li:dataProcessInstance:edge-case-run-0"

DATASETS = {
    DATASET_URN: DatasetSnapshot(
        urn=DATASET_URN, name="acme.warehouse.analytics.sessions",
        current_columns=frozenset({"session_id", "started_at"}),
        upstream_transformation_urns=(TRANSFORM_URN,),
    ),
    TRANSFORM_URN: DatasetSnapshot(urn=TRANSFORM_URN, name="acme.warehouse.analytics.sessions (dbt)"),
}


def _model(name: str, stages: tuple[str, ...]) -> ModelSnapshot:
    return ModelSnapshot(
        urn=f"urn:li:mlModel:(urn:li:dataPlatform:mlflow,{name},PROD)",
        name=name,
        training_runs=(TrainingRun(urn=RUN_URN, completed_at=NOW - timedelta(days=20),
                                    input_dataset_urns=(DATASET_URN,)),),
        features=(Feature(urn=FEATURE_URN, name="session_length_p95",
                           source_dataset_urn=DATASET_URN, source_column="session_length"),),
        deployment_environments=stages,
        group_urn="urn:li:mlModelGroup:(urn:li:dataPlatform:mlflow,session_models,PROD)",
        group_name="session_models",
    )


def _d2_finding(model: ModelSnapshot) -> Finding:
    return Finding(
        detector="D2", model_urn=model.urn,
        summary=(f"{model.name}'s feature session_length_p95 points at "
                 "acme.warehouse.analytics.sessions.session_length, missing for 6 day(s); "
                 "last trained 2026-07-12, before the schema changed."),
        evidence={
            "feature_urn": FEATURE_URN,
            "dataset_urn": DATASET_URN,
            "source_column": "session_length",
            "schema_changed_at": (NOW - timedelta(days=6)).isoformat(),
            "missing_days": 6,
            "latest_training_run_urn": RUN_URN,
            "latest_training_run_at": (NOW - timedelta(days=20)).isoformat(),
        },
    )


def _pass(detector: str) -> DetectorResult:
    return DetectorResult(detector=detector, status=DetectorStatus.PASS, checked=1)


def _no_data(detector: str, aspect: str) -> DetectorResult:
    return DetectorResult(
        detector=detector, status=DetectorStatus.INSUFFICIENT_DATA,
        missing=(MissingSignal(subject_urn=DATASET_URN, missing=aspect,
                                detail=f"acme.warehouse.analytics.sessions has no {aspect}"),),
    )


def build_cases():
    cases = []

    # 1. Undeployed model with a real finding. score 0.5 -> LOW -> NOT
    #    at_risk, despite finding_count == 1. This is the case whose
    #    absence caused the bad derivation.
    undeployed = _model("session_length_predictor_v0", ())
    cases.append((undeployed, [
        _pass("D1"), DetectorResult(detector="D2", status=DetectorStatus.FINDING,
                                     findings=(_d2_finding(undeployed),), checked=1), _pass("D3")]))

    # 2. Same divergence from the other direction: deployed, but only to
    #    STAGING, and only the softest detector fired.
    staging = _model("session_bounce_predictor_v1", ("STAGING",))
    cases.append((staging, [
        _pass("D1"),
        _pass("D2"),
        DetectorResult(detector="D3", status=DetectorStatus.FINDING, checked=1, findings=(Finding(
            detector="D3", model_urn=staging.urn,
            summary=("acme.warehouse.analytics.sessions (dbt)'s transformation logic changed "
                     "11 day(s) ago; session_bounce_predictor_v1 last trained 2026-07-12, "
                     "still assumes the old definition."),
            evidence={
                "transformation_dataset_urn": TRANSFORM_URN,
                "feature_source_dataset_urn": DATASET_URN,
                "definition_changed_at": (NOW - timedelta(days=11)).isoformat(),
                "changed_days": 11,
                "latest_training_run_urn": RUN_URN,
                "latest_training_run_at": (NOW - timedelta(days=20)).isoformat(),
            }),))]))

    # 3. Fully unassessable: every detector short of metadata. Scores 0.0
    #    like a clean model, but coverage 0/3 and the unassessable tag are
    #    what stop that from being read as "fine".
    opaque = _model("session_ltv_predictor_v2", ("PROD",))
    cases.append((opaque, [
        _no_data("D1", "operation.lastUpdatedTimestamp"),
        _no_data("D2", "deadreckon.schemaChangedAt"),
        _no_data("D3", "deadreckon.definitionChangedAt")]))

    scored = [(m, results, score_model(m, results)) for m, results in cases]
    scored.sort(key=lambda row: row[2].sort_key)
    return scored


def main() -> None:
    scored = build_cases()
    report = build_report(scored, NOW, BASE_URL, DATASETS, clock_overridden=False)
    report["_note"] = (
        "SYNTHETIC. Hand-built states the seeded fixture cannot reach without changing the "
        "demo matrix - see examples/generate_edge_cases.py. Same schema and serializer as a "
        "real run. sample-run.json is the real one."
    )
    out = Path(__file__).resolve().parent / "sample-run-edge-cases.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    print(f"Wrote {out.name} (schema {report['schema_version']})")
    for model, _results, risk in scored:
        print(f"  {model.name:32} score={risk.score:<4} {risk.severity:<7} "
              f"findings={risk.finding_count} coverage={risk.coverage} "
              f"at_risk={risk.severity in ('MEDIUM', 'HIGH')} "
              f"unassessable={risk.coverage.is_unassessable}")


if __name__ == "__main__":
    main()
