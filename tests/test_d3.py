from datetime import datetime, timedelta, timezone

from detectors import d3_semantic_drift as d3
from detectors.models import DatasetSnapshot, Feature, ModelSnapshot, TrainingRun

NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)
SNOWFLAKE_URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,x.order_details,PROD)"
DBT_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,x.order_details,PROD)"


def _model(feature: Feature, run_completed_at: datetime) -> ModelSnapshot:
    return ModelSnapshot(
        urn="urn:li:mlModel:m",
        name="m",
        training_runs=(TrainingRun(urn="urn:li:dataProcessInstance:r0", completed_at=run_completed_at, input_dataset_urns=(SNOWFLAKE_URN,)),),
        features=(feature,),
    )


def _feature() -> Feature:
    return Feature(urn="urn:li:mlFeature:(t,f)", name="f", source_dataset_urn=SNOWFLAKE_URN, source_column="discount_percent")


def test_fires_when_upstream_definition_changed_after_last_training():
    datasets = {
        SNOWFLAKE_URN: DatasetSnapshot(urn=SNOWFLAKE_URN, name="order_details", upstream_transformation_urns=(DBT_URN,)),
        DBT_URN: DatasetSnapshot(urn=DBT_URN, name="order_details (dbt)", definition_changed_at=NOW - timedelta(days=9)),
    }
    model = _model(_feature(), run_completed_at=NOW - timedelta(days=11))

    findings = d3.detect(model, datasets, NOW)

    assert len(findings) == 1
    assert findings[0].detector == "D3"
    assert findings[0].evidence["changed_days"] == 9


def test_no_finding_when_retrained_after_definition_change():
    datasets = {
        SNOWFLAKE_URN: DatasetSnapshot(urn=SNOWFLAKE_URN, name="order_details", upstream_transformation_urns=(DBT_URN,)),
        DBT_URN: DatasetSnapshot(urn=DBT_URN, name="order_details (dbt)", definition_changed_at=NOW - timedelta(days=9)),
    }
    model = _model(_feature(), run_completed_at=NOW - timedelta(days=5))

    assert d3.detect(model, datasets, NOW) == []


def test_no_finding_when_no_definition_changed_signal():
    datasets = {
        SNOWFLAKE_URN: DatasetSnapshot(urn=SNOWFLAKE_URN, name="order_details", upstream_transformation_urns=(DBT_URN,)),
        DBT_URN: DatasetSnapshot(urn=DBT_URN, name="order_details (dbt)", definition_changed_at=None),
    }
    model = _model(_feature(), run_completed_at=NOW - timedelta(days=11))

    assert d3.detect(model, datasets, NOW) == []


def test_no_finding_when_no_upstream_transformation():
    datasets = {
        SNOWFLAKE_URN: DatasetSnapshot(urn=SNOWFLAKE_URN, name="order_details", upstream_transformation_urns=()),
    }
    model = _model(_feature(), run_completed_at=NOW - timedelta(days=11))

    assert d3.detect(model, datasets, NOW) == []


def test_dedupes_findings_across_features_sharing_the_same_transform():
    feature_a = Feature(urn="urn:li:mlFeature:(t,a)", name="a", source_dataset_urn=SNOWFLAKE_URN, source_column="discount_percent")
    feature_b = Feature(urn="urn:li:mlFeature:(t,b)", name="b", source_dataset_urn=SNOWFLAKE_URN, source_column="order_total")
    datasets = {
        SNOWFLAKE_URN: DatasetSnapshot(urn=SNOWFLAKE_URN, name="order_details", upstream_transformation_urns=(DBT_URN,)),
        DBT_URN: DatasetSnapshot(urn=DBT_URN, name="order_details (dbt)", definition_changed_at=NOW - timedelta(days=9)),
    }
    model = ModelSnapshot(
        urn="urn:li:mlModel:m", name="m",
        training_runs=(TrainingRun(urn="urn:li:dataProcessInstance:r0", completed_at=NOW - timedelta(days=11), input_dataset_urns=(SNOWFLAKE_URN,)),),
        features=(feature_a, feature_b),
    )

    findings = d3.detect(model, datasets, NOW)

    assert len(findings) == 1
