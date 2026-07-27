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
4. An `institutionalMemory` entry (the aspect behind the classic
   "Documentation"/"Links" tab) with a one-line risk summary. This exists
   because `relatedAssets`/`relatedDocuments` (used for (1)) is a
   different, newer relationship than `institutionalMemory` - a document
   attached only via `relatedAssets` does not show up on the model's
   Documentation tab in this DataHub version (verified: `MLModel`'s
   GraphQL type has both `institutionalMemory` and `relatedDocuments` as
   separate fields). Confirmed empirically that the standalone Document
   entity has *no* working profile route in this DataHub version at all -
   neither a direct URL guess nor the UI's own "Resources" card for it
   resolves to anything (both 404) - so this entry's `description` (not
   its `url`, which points at the at-risk search list instead) is what
   actually carries the reasoning, front-loaded so severity/score/
   detector/subject survive the UI's own text truncation. See NOTES.md.

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
RISK_SCORE_PROPERTY_URN = "urn:li:structuredProperty:deadreckon.riskScore"
LAST_ASSESSED_AT_PROPERTY_URN = "urn:li:structuredProperty:deadreckon.lastAssessedAt"
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


def _set_institutional_memory_link(graph: DataHubGraph, entity_urn: str, url: str, description: str, now: datetime) -> None:
    # Dedupe/replace by our own marker prefix, not by url - the url this
    # points at has changed once already (see NOTES.md: the standalone
    # Document entity has no working profile route in this DataHub
    # version, confirmed 404 both directly and via the Resources card, so
    # this now links to the at-risk search list instead). Keying on url
    # would leave the old, dead link behind as a stale duplicate entry.
    existing = graph.get_aspect(entity_urn=entity_urn, aspect_type=InstitutionalMemoryClass)
    elements = [e for e in (existing.elements if existing else []) if not e.description.startswith(DEADRECKON_MEMORY_MARKER)]
    now_millis = int(now.timestamp() * 1000)
    elements.append(InstitutionalMemoryMetadataClass(
        url=url,
        description=description,
        createStamp=AuditStampClass(time=now_millis, actor=WRITEBACK_ACTOR_URN),
    ))
    graph.emit(MetadataChangeProposalWrapper(entityUrn=entity_urn, aspect=InstitutionalMemoryClass(elements=elements)))


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
    lines = [
        f"# Model Risk Assessment - {model.name}",
        "",
        f"Assessed: {now.isoformat()}",
        f"Risk score: {risk.score}/{MAX_POSSIBLE_SCORE} ({risk.severity})",
        f"Blast radius: {risk.blast_radius} (deployment environments: {', '.join(model.deployment_environments) or 'none'})",
        "",
        "## Findings",
        "",
    ]
    for finding in risk.findings:
        lines.append(f"### {finding.detector}")
        lines.append(finding.summary)
        for key, value in finding.evidence.items():
            lines.append(f"- {key}: {value}")
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
    })
    set_at_risk_tag(graph, model.urn, is_at_risk(risk.severity))

    # The Document entity itself has no working profile route in this
    # DataHub version (confirmed 404 both via a direct /documents/<urn>
    # guess and via the "Resources" card on the model's own Documentation
    # tab, which links to the same dead route) - see NOTES.md. So this
    # points at the at-risk search list instead of the document, and the
    # description (not the link) is what actually has to carry the
    # reasoning - front-loaded so severity/score/detector/subject survive
    # the UI's own truncation regardless of where it cuts.
    memory_description = (
        f"{DEADRECKON_MEMORY_MARKER} {risk.severity} risk={risk.score}/{MAX_POSSIBLE_SCORE} | "
        f"{risk.findings[0].detector}: {_finding_subject(risk.findings[0])}"
        + (f" (+{len(risk.findings) - 1} more finding(s))" if len(risk.findings) > 1 else "")
    )
    at_risk_list_url = f"{FRONTEND_BASE_URL}/search?query=undertow%3Aat-risk"
    _set_institutional_memory_link(graph, model.urn, at_risk_list_url, memory_description, now)

    return document_urn
