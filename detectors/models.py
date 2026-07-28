"""
Pure data structures shared by the three detectors and the scorer. No
DataHub dependency here on purpose - see plan-pracy-undertow.md Sec.8's
requirement that detector logic be testable on synthetic input without a
live DataHub. detectors/fetch.py is what builds these from the real graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


@dataclass(frozen=True)
class TrainingRun:
    urn: str
    completed_at: datetime
    input_dataset_urns: tuple[str, ...]


@dataclass(frozen=True)
class Feature:
    urn: str
    name: str
    source_dataset_urn: str
    source_column: str | None


@dataclass(frozen=True)
class DatasetSnapshot:
    urn: str
    name: str
    current_columns: frozenset[str] = frozenset()
    last_updated: datetime | None = None
    """Real freshness signal (operation aspect), used by D1."""
    schema_changed_at: datetime | None = None
    """Timestamp the current schema (as returned by current_columns) took
    effect - used by D2 to tell whether a missing column disappeared
    before or after a model's last training run."""
    definition_changed_at: datetime | None = None
    """Timestamp a transformation dataset's logic (dbt/Spark) last
    changed meaning without a schema change - used by D3."""
    upstream_transformation_urns: tuple[str, ...] = ()
    """1-hop upstream dataset URNs that are transformation nodes (dbt/Spark
    models) which produced this dataset, relevant to D3."""


@dataclass(frozen=True)
class ModelSnapshot:
    urn: str
    name: str
    training_runs: tuple[TrainingRun, ...]
    features: tuple[Feature, ...]
    deployment_environments: tuple[str, ...] = ()

    @property
    def latest_training_run(self) -> TrainingRun | None:
        if not self.training_runs:
            return None
        return max(self.training_runs, key=lambda r: r.completed_at)


@dataclass(frozen=True)
class Finding:
    detector: str
    """D1, D2, or D3."""
    model_urn: str
    summary: str
    evidence: dict = field(default_factory=dict)


class DetectorStatus(str, Enum):
    """Three states, because "clean" and "couldn't check" are different
    claims and conflating them is how a metadata-only agent quietly lies.

    A detector that returns no findings because the signal it needs is
    absent from the graph has not verified anything - it has only failed
    to look. Saying PASS there would assert something we never checked.
    """

    PASS = "PASS"
    """Had the data it needed, checked, found nothing wrong."""
    FINDING = "FINDING"
    """Checked and found a real problem."""
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    """Could not check - a required signal is missing from the graph."""


@dataclass(frozen=True)
class MissingSignal:
    """What a detector needed and didn't get. Names the aspect/field so
    the gap is actionable ("go emit this") rather than just "unknown"."""

    subject_urn: str
    """The entity we couldn't conclusively check."""
    missing: str
    """Name of the absent aspect/field, e.g. 'operation.lastUpdatedTimestamp'."""
    detail: str = ""


@dataclass(frozen=True)
class DetectorResult:
    detector: str
    status: DetectorStatus
    findings: tuple[Finding, ...] = ()
    missing: tuple[MissingSignal, ...] = ()
    checked: int = 0
    """How many subjects (datasets/features/transformations) this detector
    was able to check conclusively. Kept alongside `missing` so partial
    coverage stays visible: status is the headline, these are the detail."""

    @property
    def is_conclusive(self) -> bool:
        """True when this detector reached a verdict about the model -
        i.e. it either found something or genuinely verified there was
        nothing to find. Drives coverage reporting."""
        return self.status in (DetectorStatus.PASS, DetectorStatus.FINDING)


def build_result(
    detector: str,
    findings: list[Finding],
    missing: list[MissingSignal],
    checked: int,
) -> DetectorResult:
    """Aggregate per-subject outcomes into one status for the detector.

    Precedence: a real finding is always the headline, even if some other
    subject was uncheckable. Absent a finding, *any* uncheckable subject
    downgrades the whole detector to INSUFFICIENT_DATA rather than PASS -
    claiming "clean" requires having actually looked at everything. The
    `checked`/`missing` counts carry the nuance that the single status
    can't.
    """
    if findings:
        status = DetectorStatus.FINDING
    elif missing or checked == 0:
        status = DetectorStatus.INSUFFICIENT_DATA
    else:
        status = DetectorStatus.PASS
    return DetectorResult(
        detector=detector,
        status=status,
        findings=tuple(findings),
        missing=tuple(missing),
        checked=checked,
    )
