# Build notes

Running log of decisions, verification results, and DataHub documentation
issues found while building deadreckon. Documentation issues here are raw
material for OSS doc-fix contributions.

## Decisions

- 2026-07-25: Repo name `deadreckon`, Apache 2.0 license.
- 2026-07-25: Project targets Python 3.10+, developed against 3.11 via `uv`.

## Verification results

- 2026-07-26: **Mutation flag verified — the MCP server's mutation tools work
  on DataHub Core**, not Cloud-only, resolving the ambiguity flagged in
  plan-pracy-undertow.md §5. Confirmed empirically by round-tripping every
  exposed mutation tool against the local Core quickstart, on a clean
  dataset (`nyc_taxi.main.v_staging_from_raw`, a view with no pre-existing
  tags/terms/owner/domain/description), verifying persistence with
  `get_entities` after each write, then reverting:
  - `add_tags`/`remove_tags` — works, but the tag URN must already exist as
    an entity in the graph first; passing an unregistered tag URN (tried
    `urn:li:tag:mcp_verify_test`) fails with GraphQL `BAD_REQUEST` ("Urn
    does not exist"). There is no `create_tag`-equivalent mutation tool
    exposed here, so brand-new tags/terms still need to be created via the
    Python SDK or UI before `add_tags`/`add_terms` can attach them to
    entities.
  - `add_terms`/`remove_terms` — works against an existing glossary term
    (`pipeline_stage`).
  - `add_owners`/`remove_owners` — works
    (`urn:li:corpuser:datahub`, `TECHNICAL_OWNER`).
  - `update_description` (`replace` then `remove`) — works, entity-level.
  - `set_domains`/`remove_domains` — works against an existing domain.
  - `add_structured_properties`/`remove_structured_properties` — works
    against an existing structured property definition
    (`urn:li:structuredProperty:showcase.dataQualityScore`).
  - `save_document` — works; created
    `urn:li:document:shared-793bb593-a8ae-4f14-8051-b90741667b59`
    ("MCP verify test — safe to delete"), confirmed via `grep_documents`.
    No delete/remove-document tool exists in this MCP server; see the
    cleanup convention below for how it was removed afterward.

  **Conclusion:** writeback for the spec's §5 plan (`save_document` for Model
  Risk Assessment docs, `add_tags` for `undertow:at-risk`,
  `add_structured_properties` for risk score/last-assessed date) can go
  straight through the MCP mutation tools — no fallback to the Python SDK
  path is needed. Caveat: any brand-new tag/structured-property *definitions*
  not yet registered in DataHub must still be created via SDK/UI first; the
  MCP tools only attach/detach references to definitions that already exist.

  **Cleanup convention for test documents:** the MCP server has no
  `remove_document`/delete tool, so any throwaway `save_document` output
  (like the "MCP verify test — safe to delete" doc above,
  `urn:li:document:shared-793bb593-a8ae-4f14-8051-b90741667b59`) is removed
  via the `datahub` CLI instead:
  `datahub delete --urn "<document urn>" --soft`.
  Confirmed this actually hides it from normal discovery: after running it
  on the test doc, `search_documents` (the same path UI search / Ask
  DataHub use) returned 0 matches for it. Note it's a *soft* delete only —
  it sets the entity's `status` aspect to removed but doesn't purge the
  underlying aspects, so a tool that fetches by URN directly
  (`grep_documents`, `get_entities`) can still read its content afterward.
  Good enough for hiding scratch verification docs from the UI; use
  `datahub delete --urn ... --hard` instead if a test entity's data must be
  fully purged, not just hidden.
  Side note: this CLI (`acryl-datahub` 1.6.0.15 in `.venv`) is one minor
  version ahead of the quickstart server (1.5.0.6) and prints a
  client/server incompatibility warning on every invocation; delete still
  worked fine here, but worth pinning the client to match server version if
  it ever causes a real incompatibility.

- 2026-07-26: **`seed/ml_lineage.py` written and run; Bramka 1 (spec plan-pracy-undertow.md
  Sec.8) passes** - confirmed the agent can traverse dataset -> feature ->
  training run -> model -> deployment through the MCP server's read tools.
  Seeded 3 `mlFeatureTable`s (13 `mlFeature`s total), 3 `mlModelGroup`s,
  5 `mlModel`s, 8 `dataProcessInstance` training runs (subtype
  `MLFLOW_TRAINING_RUN`), wired into real tables from showcase-ecommerce
  (Snowflake: customers/orders/order_items/order_details) and
  nyc_taxi_pipeline (SQLite: raw_trips/staging_trips - the instance with the
  seeded freshness gap, so `taxi_eta_predictor_v1`'s 4 nightly training runs
  give D1 a genuine "trains nightly on a source frozen N days ago" signal
  to detect later, not a fabricated one).

  Two things had to be fixed along the way, both confirmed empirically
  against the live Core instance rather than assumed from docs:

  1. **`MLFeatureProperties.sources` rejects schemaField (column) URNs.**
     Tried pointing a feature's `sources` at a specific upstream column via
     `make_schema_field_urn(...)`; GMS returned a 422 - "Entity type for urn
     ... is not a valid destination for field path: /sources/*". This field
     only accepts dataset-level URNs (confirmed both from the compiled
     schema's relationship annotation, `entityTypes: ["dataset"]`, and from
     the runtime rejection), contradicting the plan's assumption that
     `sources` could carry column-level provenance. Worked around by
     pointing `sources` at the dataset and recording the specific source
     column in the feature's `description` instead - still real
     provenance, just not a lineage-graph edge.

  2. **`mlModelDeployment` is effectively unreadable through this MCP
     server** (mcp-server-datahub against DataHub Core 1.5.0.6). First
     implementation created real `mlModelDeployment` entities (per spec
     Sec.3) and linked them via `MLModelProperties.deployments`. Verification
     found:
     - `get_lineage`/`get_lineage_paths_between` from or to the model found
       no edge to the deployment in either direction - the `deployments`
       field's relationship (`DeployedTo`) isn't flagged `isLineage` in the
       schema, so it never enters the lineage graph these tools walk.
     - `get_entities` on the deployment URN itself returned "entity exists
       but no data could be retrieved," and on the model returned only
       `name`/`description`/`origin`/`platform` - none of
       `hyperParams`/`trainingMetrics`/`mlFeatures`/`groups`/`trainingJobs`/
       `deployments` came through, even though `get_lineage`'s facets prove
       those relationships are correctly stored (inputs/outputs/processType
       showed up there for the very same runs).
     - `search(filter="entity_type = mlModelDeployment")` fails: the
       GraphQL `EntityType` enum in this DataHub version has no matching
       symbol (tried both `ML_MODEL_DEPLOYMENT` and `MLMODEL_DEPLOYMENT`).
     - Separately, `datahub delete --hard` on one of the created
       `mlModelDeployment` URNs failed with "STAGING is not an enum symbol"
       for the `/origin` field of its own key - even though creating that
       same entity with `env="STAGING"` had succeeded moments earlier via
       the SDK. Write and delete disagree on the valid enum set for this
       entity's key. Cleaned it up with `--soft` instead, which worked.

     None of this is a bug in the seed data - `get_lineage`'s own facets
     prove the underlying graph is correct. It's specifically that
     `mlModelDeployment` has no working read path through the tools an
     MCP-only agent has available. **Fix:** dropped `mlModelDeployment` as
     an entity entirely; deployment status is now a structured property
     (`urn:li:structuredProperty:deadreckon.deploymentEnvironment`, values
     `PROD`/`STAGING`) directly on the `mlModel`. Confirmed this line
     actually closes the gap: `get_entities` on a model returns
     `structuredProperties` correctly (unlike the ML-specific property
     fields above), the `add_structured_properties`/`remove_structured_properties`
     MCP tools read/write it with no issue (matches the general mutation-tool
     verification above), and it shows up inline in `get_lineage` results
     too - confirmed by running `get_lineage` downstream from
     `nyc_taxi_pipeline.raw_trips` at `max_hops=3`, which reached
     `taxi_eta_predictor_v1` with `structuredProperties.deploymentEnvironment
     = PROD` already attached in the same response, no second call needed.
     This is a deliberate, documented departure from Sec.3 of the spec
     (which lists `mlModelDeployment` as an entity to seed) - worth
     upstreaming as a doc/behavior gap in `mcp-server-datahub` regardless
     of what this project ends up doing.

- 2026-07-26: **D1-D3 detectors, scoring, and writeback implemented and
  verified end-to-end against the live Core instance** (`detectors/`,
  `run_detectors.py`, `seed/inject_faults.py`). Architecture decision made
  along the way, with a follow-up empirical finding that justifies it:

  1. **The detector *pipeline* reads via the DataHub Python SDK/GraphQL
     directly, not through mcp-server-datahub's `get_entities`/
     `get_lineage` tools**, because those tools' field projections for
     `mlModel`, `mlFeature`, and `dataProcessInstance` are incomplete in
     exactly the way already documented above for `mlModelDeployment`.
     Confirmed empirically: `mcp__datahub__get_entities` on an `mlModel`
     URN returns only `name`/`description`/`origin`/`platform`/
     `structuredProperties` (no `hyperParams`, `trainingMetrics`,
     `mlFeatures`, `groups`, `trainingJobs`); on an `mlFeature` URN only
     `name`/`description` (no `sources`, `dataType`, `customProperties`);
     on a `dataProcessInstance` URN, nothing but the bare `urn`.
     `mcp__datahub__get_lineage` shows `dataProcessInstance` training-run
     nodes as bare stubs too (urn/type only, no timestamp). All of this
     data *is* present and fully queryable via raw GraphQL/the SDK
     (`execute_graphql`, `get_aspect`) - confirmed by fetching the exact
     same URNs directly and getting full fidelity back, including
     `DataProcessInstance.state` (run timestamps, via GraphQL) and
     dataset `schemaMetadata`/`viewProperties.logic`/`operations`
     (freshness), all of which came through the MCP tool fine for plain
     `dataset` entities but not for these three ML-specific ones. So
     `structuredProperties` remains the one field proven to project
     correctly through the MCP tool for *every* entity type tested so
     far (dataset, mlModel) - which is why every value a detector needs
     to compare programmatically (deployment environment, schema-changed-
     at, definition-changed-at, and now risk score/last-assessed-at) is
     written as a structured property rather than relying on the
     entity's own native fields, even where those native fields exist
     and are semantically the "right" place for the data (e.g.
     `SchemaMetadataClass.lastModified`, which exists on the aspect but
     isn't exposed by DataHub's GraphQL schema for `SchemaMetadata` at
     all - only `createdAt` is, and its update-on-rewrite semantics
     weren't verified, so this project doesn't rely on it either).
     Bramka 1's own binary criterion (an interactive MCP client can walk
     dataset -> feature -> training run -> model) is unaffected by this -
     it's already satisfied and stays true. This is specifically about
     what a *headless, automated* pipeline can rely on this MCP server
     version to read back reliably, which turns out to be narrower.

  2. **Writeback for the "Model Risk Assessment" document goes through
     the same GraphQL mutations `save_document` uses under the hood**
     (`createDocument`, `updateDocumentContents`, `relatedAssets`),
     called directly via `execute_graphql` so the pipeline runs headlessly
     without an LLM in the loop for every write. Confirmed empirically:
     `createDocument` with a caller-supplied `id` fails cleanly with
     "Document with ID ... already exists" on a second call with the same
     id (not a silent no-op or a duplicate) - `run_detectors.py` catches
     that specific error and falls back to `updateDocumentContents`,
     verified idempotent by re-running the full pipeline twice and
     observing `lastAssessedAt` and the document body both advance to the
     second run's timestamp. Also found in the same exploration: a
     `deleteDocument` GraphQL mutation exists (no equivalent tool is
     exposed by this MCP server, consistent with the no-delete-tool gap
     already noted above for `save_document`) - confirmed it sets
     `status.removed = true` and correctly disappears from
     `search_documents`/`searchAcrossEntities`, i.e. it's a **soft**
     delete with the exact same semantics as `datahub delete --soft`
     (content still readable by direct URN fetch afterward). Nicer than
     shelling out to the CLI for cleaning up scratch/test documents going
     forward, but not a hard purge - same caveat as before.

  3. **Fault injection for D2/D3, disclosed per Sec.3's honesty rule**
     (`seed/inject_faults.py`, idempotent, anchored like the other seed
     scripts): D2 renames `credit_limit` -> `credit_limit_usd` on the
     showcase-ecommerce `customers` table (Snowflake) and records a
     `deadreckon.schemaChangedAt` structured property (3 days ago) on
     that dataset; D3 edits the `discount_percent` calculation in the
     dbt `order_details` model's `viewLogic` from "percent of list price"
     to "percent of unit price" - same column name and type, different
     number - and records `deadreckon.definitionChangedAt` (9 days ago)
     on that dbt dataset. Both timestamps are planted rather than derived
     from DataHub's own aspect history, per the finding above (schema/
     view-logic versioning isn't reliably readable through this MCP
     server either).

  4. **End-to-end run against the live Core instance produced the
     expected mix of positive and negative findings**, including the
     specific negative control the fault injection was designed to
     produce: `customer_churn_predictor_v2` (PROD, last trained 5 days
     ago, *after* the 9-days-ago D3 definition change) correctly gets
     only a D2 finding, not D3 - while `customer_churn_predictor_v1`
     (STAGING, superseded, last trained 46 days ago) and
     `order_value_predictor_v1` (PROD, last trained 11 days ago) both get
     flagged for D3, since both trained before the change. This
     confirms the date-comparison logic in `d3_semantic_drift.py`
     isn't just "flag anything touching this dataset" - it actually
     distinguishes retrained-after-the-fact from still-stale. Full
     writeback (tag + both structured properties + related document) was
     then confirmed readable back through the *actual*
     `mcp__datahub__get_entities` tool (not just the SDK), closing the
     loop end-to-end through the same interface Bramka 1 verified.

- 2026-07-26: **Pre-push review of commit `f02f933`, plus follow-up fixes
  found during that review.**

  1. **Secret audit: clean.** Grepped the full diff of `f02f933` and the
     entire git history (`git log --all -p`, all 6 commits) for
     token/bearer/authorization/password/secret/api-key patterns, JWT-
     shaped strings, and credential-embedded URLs (`user:pass@host`).
     Zero real hits. The only matches were (a) the well-known local
     quickstart default `datahub init --username datahub --password
     datahub`, quoted in a doc-issue bullet, and (b) the already-masked
     `eyJh**********t-_Q` token fragment quoted in the 2026-07-26 session
     audit further down this file - both intentional documentation, not
     leaked values. Confirmed separately that only `.env.example` (empty
     `DATAHUB_GMS_TOKEN=` placeholder) was ever committed, never `.env`.
     The real access token lives solely in `~/.datahubenv`, outside the
     repo, and was independently confirmed (by Jacek, in his own
     terminal) to never appear anywhere in git history.

  2. **`undertow:at-risk` tag was unconditional - fixed.** Originally
     applied to any model with >=1 finding, which for the current 5-model
     seed meant all 5 got tagged (`riskScore` ranged 0.4-3.0 across them:
     customer_churn_predictor_v1=1.0/MEDIUM, v2=3.0/HIGH,
     order_value_predictor_v1=1.8/MEDIUM, taxi_eta_predictor_v1=2.4/HIGH,
     taxi_fare_predictor_v1=0.4/LOW) - a wall of red tags reads as "flags
     everything," not as a scoring agent. Fixed: `scoring.is_at_risk()`
     gates the tag on severity != LOW (score >= 0.8, the existing MEDIUM
     threshold, not a new number invented to make the demo look right) -
     the document and both structured properties are still written for
     *every* assessed model regardless (that's the data behind the
     sorted risk table from spec Sec.2), only the visual tag is gated.
     `writeback.set_at_risk_tag()` now also *removes* the tag when a
     model's severity is LOW, so it tracks current state rather than
     "was ever flagged" - verified by toggling `taxi_fare_predictor_v1`
     (genuinely LOW/0.4) and confirming the tag actually disappears via
     `get_entities` (no `tags` key at all afterward). 25/25 unit tests
     pass (2 new: `is_at_risk` semantics).

  3. **Idempotency of the full writeback path: confirmed, 3 consecutive
     runs, no fix needed.** Ran `run_detectors.py` three times in a row;
     checked raw aspects via the SDK (not just the resolved
     `get_entities` view) after each run. Tag count stayed at 1 per
     model, `structuredProperties` stayed at exactly 3 entries for
     deployed models / 2 for the undeployed one (no duplicate
     `propertyUrn`s), `relatedDocuments.total` stayed at 1 per model with
     the same document URN each time, document content length stayed
     constant (658 chars for taxi_eta_predictor_v1) with only the
     `Assessed:`/`lastAssessedAt` timestamp advancing run over run.

  4. **UI-visible latency for both writeback-facing screens: measured
     directly in the browser (Jacek's own eyes, not MCP/SDK), <5s for
     both, single combined write.** One write operation touched both
     screens at once (`write_risk_assessment` for
     `customer_churn_predictor_v1`, which updates its own `Properties`
     tab, plus `set_at_risk_tag(taxi_fare_predictor_v1, True)`, which
     changes list membership) - completed at 2026-07-26T18:44:29 UTC.
     Both screens showed the change on the *first* manual refresh after
     that timestamp:
     - `mlModels/<urn>` profile page, **Properties** tab
       (`lastAssessedAt`/`riskScore` - entity-by-URN GraphQL read, not
       search-index-backed): **<5s**.
     - Tag-filtered search (`/search?query=undertow%3Aat-risk`,
       OpenSearch-backed `searchAcrossEntities`): **<5s** - went from 4
       to 5 results (`taxi_fare_predictor_v1` present) on first refresh.
     Followed up with 3 automated add/remove polling passes (1s interval)
     directly against `searchAcrossEntities` on the same tag, to get a
     *range* rather than one manually-observed point: 0.11s, 3.00s,
     2.97s for the add transition to become visible; 1.66s, 2.98s, 2.99s
     for remove. So the honest number for planning the demo video is
     **up to ~3s, observed as low as ~0.1s** for this specific entity
     count (5 ML models) and query shape - not the "several minutes" seen
     earlier in this file for the full `datapack load` (1049 entities);
     OpenSearch catch-up time scales with what changed and the total
     index size, so this number is specific to writeback-scale changes on
     this dataset, not a general constant. Good enough that a single
     continuous take (run pipeline -> cut to UI -> refresh once) should
     work for filming, but pad with one extra refresh as a safety margin
     given the observed variance (0.1s-3s) rather than assuming the fast
     end every time.

  5. **`Model Risk Assessment` document has no working UI route at all in
     this DataHub version - confirmed 404 from every path tried, not
     fixable on our side, so the fix is a second, separate writeback that
     carries the reasoning by value instead of by link.** Sequence of
     what was actually checked, live, in the browser (Jacek's own eyes):
     - Confirmed `relatedAssets` (used for the document, via
       `createDocument`) and `institutionalMemory` (the classic
       "Documentation"/"Links" tab) are two separate aspects/relationships
       - `MLModel`'s GraphQL type exposes both `institutionalMemory` and
         `relatedDocuments` as distinct fields, and a document attached
         only via `relatedAssets` did not show up under the Documentation
         tab.
     - Added an `institutionalMemory` entry per assessed model (this
       project's own writeback, not a DataHub document) whose `url`
       originally pointed at a guessed direct document route,
       `http://localhost:9002/documents/<urn>` - **confirmed 404**.
     - The model's Documentation tab *does* show a native "Resources"
       card for the document (via `relatedAssets`) with its title and an
       "Edited .../by DataHub" byline - clicking it **also 404s**. So
       neither a guessed direct URL nor the UI's own built-in link to the
       same entity resolves to anything. This DataHub version's frontend
       has no profile route for the standalone Document entity type at
       all, through any path.
     - **Fix**: `_finding_subject()` in `detectors/writeback.py` builds a
       compact, detector-specific "what/where" clause from each finding's
       *evidence* (not by truncating the long prose `summary`), and the
       `institutionalMemory` entry's `description` is
       `[deadreckon] {severity} risk={score} | {detector}: {subject}` -
       severity, score, and detector code always land in the first ~35
       characters, well before the panel's own truncation point (observed
       description lengths ranged 79-123 chars across all 5 models, and
       the critical prefix is never what gets cut). The entry's `url` was
       changed to point at the tag-filtered search list instead
       (`/search?query=undertow%3Aat-risk`, already confirmed working and
       <5s per the latency measurement above) - somewhere that actually
       resolves, rather than linking to a 404. Confirmed live in the UI:
       the summary now renders directly in the model's right-hand Summary
       panel with no click required (this was the actual ask - "sędzia
       klikający po UI musi ją zobaczyć" - and it's now true without
       depending on the broken document route at all). Dedup keys on our
       own `[deadreckon]` marker prefix in the description, not on `url`
       (the url value itself changed once already during this fix, so
       keying on it would have left the old, dead link behind as a stale
       duplicate entry) - verified via the SDK that every model has
       exactly 1 `institutionalMemory` element after the fix, not 2.
     - **This is the fourth confirmed instance of the same pattern**
       (after `mlModelDeployment`'s unreadable relationships,
       `get_entities`/`get_lineage` dropping native fields for `mlModel`/
       `mlFeature`/`dataProcessInstance`): an MCP/SDK-level write succeeds
       and is readable via the API, but the product surface a judge
       actually clicks through cannot show it at all. This is the
       strongest candidate for the OSS issue in spec Sec.6 - see the TODO
       below, material to prepare (not send) next.
     - The Document entity itself is left as-is (still saved, still
       correctly attached via `relatedAssets`, still fully readable via
       `get_entities`/`grep_documents`/direct URN fetch) - it's still a
       real, valid writeback per spec Sec.5, just not one a UI-only judge
       will ever click into successfully in this DataHub version.
     - Deliberately did **not** touch the model's own `editableProperties`
       (description) to work around this - that field is the asset
       owner's description, ours to read, not to overwrite for a
       demo-convenience shortcut. `institutionalMemory` is a separate,
       additive aspect for exactly this kind of note, which is why it was
       used instead.

  6. **`customer_churn_predictor_v1` showing fabric `PROD` in its own URN
     while `deadreckon.deploymentEnvironment` says `STAGING` is not a
     data bug - it's a vocabulary collision, and it was fixed by renaming
     our property, not the data.** `seed/ml_lineage.py` sets `FABRIC =
     "PROD"` as a blanket constant for every ML entity's URN (`origin`
     key field) - this is DataHub's *catalog* environment (which
     metadata instance this describes: prod catalog vs a dev/test one),
     deliberately uniform across all our seeded entities since there's
     only one DataHub instance here, not five. It has nothing to do with
     where a given model is actually served, which is exactly what the
     separate `deadreckon.deploymentEnvironment` structured property
     tracks (and needs `MULTIPLE` cardinality, since unlike fabric - 1:1
     with the URN - a real model could be live in more than one serving
     environment at once). The confusion is that DataHub's own UI labels
     fabric as "Environment" too (visible in `get_lineage`'s own facets:
     `"field":"origin","displayName":"Environment"`), so a judge sees
     "Environment: PROD" (fabric, from the URN) right next to our
     property, and if *our* property were also called "Environment" (or
     even "Deployment Environment", close enough to read as the same
     concept), the two disagreeing looks like a data error instead of two
     orthogonal, both-correct facts. Fixed by renaming the structured
     property's `displayName` from "Deployment Environment" to
     "Undertow Serving Stage" (qualifiedName unchanged:
     `deadreckon.deploymentEnvironment`, so no data migration needed -
     `StructuredPropertyDefinitionClass` re-emission just updates the
     label) and tightening its `description` to spell out the distinction
     explicitly. Worth saying out loud in the video script too, since a
     judge who spots this before reading the tooltip will ask.

## DataHub documentation issues found

- `datahub init --username datahub --password datahub` run immediately after
  `datahub docker quickstart` reports "DataHub is now running" can fail with
  an opaque traceback: `AttributeError: 'NoneType' object has no attribute
  'get'` in `cli_utils.generate_access_token`. Root cause: the GraphQL
  response for `createAccessToken` apparently isn't reliably ready right at
  that moment even though `quickstart` already reported all containers
  healthy; the CLI does `response.json().get("data", {}).get(...)`, which
  crashes if `"data"` key is present but `null` (e.g. transient GraphQL
  error) instead of missing — `.get(..., {})` only guards a missing key, not
  an explicit `null` value. Retrying the exact same `datahub init` command
  ~60s later succeeded with no other changes. Two possible fixes worth
  upstreaming: (a) `quickstart`'s health check could wait until the
  createAccessToken mutation actually succeeds, not just container health;
  (b) `generate_access_token` should surface the GraphQL `errors` array
  instead of crashing with an unrelated `AttributeError`.

- `datahub datapack load showcase-ecommerce` reports "loaded successfully"
  as soon as MCPs are handed to the `datahub-rest` sink, but the search
  index (OpenSearch) then catches up asynchronously at a visibly throttled
  pace (observed ~1 entity/6s across `datasetindex_v2` etc. in this Docker
  quickstart, on 10GB RAM / 8 CPU allocated to Docker Desktop). A user who
  queries the UI or GraphQL search right after the CLI returns "success"
  will see a small fraction of the ~1049 entities and may reasonably
  conclude the load silently failed. The primary store (`system_metadata_service_v1`
  aspect count) reflects the full load almost immediately; only the search
  index lags. Worth a doc note on `datapack load` and/or `docker quickstart`
  that full searchability takes several minutes after the CLI reports
  success, with a way to poll for completion.

- `datahub-project/static-assets/datasets/nyc-taxi`: the README states the
  planted 3-day freshness gap in `nyc_taxi_pipeline.db` is "invisible in
  DataHub metadata... only detectable by querying actual MAX(timestamp) in
  each table," and this is accurate for the recipes as shipped — `ingest.yaml`
  / `ingest_pipeline.yaml` have no `profiling` block, and `add_metadata.py`
  only attaches tags/glossary/ownership, no timestamps. This directly
  conflicts with using this fixture for a metadata-only freshness detector:
  as shipped, the gap genuinely does not exist in the DataHub graph, only in
  the raw SQLite data. Fix applied here: enable DataHub's standard SQL
  profiler (`profiling.enabled: true`) on the datetime columns in a local
  copy of the ingest recipes, which surfaces real min/max timestamps into
  the `datasetProfile` aspect — still metadata, no runtime/serving access,
  and the underlying gap is genuinely baked into the community-authored
  data, not fabricated by us. Worth suggesting upstream that the recipe
  either enable profiling by default or the README be explicit that
  profiling is required for the staleness signal to be metadata-visible.

- Follow-up on the above: enabling profiling wasn't enough either. Every
  column in `nyc_taxi.db`/`nyc_taxi_pipeline.db`, including numeric ones
  (`fare_amount`, `trip_distance`), is declared `TEXT` in the SQLite schema
  (`.schema raw_trips` confirms it — looks like a `pandas.to_sql()` load
  with no dtype casting). DataHub's profiler happily computes `rowCount`
  (250000 vs 208675 — that gap alone already hints at the freshness issue)
  but returns `null` for `min`/`max` on every field, not just the datetime
  ones, because it doesn't treat TEXT columns as profileable for
  min/max. So per-column date bounds are not obtainable from this fixture
  via the standard SQL profiler at all, regardless of config.
  Separately: the real gap measured directly from the data is **9 days**
  (`raw_trips` max `tpep_pickup_datetime` = 2016-03-10, `staging_trips`/
  `mart_daily_summary` max `trip_date` = 2016-03-01), not the "3 days"
  the fixture's own README states — worth flagging upstream too.
  Final approach: `seed/nyc_taxi_freshness.py` reads the real MAX(timestamp)
  per table directly from the SQLite files with `sqlite3`, then emits a
  DataHub `operation` aspect (`lastUpdatedTimestamp`) per table, time-shifted
  so the freshest table lands on "now" and the others keep their real
  distance behind it. This is genuine metadata (the `operation` aspect is
  exactly what production pipelines use to record real update events),
  grounded in data the DataHub project actually shipped, not fabricated by
  us — it only makes an already-real gap visible in the graph.

- `datahub check plugins` requires the source-specific extra to be
  installed separately (`acryl-datahub[sqlalchemy]`) before `sqlalchemy`/
  `sqlite` ingestion works — reasonable, but worth noting since
  `acryl-datahub[datahub-rest]` alone (used for the CLI + Python SDK) does
  not pull it in.

- `datahub ingest -c <recipe.yaml>` crashes with
  `TypeError: Invalid argument(s) 'max_overflow' sent to create_engine()`
  whenever `profiling.enabled: true` is set on a file-based SQLite source.
  Root cause: `SQLAlchemySource._add_default_options()`
  (`datahub/ingestion/source/sql/sql_common.py`) unconditionally injects
  `max_overflow` into `config.options` whenever profiling is on, but
  SQLAlchemy's default pool for file-based SQLite is `NullPool`, which
  doesn't accept that kwarg. A comment in `mysql.py` references upstream
  PR #18319 fixing "the mirror-image case" for MySQL, implying the generic
  SQLAlchemy/SQLite path was never covered by that fix. Worked around by
  driving the ingestion through the Python `Pipeline` API instead of the
  YAML-only CLI, so `options.poolclass` can be set to
  `sqlalchemy.pool.QueuePool` (which does accept `max_overflow`) — not
  expressible in YAML since it needs an actual class object. See
  `seed/` and the (gitignored, local-only) `.fixtures/nyc-taxi/run_ingest.py`.
  Worth upstreaming: either have the generic SQL source force a
  pool-compatible engine when profiling is enabled, or skip injecting
  `max_overflow` for dialects whose default pool doesn't support it.

- `add_metadata.py` in the nyc-taxi fixture has a real bug: `attach_tags()`
  and `attach_glossary()` emit one MCP per (tag, table) pair, each
  constructing a fresh `GlobalTagsClass(tags=[single_tag])` /
  `GlossaryTermsClass(terms=[single_term])`. An MCP aspect emission is a
  full replace, not a merge, so only the *last* tag/term written per table
  survives. Confirmed via GraphQL: after running `add_metadata.py --all`
  as documented, every one of the 6 tables (both instances) ended up with
  exactly `pipeline_stage` as its only tag and only glossary term —
  `daily_refresh`, `time_series`, `pii`, `freshness_sla`, `empty_load` were
  all silently dropped, overwritten by later emissions for the same URN.
  Ownership was unaffected (each table only ever gets one ownership
  emission, so there's nothing to overwrite there) — that asymmetry is
  what pointed at the root cause. Found by manually diffing what the UI
  showed against what the README/script claims should be attached.
  Fixed here with `seed/fix_nyc_taxi_tags.py`, which computes the full set
  of tags/terms per table upfront and emits exactly one aggregated
  `GlobalTagsClass`/`GlossaryTermsClass` per table. Worth a PR upstream —
  `attach_tags`/`attach_glossary` need to batch by entity, not by
  (tag, entity) pair.

- `mcp-server-datahub`'s `get_entities`/`get_lineage` tools drop most
  native fields for `mlModel`, `mlFeature`, and `dataProcessInstance`
  entities specifically (see the 2026-07-26 detector-pipeline entry under
  Verification results above for the exact fields missing and how this
  was confirmed against raw GraphQL/the SDK returning the same data in
  full). This is the same class of read gap already found for
  `mlModelDeployment`, just for entity types this project still relies on
  rather than one it dropped - worth upstreaming as a documented
  limitation of the tool (or a fix to its entity-type-specific response
  builders) rather than something an agent should have to discover by
  trial and error per entity type.

- DataHub's GraphQL schema exposes `SchemaMetadata.createdAt` but no
  `lastModified`/`created` audit stamp, even though the underlying
  `SchemaMetadataClass` PDL aspect has both fields (`created`,
  `lastModified`, `deleted`, all `AuditStampClass`). Same gap for
  `ViewProperties` - no timestamp field at all in the GraphQL type. This
  means there is no metadata-graph-native way to answer "when did this
  schema/view definition last change" through GraphQL (and therefore
  through mcp-server-datahub, which sits on top of it) even though
  DataHub versions these aspects internally on every write. Worth an
  upstream doc note or GraphQL schema addition - absent that, this
  project plants its own `deadreckon.schemaChangedAt`/
  `deadreckon.definitionChangedAt` structured properties instead (see
  `seed/inject_faults.py`).

- `datahub docker quickstart`'s preflight memory check (`MIN_MEMORY_NEEDED
  = 4.3` GB in `datahub/cli/docker_check.py`) is set below what the stack
  it starts actually uses. Measured here with the showcase datapack
  loaded: the six containers idle at **~4.23 GiB combined** (GMS 1.60,
  OpenSearch 1.30, kafka-broker 0.78, frontend 0.70, mysql 0.56, actions
  0.24) - that is ~4.54 GB, already over the threshold before any indexing
  work. The comment above the constant ("Docker seems to under-report
  memory allocated, so we also need a bit of buffer") suggests it was
  picked as "4 GB plus buffer" rather than measured against the running
  stack. Caveat on our own evidence: we never ran the stack *at* a 4.3 GB
  allocation, only measured footprint on a 9.7 GB one - so this is a
  constant-vs-measurement mismatch, not a demonstrated failure. Documented
  in our README as an 8 GB requirement.

- **OpenSearch dying roughly daily is a zombie-reaping bug, NOT memory -
  and our first diagnosis of it was wrong.** Corrected 2026-07-28 after
  finding upstream issue
  [#18657](https://github.com/datahub-project/datahub/issues/18657), filed
  a day earlier by someone else with a far better root cause than ours.
  The `opensearch` healthcheck runs `curl` in-container every 5s, but PID
  1 there is the JVM, which never reaps orphaned children, so every
  healthcheck leaves a permanent zombie. PID slots fill and the JVM
  eventually cannot create a thread:
  `OutOfMemoryError: unable to create native thread ... pthread_create
  failed (EAGAIN)`, with `OOMKilled=false` and free memory to spare.
  Confirmed independently on this machine: **1060 zombies out of 1062
  processes** after 90 minutes of uptime (~708/hour, against the 720/hour
  a 5s interval predicts), while the JVM held only **140** real threads.
  Fix is `init: true` on the service so Docker runs tini as PID 1; shipped
  here as `docker-compose.opensearch-init.yml`.

  **The methodological error is worth remembering, because it was the
  whole reason the wrong theory looked plausible:** we counted "threads"
  with `ls /proc/*/task | wc -l`, which walks the task directory of
  *every process in the container*. With thousands of zombies present that
  returns a huge number (3042 at the time) that looks exactly like runaway
  thread creation. The right probe for "how many threads does this process
  have" is `ls /proc/<pid>/task | wc -l` against the specific PID - here
  `/proc/1/task`, giving 140. Two further signals we had and did not
  weigh: free memory was ~5.5 GB at the time of measurement (a 1 MB stack
  allocation should not fail), and `OOMKilled=false` with nothing in
  `dmesg` points at a *resource-limit* death rather than a memory kill.
  Lesson: when a JVM says "possibly out of memory **or process/resource
  limits reached**", check the second clause before building a theory on
  the first.

  Platform difference worth noting: our `pids.max` reads `max` (Docker
  Desktop sets no cgroup PID limit), whereas the upstream reporter's was
  18864. Same leak, different binding limit, so time-to-crash varies by
  platform - the fix is the same either way.

  **Filed upstream 2026-07-28** as a confirming comment on #18657:
  https://github.com/datahub-project/datahub/issues/18657#issuecomment-5108977744
  (draft kept at `docs/oss/comment-18657-zombie-reaping.md`). It includes
  the correction of our own misdiagnosis and the `/proc/*/task` measurement
  error, on the grounds that the next person to land on that issue with the
  same wrong hunch benefits more from seeing it than we lose by admitting
  it - and our repo is public, so silence would be the worse look.

- The standalone `Document` entity (created via `save_document`/
  `createDocument`) has **no working profile route anywhere in this
  DataHub version's frontend** - confirmed 404 two independent ways: a
  direct URL guess (`/documents/<urn>`) and the UI's own native
  "Resources" card on the model it's attached to via `relatedAssets`
  (which links to the exact same dead route). The entity is fully
  writable (MCP `save_document`) and fully readable via the API
  (`get_entities`, `grep_documents`, direct URN fetch, `relatedDocuments`
  on the attached asset) - it just cannot be opened by clicking through
  the product. This is the fourth confirmed instance of the same
  pattern in this project (after `mlModelDeployment`'s unreadable
  relationships and `get_entities`/`get_lineage` dropping native fields
  for `mlModel`/`mlFeature`/`dataProcessInstance`, both above): an
  agent-facing write succeeds and round-trips through the API, but nothing
  in the actual product can display it. Worth an upstream fix (a real
  Document profile page) or, short of that, a docs note that Documents
  are API/MCP-only in this version and should be surfaced via
  `institutionalMemory`/tags/properties on the entities they're attached
  to if a human needs to see them in the UI.

  **Filed upstream 2026-07-28** as a comment on #18675 (someone else's
  issue about Documents not appearing in search, which we independently
  reproduced on the same version):
  https://github.com/datahub-project/datahub/issues/18675#issuecomment-5108983658
  (draft at `docs/oss/comment-18675-document-visibility.md`). Went there
  rather than opening a third document-related issue; the no-route finding
  is offered for splitting out if maintainers consider it distinct from
  the indexing question.

  Re-measured immediately before filing, on documents ~3h old (i.e. well
  past any indexing window): direct URN fetch returns the title,
  `relatedDocuments` on the attached model returns 1, and
  `searchAcrossEntities` with `types:[DOCUMENT]` returns **0** for
  "Model Risk Assessment", "taxi_eta_predictor_v1" and "deadreckon" alike.

## Sesja 28.07 - decyzje

Skrót do wznowienia pracy po `/clear`. Szczegóły w commitach `1cab4d7`,
`4f44376`, `80233f2`, `8aa2c8a`, `85e5208`.

### 1. Audyt scoringu (A1-A3) + próg MEDIUM 0.7

Przestrzeń score jest **dyskretna** - waga detektora x blast radius daje
9 osiągalnych wartości, nie kontinuum. Dlatego "procent maksimum" to zły
model myślowy; progi rozdzielają klastry, nie procenty.

- **A3: `blast_radius` sumował środowiska -> teraz bierze maksimum.**
  Model już w PROD nie staje się groźniejszy przez to, że stoi też w
  STAGING - ekspozycja produkcyjna pochłania wszystko. Sumowanie miałoby
  sens dla *instancji* (PROD-EU + PROD-US), ale nasz słownik to
  *szczeble*, a szczeble się maksymalizuje. Efekt uboczny: sufit spadł z
  nieosiągalnego 4.0 na realne **3.0**, które w demie jest zajęte.
- **A1: dominacja środowiska jest zamierzona i poprawna.** Model
  produkcyjny z najsłabszym detektorem bije martwy model w STAGING z
  najmocniejszym, bo pierwszy kosztuje pieniądze dziś, a drugi nic aż do
  promocji. Niezmiennik "środowisko wybiera pasmo, detektor porządkuje
  wewnątrz pasma" jest teraz **pilnowany testem** po wszystkich
  kombinacjach detektorów, a nie trzyma się przypadkiem.
- **A1: `UNDEPLOYED_BLAST_RADIUS` -> `LATENT_RISK_FLOOR`.** Model bez
  wdrożeń ma promień rażenia **zero**; 0.5 to podłoga utrzymująca ryzyko
  utajone w rankingu, nie pomiar "pół STAGING-a".
- **A2: score bierze maksimum, krotność łamie remisy w sortowaniu.**
  Wariant z premią za wielość znalezisk *wewnątrz* score przeliczyłem -
  podnosi sufit do 3.6-4.3 i odtwarza dokładnie problem nieosiągalnego
  maksimum, który właśnie naprawiliśmy. Dlatego krotność siedzi w
  `ModelRiskScore.sort_key` i w `deadreckon.findingCount`.
- **Próg MEDIUM 0.8 -> 0.7.** 0.8 stało *dokładnie na osiągalnej
  wartości* (D1 x STAGING). Zmiana wagi D1 na 0.79 po cichu przerzuciłaby
  całą klasę modeli z MEDIUM do LOW. Klasyfikacja identyczna dla każdej
  osiągalnej wartości, tylko bez kruchości. HIGH=2.0 było już w luce.

### 2. Model trójstanowy - dlaczego INSUFFICIENT_DATA jest poza riskScore

`PASS` i `INSUFFICIENT_DATA` to **różne twierdzenia**: "sprawdziłem, jest
dobrze" vs "nie miałem czym sprawdzić". Wcześniej D1 zwracał to samo
(brak znalezisk) i przy świeżym datasecie, i przy braku aspektu
`operation` - czyli raportował niezmierzony model jako czysty. To jest
dokładnie ta cicha awaria, którą projekt ma wykrywać, popełniana przez
sam projekt.

Ryzyko i niewiedza **nie mogą wpaść do jednego skalara**, bo oba tracą
znaczenie. Dlatego pokrycie jest osobnym sygnałem
(`deadreckon.assessmentCoverage`, np. "2/3") plus tag
`undertow:unassessable`, gdy żaden detektor nie wydał werdyktu. Model
nieoceniony ma score 0.0 tak samo jak czysty - **pokrycie jest jedyną
rzeczą, która je odróżnia**, i dashboard ma obowiązek to pokazać.

Zasada agregacji: znalezisko zawsze wygrywa jako nagłówek; w razie jego
braku *jakikolwiek* niesprawdzony podmiot degraduje detektor do
INSUFFICIENT_DATA, bo "czysto" wymaga, żeby naprawdę wszystko obejrzeć.

Efekt na żywych danych: żadna tabela Snowflake z `showcase-ecommerce` nie
ma aspektu `operation`, więc D1 nie jest w stanie ocenić trzech z pięciu
modeli. **Ten brak pochodzi z oryginalnego datapacka, nie od nas** -
zweryfikowane dwustronnie: emitujemy `OperationClass` wyłącznie dla
`sqlite`/nyc_taxi i nigdy nic nie usuwamy, a w grafie 6 z 77 datasetów ma
ten aspekt i wszystkie są nasze.

### 3. Determinizm czasu - aspekty timeseries dopisują, nie zastępują

**Sedno:** `DataProcessInstanceRunEvent` i `operation` to aspekty
*timeseries*. Ponowny zasiew **dokłada** zdarzenia zamiast je nadpisać,
więc wynik zależał od **historii zasiewów**, nie od bieżącego stanu.
Objaw: po teście z przesuniętym zegarem model wrócił z datą treningu
**w przyszłości**, co przewróciło werdykty D2/D3.

Naprawa dwutorowa:
- Czas przebiegu treningowego czytamy z
  `DataProcessInstanceProperties.created` - aspekt **wersjonowany**,
  który reseed faktycznie nadpisuje.
- Świeżość datasetu: ocena "na moment T" **ignoruje zdarzenia
  zaraportowane po T**. To poprawne semantyki point-in-time i przy okazji
  uodparnia na zanieczyszczony graf.

**Dowód:** `detectors/clock.py` daje wspólne "teraz" dla seedów i
detektorów (`DEADRECKON_NOW` / `--as-of`) *wyłącznie po to, żeby teza
była testowalna*. Procedura: zasiej + oceń, przesuń zegar o 10 dni,
zasiej ponownie + oceń, `diff` macierzy 5x3. Przeprowadzony dwukrotnie
(raz po zmianie lineage'u) - pusty.

**Uwaga na przyszłość:** mój *pierwszy* dowód przeszedł przypadkiem, bo
akumulacja zdarzeń była monotoniczna. Zielony wynik testu determinizmu
nie znaczy nic, jeśli nie sprawdzi się też stanu grafu.

`run_detectors.py` ostrzega, gdy najświeższy dataset przekroczył próg D1
- dryf seeda ma być głośny, nie cichy. Przed nagraniem: **przesiać**.

Przy okazji: `seed/nyc_taxi_freshness.py` emitował przez
nieuwierzytelniony `DatahubRestEmitter` (401) - teraz `get_default_graph()`
jak reszta.

### 4. Kontrakt JSON v1.0.0 - co przyjęliśmy i odrzuciliśmy z recenzji Kimi

Recenzję zrobiła Kimi CLI - **inna linia modelu i faktyczny odbiorca**
(to ona buduje dashboard), więc to recenzja konsumenta, nie drugie
spojrzenie tego samego modelu. Werdykt: nic nie blokowało zbudowania UI,
ale kilka kształtów wypychało pracę do frontendu.

**Przyjęte:** grupowanie luk po aspekcie + `missing` -> `aspect` (nazwa
była przeciążona, a *nasz własny* zapis do grafu już grupował - dwie
powierzchnie tej samej informacji muszą mieć ten sam kształt); findings
pod `detectors.{D}.findings` (join znika z UI); `group.url`;
`detectors_meta`; `lineage_path` per znalezisko; `evidence`
udokumentowane jako **różne per detektor** zamiast udawania worka
(normalizacja odłożona świadomie jako refactor).

**Odrzucone, z powodami:**

- **`tags` zostają.** Kimi wyprowadziła `at_risk` jako "ma znaleziska" -
  **to błąd rzeczowy**. `at_risk` jest bramkowane **severity**, nie
  liczbą znalezisk: model niewdrożony z D2 ma score 0.5 -> LOW ->
  `at_risk: false` przy `finding_count: 1`. Frontend na tej regule
  narysowałby czerwoną flagę tam, gdzie graf jej nie ma, i **rozjechałby
  się z DataHubem**. Ale wina była po naszej stronie: w dumpie nie było
  ani jednego takiego modelu (ani żadnego `unassessable`), więc recenzent
  nie miał jak tego zobaczyć. Stąd `examples/sample-run-edge-cases.json` -
  syntetyczny, ale przez **ten sam serializer**, trzymany osobno, żeby
  macierz demo została nietknięta.
- **Cechy i przebiegi treningowe NIE dostają URL-i.** Zweryfikowałem
  empirycznie tylko trasy `/dataset/` i `/mlModels/`. Trasy dla
  `mlFeature` i `dataProcessInstance` są niesprawdzone, a precedens jest
  świeży: encja `document` nie ma **żadnej** działającej trasy, przez co
  wygenerowaliśmy linki dające 404 i trzeba je było wycofać. **Sam URN
  jest lepszy niż link w 404** - sędzia w niego kliknie.
- `assessment_document_urn` zostaje (dowód, że writeback się wykonał -
  a to jest wprost punktowane), `blast_radius_stage` odpuszczony
  (`serving_stages` już niesie nazwy), żadnych cięć pól wyprowadzalnych
  (rozmiar payloadu nie jest naszym problemem).

Sesja recenzji: `kimi -r session_74d50759-f59a-4fa0-a02f-974bfe18b96d`.

## Audyt sesji 2026-07-26

Poniżej pełny, dosłowny przegląd tej sesji Claude Code, dla drugiego
asystenta oceniającego zgodność z PROMPT A z `plan-pracy-undertow.md`.
Zakres pracy tej sesji: dokończenie weryfikacji mutacji MCP, usunięcie
testowego dokumentu, `seed/ml_lineage.py` i weryfikacja Bramki 1. Poniżej
tylko fakty, bez oceny.

### 1. Komendy shell dotykające plików spoza katalogu repo (`.../deadreckon`)

- `cat "/Users/jacek/.claude/projects/-Users-jacek-Documents-DataHub-The-Agent-Hackathon/memory/MEMORY.md"` —
  próba odczytu pliku pamięci Claude Code (katalog opisany w moim system
  prompcie jako właściwe miejsce na tego typu dane, poza repo projektu).
  Plik nie istniał (exit code 1), nic nie odczytano.
- `ls -la "/Users/jacek/.claude/projects/-Users-jacek-Documents-DataHub-The-Agent-Hackathon/memory/"` —
  listing tego samego katalogu pamięci; był pusty.
- `ls -la "/Users/jacek/Documents/DataHub The Agent Hackathon"` — listing
  katalogu nadrzędnego wobec repo (zawiera repo `deadreckon` jako
  podkatalog plus dwa pliki planu i `.claude/`).
- `ls -la "/Users/jacek/Documents/DataHub The Agent Hackathon/.claude"` —
  listing katalogu `.claude` na poziomie nadrzędnym (poza repo); pokazał
  tylko nazwę/rozmiar pliku `settings.local.json` (164 B), **treść tego
  pliku nigdy nie została odczytana**.
- `grep -n "zweryfikowa\|weryfikac" ".../plan-pracy-datahub-agent-hackathon.md"` —
  plik poza repo (katalog nadrzędny), tylko odczyt/grep, bez modyfikacji.
- `grep -n -i "weryf\|§4\|dnia 1\|dzień 1\|mcp" ".../plan-pracy-datahub-agent-hackathon.md" | head -60` —
  jw., odczyt/grep poza repo.
- `grep -n -i "zweryf\|verif" ".../plan-pracy-datahub-agent-hackathon.md" ".../plan-pracy-undertow.md"` —
  jw., dwa pliki poza repo, tylko grep.
- `Read` (narzędzie, nie Bash) na `.../plan-pracy-undertow.md`, dwukrotnie
  (linie 1–80, potem 80–140) — plik poza repo, tylko odczyt.
- `cat ~/.datahubenv; env | grep -i datahub; cat ".../deadreckon/.env.example"` —
  **ta komenda została ODRZUCONA przez Ciebie przed wykonaniem** (permission
  prompt), nic się nie wykonało. Zobacz sekcję 3 — to najważniejszy fakt
  tego audytu.
- `[ -f ~/.datahubenv ]` (test istnienia pliku, bez odczytu treści) oraz
  `printenv "$v" >/dev/null 2>&1` dla `DATAHUB_GMS_TOKEN`/`DATAHUB_GMS_URL`
  (przekierowane do `/dev/null`, więc wartość — gdyby istniała — nigdy nie
  trafiła do mojego outputu) — wykonane na Twoją wyraźną prośbę, po tym jak
  odrzuciłeś powyższą próbę `cat`. Wynik: oba env var "not set", plik
  istnieje ("exists (not reading contents)").
- `find / -maxdepth 6 -iname "datahub-project" 2>/dev/null | head` —
  **przeszukanie systemu plików od katalogu głównego `/`** (ograniczone do
  głębokości 6, tylko dopasowanie nazw, `2>/dev/null` tłumi błędy
  uprawnień). Nic nie znaleziono (pusty wynik). To jedyna komenda w tej
  sesji, która przeszukiwała system plików poza katalogiem roboczym.
- Wewnętrzne odczyty `~/.datahubenv` przez bibliotekę `datahub` (SDK/CLI),
  NIE przeze mnie bezpośrednio: za każdym razem, gdy uruchamiałem
  `datahub delete ...` (6 razy) albo skrypt Python używający
  `get_default_graph()` (3 razy: test `schemaField` w `mlFeature.sources`,
  `seed/ml_lineage.py` dwukrotnie, plus jednorazowy skrypt tworzący
  structured property), biblioteka sama odczytywała `~/.datahubenv`, żeby
  się uwierzytelnić do `localhost:8080`. Nigdy nie zrobiłem tego przez
  `Read`/`cat` na tym pliku — zob. sekcję 3 co do tego, co z tego trafiło
  do mojego outputu.
- Plik-zrzut wyniku narzędzia utworzony automatycznie przez system
  (nie przeze mnie, nie przez `Write`) pod
  `/Users/jacek/.claude/projects/-Users-jacek-Documents-DataHub-The-Agent-Hackathon/7b9c2aba-8814-4bbb-bc77-9722d4e9e564/tool-results/mcp-datahub-get_entities-1785044716331.txt` —
  jeden `get_entities` zwrócił wynik przekraczający limit tokenów; harness
  sam zapisał go do tego pliku (poza repo). Odczytałem go potem przez
  `jq -r '...' "<ta ścieżka>"` (dwukrotnie, różne zapytania `jq`), nigdy nie
  modyfikowałem.
- Wszystkie pozostałe komendy Bash w tej sesji (git, python3 -c
  introspekcja `datahub` w `.venv`, `pip show`, `find .venv ...`,
  uruchomienia skryptów `seed/*.py`) operowały wyłącznie wewnątrz
  `.../deadreckon` (repo lub jego `.venv`).

### 2. Uprawnienia, o które prosiłem, i ich zakres

Nie mam wglądu w to, jaki zakres zgody wybrałeś w oknie uprawnień (czy
kliknąłeś "tak, tylko tym razem" czy "tak, zawsze zezwalaj na X") — z mojej
strony widoczne jest wyłącznie to, czy wywołanie narzędzia się powiodło,
czy zostało odrzucone. Jedyne odrzucenie w całej sesji to `cat ~/.datahubenv`
opisane w sekcji 1 i 3 — po nim sam poprosiłeś mnie o bezpieczniejszą wersję
komendy, którą wykonałem. Nie proponowałem ani nie prosiłem o żadne trwałe
rozszerzenie uprawnień (np. "zawsze zezwalaj na Bash bez potwierdzenia",
"zawsze zezwalaj na odczyt plików spoza repo") — każde wywołanie narzędzia
w tej sesji było pojedynczym, konkretnym poleceniem z własnym promptem
uprawnień (o ile Twoja konfiguracja w ogóle o niego pyta dla danego typu
komendy — tego też nie widzę).

### 3. Miejsca, gdzie potencjalnie mógł przejść przeze mnie sekret

- **Zablokowana próba (nie wykonała się):** `cat ~/.datahubenv; env | grep
  -i datahub; ...`. Gdyby się wykonała i gdyby w środowisku powłoki był
  ustawiony np. `DATAHUB_GMS_TOKEN`, `env | grep -i datahub` wypisałby jego
  **pełną, niezamaskowaną wartość** do mojego outputu. Odrzuciłeś to, zanim
  się wykonało — token (jeśli był w env) nigdy do mnie nie trafił tą drogą.
- **Zamaskowany token w logach CLI (7 wystąpień):** każde wywołanie
  `datahub delete --urn ...` (soft/hard) drukuje na stdout linię w stylu
  `Using DataHubGraph: configured to talk to http://localhost:8080 with
  token: eyJh**********t-_Q` — maskowanie robi sam CLI, nie ja. Ten
  identyczny zamaskowany fragment (`eyJh**********t-_Q`) pojawił się w
  wynikach narzędzi, które przetworzyłem, dokładnie 7 razy: usunięcie
  testowego dokumentu (soft), usunięcie testowej `mlFeature` (hard), 4×
  usunięcie encji `mlModelDeployment` (hard, w pętli), 1× ponowna próba tej
  samej encji (soft). Widoczne jest tylko pierwsze 4 i ostatnie 4 znaki
  base64 (`eyJh` = standardowy początek nagłówka JWT, `t-_Q` = końcówka) —
  środek jest gwiazdkami. Pełna wartość tokenu nigdy nie pojawiła się w
  żadnym outpucie, który widziałem.
- **Odczyt `~/.datahubenv` przez SDK bez wyświetlenia treści:** opisane w
  sekcji 1 — `get_default_graph()` i `datahub` CLI czytają ten plik
  wewnętrznie, żeby się uwierzytelnić; żadna z tych operacji nie zwróciła
  mi treści pliku ani pełnego tokenu w odpowiedzi narzędzia.
- Nieudana próba surowego zapytania HTTP (`urllib.request` w Pythonie) do
  `http://localhost:8080/aspects/...` bez tokenu — zakończona `401
  Unauthorized`, żaden sekret nie został użyty ani ujawniony (bo go tam
  nie podałem).
- Brak innych miejsc w tej sesji, gdzie hasło/klucz/token mogłyby
  przechodzić przez argumenty komend, zmienne środowiskowe wypisywane
  wprost, czy logi — poza powyższymi trzema przypadkami.

### 4. Pliki utworzone/zmodyfikowane POZA repo projektu

- **Utworzone/zmodyfikowane przeze mnie bezpośrednio: żadne.** Wszystkie
  moje `Write`/`Edit` w tej sesji dotyczyły plików wewnątrz
  `.../deadreckon` (`NOTES.md`, `seed/ml_lineage.py`).
- **Utworzony automatycznie przez system (nie przeze mnie):** plik-zrzut
  `tool-results/mcp-datahub-get_entities-1785044716331.txt` pod
  `~/.claude/projects/-Users-jacek-Documents-DataHub-The-Agent-Hackathon/7b9c2aba-8814-4bbb-bc77-9722d4e9e564/tool-results/`
  — opisany w sekcji 1, efekt uboczny zbyt dużego wyniku narzędzia
  `get_entities`, zapisany przez harness Claude Code, nie przeze mnie
  wprost. Tylko odczytany (`jq`), nie modyfikowany.
- Katalog scratchpad wskazany w moim system prompcie
  (`/private/tmp/claude-501/.../scratchpad`) — **nie użyty w ogóle** w tej
  sesji.
- Poza DataHub (dane w bazie grafu, nie pliki) i repo `deadreckon`, nie
  utworzyłem ani nie zmodyfikowałem żadnych innych plików na tej maszynie.

### 5. Połączenia sieciowe/API poza DataHub (localhost) i GitHub

- **Nie znaleziono żadnych.** Wszystkie wywołania sieciowe w tej sesji
  szły albo do DataHub GMS na `http://localhost:8080` (przez narzędzia
  `mcp__datahub__*`, przez `datahub` CLI, przez Python SDK
  `get_default_graph()`/`DatahubRestEmitter`, oraz jedno bezpośrednie
  zapytanie `urllib` opisane w sekcji 3), albo do GitHub przez `git push`
  na `https://github.com/AnubisCrypto666/deadreckon.git` (na Twoje
  wyraźne polecenie "push it", dwa razy w tej sesji).
- `ToolSearch` (ładowanie schematów narzędzi MCP) i `AskUserQuestion` to
  wewnętrzne mechanizmy harnessu Claude Code, nie połączenia do zewnętrznych
  usług w rozumieniu tego audytu.
- Nie wywołałem `WebFetch` ani `WebSearch` ani żadnego innego serwera MCP
  poza `datahub` w tej sesji.

## TODO dashboard (odłożone)

- 2026-07-29: **Domyślny fixture ma zostać wbudowany bezpośrednio w
  `dashboard/index.html` jako literał** (embedded JSON), żeby dwuklik na
  pliku działał od razu, bez serwera HTTP. Wczytywanie innego pliku
  (drag & drop / file picker) zostaje dokładnie jak jest teraz — jako
  podmiana domyślnych danych, nie jedyny sposób wczytania czegokolwiek.
  **Powód:** obecnie strona domyślnie robi
  `fetch("../examples/sample-run.json")`, co pod `file://` blokuje CORS
  (przeglądarka odmawia fetch), więc samo otwarcie pliku dwuklikiem
  pokazuje błąd wczytywania i wymaga ręcznego odpalenia serwera
  (`npx serve .` / `python -m http.server`, patrz `dashboard/README.md`).
  Instrukcja "najpierw uruchom serwer" zmniejsza szansę, że sędzia w
  ogóle zobaczy dashboard.
  **Zakres i timing:** robimy to w paczce poprawek **po widoku 4.3**, nie
  teraz. Widok 4.1 jest już zamknięty i scommitowany (`68d4292`) — nie
  otwierać/nie modyfikować go w tym celu przed tamtym momentem.

## Notatki do skryptu wideo (Prompt C)

- 2026-07-29: **Widok 4.2 (Ranking & Coverage) — kolejność ujęć.** Na
  `examples/sample-run.json` strefa "UNVERIFIED — NOT THE SAME AS SAFE"
  jest **pusta**, i to jest zaleta, nie brak: pokazuje, że pole istnieje
  z zasady (żaden model w prawdziwym fixture'cie akurat go nie
  potrzebuje), a nie zostało dorysowane pod jeden konkretny przypadek.
  Efekt "wow" tego widoku pojawia się dopiero po podmianie pliku na
  `examples/sample-run-edge-cases.json` — punkt `session_ltv_predictor_v2`
  (score 0.0, coverage 0/3, `tags.unassessable: true`) wpada w tę strefę
  na oczach widza, obok punktów, które mają ten sam score 0.0 z innego
  powodu (`taxi_fare_predictor_v1`, pełne pokrycie).
  **Scenariusz nagrania:** pokazać oba stany po kolei — najpierw czysty
  przebieg na `sample-run.json` (strefa pusta, widać że pole istnieje
  z założenia), potem podmiana pliku przez file picker/drag&drop na
  `sample-run-edge-cases.json` i punkt lądujący w strefie na żywo. Ok.
  10 sekund kadru na ten fragment.

- 2026-07-30: **Osobne ujęcie: zapis do grafu widoczny na żywo w UI
  DataHuba.** Adresuje wprost premiowane kryterium "contribute back to
  the graph" — nie może zostać tylko w README/opisie zgłoszenia, musi
  być pokazane, nie tylko opisane.
  **Co pokazać:** strona encji `customer_churn_predictor_v2` w DataHub
  UI — widoczny tag `undertow:at-risk` na encji oraz trzy adnotacje
  `[deadreckon]` w zakładce Documentation, w tym ta, która mówi wprost,
  czego detektor **nie** sprawdził (nie tylko co znalazł).
  **Przejście w kadrze:** dashboard (macierz albo drill-down 4.3) →
  kliknięcie deep-linku modelu → ta sama encja otwarta w DataHub UI, tak
  żeby widz zobaczył, że to jeden i ten sam model, nie dwa osobne demo.

## Judge-simulation review (Kimi, read-only, 2026-07-30)

Kimi reviewed the repo cold, as a hackathon judge with ~3 minutes of
attention, read-only (verified via `git status` afterward — zero files
touched). Five fixed questions, no code-review/architecture feedback
requested. Session: `kimi -r session_fb43ec7a-5331-4fdd-9f3d-055c453cc9b7`.

**Answered correctly, no gaps, archived here per instruction (not
revisited before submission):**

- Q1 (what does the project do): correct two-sentence summary from
  README + dashboard alone.
- Q2 (INSUFFICIENT_DATA vs PASS, why it matters): correct, including
  the "different claims" framing and coverage-as-separate-signal point.
- Q4, the "did double-click work" half: yes — `open dashboard/index.html`
  (CLI equivalent of a double-click) opened the dashboard immediately,
  no server, no install step, no error.
- Q5 (what's missing to believe it works on real data): correct and
  matches the project's own disclosed constraints (embedded fixture
  only in the dashboard; full agent run needs live DataHub + Docker +
  the separately-cloned nyc-taxi fixture) — not a gap, an accurate
  read of a limitation this project already discloses.

**The two gaps shown to Jacek separately** (writeback claim only
verifiable via README prose, not independently from the repo without a
live DataHub instance; and the `python -m http.server` fallback command
in `dashboard/README.md` failing on systems with only `python3`) are
not archived here — see chat for the decision on whether/how to act on
them before submission.

## Wideo — zamknięte (2026-07-31)

Nagrane, wrzucone na YouTube jako **publiczne**, z napisami
(autosynchronizacja z tekstu `submission/video-script.md`). Czas
**2:49**, poniżej limitu 3:00.

Link: https://youtu.be/RruTMrAL2lE

## TODO przed finalną wysyłką (8 sierpnia)

Cztery pozycje, w tej kolejności:

1. **Audyt repo w czystym środowisku** — fresh clone (nie lokalny
   working dir), pozabijane procesy na porcie 8000, przejście README
   krok po kroku tak jak zrobiłby to sędzia. Dwie ścieżki osobno:
   dwuklik na `dashboard/index.html`, i pełny setup agenta od zera.
   Powód: 2026-07-30, test fallbacku Pythona w `dashboard/README.md`
   dał fałszywy pozytyw, bo na porcie 8000 wisiał już serwer z
   wcześniejszej sesji weryfikacyjnej — `curl` dostał odpowiedź mimo że
   sama komenda (`python` zamiast `python3`) w ogóle się nie wykonała
   (`command not found`). Fix (`python3`) już scommitowany (`97155f4`),
   ale sam test trzeba powtórzyć czysto, żeby mieć pewność, że to nie
   jedyne miejsce, gdzie środowisko dewelopera maskuje błąd instrukcji.

2. **Skan repo pod kątem sekretów** — tokeny, klucze, `.env`,
   zamaskowane fragmenty w logach/notatkach, w bieżącym stanie **i** w
   całej historii commitów, nie tylko HEAD.

3. **Rotacja tokenu DataHuba** — nowy access token, unieważnienie
   obecnego (tego używanego przez całą tę sesję developerską). Powód:
   zamaskowane fragmenty tokenu (`eyJh...t-_Q`) przewinęły się przez
   logi CLI kilkukrotnie podczas developmentu (patrz sekcja "Audyt
   sesji 2026-07-26"). Sam token nigdy nie wyciekł w pełnej postaci,
   ale to tania, standardowa higiena przed publikacją repo — robimy na
   końcu, nie wcześniej, żeby nie przerywać obecnego tokenu w środku
   prac. Dodatkowa weryfikacja 2026-07-26 (audyt przed pushem commita
   f02f933): pełna wartość tokenu żyje wyłącznie w `~/.datahubenv`,
   poza repo, i nigdy nie trafiła do historii gita w żadnej postaci —
   potwierdzone zarówno przez grep całej historii (`git log --all -p`)
   pod kątem wzorców tokenu/JWT/URL-i z credentialami (zero trafień
   poza zamaskowanym `eyJh**********t-_Q` cytowanym w tym samym
   audycie), jak i niezależnie przez Jacka w terminalu. Ręczna czynność
   w UI DataHuba — robi ją Jacek, ja tylko prowadzę.

4. **Trzy niezłożone luki w `mcp-server-datahub`** — mamy zapas czasu
   przed deadline'em, więc je składamy. Materiał źródłowy już w tym
   pliku (sekcja "2026-07-26: D1-D3 detectors..."): `get_entities`
   ucina natywne pola osobno dla `mlModel` (brak `hyperParams`,
   `trainingMetrics`, `mlFeatures`, `groups`, `trainingJobs`), osobno
   dla `mlFeature` (brak `sources`, `dataType`, `customProperties`), i
   osobno dla `dataProcessInstance` (prawie nic poza gołym `urn`,
   `get_lineage` też pokazuje go jako pusty stub bez timestampu). Trzy
   osobne, niezależnie reprodukowalne zgłoszenia, jedno per typ encji —
   dodatek do dwóch komentarzy z 28.07 (`#18657`, `#18675`), nie
   zamiennik. Ręczna czynność (wysyłka z konta GitHub Jacka) — robi ją
   Jacek, ja przygotowuję treść i prowadzę.

Na koniec (po tych czterech): checklista do formularza Devpost.
