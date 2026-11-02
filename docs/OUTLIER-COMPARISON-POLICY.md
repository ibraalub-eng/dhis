# Outlier comparison policy (Anomaly Diagnostics + Quality Alerts)

## The defect this defines away

Both engines compare a hospital's current value with its own history and with
other hospitals, but they had no shared policy:

| | Anomaly Diagnostics (before) | Quality Alerts (before) |
|---|---|---|
| Hospital history | **every prior month ever recorded** | last 12 reporting months (capped by the trend window) |
| Minimum history | `months >= minimum_history_period`, missing values not counted | 3 **valid** observations |
| Peer group | all active hospitals reporting this month | five perspectives, minimum 2 peers each |
| Method | per-rate/indicator `outlier_method` | always `auto` |

A hospital with 24 months of history could therefore be a mild deviation under
the long Diagnostics baseline (score **0.11**) while Alerts, looking only at its
recent flat 12 months, called the same month extreme (**1.0**). Neither was a
bug in isolation; the missing policy was.

## Approved policy (version `2026-10-24.1`)

Both engines import [app/engine/comparison_policy.py](../app/engine/comparison_policy.py).
There is no second copy of the clamp rules.

### Hospital-history baseline — shared

* Window: the most recent **N stored reporting months** strictly before the
  analysed month. N is the **shorter** of
  `alerts_history_window` (default 12) and the System Control
  `trend_analysis_window` (default 12). A month with no stored data does not
  invent a calendar slot; the window slides over the months that exist.
* Minimum: `alerts_min_history` (default 3, never below 2) **valid
  observations** — computed values, not calendar months. A per-indicator
  `minimum_history_period` acts as a stricter floor. Three stored months with
  one computed value is not a three-point baseline.
* Method: the per-formula configured `outlier_method` when one exists
  (`rate_config` / `Indicator`), otherwise the shared `auto` selection. Alerts
  resolves that configuration by canonical formula identity, so a registry
  definition and its rate_config row cannot use different methods.
* Disabled history (`historical_enabled = false`) disables the baseline in both
  engines; it does not delete the data or hide a diagnostic row.

### Peer baseline — shared for the same question

* Group: **all active hospitals with a valid value for the same month and
  formula**, self excluded. This is the Diagnostics peer layer and the
  `all` perspective in Quality Alerts — one baseline, one verdict.
* Minimum: `alerts_min_peers` (default 2, never below 2) other hospitals. Below
  the minimum the layer is unavailable (`score = NULL`), but the eligible peers
  are still recorded so the null is explainable.
* Statistic: peer mean and sample standard deviation (`ddof=1`), z against the
  same `zscore_threshold` (default 2.5), same 0–1 score builder and severity
  bands.

### Intentionally different perspectives — Alerts only

Quality Alerts additionally compares against same hospital type, ownership,
facility type and governorate. These are **not** equivalent to the detection
baseline:

* they answer a narrower question and may legitimately find a different member
  set or a different verdict;
* they use the same minimum peer count and the same score builders;
* every persisted row records its `perspective_scope` (`detection_baseline` or
  `stratified`), its group id (`all_active_reporting` or
  `stratified:<perspective>`) and its human label;
* they never replace, rewrite, or suppress the diagnostic result. Alerts write
  only their own rows; Diagnostics rows are untouched by a scan.

The UI labels remain distinct: “Hospital history”, “All hospitals”, “Similar
hospitals (type)”, “Ownership peers”, “Facility-type peers”, “Regional peers
(governorate)”.

## Classification policy when history is insufficient (rules 1 / 11)

A month whose own-history baseline is not evaluable is **not** silently a
normal result. The peer layer is still computed (it needs only this month's
value), and the verdict depends on it:

| History | Peer band | Classification | Level | Route |
|---|---|---|---|---|
| insufficient | unavailable or below HIGH | `INSUFFICIENT_HISTORY` | `NONE` | none |
| insufficient | HIGH / VERY_HIGH | `PEER_ANOMALY` (rule 11) | highest applicable layer band | contextual |
| sufficient | quiet | `NORMAL` (rule 10) | `NONE` | none |
| sufficient | HIGH, history quiet | `PEER_ANOMALY` (rule 6) | highest layer band | contextual |
| sufficient | HIGH, history MODERATE | `PEER_ANOMALY` (rule 7) | highest layer band | contextual |
| sufficient | quiet, history HIGH | `HISTORICAL_ANOMALY` (rule 5) | highest layer band | contextual |

* `INSUFFICIENT_HISTORY` means **the assessment could not be made**. The row
  keeps `historical_outlier_score = NULL` (unavailable evidence), never `0.0`
  (evidence of normal behaviour), and is not counted as a detection outlier.
* Rule 11 requires the same **HIGH** peer band rules 6/7 already use. A peer
  score is mapped through the existing bands and is **never promoted**: a
  score of 0.80 stays HIGH, 0.95 stays VERY_HIGH. MODERATE peer evidence is
  preserved on the row (`peer_outlier_score`) and in the interpretation, but
  does not classify without history.
* A peer-anomaly row with insufficient history is distinguishable from a
  history-confirmed one by its type plus a NULL history score and a
  `peer_zscore` method. It is peer evidence, not a confirmed historical
  anomaly.
* **Quality Score effect:** the outlier component already flags HIGH/VERY_HIGH
  rows (`FLAGGED_LEVELS`), so a rule-11 row can attract the existing penalty
  where the old `NORMAL` verdict suppressed it. No level threshold, weight or
  multiplier changed; the change is that a real finding is no longer hidden.
* **Conflicts** follow the rule-table precedence and are stated in the stored
  interpretation: history HIGH with quiet peers stays `HISTORICAL_ANOMALY`
  ("peers do not share this deviation"); peer HIGH with quiet history is
  `PEER_ANOMALY` ("no deviation from its own baseline"); both HIGH is a
  confirmed anomaly under rules 2/4/5, not a conflict.

## Degenerate comparisons (no dispersion)

A comparison whose members are **all identical** has no scale. The peer group
reports the same value (usually `0`), or the history window is flat, so the
sample standard deviation is `0`, the z-score is `0/0` and the relative
deviation is `undefined/0`. The shared score builders answer that case with
`1.0`, which is the right *raw* signal — this hospital really is the only one
off the common level — but it is not a measured magnitude. It was previously
taken at face value, so "the only hospital reporting this indicator" became the
loudest finding on the screen:

| Live database before the policy | Value |
|---|---|
| Stored alerts with `baseline_value = 0` | **889** (12% of all alerts) |
| … of those at `VERY_HIGH` | **889** (100%) — 24% of every `VERY_HIGH` row |
| … with `score = 1.0`, `z = NULL`, `stats.std = 0` | **889** |
| … active | 835 |
| Sensible baselines that were miscomputed | **0** — the peers genuinely reported `0` |

**Approved policy.** A no-dispersion comparison keeps its finding and its
evidence, and its level is **capped at `HIGH`**:

* the score, the baseline, `z = NULL`, the peer ids and the full window stay on
the row, so the underlying evidence is not discarded;
* the resolved band is preserved separately: `evidence.dispersion` records
  `zero_spread`, `cap`, `resolved_level` (what the score alone implied),
  `final_level` (what is stored) and the policy sentence;
* the stored `reason` states the cap, so the explanation travels with the row;
* the severity **thresholds are unchanged** — no band boundary, weight or score
  formula moved. Only a comparison that cannot grade a magnitude is refused the
  top band;
* a level the comparison did earn below `HIGH` (`MODERATE`, `LOW`) is never
  lowered further, and any comparison whose divisor is real is untouched;
* the cap applies only to scores **built from the spread** — `peer_zscore`,
  `zscore`, `rolling_median_mad`, `iqr`, the methods that divide by it. A
  percentage change against a flat baseline is fully measurable (“+700% vs a
  flat 10%”) even though `std = 0`, so it keeps whatever band its magnitude
  earns; that includes the common “flat history, sudden jump” case. (When the
  same window *does* have a measured spread, the percentage-change clamp below
  applies instead.)

**The divisor is the method's, not always the standard deviation.**
`rolling_median_mad` divides by the MAD and `iqr` by the inter-quartile range;
both can be `0` while the window's std is not — `[0, 0, 0, 0, 0, 18.9, 0]` has
MAD `0`, IQR `0` and std `7.13`. Testing `std` alone therefore let such a row
claim the top band on a scale its own method did not have: **533** stored
`VERY_HIGH` rows on the live store (506 MAD, 27 IQR), **491** of them with
`std > 0` and so invisible to the std-only test.

`layered.spread_used(method, series)` now returns the divisor each method's
score actually divides by — `std` for `zscore`/`peer_zscore`, `mad`, `iqr`, and
`residual_std` for `trend_deviation` — and both engines test that value. New
rows record it in `evidence.stats` (`mad`, `iqr`) and the cap records
`dispersion: {kind, value}`, so a capped row says WHICH scale was zero instead
of always reporting `std = 0`; rows written before it recompute the divisor
from the stored history series, so the read-time band matches the scan.

**Measured effect** (read time, nothing rewritten): **270 open issues** move
`VERY_HIGH → HIGH`; the dashboard's Very High card and the Quality Alerts KPI
read **947** instead of 1,217, while the open-issue total stays **2,658**. Only
27 of the 297 affected open rows kept a Very High issue, because a sibling
perspective on the same issue still carries the band without a cap.

On screen the flag is explicit: the list marks a `0`/flat baseline with a
**no spread** badge whose tooltip states that the comparison has no measurable
spread for the method used and that the level is capped, and the detail card
adds "Comparison group has no spread" when the values are in fact identical,
or "No measurable spread for this method" when only the divisor is zero. `GET /quality-alerts/issues` carries
`zero_spread` and `dispersion` on every perspective row, derived from the stored
`stats`, so rows written before the policy are labelled without a re-scan (a
re-scan is still what restates their *severity*).

**Both engines.** The policy has one implementation,
[layered.cap_zero_spread](../app/engine/anomaly/layered.py); Quality Alerts
calls it with its comparison statistics and Anomaly Diagnostics with the
`std` of each layer. Neither screen can therefore promote a zero-dispersion
comparison to `VERY_HIGH` while the other refuses to.

Diagnostics applies the cap to the **layer band, never to the row**:

* `raw`, `rate`, `historical` and `peer` layers report `zero_spread` when their
  score was built from a spread of 0 (`historical` uses the trend residual when
  the configured method is `trend_deviation`);
* the classifier caps each degenerate layer's band at `HIGH` and takes the
  highest remaining band, so a degenerate peer group cannot suppress a level a
  measured layer earned (and a measured layer beside it still reaches
  `VERY_HIGH`);
* the stored row keeps `peer_outlier_score = 1.0`, `historical_outlier_score`
  and every layer value verbatim; `peer_z` is `NULL` for a no-spread group
  (a z of `0.0` would claim "at the mean" while the score claims the opposite);
* `layered_outlier_results.classification_provenance` records
  `{zero_spread_layers, level_from_layers, level, cap}` (migration
  `f5a6b7c8d9e0_add_layered_classification_provenance.py`), and the stored
  `interpretation` states which layer had no spread.

`peer_std == 0` still yields score `1.0`: the raw evidence is preserved, only
the band it may claim is limited. The Why popup re-applies the stored flag when
it recomputes the rule table, shows the capped band in the layer strip with a
**no spread** marker, and reports `verified: false` with a "recalculate this
month" note for rows written before the policy (they carry NULL provenance).

### Diagnostics shows the policy band, not only the stored one

Outlier Diagnostics re-applies both caps when it **reads** a row
([layered.row_level_assessment](../app/engine/anomaly/layered.py)), exactly as
Quality Alerts does, so a row written before a cap was approved is presented
under the policy in effect now instead of waiting for its month to be
re-analysed:

* `outlier_level` in every payload is the band the policy assigns now;
  `stored_outlier_level` is what the row holds; `severity_cap` explains the
  difference (`{stored_severity, severity, zero_spread_layers,
  thin_peer_group, policy}`), and the table marks the row `VERY_HIGH → HIGH`
  beside the badge;
* the caps are decided per layer from what the row itself stores — its
  `classification_provenance` when present, otherwise its own peer-group values
  and history window — so a legacy row needs no re-scan, and a measured layer
  still holds the band a degenerate one cannot (nothing is lowered when no cap
  applies);
* the `level` filter, its counts, the trend chart and the heatmap use that band
  (the SQL pre-filter is widened to the stored bands a cap can lower, then
  filtered exactly), so the chips, the table and the chart cannot disagree;
* the Quality report's element and rate outlier lists read the same function;
* nothing is rewritten: a re-scan is still what restates the STORED severity,
  and on a month already scanned under the current policy the read-time band is
  identical to the stored one (0 of 10,787 live rows differ).

**Restating the store is a separate, explicit action.**
`POST /analysis/layered/rescan-stale` previews (default `confirm: false`) the
months and hospitals that still disagree — rows, scopes and the level moves
(`VERY_HIGH → HIGH`) — and writes nothing. With `confirm: true` it re-runs the
canonical analysis for exactly those (month, hospital) scopes: never a whole
month, never a scope that is already consistent. It needs `dashboard.write`,
returns the scopes it rescanned, the errors it hit and how many rows still
disagree afterwards, invalidates the analysis cache, and leaves the score
revisions of every rewritten month on record. Like any analysis run it also
refreshes that month's Quality Alerts through the normal auto-scan. The UI exposes it as **Recompute
stale months** on Outlier Diagnostics, with the preview shown in the
confirmation dialog.

## Comparison groups too small to measure a spread (thin peer groups)

A peer z-score divides by the group's own spread. With 2-3 other hospitals
that spread is estimated from 2-3 numbers — a range, not a distribution — so
the z is not a measurement of anything. The stored data showed what that costs:
rows carried `|z| = 224` from a **2-peer** group, because two nearly identical
peers make any difference look astronomically large.

The boundary is `MIN_PEERS_FOR_TOP_BAND = 4` other hospitals
([layered.py](../app/engine/anomaly/layered.py)), the same constant Quality
Alerts already used to mark a row `low confidence`. Two rules follow from it,
and they apply to the **peer layer only** — one hospital's flat history or its
denominator shift is a different question with its own cap.

**1. The top band is refused (band cap).** A peer comparison with fewer than
four peers cannot claim `VERY_HIGH`; its band is capped at `HIGH`. Everything
else the layer produced — the score, the z (when one is produced), the peer
list, the low-confidence flag — is kept, so "differs from 2 peers, but only
HIGH" is explainable rather than hidden. A level another, measured layer earned
is untouched (the cap is applied per layer, never per row).

**2. No z-score is produced (this policy's change).** For the same group the z
is **not produced at all**: `z = NULL`, on the layer, on the alert and on the
projected `anomaly_results` row. The band cap alone was not enough — it refused
the band while the z itself still read as a top-band magnitude on every screen
that quoted it (`z = 224.30` next to "threshold |z| ≥ 2.50"). What is kept is
the evidence that matters: the peer values, their mean, the peer count, the
deviation and the **score** — the same treatment a no-dispersion comparison
already gets (`z = NULL`, score `1.0`).

* one implementation for both engines:
  [layered.peer_z_measurable / peer_z_provenance](../app/engine/anomaly/layered.py);
  Quality Alerts scores its perspectives through `_peer_score`, which records
  `evidence["stats"]["z_provenance"] = {peer_count, min_peers_for_z, z_produced,
  policy}`;
* **no threshold changes**: the z threshold, the score formula and every band
  cut-off are untouched, `min_peers` still decides whether the layer EXISTS and
  the same z threshold still decides whether it fired. This is a sufficiency
  rule for the z, not a new severity rule;
* the **projected legacy row never substitutes** the hospital's own-history z
  for a peer comparison that was not graded (`projection.row_z_score`): the
  row's `benchmark` is the peer mean, so a history z beside it would describe a
  different comparison;
* both screens state it: the classifier appends "peer comparison has fewer
  than 4 peer hospitals - too few to measure a spread, so the level is capped
  at HIGH and no z-score is produced for it"; the Diagnostics layer strip marks
the peer layer **no z**, the Quality Alerts detail explains the dash in the
Z-score KPI ("Too few peer hospitals to measure a spread") and adds the same
line to "How it was compared";
* the Why popup reports the provenance (`reproduce.peer_z`, and `peer_z` on a
legacy anomaly row's audit block) and, for a stored row whose z is NULL because
of this policy, verifies the **peer population** instead of claiming a missing
measurement.

Rows written before this policy keep their stored z **on the row** until the
month is re-analysed (Diagnostics) or re-scanned (Alerts). `z_produced: false`
in the provenance is the marker of a post-policy row.

**The Quality Alerts screen does not wait for that re-scan.** The z it shows is
derived at read time by `engine.effective_z_score` — the same predicate, applied
to the stored row exactly as `effective_severity` derives the band — so a
pre-policy row presents `z_score: null` with `z_provenance` (`scope: "peer"`,
`z_produced: false`, `min_peers_for_z: 4`) and the dash explanation, while its
`stored_z_score` keeps the value the row was written with and the database row
is never modified by a read. Only `method = peer_zscore` is gated: the history
perspective stores prior MONTHS in `peer_count`, and its z is governed by the
history-observation minimum instead.

On the live store that gate withholds the z from **795 of 5043** active alerts —
all of them `peer_zscore` rows resting on 2 peers (330) or 3 peers (465), with a
stored |z| up to 224.15 — without a re-scan. 3432 stored z-scores remain
presented because their group can measure a spread.

**Every screen that could quote a peer z applies the same predicate**, so no
screen reads a top-band magnitude out of 2-3 peers:

| Surface | Source | What it does |
|---|---|---|
| Outliers / historical cross-hospital rows | `anomaly.zscore.detect_anomalies` | z `NULL` + `z_provenance`; the outlier verdict, benchmark and peer list stay |
| Audit benchmark screen | `audit.benchmark.get_benchmark` | z `NULL`, z-derived `status` `NULL` (never a green "pass"), `z_provenance`; mean/median/min/max/percentile stay |
| Root cause peer comparisons | `root_cause.calculate_peer_comparison`, `_build_peer_comparisons` | `hospital_z_score` `NULL` + `z_provenance`; percentile, mean, std and gap stay |
| Regional findings and the governorate table | `smart.regional._regional_anomalies`, `run_regional_analysis` | no cross-sectional finding is raised from a group that cannot measure a spread; the table's z cell is empty with the reason, the deviation stays |
| Quality Alerts list, detail and issue perspectives | `api.quality_alerts._alert_dict` via `engine.effective_z_score` / `z_score_provenance` | **read time**: a stored z from a group that cannot measure a spread is presented as `null` with provenance; `stored_z_score` keeps what the row was written with, so pre-policy rows need no re-scan |

Deliberately **outside** this rule: the regional risk score is a composite index
(0-100) that quotes a deviation, not a z, and its explainer lists deviation
factors — harden it only if the score itself is to be re-modelled.

## Percentage change vs. the window's own spread

A percentage change divides by the **baseline**, never by the spread: doubling a
value scores `1.0` whether the hospital has been flat for a year or routinely
swings by 80% month to month. Because a row's band is the highest applicable
layer, that change-only layer could outrank the z-score computed from the very
same window, and the row was stored at a band its own distribution denied:

| Live database (2026-04, monthly rows) | Value |
|---|---|
| History-perspective alerts scored by `pct_change` | 92 |
| … stored at a band **above** what their own z-score supports | **65** (71%) |
| … above it by two or more bands | 32 |
| Alerts whose `VERY_HIGH` had `\|z\| < 1` | several (e.g. `z = -0.23` on +93%) |

**Approved policy.** When the same series also supports a z-score (at least two
observations and a **non-zero sample standard deviation**), the
percentage-change score is **clamped to the score that z produces**
(`score_from_z` with the same configured `zscore_threshold`). The
change itself is kept and still reported; it simply does not grade the
magnitude:

* one implementation for both engines —
  [layered._score_window](../app/engine/anomaly/layered.py); Quality Alerts
  scores through `layered.score_window_detail`;
* **no threshold changes**: band cutoffs, `zscore_threshold` and the score
  formula are untouched. The clamp is `score = min(pct_score, z_score)`, so it
  can only **lower** a band, never promote one;
* the underlying evidence is preserved on both screens: Diagnostics keeps the
  pre-cap score on the layer (`pct_change_score`) and names the clamped layers in
  `Classification.pct_change_capped`; Quality Alerts stores
  `evidence["pct_change_cap"] = {pct_change_score, score, z_score, z_threshold,
  policy}`;
* both screens state it in the stored text: Diagnostics appends “…the percentage
  change is not graded on its own - it is clamped to the level the same window's
  z-score supports…”, Alerts appends “Percentage change (1.00) is clamped to the
  level the window's z-score supports (0.89); the change itself is still
  reported.” A “+93% and not an outlier” row therefore always explains itself;
* **documented carve-outs** (no clamp, change kept as evidence): fewer than two
  observations, or `std = 0` (the no-dispersion cap above already refuses the
  top band), and Layer 4 (volume), which scores the denominator change and has
  no dispersion-based sibling layer on the row.

**Measured effect** (2026-04, recomputed in a rolled-back transaction — nothing
written). All 65 contradictory rows moved, and nothing else did:

| Screen | Before | After | Moved |
|---|---|---|---|
| Diagnostics `VERY_HIGH` | 156 | 123 | 92 rows demoted, 0 promoted |
| Diagnostics `MODERATE` / `NONE` | 105 / 692 | 67 / 729 | (of which 20 rows are pre-existing drift from the insufficient-history policy, not this clamp) |
| Alerts (all perspectives) | 721 active, 281 `VERY_HIGH` | 671 active, 262 `VERY_HIGH` | 65 `pct_change` rows; 50 fall below the alert floor, 15 keep a lower band |
| Alerts, other methods | — | — | **0 changed** (`zscore`, `rolling_median_mad`, `iqr`, `peer_zscore` untouched) |

Worked example, the row that started this: `h=21 / 5.b.1 / 2026-04` was stored
`VERY_HIGH` on 29 vs 15 (+93%) while `z = -0.23`; it is now `NONE/NORMAL`, and
the stored interpretation reads “No layer exceeded its threshold. … (+93% vs
previous month); +11% below baseline mean 32.7 … raw-value comparison, own-history
baseline: the percentage change is not graded on its own…”.

### Counting: the policy band, not the stored band

A row keeps the band it was written with. The **KPI cards and the table filter**
count the band the approved policy assigns (`engine.effective_severity`), which
is recomputed from the row's own evidence with the same two caps, in the same
order, the scan applies when it writes: no dispersion, then a peer group too
small to measure a spread.

Without this the Very High KPIs contradicted the policy: on the live store
**231 of 1448** open Very High issues were Very High only through a comparison
the caps refuse to grade, and the dashboard's Very High Issues card kept
reporting them. Measured effect, no re-scan and no write:

| Surface | Stored band | Policy band |
|---|---|---|
| Dashboard “Very High Issues” (`very_high_quality_issues`) | 1448 | **1217** |
| `/quality-alerts/summary` `very_high_issues` | 1448 | **1217** |
| … `very_high_rows` (perspective rows) | 2094 | **1686** |
| … `by_severity.HIGH` / `VERY_HIGH` | 1304 / 2094 | **1712 / 1686** |
| List under the default Very High filter | 1448 issues | **1217 issues** (= the KPI) |

There is no “red” vocabulary in the API: `VERY_HIGH` is one band, named for
itself, and the row count (`very_high_rows`) is a separate, explicit unit. The
old `red_alerts` / `red_issues` / `red_only_issues` / `red_quality_issues` keys
are gone rather than aliased, so no client can read a red number as a severity.

* one implementation, used by the dashboard card, the summary, the issue
grouping and the `severity` filter — so the card and the table cannot disagree;
* the stored band is not lost: each row reports its `stored_severity` plus
  `severity_cap` provenance (`stored_severity`, `severity`, `dispersion`,
  `thin_peer_group`), and the list marks a lowered row as `VERY_HIGH → HIGH`
  with the reason, instead of printing a band the row itself contradicts;
* the `severity` filter is applied to that band (in Python, where the rows are
already loaded for grouping) — filtering the stored column would list rows the
KPI cards no longer count;
* applying it to a row the scan already capped is idempotent: a cap only ever
  lowers a band, and it recomputes to the same one. The history perspective is
  unaffected — it stores baseline MONTHS in `peer_count`, and the thin-peer
  rule is keyed on `peer_zscore`;
* a **re-scan is still what restates the stored severity**. Nothing here
  rewrites a row, so the provenance stays honest about what was written.

### A Very High issue is not the same as a Very High-only issue

The `severity=VERY_HIGH` filter lists an issue when **at least one**
perspective that fired is Very High; the issue's own badge is that strongest
band. Two cards split exactly that population by what the rest of the evidence
says, and the screen states the arithmetic beside them:

* **Very High only** — every perspective that fired is Very High;
* **Mixed severity** — a Very High perspective plus a lower band.

On the live store that is **667 + 550 = 1,217** open Very High issues, which is
also the dashboard's Very High Issues card and `/quality-alerts/issues` under the
default filter. The list shows the per-perspective band on each chip, so a mixed
row is visible as such rather than inferred from the cards. Neither card
promotes a lower band, and neither compares a perspective row with an issue.

Each card is also a **filter** (`very_high_scope=only|mixed`, on both
`/summary` and `/issues`): clicking one lists exactly the issues it counts —
667 and 550 on the live store — and clicking it again clears the filter. While a
card is active only the list/total narrows; both cards keep the whole
population's split, so the number that was clicked stays beside the list it
produced. The scope is read from each issue's whole evidence, never from the
rows a band filter matched, and a lower band clears it (an every-perspective
Very High issue has no lower-band row, so the pair would always be empty).

### How the two screens reconcile

Quality Alerts evaluates every labelled perspective independently; Outlier
Diagnostics classifies against the single all-hospital detection baseline. A
stratified alert (governorate, ownership, …) can therefore be more severe than
the diagnostic row without either being wrong. The Outlier Diagnostics **Why**
popup carries a `cross_check` block that lists the stored alerts for the same
formula/month, states whether they agree, and names the reason when they do not
(including which perspective found the deviation).

The cross-check quotes the same **policy band** the Quality Alerts screen shows,
not the band the row was written with — otherwise Diagnostics re-quoted a
severity the other screen no longer presents (on the live store **408** open
alerts, all of them lowered by the thin-peer-group cap). Each perspective row
there reports `severity` (policy band), `stored_severity`, `severity_cap`,
`level_capped` and `capped_from`, and the popup names the cap that applied — a
no-dispersion comparison and a comparison group too small to measure a spread
are different facts and are not conflated in the explanation.

`POST /control/severity-preview` is the one reader still comparing against the
stored column: it answers "how many rows would change if I save these trend
settings?" from the stored base severity, so a row the caps would restate counts
as a change. That count is therefore an upper bound on the effect of the
proposed trend settings alone.

### Recalculation

Rows written before this policy keep their stored `NORMAL` verdict until the
month is re-analysed. `INSUFFICIENT_HISTORY` in the data is therefore itself a
marker of a post-policy row; the Why popup recomputes the current verdict from
the stored layer scores and reports `verified: false` with a "recalculate"
note when stored and current disagree.

## Provenance

### Diagnostics — `layered_outlier_results`

New JSON columns (migration
`e1f2a3b4c5d6_add_layered_comparison_provenance.py`):

`history_provenance`
```json
{"policy_version": "2026-10-24.1", "window": 12, "min_observations": 3,
 "months": ["2025-01", "..."], "values": [10.0, "..."],
 "skipped_months": ["2025-02"]}
```
`peer_provenance`
```json
{"policy_version": "2026-10-24.1", "group": "all_active_reporting",
 "month": "2026-01", "min_peers": 2, "scored_peer_count": 3,
 "eligible_count": 3, "peer_ids": [2, 3, 4],
 "values": {"2": 10.0, "3": 10.0, "4": 10.0}}
```

The existing Outlier Diagnostics list returns every table column, so these
fields are available without a new endpoint. Rows written before the migration
keep `NULL`: unknown provenance, not a claim that they were wrong.

### Quality Alerts — `quality_alerts.evidence["comparison_policy"]`

Each perspective row records:

```json
{"perspective_scope": "detection_baseline",
 "peer": {"policy_version": "...", "group": "all_active_reporting",
          "group_label": "All hospitals", "month": "2026-01",
          "min_peers": 2, "eligible_count": 3, "peer_ids": [2, 3, 4],
          "values": {"2": 10.0, "3": 10.0, "4": 10.0}}}
```

History rows carry the `history` block instead (window, minimum, months,
valid count, skipped months, method, and the configuration source). The Alerts
API exposes the object as `comparison_policy` on every perspective.

## Behaviour guarantees

* Identical inputs + same window/peer set produce the same score in both
  engines (regression-tested).
* Fewer eligible peers than the minimum yields a NULL peer layer, never a
  forced outlier; the eligible count remains visible.
* Historical-window boundaries and missing months are explicit and tested.
* Severity thresholds and score formulas were **not** changed. Only the
  window/eligibility policy and provenance were aligned.
* A scan cannot remove or modify a Diagnostics row, so a different window can
  never silently suppress the diagnostic result.

## Rollout

The migration only adds nullable columns; no backfill. Re-run Diagnostics for
months whose provenance matters (normal analysis / deep repair), and re-scan
Quality Alerts, to populate the new fields. Historical rows remain readable and
are reported as having unknown provenance rather than being treated as wrong.
