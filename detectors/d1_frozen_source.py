"""
D1 - Frozen training source (plan-pracy-undertow.md Sec.4).

An upstream dataset has stopped receiving real updates, but training runs
that consume it keep firing on schedule. Signal: a training run's own
`completed_at` timestamp is more recent than the dataset's real freshness
signal (`last_updated`, sourced from DataHub's `operation` aspect - see
seed/nyc_taxi_freshness.py) by more than `freshness_threshold_days`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from detectors.models import DatasetSnapshot, Finding, ModelSnapshot

DEFAULT_FRESHNESS_THRESHOLD_DAYS = 2


def detect(
    model: ModelSnapshot,
    datasets: dict[str, DatasetSnapshot],
    now: datetime,
    freshness_threshold_days: int = DEFAULT_FRESHNESS_THRESHOLD_DAYS,
) -> list[Finding]:
    latest_run = model.latest_training_run
    if latest_run is None:
        return []

    input_urns = sorted({urn for run in model.training_runs for urn in run.input_dataset_urns})
    findings = []
    for urn in input_urns:
        ds = datasets.get(urn)
        if ds is None or ds.last_updated is None:
            continue
        frozen_for = now - ds.last_updated
        if frozen_for < timedelta(days=freshness_threshold_days):
            continue
        if latest_run.completed_at <= ds.last_updated:
            # Most recent training run predates the dataset's last real
            # update - nothing frozen from the model's point of view yet.
            continue
        findings.append(Finding(
            detector="D1",
            model_urn=model.urn,
            summary=(
                f"{model.name} trains on {ds.name}, frozen for "
                f"{frozen_for.days} day(s), while training runs continue "
                f"on schedule (latest: {latest_run.completed_at.date().isoformat()})."
            ),
            evidence={
                "dataset_urn": ds.urn,
                "dataset_last_updated": ds.last_updated.isoformat(),
                "frozen_days": frozen_for.days,
                "latest_training_run_urn": latest_run.urn,
                "latest_training_run_at": latest_run.completed_at.isoformat(),
            },
        ))
    return findings
