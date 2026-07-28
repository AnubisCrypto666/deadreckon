# Comment to post on datahub-project/datahub#18675

Independently hit this on the same version, and I think the problem is
one step worse than indexing lag — the entity has no viewable page at
all, so even "knowing the URN" doesn't help a human.

**Versions:** DataHub Core Quickstart / GMS `v1.5.0.6`,
`mcp-server-datahub` (mutations enabled), documents created via both the
MCP `save_document` tool and the `createDocument` GraphQL mutation
directly.

## Confirming the search symptom

Documents created ~3 hours before this measurement (so well outside any
plausible indexing window), attached to an `mlModel` via `relatedAssets`:

```
direct URN fetch (entity(urn) { ... on Document { info { title } } })
    -> "Model Risk Assessment - taxi_eta_predictor_v1"     ✓ exists

searchAcrossEntities types:[DOCUMENT] query:"Model Risk Assessment"  -> total = 0
searchAcrossEntities types:[DOCUMENT] query:"taxi_eta_predictor_v1"  -> total = 0
searchAcrossEntities types:[DOCUMENT] query:"deadreckon"             -> total = 0

relatedDocuments on the attached mlModel                             -> total = 1  ✓
```

So the entity exists, is fetchable by URN, and is correctly linked from
the asset it was attached to — but is not discoverable through search by
title, by attached-asset name, or by a distinctive substring. The MCP
`search_documents` tool returns 0 for the same queries. Matches your
"disagreement between what MCP reports in aggregate and what a user can
find" exactly.

## The part I'd add: there is no Document profile route

Beyond search, I could not find any way to *open* a Document in the UI,
even holding its URN. Two independent attempts, both 404:

1. A direct URL guess following the pattern used by other entity types
   (`/documents/<url-encoded-urn>`) → **404**.
2. The UI's own affordance: on the attached model's **Documentation** tab,
   the document shows up as a native "Resources" card with its correct
   title and an "Edited … by DataHub" byline. **Clicking that card also
   404s** — the product's own link points at the same non-existent route.

That second one seems worth separating from the indexing question: it
isn't that the document is hard to find, it's that there is nowhere for a
search result to lead even if search did return it. If that's a distinct
bug rather than part of this one, happy for it to be split out — I'm
commenting here rather than filing a third document-related issue.

## Same conclusion, different fallback

Like you, I abandoned Document as the user-visible write-back surface.
For anyone landing here: what worked for me was `institutionalMemory` on
the entity itself (the aspect behind the classic **Documentation /
Links** tab), with the reasoning carried in the entry's `description`
rather than behind the link. That renders directly in the right-hand
Summary panel with no click required, and — unlike `relatedAssets` — it
is a relationship the current UI actually surfaces. The Document entity
is still written (it round-trips fine through the API, and it's useful as
a machine-readable record), it just can't be the thing a human is
expected to click.

Expectation-wise I'd land on your option 2, with an addition: if Document
is API/MCP-only in this version, the docs saying so should probably also
mention that `relatedAssets` attachment produces a UI card that leads
nowhere, since that's actively misleading rather than merely absent.
