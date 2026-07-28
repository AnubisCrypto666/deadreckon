# deadreckon run output — schema **v0.1.0-draft**

> **DRAFT. Not frozen.** This is the shape `run_detectors.py --json` emits
> today, published for review by the dashboard author before it is fixed.
> Field names and nesting may still change. Freeze bumps this to `1.0.0`.

Produced by:

```bash
python run_detectors.py --json examples/sample-run.json
```

A real dump of the current fixture lives at
[`examples/sample-run.json`](../examples/sample-run.json) — five models,
covering every detector state and both a flagged and a clean model.

Serialization lives in `detectors/report.py`, which is the single source
of truth for this shape.

---

## Top level

| Field | Type | Notes |
|---|---|---|
| `schema_version` | string | `"0.1.0-draft"`. Fail loudly on an unexpected major version rather than rendering blanks. |
| `run` | object | Run metadata — see below. |
| `scoring` | object | The constants this run used. Shipped so the UI can render scales/legends without hardcoding them. |
| `models` | array | **Already in ranked order.** Render as-is; do not re-sort. |

### `run`

| Field | Type | Notes |
|---|---|---|
| `assessed_at` | ISO 8601 string | The instant the run assessed against. |
| `clock_overridden` | bool | True when `DEADRECKON_NOW`/`--as-of` was used (test/demo runs). Worth surfacing so nobody mistakes a shifted run for a live one. |
| `datahub_base_url` | string | Base used to build the `*_url` fields. |
| `models_assessed` | int | |
| `datasets_examined` | int | |
| `detectors` | string[] | `["D1","D2","D3"]`. |

### `scoring`

| Field | Type | Notes |
|---|---|---|
| `max_possible_score` | number | Currently `3.0`, and genuinely reachable — a model sits on it in the sample. Use it as the denominator; don't assume a 0–1 scale. |
| `detector_weights` | object | Per-detector confidence weight. |
| `environment_weights` | object | Serving-stage weights. |
| `latent_risk_floor` | number | Blast radius used for an undeployed model. |
| `severity_thresholds` | object | `{"HIGH": 2.0, "MEDIUM": 0.7}`; anything below MEDIUM is `LOW`. |
| `statuses` | string[] | All possible detector states. |

---

## `models[]`

| Field | Type | Notes |
|---|---|---|
| `urn` | string | DataHub URN. Stable identity — key off this, not `name`. |
| `name` | string | |
| `url` | string \| null | Deep link to the model in DataHub (URN percent-encoded). |
| `group` | object | `{urn, name}` of the `mlModelGroup`. Either may be `null`. |
| `serving_stages` | string[] | e.g. `["PROD"]`, `["STAGING"]`, or `[]` when not deployed. **Not** the environment segment of the URN — see the note below. |
| `score` | number | `0.0` when nothing was found. Not normalized to 0–1. |
| `severity` | string | `HIGH` \| `MEDIUM` \| `LOW`. |
| `blast_radius` | number | Worst serving stage reached (a max, not a sum). |
| `finding_count` | int | Also the ranking tie-breaker. |
| `coverage` | object | See below. |
| `detectors` | object | Keyed `D1`/`D2`/`D3` — see below. |
| `findings` | array | Possibly empty. See below. |
| `tags` | object | `{at_risk, unassessable}` — mirrors the tags written to the graph. |
| `assessment_document_urn` | string | The Model Risk Assessment document. **No URL:** document entities have no working profile route in this DataHub version (see `NOTES.md`), and a link that 404s is worse than none. |

### `models[].coverage`

How much of the model could actually be assessed. Deliberately separate
from the score: a detector that lacked the metadata to run is neither a
pass nor a risk, and folding "unknown" into the score would destroy the
meaning of both.

| Field | Type | Notes |
|---|---|---|
| `conclusive` | int | Detectors that reached a verdict. |
| `total` | int | Detectors run. |
| `label` | string | Pre-rendered `"2/3"`. |
| `fully_covered` | bool | `conclusive == total`. |
| `unassessable` | bool | `conclusive == 0` — no verdict at all. |

**A clean model with `fully_covered: false` is not the same as one with
`fully_covered: true`.** Please make that visible; collapsing them is
exactly the silent failure this project exists to catch.

### `models[].detectors.{D1,D2,D3}`

| Field | Type | Notes |
|---|---|---|
| `status` | string | `PASS` \| `FINDING` \| `INSUFFICIENT_DATA`. |
| `conclusive` | bool | True for `PASS` and `FINDING`. |
| `subjects_checked` | int | Datasets/features/transformations conclusively checked. |
| `finding_count` | int | |
| `missing` | array | `{missing, subject_urn, subject_url, detail}`. `missing` names the absent aspect/field (e.g. `operation.lastUpdatedTimestamp`) so the gap is actionable. |

Detector meanings:

- **D1** — frozen training source: upstream data stopped updating while training kept running.
- **D2** — schema drift under a feature: a feature's source column vanished after the last training run.
- **D3** — semantic change without retrain: an upstream dbt/Spark definition changed after the last training run.

### `models[].findings[]`

| Field | Type | Notes |
|---|---|---|
| `detector` | string | |
| `summary` | string | Full sentence, for the detail view. |
| `subject` | string | Compact "what/where" (e.g. `customers.credit_limit missing 3d`), for tables/cards. |
| `subject_urn` | string \| null | The upstream entity that broke — **not** the model. |
| `subject_url` | string \| null | Deep link to that entity. |
| `evidence` | object | Detector-specific, machine-readable. Keys vary by detector; treat as a bag for the detail view rather than something to switch on. |

---

## Notes for the dashboard

1. **`models` is pre-sorted** by `(score desc, finding_count desc)`. Ranking is one decision, made in the backend.
2. **Score is not 0–1.** Always show it against `scoring.max_possible_score`.
3. **Three states, not two.** `INSUFFICIENT_DATA` must be visually distinct from `PASS` — "we couldn't check" is not "it's fine". This is the core claim of the project.
4. **`serving_stages` vs the URN.** Every seeded entity's URN ends in `PROD` — that is DataHub's *catalog* fabric, not where the model serves. `serving_stages` is the real deployment. They can legitimately disagree (a model with URN fabric `PROD` and `serving_stages: ["STAGING"]` is correct, not a bug).
5. **Empty `findings` is a first-class result**, not an error state. A fully covered model with no findings is the strongest thing the agent can say.

## Open questions for review

- Is `evidence` useful as a free-form object, or should it be normalized per detector?
- Is `subject` (pre-truncated) the right split from `summary`, or would you rather format from `evidence` yourself?
- Should `missing` be pre-grouped by aspect (the graph writeback groups it; here it's one entry per subject)?
- Anything needed for the lineage view (spec §2 "ścieżka lineage z podświetlonym punktem zapłonu") that this doesn't carry — e.g. the full dataset→feature→run→model path rather than just the ignition point?
