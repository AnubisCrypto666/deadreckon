# deadreckon

**Build with DataHub: The Agent Hackathon — Challenge #3, Production ML Agents**

Models in production rarely fail loudly. More often they rot quietly, because
something changed four hops upstream in the data chain and nobody connected
the dots between the table, the feature, the training run, and the deployed
endpoint.

deadreckon is an agent that walks full ML lineage in DataHub, detects three
classes of silent failure using metadata alone, scores them by weight and
blast radius, and writes the risk assessment back into the graph next to the
model it concerns.

**Design constraint, not a shortcut:** deadreckon operates on metadata only.
No access to model runtime, no serving, no drift computed on live
predictions. ML teams typically have model monitoring and data monitoring as
two separate systems — the silence between them is where money goes missing.

## Status

ML lineage seeded, all three detectors (D1-D3) implemented, scored, and
writing risk assessments back into the graph end-to-end. Dashboard next.
See `NOTES.md` for build-in-progress notes and documentation issues found
along the way.

## Prerequisites

**Allocate at least 8 GB of RAM to Docker, and keep 13 GB of free disk.**

Docker Desktop → Settings → Resources → Memory, then *Apply & restart*.
(On Colima: `colima start --memory 8`.)

This is higher than the 4.3 GB the `datahub` CLI's own preflight check
enforces, simply because that is what the stack measurably uses. With the
`showcase-ecommerce` datapack loaded, the six quickstart containers idle
at **~4.23 GiB combined** (≈4.54 GB — already over the 4.3 GB threshold
before any indexing work):

| Container | Idle |
|---|---|
| `datahub-gms` | 1.60 GiB |
| `opensearch` | 1.30 GiB |
| `kafka-broker` | 780 MiB |
| `frontend` | 701 MiB |
| `mysql` | 563 MiB |
| `datahub-actions` | 236 MiB |

8 GB leaves room for the indexing spikes of a datapack load or a detector
run. The 13 GB disk figure is the `datahub` CLI's own requirement,
unchanged.

### Known issue: OpenSearch dies about once a day

Unrelated to memory. On a stock quickstart, the `opensearch` container
leaks one zombie `curl` per healthcheck (every 5s) because the JVM is PID
1 and never reaps them, so PID slots fill up and the JVM eventually fails
to create a thread. Upstream:
[datahub-project/datahub#18657](https://github.com/datahub-project/datahub/issues/18657).
Confirmed on this machine: 1060 zombies out of 1062 processes after 90
minutes of uptime (~708/hour), against only 140 real JVM threads.

The symptom is confusing — DataHub keeps serving entity-by-URN reads while
every search-backed query fails with
`ESQueryException: ... Name does not resolve`, which reads like a DNS
problem rather than a dead container.

This repo ships the upstream fix as an overlay
([`docker-compose.opensearch-init.yml`](docker-compose.opensearch-init.yml) —
`init: true`, so Docker runs tini as PID 1 and reaps the healthcheck
children). Start the stack with it:

```bash
datahub docker quickstart \
  -f ~/.datahub/quickstart/docker-compose.yml \
  -f docker-compose.opensearch-init.yml
```

Two things make this work rather than being overwritten: `docker compose`
merges later `-f` files over earlier ones, and passing `-f` at all makes
the CLI **skip re-downloading** the generated file, so the base stays
pristine. Editing `~/.datahub/quickstart/docker-compose.yml` in place does
*not* survive — `datahub docker quickstart` rewrites that file (`open(...,
"wb")`) on every run without `-f`.

Verified by merging the two files and inspecting the result: `init: true`
lands on `opensearch` only, with its image, healthcheck, JVM options and
volumes untouched.

Recovery if it does die: `docker start datahub-opensearch-1` — data lives
in a volume and survives.

## Detectors

- **D1 - Frozen training source**: an upstream dataset stopped receiving
  real updates, but training keeps running on schedule.
- **D2 - Schema drift under a feature**: a feature's source column no
  longer exists, and the schema change happened after the model's last
  training run.
- **D3 - Semantic change without retrain**: a dbt/Spark transformation
  upstream changed its logic (same schema, different meaning) after the
  model's last training run.

Run the pipeline with `python run_detectors.py` (add `--dry-run` to print
findings without writing anything back, `--matrix` for the model ×
detector state table, `--json PATH` to emit the machine-readable run).

Each detector returns **PASS**, **FINDING**, or **INSUFFICIENT_DATA** —
"we checked and it's fine" and "we had nothing to check with" are
different claims, and reporting the second as the first is precisely the
silent failure this project is about. `INSUFFICIENT_DATA` never moves the
risk score; it is reported separately as assessment coverage.

### Reproducibility

Freshness is inherently wall-clock relative, so **re-run the seed scripts
before demoing** — they anchor every timestamp to the moment they run.
`run_detectors.py` warns when the graph's freshest dataset has drifted
past D1's threshold. Setting `DEADRECKON_NOW` (ISO 8601) overrides "now"
for seeds and detectors alike; it exists so the determinism claim is
testable: seed and assess, shift the clock, re-seed and re-assess, and the
matrix comes out identical.

### Machine-readable output

`python run_detectors.py --json examples/sample-run.json` writes the full
run. Schema: [`docs/output-schema.md`](docs/output-schema.md) — **v1.0.0,
frozen**, after review by the dashboard's author.

- [`examples/sample-run.json`](examples/sample-run.json) — real dump of the seeded fixture.
- [`examples/sample-run-edge-cases.json`](examples/sample-run-edge-cases.json) — synthetic, covering states the fixture can't reach (a finding on a model that is *not* at risk, and a fully unassessable model).

## Demo honesty

D1 rides entirely on a real freshness gap already present in the
community-shipped nyc-taxi fixture (see `seed/nyc_taxi_freshness.py`) -
nothing was fabricated for it. D2 and D3 need a schema/definition change
to detect, and this fixture set has no real history of one, so
`seed/inject_faults.py` deliberately plants one: it renames a column
(`customers.credit_limit` -> `credit_limit_usd`) and edits a dbt model's
view logic (`order_details.discount_percent`, changed to a different
denominator - same column name and type, different number). Both are
disclosed here per the project's own rule: a demo that only finds what we
hid five minutes earlier isn't worth trusting. See `NOTES.md` for the
exact details and the timestamps used.

## Upstream contributions

Issues found while building this and reported back to DataHub:

- **[#18657](https://github.com/datahub-project/datahub/issues/18657#issuecomment-5108977744)** — OpenSearch dies about once a day on a stock quickstart. Independent confirmation on macOS/arm64 of someone else's diagnosis: the healthcheck leaks a zombie `curl` every 5s because the JVM is PID 1 and never reaps them. Measured 1060 zombies out of 1062 processes after 90 minutes (~708/hour) against only 140 real JVM threads, plus a platform difference (`pids.max = max` on Docker Desktop) that changes time-to-crash. Includes the correction of our own earlier misdiagnosis and the measurement error behind it. Fix shipped here as [`docker-compose.opensearch-init.yml`](docker-compose.opensearch-init.yml).
- **[#18675](https://github.com/datahub-project/datahub/issues/18675#issuecomment-5108983658)** — Document entities create successfully but aren't discoverable. Confirmed the reported search symptom on `v1.5.0.6` (document readable by URN and returned by `relatedDocuments`, but `searchAcrossEntities` returns 0 for title, attached-asset name, and a distinctive substring), and extended it: there is no Document profile route at all — a direct URL 404s, and so does the UI's own "Resources" card on the attached entity's Documentation tab.

Further material collected but not yet filed — the `mcp-server-datahub`
read gaps (`mlModelDeployment`, and `get_entities`/`get_lineage` dropping
native fields for `mlModel`/`mlFeature`/`dataProcessInstance`) — is
written up in [`NOTES.md`](NOTES.md).

## License

Apache License 2.0 — see [LICENSE](LICENSE).
