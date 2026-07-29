# deadreckon dashboard — views 4.1 (matrix) and 4.2 (ranking & coverage)

A static, self-contained dashboard for one completed deadreckon run. It can show either the model × detector risk matrix or a risk-versus-coverage scatter view, and makes the system's "honesty about what it did not check" legible at a glance.

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

## Notes

- Zero network calls other than loading the single local run JSON.
- Schema major version is validated; only `1.x.x` is accepted.
- All rendering data comes from the JSON — no hardcoded model names, detector weights, thresholds, or scoring constants.
