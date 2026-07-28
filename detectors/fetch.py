"""
Builds the pure dataclasses in detectors/models.py from the live DataHub
graph, for detectors/*.py to run against.

Reads via the DataHub Python SDK/GraphQL directly rather than through
mcp-server-datahub's `get_entities`/`get_lineage` tools. Verified
empirically (2026-07-26, see NOTES.md) that those tools drop most
ML-specific fields for mlModel, mlFeature, and dataProcessInstance
entities (hyperParams, trainingMetrics, sources, dataType, customProperties,
run timestamps - all silently absent from the tool's response even though
the underlying aspects exist and GraphQL/the SDK return them in full).
This is the same class of gap already documented for mlModelDeployment.
`structuredProperties` is the one field proven to project correctly
through the MCP tool for every entity type tested, which is why
detectors/writeback.py still targets it specifically for anything the
agent needs to write back for later reads through that tool.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from datahub.ingestion.graph.client import DataHubGraph
from datahub.metadata.schema_classes import (
    DataProcessInstanceInputClass,
    DataProcessInstancePropertiesClass,
    MLFeaturePropertiesClass,
    MLModelPropertiesClass,
    SchemaMetadataClass,
    StructuredPropertiesClass,
    UpstreamLineageClass,
)

from detectors.models import DatasetSnapshot, Feature, ModelSnapshot, TrainingRun

SCHEMA_CHANGED_AT_PROPERTY_URN = "urn:li:structuredProperty:deadreckon.schemaChangedAt"
DEFINITION_CHANGED_AT_PROPERTY_URN = "urn:li:structuredProperty:deadreckon.definitionChangedAt"
DEPLOYMENT_ENV_PROPERTY_URN = "urn:li:structuredProperty:deadreckon.deploymentEnvironment"

TRANSFORMATION_PLATFORMS = {"dbt", "spark"}

_SOURCE_COLUMN_RE = re.compile(r"Source column:\s*([\w.]+)\.\s*$")


def _parse_source_column(description: str | None) -> str | None:
    if not description:
        return None
    match = _SOURCE_COLUMN_RE.search(description)
    if not match:
        return None
    return match.group(1).rsplit(".", 1)[-1]


def _millis_to_dt(millis: int) -> datetime:
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)


def _string_property(props: StructuredPropertiesClass | None, property_urn: str) -> str | None:
    if props is None:
        return None
    for p in props.properties:
        if p.propertyUrn == property_urn and p.values:
            return str(p.values[0])
    return None


def _string_list_property(props: StructuredPropertiesClass | None, property_urn: str) -> tuple[str, ...]:
    if props is None:
        return ()
    for p in props.properties:
        if p.propertyUrn == property_urn:
            return tuple(str(v) for v in p.values)
    return ()


def _parse_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def fetch_training_run(graph: DataHubGraph, run_urn: str) -> TrainingRun | None:
    """Read a training run's completion time from `DataProcessInstanceProperties.created`.

    Deliberately *not* from the `DataProcessInstanceRunEvent` timeseries
    aspect, even though that is semantically the "run finished" signal.
    Timeseries aspects append rather than replace, so re-running the seed
    leaves every previous run's events in place and `max(timestampMillis)`
    returns whichever seeding happened to use the latest clock - making
    the assessed training date depend on seeding *history* instead of the
    current seed. That silently broke determinism once already (a model
    came back with a training date in the future after a clock-shifted
    test seed), which is exactly the class of drift this pipeline is
    supposed to detect rather than exhibit.

    `DataProcessInstanceProperties` is a versioned aspect: a re-seed
    overwrites it, so the graph always reflects the most recent seed and
    nothing else. seed/ml_lineage.py sets `created` to the run time.
    """
    inputs = graph.get_aspect(entity_urn=run_urn, aspect_type=DataProcessInstanceInputClass)
    input_urns = tuple(inputs.inputs) if inputs else ()

    props = graph.get_aspect(entity_urn=run_urn, aspect_type=DataProcessInstancePropertiesClass)
    if props is None or props.created is None:
        return None
    return TrainingRun(
        urn=run_urn,
        completed_at=_millis_to_dt(props.created.time),
        input_dataset_urns=input_urns,
    )


def fetch_dataset_snapshot(graph: DataHubGraph, dataset_urn: str, now: datetime | None = None) -> DatasetSnapshot:
    schema = graph.get_aspect(entity_urn=dataset_urn, aspect_type=SchemaMetadataClass)
    current_columns = frozenset(f.fieldPath for f in schema.fields) if schema else frozenset()

    props = graph.get_aspect(entity_urn=dataset_urn, aspect_type=StructuredPropertiesClass)
    schema_changed_at = _parse_iso(_string_property(props, SCHEMA_CHANGED_AT_PROPERTY_URN))
    definition_changed_at = _parse_iso(_string_property(props, DEFINITION_CHANGED_AT_PROPERTY_URN))

    # `operation` is a timeseries aspect: emissions append, they never
    # replace. Re-seeding therefore leaves every previously emitted event
    # in the graph, and asking for the single latest one returns whichever
    # emission carried the highest timestamp - not the current seed's.
    # Assessing "as of now" has to mean "using what was known by now", so
    # events reported after the assessment instant are excluded; that is
    # both the correct point-in-time semantics and what keeps a re-seed
    # (or a clock-shifted test seed) from poisoning later runs.
    query = """
    query getOperations($urn: String!) {
      entity(urn: $urn) {
        ... on Dataset {
          operations(limit: 50) {
            timestampMillis
            lastUpdatedTimestamp
          }
        }
      }
    }
    """
    result = graph.execute_graphql(query=query, variables={"urn": dataset_urn})
    operations = (result.get("entity") or {}).get("operations") or []
    cutoff_millis = int((now or datetime.now(timezone.utc)).timestamp() * 1000)
    observed = [op for op in operations
                if op.get("lastUpdatedTimestamp") is not None
                and op.get("timestampMillis", 0) <= cutoff_millis]
    latest = max(observed, key=lambda op: op["timestampMillis"]) if observed else None
    last_updated = _millis_to_dt(latest["lastUpdatedTimestamp"]) if latest else None

    upstream_transform_urns: tuple[str, ...] = ()
    upstream_lineage = graph.get_aspect(entity_urn=dataset_urn, aspect_type=UpstreamLineageClass)
    if upstream_lineage:
        upstream_transform_urns = tuple(
            u.dataset for u in upstream_lineage.upstreams
            if _platform_of(u.dataset) in TRANSFORMATION_PLATFORMS
        )

    name = dataset_urn.split(",")[-2] if "," in dataset_urn else dataset_urn

    return DatasetSnapshot(
        urn=dataset_urn,
        name=name,
        current_columns=current_columns,
        last_updated=last_updated,
        schema_changed_at=schema_changed_at,
        definition_changed_at=definition_changed_at,
        upstream_transformation_urns=upstream_transform_urns,
    )


def _platform_of(dataset_urn: str) -> str:
    # urn:li:dataset:(urn:li:dataPlatform:<platform>,<name>,<env>)
    match = re.search(r"urn:li:dataPlatform:([^,]+)", dataset_urn)
    return match.group(1) if match else ""


def fetch_model_snapshot(graph: DataHubGraph, model_urn: str) -> ModelSnapshot | None:
    props = graph.get_aspect(entity_urn=model_urn, aspect_type=MLModelPropertiesClass)
    if props is None:
        return None

    training_runs = []
    for run_urn in (props.trainingJobs or []):
        run = fetch_training_run(graph, run_urn)
        if run is not None:
            training_runs.append(run)

    features = []
    for feature_urn in (props.mlFeatures or []):
        feature_props = graph.get_aspect(entity_urn=feature_urn, aspect_type=MLFeaturePropertiesClass)
        if feature_props is None or not feature_props.sources:
            continue
        features.append(Feature(
            urn=feature_urn,
            name=feature_urn.split(",")[-1].rstrip(")"),
            source_dataset_urn=feature_props.sources[0],
            source_column=_parse_source_column(feature_props.description),
        ))

    structured_props = graph.get_aspect(entity_urn=model_urn, aspect_type=StructuredPropertiesClass)
    deployment_environments = _string_list_property(structured_props, DEPLOYMENT_ENV_PROPERTY_URN)

    return ModelSnapshot(
        urn=model_urn,
        name=props.name or model_urn,
        training_runs=tuple(training_runs),
        features=tuple(features),
        deployment_environments=deployment_environments,
    )


def fetch_all_model_snapshots(graph: DataHubGraph) -> list[ModelSnapshot]:
    model_urns = graph.get_urns_by_filter(entity_types=["mlModel"])
    snapshots = []
    for urn in model_urns:
        snapshot = fetch_model_snapshot(graph, urn)
        if snapshot is not None:
            snapshots.append(snapshot)
    return snapshots


def fetch_dataset_snapshots(graph: DataHubGraph, dataset_urns: set[str],
                             now: datetime | None = None) -> dict[str, DatasetSnapshot]:
    return {urn: fetch_dataset_snapshot(graph, urn, now) for urn in dataset_urns}
