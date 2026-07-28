"""
Writes risk assessment results back into the graph, next to the model
they concern (plan-pracy-undertow.md Sec.5):

1. A "Model Risk Assessment" document (via the `createDocument`/
   `updateDocumentContents` GraphQL mutations - the same mutations behind
   mcp-server-datahub's `save_document` tool, called directly here so the
   pipeline runs headlessly; see NOTES.md for how this was found and
   verified, including that `deleteDocument` exists and is a soft delete,
   same semantics as `datahub delete --soft`).
2. `deadreckon.riskScore` / `deadreckon.lastAssessedAt` structured
   properties on the model - written for every model with at least one
   finding, regardless of severity, since these back the sorted risk
   table (spec Sec.2's "tablica ryzyka: modele posortowane wg wagi").
3. The `undertow:at-risk` tag - applied only when
   `scoring.is_at_risk(risk.severity)` is true (MEDIUM/HIGH), and
   *removed* otherwise. This is deliberately separate from (2): every
   assessed model gets its score recorded, but the tag is reserved for
   models actually worth a visual flag in the UI, not every model that
   merely has a finding. Removing it when a model drops below threshold
   (e.g. its findings clear on a later run) keeps the tag meaning
   "currently at risk", not "was ever flagged".
4. One `institutionalMemory` entry per finding (the aspect behind the
   classic "Documentation"/"Links" tab), capped at
   `MAX_INSTITUTIONAL_MEMORY_FINDING_ROWS` with a "(+N more)" summary row
   beyond that, plus one overview row - this exists because
   `relatedAssets`/`relatedDocuments` (used for (1)) is a different,
   newer relationship than `institutionalMemory`: a document attached
   only via `relatedAssets` does not show up on the model's Documentation
   tab in this DataHub version (verified: `MLModel`'s GraphQL type has
   both `institutionalMemory` and `relatedDocuments` as separate fields).
   Confirmed empirically that the standalone Document entity has *no*
   working profile route in this DataHub version at all - neither a
   direct URL guess nor the UI's own "Resources" card for it resolves to
   anything (both 404) - so these entries' `description`s (not their
   shared `url`, which points at the at-risk search list instead) are
   what actually carry the reasoning, one finding per row rather than one
   entry with a "(+N more)" tail hiding everything past the first
   finding. Every run replaces the *entire* set of `[deadreckon]`-marked
   elements rather than updating them in place, so a model going from N
   findings to M findings never leaves stale rows behind - see NOTES.md.

GlobalTags and StructuredProperties emissions are full-aspect replacements,
not merges (the same gotcha documented for the upstream nyc-taxi fixture in
NOTES.md) - every write here reads the current aspect first and merges in
place, so it never clobbers `deadreckon.deploymentEnvironment` or any tag
that isn't ours.
"""

from __future__ import annotations

from datetime import datetime

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.graph.client import DataHubGraph
from datahub.metadata.schema_classes import (
    AuditStampClass,
    GlobalTagsClass,
    InstitutionalMemoryClass,
    InstitutionalMemoryMetadataClass,
    PropertyCardinalityClass,
    StructuredPropertiesClass,
    StructuredPropertyDefinitionClass,
    StructuredPropertyValueAssignmentClass,
    TagAssociationClass,
    TagPropertiesClass,
)

from detectors.models import Finding, ModelSnapshot
from detectors.scoring import MAX_POSSIBLE_SCORE, ModelRiskScore, is_at_risk

AT_RISK_TAG_URN = "urn:li:tag:undertow:at-risk"
UNASSESSABLE_TAG_URN = "urn:li:tag:undertow:unassessable"
RISK_SCORE_PROPERTY_URN = "urn:li:structuredProperty:deadreckon.riskScore"
LAST_ASSESSED_AT_PROPERTY_URN = "urn:li:structuredProperty:deadreckon.lastAssessedAt"
FINDING_COUNT_PROPERTY_URN = "urn:li:structuredProperty:deadreckon.findingCount"
ASSESSMENT_COVERAGE_PROPERTY_URN = "urn:li:structuredProperty:deadreckon.assessmentCoverage"
WRITEBACK_ACTOR_URN = "urn:li:corpuser:datahub"

# Document entities have no working profile route in this DataHub version
# (confirmed 404, both a direct guess and the UI's own "Resources" card -
# see NOTES.md), so institutionalMemory links point at the at-risk search
# list instead, and the *description* (not the link) carries the summary.
FRONTEND_BASE_URL = "http://localhost:9002"


def ensure_writeback_definitions(graph: DataHubGraph) -> None:
    graph.emit(MetadataChangeProposalWrapper(
        entityUrn=AT_RISK_TAG_URN,
        aspect=TagPropertiesClass(
            name="undertow:at-risk",
            description="Flagged by deadreckon: at least one silent-failure detector (D1-D3) fired for this model.",
        ),
    ))
    graph.emit(MetadataChangeProposalWrapper(
        entityUrn=RISK_SCORE_PROPERTY_URN,
        aspect=StructuredPropertyDefinitionClass(
            qualifiedName="deadreckon.riskScore",
            displayName="Undertow Risk Score",
            description=(
                f"detector weight x blast radius, from the most recent deadreckon run. "
                f"Range: 0 to {MAX_POSSIBLE_SCORE} (not a 0-1 normalized score)."
            ),
            valueType="urn:li:dataType:datahub.number",
            entityTypes=["urn:li:entityType:datahub.mlModel"],
            cardinality=PropertyCardinalityClass.SINGLE,
        ),
    ))
    graph.emit(MetadataChangeProposalWrapper(
        entityUrn=LAST_ASSESSED_AT_PROPERTY_URN,
        aspect=StructuredPropertyDefinitionClass(
            qualifiedName="deadreckon.lastAssessedAt",
            displayName="Undertow Last Assessed At",
            description="ISO 8601 timestamp of the most recent deadreckon run that scored this model.",
            valueType="urn:li:dataType:datahub.string",
            entityTypes=["urn:li:entityType:datahub.mlModel"],
            cardinality=PropertyCardinalityClass.SINGLE,
        ),
    ))
    graph.emit(MetadataChangeProposalWrapper(
        entityUrn=UNASSESSABLE_TAG_URN,
        aspect=TagPropertiesClass(
            name="undertow:unassessable",
            description=(
                "deadreckon could not assess this model at all - every detector was missing "
                "the metadata it needed. Distinct from at-risk: this is not a finding, it is "
                "the absence of any verdict, which usually means required aspects aren't being "
                "emitted for this model's lineage."
            ),
        ),
    ))
    graph.emit(MetadataChangeProposalWrapper(
        entityUrn=FINDING_COUNT_PROPERTY_URN,
        aspect=StructuredPropertyDefinitionClass(
            qualifiedName="deadreckon.findingCount",
            displayName="Undertow Finding Count",
            description=(
                "How many distinct findings the most recent deadreckon run raised for this "
                "model. Breaks ties when sorting the risk table by score - two models can "
                "share a score while one has several independent problems."
            ),
            valueType="urn:li:dataType:datahub.number",
            entityTypes=["urn:li:entityType:datahub.mlModel"],
            cardinality=PropertyCardinalityClass.SINGLE,
        ),
    ))
    graph.emit(MetadataChangeProposalWrapper(
        entityUrn=ASSESSMENT_COVERAGE_PROPERTY_URN,
        aspect=StructuredPropertyDefinitionClass(
            qualifiedName="deadreckon.assessmentCoverage",
            displayName="Undertow Assessment Coverage",
            description=(
                "How many of deadreckon's detectors reached a verdict for this model, as "
                "conclusive/total (e.g. '2/3'). Deliberately separate from the risk score: a "
                "detector that lacked the metadata to run is neither a pass nor a risk, and "
                "folding 'unknown' into the score would destroy the meaning of both."
            ),
            valueType="urn:li:dataType:datahub.string",
            entityTypes=["urn:li:entityType:datahub.mlModel"],
            cardinality=PropertyCardinalityClass.SINGLE,
        ),
    ))


def _add_tag(graph: DataHubGraph, entity_urn: str, tag_urn: str) -> None:
    existing = graph.get_aspect(entity_urn=entity_urn, aspect_type=GlobalTagsClass)
    tags = list(existing.tags) if existing else []
    if any(t.tag == tag_urn for t in tags):
        return
    tags.append(TagAssociationClass(tag=tag_urn))
    graph.emit(MetadataChangeProposalWrapper(entityUrn=entity_urn, aspect=GlobalTagsClass(tags=tags)))


def _remove_tag(graph: DataHubGraph, entity_urn: str, tag_urn: str) -> None:
    existing = graph.get_aspect(entity_urn=entity_urn, aspect_type=GlobalTagsClass)
    if existing is None:
        return
    tags = [t for t in existing.tags if t.tag != tag_urn]
    if len(tags) == len(existing.tags):
        return
    graph.emit(MetadataChangeProposalWrapper(entityUrn=entity_urn, aspect=GlobalTagsClass(tags=tags)))


def set_at_risk_tag(graph: DataHubGraph, model_urn: str, at_risk: bool) -> None:
    if at_risk:
        _add_tag(graph, model_urn, AT_RISK_TAG_URN)
    else:
        _remove_tag(graph, model_urn, AT_RISK_TAG_URN)


def set_unassessable_tag(graph: DataHubGraph, model_urn: str, unassessable: bool) -> None:
    if unassessable:
        _add_tag(graph, model_urn, UNASSESSABLE_TAG_URN)
    else:
        _remove_tag(graph, model_urn, UNASSESSABLE_TAG_URN)


def _set_structured_properties(graph: DataHubGraph, entity_urn: str, updates: dict[str, list]) -> None:
    existing = graph.get_aspect(entity_urn=entity_urn, aspect_type=StructuredPropertiesClass)
    by_urn = {p.propertyUrn: p for p in (existing.properties if existing else [])}
    for property_urn, values in updates.items():
        by_urn[property_urn] = StructuredPropertyValueAssignmentClass(propertyUrn=property_urn, values=values)
    graph.emit(MetadataChangeProposalWrapper(
        entityUrn=entity_urn,
        aspect=StructuredPropertiesClass(properties=list(by_urn.values())),
    ))


DEADRECKON_MEMORY_MARKER = "[deadreckon]"


def _set_institutional_memory_entries(graph: DataHubGraph, entity_urn: str, url: str, descriptions: list[str], now: datetime) -> None:
    # Dedupe/replace by our own marker prefix, not by url or by matching
    # up old/new element pairs - every run drops *all* previously-written
    # [deadreckon] elements and writes the current full set fresh. This is
    # what makes it correct when the finding count changes between runs
    # (3 findings -> 1 -> 3 again): there's no stale leftover to clean up
    # because nothing is preserved across runs in the first place, unlike
    # a scheme that tried to update elements in place by index/URL, which
    # would leave old rows behind once the count shrinks.
    existing = graph.get_aspect(entity_urn=entity_urn, aspect_type=InstitutionalMemoryClass)
    elements = [e for e in (existing.elements if existing else []) if not e.description.startswith(DEADRECKON_MEMORY_MARKER)]
    now_millis = int(now.timestamp() * 1000)
    for description in descriptions:
        elements.append(InstitutionalMemoryMetadataClass(
            url=url,
            description=description,
            createStamp=AuditStampClass(time=now_millis, actor=WRITEBACK_ACTOR_URN),
        ))
    graph.emit(MetadataChangeProposalWrapper(entityUrn=entity_urn, aspect=InstitutionalMemoryClass(elements=elements)))


MAX_INSTITUTIONAL_MEMORY_FINDING_ROWS = 5


def _build_finding_memory_descriptions(risk: ModelRiskScore) -> list[str]:
    """One compact row per finding (up to a ceiling), plus an overview
    row - instead of one entry with a "(+N more)" tail that hid anything
    past the first finding entirely (the document it would have pointed
    to has no working UI route at all - see NOTES.md).

    Coverage rides in the overview row so a reader can never mistake
    "nothing found" for "nothing checked": a clean model with gaps says
    so on its face.
    """
    coverage = risk.coverage
    if risk.findings:
        headline = (
            f"{DEADRECKON_MEMORY_MARKER} {risk.severity} risk={risk.score}/{MAX_POSSIBLE_SCORE} - "
            f"{len(risk.findings)} finding(s) below, coverage {coverage}"
        )
    elif coverage.is_unassessable:
        headline = (
            f"{DEADRECKON_MEMORY_MARKER} NOT ASSESSED - no detector had the metadata it needed "
            f"(coverage {coverage})"
        )
    elif coverage.is_fully_covered:
        headline = f"{DEADRECKON_MEMORY_MARKER} CLEAR - all {coverage.total} detectors checked, nothing found"
    else:
        headline = (
            f"{DEADRECKON_MEMORY_MARKER} CLEAR so far - nothing found, but only coverage "
            f"{coverage} (the rest could not be checked)"
        )

    rows = [headline]
    shown = risk.findings[:MAX_INSTITUTIONAL_MEMORY_FINDING_ROWS]
    rows += [f"{DEADRECKON_MEMORY_MARKER} - {f.detector}: {_finding_subject(f)}" for f in shown]
    remaining = len(risk.findings) - len(shown)
    if remaining > 0:
        rows.append(f"{DEADRECKON_MEMORY_MARKER} - (+{remaining} more finding(s), see the document/API for detail)")

    # Name what was missing, not just how much - a gap is only actionable
    # if the reader learns which aspect to go emit, and on what. Grouped
    # by aspect because the same one missing across four datasets is one
    # problem to fix, not four rows of identical text.
    rows += _grouped_gap_rows(coverage.missing)
    return rows


MAX_GAP_SUBJECTS_LISTED = 3


def _grouped_gap_rows(missing: tuple[MissingSignal, ...]) -> list[str]:
    by_aspect: dict[str, list[str]] = {}
    for signal in missing:
        subjects = by_aspect.setdefault(signal.missing, [])
        name = _short_dataset_name(signal.subject_urn)
        if name not in subjects:
            subjects.append(name)

    rows = []
    for aspect, subjects in list(by_aspect.items())[:MAX_INSTITUTIONAL_MEMORY_FINDING_ROWS]:
        shown = ", ".join(subjects[:MAX_GAP_SUBJECTS_LISTED])
        extra = len(subjects) - MAX_GAP_SUBJECTS_LISTED
        if extra > 0:
            shown += f" (+{extra} more)"
        rows.append(f"{DEADRECKON_MEMORY_MARKER} - not checked: {aspect} absent on {shown}")
    return rows


def _short_dataset_name(dataset_urn: str) -> str:
    return dataset_urn.split(",")[-2] if "," in dataset_urn else dataset_urn


def _finding_subject(finding: Finding) -> str:
    """Compact, detector-specific "what/where" clause - built from
    evidence rather than reusing the full prose summary, so the subject
    (not just severity/score) survives a UI that truncates long text."""
    ev = finding.evidence
    if finding.detector == "D1" and "dataset_urn" in ev:
        return f"{_short_dataset_name(ev['dataset_urn'])} frozen {ev.get('frozen_days', '?')}d"
    if finding.detector == "D2" and "source_column" in ev:
        return f"{_short_dataset_name(ev['dataset_urn'])}.{ev['source_column']} missing {ev.get('missing_days', '?')}d"
    if finding.detector == "D3" and "transformation_dataset_urn" in ev:
        return f"{_short_dataset_name(ev['transformation_dataset_urn'])} logic changed {ev.get('changed_days', '?')}d ago"
    return finding.summary


def _render_report(model: ModelSnapshot, risk: ModelRiskScore, now: datetime) -> str:
    coverage = risk.coverage
    lines = [
        f"# Model Risk Assessment - {model.name}",
        "",
        f"Assessed: {now.isoformat()}",
        f"Risk score: {risk.score}/{MAX_POSSIBLE_SCORE} ({risk.severity})",
        f"Blast radius: {risk.blast_radius} (serving stage: {', '.join(model.deployment_environments) or 'not deployed'})",
        f"Assessment coverage: {coverage} detector(s) conclusive",
        "",
    ]

    if risk.findings:
        lines += ["## Findings", ""]
        for finding in risk.findings:
            lines.append(f"### {finding.detector}")
            lines.append(finding.summary)
            for key, value in finding.evidence.items():
                lines.append(f"- {key}: {value}")
            lines.append("")
    else:
        lines += ["## Findings", "", "None." if coverage.is_fully_covered
                  else "None among the detectors that could run - see coverage gaps below.", ""]

    # Always render the gaps, even when there are findings: a reader has
    # to be able to tell a clean bill of health from a partial one.
    if coverage.missing:
        lines += ["## Coverage gaps", "",
                  "These checks could not run - the listed metadata is absent from the graph.", ""]
        for signal in coverage.missing:
            lines.append(f"- `{signal.missing}` on {signal.subject_urn}")
            if signal.detail:
                lines.append(f"  - {signal.detail}")
        lines.append("")

    return "\n".join(lines)


def _document_id_for(model: ModelSnapshot) -> str:
    return f"deadreckon-risk-{model.name}"


def write_risk_assessment(graph: DataHubGraph, model: ModelSnapshot, risk: ModelRiskScore, now: datetime) -> str:
    document_id = _document_id_for(model)
    document_urn = f"urn:li:document:{document_id}"
    content = _render_report(model, risk, now)
    title = f"Model Risk Assessment - {model.name}"

    create_mutation = """
    mutation createDoc($input: CreateDocumentInput!) {
      createDocument(input: $input)
    }
    """
    try:
        graph.execute_graphql(query=create_mutation, variables={"input": {
            "id": document_id,
            "title": title,
            "subType": "Analysis",
            "contents": {"text": content},
            "relatedAssets": [model.urn],
        }})
    except Exception as exc:
        if "already exists" not in str(exc):
            raise
        update_mutation = """
        mutation updateDoc($input: UpdateDocumentContentsInput!) {
          updateDocumentContents(input: $input)
        }
        """
        graph.execute_graphql(query=update_mutation, variables={"input": {
            "urn": document_urn,
            "title": title,
            "contents": {"text": content},
        }})

    _set_structured_properties(graph, model.urn, {
        RISK_SCORE_PROPERTY_URN: [risk.score],
        LAST_ASSESSED_AT_PROPERTY_URN: [now.isoformat()],
        FINDING_COUNT_PROPERTY_URN: [risk.finding_count],
        ASSESSMENT_COVERAGE_PROPERTY_URN: [str(risk.coverage)],
    })
    set_at_risk_tag(graph, model.urn, is_at_risk(risk.severity))
    # Deliberately not the same thing as at-risk: this says we reached no
    # verdict at all, which is a metadata-completeness problem rather than
    # a model problem. Only fires when *every* detector came up empty -
    # partial gaps are carried by assessmentCoverage, so this tag stays
    # rare enough to mean something (the mistake at-risk made before it
    # was gated on severity).
    set_unassessable_tag(graph, model.urn, risk.coverage.is_unassessable)

    # The Document entity itself has no working profile route in this
    # DataHub version (confirmed 404 both via a direct /documents/<urn>
    # guess and via the "Resources" card on the model's own Documentation
    # tab, which links to the same dead route) - see NOTES.md. So this
    # points at the at-risk search list instead of the document, and the
    # description (not the link) is what actually has to carry the
    # reasoning - front-loaded so severity/score/detector/subject survive
    # the UI's own truncation regardless of where it cuts. One row per
    # finding (capped, see MAX_INSTITUTIONAL_MEMORY_FINDING_ROWS) instead
    # of a single entry with a "(+N more)" tail that hid everything past
    # the first finding.
    at_risk_list_url = f"{FRONTEND_BASE_URL}/search?query=undertow%3Aat-risk"
    _set_institutional_memory_entries(graph, model.urn, at_risk_list_url, _build_finding_memory_descriptions(risk), now)

    return document_urn
