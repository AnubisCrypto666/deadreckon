from detectors.models import Finding
from detectors.writeback import _finding_subject, _short_dataset_name

DATASET_URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.order_entry.customers,PROD)"
TRANSFORM_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,b2fd91.ORDER_ENTRY_DB.analytics.order_details,PROD)"


def test_short_dataset_name_strips_platform_and_env():
    assert _short_dataset_name(DATASET_URN) == "b2fd91.order_entry_db.order_entry.customers"


def test_short_dataset_name_handles_urn_without_commas():
    assert _short_dataset_name("not-a-urn") == "not-a-urn"


def test_d1_subject_is_compact_and_uses_evidence_not_prose():
    finding = Finding(
        detector="D1", model_urn="urn:li:mlModel:m", summary="a very long prose summary " * 5,
        evidence={"dataset_urn": DATASET_URN, "frozen_days": 12},
    )
    subject = _finding_subject(finding)
    assert subject == "b2fd91.order_entry_db.order_entry.customers frozen 12d"
    assert len(subject) < 80


def test_d2_subject_includes_column_and_missing_days():
    finding = Finding(
        detector="D2", model_urn="urn:li:mlModel:m", summary="prose",
        evidence={"dataset_urn": DATASET_URN, "source_column": "credit_limit", "missing_days": 3},
    )
    subject = _finding_subject(finding)
    assert subject == "b2fd91.order_entry_db.order_entry.customers.credit_limit missing 3d"


def test_d3_subject_uses_transformation_dataset():
    finding = Finding(
        detector="D3", model_urn="urn:li:mlModel:m", summary="prose",
        evidence={"transformation_dataset_urn": TRANSFORM_URN, "changed_days": 9},
    )
    subject = _finding_subject(finding)
    assert subject == "b2fd91.ORDER_ENTRY_DB.analytics.order_details logic changed 9d ago"


def test_falls_back_to_summary_when_expected_evidence_is_missing():
    finding = Finding(detector="D1", model_urn="urn:li:mlModel:m", summary="fallback prose", evidence={})
    assert _finding_subject(finding) == "fallback prose"


def test_headline_prefix_survives_within_120_chars_even_for_long_dataset_names():
    long_urn = (
        "urn:li:dataset:(urn:li:dataPlatform:snowflake,"
        "some.extremely.long.database.schema.qualified.table.name.that.goes.on,PROD)"
    )
    finding = Finding(
        detector="D2", model_urn="urn:li:mlModel:m", summary="prose",
        evidence={"dataset_urn": long_urn, "source_column": "credit_limit", "missing_days": 3},
    )
    headline = f"[deadreckon] HIGH risk=3.0 | {finding.detector}: {_finding_subject(finding)}"
    prefix = headline[:35]
    assert "HIGH" in prefix
    assert "3.0" in prefix
    assert "D2" in prefix
