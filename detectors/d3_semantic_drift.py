"""
D3 - Semantic change without retrain (plan-pracy-undertow.md Sec.4).

A transformation dataset (dbt/Spark) one hop upstream of a feature's
source dataset changed its logic after the model's last training run.
Schema is unchanged (D2 doesn't fire), but the meaning of the numbers is
different from what the model learned.

Returns PASS / FINDING / INSUFFICIENT_DATA. Note that "this feature's
source has no upstream transformation at all" is a *conclusive* answer,
not a gap: there is no transformation whose definition could have drifted,
so there is genuinely nothing to find. That is different from "there is a
transformation upstream but we don't know when it last changed", which is
a real blind spot.
"""

from __future__ import annotations

from datetime import datetime

from detectors.models import (
    DatasetSnapshot,
    DetectorResult,
    Finding,
    MissingSignal,
    ModelSnapshot,
    build_result,
)

DETECTOR = "D3"
TITLE = "Semantic change without retrain"
DESCRIPTION = (
    "An upstream dbt/Spark transformation changed its logic after the model's last "
    "training run - same schema, different meaning."
)


def detect(
    model: ModelSnapshot,
    datasets: dict[str, DatasetSnapshot],
    now: datetime,
) -> DetectorResult:
    findings: list[Finding] = []
    missing: list[MissingSignal] = []
    checked = 0

    latest_run = model.latest_training_run
    if latest_run is None:
        return build_result(DETECTOR, findings, [MissingSignal(
            subject_urn=model.urn,
            missing="mlModelProperties.trainingJobs",
            detail="model has no training runs, so a definition change cannot be dated relative to training",
        )], checked)

    if not model.features:
        return build_result(DETECTOR, findings, [MissingSignal(
            subject_urn=model.urn,
            missing="mlModelProperties.mlFeatures",
            detail="model declares no features, so there is no upstream transformation to trace",
        )], checked)

    seen_transform_urns: set[str] = set()
    for feature in model.features:
        ds = datasets.get(feature.source_dataset_urn)
        if ds is None:
            missing.append(MissingSignal(
                subject_urn=feature.source_dataset_urn,
                missing="dataset",
                detail=f"source dataset for feature {feature.name} is not present in the graph",
            ))
            continue

        if not ds.upstream_transformation_urns:
            # Conclusive: nothing upstream that could redefine the data.
            checked += 1
            continue

        for transform_urn in ds.upstream_transformation_urns:
            if transform_urn in seen_transform_urns:
                continue

            transform = datasets.get(transform_urn)
            if transform is None:
                seen_transform_urns.add(transform_urn)
                missing.append(MissingSignal(
                    subject_urn=transform_urn,
                    missing="dataset",
                    detail="upstream transformation dataset is not present in the graph",
                ))
                continue
            if transform.definition_changed_at is None:
                seen_transform_urns.add(transform_urn)
                missing.append(MissingSignal(
                    subject_urn=transform.urn,
                    missing="deadreckon.definitionChangedAt",
                    detail=(
                        f"{transform.name} transforms data this model reads, but there is no "
                        "record of when its logic last changed"
                    ),
                ))
                continue

            seen_transform_urns.add(transform_urn)
            checked += 1
            if transform.definition_changed_at <= latest_run.completed_at:
                continue

            changed_for = now - transform.definition_changed_at
            findings.append(Finding(
                detector=DETECTOR,
                model_urn=model.urn,
                summary=(
                    f"{transform.name}'s transformation logic changed "
                    f"{changed_for.days} day(s) ago; {model.name} last "
                    f"trained {latest_run.completed_at.date().isoformat()}, "
                    f"still assumes the old definition."
                ),
                evidence={
                    "transformation_dataset_urn": transform.urn,
                    "feature_source_dataset_urn": ds.urn,
                    "definition_changed_at": transform.definition_changed_at.isoformat(),
                    "changed_days": changed_for.days,
                    "latest_training_run_urn": latest_run.urn,
                    "latest_training_run_at": latest_run.completed_at.isoformat(),
                },
            ))

    return build_result(DETECTOR, findings, missing, checked)
