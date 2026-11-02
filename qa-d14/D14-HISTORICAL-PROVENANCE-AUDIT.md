# D14 — Historical Results, Provenance & Reproducibility Audit

**Project:** Health AI – SRMNH Data Quality System
**Date:** 2026-11-02
**Mode:** Strict read-only audit (no writes, no migrations, no recalculation, no server)
**Database:** `health_ai` @ `127.0.0.1:5432`, PostgreSQL 17.11 — every session opened with `SET TRANSACTION READ ONLY`
**Branch / HEAD at audit:** `very-high-gate-integration` / `4b82b19388f0b8568ca8c33c62a9b5f7aa60daac`
**Working tree at audit:** 136 porcelain entries (65 modified tracked files, 89 untracked), 2 stashes, 0 staged
**Stored policy label on every layered row:** `policy_version = 2026-10-24.1` (`app/engine/comparison_policy.py:45`)

---

## A. Executive summary

Historical results are **internally consistent and largely reproducible**, but they were produced by a policy layer that is **not in version control** and, for a defined subset of alerts, by a **pre-cap scoring path**.

| Question | Answer |
|---|---|
| Can historical layered results be reproduced? | **6,005 / 10,787 (55.7%)** reproduce exactly from their own stored window and method. **4,618 (42.8%)** are `insufficient_history` rows that store no score (nothing to reproduce). **164 (1.5%)** are partially reproducible. **0** are impossible. |
| Can historical alerts be reproduced? | **5,062 / 7,156 (70.7%)** reproduce exactly. **1,091 (15.2%)** are **legacy pre-cap percentage-change results**. **1,003 (14.0%)** are partially reproducible (degenerate peer spread, or a score produced by a documented fallback). **0** are impossible. |
| Is policy provenance preserved? | **No.** The caps, the top-band gate and Rule B exist **only in the uncommitted working tree**. `HEAD`'s `layered.py` contains none of `PCT_CHANGE_CAP_POLICY`, `ZERO_SPREAD_LEVEL_CAP`, `MIN_PEERS_FOR_TOP_BAND`, `VERY_HIGH_ELIGIBILITY_POLICY` or `peer_very_high_eligibility`. Every row records the same constant `2026-10-24.1`, so the label cannot distinguish the engine that wrote it. |
| Are stored and current bands confused? | **No.** Stored values are never rewritten. Readers expose `stored_severity` beside the policy band (`effective_severity` / `effective_row_level`): 790 alerts and 146 layered rows are stored `VERY_HIGH` and presented `HIGH`. |
| Does the legacy difference reach downstream maths? | **Not the Quality Score.** The outlier penalty reads the stored layered band, so the 1,091 legacy alert scores do not change any penalty. It does reach **alert presentation and severity counts**. |

Two findings dominate:

1. **1,091 alert rows store an uncapped percentage-change score** (15 hospitals, 67 indicators, months 2026-01 → 2026-08). Recomputing them under the current cap would move **1,082 bands**, including **58 that would drop to `NONE`** — i.e. findings the current policy would not raise at all.
2. **The analytical policy is not reproducible from the repository.** The code that produced the latest results exists only as uncommitted work; `policy_version` is a hand-maintained constant copied onto every row.

No production record, band, score, threshold, configuration or migration was touched. The audit added one untracked report file (`qa-d14/`).

---

## B. Historical policy timeline

Commit history for the scoring core (`app/engine/anomaly/layered.py`):

| Commit | Date | What it introduced |
|---|---|---|
| `0689d3e` | 2026-10-10 | scoring core, bands (0.25/0.50/0.75/0.90), auto method selection |
| `d01fa8c` | 2026-10-10 | raw + historical-baseline layers |
| `74093a3` | 2026-10-10 | rate and volume/denominator layers |
| `cce0550` | 2026-10-10 | peer layer with tier fallback |
| `9cb13b1` | 2026-10-10 | entry point, orchestration |
| `aec5061` | 2026-10-23 | one detection truth from layers to alerts and explanations |

| Policy | Previous behaviour | Current behaviour | Evidence | Effective period | Affected | Historical impact |
|---|---|---|---|---|---|---|
| Z threshold | 2.5 | 2.5 | `quality_alerts.py` `z_threshold`; every one of 7,156 alerts stores 2.5 | whole history | alerts, layered, gate | **none** (0 rows differ) |
| Percentage-change cap | raw `|Δ%|/100`, can reach 1.0 | clamped to the same window's dispersion score | `PCT_CHANGE_CAP_POLICY`, `cap_pct_change`, `score_window_detail`; **absent from HEAD** | **UNKNOWN** (uncommitted) | alerts, layered history layer | **confirmed**: 1,091 alerts |
| Zero-dispersion cap | 1.0 on a zero divisor | layer band capped at `HIGH` | `ZERO_SPREAD_LEVEL_CAP`; **absent from HEAD** | **UNKNOWN** (uncommitted) | both | confirmed in stored evidence (`dispersion`, `zero_spread_layers`) |
| Thin-peer cap (<4 peers) | band allowed at VH | layer band capped at `HIGH`, no peer z | `MIN_PEERS_FOR_TOP_BAND`; **absent from HEAD** | **UNKNOWN** (uncommitted) | both | 1,559 alerts and 150 layered rows have `peer_count < 4` |
| Top-band eligibility gate | VH granted on the layer's own scale | VH requires the same window's dispersion band ≥ VH, else `HIGH` | `very_high_eligibility`, `row_very_high_eligibility`; **absent from HEAD** | **UNKNOWN** (uncommitted) | history claims only | **146 layered rows + 790 alerts** are stored VH, presented HIGH |
| Peer Rule B | peer z alone | statistical verdict from usable MAD/IQR; never changes the band | `peer_very_high_eligibility`; **absent from HEAD** | **UNKNOWN** (uncommitted) | peer claims | none (never lowers a band) |
| History window | unbounded | 12 months, minimum 3 observations | `comparison_policy.COMPARISON_POLICY_VERSION = "2026-10-24.1"`, stored on every row | **UNKNOWN** (constant, not dated) | both | baseline for every reproducibility check |
| Severity policy (trend) | — | normalises engine band to final band | stored `severity_policy.fingerprint = b80630c99211a85b` on 5,969 alerts | UNKNOWN | alerts | none observed |
| Engine version | **not recorded** | **not recorded** | no `engine_version` column/key anywhere | — | all | **UNKNOWN** |

**Effective dates cannot be established.** Alerts carry `detected_at` only on two days (2026-10-21: 6,474 rows; 2026-10-24: 682 rows), but both days contain *both* capped (32 and 45) and uncapped percentage-change rows — a rescan updates rows without moving `detected_at`, so the timestamp is not a write time. Per the rules of this audit, the effective period of the cap is therefore **UNKNOWN**, not inferred.

---

## C. Reproducibility matrix

Method: for every row, recompute in memory with the **current production functions** (`layered.score_window_detail`, `score_from_z`) from the row's own stored inputs (window values, current value, previous value, stored method, stored/default threshold). Nothing was persisted.

### Alerts (`quality_alerts`, n = 7,156)

| Class | Count | % | Basis |
|---|---|---|---|
| **A. Reproducible** | 5,062 | 70.7% | stored score == recomputed score within 1e-6 |
| **B. Partially reproducible** | 1,003 | 14.0% | 793 peer rows with stored group `std = 0` (score 1.0 is the documented degenerate fallback, magnitude unmeasurable) + 210 rows whose stored score does not match the stored window under the stored method |
| **C. Not reproducible** | 0 | 0% | every alert stores a window or summary statistics sufficient to recompute |
| **D. Legacy policy result** | 1,091 | 15.2% | stored score equals the **uncapped** percentage change while the current cap yields a lower score, and no `pct_change_cap` block is stored |

### Layered results (`layered_outlier_results`, n = 10,787)

| Class | Count | % | Basis |
|---|---|---|---|
| **A. Reproducible** | 6,005 | 55.7% | history-layer score == recomputed score from `history_provenance.values` |
| **B. Partially reproducible** | 164 | 1.5% | IQR 58, peer_zscore 50, zscore 35, pct_change 21 — stored window does not reproduce the stored score; cause **UNKNOWN** (possible window trimming or a different window at scan time) |
| **C. Not reproducible** | 0 | 0% | — |
| **D. Legacy policy result** | 0 | 0% | — |
| **N. No result stored** | 4,618 | 42.8% | `outlier_method = insufficient_history`, `historical_outlier_score = NULL` — not a scored result, so not classified as a reproducibility failure |

Peer-layer reproducibility: **10,655 rows (98.8%)** store the peer group's values; 132 store none. Alerts store peer groups as a **keyed object**, layered rows as a **flat array** — a format inconsistency, not data loss.

**Internal band consistency:** 696 layered rows store `outlier_level = NONE` while their own peer/volume scores imply `LOW` or above. This is **not corruption**: `classify.py:459` sets `level_from_layers = NONE` when rule 1 (insufficient history) fires, so those rows are policy-consistent and fully reproducible (stored window + method + rule). All 696 are from the 2026-10-27 batch, all `insufficient_history`, all stored *below* the layer maximum.

---

## D. Legacy results analysis

### D.1 Record 6589 (hospital 21, `5.b.1`, 2026-04)

| Field | Alert row (id 6589) | Layered row (id 206569) |
|---|---|---|
| Window | 2026-01: 45, 2026-02: 38, 2026-03: 15 | identical (`history_provenance.values = [45, 38, 15]`) |
| Current value | 29 | 29 |
| Method | `pct_change` | `pct_change` |
| Score | **0.9333** = 29 vs 15 (+93.3%), uncapped | **0.04672398052753415** = `|z|/5`, z = −0.2336 |
| Stored band | `VERY_HIGH` | `NONE` |
| Band shown now | `HIGH` (gate refuses the top band) | `NONE` |
| Cap evidence | **absent** (`pct_change_cap` not stored) | n/a (score already capped) |
| Written | detected 2026-10-24 07:55:28 | created 2026-10-29 09:00:03 |
| Policy label | `2026-10-24.1` | `2026-10-24.1` |

**Attribution:** the alert's stored score is exactly the *uncapped* percentage change and the current engine yields the capped 0.0467 from the same inputs, so the alert was written by a pre-cap scoring path. The layered row was regenerated after the cap. The two rows therefore differ by **policy generation, not by measurement** — same window, same current value, same z.

**Which policy version?** The uncapped path corresponds to `_score_window` before `cap_pct_change` was composed; that code is **not in git**, so the version is **UNKNOWN**; the closest identifiable label is "pre-`PCT_CHANGE_CAP_POLICY`", which the working tree marks only by constant name, not by a dated version.

**Does the current engine calculate the capped result consistently?** Yes: all 1,581 layered `pct_change` rows reproduce from the stored window, and every one of the 77 alerts that carries `pct_change_cap` reproduces with the cap applied. The cap is applied in one place (`layered.score_window_detail`) shared by both engines.

### D.2 The matching class

| Measure | Value |
|---|---|
| Alerts with `method = pct_change` | 1,284 |
| … carrying `pct_change_cap` evidence | 77 (all `history` perspective) |
| … storing the **uncapped** change with no cap evidence | **1,091** |
| Hospitals / indicators / months | 15 / 67 / 2026-01 … 2026-08 |
| Stored severity of the class | MODERATE 790, HIGH 110, VERY_HIGH 191 |
| Written batches (`detected_at`) | 2026-10-21: 859; 2026-10-24: 232 |
| Same-key alert↔layered pairs | 2,204 |
| … whose stored scores differ | **735** (268 with a `comparison_policy` block, 467 without) |

The **268** figure matches D13's earlier measurement: it counts the sub-class whose alerts still carry the `comparison_policy` provenance block. The additional **467** are the same phenomenon on rows written before that block was captured. Both are policy-generation differences, not two different causes.

### D.3 Where the difference is visible

| Surface | Effect |
|---|---|
| Alerts list / detail | Stored `VERY_HIGH`, presented `HIGH` where the gate refuses; score is the stored 0.9333 |
| Dashboard KPIs | Count via `effective_severity` — already the policy band, not the stored band |
| Diagnostics (layered) | Layered row is correct (`NONE`, 0.0467); the alert row is the outlier |
| Quality Scores | **No effect**: penalty reads the stored layered band (105 scores carry a penalty, total 2,993.9) |
| Reports | Read `effective_row_level`; the alert's stored 0.9333 is not recalculated anywhere |
| Explain | Shows both stored and effective bands with the cap reason |

Downstream verdict: **presentation only, already floored by the current gate**; no downstream arithmetic consumes the alert score.

---

## E. Provenance completeness

### Alerts

| Field | Present | Missing/NULL | Coverage | Reproducibility role |
|---|---|---|---|---|
| hospital_id, month, indicator_id/code | 7,156 | 0 | 100% | required — present |
| indicator_name, unit, formula, formula_version | 1,836 | **5,320** | 25.7% (data-element rows) | definition not captured historically |
| method | 7,156 | 0 | 100% | required — present |
| current_value / baseline_value | 7,156 | 0 | 100% | required — present |
| deviation_pct | 6,277 | 879 | 87.7% | supporting |
| z_score | 5,413 | **1,743** | 75.6% | not stored for degenerate/thin-peer rows (by policy) |
| peer_count | 7,156 | 0 | 100% | present |
| evidence.z_threshold | 7,156 | 0 | 100% | required — present, all 2.5 |
| evidence.stats (mean/median/std) | 7,156 | 0 | 100% | required — present |
| evidence.history (window pairs) | 2,512 | 4,644 peer rows n/a | 100% of history rows | required — present |
| evidence.peer_ids | 4,644 | — | 100% of peer rows | present |
| evidence.comparison_policy | **5,330** | 1,826 | 74.5% | window/min-observations/version missing on 25.5% |
| evidence.pct_change_cap | 77 | 1,207 pct rows | 6.0% of pct rows | **only written when the cap lowered the score** — absence is not proof, but stored value equals the uncapped change in all 1,091 legacy rows |
| evidence.severity_policy / final_severity | 5,969 | 1,187 | 83.4% | policy fingerprint `b80630c99211a85b` |
| detected_at, status, interpretation, confidence | 7,156 | 0 | 100% | present |

### Layered results

| Field | Present | Missing/NULL | Coverage | Role |
|---|---|---|---|---|
| history_provenance (window, months, min obs, version) | 10,787 | 0 | 100% | required — present |
| history_provenance.values | **9,075** | 1,712 empty | 84.1% | required for reproduction; empty exactly on no-history rows |
| peer_provenance.values | 10,655 | 132 | 98.8% | present (flat array) |
| classification_provenance | 10,787 | 0 | 100% | caps/level/version stored |
| classification_provenance.zscore_threshold | 217 | 10,570 | 2.0% | falls back to the saved 2.5 default — safe but not explicit |
| evidence | **0** | 10,787 | 0% | **no per-row evidence snapshot is stored** |
| historical_mean / historical_std | 9,075 / 7,586 | 1,712 / 3,201 | 84.1% / 70.3% | derivable from values |
| previous_value | 9,142 | 1,645 | 84.7% | derivable from values |
| z_score / change_percent | 5,195 / 6,072 | 5,592 / 4,715 | 48.2% / 56.3% | not stored when no measurable spread / no change layer |
| outlier_method, outlier_level, peer_count, created_at | 10,787 | 0 | 100% | present |

### Quality scores

| Field | Present | Missing | Note |
|---|---|---|---|
| score, components, outlier_penalty | 176 | 0 | 105 have a non-zero penalty (total 2,993.9) |
| scoring_config | 176 | 0 | present |
| scoring_fingerprint | 137 | **39** | 1 distinct value across the 137 |
| config_fingerprint | **0** | 176 | **never populated** |
| config_snapshot | **0** | 176 | **never populated** |
| quality_score_revisions | 0 | — | no revision trail exists |

**Distinctions used:** *missing* = the column/key is absent or NULL; *not captured historically* = the field did not exist when the row was written (alerts' `pct_change_cap`, layered `zscore_threshold`); *not applicable* = the layer/row was never scored (`insufficient_history`, peer z on a thin group); *unknown* = the value cannot be established from what is stored (engine version, effective dates).

---

## F. Cross-screen historical consistency

| Screen | Reader | Stored band shown? | Policy band shown? | Silent overwrite? |
|---|---|---|---|---|
| Alerts list / detail | `app/api/quality_alerts.py::_effective_severity` | yes (`stored_severity`) | yes (`effective_severity`, also `severity`) | no — two fields |
| Dashboard KPIs | `app/api/dashboard.py` → `effective_severity` | no (counts policy band) | yes | no write; but stored band is not surfaced here |
| Diagnostics / Very High analysis | `app/api/analysis.py` → `effective_row_level`, `row_level_assessment` | via `stored_severity` in the cap block | yes | no |
| Explain | `app/engine/audit/explain.py` | yes | yes | no |
| Reports | `app/api/reports.py` → `effective_row_level` | **no** — the report payload carries only the policy band | yes | no write, but the historical band is not reported |
| Export | same report path | as above | yes | no |

Answers to the section-8 checks:

- **Stored values are not silently replaced.** All readers that need the current band recompute it from stored evidence and label it; none writes back.
- **Effective vs stored is distinguished** on alerts, diagnostics and explain; on reports and dashboard the stored band is not exposed, so a cap is invisible there (risk R6).
- **Historical policy differences are not hidden** on the alert detail (the cap block is rendered), but the 1,091 legacy rows carry no cap block because the cap did not exist at write time — the detail therefore shows the stored `VERY_HIGH` beside a gate-derived `HIGH` without naming the percentage-change cap.
- **Missing provenance is not presented as verified**: a peer row without a stored group is `undecided`, not eligible; a refused top band reports its reason.
- **KPI definitions preserved**: alerts counts and dashboard counts both fold through `effective_severity`; D12 measured parity (2,658 alerts / 801 issues). No duplicate keys introduced: 7,156 alerts fold into **1,130** distinct (hospital, indicator, month) issue keys and 5,043 rows are `active`.
- **Filters use the policy band** (`_matches_severity`), so filtering by `VERY_HIGH` on Alerts excludes the 790 rows stored VH but presented HIGH — a legitimate, documented projection difference, not a lost record.

---

## G. Recalculation impact (analysis only — nothing recalculated or persisted)

| Category | Alerts | Hospitals | Indicators | Months | Band change if recalculated |
|---|---|---|---|---|---|
| Legacy uncapped percentage change | **1,091** | 15 | 67 | 2026-01 … 2026-08 | **1,082 change band**, measured: MODERATE→LOW 350, MODERATE→NONE 437, VERY_HIGH→NONE 58, VERY_HIGH→LOW 84, VERY_HIGH→MODERATE 40, VERY_HIGH→HIGH 6, HIGH→LOW 55, HIGH→NONE 48, HIGH→MODERATE 4; 125 keep their band |
| Layered rows with a partial reproduction | 164 rows | — | — | — | **UNKNOWN** — the stored window does not reproduce the score, so the correct band cannot be asserted |
| Rows whose band is already floored by the current gate | 790 alerts / 146 layered | — | — | — | 0 (presentation already reflects the floor) |

- **Alert KPI impact:** `VERY_HIGH` would lose at least the 191 legacy rows currently stored VH (and up to 790 already-floored rows if the stored band were counted instead). Counted today through `effective_severity`, none of the 790 is in the VH KPI.
- **Quality Score impact:** **0.0 points** — the penalty reads stored layered levels; no legacy alert score is an input. 105 scores carry penalties totalling 2,993.9.
- **Effective severity impact:** 0 as displayed; the 1,082 measured band changes describe what a *recalculation* would store, not a current display difference.
- **Not measured (UNKNOWN):** whether the 164 partial layered rows would move, and what a full regeneration of all 8 months would produce (out of scope; would require a write phase).

---

## H. Future provenance contract (recommendation only — not implemented)

**A. Minimum fields per result row**
`engine_version`, `scoring_policy_version`, `eligibility_policy_version`, `threshold_set_version`, `input_snapshot` (window months + values + current + previous), `method`, `method_selection_reason`, `computed_score_raw`, `score_after_caps`, `cap_blocks[]`, `gate_decision`, `band_stored`, `band_effective_at_write`, `created_at`, `run_id`.

**B. Policy versioning** — version each policy independently (score, caps, gate, peer eligibility, window) and store the tuple; never a single hand-edited constant. A version is immutable and its definition is committed alongside the code.

**C. Engine versioning** — a build identifier (commit SHA + dirty flag) written by the pipeline at insert time. `HEAD`-based SHA makes the current "policy exists only in the working tree" situation detectable after the fact.

**D. Input snapshot** — the exact window used (months, values, skipped months), the current/previous values, the peer group's values *and* their hospital ids, and the z threshold actually used, stored on every row (not only when a cap fires).

**E. Historical interpretation** — a row without an engine version is labelled `unversioned`; a row whose score cannot be reproduced is labelled `partial`, never "verified". Legacy rows keep their stored band and gain a `legacy_reason` once approved.

**F. Reproducibility status** — a stored enum: `verified` (recomputed == stored), `partial`, `legacy_policy`, `unknown`, `not_reproducible`, with the recomputation timestamp and engine version that produced the verdict.

**G. UI** — Alerts, Diagnostics and Explain show three values when they differ: *stored*, *policy now*, and *why* (cap/gate/legacy). Reports include the stored band beside the policy band. A row with `unknown` status is presented as "provenance incomplete", never as incorrect.

Backward compatible: new columns/keys are nullable; existing readers fall back to today's behaviour; no API payload is required to change for the proposal to take effect (a read-time `provenance_status` field can be added first).

---

## I. Defect and risk register

| ID | Type | Severity | Statement | Evidence |
|---|---|---|---|---|
| R1 | **Confirmed defect (historical)** | High | 1,091 alerts store uncapped percentage-change scores; 1,082 would change band and 58 would become `NONE` under current policy | §D.2, §G |
| R2 | **Confirmed defect (process)** | High | The caps, gate and Rule B exist only in the uncommitted working tree; `policy_version` is a constant copied to all 10,787 rows | §B (`git show HEAD` matched none) |
| R3 | Provenance gap | High | No engine version anywhere; `quality_scores.config_fingerprint`/`config_snapshot` are NULL on all 176 rows; `scoring_fingerprint` NULL on 39 | §E |
| R4 | Provenance gap | Medium | Alerts: formula/unit absent on 5,320 rows (74.4%), `comparison_policy` absent on 1,826 (25.5%); layered `evidence` absent on 100% | §E |
| R5 | Limitation | Medium | 164 layered rows are only partially reproducible; cause unknown | §C |
| R6 | Presentation | Medium | Reports and Dashboard expose only the policy band; a stored/policy difference is invisible there | §F |
| R7 | Data-shape inconsistency | Low | Peer group stored as keyed object in alerts but as array in layered rows | §C |
| R8 | Limitation | Low | `zscore_threshold` stored on 217/10,787 layered rows; the rest rely on the 2.5 default | §E |
| R9 | Unknown | Low | Effective period of every uncommitted policy is UNKNOWN; `detected_at` is not a write time | §B |

---

## J. Validation results

| Check | Command | Result |
|---|---|---|
| Focused regression (read-only SQLite fixtures through `tests/conftest.py`) | `python -m pytest tests/test_d13_integrity.py tests/test_very_high_gate_wiring.py tests/test_layered_engine.py tests/test_pct_change_cap.py tests/test_thin_peer_z.py tests/test_quality_alert_zero_spread.py tests/test_indicators_tab.py -q` | **184 passed, 0 failed, 0 skipped, exit 0** (193.34s) |
| Recalculation of stored results | in-process `layered.score_window_detail` / `score_from_z` only, no session flush | 7,156 + 10,787 rows evaluated, **0 writes** |
| Database target | `health_ai` PostgreSQL for reads (READ ONLY transaction); SQLite temp files for pytest | production rows untouched |
| Full suite | not run in D14 (D13 ran 800 passed / 1 skipped on the same tree) | reported as not run, not as passing |

Tests were not modified. No test can write to production: the pytest fixtures create isolated SQLite databases.

---

## K. Database integrity evidence (before → after)

| Metric | Before | After |
|---|---|---|
| `quality_alerts` rows / `sum(id)` / `max(id)` | 7,156 / 25,607,746 / 7,156 | identical |
| Alert severity fold | MOD 2,745, HIGH 2,235, VH 2,176 | identical |
| `quality_alerts` fingerprint (id, severity, score, method, perspective) | `de3fa35b0bd1d0dc41b803950498c1f4` | identical |
| `layered_outlier_results` rows / `sum(id)` / `max(id)` | 10,787 / 2,210,709,624 / 211,960 | identical |
| Layered band fold | NONE 7,889, LOW 1,289, MOD 453, HIGH 639, VH 517 | identical |
| Layered fingerprint (id, level, five scores) | `23f50892433d958ea857e803a3dc5631` | identical |
| `quality_scores` rows / `sum(id)` / fingerprint | 176 / 367,576 / `73b80c278609e75f5001b86a76637f57` | identical |
| Alerts whose stored threshold ≠ 2.5 | 0 | 0 |
| Inserts / updates / deletes / migrations / backfills | — | **none** |
| Branch / HEAD | `very-high-gate-integration` / `4b82b19` | unchanged |
| Stashes / staged files / porcelain entries | 2 / 0 / 136 | unchanged |

---

## L. Human review recommendation

### READY WITH LIMITATIONS

Historical integrity is **not at risk**: stored results are never overwritten, the presentation layer already distinguishes stored from policy bands, and the engine reproduces its own outputs exactly for 6,005 layered rows and 5,062 alerts.

The limitations are provenance, not corruption:

1. **R1** — 1,091 legacy uncapped alerts (measured) require a separately approved recalculation phase; they must not be re-graded in place without that approval.
2. **R2** — the analytical policy is not committed; no row can be attributed to a dated engine.
3. **R3/R4** — engine version, score config fingerprints and per-row evidence snapshots are missing, so a future change cannot be audited from the data alone.
4. **R5** — 164 layered rows remain partially reproducible; cause UNKNOWN.

Recommended next phase (not started, awaiting approval): implement the provenance contract in §H on **new** results only, leaving all existing rows untouched, and treat the 1,091 legacy alerts as a labelled class rather than a correction target.
