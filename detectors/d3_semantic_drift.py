"""
D3 - Semantic change without retrain (plan-pracy-undertow.md Sec.4).

A transformation dataset (dbt/Spark) one hop upstream of a feature's
source dataset changed its logic after the model's last training run.
Schema is unchanged (D2 doesn't fire), but the meaning of the numbers is
different from what the model learned.
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
    seen_transform_urns: set[str] = set()
    for feature in model.features:
        ds = datasets.get(feature.source_dataset_urn)
        if ds is None:
            continue
        for transform_urn in ds.upstream_transformation_urns:
            transform = datasets.get(transform_urn)
            if transform is None or transform.definition_changed_at is None:
                continue
            if transform.definition_changed_at <= latest_run.completed_at:
                continue
            if transform_urn in seen_transform_urns:
                continue
            seen_transform_urns.add(transform_urn)
            changed_for = now - transform.definition_changed_at
            findings.append(Finding(
                detector="D3",
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
    return findings
