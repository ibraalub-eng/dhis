# Severity Caps Policy — pre-approval verification audit

**Date:** 2026-10-29
**Mode:** read-only. No data, schema, configuration, threshold or code was changed;
the only artefact is this report. Every figure below was recomputed from one
database snapshot with SQLAlchemy read queries (see *Reproduction* at the end).
**Store:** `quality_alerts` 7,156 rows, `layered_outlier_results` 10,787 rows,
months 2026-01 … 2026-08, 18 active hospitals.

## Verdict

| # | Checklist section | Verdict |
|---|---|---|
| 1 | Severity calculation and thresholds | **Pass** — one cutoff table, boundaries as documented, one normalization path |
| 2 | Severity Caps Policy | **Pass** — all four rules hold; the zero-dispersion test now uses each method's own divisor (F1 fixed) |
| 3 | Statistical validity | **Pass** — zero **std** and zero **MAD/IQR** are both handled (F1 fixed); extreme z values located and explained |
| 4 | Consistency across the application | **Pass with one row-level gap** — shared implementation; Outlier Diagnostics has no read-time cap and holds 1 stale Very High row (F2) |
| 5 | Evidence and audit trail | **Pass**, with two provenance omissions (F5) |
| 6 | Reported numbers | **Pass** — all five figures reproduce exactly; the apparent contradiction is scope + unit mixing, not arithmetic |
| 7 | Regression tests | **Pass** (156 passed) **with coverage gaps** (F4) |

Approval can proceed for the policy as implemented. F1 was approved and is
fixed: a comparison whose own divisor is zero can no longer claim `VERY_HIGH`,
which moved 270 open issues `VERY_HIGH → HIGH` (Very High count now 947).

---

## 1. Severity calculation and thresholds

### 1.1 Boundaries

`BAND_CUTOFFS` in [layered.py](../app/engine/anomaly/layered.py) is the only
cutoff table in `app/` (pinned by
`tests/test_severity_consistency.py::test_canonical_scale_is_the_only_band_scale`).
Each entry is an **exclusive upper bound**, so a score equal to a boundary takes
the band *above* it:

| Score | Band | Note |
|---|---|---|
| `< 0.25` | `NONE` | |
| `0.25` exactly | **`LOW`** | 0.25 is the first LOW score, not the last NONE |
| `0.50` exactly | **`MODERATE`** | |
| `0.75` exactly | **`HIGH`** | |
| `0.90` exactly | **`VERY_HIGH`** | |
| `1.0` | `VERY_HIGH` | saturation |

Verified by direct call: `0.2499 → NONE`, `0.25 → LOW`, `0.4999 → LOW`,
`0.50 → MODERATE`, `0.7499 → MODERATE`, `0.75 → HIGH`, `0.8999 → HIGH`,
`0.90 → VERY_HIGH`. `None` stays `None` (layer not applicable), never `NONE`.

### 1.2 Where severity comes from

Severity is **derived from the score**, not assigned by the detection layers:
each layer produces a `score` and its `level` property is
`level_for_score(score)`. The classifier takes the highest layer band, applies
the per-layer caps, then the small-denominator guard.

Two vocabularies still exist and are deliberately normalized by
[severity.py](../app/engine/severity.py) without inventing a band:
rules → `CRITICAL/HIGH/MEDIUM/LOW` → `VERY_HIGH/HIGH/MODERATE/LOW`;
trend labels use their own %-slope bands (`2/5/15/30`) and are only recorded
unless the trend policy is `escalate`/`override`, whose default is **none**.
Confidence uses the same four words for a different dimension and is never
summed into severity (pinned by a test). No module defines a second 0-1 cutoff
table.

Quality Alerts accepts `LOW/MODERATE/HIGH/VERY_HIGH` (canonical scale minus
`NONE`); with the current floor `alerts_min_score = 0.5` the store holds
`MODERATE` and above only.

---

## 2. Severity Caps Policy

| Rule | Implementation | Verified behaviour |
|---|---|---|
| `cap_pct_change` | [layered.cap_pct_change](../app/engine/anomaly/layered.py) → `_score_window_detail` | Clamps `min(pct_score, z_score)` **only** when the window has ≥2 observations and `std > 0`. With `std = 0` or one point it returns the raw score unchanged. Score only, per layer. |
| `cap_zero_spread` | [layered.cap_zero_spread](../app/engine/anomaly/layered.py) | Refuses the top band (`VERY_HIGH → HIGH`) when a spread-based score had `std = 0`. Returns `(band, provenance)`; the score, indicator values, baseline and z are untouched. `capped: false` in the provenance when the band was already ≤ `HIGH`. |
| `cap_thin_peer` | [layered.cap_thin_peer](../app/engine/anomaly/layered.py) | Peer comparison with `< 4` peers cannot exceed `HIGH`; only applies when `method = peer_zscore`. History `peer_count` (months) is exempt. The no-z rule (`peer_z_measurable`) withholds the z for the same groups. |
| Monotonic | both caps compare `LEVEL_RANK` and only lower | A cap never raises a band. |
| `MODERATE` stays `MODERATE` | cap threshold is `HIGH` | `cap_zero_spread("MODERATE", 0.0) → ("MODERATE", …capped: false)`; same for thin peer. `LOW`/`NONE` also unchanged. |
| Per layer, never per row | `classify._layer_band` + `degenerate_layers` / `thin_peer_layers` | A capped layer cannot suppress a measured sibling: 0 of 799 stored Diagnostics `VERY_HIGH` rows carry a capped layer that decided the row, and 131 rows were written `HIGH` with `level_from_layers = VERY_HIGH` (cap actually applied). |
| `INSUFFICIENT_HISTORY` | `outlier_type`, not a band | 4,419 Diagnostics rows carry the type; **0** carry a level other than `NONE`. `QUALITY_ALERT_SEVERITIES` has no such value. |

Composition order is identical on both engines: percentage-change clamp at score
time → band → trend policy → zero-dispersion cap → thin-peer cap.

**Idempotency:** re-applying `effective_severity` to its own result changed **0
of 7,156** alert rows.

---

## 3. Statistical validity

| Check | Result |
|---|---|
| z not treated as measurable at `std = 0` | Pass — `compute_peer_layer`, `compute_historical_layer` and alert `_peer_score`/`_history_score` all store `z = NULL` when `std = 0`; the score keeps the documented 1.0 fallback and the band cap grades it. |
| Extreme `|z| = 224` | Located: alert id 847, hospital 36, 2026-08, `governorate`, `peer_count = 2`, `z = -224.15`. Presented as `HIGH` with **no z** (`effective_z_score` withholds it). Not displayed as a measured magnitude anywhere. |
| `stored_z_score` shown raw? | No. The API keeps `stored_z_score` for audit and publishes `z_score` (withheld) plus `z_provenance`; the detail card prints a dash with "Too few peer hospitals to measure a spread". |
| 2–3-peer z rows in store | 887 rows still carry a stored z from a `< 4`-peer group (pre-policy rows); all are withheld at read time on Quality Alerts and the benchmark/root-cause/regional/explain surfaces. |
| `min_peers` independent of caps | Pass — `compute_peer_layer` uses `max(2, min_peers)` to decide layer **availability**; the caps use the fixed `MIN_PEERS_FOR_TOP_BAND = 4` only for the **band**. |
| History `peer_count` counts months | Pass — history findings store `len(series)` months, and both cap functions ignore `peer_count` unless `method = peer_zscore`. |
| History z extremes | 21 open rows have `|z| ≥ 10` (max 23.2) on 3–7 baseline points. Arithmetically valid, statistically weak; no policy covers them (observation F6). |
| High z at 4+ peers | 236 open peer rows have `|z| ≥ 10` with ≥4 peers (max 108.6) — a near-identical peer cluster still yields a huge ratio. The score is saturated either way; the z is displayed. Observation F6. |

### Finding F1 (high) — a zero MAD / zero IQR still claims `VERY_HIGH`

`zero_dispersion()` tests **std only**. But the robust builders divide by MAD,
and the IQR builder by IQR, and both have an explicit ungraded fallback:
`score_from_mad(mad=0) → 1.0`, `score_from_iqr(iqr=0) → 1.0`. A series where
more than half the points share the median therefore has `std > 0` but a
**zero divisor**, so neither cap fires.

Live example: alert 1889, hospital 36, 2026-02, history `[0,0,1,4,0,0,0]`,
current `1`, median `0`, **MAD = 0**, `std = 1.50`, score `1.0`, band
`VERY_HIGH`.

| Measure | Count |
|---|---|
| Open Very High alert rows scored by a zero MAD/IQR (std > 0) | **297** (294 MAD, 3 IQR) |
| … of which the issue has no other Very High row | **270** |
| Very High issues affected (1,217 → at most 947) | **270 (22%)** |
| Diagnostics `VERY_HIGH` rows with zero MAD/IQR | **295 of 539** (291 MAD, 4 IQR) |

This is the same defect the zero-dispersion policy was written for, on a
different divisor, and it is the largest single driver of over-detection in the
current store. It is a cap **extension**, not a threshold change, but it moves
270 open issues, so it needs an explicit decision.

**Status: fixed (approved).** `layered.spread_used()` now returns the divisor
per method (`std`, `mad`, `iqr`, `residual_std`) and both engines cap on it;
new rows record `stats.mad` / `stats.iqr`, the cap records
`dispersion: {kind, value}`, and rows written before it recompute the divisor
from the stored history series. Measured at read time, nothing rewritten:
**270 open issues** move `VERY_HIGH → HIGH` — the Very High count reads **947**
(was 1,217) against an unchanged total of **2,658**, and re-applying the policy
to the capped band changes 0 of 2,881 rows (idempotent). Regression tests:
`test_a_robust_method_is_graded_by_its_own_divisor`,
`test_a_zero_median_deviation_is_degenerate_even_when_std_is_not`,
`test_a_recorded_divisor_is_used_without_the_series`,
`test_the_scan_records_the_divisor_it_scored_with`.

---

## 4. Consistency across the application

* **One implementation.** `cap_pct_change`, `cap_zero_spread`, `cap_thin_peer`,
  `zero_dispersion`, `peer_z_measurable` and `BAND_CUTOFFS` live only in
  `app/engine/anomaly/layered.py`. `app/engine/quality_alerts.py` re-exports thin
  adapters over the same functions; there is no second copy.
* **One read-time band.** `quality_alerts.effective_severity` recomputes both
  caps from the row's own `evidence["stats"]` and `peer_count`, so pre-policy
  rows are presented under the current policy. It is used by:
  the dashboard Very High KPI, `GET /quality-alerts/summary`
  (`very_high_rows`, `by_severity`, `very_high_issues`, the two clickable
  buckets), the issues table and its `severity` filter, the alert detail and
  the explain/cross-check payload.
* **Same row, same answer.** On the snapshot, the summary's `very_high_rows`
  resolves to 1,686 rows and its `very_high_issues` to 1,217 issues — the same
  1,217 the dashboard Very High Issues card, the issues table and the two
  clickable buckets (667 + 550) resolve to.
* **Stored vs effective is visible.** The payload carries
  `severity` (effective), `stored_severity`, and `severity_cap` with
  `{stored_severity, severity, dispersion, thin_peer_group}`; the table and the
  detail badge render `STORED X → Y` with the policy reason.
* **Capped rows never become `NORMAL`/`NONE`.** Across 7,156 rows the minimum
  effective band is `HIGH`, identical to the minimum stored band; both caps
  return `HIGH` as the floor for a top-band row.
* **Rows without an applicable cap are unchanged.** 592 rows moved, all
  `VERY_HIGH → HIGH`; no other transition exists in the store.

### Finding F2 (medium) — Outlier Diagnostics serves stored bands with no read-time cap

`GET /analysis/...` layered endpoints filter and return
`LayeredOutlierResult.outlier_level` verbatim. One stored row contradicts the
policy:

| Row | Detail |
|---|---|
| `layered_outlier_results.id` | 202771 |
| Hospital / month | 26 / 2026-04 |
| Peer group | 3 peers, `peer_score = 0.9238` |
| Stored | `PEER_ANOMALY`, `VERY_HIGH`, provenance omits `thin_peer_layers` |
| Policy band | `HIGH` |

Two further rows (197264, 205368) already hold `HIGH`, i.e. the cap applied but
the provenance key was not written — the whole store predates the
`thin_peer_layers` provenance field (0 of 10,787 rows have it). The impact is
one row, but it is a real screen disagreement; the other screens already withhold
its z.

**Resolved 2026-10-29 twice over: the read-time band now applies the caps, and
the affected months were rescanned.** `GET /analysis/layered` (and its
`/trend` and `/heatmap` siblings) re-applies both caps when it reads a row via
`layered.row_level_assessment`: `outlier_level` is the policy band,
`stored_outlier_level` is what the row holds, `severity_cap` explains the
difference, and the level filter/counts are answered from the policy band. A
row written before a cap existed therefore reads correctly without being
re-analysed. Then a dry run compared
every stored row with a fresh recompute and found 70 (month, hospital) scopes in
2026-04…2026-08 that disagreed; those scopes were re-analysed through the
canonical pipeline. 282 rows moved `VERY_HIGH → HIGH`, two more refreshed their
interpretation only, no row was added or removed, and the Quality Score did not
change. Stored Diagnostics bands are now 7,889 `NONE` / 1,289 `LOW` / 453
`MODERATE` / 639 `HIGH` / 517 `VERY_HIGH` (10,787 rows, sum == total), a fresh
recompute disagrees with **0** rows, and the reported row (2026-04, hospital 26,
`10.a.1.2`) is stored as `HIGH` with `thin_peer_layers: ["peer"]`,
`level_from_layers: "VERY_HIGH"`, `cap: "HIGH"`.

---

## 5. Evidence and audit trail

| Requirement | Status |
|---|---|
| Cap reason in `evidence` | **Yes** for zero dispersion (`evidence.dispersion`, written by the current scan), thin peer (`evidence.thin_peer_group`, written by the current scan) and the pct clamp (`evidence.pct_change_cap`). |
| Original and effective band traceable | **Yes** — `stored_severity` + `severity` + `severity_cap.policy`; Diagnostics keeps `classification_provenance = {zero_spread_layers, level_from_layers, level, cap}` (131 capped rows). |
| UI distinguishes stored from effective | **Yes** — capped badge in the table and detail, plus the stored z pair (`z_score` / `stored_z_score`). |
| No capped alert silently `NORMAL` | **Yes** — floor is `HIGH`. |
| Unaffected alerts unchanged | **Yes** — 6,564 rows untouched. |

### Finding F5 (low) — provenance omissions

* Diagnostics does not persist the percentage-change clamp: the layer keeps
  `pct_change_score` in memory and `Classification.pct_change_capped`, but
  `classification_provenance` has no `pct_change_layers` key (0 rows). The
  clamped score is stored, the pre-clamp change is not.
* Diagnostics `classification_provenance` gained `thin_peer_layers` when the
  months were rescanned on 2026-10-29 (all 10,787 rows now carry the current
  policy version); the pct clamp is still not persisted there.

### Write-side parity — Quality Alerts (2026-10-29)

The scan and the reader must reach the same band, otherwise a stored row keeps a
band the policy refuses until somebody rescans the month. Measured on the live
store after scanning 2026-01…2026-03 (1,573 rows updated, 0 created, 0
deactivated):

| Population | Rows | Stored ≠ policy |
|---|---|---|
| Live open alerts | 5,043 | **0** |
| Retired open alerts (`active = false`) | 2,113 | 378 |

Live stored bands now equal the policy bands exactly — 1,645 `MODERATE` / 2,009
`HIGH` / 1,389 `VERY_HIGH` — and the KPI did not move (2,658 open issues, 947
Very High), because readers already applied the caps. Retired rows are records of
findings a later scan no longer detects: no screen counts them, and they keep the
band they were written with rather than being rewritten. `scripts/audit_severity_counts.py`
now reconciles the two populations separately, so its drift figure is the live
one.

---

## 6. Reported numbers — full reconciliation

All five figures are correct; they describe **three different scopes and two
different units**. Recalculated from one snapshot:

| Step | Rows | Issues (hospital × canonical formula × month) |
|---|---:|---:|
| All stored alert rows | 7,156 | 3,548 |
| … stored `VERY_HIGH` | **2,881** | 1,886 |
| … reduced by the read-time cap | **592** (460 thin-peer + 132 zero-spread) | — |
| … effective `VERY_HIGH` | **2,289** | 1,603 |
| Open rows only (active hospital + `active` + not closed + enabled month) | 5,043 | **2,658** |
| … stored `VERY_HIGH` | 2,094 | **1,448** |
| … reduced by the cap | 408 (all thin-peer) | — |
| … effective `VERY_HIGH` | **1,686** | **1,217** |

Answers to the three questions:

1. **Why `2,881 − 592 = 2,289` but the "effective" figure is 1,686?**
   Both are right, on different populations. 2,881 / 592 / 2,289 are **all
   stored rows**; 1,686 is the **open** population. The 603-row difference
   (2,289 − 1,686) is rows that are inactive, closed, in a disabled
   hospital-month or belong to an inactive hospital.
2. **Do the 592 and 1,686 use different scopes or calculations?**
   Same calculation (`effective_severity`), different scope: 592 = every stored
   row capped; 408 of those are open, and those 408 are the rows behind 1,686.
   The 184-row remainder sits outside the open scope.
3. **Why did open critical issues fall by 231, not 592?**
   Because issues are folded: 2,094 open Very High **rows** belong to 1,448
   **issues** (1.45 rows per issue), and the 408 capped rows belong to 231
   issues (1.77 rows per issue). Rows and issues are not interchangeable, and
   `1,686` is a row count while `1,448 → 1,217` are issue counts.

The original table also put a row count (1,686) beside issue counts (1,448 …),
which is why the subtraction looked impossible. Both names now exist explicitly
in the API (`very_high_rows` vs `very_high_issues`).

**All 592 capped rows are `VERY_HIGH → HIGH`; 231 is entirely the thin-peer
cap.** The zero-spread cap already applied at write time to every open alert
(816 rows carry `evidence.dispersion`), so it no longer moves the open KPI.

---

## 7. Regression tests

Run on this snapshot's code:

```
tests/test_layered_engine.py tests/test_quality_alert_zero_spread.py
tests/test_thin_peer_z.py tests/test_layered_zero_spread.py
tests/test_comparison_policy.py tests/test_insufficient_history_policy.py
tests/test_severity_consistency.py
→ 156 passed
```

Covered: exact boundaries and values either side; zero dispersion for
spread-based methods; measured spread still reaching `VERY_HIGH` beside a
degenerate layer; 2-peer and 4-peer groups; withholding a pre-policy z at read
time; the insufficient-history rules; cross-module scale parity.

### Finding F4 (low) — coverage gaps

* no explicit **1-peer** or **3-peer** case (2 and 4 are covered);
* no **zero-MAD** or **zero-IQR** case with `std > 0` — the F1 behaviour is
  untested in both directions;
* no **percentage change on a flat window** (`std = 0`) case;
* no unit test for **idempotency** of `effective_severity` (verified only
  against live data here: 0 rows change on re-application).

---

## Findings and recommendations

| ID | Severity | Finding | Recommendation |
|---|---|---|---|
| F1 | High — **fixed** | Zero MAD/IQR comparisons claimed `VERY_HIGH` (270 open issues, 295 Diagnostics rows) | Done: the test uses each method's actual divisor (std / MAD / IQR / trend residual), the divisor is persisted in `evidence.stats`, and legacy rows recompute it from their stored series. 270 issues moved `VERY_HIGH → HIGH`; no threshold changed. |
| F2 | Medium | Diagnostics served stored bands with no read-time cap; 1 row was `VERY_HIGH` on 3 peers | **Fixed both ways**: the read-time cap now applies in the list, level filter, trend, heatmap and report payloads, and `POST /analysis/layered/rescan-stale` previews then rewrites only the months still stored uncapped (the affected months were also rescanned). No threshold change. |
| F3 | Low | The docs say `std = 0` percentage-change rows are caught by the zero-spread cap, but `zero_dispersion()` excludes `pct_change` | Decide whether a +100% on a flat baseline may stay `VERY_HIGH`; correct the doc either way and add the flat-window test. No live row today. |
| F4 | Low | Test gaps (1/3 peers, zero MAD/IQR, flat pct window, idempotency) | Add the four cases; no production change. |
| F5 | Low | Diagnostics provenance omits the pct clamp and (in the store) thin-peer layers | Persist `pct_change_layers` and `thin_peer_layers` on write; rescanning existing months fills them. |
| F6 | Observation | High z on a tight but non-zero spread (up to 108 with ≥4 peers) and history z up to 23 on 3–7 points | Policy question, not a defect: the cap is on the *group size*, not on the z magnitude. Document the limit; any change is a threshold decision. |

## Approval conditions

1. **Sections 1, 2, 4, 5, 6 may be approved as implemented** — the cutoffs,
   cap semantics, read-time band, evidence trail and reported figures all hold.
2. **Section 3 may now be approved**: the test asks whether the divisor the
   method used was zero, so a zero-MAD/IQR comparison can no longer claim the
   top band (F1 fixed).
3. **F2 is closed**: Diagnostics re-applies the caps at read time (like Quality
   Alerts), so both screens return the same band for the same stored row even
   before a re-scan; the 2026-10-29 rescan then restated the stored bands, and a
   fresh recompute finds no stored disagreement.
4. **Close F3–F5** as documentation/test work; they change no band. The two
   write-path regression tests (thin peer in a scan, zero-IQR window in a scan)
   are in place so a future scan cannot store an uncapped band.
5. A rescan has been performed for the affected months; re-running it is
   idempotent (0 further changes).

---

## Reproduction

Every number above comes from read-only SQLAlchemy queries against one session:

```python
from app.database import SessionLocal
from app.models import QualityAlert
from app.engine.quality_alerts import effective_severity, CLOSED_STATUSES
from app.eligibility import exclude_disabled

db = SessionLocal()
rows = db.query(QualityAlert).all()
effective = [effective_severity(r.severity, stats=(r.evidence or {}).get("stats"),
                                method=r.method, peer_count=r.peer_count)
             for r in rows]
```

The open scope is the dashboard's `_open_quality_alert_scope`: active hospital,
`active = true`, status not in `CLOSED_STATUSES`, `exclude_disabled`, then folded
by `(hospital, canonical_identity, month)`. The MAD/IQR check recomputes the
divisor from `evidence["history"]` (alerts) or `history_provenance["values"]`
(Diagnostics) using the engine's own `mad()` / inclusive quartiles.
