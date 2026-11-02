# D12 — End-to-End System Integrity Audit

**System:** Health AI — SRMNH Data Quality System
**Commit audited:** `very-high-gate-integration` @ `4b82b19388f0b8568ca8c33c62a9b5f7aa60daac`
**Mode:** STRICT READ-ONLY. No source, test, config, schema or data change was made.
**Date:** 2026-11-02

---

## A. Executive summary

The system has **one production Outlier Engine and one set of shared policy functions**, and every
screen that presents an outlier band routes through them at read time (`effective_row_level`,
`effective_severity`). The single-source policy — median/MAD, quartiles, zero-spread cap, thin-peer
cap, `MIN_PEERS_FOR_TOP_BAND = 4`, `very_high_eligibility`, `row_level_assessment`,
`gate_threshold`, `row_layer_bands`, and the comparison window/peer policy in
`app/engine/comparison_policy.py` — is imported, not re-implemented, by Alerts, Diagnostics,
Explanations, Root Cause, Benchmark and the Dashboard.

Two confirmed integrity defects remain, both in the **top band on the history perspective**:

1. **D12-01 — Perspective routing disagreement.** 37 same-key (hospital, indicator, month) pairs
   report `HIGH` in Quality Alerts and `VERY_HIGH` in Diagnostics, because the alert row is a
   `history` perspective whose gate refuses (`DISPERSION_BAND_BELOW_VERY_HIGH`) while the layered
   row is routed to `peer` and stays `undecided`/`PEER_POLICY`, keeping `VERY_HIGH`.
2. **D12-02 — Score duplication on identical evidence.** 1 173 history rows carry an *identical*
   stored window; among the differing ones, 268 produce a different alert-vs-layered score and 424
   match `level_for_score(layered_score)`, i.e. the two engines scored the same window differently.

Caps are applied consistently and monotonically: **790 alerts and 146 layered rows were re-banded,
and not one band was raised** (`raised = 0` in both populations), so the caps can only lower
severity. Dashboard KPI parity is exact: `_quality_issue_counts` = `{total: 2658, very_high: 801}`,
identical to the alerts-side fold, with `very_high <= total` holding by construction.

The peer perspective agrees **486/486** — full agreement. Divergence is confined to the history
perspective (749 agree / 891 differ) and is explained at runtime by the Diagnostics popup's
`cross_check`, so it is visible, not silent.

**Suite:** 1 168 passed, **5 failed**, 2 skipped, 1 635.24 s, `exit=1`, all on isolated SQLite
(`tests/conftest.py` redirects `SessionLocal`, cache and model dirs). Four failures are SQLite
`ALTER COLUMN` unsupported in `a1c2e3f4b5d6_repair_quality_score_revision_action.py`; one is a
missing `'Edit'` i18n key introduced by the **uncommitted** D11 working-tree edit.

**Verdict: READY WITH LIMITATIONS** (no P0; two bounded P1s; full register in section E).

---

## B. Architecture map (single source of truth)

```
Excel upload ─► app/engine/upload.py / file_ops.py ─► IndicatorValue (raw only, no band)
                                                         │
               app/engine/comparison_policy.py  ◄────────┘
               (window = min(alerts_window, trend.window)=12,
                min_obs=3, min_peers=2, group=all_active_reporting)
                         │
        ┌────────────────┴──────────────────┐
        ▼                                   ▼
app/engine/anomaly/layered.py        app/engine/quality_alerts.py
 median, mad, quartiles,             scan → stored severity + evidence
 cap_zero_spread, cap_thin_peer,     effective_severity(), severity_cap(),
 MIN_PEERS_FOR_TOP_BAND=4,           eligibility_assessment(), effective_z_score(),
 THIN_PEER_LEVEL_CAP=HIGH,           top_band_gate(), alert_route()
 very_high_eligibility(),
 row_level_assessment(),
 effective_row_level(),
 gate_threshold(), row_layer_bands()
        │                                   │
        ▼                                   ▼
LayeredOutlierResult (10 787)        QualityAlert (7 156)
        │                                   │
 ┌──────┼───────────────┬───────────┬───────┼──────────────┐
 ▼      ▼               ▼           ▼       ▼              ▼
Diagnostics  Explain  RootCause  Benchmark  Alerts API   Dashboard KPI
analysis.py  audit/   root_      audit/     quality_     _quality_issue_
             explain  cause.py   benchmark  alerts.py    counts()
             .py
        │
        ▼
Reports (DataElementOutlierOut.outlier_level = effective_row_level)
```

Every arrow into a band display resolves through the shared functions. The only band consumers that
do **not** are listed in section C as DUPLICATED / ALTERNATIVE and in the register.

### Constants verified in code

| Policy | Location | Value |
|---|---|---|
| z threshold | `app/engine/severity.py` | `thresholds.zscore_threshold`, clamped to ≥ 2.5 |
| Band cutoffs | `app/engine/severity.py` | 0.25 / 0.50 / 0.75 / 0.90 |
| Top-band peer floor | `anomaly/layered.py` | `MIN_PEERS_FOR_TOP_BAND = 4` |
| Thin-peer cap | `anomaly/layered.py` | `THIN_PEER_LEVEL_CAP = HIGH` |
| History window | `comparison_policy.py` | `min(alerts_history_window, trend.window)`, default 12 |
| Min observations | `comparison_policy.py` | 3 (floor 2, per-indicator floor wins) |
| Min peers | `comparison_policy.py` | 2, group `all_active_reporting` |
| Policy version | `comparison_policy.py` | `2026-10-24.1` |

---

## C. Cross-screen consistency matrix

| Screen / component | File | Classification | Evidence |
|---|---|---|---|
| Excel ingestion | `engine/upload.py`, `file_ops.py` | SHARED ENGINE (n/a for bands) | writes raw `IndicatorValue`; no band computed at import |
| Derived indicators | `engine/indicator_calc.py`, `IndicatorDefinition` | SHARED ENGINE | one fixed-grammar evaluator for all derived metrics; 0/0 → `zero_denominator`, missing ≠ 0 |
| Validation rules | `engine/quality/rules.py` | ALTERNATIVE POLICY (different domain) | CRITICAL/HIGH/MEDIUM/LOW rule severity; consistently read by `api/alerts.py`, `api/analysis.py`, `api/rules.py` |
| Layered engine | `engine/anomaly/layered.py` | SHARED ENGINE | canonical caps, gate, `row_*` |
| Alert scan | `engine/quality_alerts.py` | SHARED ENGINE + ALTERNATIVE POLICY (perspective routing) | imports caps/gate; history vs stratified perspectives deliberate (see D12-01) |
| Quality Alerts API | `api/quality_alerts.py` | SHARED RESULT | `_alert_dict` publishes `severity`, `effective_severity`, `stored_severity`, `severity_cap`, `top_band_eligibility`, `stored_z_score` |
| Alerts frontend | `static/js/quality-alerts.js` | SHARED RESULT | `a.effective_severity \|\| a.severity` |
| Dashboard KPI cards | `api/dashboard.py::_quality_issue_counts` | SHARED RESULT | exact parity 2 658 / 801 |
| Dashboard score anomalies | `api/dashboard.py` (~982) | ALTERNATIVE POLICY | `anomaly_zscore_threshold` used only for QualityScore component anomalies |
| Diagnostics tab | `api/analysis.py` | SHARED ENGINE | filters/sorts on `effective_row_level`, `row_level_assessment` |
| Explain popup | `engine/audit/explain.py` | SHARED ENGINE | recomputes caps/gate from stored evidence; `cross_check`; `displayed_outlier_level` |
| Root cause | `engine/root_cause.py` | SHARED ENGINE | imports policy; withholds z when `peer_z_measurable` is false |
| Benchmark | `engine/audit/benchmark.py` | SHARED ENGINE | imports policy |
| Regional smart | `engine/smart/regional.py` | ALTERNATIVE POLICY | own \|z\|≥2 thresholds, `warning`/`critical` labels |
| Reports | `api/reports.py` | SHARED RESULT | `DataElementOutlierOut.outlier_level = effective_row_level`; `v.severity` (lines 753/915) is rule severity, not alert severity |
| Quality score | `engine/quality/scoring.py` | DUPLICATED CALCULATION (stale input) | `layered_outlier_penalty` reads **stored** band via `_layered_attr` → D12-05 |
| Full export | `engine/export.py::build_full_export` | NOT APPLICABLE / INFO | exports master data, indicator values, smart analysis — **no severity field at all** |
| Legacy outliers UI | `static/js/outliers.js` | ALTERNATIVE POLICY | \|z\|≥3 `critical`, ≥2 `high` |
| Migration/tests | `tests/conftest.py` | SHARED ENGINE (isolation) | SQLite file DB, redirected `SessionLocal`, cache, XGB, uploads |

---

## D. Data integrity evidence (all read-only)

All recomputations ran inside `SET TRANSACTION READ ONLY` sessions against `health_ai`
(PostgreSQL 17.11, 44 tables).

### Alert population

| Metric | Stored | Effective (read-time) |
|---|---|---|
| MODERATE | 2 745 | 2 745 |
| HIGH | 2 235 | 3 025 |
| VERY_HIGH | 2 176 | 1 386 |
| **Changed** | — | **790** |
| **Raised** | — | **0** |

Caps responsible: `dispersion 326`, `thin_peer 52`, `gate 412` (sums to 790).

### Layered population (10 787)

| Band | Stored | Effective |
|---|---|---|
| NONE | 7 889 | 7 889 |
| LOW | 1 289 | 1 289 |
| MODERATE | 453 | 453 |
| HIGH | 639 | 785 |
| VERY_HIGH | 517 | 371 |
| **Changed** | — | **146**, raised **0** |

### Agreement analysis (same key)

- Same-key alert↔layered pairs: **6 069** — agree 2 252, differ 3 817.
- Per layer (`row_layer_bands`, not row-vs-row max): historical 749 agree / 891 differ;
  **peer 486 agree / 0 differ**.
- Top-band divergences: **37**, all alert=`history` gate-refused vs layered `peer`/undecided.
- Identical stored window across both engines: **1 173** history rows; among differing ones
  **268** have different scores and **424** match `level_for_score(layered_score)`.
  Examples: alert 6 589 score 0.933→HIGH vs layered 0.047→NONE; alerts 6 984 and 413 score
  1.0/0.95 → `VERY_HIGH` but effective `HIGH`.

### Provenance completeness

| Check | Result |
|---|---|
| Alerts without stored series | **4 644 / 7 156** (D12-04) |
| Alerts without `z_threshold` | 0 |
| Alerts without `comparison_policy` | **1 826** |
| Stored threshold ≠ 2.5 | 0 |
| Method differs alert vs layered (same key) | **3 758 / 6 069** |

### KPI parity

`_quality_issue_counts` = `{total: 2658, very_high: 801}`; alerts-side fold identical
(issues 2 658, any-VH 801; VH-only 354). `very_high <= total` holds by construction because both
cards read the same fold.

### Write-freedom fingerprints

| Fingerprint | Opening baseline | After audit |
|---|---|---|
| `quality_alerts` rows | 7 156 | 7 156 |
| max(id) / sum(id) | 7 156 / 25 607 746 | 7 156 / 25 607 746 |
| stored severity fold | M2745 / H2235 / VH2176 | M2745 / H2235 / VH2176 |
| all statuses | `New` | `New` (7 156) |
| `layered_outlier_results` | 10 787 | 10 787, stored fold unchanged |
| `hospitals` | 39 | 39 |
| Git branch / HEAD / stashes / porcelain | `very-high-gate-integration` / `4b82b19` / 2 / 133 | identical |

No migration, backfill, recalculation, regeneration or re-scan was executed. Working tree is
unchanged apart from the pre-existing D11 entries plus this new untracked `qa-d12/` report.

---

## E. Defect register

Fields: **ID · Severity · Classification · Component · Evidence · Expected · Actual · Impact ·
Reproducible · Confidence · Design-vs-defect · Screens affected · Proposed remediation ·
Verification required.**

### D12-01 — Alert and Diagnostics disagree on the top band for the same month

- **Severity:** P1 · **Classification:** ALTERNATIVE POLICY (routing) manifesting as a defect
- **Component:** `engine/quality_alerts.py::top_band_gate` / `alert_route` vs
  `engine/anomaly/layered.py::very_high_eligibility`
- **Evidence:** 37 same-key pairs; e.g. alert 587 vs layered row, alert 993, alert 627. Same window
  `[3,3,1,3,6,2,4]`, same current 10.0, same threshold 2.5.
- **Expected:** when both engines answer the same question, the band is identical.
- **Actual:** alert `history` gate returns `DISPERSION_BAND_BELOW_VERY_HIGH` → HIGH; layered row is
  routed to `peer` → `undecided`/`PEER_POLICY` → keeps VERY_HIGH.
- **Impact:** same hospital/indicator/month shows HIGH on Quality Alerts and VERY_HIGH on
  Diagnostics; a user acting on either screen alone can triage the wrong case.
- **Reproducible:** yes, read-only recomputation of both functions on stored rows.
- **Confidence:** confirmed.
- **Design vs defect:** partial design (perspectives differ by intent) that produces a genuine
  comparability defect in the shared top band.
- **Screens:** Quality Alerts, Diagnostics, Explain popup (`cross_check` explains it), Reports.
- **Proposed remediation (not applied):** on the history perspective, route gate-refused rows to
  the canonical peer layer, or publish the layered band alongside and label the alert band as
  perspective-specific in the API contract.
- **Verification required:** re-run the 6 069-pair comparison; target 0 top-band divergences with
  unchanged `raised = 0` guarantee.

### D12-02 — Same stored window, two different outlier scores

- **Severity:** P1 · **Classification:** DUPLICATED CALCULATION
- **Component:** alert scoring vs `anomaly/layered.py` scoring on `history`
- **Evidence:** 1 173 history rows share an identical stored window; 268 yield different scores;
  424 match `level_for_score(layered_score)`; alert 6 589 0.933→HIGH vs layered 0.047→NONE;
  alerts 6 984 / 413 score 1.0 / 0.95 → VERY_HIGH but effective HIGH.
- **Expected:** identical inputs → identical score and band.
- **Actual:** the alert score is computed from a different series/statistic than the layered row
  despite the stored window being byte-identical.
- **Impact:** 424 rows carry a band that the stored evidence does not support; D12-01's 37
  top-band cases are a subset of this mechanism.
- **Reproducible:** yes (read-only recompute of `level_for_score` on stored layered score).
- **Confidence:** confirmed.
- **Design vs defect:** defect.
- **Screens:** Quality Alerts, Diagnostics, Dashboard KPI, Reports.
- **Proposed remediation (not applied):** derive the alert band from the stored layered score for
  the same key, or persist the exact series/statistic used and assert equality at scan time.
- **Verification required:** 0 score mismatches on identical-window rows; re-check KPI parity
  (2 658 / 801) afterwards.

### D12-03 — QualityScore penalty uses the pre-cap band

- **Severity:** P2 · **Classification:** DUPLICATED CALCULATION (stale input)
- **Component:** `engine/quality/scoring.py::layered_outlier_penalty` via `_layered_attr`
- **Evidence:** reads `outlier_level` straight from `layered_outlier_results`; 146 layered rows
  (and 790 alerts) have a different effective band.
- **Expected:** score penalty reflects the operational band the user sees.
- **Actual:** penalty is computed from the stored band, so capped rows are over-penalised.
- **Impact:** `quality_scores` (176 rows) can differ from the band shown on Diagnostics/Alerts.
- **Reproducible:** yes, code inspection + distribution counts.
- **Confidence:** confirmed (code), magnitude not quantified.
- **Design vs defect:** defect (inconsistent input to a published KPI).
- **Screens:** Quality Score cards, dashboard score panels, reports using scores.
- **Proposed remediation (not applied):** apply `effective_row_level` inside the penalty, or store a
  second `effective_level` column written at scan time.
- **Verification required:** recompute affected scores on a DB copy and diff against current values.

### D12-04 — Alert provenance gaps prevent re-derivation

- **Severity:** P2 · **Classification:** defect (observability)
- **Component:** `QualityAlert.evidence`
- **Evidence:** 4 644 / 7 156 alerts have no stored series; 1 826 have no `comparison_policy`;
  3 758 / 6 069 differ in `method` from the layered row. Stored threshold is never missing
  (0 gaps, 0 mismatches vs 2.5).
- **Expected:** every alert can be re-explained from stored evidence alone.
- **Actual:** 65 % of alerts cannot be recomputed; Explain must fall back.
- **Impact:** auditability and incident replay are limited; D12-02 cannot be fully closed for
  these rows.
- **Reproducible:** yes (column null counts).
- **Confidence:** confirmed.
- **Design vs defect:** defect.
- **Screens:** Explain popup, Reports, any audit export.
- **Proposed remediation (not applied):** persist window, statistic and policy version at write
  time for new scans; treat historical rows as read-only.
- **Verification required:** provenance coverage = 100 % on a fresh scan in an isolated copy.

### D12-05 — Export contains no severity/outlier band

- **Severity:** INFO · **Classification:** NOT APPLICABLE
- **Component:** `engine/export.py::build_full_export`
- **Evidence:** output sections are master data, indicator values and smart analysis only; no
  severity or band field exists.
- **Impact:** none for consistency (nothing to disagree); downstream consumers cannot reconcile
  bands from an export.
- **Reproducible:** yes (code inspection).
- **Confidence:** confirmed. **Design vs defect:** design choice.
- **Screens:** Export.
- **Proposed remediation (not applied):** none required; document the omission or add a band
  section derived from the effective functions if exports are used for audit.
- **Verification required:** n/a (decision item).

### D12-06 — Output surfaces with their own thresholds

- **Severity:** P3 · **Classification:** ALTERNATIVE POLICY
- **Components:** `static/js/outliers.js` (\|z\|≥3 critical / ≥2 high),
  `engine/smart/regional.py` (\|z\|≥2 warning/critical),
  `api/dashboard.py` `anomaly_zscore_threshold` (score anomalies only),
  `engine/quality/rules.py` (CRITICAL/HIGH/MEDIUM/LOW rule severity).
- **Evidence:** each is scoped to a different question and labelled differently; none of them
  presents itself as the SRMNH outlier band.
- **Impact:** user confusion risk only where labels are visually similar.
- **Reproducible:** yes (code inspection).
- **Confidence:** confirmed. **Design vs defect:** design (documented purpose per surface).
- **Screens:** Legacy outliers view, Regional smart analysis, Score anomalies, Rules/Alerts tabs.
- **Proposed remediation (not applied):** none; keep the labels distinct and documented.
- **Verification required:** n/a.

### D12-07 — Missing `'Edit'` i18n key (uncommitted working-tree regression)

- **Severity:** P3 · **Classification:** defect (UI text), unrelated to the outlier engine
- **Component:** `static/js/i18n.js` vs `static/tabs/indicators.html:58`
- **Evidence:** fragment uses `data-i18n="Edit"`; `'Edit': 'تعديل'` is a **deleted line** in the
  uncommitted diff; `tests/test_indicators_tab.py::test_fragment_data_i18n_keys_are_translated`
  fails with `missing i18n entries: ['Edit']`.
- **Expected:** all fragment keys translated.
- **Actual:** the Indicators drawer Edit button renders its English fallback.
- **Impact:** cosmetic/localisation only.
- **Reproducible:** yes (`python -m pytest tests/test_indicators_tab.py::test_fragment_data_i18n_keys_are_translated`).
- **Confidence:** confirmed. **Design vs defect:** defect.
- **Screens:** Indicators tab drawer.
- **Proposed remediation (not applied):** restore the key in `i18n.js`.
- **Verification required:** that single test green.

### D12-08 — Four migration tests fail on SQLite

- **Severity:** P2 · **Classification:** defect (test infrastructure, pre-existing)
- **Component:** `alembic/versions/a1c2e3f4b5d6_repair_quality_score_revision_action.py`
- **Evidence:** `sqlite3.OperationalError: near "ALTER": syntax error` for
  `ALTER TABLE quality_score_revisions ALTER COLUMN action SET NOT NULL`; tests create a
  `tmp_path` SQLite DB, so no production data is touched.
- **Expected:** migration is SQLite-compatible or guarded for the test dialect.
- **Actual:** all four upgrade/downgrade variants of that migration fail.
- **Impact:** the full suite cannot be green (`exit=1`), masking future regressions.
- **Reproducible:** yes (`tests/test_indicator_definitions_migration.py`, 4 tests).
- **Confidence:** confirmed. **Design vs defect:** environment/test defect, not caused by D12.
- **Screens:** none (CI signal only).
- **Proposed remediation (not applied):** guard with `batch_alter_table` or skip on SQLite.
- **Verification required:** 4 tests green on SQLite; unchanged on PostgreSQL.

---

## F. Test report (existing suites only, no tests added)

Command:

```
python -m pytest <51 selected test files>   # run in BACKGROUND, log /tmp/d12-suite.log
```

| Item | Value |
|---|---|
| Files | 51 |
| Passed | **1 168** |
| Failed | **5** |
| Skipped | **2** |
| Duration | 1 635.24 s (27:15) |
| Exit code | **1** |
| Database | per-test SQLite file DB via `tests/conftest.py` (production `health_ai` never opened) |

Failures: 4 × `tests/test_indicator_definitions_migration.py` (D12-08), 1 ×
`tests/test_indicators_tab.py::test_fragment_data_i18n_keys_are_translated` (D12-07).
No failure touches the outlier engine, caps, gate or comparison policy.

---

## G. Limitations

1. No application server was started (a boot could run `_ensure_all_tables()` / migrations), so
   all screen-level conclusions rest on code paths plus read-only recomputation of the same
   functions, not on live HTTP responses.
2. Node-level browser behaviour (JS fallbacks) was read from source, not exercised.
3. The 790 / 146 re-band counts are read-time recomputations; stored rows were deliberately not
   rewritten, so D12-03's score impact is quantified structurally, not numerically.
4. Two `git stash` entries and 133 pre-existing porcelain entries belong to earlier work; they were
   inspected only as baseline, never applied.
5. Alert "active" population could not be reproduced with `status` (all 7 156 rows are `New`);
   the earlier 5 043 figure came from a resolution-flag filter. Counts and id checksums are
   unchanged, so this does not affect the write-freedom conclusion.

---

## H. Scope manifest

- Branch `very-high-gate-integration`, HEAD `4b82b19388f0b8568ca8c33c62a9b5f7aa60daac`; 2 stashes;
  133 porcelain entries before and after.
- Engine: `app/engine/anomaly/layered.py`, `app/engine/quality_alerts.py`,
  `app/engine/severity.py`, `app/engine/comparison_policy.py`, `app/engine/quality/scoring.py`,
  `app/engine/export.py`, `app/engine/audit/explain.py`, `app/engine/audit/benchmark.py`,
  `app/engine/root_cause.py`, `app/engine/smart/regional.py`, `app/engine/indicator_calc.py`.
- APIs: `app/api/quality_alerts.py`, `app/api/dashboard.py`, `app/api/analysis.py`,
  `app/api/reports.py`, `app/api/alerts.py`, `app/api/rules.py`.
- Frontend: `static/js/quality-alerts.js`, `static/js/outliers.js`, `static/js/i18n.js`,
  `static/tabs/indicators.html`.
- Data: `quality_alerts` (7 156), `layered_outlier_results` (10 787), `quality_scores` (176),
  `validation_results` (7 867), `anomaly_results` (2 037), `indicator_values` (16 720),
  `hospitals` (39), `indicators` (100).
- Tests: `tests/conftest.py`, `tests/test_indicator_definitions_migration.py`,
  `tests/test_indicators_tab.py` + 48 further files in the 51-file run.
- Artifacts: this report (`qa-d12/`), `/tmp/d12-baseline.txt`, `/tmp/d12-suite.log`.

---

## I. Review recommendation

**READY WITH LIMITATIONS.**

- No P0 and no evidence of a second production engine: all band displays resolve through the shared
  policy, caps never raise a band, and KPI parity is exact.
- Two P1 defects (D12-01, D12-02) are confined to the history perspective's top band and to
  identical-window scoring, are already surfaced by `cross_check`, and have bounded remediation
  paths.
- D12-03 (score penalty from stored band) and D12-04 (provenance gaps) should be folded into the
  same remediation cycle.
- D12-07 and D12-08 are unrelated hygiene items; fixing them is a prerequisite for a green baseline.

**No remediation has been performed. Awaiting explicit approval before any fix.**
