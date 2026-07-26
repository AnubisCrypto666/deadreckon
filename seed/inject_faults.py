"""
Plants the D2 (schema drift) and D3 (semantic drift without retrain)
fault signals that detectors/d2_schema_drift.py and d3_semantic_drift.py
are meant to catch. See plan-pracy-undertow.md Sec.3's own honesty rule:
scenarios #2 and #3 require deliberately altering schema/definition
history ourselves, and that has to be disclosed plainly in the README -
unlike D1, which rides on the real, community-shipped nyc-taxi freshness
gap (seed/nyc_taxi_freshness.py).

D2 - renames `credit_limit` to `credit_limit_usd` on the showcase-ecommerce
`customers` table (Snowflake). The mlFeature `customer_credit_limit`
(feature table `customer_features`) still points at the old column name in
its description, and `customer_churn_predictor_v2` (PROD, last trained 5
days ago per seed/ml_lineage.py) was trained before the rename. A
`deadreckon.schemaChangedAt` structured property records when the rename
"took effect", anchored 3 days ago - after that training run, so the
model is provably stale against its own feature.

D3 - edits the discount_percent calculation in the dbt `order_details`
model's view logic: originally `(list_price - unit_price) / list_price *
100` (percent of list price), changed here to `... / unit_price * 100`
(percent of unit price) - same column name and type, different number.
`order_value_predictor_v1` (PROD, last trained 11 days ago) uses the
`avg_discount_pct_30d` feature sourced from this column.
`customer_churn_predictor_v2` also uses this dbt node transitively (via
avg_order_value_30d/order_total) but trained 5 days ago - *after* the
9-days-ago definition change anchored here - so it should NOT be flagged;
that's the intended contrast the detector's date logic is meant to draw.
A `deadreckon.definitionChangedAt` structured property on the dbt dataset
records the change timestamp, since DataHub's own aspect versioning for
`viewProperties`/`schemaMetadata` isn't reliably exposed through
mcp-server-datahub's get_entities/get_lineage tools (see NOTES.md) - unlike
structuredProperties, which is.

Idempotent: re-running with the same --anchor just re-emits the same
target state (rename + edited logic + same property values).
"""

import argparse
import copy
from datetime import datetime, timedelta, timezone

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.graph.client import get_default_graph
from datahub.metadata.schema_classes import (
    PropertyCardinalityClass,
    SchemaMetadataClass,
    StructuredPropertiesClass,
    StructuredPropertyDefinitionClass,
    StructuredPropertyValueAssignmentClass,
    ViewPropertiesClass,
)

CUSTOMERS_URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.order_entry.customers,PROD)"
ORDER_DETAILS_DBT_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,b2fd91.ORDER_ENTRY_DB.analytics.order_details,PROD)"

SCHEMA_CHANGED_AT_PROPERTY_URN = "urn:li:structuredProperty:deadreckon.schemaChangedAt"
DEFINITION_CHANGED_AT_PROPERTY_URN = "urn:li:structuredProperty:deadreckon.definitionChangedAt"

OLD_COLUMN_NAME = "credit_limit"
NEW_COLUMN_NAME = "credit_limit_usd"
SCHEMA_CHANGE_DAYS_AGO = 3

OLD_DISCOUNT_LOGIC = (
    "    CASE \n"
    "        WHEN li.list_price > 0 THEN ((li.list_price - li.unit_price) / li.list_price) * 100 \n"
    "        ELSE 0 \n"
    "    END AS discount_percent,"
)
NEW_DISCOUNT_LOGIC = (
    "    CASE \n"
    "        WHEN li.unit_price > 0 THEN ((li.list_price - li.unit_price) / li.unit_price) * 100 \n"
    "        ELSE 0 \n"
    "    END AS discount_percent,"
)
DEFINITION_CHANGE_DAYS_AGO = 9


def _iso(now: datetime, days_ago: int) -> str:
    return (now - timedelta(days=days_ago)).isoformat()


def emit_property_definitions(graph) -> None:
    graph.emit(MetadataChangeProposalWrapper(
        entityUrn=SCHEMA_CHANGED_AT_PROPERTY_URN,
        aspect=StructuredPropertyDefinitionClass(
            qualifiedName="deadreckon.schemaChangedAt",
            displayName="Schema Changed At",
            description=(
                "ISO 8601 timestamp of when this dataset's current schema "
                "took effect. Stands in for DataHub's own schemaMetadata "
                "aspect versioning, which isn't reliably readable through "
                "mcp-server-datahub - see NOTES.md."
            ),
            valueType="urn:li:dataType:datahub.string",
            entityTypes=["urn:li:entityType:datahub.dataset"],
            cardinality=PropertyCardinalityClass.SINGLE,
        ),
    ))
    graph.emit(MetadataChangeProposalWrapper(
        entityUrn=DEFINITION_CHANGED_AT_PROPERTY_URN,
        aspect=StructuredPropertyDefinitionClass(
            qualifiedName="deadreckon.definitionChangedAt",
            displayName="Definition Changed At",
            description=(
                "ISO 8601 timestamp of when a transformation dataset's "
                "(dbt/Spark) view logic last changed meaning without a "
                "schema change."
            ),
            valueType="urn:li:dataType:datahub.string",
            entityTypes=["urn:li:entityType:datahub.dataset"],
            cardinality=PropertyCardinalityClass.SINGLE,
        ),
    ))


def inject_d2_schema_drift(graph, now: datetime) -> None:
    schema = graph.get_aspect(entity_urn=CUSTOMERS_URN, aspect_type=SchemaMetadataClass)
    if schema is None:
        raise RuntimeError(f"no schemaMetadata found for {CUSTOMERS_URN}")

    renamed = False
    new_fields = []
    for f in schema.fields:
        f = copy.deepcopy(f)
        if f.fieldPath == OLD_COLUMN_NAME:
            f.fieldPath = NEW_COLUMN_NAME
            renamed = True
        new_fields.append(f)
    if not renamed:
        existing_names = {f.fieldPath for f in schema.fields}
        if NEW_COLUMN_NAME in existing_names:
            print(f"  {CUSTOMERS_URN}: already renamed to {NEW_COLUMN_NAME}, skipping")
        else:
            raise RuntimeError(f"column {OLD_COLUMN_NAME!r} not found on {CUSTOMERS_URN}")
    else:
        schema.fields = new_fields
        schema.version += 1
        graph.emit(MetadataChangeProposalWrapper(entityUrn=CUSTOMERS_URN, aspect=schema))
        print(f"  {CUSTOMERS_URN}: renamed {OLD_COLUMN_NAME} -> {NEW_COLUMN_NAME}")

    graph.emit(MetadataChangeProposalWrapper(
        entityUrn=CUSTOMERS_URN,
        aspect=StructuredPropertiesClass(properties=[
            StructuredPropertyValueAssignmentClass(
                propertyUrn=SCHEMA_CHANGED_AT_PROPERTY_URN,
                values=[_iso(now, SCHEMA_CHANGE_DAYS_AGO)],
            ),
        ]),
    ))
    print(f"  {CUSTOMERS_URN}: schemaChangedAt = {SCHEMA_CHANGE_DAYS_AGO} day(s) ago")


def inject_d3_semantic_drift(graph, now: datetime) -> None:
    view_props = graph.get_aspect(entity_urn=ORDER_DETAILS_DBT_URN, aspect_type=ViewPropertiesClass)
    if view_props is None:
        raise RuntimeError(f"no viewProperties found for {ORDER_DETAILS_DBT_URN}")

    if NEW_DISCOUNT_LOGIC in view_props.viewLogic:
        print(f"  {ORDER_DETAILS_DBT_URN}: discount_percent logic already changed, skipping")
    elif OLD_DISCOUNT_LOGIC not in view_props.viewLogic:
        raise RuntimeError("expected discount_percent CASE block not found verbatim in viewLogic")
    else:
        view_props.viewLogic = view_props.viewLogic.replace(OLD_DISCOUNT_LOGIC, NEW_DISCOUNT_LOGIC)
        graph.emit(MetadataChangeProposalWrapper(entityUrn=ORDER_DETAILS_DBT_URN, aspect=view_props))
        print(f"  {ORDER_DETAILS_DBT_URN}: discount_percent now computed against unit_price, not list_price")

    graph.emit(MetadataChangeProposalWrapper(
        entityUrn=ORDER_DETAILS_DBT_URN,
        aspect=StructuredPropertiesClass(properties=[
            StructuredPropertyValueAssignmentClass(
                propertyUrn=DEFINITION_CHANGED_AT_PROPERTY_URN,
                values=[_iso(now, DEFINITION_CHANGE_DAYS_AGO)],
            ),
        ]),
    ))
    print(f"  {ORDER_DETAILS_DBT_URN}: definitionChangedAt = {DEFINITION_CHANGE_DAYS_AGO} day(s) ago")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchor", type=str, default=None,
                         help="ISO date to treat as 'now' (default: real now) - keep in sync with ml_lineage.py's --anchor")
    args = parser.parse_args()
    now = (datetime.now(timezone.utc) if args.anchor is None
           else datetime.fromisoformat(args.anchor).replace(tzinfo=timezone.utc))

    graph = get_default_graph()

    print("Structured property definitions:")
    emit_property_definitions(graph)
    print("D2 - schema drift (customers.credit_limit rename):")
    inject_d2_schema_drift(graph, now)
    print("D3 - semantic drift (order_details discount_percent logic):")
    inject_d3_semantic_drift(graph, now)
    print("\nDone.")


if __name__ == "__main__":
    main()
