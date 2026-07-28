"""
D1 - Frozen training source (plan-pracy-undertow.md Sec.4).

An upstream dataset has stopped receiving real updates, but training runs
that consume it keep firing on schedule. Signal: a training run's own
`completed_at` timestamp is more recent than the dataset's real freshness
signal (`last_updated`, sourced from DataHub's `operation` aspect - see
seed/nyc_taxi_freshness.py) by more than `freshness_threshold_days`.

Returns PASS / FINDING / INSUFFICIENT_DATA. The distinction that matters
here: a dataset with no `operation` aspect at all is not a fresh dataset,
it is an unmeasured one. Reporting that as "clean" would be the exact
silent failure this project exists to catch.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from detectors.models import (
    DatasetSnapshot,
    DetectorResult,
    Finding,
    MissingSignal,
    ModelSnapshot,
    build_result,
)

DETECTOR = "D1"
TITLE = "Frozen training source"
DESCRIPTION = (
    "An upstream dataset stopped receiving real updates, but training runs that "
    "consume it keep firing on schedule."
)
DEFAULT_FRESHNESS_THRESHOLD_DAYS = 2


def detect(
    model: ModelSnapshot,
    datasets: dict[str, DatasetSnapshot],
    now: datetime,
    freshness_threshold_days: int = DEFAULT_FRESHNESS_THRESHOLD_DAYS,
) -> DetectorResult:
    findings: list[Finding] = []
    missing: list[MissingSignal] = []
    checked = 0

    latest_run = model.latest_training_run
    if latest_run is None:
        return build_result(DETECTOR, findings, [MissingSignal(
            subject_urn=model.urn,
            missing="mlModelProperties.trainingJobs",
            detail="model has no training runs, so there is no training cadence to compare a source's freshness against",
        )], checked)

    input_urns = sorted({urn for run in model.training_runs for urn in run.input_dataset_urns})
    if not input_urns:
        return build_result(DETECTOR, findings, [MissingSignal(
            subject_urn=latest_run.urn,
            missing="dataProcessInstanceInput.inputs",
            detail="training runs declare no input datasets, so there is no source to check for staleness",
        )], checked)

    for urn in input_urns:
        ds = datasets.get(urn)
        if ds is None:
            missing.append(MissingSignal(
                subject_urn=urn,
                missing="dataset",
                detail="training input dataset is not present in the graph",
            ))
            continue
        if ds.last_updated is None:
            missing.append(MissingSignal(
                subject_urn=urn,
                missing="operation.lastUpdatedTimestamp",
                detail=f"{ds.name} has no operation aspect, so its real update time is unknown",
            ))
            continue

        checked += 1
        frozen_for = now - ds.last_updated
        if frozen_for < timedelta(days=freshness_threshold_days):
            continue
        if latest_run.completed_at <= ds.last_updated:
            # Most recent training run predates the dataset's last real
            # update - nothing frozen from the model's point of view yet.
            continue
        findings.append(Finding(
            detector=DETECTOR,
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

    return build_result(DETECTOR, findings, missing, checked)
