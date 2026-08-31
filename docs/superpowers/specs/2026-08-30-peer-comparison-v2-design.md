# Peer Comparison v2: Risk-Based Ranking + Scope Filtering

## Date
2026-08-30

## Status
Approved design (brainstorming complete)

## Problem
`compare_peers` (app/engine/comparative/advanced_comparison.py:128) ranks hospitals
**descending by `total_cases`** (sum of all indicator values for the month) and then
labels them via percentile thresholds as "متفوق / متوسط / يحتاج تحسين / حرج". This
confuses **volume** with **quality/risk**:

- A high-volume hospital gets ranked 1 and labelled "متفوق (Excellent)" even if it is
  statistically anomalous.
- A small hospital gets labelled "حرج (Critical)" merely for having low volume — not for
  being risky.

Additionally, the UI dropdown already offers `comparison_type` (`all` / `governorate` /
`type`) and the frontend sends it to the API, but the backend **ignores it entirely** —
the peer group is always all active hospitals. The peer scope is therefore non-functional.

## User-confirmed decisions (brainstorming)
1. **Criterion:** rank by the hospital's actual **`anomaly_score`** (from the smart-anomaly
   ensemble), not `total_cases`.
2. **Ascending-risk percentile:** the higher the number, the MORE risky. Rank 1 = most risky.
3. **Labels by risk level:** `critical` (حرج) / `high` (عالي) / `moderate` (متوسط) /
   `low` (منخفض), defined by risk-percentile thresholds.
4. **Scope functional:** activate `comparison_type` (all / same governorate / same type).

## Design

### 1. New metric and percentile

Data source: `run_smart_analytics(session, month).anomalies` -> map
`{hospital_id: (hospital_name, anomaly_score, governorate, hospital_type)}`.
Hospitals without data that month are excluded (as today).

Sort **descending by `anomaly_score`** (rank 1 = most risky). Secondary tie-break by
hospital name (deterministic alphabetical order).

Risk percentile (ascending-risk, so a taller bar = more risky):
```
risk_percentile = 100 * (total - rank + 1) / total
```
- Most risky (rank 1) -> 100
- Least risky -> smallest value

### 2. Risk-level labels (Arabic / English)

| risk_percentile | Arabic | English | UI level (badge) |
|---|---|---|---|
| >= 75 | حرج | critical | critical (red) |
| >= 50 | عالي | high | warning (orange) |
| >= 25 | متوسط | moderate | normal (green) |
| < 25 | منخفض | low | normal (green) |

Replaces the old Excel/Average/Needs-improvement/Critical mapping.

### 3. Scope filtering (comparison_type)

- `all`: all active hospitals with data that month.
- `governorate`: only hospitals whose `governorate` equals the reference hospital's
  `governorate`. Requires `hospital_id`; without it -> `[]`.
- `type`: only hospitals whose `hospital_type` equals the reference hospital's
  `hospital_type`. Requires `hospital_id`; without it -> `[]`.
- Reference hospital resolved via `session.query(Hospital).get(hospital_id)`. If not
  found / deleted -> `[]`.

### 4. PeerComparison dataclass + API

Add a new field `anomaly_score: float` to `PeerComparison` (for display).

`get_advanced_comparison` (app/api/comparative.py:27) serializes peers into
`peer_comparison`; add `"anomaly_score": p.anomaly_score` to each entry.

### 5. Reordering to avoid double analytics

`perform_advanced_comparison` currently runs `run_smart_analytics` inside the loop body
for historical months (perf issue, out of scope) and once more at line 80 for
`current_analytics`. Move `current_analytics = run_smart_analytics(session, month)` to
**before** `compare_peers` and pass `current_analytics` (or its `anomalies`) into
`compare_peers`, so the ranking reuses the already-computed anomalies instead of
re-reading `IndicatorValue` rows and re-running nothing extra.

Result: one `run_smart_analytics` call serves both the predictions AND the peer ranking.

### 6. Frontend

- `static/js/smart/report.js:12` `_LABEL_LEVELS`: add the new Arabic/English risk labels
  mapped to badge levels:
  - `حرج` / `critical` -> `critical`
  - `عالي` / `high` -> `warning`
  - `متوسط` / `moderate` -> `normal`
  - `منخفض` / `low` -> `normal`
- `renderComparison` (report.js:189): add an `anomaly_score` column to the peer table next
  to percentile. `_labelColor` / `_riskBadge(_labelToLevel(...))` already consume the
  comparison_label; the new levels map cleanly to the existing color logic.

### 7. Error/edge handling

- No hospitals with data that month -> `[]` -> frontend shows "No data" (already wired via
  `showSmartSectionEmpty`, report.js:224).
- Reference hospital not found -> `[]`.
- Scope group smaller than 2 -> `[]` (no comparison shown, UI shows "No data"); this is
  intentional.
- Tied anomaly scores -> deterministic name tie-break.

## Scope restriction
Only:
- `app/engine/comparative/advanced_comparison.py`
- `app/api/comparative.py`
- `static/js/smart/report.js`

Do NOT modify unrelated modules. Caching/performance improvements (#1) are explicitly
**out of scope** for this design and deferred.

## Testing (TDD — test first)
- Ascending-risk percentile: most risky -> 100, least risky -> smallest.
- Label thresholds at 25/50/75 -> critical/high/moderate/low.
- Scope filtering: `governorate` limited to reference governorate; `type` limited to
  reference type; no `hospital_id` with scope -> `[]`.
- Tie-break by name.
- API response includes `anomaly_score` per peer.
- Existing chart/peer tests remain green; old volume-based percentile expectations revised.

## Wording / statistical rules
- The peer rank reflects **relative risk position among the peer group** via
  `anomaly_score` — same statistical meaning as the anomaly-score section. It is a
  relative percentile, not an absolute diagnosis.
