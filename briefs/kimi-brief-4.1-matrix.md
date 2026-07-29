# Brief: deadreckon dashboard — View 4.1, the risk matrix

## What this project is

deadreckon is a hackathon submission (Build with DataHub: The Agent
Hackathon). A Python agent walks ML lineage in DataHub, detects silent
model failures using metadata only, and writes risk assessments back to
the graph. You are building the dashboard that presents one completed
run of that agent.

**This dashboard is not a daily-use tool. It exists to be watched in a
~100-second judge video.** It has to make one specific, unusual claim
legible at a glance: this system is honest about what it did NOT check,
not just what it found. That claim is the entire point of the visual
design — keep it in view while you build.

## Your scope: ONLY view 4.1, the matrix

Build one view: a matrix of models × detectors, plus the minimal
scaffolding needed to load data into it. Do **not** build ranking
detail panels, drill-down, or the lineage subgraph — those are later,
separately-briefed views (4.2, 4.3, 4.4) that depend on your review of
this one first. If you finish early, stop and wait rather than
expanding scope.

## Data contract — read these first, they are the ground truth

1. `docs/output-schema.md` — the full schema, **frozen at v1.0.0**.
2. `examples/sample-run.json` — a real run: 5 models, all three
   detector states appear, includes one fully-clean control model.
3. `examples/sample-run-edge-cases.json` — synthetic states the real
   fixture can't produce: a finding on a model that is NOT at-risk, and
   a model that is fully unassessable (0/3 coverage).

**The schema is frozen. Do not propose changes to it, do not invent
fields that aren't in `docs/output-schema.md`, do not assume a field
exists because it would be convenient.** If something feels missing,
say so instead of working around it silently.

Key facts you must not relearn the hard way:

- `models[]` is **already sorted** (score desc, then finding_count
  desc). Render in the order given — do not re-sort client-side.
- Three detector states exist: `PASS`, `FINDING`, `INSUFFICIENT_DATA`.
  These are **not** a pass/fail binary with a null case bolted on —
  they are three co-equal outcomes. `INSUFFICIENT_DATA` means "we had
  no metadata to check this with," which is a different claim from
  "we checked and it's fine." Never render it as a lighter/greyer
  version of PASS, and never collapse it toward FINDING either.
- `score` is out of `scoring.max_possible_score` (currently `3.0`, but
  read it from the JSON — **do not hardcode `3.0`**). It is not a 0–1
  scale.
- `severity` (`HIGH`/`MEDIUM`/`LOW`) comes pre-computed per model. Read
  `scoring.severity_thresholds` if you want to render a legend, but
  don't recompute severity yourself.
- `coverage.label` is a pre-rendered string like `"2/3"` — use it
  directly rather than formatting `conclusive`/`total` yourself.
- `tags.at_risk` and `tags.unassessable` are **read directly, never
  derived**. Specifically: `at_risk` is gated on severity, not on
  whether findings exist — a model can have a finding and still not be
  at-risk (see the edge-case fixture). Do not write logic like
  `finding_count > 0` to color a row as risky.
- `run.clock_overridden` (bool): when true, the run used a
  rehearsal/overridden clock, not a live one. This needs a permanent,
  impossible-to-miss banner — not a dismissible toast, not a small
  icon. Word it so a viewer understands it's a deliberate honesty
  feature of the project ("this run's clock was overridden for
  testing — effective date: `<run.assessed_at>`"), not a bug warning.
  Both fixtures currently have `clock_overridden: false` — build and
  test the banner by editing a local copy of the JSON to `true`, but
  don't hardcode a check for one specific run.
- Absolutely nothing in the frontend should hardcode a model name, a
  detector weight, a threshold, or a scoring constant. All of that
  comes from `detectors_meta`, `scoring`, and the model entries
  themselves — the dashboard must work unmodified on any run that
  matches the schema, not just the two shipped examples.

## The one thing this view must prove

Every other hackathon submission in this challenge will show a risk
ranking. **None of them will show a system admitting what it didn't
check.** So in the matrix:

- A cell must be visually a **distinct state**, not a color alone.
  Red/orange survive YouTube compression badly and can blur together.
  Give each of the three states its own shape or icon or fill pattern
  in addition to color, so the matrix is legible even desaturated.
- `INSUFFICIENT_DATA` needs equal visual weight to `FINDING` and
  `PASS` — not a muted/grey afterthought.
- The one fully-clean model in `sample-run.json` (`taxi_fare_predictor_v1`
  — PASS/PASS/PASS, score `0.0`, severity `LOW`) must be visible in the
  same frame as the rest, unscrolled. Without a clean control row
  visible, the matrix reads as "a tool that paints everything red,"
  which undercuts the whole premise. Don't hardcode this model by
  name — just make sure your layout doesn't crop or paginate rows.

## What must be visible in this view

- Table/grid: rows = models (in the order the JSON gives them), columns
  = `D1`/`D2`/`D3` (use `detectors_meta.{D1,D2,D3}.title` for column
  headers — don't hardcode detector names).
- Per model row: `name`, `score` rendered against
  `scoring.max_possible_score` (e.g. `"1.8 / 3.0"`), `severity` badge,
  coverage as `coverage.label` (e.g. `"2/3"`).

**Format requirement, not a style preference — this came out of the
scoring audit:** risk must always render as `risk=X/Y` with the ceiling
visible (`Y` = `scoring.max_possible_score`, read from the JSON, e.g.
`"risk=1.8/3.0"`), never as the bare number `1.8` alone. A lone number
reads as a 0–1-normalized score, which it isn't, and that misreading is
exactly what sank the earlier draft. Same logic for coverage: always
`N/3` (i.e. `coverage.label`), never a bare count and never a percentage.
This applies everywhere a score or coverage value appears in this view,
not just in one place.
- The `clock_overridden` banner described above, present on this view
  (it'll need to be present on every view later, but for now just get
  it working here).

## Data loading — static file contract, no backend

There is no API. The dashboard reads a single static JSON file that
matches the frozen schema.

- In dev, default-load `examples/sample-run.json` (path relative to
  repo root — ask if you need it copied into your dashboard directory,
  don't assume a path).
- Also provide a way to load a **different** file at runtime — drag and
  drop or a file picker, either is fine. This is required because a
  judge needs to be able to drop in
  `examples/sample-run-edge-cases.json` and see the UI keep working
  without a rebuild.
- Validate only `schema_version`'s major version (`"1.x.x"` is fine,
  a different major should fail loudly with a visible error, not a
  silent blank screen). Don't build a full JSON-schema validator —
  that's over-engineering for this scope.
- **Zero network calls.** No fetch to DataHub, no fetch to any backend,
  ever. The only I/O is reading a local file the user (or dev default)
  supplies.

## Visual constraints — this is designed for a compressed video, not a monitor

- Target 1920×1080, **no scrolling** in this main view.
- Large type, high contrast, minimal chrome — this is not a data-dense
  ops dashboard, it's evidence for a ~100-second video.
- Dark background, unless it meaningfully complicates something —
  it compresses better on YouTube.
- No entrance animation longer than 200ms anywhere (longer animations
  smear during screen recording/compression).
- States are never color-only encoded anywhere in this view (see
  above) — this applies to severity badges too, not just detector
  cells.

## Stack — constrained, not your choice

Static frontend only, no backend, no server-side rendering. Pick one:

- Vite + React (+ TypeScript), building to a static `dist/`, or
- a single self-contained HTML file (inline JS/CSS, no build step).

**No framework that requires a rendering server** (no Next.js server
mode, no SSR of any kind) — this must be deployable as static files to
Vercel with zero server component, and the run instructions for the
judge have to fit in three lines (`npm install && npm run dev`, or
literally "open this HTML file"). If you pick Vite+React, a plain
`npm install` / `npm run dev` / `npm run build` workflow is what "one
command" means here — don't add custom tooling on top.

## Acceptance criteria (I will check these before showing this to the user)

- Both `examples/sample-run.json` and
  `examples/sample-run-edge-cases.json` render with **zero console
  errors**.
- The edge-cases file specifically must not break anything: the model
  with a `FINDING` that is not `at_risk`, and the fully unassessable
  model (`coverage.unassessable: true`, all three detectors
  `INSUFFICIENT_DATA`), must both render sensibly — not blank, not a
  crash, not a nonsensical "0 findings but red" state.
- No network calls other than loading the local JSON file.
- No hardcoded model names, thresholds, or weights anywhere in the
  frontend source — grep-able as a real check, not a suggestion.
- No secrets, keys, or tokens anywhere, including in any config file
  you add.
- A README (can be a `dashboard/README.md`) explaining how to install
  and run this locally without Docker — assume the reader has Node and
  nothing else set up.

## Deliverable location

Create a new top-level directory in this repo, e.g. `dashboard/`, for
all frontend code. Don't touch anything under `detectors/`, `seed/`,
`docs/`, or `examples/` — those are backend-owned and the schema
inside them is frozen.

## Out of scope for this task (do not build yet)

- Ranking/coverage as two separately-emphasized dimensions beyond what's
  needed for the matrix (that's 4.2).
- Drill-down into a finding's evidence/lineage (4.3).
- The ignition subgraph (4.4).
- Any DataHub deep-link beyond what's trivially in the JSON (`url`
  fields) — you don't need to construct or verify any URLs yourself for
  this view.

If anything above is ambiguous or you think the schema is missing
something you need, stop and ask rather than guessing or inventing a
field.
