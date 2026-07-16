### Task 5 Report: Frontend — Dashboard JS

**Status:** DONE

**Changes:**
- `static/js/settings.js`:
  - Added `renderSparkline()` helper after `renderKpiCards` (line 318)
  - Added ranking table: `rankingData`, `rankingSortCol/Asc` state vars, `loadRankingTable()` (exported), `renderRankingTable()`, sort click handler
  - Added scorecard: `showHospitalScorecard()` (exported), `closeScorecard()` (exported) with Chart.js trend/bar charts and alerts list
  - Modified `loadDashboard()`: added sparkline rendering after summary cards, added `loadRankingTable()` call after `loadHeatmap()`

- `static/js/app.js`:
  - Added `loadRankingTable`, `showHospitalScorecard`, `closeScorecard` to settings.js import (line 8)
  - Added `window.loadRankingTable`, `window.showHospitalScorecard`, `window.closeScorecard` assignments (lines 64-66)

**Verification:**
- No duplicate imports of `esc` or `apiGet` (already present in settings.js)
- No duplicate imports in app.js
- All exported functions properly wired to window globals for onclick handlers
- Code follows existing conventions (indentation, `apiGet` pattern, Chart.js usage)

**Concerns:** None
