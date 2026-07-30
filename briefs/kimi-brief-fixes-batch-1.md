# Brief: deadreckon dashboard — fix batch (5 items, nothing else)

## Context

`dashboard/index.html` is a single self-contained static HTML file
implementing four already-built, committed, and verified views (4.1
matrix, 4.2 ranking/coverage, 4.3 finding drill-down, 4.4 ignition
subgraph). All four work correctly today. This task is **five specific,
narrow fixes only** — read the whole file first, but do not restructure,
refactor, or "improve" anything beyond exactly what's listed below.
Nothing else about layout, data handling, or existing views should
change. If you think something else needs fixing, stop and ask rather
than including it.

Verify every fix visually in a real rendered browser screenshot against
both `examples/sample-run.json` and `examples/sample-run-edge-cases.json`
— not just a DOM-presence check. That's how a real, previously-shipped
bug in this project (matrix column overlap, view 4.1) was caught before,
and how it wasn't caught the first time.

---

## 1. Embed the default fixture as a literal — no server required for double-click

**Problem:** `dashboard/index.html` currently loads its default data via
`fetch(DEFAULT_RUN_URL)` (`DEFAULT_RUN_URL = "../examples/sample-run.json"`,
used in `loadDefault()`). Under the `file://` protocol (i.e. a judge just
double-clicking the file), browsers block this fetch via CORS, so the
dashboard falls back to an error + file-picker prompt instead of showing
data immediately. The README currently tells the reader to run a local
static server first — that's one avoidable step between a judge and
seeing anything work.

**Fix:** embed the exact contents of `examples/sample-run.json` as a
JS literal directly in `dashboard/index.html` (e.g. a `const
EMBEDDED_DEFAULT_RUN = {...}` object, or a `<script type="application/json">`
block you parse — your choice of mechanism). Use that embedded data as
the default on load, **with no fetch and no network call at all** for
the default case. This actually strengthens the existing "zero network
calls" property rather than just working around CORS.

- Remove the `fetch(DEFAULT_RUN_URL)` call and the `DEFAULT_RUN_URL`
  constant along with it — they're no longer needed once the data is
  embedded.
- **Loading a different file (drag-and-drop / file picker) stays exactly
  as it is today** — unchanged behavior, still reads from an actual
  file the user supplies. This fix only changes where the *default*
  data comes from.
- Do **not** embed `examples/sample-run-edge-cases.json` — that one
  stays file-load-only, exactly as today.
- The embedded literal must be byte-for-byte the same data as
  `examples/sample-run.json` (copy it in directly; don't hand-transcribe
  or summarize it).
- Update `dashboard/README.md`: the "open the file directly" caveat
  about CORS blocking the default fetch is no longer true — opening
  `dashboard/index.html` by double-click should now show the default
  run immediately, with no server needed at all. The `npx serve` /
  `python -m http.server` instructions can stay as an *optional*
  alternative (useful for testing drag-and-drop with a large file, or
  just personal preference) but should no longer be presented as
  required.

**Verify:** open `dashboard/index.html` via `file://` (a literal
double-click, not through a local server) and confirm the matrix
appears immediately, all four views work, and the browser console shows
no CORS/fetch errors on load.

---

## 2. Make linked vs. unlinked chips visually distinguishable without hovering

**Problem:** in the view 4.4 ignition subgraph, `.subgraph-node a`
currently has `color: inherit; text-decoration: none;` — a linked node
chip (dataset/model, has a real DataHub URL) looks visually identical to
an unlinked one (`mlFeature`/`dataProcessInstance`, plain `<span>`,
correctly has no URL) until you hover over it. This matters specifically
because **the deep-link is the visual proof that this project writes
back to the DataHub graph** — a judge needs to see, at a glance and
without moving a mouse, which chips are clickable.

**Fix:** give the `<a class="node-name">` chips a clearly distinct,
non-hover-dependent treatment — reuse the existing link color already
used elsewhere in this file (`var(--accent)`, the blue already used for
the model name link in the header and elsewhere) plus an underline
that's visible by default, not only on `:hover`. Unlinked
`<span class="node-name">` chips stay exactly as they are now (neutral
text color, no underline). This is a CSS-only change to the existing
`.subgraph-node a` / `.subgraph-node a:hover` rules — don't touch the
chip layout, spacing, or the causal-annotation logic.

**Verify:** screenshot a D2 finding (has both a linked dataset chip and
an unlinked `mlFeature` chip in the same row) and confirm the two are
distinguishable without zooming in or hovering.

---

## 3. Coverage in the Matrix view (4.1) reads as visually secondary — fix without restructuring the layout

**Problem:** in the Matrix view, the `COVERAGE` column (`.coverage`
class) renders in `color: var(--text-dim)` — a dim grey — sitting next
to the `RISK` column (bright, high-contrast) and the `SEVERITY` badges
(colored pill with background + border). The project's own stated thesis
is that coverage is an **equally load-bearing signal**, not a secondary
footnote, alongside risk — so it shouldn't be the visually quietest
thing on the row.

**Fix, without changing the table's column layout or adding new
columns:**
- Brighten the base (fully-covered, non-unassessable) coverage text so
  it reads with the same visual weight as `.risk` — don't leave it
  dimmer than the number right next to it.
- Give the coverage value the same *kind* of treatment already used for
  `.badge.severity-*` (a small pill: background + border + short label)
  rather than plain inline text — reuse that existing visual language
  instead of inventing a new one. Base the pill's state on the fields
  already in the data, not on parsing the `N/3` label string:
  - `coverage.fully_covered === true` → a distinct "fully assessed"
    treatment (pick a color that doesn't collide with the meaning
    already carried by `--pass`/`--finding`/`--unknown` in severity and
    detector-state colors elsewhere on the same screen — `--accent`,
    the blue already used for links/emphasis, is a reasonable choice
    since coverage isn't a risk signal).
  - `coverage.fully_covered === false && coverage.unassessable === false`
    → visually present but distinguishable from "fully assessed" (e.g.
    same pill shape, more neutral/outline-only treatment).
  - `coverage.unassessable === true` → keep using `--unknown` (amber),
    already correct today, just carried into the new pill treatment
    instead of plain dim text.
- This applies to the Matrix view's coverage column specifically. Don't
  change how coverage is displayed in view 4.2 (the scatter axis) or in
  the 4.3 drill-down header — those are out of scope for this item.

**Verify:** screenshot the Matrix view for both fixtures and confirm
`coverage` no longer reads as the flattest/dimmest element on the row —
compare side-by-side with the `RISK` and `SEVERITY` columns for
comparable visual weight. Also confirm `session_ltv_predictor_v2` in
the edge-cases fixture (`coverage.unassessable: true`, `0/3`) is still
clearly flagged as the "nothing checked" case, not just re-colored
generically.

---

## 4. Stray punctuation in the 4.1 legend

**Problem:** `renderLegend()` builds the severity legend as
`` `Severity:${thresholdText}` `` where `thresholdText` already starts
with `` ` · thresholds: ...` ``, producing the rendered string
`"Severity: · thresholds: HIGH ≥ 2, MEDIUM ≥ 0.7"` — a stray/duplicated
separator between "Severity:" and "thresholds:".

**Fix:** rewrite that string construction so it reads cleanly with no
redundant punctuation — e.g. `"Severity — thresholds: HIGH ≥ 2, MEDIUM
≥ 0.7"` or `"Severity (thresholds: HIGH ≥ 2, MEDIUM ≥ 0.7)"`, your
choice, as long as there's no doubled separator and it still reads as
one coherent label. Don't change anything else in `renderLegend()` —
the status chips and severity chips themselves are correct as-is.

**Verify:** screenshot the legend and read the exact rendered text.

---

## 5. Two markers nearly touch in the 4.2 scatter plot (edge-cases fixture)

**Problem:** in `examples/sample-run-edge-cases.json`, plotted on the
Ranking & Coverage view, `session_bounce_predictor_v1` (risk 0.6,
coverage 3/3) and `session_length_predictor_v0` (risk 0.5, coverage 3/3)
sit close enough in plotted space that their point markers nearly touch
and their labels crowd each other. The current label placement
alternates purely by array index (`index % 2 === 0` decides "label
above vs. below"), which doesn't account for how close two points
actually land in pixel space — that's why this specific pair collides.

**Fix:** when placing labels in the ranking chart, detect points whose
plotted positions are close enough to collide (a pixel-distance check
between a point and previously-placed points, not just alternating by
array index) and push their labels further apart — e.g. increase the
vertical offset, or alternate left/right in addition to above/below —
enough that neither the markers' leader lines nor the label boxes
overlap. This needs to generalize (don't hardcode a fix for these two
specific model names) since which models are close together depends on
the loaded run's actual scores, not on anything fixed in this fixture.

**Verify:** screenshot the Ranking & Coverage view on
`examples/sample-run-edge-cases.json` specifically and confirm the two
labels and their leader lines are clearly separated. Also re-check
`examples/sample-run.json`'s ranking view to confirm this change didn't
introduce new overlaps there (it currently has no overlap issue, but the
label-placement logic is shared code).

---

## Acceptance criteria

- All five items above verified with real rendered screenshots against
  both fixtures, as described in each section.
- Views 4.1, 4.2, 4.3, and 4.4 otherwise behave exactly as they did
  before this batch — no unrelated visual or behavioral changes.
- Zero console errors in both fixtures, including the new
  double-click/`file://` path from item 1.
- No hardcoded model names, detector weights, thresholds, or scoring
  constants introduced by any of these fixes.
- No network calls at all on default load (stronger than before — item
  1 removes the only fetch that existed).
- No secrets, keys, or tokens anywhere.
- `dashboard/README.md` updated per item 1's instruction (and only
  that — don't rewrite unrelated sections).

## Out of scope

- Anything not listed in the five items above.
- Any new view, any new interaction, any layout restructuring.
- Changing detector-state colors/icons, severity badge colors, or the
  clock-override banner.

If anything above is ambiguous, or conflicts with something you observe
in the current file, stop and ask rather than guessing.
