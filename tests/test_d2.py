from datetime import datetime, timedelta, timezone

from detectors import d2_schema_drift as d2
from detectors.models import DatasetSnapshot, Feature, ModelSnapshot, TrainingRun

NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)
SOURCE_URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,x.customers,PROD)"


def _model(feature: Feature, run_completed_at: datetime) -> ModelSnapshot:
    return ModelSnapshot(
        urn="urn:li:mlModel:m",
        name="m",
        training_runs=(TrainingRun(urn="urn:li:dataProcessInstance:r0", completed_at=run_completed_at, input_dataset_urns=(SOURCE_URN,)),),
        features=(feature,),
    )


def test_fires_when_column_removed_after_last_training():
    feature = Feature(urn="urn:li:mlFeature:(t,f)", name="f", source_dataset_urn=SOURCE_URN, source_column="credit_limit")
    datasets = {
        SOURCE_URN: DatasetSnapshot(
            urn=SOURCE_URN, name="customers",
            current_columns=frozenset({"credit_limit_usd", "customer_id"}),
            schema_changed_at=NOW - timedelta(days=3),
        ),
    }
    model = _model(feature, run_completed_at=NOW - timedelta(days=5))

    findings = d2.detect(model, datasets, NOW)

    assert len(findings) == 1
    assert findings[0].detector == "D2"
    assert findings[0].evidence["missing_days"] == 3


def test_no_finding_when_column_still_present():
    feature = Feature(urn="urn:li:mlFeature:(t,f)", name="f", source_dataset_urn=SOURCE_URN, source_column="credit_limit")
    datasets = {
        SOURCE_URN: DatasetSnapshot(
            urn=SOURCE_URN, name="customers",
            current_columns=frozenset({"credit_limit", "customer_id"}),
            schema_changed_at=NOW - timedelta(days=3),
        ),
    }
    model = _model(feature, run_completed_at=NOW - timedelta(days=5))

    assert d2.detect(model, datasets, NOW) == []


def test_no_finding_when_retrained_after_schema_change():
    feature = Feature(urn="urn:li:mlFeature:(t,f)", name="f", source_dataset_urn=SOURCE_URN, source_column="credit_limit")
    datasets = {
        SOURCE_URN: DatasetSnapshot(
            urn=SOURCE_URN, name="customers",
            current_columns=frozenset({"credit_limit_usd"}),
            schema_changed_at=NOW - timedelta(days=10),
        ),
    }
    model = _model(feature, run_completed_at=NOW - timedelta(days=2))

    assert d2.detect(model, datasets, NOW) == []


def test_no_finding_when_no_schema_changed_signal():
    feature = Feature(urn="urn:li:mlFeature:(t,f)", name="f", source_dataset_urn=SOURCE_URN, source_column="credit_limit")
    datasets = {
        SOURCE_URN: DatasetSnapshot(
            urn=SOURCE_URN, name="customers",
            current_columns=frozenset({"credit_limit_usd"}),
            schema_changed_at=None,
        ),
    }
    model = _model(feature, run_completed_at=NOW - timedelta(days=5))

    assert d2.detect(model, datasets, NOW) == []


def test_no_finding_when_feature_has_no_source_column():
    feature = Feature(urn="urn:li:mlFeature:(t,f)", name="f", source_dataset_urn=SOURCE_URN, source_column=None)
    datasets = {
        SOURCE_URN: DatasetSnapshot(
            urn=SOURCE_URN, name="customers",
            current_columns=frozenset(),
            schema_changed_at=NOW - timedelta(days=3),
        ),
    }
    model = _model(feature, run_completed_at=NOW - timedelta(days=5))

    assert d2.detect(model, datasets, NOW) == []
