# deadreckon dashboard — views 4.1 (matrix), 4.2 (ranking & coverage), and 4.3 (drill-down)

A static, self-contained dashboard for one completed deadreckon run. It shows the model × detector risk matrix, a risk-versus-coverage scatter view, and a per-cell finding drill-down, all to make the system's "honesty about what it did not check" legible at a glance.

## Run locally

No build step and no dependencies. The only requirement is a local static server so the browser can fetch the default run JSON.

From the repo root:

```bash
npx serve .
```

Then open `http://localhost:3000/dashboard/` (or the URL `npx serve` prints).

If you prefer Python:

```bash
python -m http.server 8000
```

Then open `http://localhost:8000/dashboard/`.

### Opening the file directly

You can also open `dashboard/index.html` directly in a browser, but most browsers block the default `examples/sample-run.json` fetch under the `file://` protocol. The UI will fall back to a file picker so you can still drop in any run JSON.

## Load a different run

Use the **Load run JSON** button in the top-right, or drag and drop a run file anywhere onto the page. Both `examples/sample-run.json` and `examples/sample-run-edge-cases.json` are accepted.

## Switch views

Use the **Matrix** / **Ranking & Coverage** tabs at the top of the page. Both views render from the same already-loaded run data; switching does not re-read the file.

A permanent banner appears above either view when `run.clock_overridden` is `true`.

## Matrix view (4.1)

- Rows = models, in the order the JSON provides them.
- Columns = detectors (`D1`, `D2`, `D3`), using the titles from `detectors_meta`.
- Per row: model name, `risk=X/Y` against `scoring.max_possible_score`, a severity badge, and `coverage.label`.
- Each detector cell shows a distinct shape + color state: `PASS` (green check), `FINDING` (red cross), and `INSUFFICIENT_DATA` (amber question mark).

## Ranking & Coverage view (4.2)

- A scatter plot with risk on the horizontal axis (`0` to `scoring.max_possible_score`) and coverage on the vertical axis (`0/3` to `3/3`, read from `coverage.label`).
- Every model is positioned by both dimensions at once, with its name labeled next to its point.
- The bottom band is shaded and labeled **"Unverified — not the same as safe"** so a model with `score=0.0` and `coverage=0/3` is immediately distinguishable from a model with `score=0.0` and `coverage=3/3`.
- Point shape and color indicate the model's status: fully checked/clean, at risk, finding-but-not-at-risk, or unassessable.

## Drill-down view (4.3)

- Click any detector cell in the Matrix view to open a drill-down for that model × detector.
- `FINDING` cells show every finding: the full summary, the linked subject (when `subject_url` is present), and the evidence fields with human-readable, per-detector labels.
- `PASS` cells show **"No findings — N subjects checked"** to make a clean, fully checked result a first-class outcome.
- `INSUFFICIENT_DATA` cells show the grouped `coverage_gaps`: the missing aspect, count, and each subject (linked when a URL is present).
- Deep links are only ever built from `url` values already present in the run JSON (`model.url`, `finding.subject_url`, `lineage_path[].url`, `coverage_gaps[].subjects[].url`). URNs without a matching URL are rendered as plain monospace text.

## Notes

- Zero network calls other than loading the single local run JSON.
- Schema major version is validated; only `1.x.x` is accepted.
- All rendering data comes from the JSON — no hardcoded model names, detector weights, thresholds, or scoring constants.
