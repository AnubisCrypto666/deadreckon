"""
Pure data structures shared by the three detectors and the scorer. No
DataHub dependency here on purpose - see plan-pracy-undertow.md Sec.8's
requirement that detector logic be testable on synthetic input without a
live DataHub. detectors/fetch.py is what builds these from the real graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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
