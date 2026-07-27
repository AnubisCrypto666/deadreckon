from datetime import datetime, timezone

from datahub.metadata.schema_classes import AuditStampClass, InstitutionalMemoryClass, InstitutionalMemoryMetadataClass

from detectors.models import Finding
from detectors.scoring import ModelRiskScore
from detectors.writeback import (
    DEADRECKON_MEMORY_MARKER,
    MAX_INSTITUTIONAL_MEMORY_FINDING_ROWS,
    _build_finding_memory_descriptions,
    _finding_subject,
    _set_institutional_memory_entries,
    _short_dataset_name,
)

DATASET_URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.order_entry.customers,PROD)"
TRANSFORM_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,b2fd91.ORDER_ENTRY_DB.analytics.order_details,PROD)"
MODEL_URN = "urn:li:mlModel:m"
NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)


class FakeGraph:
    """Minimal test double for the two DataHubGraph calls writeback.py
    makes (get_aspect/emit) - lets the merge/replace logic in
    _set_institutional_memory_entries be tested without a live DataHub."""

    def __init__(self):
        self._aspects: dict = {}

    def get_aspect(self, entity_urn, aspect_type):
        return self._aspects.get((entity_urn, aspect_type))

    def emit(self, mcp):
        self._aspects[(mcp.entityUrn, type(mcp.aspect))] = mcp.aspect


def _finding(detector: str) -> Finding:
    return Finding(detector=detector, model_urn=MODEL_URN, summary=f"{detector} prose",
                    evidence={"dataset_urn": DATASET_URN, "frozen_days": 1, "missing_days": 1,
                              "source_column": "x", "transformation_dataset_urn": TRANSFORM_URN,
                              "changed_days": 1})


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


def _deadreckon_elements(graph: FakeGraph) -> list:
    im = graph.get_aspect(entity_urn=MODEL_URN, aspect_type=InstitutionalMemoryClass)
    return [e for e in im.elements if e.description.startswith(DEADRECKON_MEMORY_MARKER)]


def test_institutional_memory_entry_count_tracks_finding_count_3_to_1_to_3():
    graph = FakeGraph()
    url = "http://localhost:9002/search?query=undertow%3Aat-risk"

    # 3 findings -> 3 rows (+1 overview row = 4 total).
    descriptions_3 = [f"{DEADRECKON_MEMORY_MARKER} row {i}" for i in range(4)]
    _set_institutional_memory_entries(graph, MODEL_URN, url, descriptions_3, NOW)
    assert len(_deadreckon_elements(graph)) == 4

    # Data changes, model now has only 1 finding -> 1 row (+1 overview = 2).
    # The stale rows from the 3-finding run must be gone, not just added to.
    descriptions_1 = [f"{DEADRECKON_MEMORY_MARKER} row {i}" for i in range(2)]
    _set_institutional_memory_entries(graph, MODEL_URN, url, descriptions_1, NOW)
    elements = _deadreckon_elements(graph)
    assert len(elements) == 2
    assert {e.description for e in elements} == set(descriptions_1)

    # Back to 3 findings -> back to 4 rows, not 6 (2 old + 4 new).
    _set_institutional_memory_entries(graph, MODEL_URN, url, descriptions_3, NOW)
    elements = _deadreckon_elements(graph)
    assert len(elements) == 4
    assert {e.description for e in elements} == set(descriptions_3)


def test_institutional_memory_preserves_non_deadreckon_elements():
    graph = FakeGraph()
    someone_elses_link = InstitutionalMemoryMetadataClass(
        url="https://wiki.example.com/runbook",
        description="Team runbook - not ours",
        createStamp=AuditStampClass(time=0, actor="urn:li:corpuser:someone_else"),
    )
    graph._aspects[(MODEL_URN, InstitutionalMemoryClass)] = InstitutionalMemoryClass(elements=[someone_elses_link])

    url = "http://localhost:9002/search?query=undertow%3Aat-risk"
    _set_institutional_memory_entries(graph, MODEL_URN, url, [f"{DEADRECKON_MEMORY_MARKER} row"], NOW)

    im = graph.get_aspect(entity_urn=MODEL_URN, aspect_type=InstitutionalMemoryClass)
    descriptions = {e.description for e in im.elements}
    assert "Team runbook - not ours" in descriptions
    assert f"{DEADRECKON_MEMORY_MARKER} row" in descriptions
    assert len(im.elements) == 2


def _risk_with_n_findings(n: int) -> ModelRiskScore:
    findings = tuple(_finding("D1") for _ in range(n))
    return ModelRiskScore(model_urn=MODEL_URN, findings=findings, blast_radius=3.0, score=2.4, severity="HIGH")


def test_finding_rows_capped_with_summary_row_when_over_limit():
    risk = _risk_with_n_findings(MAX_INSTITUTIONAL_MEMORY_FINDING_ROWS + 2)
    rows = _build_finding_memory_descriptions(risk)

    # 1 overview + MAX detail rows + 1 "more" row.
    assert len(rows) == 1 + MAX_INSTITUTIONAL_MEMORY_FINDING_ROWS + 1
    assert "+2 more" in rows[-1]


def test_finding_rows_no_summary_row_when_under_limit():
    risk = _risk_with_n_findings(2)
    rows = _build_finding_memory_descriptions(risk)

    # 1 overview + 2 detail rows, no "more" row.
    assert len(rows) == 3
    assert not any("more" in r for r in rows)


def test_finding_rows_exactly_at_limit_has_no_summary_row():
    risk = _risk_with_n_findings(MAX_INSTITUTIONAL_MEMORY_FINDING_ROWS)
    rows = _build_finding_memory_descriptions(risk)

    assert len(rows) == 1 + MAX_INSTITUTIONAL_MEMORY_FINDING_ROWS
    assert not any("more" in r for r in rows)
