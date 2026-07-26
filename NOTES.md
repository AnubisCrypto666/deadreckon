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

## TODO przed finalną wysyłką (8 sierpnia)

- Rotacja tokenu DataHuba: wygenerować nowy access token, unieważnić obecny
  (ten używany w tej sesji). Powód: zamaskowane fragmenty tokenu (eyJh...t-_Q)
  przewinęły się przez logi CLI kilkukrotnie podczas developmentu (patrz sekcja
  "Audyt sesji 2026-07-26"). Sam token nigdy nie wyciekł w pełnej postaci, ale
  to tania, standardowa higiena przed publikacją repo - zrobić na końcu, nie
  teraz, żeby nie przerywać obecnego tokenu w środku prac.
