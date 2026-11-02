# D13 — Integrity Reconciliation (D12 findings)

Status: read-only findings + the changes made in D13. No stored row, threshold,
band, peer policy, formula or scoring weight was changed.

## D13-01 — Alerts vs Diagnostics history divergence

### What the two engines actually do

* An **alert row** scores ONE labelled perspective (`history`, `all`, `type`,
  `ownership`, `facility_type`, `governorate`) and carries that perspective's
  band.
* A **layered row** (Diagnostics) computes five layer scores (`raw`, `rate`,
  `historical`, `volume`, `peer`) and reports the highest measured band.
* Both score through `layered.score_window_detail`, and both judge the top band
  through `layered.very_high_eligibility` — the same functions, the same
  `zscore_threshold` (2.5) and the same cutoffs.

### The 37 reported "top-band divergences" are a comparison artifact

For alert 587 (and 993, 627) the two sides store **identical** evidence:

| Field | Alert | Layered row |
|---|---|---|
| window | `[3,3,1,3,6,2,4]` | `[3,3,1,3,6,2,4]` |
| current | 10.0 | 10.0 |
| score | 1.0 | 1.0 (`historical_outlier_score`) |
| z | 4.3576 | 4.3576 |
| threshold | 2.5 | 2.5 |

The alert's `history` claim is refused by the dispersion gate
(`DISPERSION_BAND_BELOW_VERY_HIGH`) and becomes HIGH. The layered row also has
a **peer layer at VERY_HIGH** (peer score 1.0), so its row-level band stays
VERY_HIGH with `route=peer`, `decision=undecided`. Both statements are true:

* "this hospital's own history does not support the top band" → HIGH, and
* "this hospital is at the top band compared with its peers" → VERY_HIGH.

Diagnostics reports the row maximum; the alert screen reports one perspective.
Alert 413 shows the check from the other side: its layered row has only history
holders, the gate refuses it, and the row is HIGH — exactly the alert's band.
Alert 6984 behaves the same way. 5 of the 6 audited cases are therefore
consistent, not divergent.

### The 6 589-type cases are legacy rows, already fixed for new scans

Alert 6 589: window `[45,38,15]`, current 29, method `pct_change`.

* Alert stored score **0.9333** (the raw percentage change against the previous
  point, 15) and stored VERY_HIGH.
* Layered row score **0.0467**: the same change clamped by
  `cap_pct_change` to what the window's z supports
  (`PCT_CHANGE_CAP_POLICY`, z = −0.2336).
* Its evidence has **no** `pct_change_cap` block, i.e. it was written before
  that policy; the current scan path calls `layered.score_window_detail` and
  produces 0.0467 (see `tests/test_d13_integrity.py`).

Re-grading that stored band at read time would change a stored analytical
result, which D13 explicitly forbids. The correct treatment is:

1. new scans are already aligned (shared scoring function),
2. legacy rows keep their stored band and their stored evidence,
3. a reconciliation report can list them (read-only) for an explicit,
   separately approved re-scan.

### Decision

No routing, gate, cap, threshold or scoring change was needed. The regression
tests pin the invariants the audit relied on:

* identical window + current + method ⇒ identical score and band,
* history top band refused on both screens,
* a peer layer holding the top band is not judged by the history window,
* the row maximum is not a second calculation,
* caps run before the gate and never raise a band.

## D13-02 — Quality-score outlier penalty (measured, no change)

`layered_outlier_penalty` counts rows whose band is `HIGH` or `VERY_HIGH`.
Every approved rule only ever lowers a band from `VERY_HIGH` to `HIGH` (the
gate and both caps floor at HIGH), and both bands are flagged. The penalty
numerator is therefore **invariant** under the read-time policy.

Read-only measurement over the live store:

| Metric | Value |
|---|---|
| QualityScore rows | 176 |
| Rows with layered input rows | 137 |
| Hospital-months whose flagged count changes | **0** |
| Outlier multiplier | 2.0 |
| Penalty delta (points) | 0.0 |
| Raised / lowered penalties | 0 / 0 |

Decision: **no code change**. Switching the penalty to the effective band would
alter no stored number and would add a second band concept to a component whose
input is intentionally the stored detection result. Reprojected if a future
policy ever lowers HIGH, this measurement must be repeated.

## D13-03 — i18n regression

`'Edit': 'تعديل'` was a deleted line inside the uncommitted `i18n.js` diff (the
hospital-month audit keys were inserted over it). It is restored in place; no
other translation was touched. The existing fragment-key test and the focused
D13 assertion cover it.

## D13-04 — SQLite migration compatibility

`a1c2e3f4b5d6_repair_quality_score_revision_action.py` used
`op.alter_column(..., nullable=...)` three times. SQLite has no
`ALTER COLUMN`, so `upgrade head` raised `sqlite3.OperationalError: near
"ALTER": syntax error` on every SQLite test database.

The three repairs now run inside one `op.batch_alter_table` block: PostgreSQL
issues the same `ALTER TABLE` statements as before, and SQLite recreates the
table and copies its rows (the repository's existing convention for SQLite,
e.g. `e5f6a7b8c9d0`). The NOT NULL relaxations still happen only when no row
would violate them, and the legacy `reason` column is still preserved.

A partial database whose foreign-key parent tables do not exist cannot be
reflected for a batch rebuild; the repair is skipped there (the file already
guards absent tables/columns the same way), and the migration still reaches
head. Real databases always contain those parents.

## D12-04 — Provenance recommendation (not implemented)

No schema migration in D13. For future rows:

| Field | Capture stage | Purpose |
|---|---|---|
| `comparison_policy` (version, window, min observations, peer group, min peers) | scan/pipeline, before scoring | reproducibility across policy edits |
| `series` / `values` (the exact window used) | scan/pipeline, with the score | re-derive or explain without re-reading today's data |
| `method`, `z`, `threshold`, score before any cap | scan/pipeline | distinguish a policy refusal from a measurement change |
| `pct_change_cap` / cap blocks | when the cap fires (already done) | explain a clamped band |
| `canonical` identity (already stored) | scan/pipeline | join alerts to Diagnostics rows |

Legacy rows: keep them as-is and mark them by absence — `null` provenance means
"unknown, not verified", never "verified and equal". Readers should label such
rows as legacy instead of treating a missing field as agreement. The D12 audit's
4 644 series-less alerts and 1 826 policy-less alerts are exactly this case.
