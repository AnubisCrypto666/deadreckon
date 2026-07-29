# deadreckon dashboard — view 4.1, the risk matrix

A static, self-contained dashboard for one completed deadreckon run. It renders the model × detector risk matrix and makes the system's "honesty about what it did not check" legible at a glance.

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

## What it shows

- Rows = models, in the order the JSON provides them.
- Columns = detectors (`D1`, `D2`, `D3`), using the titles from `detectors_meta`.
- Per row: model name, `risk=X/Y` against `scoring.max_possible_score`, a severity badge, and `coverage.label`.
- Each detector cell shows a distinct shape + color state: `PASS` (green check), `FINDING` (red cross), and `INSUFFICIENT_DATA` (amber question mark).
- A permanent banner appears when `run.clock_overridden` is `true`.

## Notes

- Zero network calls other than loading the single local run JSON.
- Schema major version is validated; only `1.x.x` is accepted.
- All rendering data comes from the JSON — no hardcoded model names, detector weights, thresholds, or scoring constants.
