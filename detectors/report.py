"""
Serializes a run into the JSON contract the dashboard consumes.

This module is the single source of truth for that shape - see
docs/output-schema.md, which documents it field by field. Schema version
is declared in the payload so the frontend can fail loudly on a shape it
wasn't built against, rather than silently rendering blanks.

Shaped by a review from the dashboard's author (a different model line,
reviewing as the consumer rather than as a second pair of eyes on our own
work). The changes that came out of it: findings live under the detector
that raised them so the UI never re-derives that join; coverage gaps are
grouped by aspect, matching how the same information is already written to
the graph; every finding carries the lineage path that produced it.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from detectors import d1_frozen_source, d2_schema_drift, d3_semantic_drift
from detectors.models import DatasetSnapshot, DetectorResult, DetectorStatus, Finding, ModelSnapshot
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

SCHEMA_VERSION = "1.0.0"

# Only these two UI routes have been verified to resolve against a live
# DataHub. mlFeature, dataProcessInstance and document routes are NOT
# emitted as URLs: the document entity turned out to have no working
# profile page at all in this version (see NOTES.md), and a link that 404s
# is worse than a bare URN the reader can paste into search.
ROUTE_TEMPLATES = {
    "dataset": "{base}/dataset/{urn}",
    "mlModel": "{base}/mlModels/{urn}",
}

DETECTOR_MODULES = (d1_frozen_source, d2_schema_drift, d3_semantic_drift)


def _entity_type_of(urn: str) -> str | None:
    if urn.startswith("urn:li:dataset:"):
        return "dataset"
    if urn.startswith("urn:li:mlModel:"):
        return "mlModel"
    if urn.startswith("urn:li:mlModelGroup:"):
        return "mlModelGroup"
    if urn.startswith("urn:li:mlFeature:"):
        return "mlFeature"
    if urn.startswith("urn:li:dataProcessInstance:"):
        return "dataProcessInstance"
    return None


def _entity_url(base_url: str, urn: str | None) -> str | None:
    if not urn:
        return None
    template = ROUTE_TEMPLATES.get(_entity_type_of(urn) or "")
    if template is None:
        return None
    # URNs contain ':' '(' ')' ',' - all must be percent-encoded or the UI
    # route won't match (verified against a live instance).
    return template.format(base=base_url, urn=quote(urn, safe=""))


def _short_urn_name(urn: str) -> str:
    """Display name derived from the URN itself - no extra graph call.

    Datasets/models encode the name between the last two commas; process
    instances carry it as the final segment.
    """
    if "," in urn:
        return urn.split(",")[-2]
    return urn.rsplit(":", 1)[-1]


def _node(urn: str, name: str | None, base_url: str, ignition: bool = False) -> dict:
    return {
        "type": _entity_type_of(urn),
        "urn": urn,
        "name": name or _short_urn_name(urn),
        "url": _entity_url(base_url, urn),
        "ignition": ignition,
    }


def _lineage_path(
    finding: Finding,
    model: ModelSnapshot,
    datasets: dict[str, DatasetSnapshot],
    base_url: str,
) -> list[dict]:
    """Upstream-to-downstream path that produced this finding.

    Built entirely from what the detectors already had in hand - the
    finding's own evidence plus the model snapshot - so emitting it costs
    no additional graph queries. Deliberately raw: node identity, a
    display name, and the ignition flag. No edge semantics, no timestamps
    per node, no enrichment; those would need lookups we are not doing.

    D3's path stops at the source dataset rather than naming a feature:
    the detector dedupes by transformation, so one finding can cover
    several features and singling one out would overstate what was found.
    """
    ev = finding.evidence
    feature_names = {f.urn: f.name for f in model.features}

    def dataset_node(urn: str, ignition: bool = False) -> dict:
        snapshot = datasets.get(urn)
        return _node(urn, snapshot.name if snapshot else None, base_url, ignition)

    path: list[dict] = []
    if finding.detector == "D1":
        path.append(dataset_node(ev["dataset_urn"], ignition=True))
    elif finding.detector == "D2":
        path.append(dataset_node(ev["dataset_urn"], ignition=True))
        feature_urn = ev.get("feature_urn")
        if feature_urn:
            path.append(_node(feature_urn, feature_names.get(feature_urn), base_url))
    elif finding.detector == "D3":
        path.append(dataset_node(ev["transformation_dataset_urn"], ignition=True))
        source_urn = ev.get("feature_source_dataset_urn")
        if source_urn:
            path.append(dataset_node(source_urn))

    run_urn = ev.get("latest_training_run_urn")
    if run_urn:
        path.append(_node(run_urn, None, base_url))
    path.append(_node(model.urn, model.name, base_url))
    return path


def _finding_subject_urn(finding: Finding) -> str | None:
    """The entity a finding is *about* - the upstream thing that broke,
    not the model. That is what a reader needs to click through to."""
    for key in ("dataset_urn", "transformation_dataset_urn"):
        if key in finding.evidence:
            return finding.evidence[key]
    return None


def _serialize_finding(
    finding: Finding,
    model: ModelSnapshot,
    datasets: dict[str, DatasetSnapshot],
    base_url: str,
) -> dict:
    subject_urn = _finding_subject_urn(finding)
    return {
        "detector": finding.detector,
        "summary": finding.summary,
        "subject": _finding_subject(finding),
        "subject_urn": subject_urn,
        "subject_url": _entity_url(base_url, subject_urn),
        "evidence": finding.evidence,
        "lineage_path": _lineage_path(finding, model, datasets, base_url),
    }


def _serialize_coverage_gaps(missing, base_url: str) -> list[dict]:
    """Group gaps by the aspect that was absent.

    One aspect missing across four datasets is one thing to go fix, not
    four rows of identical text - and the graph writeback already groups
    it this way, so the two surfaces now agree on shape.
    """
    grouped: dict[str, list[dict]] = {}
    for signal in missing:
        grouped.setdefault(signal.missing, []).append({
            "urn": signal.subject_urn,
            "url": _entity_url(base_url, signal.subject_urn),
            "detail": signal.detail,
        })
    return [{"aspect": aspect, "count": len(subjects), "subjects": subjects}
            for aspect, subjects in grouped.items()]


def _serialize_detector(
    result: DetectorResult,
    model: ModelSnapshot,
    datasets: dict[str, DatasetSnapshot],
    base_url: str,
) -> dict:
    return {
        "status": result.status.value,
        "conclusive": result.is_conclusive,
        "subjects_checked": result.checked,
        "finding_count": len(result.findings),
        "findings": [_serialize_finding(f, model, datasets, base_url) for f in result.findings],
        "coverage_gaps": _serialize_coverage_gaps(result.missing, base_url),
    }


def serialize_model(
    model: ModelSnapshot,
    results: list[DetectorResult],
    risk: ModelRiskScore,
    datasets: dict[str, DatasetSnapshot],
    base_url: str,
) -> dict:
    by_detector = {r.detector: r for r in results}
    coverage = risk.coverage
    return {
        "urn": model.urn,
        "name": model.name,
        "url": _entity_url(base_url, model.urn),
        "group": {
            "urn": model.group_urn,
            "name": model.group_name,
            "url": _entity_url(base_url, model.group_urn),
        },
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
        "detectors": {name: _serialize_detector(by_detector[name], model, datasets, base_url)
                      for name in sorted(by_detector)},
        "tags": {
            "at_risk": is_at_risk(risk.severity),
            "unassessable": coverage.is_unassessable,
        },
        "assessment_document_urn": f"urn:li:document:{_document_id_for(model)}",
    }


def _detectors_meta() -> dict:
    return {
        module.DETECTOR: {
            "title": module.TITLE,
            "description": module.DESCRIPTION,
            "weight": DETECTOR_WEIGHTS[module.DETECTOR],
        }
        for module in DETECTOR_MODULES
    }


def build_report(
    scored: list[tuple[ModelSnapshot, list[DetectorResult], ModelRiskScore]],
    now: datetime,
    base_url: str,
    datasets: dict[str, DatasetSnapshot],
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
            "datasets_examined": len(datasets),
            "detectors": sorted(DETECTOR_WEIGHTS),
        },
        "detectors_meta": _detectors_meta(),
        "scoring": {
            "max_possible_score": MAX_POSSIBLE_SCORE,
            "detector_weights": dict(DETECTOR_WEIGHTS),
            "environment_weights": dict(ENVIRONMENT_WEIGHTS),
            "latent_risk_floor": LATENT_RISK_FLOOR,
            "severity_thresholds": dict(SEVERITY_THRESHOLDS),
            "statuses": [s.value for s in DetectorStatus],
        },
        "models": [serialize_model(model, results, risk, datasets, base_url)
                   for model, results, risk in scored],
    }
