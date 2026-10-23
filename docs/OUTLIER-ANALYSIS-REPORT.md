# Outlier Analysis & Outlier Diagnostics — Computation Report

**Scope**: how the two outlier screens compute every number they show, which
data each one consumes, and where to change behaviour. Everything below is
sourced from the running code (file references included).

---

## 1. Where the data comes from (both screens)

```
Excel uploads (Upload screen)
        │  data-tree codes, e.g. 2=deliveries, 5=C-sections, 6=live births,
        │  7=stillbirths, 10=SMM, 11=maternal deaths, 17=neonatal deaths
        ▼
IndicatorValue rows  (hospital_id, month, indicator_id, value)
        │  enabled values only (disabled indicators excluded;
        │  Required-denominator rule — pipeline.get_enabled_values_*)
        ▼
run_full_analysis()  ── app/engine/pipeline.py   (one pass per hospital × month)
        │
        ├──► LayeredOutlierResult rows     → detection truth (Outlier
        │                                     Diagnostics, Quality report,
        │                                     Quality Alerts, Quality Score)
        └──► AnomalyResult rows            → a PROJECTION of those rows
                                             (Outlier Analysis, dashboard,
                                             audit benchmark, root cause)
```

There is **one detector** (`run_layered_analysis`). The `anomaly_results`
table is filled by `app/engine/anomaly/projection.py` from the layered
results — same value, same benchmark, same verdict — so a month cannot be an
outlier on one screen and normal on another. Nothing is computed at page-load
time; every screen is a pure read of persisted rows. The classic
`detect_anomalies` detector (section 2.2 A) is no longer run by the pipeline;
it survives only as the degraded fallback if the layered engine fails.

The **rate formulas themselves are never inline**: every rate is evaluated
through the central registry (`app/engine/rate_config.py`) — numerator codes,
denominator codes, and display multiplier live there, plus DB-merged overrides
(`load_rate_specs`, rate_config table).

---

## 2. Outlier Analysis screen (tab: Outliers)

**Reads**: `GET /analysis/outliers` → `anomaly_results` table
([app/api/analysis.py:370](../app/api/analysis.py)) — only rows with
`is_outlier = true`, active hospitals, sorted by z-score descending.
**Written by**: `_save_anomaly_results`
([pipeline.py:704](../app/engine/pipeline.py)).

### 2.1 Candidate set — every derivative indicator, once

Candidates come from `indicator_service.resolve_outlier_candidates(session)`
([indicator_service.py:284](../app/engine/indicator_service.py), called at
[pipeline.py:426](../app/engine/pipeline.py)):

- **all active registry definitions**, whichever analysis site seeded them
  (`zscore`, `clinical`, `forecast`) plus **shared/managed definitions** the
  user created in the Indicators screen — i.e. exactly the Indicators screen's
  "Derivative Indicator" rows;
- **one candidate per rate**, grouped by formula + unit *scale* (`per 1000`
  and `per 1,000` are the same scale), because the registry stores the same
  rate once per site. The zscore copy represents its group, so a stored
  result keeps its identity across re-analyses; a rate with no zscore copy
  is represented by its clinical copy, then forecast.

Raw data elements are excluded by construction (the resolver only reads
`IndicatorDefinition` rows) — locked by the contract test
`tests/test_outlier_screen_indicator_types.py`. Count-type derivatives
("Adolescent cases") are included: they are computed from data elements even
though they carry no denominator. The screen's dropdown is labelled
**"Derivative Indicator"** and is filled from
`GET /analysis/outlier-indicators` (the same candidate list), so it always
offers the whole catalog rather than only the rates that happen to have an
outlier in the current result set.

### 2.2 Projected rate rows (legacy detector, kept only as a fallback)

`AnomalyResult` rows are now produced by the projection, not by a detector.
The formulas below describe the fallback that runs only when the layered
engine cannot run; its peer rule is the same canonical all-hospital group, so
even the fallback cannot quote a different benchmark.

**A. Cross-hospital (peer) anomaly** — `detect_anomalies`
([zscore.py:72](../app/engine/anomaly/zscore.py)):

```
rate_h       = registry rate of hospital h this month
peers        = all other hospitals with a computable rate this month
benchmark    = mean(peers)
z            = (rate_this − benchmark) / std(peers, ddof=1)     [0 if std=0]
is_outlier   = |z| > zscore_threshold        (default 2.5)
```

The benchmark **excludes the hospital itself** (same definition the Audit
benchmark screen uses, so both views agree). Each row stores peer count,
std, min, max, median and a `peers_detail` list powering the drill-down
popover.

**B. Own-history (trend) anomaly** — `detect_monthly_trend`
([zscore.py:131](../app/engine/anomaly/zscore.py)):

```
history      = same hospital's rates in strictly earlier months (≥ 2)
benchmark    = mean(history)
z            = (current − benchmark) / std(history, ddof=1)
```

Rows get the suffix **"(trend)"** on the rate name and carry no peer stats.

**Dedup**: one row per indicator — the cross-hospital anomaly wins over the
trend row ([pipeline.py:431](../app/engine/pipeline.py)).

### 2.3 Threshold

`zscore_threshold` from the Trends config (`AppConfig`), default **2.5**,
passed into both detectors as `anomaly_config`
([pipeline.py:385](../app/engine/pipeline.py)). A p-value is computed
(SciPy normal tail) but the stored decision is purely the z-threshold.

### 2.4 What the screen shows

Month / hospital / derivative-indicator filters (the indicator list is the
registry — `/analysis/outlier-indicators` — and filters on the definition
**code**, so two indicators sharing a name stay distinct); the
**Classification column** is a
cross-reference joined from the Diagnostics screen's rows
(`layered_type` / `layered_level` / `layered_interpretation`,
[analysis.py:441-490](../app/api/analysis.py)); the **Why** popup is served by
`/audit/explain?kind=anomaly` and recomputes the same rate live through the
registry (`compute_rate`). CSV / JSON export is client-side.

---

## 3. Outlier Diagnostics screen (tab: Layered)

**Reads**: `GET /analysis/layered` → `layered_outlier_results` table
([analysis.py:497](../app/api/analysis.py)) — paged (50/page), sortable by
month / level / type / raw_value / rate / denominator.
**Written by**: `_save_layered_results`
([pipeline.py:788](../app/engine/pipeline.py)) via `_run_and_save_layered_results`
([pipeline.py:733](../app/engine/pipeline.py)).

### 3.1 Analysis units

`build_analysis_specs` ([layered.py:735](../app/engine/anomaly/layered.py))
builds one spec per:

- **count indicator** — every non-synthetic `Indicator` row (the Data Element
  indicators), carrying per-indicator settings: `minimum_history_period`
  (default 3), `outlier_method` (default `auto`), `historical_enabled`,
  `peer_comparison_enabled`;
- **rate spec** — every *active* row of the rate registry (numerator +
  denominator codes, multiplier, unit, optional `minimum_denominator`).

Rows with a denominator are **rate rows** (`rate_*` codes); the rest are data
elements. This is why the screen's indicator filter (labelled **"Data
Element"**) never offers rate rows — the frontend drops any row with a
synthetic `rate_` code or persisted numerator+denominator
(`_isRateRow` guard in `static/js/layered.js`).

### 3.2 The five layers

For each hospital × spec × month, `analyze_layered_entry`
([layered.py:570](../app/engine/anomaly/layered.py)) runs the layers in a
fixed order (peer never runs first):

| # | Layer | What it scores | Applies to |
|---|-------|----------------|------------|
| 1 | **Raw value** | numerator (rate rows) or the count itself vs prior months | all rows |
| 2 | **Rate** | current rate vs the hospital's own historical rates | rate rows only |
| 3 | **Historical baseline** | current value vs the baseline window (mean/median/std/z), optional Theil–Sen `trend_deviation` blend when configured | all rows |
| 4 | **Volume** | % change of the **denominator** vs previous month; missing/zero denominator ⇒ `den_ok=False` and rate layers become not-computable | rate rows only |
| 5 | **Peer comparison** | z-score of this month's unit value vs **every other active hospital reporting the indicator that month** (the single canonical baseline — self excluded, ≥ 2 others required) | rows with peers enabled |

### 3.3 Method auto-selection (per series)

`select_method` ([layered.py:219](../app/engine/anomaly/layered.py)):

1. a configured per-indicator method always wins;
2. rare-event counts (mean < 10) → **rolling median + MAD** (×1.4826 scale) —
   plain z is never used on small counts;
3. stable series (CV < 0.5) → **% change**;
4. ≥ 6 points → **IQR** (Tukey fences, 1.5×IQR);
5. otherwise → **z-score**.

### 3.4 Score → severity band

Every layer maps its deviation to a 0–1 score, then to a band
(`BAND_CUTOFFS`, [layered.py:29](../app/engine/anomaly/layered.py)):

```
score < 0.25 → NONE        score < 0.75 → MODERATE
score < 0.50 → LOW         score < 0.90 → HIGH
                             otherwise   → VERY_HIGH
```

Anchors: `|z| = threshold` ⇒ 0.5 (MODERATE), `|z| = 2×threshold` ⇒ 1.0;
`|Δ%| = 100` ⇒ 1.0 for %-change methods.

### 3.5 Classification — deterministic rule table

`classify_layered` ([classify.py:199](../app/engine/anomaly/classify.py)),
first match wins:

| Rule | Condition (summary) | Classification | Route |
|------|--------------------|----------------|-------|
| 1 | fewer than `minimum_history_period` prior months | NORMAL (insufficient history) | none |
| 2 | raw + rate + history all HIGH, volume ≤ LOW, change ≥ **+300%** | **POSSIBLE_DATA_ENTRY_ERROR** | data_quality |
| 3 | raw HIGH + volume HIGH, rate ≤ MODERATE | **VOLUME_DRIVEN_ANOMALY** | contextual |
| 4 | rate HIGH + history HIGH, volume ≤ LOW | **CLINICAL_INVESTIGATION_REQUIRED** | clinical |
| 5 | history HIGH | **HISTORICAL_ANOMALY** | contextual |
| 6 | peer HIGH, history ≤ LOW | **PEER_ANOMALY** | contextual |
| 7 | peer HIGH + history ≥ MODERATE | **PEER_ANOMALY** (both stated) | contextual |
| 8 | raw ≥ MODERATE, nothing else HIGH | **RAW_VALUE_ANOMALY** | contextual |
| 9 | rate ≥ MODERATE, nothing else HIGH | **RATE_ANOMALY** | contextual |
| 10 | otherwise | NORMAL | none |

Overall level = highest applicable layer score (capped at **LOW** for
rate-based types when a `minimum_denominator` guard trips — small
denominators can never claim HIGH). Rules 2, 4, 6, 7 flag
`investigation_required`. The interpretation sentence is composed from the
actual numbers (`build_interpretation`) — never a canned string.

### 3.6 Persistence rule

Only rows where the **raw analysis value (numerator) exists this month** are
persisted (`should_persist`, [layered.py:728](../app/engine/anomaly/layered.py)) —
a present numerator with a missing denominator is kept (the row documents
that the rate was not computable).

### 3.7 What the screen shows

Month + hospital filters, with Data Element / Classification / Level /
Investigation behind **Advanced filters**; a five-square severity strip per
row (one square per layer, colored by the same band cutoffs the engine uses);
**Why** opens the stored layer scores + interpretation; CSV export. The
indicator dropdown lists Data Element indicators only (rate rows live on the
Outlier Analysis screen).

---

## 4. How the two screens relate

| | Outlier Analysis | Outlier Diagnostics |
|---|---|---|
| Question answered | *Is* this hospital an outlier on a derivative indicator? | *Why* is this row classified the way it is? |
| Reference set | other hospitals (same month) **or** own history | own 5-layer evidence: raw, rate, history, volume, peers |
| Decision | binary `|z| > 2.5` | 10-rule deterministic classification + 5-level severity |
| Unit of analysis | registry/managed rate definitions | every data element **and** every active rate spec |
| Table | `anomaly_results` | `layered_outlier_results` |

The Analysis screen's **Classification** column is literally the Diagnostics
row for the same (hospital, month, analysis code) — joined at read time.

---

## 5. Where to change what

| Want to change | Place |
|---|---|
| Rate formula (numerator/denominator/multiplier) | `app/engine/rate_config.py` (builtin) or the rate_config DB table |
| Peer z threshold (both screens) | AppConfig `zscore_threshold` (Trends config, default 2.5) |
| Detection method constants (`CV_MAX`, `MIN_IQR_POINTS`, `RARE_EVENT_MEAN_MAX`, `MAD_SCALE`) | `app/engine/anomaly/layered.py` §Method-selection constants |
| Classification rules / bands | `app/engine/anomaly/classify.py` + `BAND_CUTOFFS` in `layered.py` |
| Per-indicator history/method toggles | Indicator rows (`minimum_history_period`, `outlier_method`, `historical_enabled`, `peer_comparison_enabled`) |
| Small-denominator guard | rate registry `minimum_denominator` per rate |
| Peer group (all hospitals reporting the indicator that month) | `canonical_peer_tiers`, `layered.py` |
| Detection floor (MODERATE and up) | `is_detection_outlier` / `OUTLIER_LEVEL_MIN`, `layered.py` |
| Screen filters / rendering | `static/js/outliers.js`, `static/js/layered.js`, `static/tabs/outliers.html`, `static/tabs/layered.html` |

## 6. Regression coverage

- `tests/test_single_outlier_truth.py` — one detector: the projection matches
  the layered rates value-for-value and verdict-for-verdict, the peer group is
  every reporting hospital, and the report card counts exactly the
  detection-level layered rows.

- `tests/test_outlier_screen_indicator_types.py` — Analysis candidates are
  derivative-only; each screen's selector is wired to its indicator type.
- `tests/test_layered_ui.py`, `tests/test_outliers_js.py` — screen contracts.
- `tests/test_anomaly.py`, `tests/test_layered_engine.py`,
  `tests/test_layered_pipeline.py` — detector math and persistence.
- Layer classification scenarios live with the engine spec tests
  (rules 1–10, including the +300% magnitude guard and the small-denominator
  cap).

---*Generated from the running source code, October 2026.*

## ملخص بالعربية

- **شاشة تحليل الشذوذ (Outlier Analysis)**: تقرأ من جدول `anomaly_results`
  الذي يُبنى عند كل رفع/إعادة حساب. المرشحات هي **المؤشرات المشتقة** فقط
  (من السجل المركزي `rate_config` + التعريفات المشتركة)، والحكم بسيط:
  z-score مقابل متوسط المستشفيات الأخرى (بدون المستشفى نفسه) أو مقابل تاريخ
  المستشفى نفسه، والشذوذ عندما يتجاوز |z| العتبة 2.5.
- **شاشة تشخيص الشذوذ (Outlier Diagnostics)**: تقرأ من
  `layered_outlier_results` وتحسب **خمس طبقات** لكل مؤشر (خام، معدل، تاريخ،
  حجم/مقام، أقران) ثم تصنّف عبر جدول قواعد حتمي من 10 قواعد إلى 8 أنواع من
  الشذوذ مع مستوى خطورة من NONE إلى VERY_HIGH، وتحوّل صغير في المقام يقصّ
  المستوى عند LOW.
- كل الأرقام تأتي من نفس تمريرة التحليل (`run_full_analysis`)، ويمكن تغيير
  كل عتبة أو صيغة من السجل المركزي أو من إعدادات كل مؤشر.
