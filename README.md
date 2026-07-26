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
findings without writing anything back).

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
