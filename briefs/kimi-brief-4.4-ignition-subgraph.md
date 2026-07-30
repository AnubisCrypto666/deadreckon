# Brief: deadreckon dashboard — View 4.4, the ignition subgraph

## What this project is

deadreckon is a hackathon submission. A Python agent walks ML lineage in
DataHub, detects silent model failures using metadata only, and writes
risk assessments back to the graph. The dashboard presents one
completed run of that agent to a judge watching a short video. Its
whole point is to show a system being honest about what it did **not**
check, not just what it found.

## What already exists — read this first, don't rebuild it

`dashboard/index.html` is a single self-contained static HTML file (no
build step, no backend, no network calls beyond loading one local
JSON), already implementing:

- **View 4.1** — the model × detector matrix.
- **View 4.2** — a risk-vs-coverage scatter plot (tab switcher).
- **View 4.3** — clicking any matrix cell opens a drill-down modal:
  reasoning, per-detector evidence with human-readable labels, and (for
  `FINDING` cells) a plain-text "Ignition:" line naming the node where
  the problem originates.

All three are built, committed, and verified in a real browser against
both fixtures. **Read the entire file before changing anything.** Also
read `briefs/kimi-brief-4.3-drilldown.md` for the exact deep-link rule
and evidence-rendering conventions already established — this task
extends that same drill-down, it doesn't replace it.

## Your scope: ONLY view 4.4 — the ignition subgraph

From the project plan: *"A narrow subgraph: only the path from the
ignition point to the model, 5-8 nodes, a single line, with a CAUSAL
annotation at the ignition node (why this one) — plus a clear deep-link
'open full lineage in DataHub'. The causal annotation is what DataHub
doesn't have; everything else is someone else's work, worth linking to
rather than rebuilding."*

This is an **enhancement to the existing FINDING drill-down (4.3)**,
not a new tab or view. When a drill-down modal is showing a `FINDING`
(which always carries a `lineage_path`), replace the current plain
"Ignition:" text line with the compact visual path described below.
`PASS` and `INSUFFICIENT_DATA` modal content is unaffected — those
detector states have no `lineage_path` and need no change.

## Hard constraint: do NOT recreate DataHub's own lineage view

This directly affects the project's originality scoring — *"building on
a platform's features is fine, reproducing them is not."* DataHub's own
lineage view is a pannable, zoomable, force-directed graph canvas.
**Do not build anything like that.** What you're building instead:

- A **fixed, non-interactive, single horizontal row** of node chips
  connected by simple arrows (→). No pan, no zoom, no drag, no minimap,
  no auto-layout algorithm.
- Real `lineage_path` arrays in the current fixtures are 3-4 nodes long
  (D1: `dataset → dataProcessInstance → mlModel`; D2: `dataset →
  mlFeature → dataProcessInstance → mlModel`; D3: `dataset(dbt) →
  dataset(source) → dataProcessInstance → mlModel`). Design comfortably
  for up to ~8 nodes since the plan anticipates that range, but don't
  force extra visual complexity for the 3-4 nodes you'll actually see
  in the fixtures.
- Small, embedded inline in the modal — this is a compact annotated
  strip, not a full-screen diagram.

## What to render

For each node in `lineage_path` (already ordered upstream → downstream,
ending at the model — render in that order, left to right):

- A small chip/box showing the node's `type` (as a short label or
  icon — `dataset`, `mlFeature`, `dataProcessInstance`, `mlModel`) and
  `name`.
- **Linking rule — reuse the exact deep-link rule from 4.3, this view
  has it easier:** `lineage_path[].url` is already present per node.
  If `url` is non-null, the chip is a link (`target="_blank"`,
  `rel="noopener"`). If `url` is null (always true for `mlFeature` and
  `dataProcessInstance` in this DataHub version — a prior, deliberate
  finding, not a bug), render plain text, not a link. **Never
  synthesize a URL yourself for any node, ever** — same hard rule as
  4.3, for the same reason (this project already shipped one guessed
  URL that 404'd, on the `document` entity — see `NOTES.md`).
- Arrows (→) between consecutive chips indicating flow direction.
- D3 paths have two consecutive `dataset`-typed nodes (the dbt
  transformation and its Snowflake source) — make sure they're
  visually distinguishable by name, not just by a repeated "dataset"
  type label, or the path reads as a duplicate/error at a glance.

**The ignition node** (`ignition: true`, exactly one per path) needs:

- Distinct visual treatment (highlighted border/background — reuse the
  existing visual language: `--unknown`/amber is already used
  elsewhere for "pay attention here" states, or pick something equally
  distinct that isn't already meaning something else in this UI).
- A short **causal annotation** attached to it — a compact phrase
  answering "why is this the ignition point," not the full finding
  `summary` (which is already shown elsewhere in the same modal, don't
  repeat it verbatim). Derive it from the same `evidence` fields
  already used in 4.3's evidence table, using this phrasing per
  detector:
  - **D1**: `"Frozen {frozen_days} day(s) — training kept running"`
  - **D2**: `"{source_column} missing {missing_days} day(s) before last training"`
  - **D3**: `"Definition changed {changed_days} day(s) before last training"`

  (Field names match `docs/output-schema.md`'s evidence tables, same as
  the mapping already built in 4.3's `renderEvidenceRows`.)

**Below or beside the path**, a separate, clearly labeled link: **"Open
full lineage in DataHub →"**, pointing at `model.url` — the model's own
verified DataHub profile page, one click away from its native Lineage
tab. **Do not** try to construct or guess a URL that opens DataHub's
lineage-mode UI directly (e.g. a `?is_lineage_mode=true`-style query
param) — that specific route is unverified in this DataHub version, and
this project already learned the hard way (see `NOTES.md`) that a
guessed route that 404s is worse than a plain link to a page that
definitely works.

## Visual constraints — same continuous piece of evidence as 4.1-4.3

- Dark background, high contrast, large type, minimal chrome.
- States are never color-only.
- No entrance animation longer than 200ms.
- No new scrollbar on the Matrix view itself; the modal may already
  scroll internally (established in 4.3) if content is long — the
  subgraph strip should stay compact enough that it normally doesn't
  push the modal into scrolling on its own.

## Lessons from building 4.1-4.3 — don't repeat these

- **Verify visually in a real rendered browser screenshot, not just a
  DOM-presence check.** 4.1 shipped once with overlapping text that no
  DOM check caught. Screenshot this specifically for a D1 finding (3
  nodes), a D2 finding (4 nodes, includes an unlinked `mlFeature`
  chip), and a D3 finding (4 nodes, two consecutive `dataset` chips
  with different names) — three visually distinct shapes, check all
  three render cleanly, no chip/arrow/label overlap, no clipped text.
- **Zero console errors is literal**, and the fixed favicon `<link
  rel="icon">` must stay in place.
- Give every chip's name text explicit width/wrap handling — some
  dataset names in the fixtures are long
  (`b2fd91.order_entry_db.order_entry.customers`,
  `acme.warehouse.analytics.sessions`) and must not overflow into the
  next chip or arrow.

## Data contract reminders — still load-bearing

- Schema is **frozen** at v1.0.0. Don't invent fields, don't propose
  changes.
- No hardcoded model names, detector weights, thresholds, or scoring
  constants anywhere in the source.
- `lineage_path[].type` is a closed enum (`dataset`, `mlFeature`,
  `dataProcessInstance`, `mlModel`) — handle exactly these four, and
  don't crash on an unexpected value (fall back to showing the raw
  `type` string rather than erroring).

## Acceptance criteria (I will check these before considering this done)

- Tested against real findings covering all three detector shapes in
  `examples/sample-run.json`: a D1 finding (`taxi_eta_predictor_v1`), a
  D2 finding (`customer_churn_predictor_v2` or
  `customer_churn_predictor_v1`), and a D3 finding
  (`order_value_predictor_v1`). Also tested against
  `examples/sample-run-edge-cases.json`'s D2 and D3 findings
  (`session_length_predictor_v0`, `session_bounce_predictor_v1`).
- In every case: exactly one node is visually marked as ignition, its
  causal annotation matches the phrasing template above for that
  detector, and the annotation text is populated correctly from that
  finding's actual `evidence` values (not a placeholder).
- "Open full lineage in DataHub →" is present and points at that
  model's `model.url`, verified by inspection to be the same value
  already used elsewhere in the dashboard for that model (not a new
  URL construction).
- **Zero fabricated URLs** anywhere in this new code — every link
  traces back to a `url` value already present verbatim in the source
  JSON (`lineage_path[].url` or `model.url`).
- Zero console errors in a real browser across all tested findings in
  both fixtures.
- Views 4.1, 4.2, and 4.3's `PASS`/`INSUFFICIENT_DATA` content are
  completely unchanged.
- No hardcoded model names, thresholds, or weights.
- No network calls beyond loading the local run JSON.
- No secrets, keys, or tokens anywhere.
- `dashboard/README.md` updated to mention this.

## Out of scope for this task

- Any new top-level tab/view — this lives inside the existing 4.3
  modal only.
- Any interactive graph (pan/zoom/drag/minimap/auto-layout).
- Changing `PASS` or `INSUFFICIENT_DATA` drill-down content.
- Any deep-link construction beyond reusing `lineage_path[].url` and
  `model.url` verbatim.
- Changes to views 4.1 or 4.2.

If anything above is ambiguous, or the schema seems to be missing
something you'd need, stop and ask rather than guessing.
