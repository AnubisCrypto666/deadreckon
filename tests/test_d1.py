from datetime import datetime, timedelta, timezone

from detectors import d1_frozen_source as d1
from detectors.models import DatasetSnapshot, DetectorStatus, ModelSnapshot, TrainingRun

NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)
SOURCE_URN = "urn:li:dataset:(urn:li:dataPlatform:sqlite,x.raw,PROD)"


def _model(runs: list[TrainingRun]) -> ModelSnapshot:
    return ModelSnapshot(urn="urn:li:mlModel:m", name="m", training_runs=tuple(runs), features=())


def _run(days_ago: int, inputs=(SOURCE_URN,)) -> TrainingRun:
    return TrainingRun(urn=f"urn:li:dataProcessInstance:r{days_ago}",
                       completed_at=NOW - timedelta(days=days_ago), input_dataset_urns=inputs)


# --- FINDING ---------------------------------------------------------------

def test_finding_when_source_frozen_past_threshold_and_training_continues():
    frozen_dataset = {
        SOURCE_URN: DatasetSnapshot(urn=SOURCE_URN, name="raw", last_updated=NOW - timedelta(days=12)),
    }
    model = _model([_run(0), _run(1)])

    result = d1.detect(model, frozen_dataset, NOW)

    assert result.status is DetectorStatus.FINDING
    assert len(result.findings) == 1
    assert result.findings[0].evidence["frozen_days"] == 12


# --- PASS ------------------------------------------------------------------

def test_pass_when_dataset_still_fresh():
    fresh_dataset = {
        SOURCE_URN: DatasetSnapshot(urn=SOURCE_URN, name="raw", last_updated=NOW - timedelta(hours=6)),
    }

    result = d1.detect(_model([_run(0)]), fresh_dataset, NOW)

    assert result.status is DetectorStatus.PASS
    assert result.findings == ()
    assert result.checked == 1


def test_pass_when_training_predates_the_freeze():
    frozen_dataset = {
        SOURCE_URN: DatasetSnapshot(urn=SOURCE_URN, name="raw", last_updated=NOW - timedelta(days=12)),
    }
    # The only training run happened before the dataset went stale, so
    # nothing was frozen from the model's point of view - conclusively OK.
    result = d1.detect(_model([_run(20)]), frozen_dataset, NOW)

    assert result.status is DetectorStatus.PASS


# --- INSUFFICIENT_DATA -----------------------------------------------------

def test_insufficient_data_when_no_operation_aspect():
    unknown_dataset = {
        SOURCE_URN: DatasetSnapshot(urn=SOURCE_URN, name="raw", last_updated=None),
    }

    result = d1.detect(_model([_run(0)]), unknown_dataset, NOW)

    assert result.status is DetectorStatus.INSUFFICIENT_DATA
    assert result.findings == ()
    assert [m.missing for m in result.missing] == ["operation.lastUpdatedTimestamp"]


def test_insufficient_data_when_model_never_trained():
    result = d1.detect(_model([]), {}, NOW)

    assert result.status is DetectorStatus.INSUFFICIENT_DATA
    assert [m.missing for m in result.missing] == ["mlModelProperties.trainingJobs"]


def test_insufficient_data_when_runs_declare_no_inputs():
    result = d1.detect(_model([_run(0, inputs=())]), {}, NOW)

    assert result.status is DetectorStatus.INSUFFICIENT_DATA
    assert [m.missing for m in result.missing] == ["dataProcessInstanceInput.inputs"]


def test_insufficient_data_when_input_dataset_absent_from_graph():
    result = d1.detect(_model([_run(0)]), {}, NOW)

    assert result.status is DetectorStatus.INSUFFICIENT_DATA
    assert [m.missing for m in result.missing] == ["dataset"]


# --- mixed -----------------------------------------------------------------

def test_finding_wins_over_a_partial_gap():
    other_urn = "urn:li:dataset:(urn:li:dataPlatform:sqlite,x.other,PROD)"
    datasets = {
        SOURCE_URN: DatasetSnapshot(urn=SOURCE_URN, name="raw", last_updated=NOW - timedelta(days=12)),
        other_urn: DatasetSnapshot(urn=other_urn, name="other", last_updated=None),
    }
    model = _model([_run(0, inputs=(SOURCE_URN, other_urn))])

    result = d1.detect(model, datasets, NOW)

    # A real finding is the headline even though one input was uncheckable,
    # but the gap is still reported so coverage stays honest.
    assert result.status is DetectorStatus.FINDING
    assert len(result.findings) == 1
    assert len(result.missing) == 1


def test_clean_check_plus_gap_is_not_reported_as_pass():
    other_urn = "urn:li:dataset:(urn:li:dataPlatform:sqlite,x.other,PROD)"
    datasets = {
        SOURCE_URN: DatasetSnapshot(urn=SOURCE_URN, name="raw", last_updated=NOW - timedelta(hours=1)),
        other_urn: DatasetSnapshot(urn=other_urn, name="other", last_updated=None),
    }
    model = _model([_run(0, inputs=(SOURCE_URN, other_urn))])

    result = d1.detect(model, datasets, NOW)

    # One input verified fresh, one unmeasurable - claiming PASS here would
    # assert something about a dataset we never actually looked at.
    assert result.status is DetectorStatus.INSUFFICIENT_DATA
    assert result.checked == 1
