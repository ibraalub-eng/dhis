# Task 9 Report: CSV Export for Outlier and Rule-Failure Tabs

## What I Implemented

Added client-side CSV export functionality to the outlier analysis and rule-failure tabs in `static/js/outliers.js`.

### Changes Made

**`static/js/outliers.js`**
- Added `downloadCSV(filename, headers, rows)` utility — generates a CSV Blob with BOM prefix (`\ufeff` for Excel/Arabic compatibility), creates a temporary download link, and triggers the browser download.
- Added `todayStr()` helper to format today's date as `YYYY-MM-DD`.
- Added `exportOutliersCSV()` — reads from `window._lastOutlierData`, maps data fields (Hospital, Month, Indicator, Z-Score, Severity, Features), downloads as `outliers_YYYY-MM-DD.csv`.
- Added `exportRuleFailuresCSV()` — reads from `window._lastRuleFailureData`, maps data fields (Hospital, Rule Code, Description, Severity, Indicator, Failed Months), downloads as `rule_failures_YYYY-MM-DD.csv`.
- Added `window._lastOutlierData = anomalies` in ML mode of `loadOutliers()`.
- Added `window._lastOutlierData = data` in `updateOutlierUI()` (statistical mode).
- Added `window._lastRuleFailureData = data` in `updateRuleFailUI()`.

**`static/js/app.js`**
- Imported `exportOutliersCSV` and `exportRuleFailuresCSV` from `outliers.js`.
- Attached both to `window` for `onclick` handlers.

**`static/tabs/outliers.html`**
- Added "Export CSV" button next to the outlier count/loading indicator.

**`static/tabs/alerts.html`**
- Added "Export CSV" button next to the rule-failure summary pills.

### Button Styling
Both buttons use dark theme styling:
- `background: var(--bg-surface-hover)`
- `color: var(--text-primary)`
- `border: 1px solid var(--border-default)`

## Tests

- **Command:** `python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short`
- **Result:** 72 passed, 0 failed (5164 warnings — all pre-existing deprecation warnings)

## Files Changed
1. `static/js/outliers.js` — CSV export functions + data storage
2. `static/js/app.js` — import + window attachment
3. `static/tabs/outliers.html` — Export CSV button
4. `static/tabs/alerts.html` — Export CSV button

## Concerns
None. All changes are client-side only with no backend modifications. The BOM prefix ensures proper UTF-8 handling for Arabic text in Excel.
