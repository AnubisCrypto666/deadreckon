"""
Serializes a run into the JSON contract the dashboard consumes.

This module is the single source of truth for that shape - see
docs/output-schema.md, which documents it field by field. Schema version
is declared in the payload so the frontend can fail loudly on a shape it
wasn't built against, rather than silently rendering blanks.

DRAFT (v0): not frozen. Field names and nesting may still change until
the dashboard author has reviewed it.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from detectors.models import DetectorResult, DetectorStatus, Finding, ModelSnapshot
from detectors.scoring import (
    DETECTOR_WEIGHTS,
    ENVIRONMENT_WEIGHTS,
    LATENT_RISK_FLOOR,
    MAX_POSSIBLE_SCORE,
    SEVERITY_THRESHOLDS,
    ModelRiskScore,
    is_at_risk,
)
from detectors.writeback import _document_id_for, _finding_subject

SCHEMA_VERSION = "0.1.0-draft"

DATASET_URL_TEMPLATE = "{base}/dataset/{urn}"
MODEL_URL_TEMPLATE = "{base}/mlModels/{urn}"


def _entity_url(base_url: str, urn: str) -> str | None:
    """Best-effort deep link into the DataHub UI.

    Only dataset and mlModel routes are emitted, both verified to resolve.
    Document entities deliberately get no URL: they have no working
    profile route in this DataHub version (see NOTES.md), and a link that
    404s is worse than no link.
    """
    # URNs contain ':' '(' ')' ',' - all of which have to be percent-encoded
    # or the UI route won't match (verified against a live instance).
    encoded = quote(urn, safe="")
    if urn.startswith("urn:li:dataset:"):
        return DATASET_URL_TEMPLATE.format(base=base_url, urn=encoded)
    if urn.startswith("urn:li:mlModel:"):
        return MODEL_URL_TEMPLATE.format(base=base_url, urn=encoded)
    return None


def _finding_subject_urn(finding: Finding) -> str | None:
    """The entity a finding is *about* - the upstream thing that broke,
    not the model. That is what a reader needs to click through to."""
    ev = finding.evidence
    for key in ("dataset_urn", "transformation_dataset_urn"):
        if key in ev:
            return ev[key]
    return None


def _serialize_finding(finding: Finding, base_url: str) -> dict:
    subject_urn = _finding_subject_urn(finding)
    return {
        "detector": finding.detector,
        "summary": finding.summary,
        "subject": _finding_subject(finding),
        "subject_urn": subject_urn,
        "subject_url": _entity_url(base_url, subject_urn) if subject_urn else None,
        "evidence": finding.evidence,
    }


def _serialize_missing(signal, base_url: str) -> dict:
    return {
        "missing": signal.missing,
        "subject_urn": signal.subject_urn,
        "subject_url": _entity_url(base_url, signal.subject_urn),
        "detail": signal.detail,
    }


def _serialize_detector(result: DetectorResult, base_url: str) -> dict:
    return {
        "status": result.status.value,
        "conclusive": result.is_conclusive,
        "subjects_checked": result.checked,
        "finding_count": len(result.findings),
        "missing": [_serialize_missing(m, base_url) for m in result.missing],
    }


def serialize_model(
    model: ModelSnapshot,
    results: list[DetectorResult],
    risk: ModelRiskScore,
    base_url: str,
) -> dict:
    by_detector = {r.detector: r for r in results}
    coverage = risk.coverage
    return {
        "urn": model.urn,
        "name": model.name,
        "url": _entity_url(base_url, model.urn),
        "group": {"urn": model.group_urn, "name": model.group_name},
        "serving_stages": list(model.deployment_environments),
        "score": risk.score,
        "severity": risk.severity,
        "blast_radius": risk.blast_radius,
        "finding_count": risk.finding_count,
        "coverage": {
            "conclusive": coverage.conclusive,
            "total": coverage.total,
            "label": str(coverage),
            "fully_covered": coverage.is_fully_covered,
            "unassessable": coverage.is_unassessable,
        },
        "detectors": {name: _serialize_detector(by_detector[name], base_url)
                      for name in sorted(by_detector)},
        "findings": [_serialize_finding(f, base_url) for f in risk.findings],
        "tags": {
            "at_risk": is_at_risk(risk.severity),
            "unassessable": coverage.is_unassessable,
        },
        "assessment_document_urn": f"urn:li:document:{_document_id_for(model)}",
    }


def build_report(
    scored: list[tuple[ModelSnapshot, list[DetectorResult], ModelRiskScore]],
    now: datetime,
    base_url: str,
    dataset_count: int,
    clock_overridden: bool,
) -> dict:
    """Full run payload. `scored` must already be in ranked order - the
    dashboard renders `models` as-is rather than re-sorting, so ranking
    stays a single decision made here (see ModelRiskScore.sort_key)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "assessed_at": now.isoformat(),
            "clock_overridden": clock_overridden,
            "datahub_base_url": base_url,
            "models_assessed": len(scored),
            "datasets_examined": dataset_count,
            "detectors": sorted(DETECTOR_WEIGHTS),
        },
        "scoring": {
            "max_possible_score": MAX_POSSIBLE_SCORE,
            "detector_weights": dict(DETECTOR_WEIGHTS),
            "environment_weights": dict(ENVIRONMENT_WEIGHTS),
            "latent_risk_floor": LATENT_RISK_FLOOR,
            "severity_thresholds": dict(SEVERITY_THRESHOLDS),
            "statuses": [s.value for s in DetectorStatus],
        },
        "models": [serialize_model(model, results, risk, base_url)
                   for model, results, risk in scored],
    }
