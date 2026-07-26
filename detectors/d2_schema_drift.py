"""
D2 - Schema drift under a feature (plan-pracy-undertow.md Sec.4).

A feature's source column is no longer present in its source dataset's
current schema, and the schema change that removed/renamed it happened
after the model's last training run - meaning the model was trained
against a column that has since vanished, and serving would read nulls.
"""

from __future__ import annotations

from datetime import datetime

from detectors.models import DatasetSnapshot, Finding, ModelSnapshot


def detect(
    model: ModelSnapshot,
    datasets: dict[str, DatasetSnapshot],
    now: datetime,
) -> list[Finding]:
    latest_run = model.latest_training_run
    if latest_run is None:
        return []

    findings = []
    for feature in model.features:
        if feature.source_column is None:
            continue
        ds = datasets.get(feature.source_dataset_urn)
        if ds is None or ds.schema_changed_at is None:
            continue
        if feature.source_column in ds.current_columns:
            continue
        if ds.schema_changed_at <= latest_run.completed_at:
            # Column vanished before the last training run, or the model
            # was retrained after the schema change already - the model
            # in production reflects the current schema.
            continue
        missing_for = now - ds.schema_changed_at
        findings.append(Finding(
            detector="D2",
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
    return findings
