// Theme-aware CSS variable reader
function getCSSVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Chart color palette - reads from CSS design tokens
function getChartColors() {
  return {
    primary: getCSSVar('--accent-teal'),
    secondary: getCSSVar('--accent-purple'),
    accent: getCSSVar('--accent-red'),
    warning: getCSSVar('--accent-orange'),
    success: getCSSVar('--accent-green'),
    neutral: getCSSVar('--text-secondary'),
    background: getCSSVar('--bg-surface'),
    grid: getCSSVar('--border-default'),
    ciBand: getCSSVar('--severity-info-bg'),
  };
}

// Global mutable reference updated on theme change
const CHART_COLORS = getChartColors();
window.__refreshChartColors = function() {
  Object.assign(CHART_COLORS, getChartColors());
};

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.CHART_COLORS = CHART_COLORS;
}

// Custom plugin for 95% confidence interval band
const ciBandPlugin = {
  id: 'ciBand',
  beforeDraw(chart) {
    const { ctx, scales } = chart;
    const ciData = chart.config.options.plugins.ciBand;
    
    if (!ciData || !ciData.upper || !ciData.lower) return;
    if (!scales || !scales.x || !scales.y) return;
    
    const upper = ciData.upper;
    const lower = ciData.lower;
    const xScale = scales.x;
    const yScale = scales.y;
    
    // Filter out null/undefined values
    const validIndices = [];
    for (let i = 0; i < upper.length; i++) {
      if (upper[i] != null && lower[i] != null) {
        validIndices.push(i);
      }
    }
    
    if (validIndices.length < 2) return;
    
    ctx.save();
    ctx.fillStyle = getCSSVar('--severity-info-bg') || CHART_COLORS.ciBand;
    ctx.beginPath();
    
    // Draw upper bound
    validIndices.forEach((index, i) => {
      const x = xScale.getPixelForValue(index);
      const y = yScale.getPixelForValue(upper[index]);
      if (i === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });
    
    // Draw lower bound in reverse
    for (let i = validIndices.length - 1; i >= 0; i--) {
      const index = validIndices[i];
      const x = xScale.getPixelForValue(index);
      const y = yScale.getPixelForValue(lower[index]);
      ctx.lineTo(x, y);
    }
    
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.ciBandPlugin = ciBandPlugin;
}

// ── Chart Registry: tracks all Chart.js instances for theme refresh ──────
const _chartRegistry = new Set();

window.registerChart = function(chartInstance) {
  _chartRegistry.add(chartInstance);
};

window.unregisterChart = function(chartInstance) {
  _chartRegistry.delete(chartInstance);
};

var _refreshDebounce = null;

window.refreshAllCharts = function() {
  // Debounce: collapse rapid consecutive calls (e.g. theme toggle + DOM updates)
  if (_refreshDebounce) clearTimeout(_refreshDebounce);
  _refreshDebounce = setTimeout(function() {
    _refreshDebounce = null;
    _doRefreshAllCharts();
  }, 120);
};

function _doRefreshAllCharts() {
  // 1. Update CHART_COLORS from CSS variables
  if (window.__refreshChartColors) window.__refreshChartColors();

  var _cs = getComputedStyle(document.documentElement);
  var textColor = _cs.getPropertyValue('--text-secondary').trim() || '#9AA0AC';
  var gridColor = _cs.getPropertyValue('--border-default').trim() || '#2A2E3B';
  var primaryColor = CHART_COLORS.primary || '#14b8a6';
  var secondaryColor = CHART_COLORS.secondary || '#8b5cf6';
  var warningColor = CHART_COLORS.warning || '#f59e0b';
  var successColor = CHART_COLORS.success || '#22c55e';
  var surfaceColor = getCSSVar('--bg-surface') || '#1A1D27';
  var elevatedColor = getCSSVar('--bg-elevated') || '#1e293b';

  // 2. Update Plotly charts — font, grid, backgrounds, and trace colors
  document.querySelectorAll('.js-plotly-plot').forEach(function(el) {
    if (typeof Plotly === 'undefined' || !el.data) return;
    try {
      // Update layout (font, grid, background)
      Plotly.relayout(el, {
        'font.color': textColor,
        'paper.bgcolor': 'rgba(0,0,0,0)',
        'plot.bgcolor': 'rgba(0,0,0,0)',
      });
      // Update grid colors on all axes
      var updateAxes = {};
      el.data.forEach(function(trace, i) {
        if (trace.xaxis) updateAxes[trace.xaxis + '.gridcolor'] = gridColor;
        if (trace.yaxis) updateAxes[trace.yaxis + '.gridcolor'] = gridColor;
      });
      if (Object.keys(updateAxes).length) Plotly.relayout(el, updateAxes);
    } catch(e) { /* ignore */ }
  });

  // 3. Update Chart.js instances
  _chartRegistry.forEach(function(chart) {
    try {
      if (!chart || !chart.canvas || !chart.canvas.parentNode) {
        _chartRegistry.delete(chart);
        return;
      }
      // Update legend
      if (chart.options && chart.options.plugins && chart.options.plugins.legend && chart.options.plugins.legend.labels) {
        chart.options.plugins.legend.labels.color = CHART_COLORS.neutral;
      }
      // Update scales (axes, grid, ticks, titles)
      if (chart.options && chart.options.scales) {
        Object.values(chart.options.scales).forEach(function(scale) {
          if (scale.ticks) scale.ticks.color = CHART_COLORS.neutral;
          if (scale.grid) scale.grid.color = CHART_COLORS.grid;
          if (scale.title && scale.title.color !== undefined) scale.title.color = CHART_COLORS.neutral;
        });
      }
      // Update tooltip
      if (chart.options && chart.options.plugins && chart.options.plugins.tooltip) {
        chart.options.plugins.tooltip.backgroundColor = elevatedColor;
        chart.options.plugins.tooltip.titleFont = chart.options.plugins.tooltip.titleFont || {};
        chart.options.plugins.tooltip.titleFont.color = getCSSVar('--text-primary') || '#e5e7eb';
        chart.options.plugins.tooltip.bodyFont = chart.options.plugins.tooltip.bodyFont || {};
        chart.options.plugins.tooltip.bodyFont.color = getCSSVar('--text-secondary') || '#9ca3af';
      }
      // Update dataset colors
      if (chart.data && chart.data.datasets) {
        var colorMap = {
          primary: primaryColor, secondary: secondaryColor,
          accent: CHART_COLORS.accent, warning: warningColor, success: successColor
        };
        chart.data.datasets.forEach(function(ds, i) {
          var role = ds._colorRole || (i === 0 ? 'primary' : i === 1 ? 'secondary' : 'success');
          var newColor = colorMap[role] || primaryColor;
          if (ds.borderColor) ds.borderColor = newColor;
          if (ds.backgroundColor && ds.backgroundColor !== 'transparent' && ds.backgroundColor !== 'rgba(0,0,0,0)') {
            ds.backgroundColor = newColor;
          }
          if (ds.pointBackgroundColor) ds.pointBackgroundColor = newColor;
        });
      }
      chart.update('none');
    } catch(e) { /* ignore */ }
  });
}

// ── MutationObserver: auto-refresh charts when data-theme changes ──────
if (typeof MutationObserver !== 'undefined') {
  var _themeObserver = new MutationObserver(function(mutations) {
    for (var i = 0; i < mutations.length; i++) {
      if (mutations[i].attributeName === 'data-theme') {
        if (window.refreshAllCharts) window.refreshAllCharts();
        break;
      }
    }
  });
  _themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
}
