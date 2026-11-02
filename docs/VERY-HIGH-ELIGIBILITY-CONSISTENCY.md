# VERY_HIGH eligibility — cross-screen consistency review (read-only)

Status: **wired on the branch `very-high-gate-integration`; `main` is unchanged.**
Sections 1-11 are the read-only review that justified the wiring. Section 12 is
the merge preparation: what was changed on the branch, the two proofs the review
demanded, and what still needs a separate approval before merge.

Nothing was written to the database, no migration was run, no threshold moved
(`zscore_threshold = 2.5`), and the stored-band fingerprint is identical before
and after the audit run (`b011d308…61c`).

Reproduce:

```bash
.venv/Scripts/python.exe scripts/verify_very_high_consistency.py
# full narrative -> outbox/very-high-consistency.log
# per-row evidence -> outbox/very-high-consistency.csv
```

## 1. What is compared, and with which identity

| Source | Row | Identity used |
|---|---|---|
| Quality Alerts | one PERSPECTIVE of a finding | `(hospital, month, canonical formula)` |
| Dashboard | one ISSUE (`_quality_issue_counts`) | same fold, same `effective_severity` |
| Outlier Diagnostics | one analysis pass per `analysis_code` | same canonical formula for a rate row, the data-element code for a count row |

The identity is the **formula + display scale**, not the code: one formula is
registered under several codes (`sys_clinical_rate_cs`, `cs_rate`, …). Matching
by code split the same event in two and understated the overlap:

* raw-code matching finds **375** shared identities;
* canonical matching finds **396** — **21 events** are registered under another
  code on one side;
* Diagnostics never has two rows for one identity (**0** duplicates);
* an alert identity holds 1–5 rows (perspectives, plus equivalent codes), and no
  identity+perspective pair holds two rows (**0**).

Populations (live store, this run):

| | rows | stored VERY_HIGH | VH identities |
|---|---|---|---|
| Quality Alerts | 5,043 | 1,389 | 947 |
| Diagnostics | 10,787 | 517 | 517 |

Row counts across the tables are **not** comparable: an alert row is one
perspective, a diagnostics row is one analysis pass. Only identities are:
396 shared (551 alerts-only, 121 diagnostics-only).

## 2. Which rule judges which layer

`VERY_HIGH` does not mean "the same measurement" on every row. The eligibility
gate asks one question — *does the row's own-history window support the top
band?* — and is routed per layer:

| Layer holding the top band | Rule that judges it | Outcome of this gate |
|---|---|---|
| `historical` / `rate` / `raw` (count analysis) | the shared gate, on the window in that layer's own unit | `eligible` / `ineligible` |
| `peer` | the approved peer rules only (no dispersion; fewer than 4 peers) | `undecided`, band kept |
| `volume` | percentage change of the denominator, no dispersion divisor | `undecided`, band kept |
| `raw` on a **rate** analysis | count vs rate window — a unit mismatch, not evidence about the rate | `undecided`, `unit_compatible=false` |

Routing on the live store:

| Source | Route | eligible | ineligible | undecided |
|---|---|---|---|---|
| Diagnostics (517 rows) | history | 82 | 146 | — |
| | peer | — | — | 163 |
| | volume | — | — | 101 |
| | raw count on rate | — | — | 25 |
| Alerts (1,389 rows) | history | 96 | 163 | — |
| | peer (all non-history perspectives) | — | — | 1,130 |

`not_applicable` is separate from `undecided`, and neither is counted as a pass
or a rejection. In this population no row is `not_applicable` (all 1,906 rows
carry `VERY_HIGH`), and no row's band changed while its eligibility was
`undecided` (**0**).

## 3. Effect of the gate, per screen

| Screen | Unit | Before | After | Moved |
|---|---|---|---|---|
| Quality Alerts + Dashboard | rows | 1,389 | 1,226 | 163 rows → HIGH |
| Quality Alerts + Dashboard | issues | 947 | 801 | 146 issues |
| Diagnostics | rows | 517 | 371 | 146 rows → HIGH |

The Dashboard's own production function `_quality_issue_counts` reports **947**
Very High issues today — identical to the audit's issue fold, which is why the
two screens can only disagree if they receive different inputs (see §5).

Diagnostics moves fewer rows than the alerts screen because most of its
`VERY_HIGH` rows rest on a layer this policy does not govern (peer 163, volume
101, raw-on-rate 25) — those keep their band by design.

## 4. Agreement between the tables

Of the 396 shared identities, **389 (98.2%)** read the same band after the gate:

| Pair | Count |
|---|---|
| `VERY_HIGH` / `VERY_HIGH` | 250 |
| `HIGH` / `HIGH` | 139 |
| `VERY_HIGH` / `HIGH` | 7 |

* **Comparable history events** (same window, same current value, both routed to
  the history layer): **228**, decisions that differ: **0**.
* **Unexplained differences: 0.**
* The only remaining differences are the **7** identities in the next section,
  all caused by a different source layer — not by a different policy.

## 5. The ten identities that previously read two bands

The earlier report grouped by raw code and compared per-layer scores without
applying the approved caps. Recomputed through the shared per-layer bands, the
ten resolve as follows:

| # | Identity | Earlier | Now | Cause |
|---|---|---|---|---|
| 1 | h6 2026-06 `10.i` | HIGH / VERY_HIGH | HIGH / HIGH | resolved: the Diagnostics top band also rested on a peer layer whose stored score is 1.0 from an **all-equal** peer group — the approved no-dispersion cap already refuses it, so it is not a holder |
| 2 | h24 2026-07 `sys_clinical_rate_hysterectomy` | HIGH / VERY_HIGH | HIGH / HIGH | resolved: same pattern on a rate row (peer values all 0); the rate window itself is refused on both sides |
| 3 | h26 2026-08 `10.a.3.3` | HIGH / VERY_HIGH | HIGH / HIGH | resolved: peer layer capped as degenerate; history refused on both sides |
| 4 | h36 2026-06 `9` | HIGH / VERY_HIGH | VERY_HIGH / HIGH | different baseline: the alerts top band comes from a **type** peer comparison with a measured spread and ≥4 peers (existing peer policy allows it); the history row is refused on both sides |
| 5 | h36 2026-07 `13` | HIGH / VERY_HIGH | VERY_HIGH / HIGH | same as #4 |
| 6 | h36 2026-07 `2.i` | HIGH / VERY_HIGH | VERY_HIGH / HIGH | same as #4 |
| 7 | h36 2026-08 `6.d` | HIGH / VERY_HIGH | VERY_HIGH / HIGH | same as #4 |
| 8 | h6 2026-07 `6.d` | VERY_HIGH / HIGH | VERY_HIGH / HIGH | different baseline (ownership peer comparison vs own history) |
| 9 | h21 2026-04 `8.b` | VERY_HIGH / HIGH | VERY_HIGH / HIGH | different baseline (governorate peer comparison vs own history) |
| 10 | h22 2026-07 `2.l` | VERY_HIGH / HIGH | VERY_HIGH / HIGH | different baseline (ownership and governorate peer comparisons vs own history) |

For all seven remaining differences the gate returns the **same answer on the
history layer on both sides** (ineligible in every case, on the same window and
the same value) — the band difference comes from a peer comparison that the
alerts screen reports as its own perspective and Diagnostics does not store as a
row of its own. This is a difference in **baselines**, not in policy, and it is
the reason the gate must not be extended to peer layers: a peer z already
divides by the group's own spread, and the approved peer rules (no dispersion,
fewer than four peers) are the rules that judge it. Asking the history question
of a peer claim would apply a different measurement altogether.

Row-level attribution to the earlier run is not reproducible: that script version
was replaced in place (it is untracked), and its gateability test compared layer
scores before the approved caps. What is verifiable is the table above, produced
by the current script.

## 6. Unit check — does each side grade the same quantity?

| Check | Result |
|---|---|
| alert's `current_value` equals the diagnostics row's own unit value (rate for a rate analysis, else raw) | **396 / 396** shared identities |
| documented peer baseline equals the mean of the stored peer values | **517 / 517** rows with peers |
| rows whose top band rests on a raw **count** layer of a **rate** analysis | **51** (25 of them have no other holder → route `raw_count_on_rate`) |
| alert peer perspectives that store the member peer values | **none** (1,130 rows store the group's stats only — provenance gap, not needed by the peer caps) |

The engine itself is unit-consistent: `analyze_layered_entry` compares
`rate_value if spec.is_rate else raw_value` against `unit_values` built with
`rate_analysis_value` for rate specs, and the stored history window of a rate
row is the rate window. The 51 flagged rows are the only place where a layer
speaks about a different unit than the window, and they are kept `undecided`
rather than refused.

## 7. Evidence completeness

* Required evidence missing: **0 rows** on either side. Every row that is
  `undecided` is undecided because of its layer, not because data was absent.
* Not stored but not needed: the 1,130 peer alert rows carry the peer mean/std
  and peer count, never the member values.

## 8. Invariants verified

| Invariant | Result |
|---|---|
| `gate(x) != gate(gate(x))` | 0 |
| rows pushed below `HIGH` | 0 |
| rows whose base band was below `VERY_HIGH` and moved | 0 |
| undecided rows whose band changed | 0 |
| stored-band fingerprint before / after | `b011d308…61c` / `b011d308…61c` (unchanged) |

## 9. Dashboard: minimum fields for the gate

The Dashboard's Very High card is computed by
`app/api/dashboard.py::_quality_issue_counts`. It already reads the same rows,
the same canonical fold and the same `effective_severity` as Quality Alerts, and
this run confirms its **947** equals the audit's fold. But its query selects:

```
hospital_id, indicator_code, month, formula, unit, severity, method,
peer_count, evidence
```

**`current_value` is missing**, and it is the one input the gate cannot work
without. It is not derivable from `evidence` (evidence stores `numerator` /
`denominator` for rates and no value for counts), and recomputing it would be a
second computation that can drift from the stored one.

Simulated with the live data: wired **without** `current_value` the Dashboard
would report **947** Very High issues while Quality Alerts reports **801** —
every row would be `undecided` and keep its band.

Minimum safe change (not made):

1. add `QualityAlert.current_value` to the existing `with_entities(...)` of the
   Very High query — same query, same row, no join, no extra round trip;
2. thread it into the band call: `effective_severity(..., current=...)`;
3. keep `applicable = false` / `eligible = null` flowing through as "band
   unchanged", never as a pass.

Same indicator, hospital, month, perspective and unit by construction: the value
is a column of the same row that is being banded.

## 10. What remains before wiring (separate approval)

1. **Quality Alerts / Dashboard seam** — pass `current` into
   `effective_severity` from a full row (alerts, explain) and from the added
   Dashboard column, and apply `cap_very_high_eligibility` only on the history
   route.
2. **Diagnostics seam** — route per layer in `row_level_assessment` using
   `row_layer_bands` (peer / volume / raw-on-rate stay `undecided`).
3. **Threshold provenance gap** — a `LayeredOutlierResult` does not persist the z
   threshold it was scored with, so a reader must use the configured value
   (`load_analysis_config`, 2.5 today). Recording it in
   `classification_provenance` would make the read-time gate exact; until then
   the audit reports which threshold it used.
4. **Explain/Why surfaces** must render `undecided` as "the comparison cannot be
   graded", not as "normal".

Not done and not needed for this task: no migration, no stored-row update, no
threshold change (`zscore_threshold = 2.5` untouched), no manual exceptions, no
server start.

## 11. Tests

| Command | Result |
|---|---|
| `pytest tests/test_very_high_consistency_report.py` | 28 passed |
| `pytest tests/test_layered_*.py tests/test_very_high_eligibility.py tests/test_quality_alert_*.py tests/test_quality_alerts_api.py tests/test_quality_alerts_canonical.py tests/test_severity_consistency.py tests/test_explain.py` | 293 passed |
| `pytest tests/test_dashboard_*.py tests/test_quality_alerts_ui.py tests/test_layered_ui.py` | 111 passed |
| `ruff check` on `layered.py`, the audit script and the new tests | clean |

The new tests cover: equivalent codes folding to one identity, perspectives
sharing one identity, fallback identity for a missing spec, history/peer/volume/
raw-on-rate routing, rate-versus-count unit mismatch, missing `current_value` and
missing window staying `undecided`, `not_applicable` vs `eligible = null`,
idempotency, the "never below HIGH" rule, no mutation of a stored row, cross-
screen agreement on identical inputs, and production parity
(`row_layer_bands` max == `row_level_assessment`, `effective_severity` still
caps a zero-spread peer group).

## 12. Merge preparation — the four changes, on the branch

Branch: `very-high-gate-integration` (branched from `main`; `main` not touched).
The four items listed in §10 are implemented and verified; production data is
still read-only.

### 12.1 What changed

| # | Change | Where |
|---|---|---|
| 1 | Routing: `top_band_route`, `row_very_high_eligibility`, `gate_threshold`, `row_gate_threshold`, `ROUTE_*` / `DECISION_*`; `row_level_assessment` composes the caps **and** the gate, per layer | `app/engine/anomaly/layered.py` |
| 1 | `effective_severity` / `severity_cap` gained `current`, `perspective`, `threshold`; new `top_band_gate`, `eligibility_assessment`, `alert_route`, `stored_threshold` | `app/engine/quality_alerts.py` |
| 1 | Quality Alerts passes the row's own inputs (window, `current_value`, perspective, stored threshold) and publishes `top_band_eligibility` on every row and on the issue summary | `app/api/quality_alerts.py` |
| 1 | **Dashboard**: the Very High query now selects `QualityAlert.current_value` and `QualityAlert.perspective` and threads both into the same band call | `app/api/dashboard.py` |
| 1 | Diagnostics reads the gate through `row_level_assessment` / `effective_row_level` (list, filters, trend, badges — one function, so they cannot disagree) | `app/api/analysis.py` |
| 2 | The rescan write-back deliberately still targets **only the two approved caps**: a gate-only refusal is presented, never re-bandered on disk | `app/api/analysis.py#_stale_layered_rows` |
| 3 | `classification_provenance` now records `zscore_threshold` at scan time, and `_save_layered_results` takes it from the analyse step | `app/engine/pipeline.py` |
| 4 | Explain publishes `top_band_eligibility` (per perspective **and** for the diagnostic row), names the gate in the capped-alert explanation, and renders the three states in words — `undecided` reads as *not judged*, never as *normal* | `app/engine/audit/explain.py`, `static/js/explain.js`, `static/js/i18n.js` |

Routing is unchanged from §3 and is the rule the code now enforces:

| Top band held by | Rule | State |
|---|---|---|
| own history (raw / rate / historical) | the window's dispersion-aware band | `eligible` / `ineligible` / `undecided` |
| peer | approved peer policies (no spread, <4 peers) | `undecided` — band stands |
| volume | denominator % change | `undecided` — band stands |
| raw count on a rate analysis | unit mismatch | `undecided`, `unit_compatible=false` |
| nothing | — | `undecided` |

`ineligible` moves the band to HIGH and never lower; `undecided` and
`applicable=false` leave it exactly as stored.

### 12.2 Proof 1 — the Dashboard uses the same inputs

* its Very High query reads `current_value` and `perspective` from the **same
  row** it bands (`with_entities`, no join, no second query, no recomputation);
* the audit calls the production functions themselves and compares:
  `alerts: production != routed decision: 0 of 1389`, `diagnostics: 0 of 517`;
* `Dashboard _quality_issue_counts` = **801** Very High issues and the audit's
  identity fold = **801** — equal (`=== 8b` in the log);
* for contrast, the audit still prints what the Dashboard reported *before* the
  column existed: **947**, i.e. 146 rows the gate would refuse but could not
  judge — which is why the column is required.

### 12.3 Proof 2 — a band change does not change the issue or its history

* **No write path touches stored bands**: `rescan-stale` excludes gate-only
  refusals (test `test_the_rescan_write_back_still_targets_only_the_approved_caps`),
  and reading every row through **`_alert_dict`, `row_level_assessment`,
  `row_very_high_eligibility` and `_stale_layered_rows`** leaves the severity,
  the stored level and the evidence byte-identical
  (`test_reading_a_row_changes_nothing`);
* the audit re-reads every stored band after its own run: fingerprint
  `b011d3087075a8816a609b12bb56823af961461c` **unchanged**;
* issue identity and counts are computed from the same stored rows
  (`hospital, canonical formula, month`) — the gate only changes which band a row
  is *presented* under, never the issue it belongs to, its status, its assignee
  or its `detected_at`;
* `undecided` rows: **0** changed band; rows pushed below HIGH: **0**; rows whose
  base band was below VERY_HIGH and moved: **0**; `gate(x) != gate(gate(x))`: **0**.

### 12.4 Numbers after the wiring (live data, read-only)

| | alerts | diagnostics |
|---|---|---|
| stored `VERY_HIGH` | 1,389 | 517 |
| after the gate | 1,226 (163 → HIGH) | 371 (146 → HIGH) |
| issues | 947 → **801** | — |
| states | 96 eligible / 163 ineligible / 1,130 undecided | 82 / 146 / 289 |
| shared identities | 396 (Dashboard 801 == audit 801) | |
| band agreement | 389/396 (98.2%); pairs 250 VH/VH, 139 HIGH/HIGH, **7 VH/HIGH** | |
| comparable history events (same window, same value) | 228 with **0** differing decisions | |
| units | alert value == row's unit value 396/396; 51 raw-on-rate rows `undecided` | |

The 7 remaining identities are the peer-versus-history difference documented in
§5: the alert's top band comes from a stratified peer perspective that
Diagnostics does not score as its own row, while the **history layer decides
identically on both sides** (`same window and value: True`, both `ineligible`).
They are not a policy disagreement and must not be forced together.

### 12.5 Still needs a separate approval (not done)

1. **Writing a lower band back to disk.** The gate is read-time only; a re-scan
   is still what restates a stored band, and the rescan currently excludes
   gate-only refusals on purpose. Re-banding 146 diagnostics rows / 163 alert
   rows permanently is a data change and should be its own reviewed step.
2. **Back-filling `zscore_threshold` on existing rows.** Rows written before
   §12.1/#3 fall back to the configured value (2.5 today, which equals the
   default). No back-fill is proposed; a re-scan of a month records it.
3. **Working-tree hygiene**: the branch carries the pre-existing modified files
   of this checkout plus the changes above; nothing is committed.

### 12.6 Tests (this run)

| Command | Result |
|---|---|
| `pytest tests/test_very_high_gate_wiring.py` | **21 passed** (new) |
| `pytest tests/test_very_high_consistency_report.py` | 28 passed |
| `pytest tests/test_layered_api.py` | 27 passed (one test updated, one added) |
| `pytest tests/test_quality_alerts_api.py tests/test_quality_alerts_ui.py tests/test_quality_alerts_canonical.py tests/test_quality_alert_very_high_band.py tests/test_severity_consistency.py tests/test_explain.py` | **118 passed** |
| `pytest tests/test_dashboard_analysis_ux.py tests/test_dashboard_ghost_rows.py tests/test_layered_zero_spread.py tests/test_thin_peer_z.py tests/test_layered_schema.py tests/test_layered_pipeline.py tests/test_pipeline.py` | **118 passed** |
| `pytest tests/test_layered_zero_spread.py tests/test_thin_peer_z.py tests/test_very_high_eligibility.py tests/test_very_high_consistency_report.py tests/test_quality_alert_very_high_band.py` | 83 passed |
| `ruff check` on every modified file | clean (the one remaining `B905` in `quality_alerts.py` is pre-existing) |

The new tests cover: perspective routing, peer/volume/raw-on-rate staying
undecided, the four states reported apart, missing `current_value` and missing
window staying undecided and named, per-layer composition (a refused history
layer does not lower a peer layer's band), never below HIGH, idempotency, the
stored threshold winning over the default, the threshold being recorded by
`_save_layered_results`, Dashboard/Quality Alerts counting the same band, the
payload stating the decision, no stored row changing on read, and the rescan
write-back excluding gate-only refusals.

The server was **not** started: the UI wording change (item 4) is verified by
the payload tests and by inspection of `explain.js`, not by rendering it.

## 13. Threshold provenance (what the gate is asked with)

Every reader judges a row with **the threshold that row recorded**, never with
the value currently saved in System Control:

| Source | Field |
| --- | --- |
| Quality Alerts, Dashboard, Explain | `evidence["z_threshold"]` (`engine.stored_threshold`) |
| Outlier Diagnostics, Explain diagnostic block | `classification_provenance["zscore_threshold"]` (`layered.row_gate_threshold`) |

When neither exists — every row written before the field was introduced — the
resolution falls back to the **saved default `2.5`** (`PEER_Z_THRESHOLD_DEFAULT`),
not to the configured setting. That is deliberate: a row graded at 2.5 must not
be re-graded because an operator changed `thresholds.zscore_threshold`
afterwards. The live store currently holds 1,389 stored-`VERY_HIGH` alerts with
`z_threshold = 2.5` and 517 stored-`VERY_HIGH` diagnostics rows with **no**
recorded threshold, so today both paths resolve to the same value. No backfill
is performed; a re-analysis of the month writes the provenance for new rows.

The audit's routing and threshold resolution are the production functions
(`quality_alerts.alert_route`, `layered.row_gate_threshold`); the report's own
logic is limited to aggregation and presentation.
