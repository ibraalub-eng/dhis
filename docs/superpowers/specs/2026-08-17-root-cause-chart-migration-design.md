# Root Cause Chart Migration Design: Plotly.js to Chart.js

**Date:** 2026-08-17
**Status:** Approved
**Author:** AI Assistant

---

## Overview

Migrate the root cause analysis timeline chart from Plotly.js to Chart.js with improved colors and design. This is a direct migration approach (Approach 1) focusing on visual improvement while maintaining existing functionality.

---

## Current State

### Timeline Chart Implementation
- **Library:** Plotly.js (~3MB)
- **Location:** `static/js/settings.js` (functions: `drawRcTimelineChart`, `renderRcTimeline`, `renderRcTimelineChart`)
- **HTML:** `static/tabs/root-cause.html` (element: `rcTimelineChart`)
- **Data Source:** `/root-cause/{hospital_id}/timeline` API endpoint
- **Features:**
  - Line chart with hospital value (solid teal) and peer average (dashed purple)
  - 95% confidence interval band (scatter fill)
  - Responsive design
  - Basic tooltips

### Current Limitations
1. Heavy library affects page load time
2. Complex API for simple line chart
3. Limited customization control
4. Basic tooltip functionality

---

## Design: Unified Color Palette

### Color System
```javascript
const CHART_COLORS = {
  primary: '#0d9488',      // Teal - hospital value line
  secondary: '#7c3aed',    // Purple - peer average line
  accent: '#c62828',       // Red - critical severity
  warning: '#e65100',      // Orange - high/medium severity
  success: '#2e7d32',      // Green - good status
  neutral: '#64748b',      // Gray - text and borders
  background: '#f8fafc',   // Light gray - chart background
  grid: '#e2e8f0',        // Light gray - grid lines
  ciBand: 'rgba(124,58,237,0.12)', // Purple with opacity - CI band
};
```

### Typography
- Chart labels: 10px, `#64748b`
- Chart titles: 12px, `#374151`, bold
- Tooltips: 11px, white on `#1e293b` background
- Legend: 10px, `#64748b`

### Spacing & Borders
- Chart padding: 16px
- Element spacing: 8px
- Border radius: 6px
- Grid line width: 1px

---

## Design: Timeline Chart Migration

### Architecture
```
Current: Plotly.js → Complex API → Custom rendering
New: Chart.js → Simple API → Standard rendering
```

### Implementation Details

#### 1. Chart.js Configuration
```javascript
const timelineChart = new Chart(ctx, {
  type: 'line',
  data: {
    labels: months,
    datasets: [
      {
        label: 'Hospital Value',
        data: hospitalValues,
        borderColor: CHART_COLORS.primary,
        backgroundColor: CHART_COLORS.primary,
        borderWidth: 2.5,
        pointRadius: 5,
        pointHoverRadius: 7,
        tension: 0.3,
        fill: false,
      },
      {
        label: 'Peer Average',
        data: peerValues,
        borderColor: CHART_COLORS.secondary,
        backgroundColor: CHART_COLORS.secondary,
        borderWidth: 2,
        borderDash: [5, 5],
        pointRadius: 4,
        pointHoverRadius: 6,
        tension: 0.3,
        fill: false,
      }
    ]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top',
        labels: {
          font: { size: 10 },
          color: CHART_COLORS.neutral,
          usePointStyle: true,
        }
      },
      tooltip: {
        backgroundColor: '#1e293b',
        titleFont: { size: 11 },
        bodyFont: { size: 11 },
        padding: 12,
        cornerRadius: 6,
        callbacks: {
          title: function(items) {
            return items[0].label;
          },
          label: function(context) {
            const label = context.dataset.label || '';
            const value = context.parsed.y;
            return label + ': ' + value.toFixed(1);
          },
          afterBody: function(items) {
            const peerCount = getPeerCountForMonth(items[0].label);
            return peerCount ? 'Peer hospitals: ' + peerCount : '';
          }
        }
      }
    },
    scales: {
      x: {
        grid: { color: CHART_COLORS.grid },
        ticks: { color: CHART_COLORS.neutral, font: { size: 10 } }
      },
      y: {
        grid: { color: CHART_COLORS.grid },
        ticks: { color: CHART_COLORS.neutral, font: { size: 10 } },
        beginAtZero: false,
      }
    },
    interaction: {
      intersect: false,
      mode: 'index'
    }
  }
});
```

#### 2. 95% Confidence Interval Band
- Use custom Chart.js plugin to render CI band
- Create filled area between upper and lower bounds
- Render as semi-transparent purple area (`rgba(124,58,237,0.12)`)
- Only show for months with valid peer data (non-null bounds)
- Plugin will be implemented as a local utility function

#### 3. Enhanced Tooltips
- Show month name (full format)
- Display hospital value and peer average
- Include peer count for context
- Show confidence interval range when available

#### 4. Interactive Features
- Hover effects with larger points
- Toggle datasets via legend clicks
- Smooth animations on data load

---

## Design: Sparklines & Visual Elements

### Sparklines (Out of Scope)
- Current SVG sparklines will remain unchanged in this migration
- Future improvement: Replace with Chart.js mini line charts
- Focus of this migration is timeline chart only

### Progress Bars
- Animated transitions (0.3s ease)
- Gradient backgrounds for visual appeal
- Consistent height (6px) and border radius (3px)

### Card Styling
- Subtle gradient backgrounds
- Improved shadow effects
- Consistent border radius (8px)
- Better spacing between elements

---

## Implementation Plan

### Scope
This migration focuses specifically on:
1. Replacing Plotly.js with Chart.js for the timeline chart
2. Updating colors to match unified color palette
3. Improving tooltip functionality
4. Maintaining all existing functionality

### Out of Scope
- Sparkline replacement (will remain as SVG)
- Progress bar improvements (minor visual changes only)
- Card styling improvements (future enhancement)

### Files to Modify
1. **`static/js/settings.js`**
   - Remove Plotly.js dependency
   - Add Chart.js configuration
   - Update `drawRcTimelineChart()` function
   - Implement custom CI band plugin

2. **`static/tabs/root-cause.html`**
   - Update chart container styling
   - Replace Plotly.js CDN with Chart.js CDN

3. **`static/js/app.js`**
   - Update imports if needed

### Dependencies
- **Remove:** Plotly.js CDN link
- **Add:** Chart.js CDN (v4.x)
- **Implement:** Custom CI band plugin (local utility)

### Testing
1. Verify chart renders correctly with sample data
2. Test responsive behavior on different screen sizes
3. Verify tooltip functionality
4. Test legend toggle functionality
5. Verify color consistency with design system
6. Test CI band rendering with valid/invalid data

---

## Success Criteria

1. ✅ Timeline chart renders correctly with Chart.js
2. ✅ Colors match unified color palette (teal for hospital, purple for peer)
3. ✅ Tooltips show month, values, and peer count
4. ✅ Responsive on mobile and desktop
5. ✅ Performance improvement (faster load time than Plotly.js)
6. ✅ No regression in existing functionality
7. ✅ CI band renders correctly for months with valid data
8. ✅ Legend toggle works to show/hide datasets

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| CI band rendering complexity | Medium | Use Chart.js fill-between plugin or custom solution |
| Tooltip customization | Low | Chart.js has extensive tooltip API |
| Performance regression | Low | Chart.js is lighter than Plotly.js |
| Mobile responsiveness | Low | Chart.js has built-in responsive support |

---

## Next Steps

1. Create detailed implementation plan with task breakdown
2. Set up Chart.js in the project (CDN or npm)
3. Implement custom CI band plugin
4. Migrate timeline chart from Plotly.js to Chart.js
5. Test with sample data and refine
6. Update documentation and commit changes
