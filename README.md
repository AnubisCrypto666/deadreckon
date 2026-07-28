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
enforces, and the gap is deliberate. Measured on this stack, the six
quickstart containers idle at **~4.2 GB combined** — meaning the official
minimum passes the preflight check with essentially no headroom left, and
then falls over under the indexing load of a datapack load or a detector
run. That is not theoretical: OpenSearch on this machine died with
`OutOfMemoryError: unable to create native thread` mid-development. It had
a 1 GB JVM heap but ~1300 live threads at ~1 MB of stack each, so the
memory pressure was thread stacks rather than heap — which is why raising
the heap is not the fix, and raising the VM allocation is.

If OpenSearch does die, the symptom is DataHub returning
`ESQueryException: ... Name does not resolve` on search-backed queries.
Recover with `docker start datahub-opensearch-1` — data lives in a volume
and survives.

The 13 GB disk figure is the `datahub` CLI's own requirement, unchanged.

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
run. Schema: [`docs/output-schema.md`](docs/output-schema.md) (draft v0,
not yet frozen). Sample: [`examples/sample-run.json`](examples/sample-run.json).

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

## License

Apache License 2.0 — see [LICENSE](LICENSE).
