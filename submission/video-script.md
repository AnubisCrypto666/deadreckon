# deadreckon — video script

**Target run time: 2:33, hard cap 3:00.** Written for one person
reading from the screen and clicking with one hand — every beat names
the exact click. Timings are narration-read estimates; the ~27s margin
to the cap is deliberate and lives in the script, not in on-the-day
discipline — a live take with real clicks and transitions always runs
longer than a silent read.

Two shots below are marked **[NOTES]** — they come directly from
`NOTES.md`'s video-script notes and are the two moments this script is
built around. Don't cut either one, even under time pressure.

Recommended prep before recording:
- Have `dashboard/index.html` already open in a tab, on the **Matrix**
  view, showing `examples/sample-run.json` (its embedded default).
- Have `examples/sample-run-edge-cases.json` ready to drag in from a
  visible Finder/Explorer window or the file picker.
- Have a second browser tab pre-authenticated into the local DataHub
  UI (`http://localhost:9002`), not yet navigated anywhere — you'll
  click into it from the dashboard, not type a URL.
- Have a static slide (or the rendered `README.md` Mermaid diagram) ready
  for the architecture beat.

---

## 1. The problem — 0:00–0:20 (20s)

**On screen:** title card / static slide — "deadreckon" + one line of
subtext, no UI yet.

**Voiceover:**

> Production ML models rarely fail loudly. A serving metric looks fine,
> the pipeline runs on schedule — but four hops upstream, a column got
> renamed, or a table stopped refreshing, and nobody connected the
> dots. deadreckon is an agent that walks a model's full lineage in
> DataHub, using metadata only, and tells you not just what it found —
> but what it couldn't check at all.

---

## 2. Matrix view — 0:20–0:33 (13s)

**On screen:** dashboard already open, Matrix tab, `sample-run.json`
loaded. Point at the row for `taxi_fare_predictor_v1` (bottom row, all
green) and at one `INSUFFICIENT_DATA` cell.

**Voiceover:**

> Five models, three detectors each. Every cell is one of three states —
> pass, finding, or insufficient data — never just red or green. And
> here's the control: `taxi_fare_predictor_v1`, checked clean across the
> board.

---

## 3. Drill-down: INSUFFICIENT_DATA reasoning — 0:33–0:50 (17s)

**Click:** the `D1` cell for `customer_churn_predictor_v2` (top row,
amber `INSUFFICIENT DATA`).

**On screen:** the drill-down modal opens, showing the coverage-gap
reasoning (which aspect is missing, on which datasets).

**Voiceover:**

> Click any cell — even this one. D1 didn't pass this model, and it
> didn't flag it either — it's telling us the metadata it needed just
> isn't there. That's a different claim than "safe," and most systems
> don't make the distinction.

**Click:** close the modal (✕ or Escape).

---

## 4. Ranking & Coverage, clean run — 0:50–1:01 (11s)

**Click:** the **Ranking & Coverage** tab.

**On screen:** the scatter plot, `sample-run.json` still loaded. Point
at the empty shaded band at the bottom.

**Voiceover:**

> Risk and coverage plotted as two separate axes. Right now, the
> "unverified" zone down here is empty — it exists by design, not for
> one demo case.

---

## 5. Swap to edge-cases — the zone populates live — 1:01–1:13 (12s) **[NOTES]**

**Click:** the file picker (or drag-and-drop) → load
`examples/sample-run-edge-cases.json`.

**On screen:** the same scatter plot re-renders; a point
(`session_ltv_predictor_v2`) appears inside the shaded zone.

**Voiceover:**

> Now watch a different run load. There — a model that scored zero, but
> wasn't checked at all, landing exactly where it should, right next to
> another zero-score model that's actually clean.

---

## 6. Ignition subgraph — 1:13–1:33 (20s)

`customer_churn_predictor_v2` (needed for this beat and the next) only
exists in the real fixture, not the edge-cases file just loaded — swap
back first.

**Click:** the file picker → reload `examples/sample-run.json` (or
just refresh the page, since it's embedded as the default). **Click:**
the **Matrix** tab. **Click:** the `D2` `FINDING` cell for
`customer_churn_predictor_v2` (top row).

**On screen:** the drill-down modal, scroll to the ignition subgraph
strip below the finding summary — the amber-highlighted ignition node
with its causal annotation, the arrows, and the "Open full lineage in
DataHub →" link.

**Voiceover:**

> Back to the real run, same model, its schema-drift finding. Here's
> the ignition path — the exact node where this started, annotated
> with *why* — plus a real deep-link into DataHub. Not a redraw of
> DataHub's own lineage view, just the one thing it doesn't say.

---

## 7. Into DataHub — the graph writeback, live — 1:33–1:55 (22s) **[NOTES]**

**Click:** the "Open full lineage in DataHub →" link (or the model name
link) — opens `customer_churn_predictor_v2`'s real profile page in
DataHub, in the pre-opened tab.

**On screen:** the model's entity page in DataHub UI. Point at the
`undertow:at-risk` tag near the title, then click into the
**Documentation** tab and point at the three `[deadreckon]` notes —
especially the one stating what wasn't checked.

**Voiceover:**

> And that link is real. Same model, live in DataHub: tagged
> `undertow:at-risk`, and three deadreckon notes right in its
> Documentation tab — including one that says exactly what wasn't
> checked. This isn't a report sitting in a file. It's written back
> into the graph.

---

## 8. Architecture + open-source contributions — 1:55–2:25 (30s)

Full architecture diagram is in `README.md` — a judge who wants it will
find it there. This beat is one sentence per topic, not a diagram
walkthrough.

**On screen:** a brief flash of the README's architecture section
(2–3s), then a simple text overlay naming the two filed issues
(`#18657`, `#18675`).

**Voiceover:**

> Under the hood, three detectors read DataHub's ML lineage through its
> MCP server, score by weight and blast radius, and write everything
> straight back into the graph you just saw — full architecture's in
> the README. Building this also surfaced two real DataHub bugs, both
> filed upstream and fixed in this repo: an OpenSearch crash, and a
> broken Document-entity link.

---

## 9. Close — 2:25–2:33 (8s)

**On screen:** repo URL / static end card.

**Voiceover:**

> Code, examples, and full setup instructions are all in the repo
> below — Apache 2.0 licensed.

---

## Timing summary

| Beat | Duration | Running total |
|---|---|---|
| 1. Problem | 20s | 0:20 |
| 2. Matrix | 13s | 0:33 |
| 3. Drill-down (INSUFFICIENT_DATA) | 17s | 0:50 |
| 4. Ranking & Coverage (clean) | 11s | 1:01 |
| 5. Swap to edge-cases **[NOTES]** | 12s | 1:13 |
| 6. Ignition subgraph (swap back first) | 20s | 1:33 |
| 7. Into DataHub **[NOTES]** | 22s | 1:55 |
| 8. Architecture + OSS (one sentence each) | 30s | 2:25 |
| 9. Close | 8s | 2:33 |

Scripted at **2:33**, ~27s under the 3:00 cap — the margin is
deliberate, not a rounding error; live delivery and click/transition
time reliably run longer than a silent read of this script.
