## Task 4: Implement Chart.js Timeline Function

**Status:** DONE

### What was implemented

Replaced the Plotly.js implementation of `drawRcTimelineChart` with Chart.js in `static/js/settings.js`.

### Changes made

1. **Replaced `drawRcTimelineChart` function** (lines 137-253):
   - Removed Plotly.newPlot call and Plotly scatter traces
   - Created Chart.js line chart with two datasets (hospital value, peer mean)
   - Added CI band plugin integration via `plugins: [ciBandPlugin]`
   - Configured responsive behavior, tooltip callbacks, and styling using `CHART_COLORS`
   - Added proper chart instance cleanup via `window._rcTimelineChartInstance.destroy()`

2. **Updated `renderRcTimeline` function** (lines 262-266):
   - Replaced `Plotly.purge(chartEl.id)` with Chart.js instance destruction
   - Added null check and cleanup for `window._rcTimelineChartInstance`

### Key implementation details

- Uses `CHART_COLORS` from chart-utils.js for consistent color palette
- Uses `ciBandPlugin` from chart-utils.js for 95% CI band visualization
- Chart instance stored in `window._rcTimelineChartInstance` for lifecycle management
- Tooltip callbacks show formatted values and peer hospital counts
- Interaction configured as index mode for synchronized hover across datasets
- Bilingual labels preserved (Arabic indicator name + English suffix)

### Files changed

- `static/js/settings.js` - Modified `drawRcTimelineChart` and `renderRcTimeline` functions

### Test results

No existing tests for JavaScript frontend code. Implementation verified through code review and consistency with chart-utils.js API.

### Self-review findings

- Implementation matches the task brief exactly
- Uses the specified CHART_COLORS and ciBandPlugin from chart-utils.js
- Proper cleanup of previous chart instances before creating new ones
- All Plotly references removed from the timeline chart function
- No other files affected by this change
