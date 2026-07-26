"""
Writes risk assessment results back into the graph, next to the model
they concern (plan-pracy-undertow.md Sec.5):

1. A "Model Risk Assessment" document (via the `createDocument`/
   `updateDocumentContents` GraphQL mutations - the same mutations behind
   mcp-server-datahub's `save_document` tool, called directly here so the
   pipeline runs headlessly; see NOTES.md for how this was found and
   verified, including that `deleteDocument` exists and is a soft delete,
   same semantics as `datahub delete --soft`).
2. The `undertow:at-risk` tag on the model.
3. `deadreckon.riskScore` / `deadreckon.lastAssessedAt` structured
   properties on the model.

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
    GlobalTagsClass,
    PropertyCardinalityClass,
    StructuredPropertiesClass,
    StructuredPropertyDefinitionClass,
    StructuredPropertyValueAssignmentClass,
    TagAssociationClass,
    TagPropertiesClass,
)

from detectors.models import ModelSnapshot
from detectors.scoring import ModelRiskScore

AT_RISK_TAG_URN = "urn:li:tag:undertow:at-risk"
RISK_SCORE_PROPERTY_URN = "urn:li:structuredProperty:deadreckon.riskScore"
LAST_ASSESSED_AT_PROPERTY_URN = "urn:li:structuredProperty:deadreckon.lastAssessedAt"


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
            description="detector weight x blast radius, from the most recent deadreckon run.",
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


def _set_structured_properties(graph: DataHubGraph, entity_urn: str, updates: dict[str, list]) -> None:
    existing = graph.get_aspect(entity_urn=entity_urn, aspect_type=StructuredPropertiesClass)
    by_urn = {p.propertyUrn: p for p in (existing.properties if existing else [])}
    for property_urn, values in updates.items():
        by_urn[property_urn] = StructuredPropertyValueAssignmentClass(propertyUrn=property_urn, values=values)
    graph.emit(MetadataChangeProposalWrapper(
        entityUrn=entity_urn,
        aspect=StructuredPropertiesClass(properties=list(by_urn.values())),
    ))


def _render_report(model: ModelSnapshot, risk: ModelRiskScore, now: datetime) -> str:
    lines = [
        f"# Model Risk Assessment - {model.name}",
        "",
        f"Assessed: {now.isoformat()}",
        f"Risk score: {risk.score} ({risk.severity})",
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

    _add_tag(graph, model.urn, AT_RISK_TAG_URN)
    _set_structured_properties(graph, model.urn, {
        RISK_SCORE_PROPERTY_URN: [risk.score],
        LAST_ASSESSED_AT_PROPERTY_URN: [now.isoformat()],
    })
    return document_urn
