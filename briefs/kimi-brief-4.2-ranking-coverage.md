# Brief: deadreckon dashboard — View 4.2, ranking & coverage as independent dimensions

## What this project is

deadreckon is a hackathon submission. A Python agent walks ML lineage in
DataHub, detects silent model failures using metadata only, and writes
risk assessments back to the graph. The dashboard presents one
completed run of that agent to a judge watching a short video. Its
whole point is to show a system being honest about what it did **not**
check, not just what it found.

## What already exists — read this first, don't rebuild it

`dashboard/index.html` already exists: a single self-contained static
HTML file (no build step, no backend, no network calls beyond loading
one local JSON) implementing view 4.1, the model × detector matrix. It
is built, committed, and verified against both fixture files in a real
browser. **Read the whole file before changing anything.** Also read
`briefs/kimi-brief-4.1-matrix.md` for the full data-contract and visual
ground rules that view was built under — they still apply here.

**Do not regress view 4.1.** Whatever you build for 4.2 must live
alongside it (see "Where this lives" below) without breaking the
matrix, its data loading, its clock-override banner, or its verified
zero-console-errors state.

## Your scope: ONLY view 4.2 — ranking & coverage

From the project plan: *"Risk and coverage as two separate, independently-presented
dimensions. It must be legible that a model can have low risk **and**
low coverage, and that this is NOT the same as being safe."*

Do not build the finding drill-down (4.3) or the ignition subgraph
(4.4) — those come later, separately briefed, after this view is
reviewed.

## The one thing this view must prove

This is the load-bearing case, and it is why `examples/sample-run-edge-cases.json`
exists — the real fixture alone can't produce it:

- `taxi_fare_predictor_v1` in `examples/sample-run.json`: `score: 0.0`,
  `coverage: {conclusive: 3, total: 3, label: "3/3", fully_covered: true}`.
  This model was fully checked and found clean. **Genuinely safe.**
- `session_ltv_predictor_v2` in `examples/sample-run-edge-cases.json`:
  `score: 0.0`, `coverage: {conclusive: 0, total: 3, label: "0/3",
  unassessable: true}`. This model scores identically — but nothing
  about it was actually checked. **Not safe. Unverified.**

Both models produce the exact same risk score. If your view represents
risk alone, or represents coverage as a minor secondary label, these
two models become visually indistinguishable — which is precisely the
silent failure this whole project exists to catch. **A judge must be
able to look at this view and immediately tell these two models apart
without reading any text carefully.** This is the single acceptance
bar for 4.2; everything else is in service of it.

## Visual approach

Your call on the exact chart, but it must show risk and coverage as
**two independent axes/dimensions that don't collapse into one
number**, with every model positioned by both simultaneously. Two
reasonable directions:

1. **A scatter/quadrant plot** — X axis: risk score (`0` to
   `scoring.max_possible_score`). Y axis: coverage (`coverage.conclusive`
   / `coverage.total`, e.g. plotted on a `0`–`total` scale, or grouped
   by distinct coverage levels since `total` is small — currently
   always 3). One point per model, labeled with model name. The
   "low risk, low coverage" region needs its own visual treatment
   (e.g. a shaded zone, a border, an explicit label like "unverified —
   not the same as safe") that is visually distinct from "low risk,
   full coverage" — regardless of how few or many models currently
   land there.
2. **Two parallel ranked lists / a slopegraph** — models ranked by risk
   on one side, ranked by coverage on the other, connected, so a viewer
   can see a model's position on both rankings at once. Coverage still
   needs its own explicit visual treatment for "not fully covered" vs
   "unassessable" (`coverage.unassessable: true`, i.e. `0/3`) — don't
   just show a number, since a low number reads as "small risk," not
   "we don't know."

Whichever you pick, do not hide the distinction in a tooltip — the
video won't show hover states. It must be visible in the static frame.

## Data contract — same rules as 4.1, restated because they're load-bearing

- Schema is **frozen** at v1.0.0 (`docs/output-schema.md`). Don't invent
  fields, don't propose changes.
- `coverage.label` is pre-rendered (`"2/3"`, `"0/3"`) — use it directly.
- `coverage.fully_covered` (`conclusive == total`) and
  `coverage.unassessable` (`conclusive == 0`) are both provided — read
  them, don't recompute.
- `score` is against `scoring.max_possible_score` — read the max from
  JSON, never hardcode `3.0`.
- `tags.at_risk` / `tags.unassessable` are read directly, never derived
  from score or finding_count.
- **Format requirement, carried over from 4.1's scoring audit:**
  wherever risk appears, render `risk=X/Y` with the ceiling visible
  (never a bare number). Wherever coverage appears, render `coverage.label`
  (`N/3`), never a bare count or a percentage.
- No hardcoded model names, detector weights, thresholds, or scoring
  constants anywhere in the source — grep-able, not a suggestion.

## Where this lives

Extend `dashboard/index.html` in place: add a lightweight way to switch
between "Matrix" (the existing 4.1 view) and "Ranking & Coverage" (this
new view) — e.g. two tabs/buttons at the top — without a page reload
and without re-reading the file (both views render off the same
already-loaded run data in memory). Keep it a single static file, no
build step, no new dependencies, no server component. Don't create a
second HTML file or a router — this is still meant to open with one
command.

## Lessons from building 4.1 — don't repeat these

- **Table/layout column-width bug**: the matrix view initially shipped
  with model-name text overlapping the risk-score column because no
  column had an explicit width under `table-layout: fixed`, combined
  with `white-space: nowrap` letting overflow spill into the next
  cell instead of wrapping or clipping. Whatever layout you use here
  (SVG, CSS grid, flex, table), give every element that renders
  variable-length text (model names especially) an explicit
  width/constraint and verified wrap/truncate behavior — check this
  specifically with the longest model name across both fixtures
  (`customer_churn_predictor_v2`, `session_length_predictor_v0`, etc.)
  and don't assume it'll just fit.
- **Zero console errors is literal.** The matrix view previously
  triggered a `/favicon.ico` 404 that showed up as a console error;
  it's already fixed in the current `dashboard/index.html` — don't
  reintroduce it (don't remove the existing `<link rel="icon">`).
- Verify visually in an actual browser at 1920×1080 against both
  fixture files before considering this done — don't rely solely on a
  DOM-presence check. The overlap bug in 4.1 wasn't caught by "does
  the element exist," only by looking at a rendered screenshot.

## Visual constraints — same as 4.1, this is one continuous piece of evidence

- Target 1920×1080, no scrolling.
- Dark background, high contrast, large type, minimal chrome.
- States are never color-only — shape/icon/label alongside color,
  same as the matrix's detector cells.
- No entrance animation longer than 200ms.
- The tab/view switcher itself should be unobtrusive — this view isn't
  the place to spend visual weight; the risk/coverage distinction is.

## Acceptance criteria (I will check these before showing this to the user)

- Both `examples/sample-run.json` and `examples/sample-run-edge-cases.json`
  render this view with **zero console errors**, verified in a real
  browser, not just a DOM check.
- Loaded against `sample-run-edge-cases.json`: `taxi_fare_predictor_v1`-style
  "genuinely clean" (not present in this file, but reason about it) vs.
  `session_ltv_predictor_v2` ("unassessable," same score, zero
  coverage) must be visually distinguishable at a glance. This is the
  core test — check it explicitly, don't just eyeball the whole page.
- The existing Matrix view (4.1) still works exactly as before —
  loading either fixture, the clock-override banner, the file
  picker/drag-drop — nothing regresses.
- No hardcoded model names, thresholds, or weights anywhere in the
  source.
- No network calls beyond loading the local run JSON.
- No secrets, keys, or tokens anywhere.
- `dashboard/README.md` updated if the run instructions or what's shown
  changed in any way a reader would need to know.

## Out of scope for this task

- Finding drill-down / evidence detail (4.3).
- The ignition subgraph (4.4).
- Any new deep-links beyond what's already in the JSON's `url` fields.
- Redesigning the Matrix view's own visuals — only add navigation to
  reach this new view, don't restyle 4.1.

If anything above is ambiguous, or the schema seems to be missing
something you'd need, stop and ask rather than guessing.
