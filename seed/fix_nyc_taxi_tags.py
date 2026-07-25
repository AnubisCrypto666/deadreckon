"""
Fixes a bug in the upstream nyc-taxi fixture's add_metadata.py
(datahub-project/static-assets, datasets/nyc-taxi): attach_tags() and
attach_glossary() emit one MetadataChangeProposal per (tag, table) pair,
each carrying a fresh `GlobalTagsClass(tags=[single_tag])` /
`GlossaryTermsClass(terms=[single_term])`. Since an MCP aspect emission
fully replaces the aspect rather than merging with it, only the last tag
and last term written per table survives - every table in both nyc_taxi
and nyc_taxi_pipeline ends up with only `pipeline_stage` (the last key in
TAG_ASSIGNMENTS/GLOSSARY_ASSIGNMENTS dict order), silently dropping
daily_refresh/time_series/pii and freshness_sla/empty_load. Confirmed via
GraphQL: every one of the 6 tables had exactly one tag and one term
(pipeline_stage / pipeline_stage) instead of the 2-4 each should have.
Reported upstream-worthy in NOTES.md.

This script re-emits the correct aggregated tags/terms in a single MCP
per entity per aspect, using the same TAG_ASSIGNMENTS/GLOSSARY_ASSIGNMENTS
data as the upstream script (add_metadata.py must have already been run
once, so the tag/term entities themselves already exist in the graph).
"""

import time

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    AuditStampClass,
    GlobalTagsClass,
    GlossaryTermAssociationClass,
    GlossaryTermsClass,
    TagAssociationClass,
)

DATAHUB_SERVER = "http://localhost:8080"
PLATFORM = "sqlite"
INSTANCES = ["nyc_taxi", "nyc_taxi_pipeline"]

TAG_ASSIGNMENTS = {
    "daily_refresh": ["raw_trips", "staging_trips", "mart_daily_summary"],
    "time_series": ["raw_trips", "staging_trips"],
    "pii": ["raw_trips", "staging_trips"],
    "pipeline_stage": ["raw_trips", "staging_trips", "mart_daily_summary"],
}

GLOSSARY_ASSIGNMENTS = {
    "freshness_sla": ["raw_trips", "staging_trips", "mart_daily_summary"],
    "empty_load": ["mart_daily_summary"],
    "pipeline_stage": ["raw_trips", "staging_trips", "mart_daily_summary"],
}


def tables_to_tags() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for tag, tables in TAG_ASSIGNMENTS.items():
        for t in tables:
            result.setdefault(t, []).append(tag)
    return result


def tables_to_terms() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for term, tables in GLOSSARY_ASSIGNMENTS.items():
        for t in tables:
            result.setdefault(t, []).append(term)
    return result


def main() -> None:
    emitter = DatahubRestEmitter(DATAHUB_SERVER)
    tags_by_table = tables_to_tags()
    terms_by_table = tables_to_terms()

    for instance in INSTANCES:
        print(f"\nInstance: {instance}")
        for table in sorted(set(tags_by_table) | set(terms_by_table)):
            urn = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},{instance}.main.{table},PROD)"

            tags = tags_by_table.get(table, [])
            if tags:
                emitter.emit(
                    MetadataChangeProposalWrapper(
                        entityUrn=urn,
                        aspect=GlobalTagsClass(
                            tags=[TagAssociationClass(tag=f"urn:li:tag:{t}") for t in tags]
                        ),
                    )
                )

            terms = terms_by_table.get(table, [])
            if terms:
                emitter.emit(
                    MetadataChangeProposalWrapper(
                        entityUrn=urn,
                        aspect=GlossaryTermsClass(
                            terms=[
                                GlossaryTermAssociationClass(urn=f"urn:li:glossaryTerm:{term}")
                                for term in terms
                            ],
                            auditStamp=AuditStampClass(
                                time=int(time.time() * 1000),
                                actor="urn:li:corpuser:datahub",
                            ),
                        ),
                    )
                )
            print(f"  {table}: tags={tags} terms={terms}")

    print("\nDone.")


if __name__ == "__main__":
    main()
