"""
D2 - Schema drift under a feature (plan-pracy-undertow.md Sec.4).

A feature's source column is no longer present in its source dataset's
current schema, and the schema change that removed/renamed it happened
after the model's last training run - meaning the model was trained
against a column that has since vanished, and serving would read nulls.

Returns PASS / FINDING / INSUFFICIENT_DATA. Note the asymmetry in what
this detector needs: if the column is still present, that is conclusive on
its own and no change timestamp is required. The timestamp is only needed
to adjudicate a column that *is* missing - was it removed before the last
training run (so the model already reflects its absence) or after (so the
model is stale against its own feature)?
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

DETECTOR = "D2"


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
            detail="model has no training runs, so a schema change cannot be dated relative to training",
        )], checked)

    if not model.features:
        return build_result(DETECTOR, findings, [MissingSignal(
            subject_urn=model.urn,
            missing="mlModelProperties.mlFeatures",
            detail="model declares no features, so there is no feature-to-column mapping to verify",
        )], checked)

    for feature in model.features:
        if feature.source_column is None:
            missing.append(MissingSignal(
                subject_urn=feature.urn,
                missing="mlFeatureProperties.description[Source column]",
                detail=f"feature {feature.name} does not record which upstream column it reads",
            ))
            continue

        ds = datasets.get(feature.source_dataset_urn)
        if ds is None:
            missing.append(MissingSignal(
                subject_urn=feature.source_dataset_urn,
                missing="dataset",
                detail=f"source dataset for feature {feature.name} is not present in the graph",
            ))
            continue
        if not ds.current_columns:
            missing.append(MissingSignal(
                subject_urn=ds.urn,
                missing="schemaMetadata.fields",
                detail=f"{ds.name} exposes no schema, so a column's presence cannot be verified",
            ))
            continue

        if feature.source_column in ds.current_columns:
            # Conclusive without needing a change timestamp: the column
            # the feature reads is right there in the current schema.
            checked += 1
            continue

        if ds.schema_changed_at is None:
            missing.append(MissingSignal(
                subject_urn=ds.urn,
                missing="deadreckon.schemaChangedAt",
                detail=(
                    f"{ds.name}.{feature.source_column} is absent from the current schema, but "
                    "without a schema-change timestamp it cannot be told whether the model was "
                    "retrained since it disappeared"
                ),
            ))
            continue

        checked += 1
        if ds.schema_changed_at <= latest_run.completed_at:
            # Column vanished before the last training run - the model in
            # production already reflects the current schema.
            continue

        missing_for = now - ds.schema_changed_at
        findings.append(Finding(
            detector=DETECTOR,
            model_urn=model.urn,
            summary=(
                f"{model.name}'s feature {feature.name} points at "
                f"{ds.name}.{feature.source_column}, missing for "
                f"{missing_for.days} day(s); last trained "
                f"{latest_run.completed_at.date().isoformat()}, before the "
                f"schema changed."
            ),
            evidence={
                "feature_urn": feature.urn,
                "dataset_urn": ds.urn,
                "source_column": feature.source_column,
                "schema_changed_at": ds.schema_changed_at.isoformat(),
                "missing_days": missing_for.days,
                "latest_training_run_urn": latest_run.urn,
                "latest_training_run_at": latest_run.completed_at.isoformat(),
            },
        ))

    return build_result(DETECTOR, findings, missing, checked)
