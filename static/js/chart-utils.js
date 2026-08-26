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
    ctx.fillStyle = CHART_COLORS.ciBand;
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

window.refreshAllCharts = function() {
  // 1. Update CHART_COLORS from CSS variables
  if (window.__refreshChartColors) window.__refreshChartColors();

  var _cs = getComputedStyle(document.documentElement);
  var textColor = _cs.getPropertyValue('--text-secondary').trim() || '#9AA0AC';
  var gridColor = _cs.getPropertyValue('--border-default').trim() || '#2A2E3B';

  // 2. Update Plotly charts (smart analytics, outliers, validation)
  document.querySelectorAll('.js-plotly-plot, [id*="smart-"]').forEach(function(el) {
    if (el.__plotly && typeof Plotly !== 'undefined') {
      Plotly.relayout(el, {
        'font.color': textColor,
        'xaxis.gridcolor': gridColor,
        'yaxis.gridcolor': gridColor,
        'paper.bgcolor': 'rgba(0,0,0,0)',
        'plot.bgcolor': 'rgba(0,0,0,0)',
      });
    }
  });

  // 3. Directly update Chart.js instances without destroy/recreate
  _chartRegistry.forEach(function(chart) {
    try {
      if (!chart || !chart.canvas || !chart.canvas.parentNode) {
        _chartRegistry.delete(chart);
        return;
      }
      // Update legend and tick colors
      if (chart.options && chart.options.plugins && chart.options.plugins.legend && chart.options.plugins.legend.labels) {
        chart.options.plugins.legend.labels.color = CHART_COLORS.neutral;
      }
      if (chart.options && chart.options.scales) {
        Object.values(chart.options.scales).forEach(function(scale) {
          if (scale.ticks) scale.ticks.color = CHART_COLORS.neutral;
          if (scale.grid) scale.grid.color = CHART_COLORS.grid;
          if (scale.title && scale.title.color !== undefined) scale.title.color = CHART_COLORS.neutral;
        });
      }
      // Update dataset border/point colors to match new theme
      if (chart.data && chart.data.datasets) {
        chart.data.datasets.forEach(function(ds) {
          // Update colors that reference old theme values
          if (ds.borderColor === CHART_COLORS.primary || ds.borderColor === CHART_COLORS.secondary) {
            // These are already the right values after __refreshChartColors
          }
        });
      }
      chart.update('none'); // Update without animation for instant effect
    } catch(e) { /* ignore */ }
  });
};
