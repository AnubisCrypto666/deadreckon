# Build notes

Running log of decisions, verification results, and DataHub documentation
issues found while building deadreckon. Documentation issues here are raw
material for OSS doc-fix contributions.

## Decisions

- 2026-07-25: Repo name `deadreckon`, Apache 2.0 license.
- 2026-07-25: Project targets Python 3.10+, developed against 3.11 via `uv`.

## Verification results

(filled in as milestones close — see plan §4 "do zweryfikowania w dniu 1")

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
