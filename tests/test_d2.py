from datetime import datetime, timedelta, timezone

from detectors import d2_schema_drift as d2
from detectors.models import DatasetSnapshot, DetectorStatus, Feature, ModelSnapshot, TrainingRun

NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)
SOURCE_URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,x.customers,PROD)"


def _model(feature: Feature | None, run_days_ago: int | None = 5) -> ModelSnapshot:
    runs = () if run_days_ago is None else (TrainingRun(
        urn="urn:li:dataProcessInstance:r0",
        completed_at=NOW - timedelta(days=run_days_ago),
        input_dataset_urns=(SOURCE_URN,),
    ),)
    return ModelSnapshot(urn="urn:li:mlModel:m", name="m", training_runs=runs,
                          features=() if feature is None else (feature,))


def _feature(source_column: str | None = "credit_limit") -> Feature:
    return Feature(urn="urn:li:mlFeature:(t,f)", name="f",
                    source_dataset_urn=SOURCE_URN, source_column=source_column)


# --- FINDING ---------------------------------------------------------------

def test_finding_when_column_removed_after_last_training():
    datasets = {
        SOURCE_URN: DatasetSnapshot(
            urn=SOURCE_URN, name="customers",
            current_columns=frozenset({"credit_limit_usd", "customer_id"}),
            schema_changed_at=NOW - timedelta(days=3),
        ),
    }

    result = d2.detect(_model(_feature()), datasets, NOW)

    assert result.status is DetectorStatus.FINDING
    assert result.findings[0].evidence["missing_days"] == 3


# --- PASS ------------------------------------------------------------------

def test_pass_when_column_still_present():
    datasets = {
        SOURCE_URN: DatasetSnapshot(
            urn=SOURCE_URN, name="customers",
            current_columns=frozenset({"credit_limit", "customer_id"}),
            schema_changed_at=NOW - timedelta(days=3),
        ),
    }

    result = d2.detect(_model(_feature()), datasets, NOW)

    assert result.status is DetectorStatus.PASS
    assert result.checked == 1


def test_pass_when_column_present_even_without_schema_change_timestamp():
    # A present column is conclusive on its own - the change timestamp is
    # only needed to adjudicate a column that is actually gone.
    datasets = {
        SOURCE_URN: DatasetSnapshot(
            urn=SOURCE_URN, name="customers",
            current_columns=frozenset({"credit_limit"}),
            schema_changed_at=None,
        ),
    }

    result = d2.detect(_model(_feature()), datasets, NOW)

    assert result.status is DetectorStatus.PASS


def test_pass_when_retrained_after_schema_change():
    datasets = {
        SOURCE_URN: DatasetSnapshot(
            urn=SOURCE_URN, name="customers",
            current_columns=frozenset({"credit_limit_usd"}),
            schema_changed_at=NOW - timedelta(days=10),
        ),
    }

    result = d2.detect(_model(_feature(), run_days_ago=2), datasets, NOW)

    assert result.status is DetectorStatus.PASS


# --- INSUFFICIENT_DATA -----------------------------------------------------

def test_insufficient_data_when_column_missing_but_no_schema_change_timestamp():
    datasets = {
        SOURCE_URN: DatasetSnapshot(
            urn=SOURCE_URN, name="customers",
            current_columns=frozenset({"credit_limit_usd"}),
            schema_changed_at=None,
        ),
    }

    result = d2.detect(_model(_feature()), datasets, NOW)

    assert result.status is DetectorStatus.INSUFFICIENT_DATA
    assert [m.missing for m in result.missing] == ["deadreckon.schemaChangedAt"]


def test_insufficient_data_when_feature_has_no_source_column():
    datasets = {
        SOURCE_URN: DatasetSnapshot(urn=SOURCE_URN, name="customers",
                                     current_columns=frozenset({"a"}),
                                     schema_changed_at=NOW - timedelta(days=3)),
    }

    result = d2.detect(_model(_feature(source_column=None)), datasets, NOW)

    assert result.status is DetectorStatus.INSUFFICIENT_DATA
    assert [m.missing for m in result.missing] == ["mlFeatureProperties.description[Source column]"]


def test_insufficient_data_when_dataset_has_no_schema():
    datasets = {
        SOURCE_URN: DatasetSnapshot(urn=SOURCE_URN, name="customers", current_columns=frozenset()),
    }

    result = d2.detect(_model(_feature()), datasets, NOW)

    assert result.status is DetectorStatus.INSUFFICIENT_DATA
    assert [m.missing for m in result.missing] == ["schemaMetadata.fields"]


def test_insufficient_data_when_model_never_trained():
    result = d2.detect(_model(_feature(), run_days_ago=None), {}, NOW)

    assert result.status is DetectorStatus.INSUFFICIENT_DATA
    assert [m.missing for m in result.missing] == ["mlModelProperties.trainingJobs"]


def test_insufficient_data_when_model_has_no_features():
    result = d2.detect(_model(None), {}, NOW)

    assert result.status is DetectorStatus.INSUFFICIENT_DATA
    assert [m.missing for m in result.missing] == ["mlModelProperties.mlFeatures"]
