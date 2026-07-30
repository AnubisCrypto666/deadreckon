# Brief: deadreckon dashboard — View 4.3, finding drill-down

## What this project is

deadreckon is a hackathon submission. A Python agent walks ML lineage in
DataHub, detects silent model failures using metadata only, and writes
risk assessments back to the graph. The dashboard presents one
completed run of that agent to a judge watching a short video. Its
whole point is to show a system being honest about what it did **not**
check, not just what it found.

## What already exists — read this first, don't rebuild it

`dashboard/index.html` is a single self-contained static HTML file
(no build step, no backend, no network calls beyond loading one local
JSON), already implementing:

- **View 4.1** — the model × detector matrix (a table).
- **View 4.2** — a risk-vs-coverage scatter plot, reachable via a
  tab switcher in the header.

Both are built, committed, and verified in a real browser against both
fixtures. **Read the entire file before changing anything.** Also read
`briefs/kimi-brief-4.1-matrix.md` and `briefs/kimi-brief-4.2-ranking-coverage.md`
for the data-contract and visual ground rules already established —
they still apply here. **Do not regress either existing view.**

## Your scope: ONLY view 4.3 — the finding drill-down

From the project plan: *"Click a matrix cell: show the reasoning,
the evidence, and a deep-link to the entity in DataHub."*

Do not build the ignition subgraph (4.4) — that is separately briefed,
later, after this view is reviewed. Specifically **do not render
`lineage_path` as a graph or diagram** in this view — that is 4.4's
entire job. You may reference `lineage_path` as plain text if useful
(e.g. naming the ignition node), but building any kind of node/edge
visualization here is out of scope.

Drill-down triggers from the **Matrix view (4.1) only** — clicking a
detector cell. Do not add drill-down/click behavior to the Ranking &
Coverage scatter points; that view stays as-is.

## What "clicking a cell" must show

Every cell is clickable — **all three states**, not just `FINDING`.
This isn't incidental: showing "we checked and found nothing" and "we
had nothing to check with" as clearly as "we found something" is the
same honesty principle the whole project is built on. Open a modal or
panel (your choice of mechanism) with:

### If the cell is `FINDING`

For **every** entry in that detector's `findings` array (there can be
more than one, even though today's fixtures happen to have 0 or 1 per
cell — don't assume a single-element array):

- The full `summary` sentence (the reasoning).
- The `subject` (compact label) with `subject_url` as a clickable link
  **only when `subject_url` is non-null** — it already comes correctly
  gated from the backend, never build your own link if it's null.
- `evidence`, rendered with **human-readable, per-detector field
  labels** — not a raw key/value dump of the JSON. Use this exact
  mapping (evidence shape is frozen in `docs/output-schema.md`):

  **D1** (`dataset_urn`, `dataset_last_updated`, `frozen_days`,
  `latest_training_run_urn`, `latest_training_run_at`):
  - "Frozen source" → the dataset (as text/URN; see linking rule below)
  - "Last real update" → `dataset_last_updated`
  - "Frozen for" → `frozen_days` days
  - "Latest training run" → `latest_training_run_at` (run URN as text)

  **D2** (`feature_urn`, `dataset_urn`, `source_column`,
  `schema_changed_at`, `missing_days`, `latest_training_run_urn`,
  `latest_training_run_at`):
  - "Feature" → `feature_urn` (as text; see linking rule)
  - "Source column" → `source_column`, on dataset `dataset_urn`
  - "Schema changed" → `schema_changed_at`
  - "Missing for" → `missing_days` days
  - "Latest training run" → `latest_training_run_at`

  **D3** (`transformation_dataset_urn`, `feature_source_dataset_urn`,
  `definition_changed_at`, `changed_days`, `latest_training_run_urn`,
  `latest_training_run_at`):
  - "Transformation" → `transformation_dataset_urn`
  - "Feature source" → `feature_source_dataset_urn`
  - "Definition changed" → `definition_changed_at`
  - "Changed" → `changed_days` days ago
  - "Latest training run" → `latest_training_run_at`

  If a finding's `detector` value isn't one of D1/D2/D3 (shouldn't
  happen given the frozen schema, but don't crash), fall back to a
  generic key/value list rather than erroring.

### If the cell is `PASS`

Show something like **"No findings — N subjects checked"** using
`detector.subjects_checked`. Frame it as a real, positive result, not
an empty state — an empty `findings` array is explicitly a first-class
outcome per the schema, the strongest thing the agent can say about a
model.

### If the cell is `INSUFFICIENT_DATA`

Show `coverage_gaps`, grouped exactly as they arrive (already grouped
by `aspect` — don't re-group or flatten): for each gap, show the
`aspect` name, the `count`, and the list of `subjects` (`urn`, `url`,
`detail`) — link each subject when its `url` is present. This is
arguably the most important state to make legible: it's the model
admitting it doesn't know, not a hidden absence.

## Deep-link rule — this is the one that has bitten this project before

**Never construct or synthesize a URL yourself, for any entity, ever.**
Only ever use a `url` value that is *already present verbatim*
somewhere in the run JSON: `model.url`, `model.group.url`,
`finding.subject_url`, `lineage_path[].url`, or
`coverage_gaps[].subjects[].url`. If none of these give you a url for
a particular URN, render that URN as plain monospace text — not a
link, not a guessed route.

This matters specifically for URNs that show up *inside* `evidence`
(`feature_urn`, `latest_training_run_urn`, `dataset_urn` used as a
feature source, `transformation_dataset_urn`, `feature_source_dataset_urn`)
— `evidence` itself carries no accompanying `url` per key. If you want
to link one of these, you may cross-reference the URN string against
that same finding's own `lineage_path` array (which does carry a `url`
per node — correctly `null` for `mlFeature`/`dataProcessInstance`
nodes) and use whatever `url` you find there. If nothing matches,
render plain text.

**Why this is a hard rule, not a style preference:** this project
already hit a real 404 building a guessed direct URL to a `document`
entity in DataHub, documented in `NOTES.md` and the project's own
`docs/output-schema.md` (*"a link that 404s is worse than none"*).
Only `dataset` and `mlModel` routes are verified in this DataHub
version — `mlFeature` and `dataProcessInstance` are not, which is
exactly why their `lineage_path[].url` is always `null` in the data you
have. Respect that null; don't work around it.

## Data contract reminders — same rules as 4.1/4.2, still load-bearing

- Schema is **frozen** at v1.0.0 (`docs/output-schema.md`). Don't invent
  fields, don't propose changes.
- No hardcoded model names, detector weights, thresholds, or scoring
  constants anywhere in the source.
- If the drill-down header shows the model's score or coverage for
  context, keep the established format: `risk=X/Y` (ceiling visible,
  never a bare number) and `coverage.label` (`N/3`).
- `tags.at_risk` / `tags.unassessable` are read directly, never derived.

## Visual constraints — same continuous piece of evidence as 4.1/4.2

- Dark background, high contrast, large type, minimal chrome.
- States are never color-only.
- No entrance animation longer than 200ms.
- The underlying view (Matrix) should not itself gain a scrollbar from
  this change. The drill-down overlay/modal itself may size to content
  and scroll internally if a particular finding's content is long —
  that's fine and expected, unlike the main resting-state views.
- Closing the drill-down (click outside, a close button, and Escape
  key) must cleanly return to the exact same Matrix view state — no
  reload, no data re-fetch.

## Lessons from building 4.1/4.2 — don't repeat these

- **Verify visually in a real rendered browser screenshot, not just a
  DOM-presence check.** The 4.1 matrix shipped once with model-name
  text overlapping the risk column — invisible to "does the element
  exist," only caught by looking at a screenshot. Check this drill-down
  the same way, especially with the longest `summary` text and the
  most `coverage_gaps` subjects across both fixtures.
- **Zero console errors is literal** and already includes a fixed
  favicon `<link rel="icon">` — don't remove it.
- Give any element rendering variable-length text (finding summaries,
  URNs, subject details) explicit width/wrap handling — don't assume
  it'll fit.

## Acceptance criteria (I will check these before considering this done)

- Every cell in the Matrix view, across both `examples/sample-run.json`
  and `examples/sample-run-edge-cases.json`, opens a drill-down with
  content matching its actual state (`PASS`/`FINDING`/`INSUFFICIENT_DATA`).
- Tested against real examples of all three: D1/D2/D3 findings (present
  in `sample-run.json`), a fully `INSUFFICIENT_DATA` model
  (`session_ltv_predictor_v2` in the edge-cases file — all three
  detectors, each with a single-subject coverage gap), and at least one
  genuine `PASS` cell.
- **Zero fabricated URLs** — every link rendered anywhere in the
  drill-down must trace back to a `url` value that already existed
  verbatim in the source JSON. This should be verifiable by inspection:
  no string concatenation building a route from a URN.
- Zero console errors in a real browser, verified across opening and
  closing drill-downs for multiple cells in both fixtures.
- Matrix (4.1) and Ranking & Coverage (4.2) views work exactly as
  before — no regression.
- No hardcoded model names, thresholds, or weights.
- No network calls beyond loading the local run JSON.
- No secrets, keys, or tokens anywhere.
- `dashboard/README.md` updated to mention the drill-down.

## Out of scope for this task

- The ignition subgraph / any lineage graph rendering (4.4).
- Click behavior on the Ranking & Coverage scatter plot.
- Any new deep-links beyond `url` values already present in the JSON.
- Redesigning the Matrix or Ranking views themselves — only add the
  drill-down interaction to Matrix cells.

If anything above is ambiguous, or the schema seems to be missing
something you'd need, stop and ask rather than guessing.
