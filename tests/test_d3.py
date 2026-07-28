from datetime import datetime, timedelta, timezone

from detectors import d3_semantic_drift as d3
from detectors.models import DatasetSnapshot, DetectorStatus, Feature, ModelSnapshot, TrainingRun

NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)
SNOWFLAKE_URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,x.order_details,PROD)"
DBT_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,x.order_details,PROD)"


def _model(features: tuple[Feature, ...], run_days_ago: int | None = 11) -> ModelSnapshot:
    runs = () if run_days_ago is None else (TrainingRun(
        urn="urn:li:dataProcessInstance:r0",
        completed_at=NOW - timedelta(days=run_days_ago),
        input_dataset_urns=(SNOWFLAKE_URN,),
    ),)
    return ModelSnapshot(urn="urn:li:mlModel:m", name="m", training_runs=runs, features=features)


def _feature(name: str = "f", column: str = "discount_percent") -> Feature:
    return Feature(urn=f"urn:li:mlFeature:(t,{name})", name=name,
                    source_dataset_urn=SNOWFLAKE_URN, source_column=column)


def _datasets(definition_changed_days_ago: int | None = 9, with_transform: bool = True) -> dict:
    changed_at = None if definition_changed_days_ago is None else NOW - timedelta(days=definition_changed_days_ago)
    datasets = {
        SNOWFLAKE_URN: DatasetSnapshot(
            urn=SNOWFLAKE_URN, name="order_details",
            upstream_transformation_urns=(DBT_URN,) if with_transform else (),
        ),
    }
    if with_transform:
        datasets[DBT_URN] = DatasetSnapshot(urn=DBT_URN, name="order_details (dbt)",
                                             definition_changed_at=changed_at)
    return datasets


# --- FINDING ---------------------------------------------------------------

def test_finding_when_upstream_definition_changed_after_last_training():
    result = d3.detect(_model((_feature(),)), _datasets(), NOW)

    assert result.status is DetectorStatus.FINDING
    assert result.findings[0].evidence["changed_days"] == 9


def test_finding_deduped_across_features_sharing_the_same_transform():
    model = _model((_feature("a"), _feature("b", column="order_total")))

    result = d3.detect(model, _datasets(), NOW)

    assert result.status is DetectorStatus.FINDING
    assert len(result.findings) == 1


# --- PASS ------------------------------------------------------------------

def test_pass_when_retrained_after_definition_change():
    result = d3.detect(_model((_feature(),), run_days_ago=5), _datasets(), NOW)

    assert result.status is DetectorStatus.PASS


def test_pass_when_no_upstream_transformation_exists():
    # Conclusive, not a gap: there is no transformation whose definition
    # could have drifted, so there is genuinely nothing to find.
    result = d3.detect(_model((_feature(),)), _datasets(with_transform=False), NOW)

    assert result.status is DetectorStatus.PASS
    assert result.checked == 1


# --- INSUFFICIENT_DATA -----------------------------------------------------

def test_insufficient_data_when_transform_has_no_definition_timestamp():
    result = d3.detect(_model((_feature(),)), _datasets(definition_changed_days_ago=None), NOW)

    assert result.status is DetectorStatus.INSUFFICIENT_DATA
    assert [m.missing for m in result.missing] == ["deadreckon.definitionChangedAt"]


def test_insufficient_data_when_transform_dataset_absent_from_graph():
    datasets = {
        SNOWFLAKE_URN: DatasetSnapshot(urn=SNOWFLAKE_URN, name="order_details",
                                        upstream_transformation_urns=(DBT_URN,)),
    }

    result = d3.detect(_model((_feature(),)), datasets, NOW)

    assert result.status is DetectorStatus.INSUFFICIENT_DATA
    assert [m.missing for m in result.missing] == ["dataset"]


def test_insufficient_data_when_model_never_trained():
    result = d3.detect(_model((_feature(),), run_days_ago=None), _datasets(), NOW)

    assert result.status is DetectorStatus.INSUFFICIENT_DATA
    assert [m.missing for m in result.missing] == ["mlModelProperties.trainingJobs"]


def test_insufficient_data_when_model_has_no_features():
    result = d3.detect(_model(()), _datasets(), NOW)

    assert result.status is DetectorStatus.INSUFFICIENT_DATA
    assert [m.missing for m in result.missing] == ["mlModelProperties.mlFeatures"]
