"""
Seeds the ML lineage layer (mlFeatureTable, mlFeature, mlModelGroup, mlModel,
dataProcessInstance training runs, mlModelDeployment) via the DataHub Python
SDK, wired into datasets already loaded by showcase-ecommerce (Snowflake) and
nyc-taxi (SQLite). See plan-pracy-undertow.md Sec.3 for the spec this fulfills.

MLFeatureProperties.sources only accepts dataset-level URNs, not schemaField
(column) URNs - confirmed empirically against the local DataHub Core
instance, which rejects a schemaField destination for that field with a 422
("is not a valid destination for field path: /sources/*"). Column-level
provenance is recorded in each feature's description instead of as a
lineage-graph edge; see NOTES.md.

Deployment status is recorded as a structured property on the mlModel
itself (deadreckon.deploymentEnvironment), NOT as a separate mlModelDeployment
entity. mlModelDeployment was tried first and abandoned: mcp-server-datahub's
get_entities returns "no data could be retrieved" for it, get_lineage finds
no edge to/from it in either direction (MLModelProperties.deployments/
DeployedTo isn't flagged isLineage), and its search filter enum
(mlModelDeployment) doesn't resolve either - so an MCP-only agent had no way
to read deployment status back. structuredProperties on mlModel IS correctly
projected by get_entities (and settable via the add_structured_properties
MCP tool), so it carries the same information through a path that's
actually readable. See NOTES.md for the full Bramka 1 verification.

Training-run timestamps are anchored to the day this script runs (--anchor
overrides), so the taxi_eta model's nightly retraining cadence against
nyc_taxi_pipeline (frozen by seed/nyc_taxi_freshness.py) always reads as
current, not as a July date, whenever this is demoed.

Uses get_default_graph() (reads ~/.datahubenv) rather than a bare
DatahubRestEmitter(url), so it authenticates the same way the `datahub` CLI
does without a token ever having to be typed into a script or shell here.
"""

import argparse
from datetime import datetime, timedelta, timezone

from datahub.emitter.mce_builder import (
    make_data_process_instance_urn,
    make_ml_feature_table_urn,
    make_ml_feature_urn,
    make_ml_model_group_urn,
    make_ml_model_urn,
)
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.graph.client import get_default_graph
from datahub.metadata.schema_classes import (
    AuditStampClass,
    DataProcessInstanceInputClass,
    DataProcessInstanceOutputClass,
    DataProcessInstancePropertiesClass,
    DataProcessInstanceRunEventClass,
    DataProcessRunStatusClass,
    DataProcessTypeClass,
    MLFeaturePropertiesClass,
    MLFeatureTablePropertiesClass,
    MLHyperParamClass,
    MLMetricClass,
    MLModelGroupPropertiesClass,
    MLModelPropertiesClass,
    PropertyCardinalityClass,
    PropertyValueClass,
    StructuredPropertiesClass,
    StructuredPropertyDefinitionClass,
    StructuredPropertyValueAssignmentClass,
    SubTypesClass,
)

DEPLOYMENT_ENV_PROPERTY_URN = "urn:li:structuredProperty:deadreckon.deploymentEnvironment"

FEATURE_PLATFORM = "feast"
MODEL_PLATFORM = "mlflow"
FABRIC = "PROD"


def _dataset_urn(platform: str, name: str) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:{platform},{name},PROD)"


CUSTOMERS = _dataset_urn("snowflake", "b2fd91.order_entry_db.order_entry.customers")
ORDERS = _dataset_urn("snowflake", "b2fd91.order_entry_db.order_entry.orders")
ORDER_ITEMS = _dataset_urn("snowflake", "b2fd91.order_entry_db.order_entry.order_items")
ORDER_DETAILS = _dataset_urn("snowflake", "b2fd91.order_entry_db.analytics.order_details")
TAXI_RAW = _dataset_urn("sqlite", "nyc_taxi_pipeline.main.raw_trips")
TAXI_STAGING = _dataset_urn("sqlite", "nyc_taxi_pipeline.main.staging_trips")

# feature_table -> real upstream datasets a training run against it actually reads
TRAINING_RUN_INPUTS = {
    "customer_features": [CUSTOMERS],
    "order_features": [ORDER_DETAILS, ORDERS, ORDER_ITEMS],
    "taxi_trip_features": [TAXI_RAW, TAXI_STAGING],
}

# feature_table -> { feature_name: (source_dataset, source_column, dataType, description) }
FEATURE_TABLES = {
    "customer_features": {
        "description": "Feast feature view over the order-entry customer dimension.",
        "features": {
            "customer_tenure_days": (CUSTOMERS, "customer_since", "COUNT",
                "Days since signup. Source column: customers.customer_since."),
            "customer_credit_limit": (CUSTOMERS, "credit_limit", "CONTINUOUS",
                "Source column: customers.credit_limit."),
            "customer_class_code": (CUSTOMERS, "customer_class", "NOMINAL",
                "Source column: customers.customer_class."),
            "customer_region_id": (CUSTOMERS, "region_id", "NOMINAL",
                "Source column: customers.region_id."),
        },
    },
    "order_features": {
        "description": "Feast feature view aggregating order and order-item history.",
        "features": {
            "avg_order_value_30d": (ORDER_DETAILS, "order_total", "CONTINUOUS",
                "30-day rolling mean. Source column: analytics.order_details.order_total."),
            "order_count_30d": (ORDERS, "order_id", "COUNT",
                "30-day rolling count. Source column: order_entry.orders.order_id."),
            "avg_discount_pct_30d": (ORDER_DETAILS, "discount_percent", "CONTINUOUS",
                "Source column: analytics.order_details.discount_percent."),
            "days_since_last_order": (ORDERS, "order_date", "COUNT",
                "Source column: order_entry.orders.order_date."),
            "return_rate_90d": (ORDER_ITEMS, "return_date", "CONTINUOUS",
                "Source column: order_entry.order_items.return_date."),
        },
    },
    "taxi_trip_features": {
        "description": "Feast feature view over nyc_taxi_pipeline trip data.",
        "features": {
            "avg_trip_duration_min": (TAXI_STAGING, "trip_duration_min", "CONTINUOUS",
                "Source column: nyc_taxi_pipeline.staging_trips.trip_duration_min."),
            "avg_trip_distance": (TAXI_RAW, "trip_distance", "CONTINUOUS",
                "Source column: nyc_taxi_pipeline.raw_trips.trip_distance."),
            "avg_fare_amount": (TAXI_RAW, "fare_amount", "CONTINUOUS",
                "Source column: nyc_taxi_pipeline.raw_trips.fare_amount."),
            "pickup_hour_bucket": (TAXI_RAW, "tpep_pickup_datetime", "ORDINAL",
                "Source column: nyc_taxi_pipeline.raw_trips.tpep_pickup_datetime."),
        },
    },
}

MODEL_GROUPS = {
    "customer_churn_models": "Customer churn classifiers.",
    "order_value_models": "Next-order value regressors.",
    "taxi_eta_models": "NYC taxi ETA and fare regressors.",
}

# model_name -> spec. `runs` is a list of {days_ago, duration_min}; `deployment`
# is a FabricType string ("PROD"/"STAGING") or None if not yet promoted.
MODELS = {
    "customer_churn_predictor_v1": {
        "group": "customer_churn_models",
        "type": "CLASSIFICATION",
        "description": "Gradient-boosted churn classifier, superseded by v2.",
        "features": [
            "customer_features.customer_tenure_days",
            "customer_features.customer_credit_limit",
            "order_features.avg_order_value_30d",
            "order_features.days_since_last_order",
        ],
        "hyperparams": {"n_estimators": "200", "max_depth": "6", "learning_rate": "0.05"},
        "metrics": {"auc": "0.81", "recall_at_p50": "0.64"},
        "runs": [{"days_ago": 46, "duration_min": 38}],
        "deployment": "STAGING",
    },
    "customer_churn_predictor_v2": {
        "group": "customer_churn_models",
        "type": "CLASSIFICATION",
        "description": "Gradient-boosted churn classifier, current production version.",
        "features": [
            "customer_features.customer_tenure_days",
            "customer_features.customer_credit_limit",
            "customer_features.customer_class_code",
            "order_features.avg_order_value_30d",
            "order_features.days_since_last_order",
        ],
        "hyperparams": {"n_estimators": "350", "max_depth": "7", "learning_rate": "0.03"},
        "metrics": {"auc": "0.86", "recall_at_p50": "0.71"},
        "runs": [{"days_ago": 5, "duration_min": 51}],
        "deployment": "PROD",
    },
    "order_value_predictor_v1": {
        "group": "order_value_models",
        "type": "REGRESSION",
        "description": "Regression model estimating next-order value per customer.",
        "features": [
            "order_features.avg_order_value_30d",
            "order_features.order_count_30d",
            "order_features.avg_discount_pct_30d",
            "order_features.return_rate_90d",
        ],
        "hyperparams": {"model_type": "lightgbm", "num_leaves": "63"},
        "metrics": {"rmse": "14.2", "mae": "9.7"},
        "runs": [{"days_ago": 11, "duration_min": 22}],
        "deployment": "PROD",
    },
    "taxi_eta_predictor_v1": {
        "group": "taxi_eta_models",
        "type": "REGRESSION",
        "description": "ETA regression trained nightly on nyc_taxi_pipeline trip data.",
        "features": [
            "taxi_trip_features.avg_trip_duration_min",
            "taxi_trip_features.avg_trip_distance",
            "taxi_trip_features.pickup_hour_bucket",
        ],
        "hyperparams": {"model_type": "xgboost", "max_depth": "8"},
        "metrics": {"mae_minutes": "2.1"},
        "runs": [{"days_ago": d, "duration_min": 17} for d in (0, 1, 2, 3)],
        "deployment": "PROD",
    },
    "taxi_fare_predictor_v1": {
        "group": "taxi_eta_models",
        "type": "REGRESSION",
        "description": "Fare-amount regression, same feature view as the ETA model.",
        "features": [
            "taxi_trip_features.avg_fare_amount",
            "taxi_trip_features.avg_trip_distance",
            "taxi_trip_features.pickup_hour_bucket",
        ],
        "hyperparams": {"model_type": "xgboost", "max_depth": "6"},
        "metrics": {"mae_dollars": "1.35"},
        "runs": [{"days_ago": 2, "duration_min": 14}],
        "deployment": None,
    },
}


def emit_feature_tables(graph) -> None:
    for table_name, table_def in FEATURE_TABLES.items():
        table_urn = make_ml_feature_table_urn(FEATURE_PLATFORM, table_name)
        feature_urns = []
        for feature_name, (source_ds, _column, data_type, description) in table_def["features"].items():
            feature_urn = make_ml_feature_urn(table_name, feature_name)
            feature_urns.append(feature_urn)
            graph.emit(MetadataChangeProposalWrapper(
                entityUrn=feature_urn,
                aspect=MLFeaturePropertiesClass(
                    description=description,
                    dataType=data_type,
                    sources=[source_ds],
                ),
            ))
        graph.emit(MetadataChangeProposalWrapper(
            entityUrn=table_urn,
            aspect=MLFeatureTablePropertiesClass(
                description=table_def["description"],
                mlFeatures=feature_urns,
            ),
        ))
        print(f"  mlFeatureTable {table_name}: {len(feature_urns)} features")


def emit_deployment_env_property_definition(graph) -> None:
    graph.emit(MetadataChangeProposalWrapper(
        entityUrn=DEPLOYMENT_ENV_PROPERTY_URN,
        aspect=StructuredPropertyDefinitionClass(
            qualifiedName="deadreckon.deploymentEnvironment",
            displayName="Deployment Environment",
            description=(
                "Environment(s) this ML model is currently deployed to. Denormalized "
                "onto the model itself rather than modeled as a separate "
                "mlModelDeployment entity - see NOTES.md for why."
            ),
            valueType="urn:li:dataType:datahub.string",
            entityTypes=["urn:li:entityType:datahub.mlModel"],
            cardinality=PropertyCardinalityClass.MULTIPLE,
            allowedValues=[PropertyValueClass(value="PROD"), PropertyValueClass(value="STAGING")],
        ),
    ))


def emit_model_groups(graph) -> None:
    for group_name, description in MODEL_GROUPS.items():
        group_urn = make_ml_model_group_urn(MODEL_PLATFORM, group_name, FABRIC)
        graph.emit(MetadataChangeProposalWrapper(
            entityUrn=group_urn,
            aspect=MLModelGroupPropertiesClass(name=group_name, description=description),
        ))
    print(f"  {len(MODEL_GROUPS)} mlModelGroups")


def emit_training_runs(graph, model_name: str, model_def: dict, now: datetime) -> list[str]:
    tables_used = {f.split(".", 1)[0] for f in model_def["features"]}
    run_inputs = sorted({ds for t in tables_used for ds in TRAINING_RUN_INPUTS[t]})
    model_urn = make_ml_model_urn(MODEL_PLATFORM, model_name, FABRIC)

    run_urns = []
    for i, run_def in enumerate(model_def["runs"]):
        run_time = now - timedelta(days=run_def["days_ago"])
        run_time_ms = int(run_time.timestamp() * 1000)
        run_id = f"{model_name}-run-{i}"
        run_urn = make_data_process_instance_urn(run_id)
        run_urns.append(run_urn)

        graph.emit(MetadataChangeProposalWrapper(
            entityUrn=run_urn,
            aspect=SubTypesClass(typeNames=["MLFLOW_TRAINING_RUN"]),
        ))
        graph.emit(MetadataChangeProposalWrapper(
            entityUrn=run_urn,
            aspect=DataProcessInstancePropertiesClass(
                name=run_id,
                created=AuditStampClass(time=run_time_ms, actor="urn:li:corpuser:datahub"),
                type=DataProcessTypeClass.BATCH_SCHEDULED,
                customProperties={"model": model_name, "duration_min": str(run_def["duration_min"])},
            ),
        ))
        graph.emit(MetadataChangeProposalWrapper(
            entityUrn=run_urn,
            aspect=DataProcessInstanceInputClass(inputs=run_inputs),
        ))
        graph.emit(MetadataChangeProposalWrapper(
            entityUrn=run_urn,
            aspect=DataProcessInstanceOutputClass(outputs=[model_urn]),
        ))
        graph.emit(MetadataChangeProposalWrapper(
            entityUrn=run_urn,
            aspect=DataProcessInstanceRunEventClass(
                timestampMillis=run_time_ms + run_def["duration_min"] * 60 * 1000,
                status=DataProcessRunStatusClass.COMPLETE,
            ),
        ))
    return run_urns


def emit_models(graph, now: datetime) -> None:
    for model_name, model_def in MODELS.items():
        model_urn = make_ml_model_urn(MODEL_PLATFORM, model_name, FABRIC)
        group_urn = make_ml_model_group_urn(MODEL_PLATFORM, model_def["group"], FABRIC)
        feature_urns = [make_ml_feature_urn(*f.split(".", 1)) for f in model_def["features"]]
        run_urns = emit_training_runs(graph, model_name, model_def, now)

        latest_run_days_ago = min(r["days_ago"] for r in model_def["runs"])
        # NOTE: an MLModelProperties emission fully replaces the aspect, not merges it
        # (same gotcha as the upstream nyc-taxi add_metadata.py bug fixed in
        # seed/fix_nyc_taxi_tags.py) - every field must be set in this single emission.
        graph.emit(MetadataChangeProposalWrapper(
            entityUrn=model_urn,
            aspect=MLModelPropertiesClass(
                name=model_name,
                description=model_def["description"],
                type=model_def["type"],
                date=int((now - timedelta(days=latest_run_days_ago)).timestamp() * 1000),
                hyperParams=[MLHyperParamClass(name=k, value=v) for k, v in model_def["hyperparams"].items()],
                trainingMetrics=[MLMetricClass(name=k, value=v) for k, v in model_def["metrics"].items()],
                mlFeatures=feature_urns,
                groups=[group_urn],
                trainingJobs=run_urns,
            ),
        ))

        if model_def["deployment"]:
            graph.emit(MetadataChangeProposalWrapper(
                entityUrn=model_urn,
                aspect=StructuredPropertiesClass(properties=[
                    StructuredPropertyValueAssignmentClass(
                        propertyUrn=DEPLOYMENT_ENV_PROPERTY_URN,
                        values=[model_def["deployment"]],
                    ),
                ]),
            ))
        print(f"  mlModel {model_name}: {len(run_urns)} run(s), "
              f"deployment={model_def['deployment'] or 'none'}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchor", type=str, default=None,
                         help="ISO date to treat as 'now' for run timestamps (default: real now)")
    args = parser.parse_args()
    now = (datetime.now(timezone.utc) if args.anchor is None
           else datetime.fromisoformat(args.anchor).replace(tzinfo=timezone.utc))

    graph = get_default_graph()

    print("Deployment-environment structured property definition:")
    emit_deployment_env_property_definition(graph)
    print("Feature tables + features:")
    emit_feature_tables(graph)
    print("Model groups:")
    emit_model_groups(graph)
    print("Models, training runs, deployment-environment property:")
    emit_models(graph, now)
    print("\nDone.")


if __name__ == "__main__":
    main()
