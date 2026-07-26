from datetime import datetime, timedelta, timezone

from detectors import d1_frozen_source as d1
from detectors.models import DatasetSnapshot, ModelSnapshot, TrainingRun

NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)
SOURCE_URN = "urn:li:dataset:(urn:li:dataPlatform:sqlite,x.raw,PROD)"


def _model(runs: list[TrainingRun]) -> ModelSnapshot:
    return ModelSnapshot(urn="urn:li:mlModel:m", name="m", training_runs=tuple(runs), features=())


def test_fires_when_source_frozen_past_threshold_and_training_continues():
    frozen_dataset = {
        SOURCE_URN: DatasetSnapshot(urn=SOURCE_URN, name="raw", last_updated=NOW - timedelta(days=12)),
    }
    model = _model([
        TrainingRun(urn="urn:li:dataProcessInstance:r0", completed_at=NOW, input_dataset_urns=(SOURCE_URN,)),
        TrainingRun(urn="urn:li:dataProcessInstance:r1", completed_at=NOW - timedelta(days=1), input_dataset_urns=(SOURCE_URN,)),
    ])

    findings = d1.detect(model, frozen_dataset, NOW)

    assert len(findings) == 1
    assert findings[0].detector == "D1"
    assert findings[0].evidence["frozen_days"] == 12


def test_no_finding_when_dataset_still_fresh():
    fresh_dataset = {
        SOURCE_URN: DatasetSnapshot(urn=SOURCE_URN, name="raw", last_updated=NOW - timedelta(hours=6)),
    }
    model = _model([
        TrainingRun(urn="urn:li:dataProcessInstance:r0", completed_at=NOW, input_dataset_urns=(SOURCE_URN,)),
    ])

    assert d1.detect(model, fresh_dataset, NOW) == []


def test_no_finding_when_no_operation_signal_at_all():
    unknown_dataset = {
        SOURCE_URN: DatasetSnapshot(urn=SOURCE_URN, name="raw", last_updated=None),
    }
    model = _model([
        TrainingRun(urn="urn:li:dataProcessInstance:r0", completed_at=NOW, input_dataset_urns=(SOURCE_URN,)),
    ])

    assert d1.detect(model, unknown_dataset, NOW) == []


def test_no_finding_when_training_predates_the_freeze():
    frozen_dataset = {
        SOURCE_URN: DatasetSnapshot(urn=SOURCE_URN, name="raw", last_updated=NOW - timedelta(days=12)),
    }
    # The one and only training run happened before the dataset went
    # stale from *today's* vantage point - nothing was frozen from the
    # model's perspective at training time.
    model = _model([
        TrainingRun(
            urn="urn:li:dataProcessInstance:r0",
            completed_at=NOW - timedelta(days=20),
            input_dataset_urns=(SOURCE_URN,),
        ),
    ])

    assert d1.detect(model, frozen_dataset, NOW) == []


def test_no_finding_when_model_never_trained():
    model = _model([])
    assert d1.detect(model, {}, NOW) == []
