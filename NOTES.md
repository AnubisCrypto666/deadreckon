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
