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
  // Update CHART_COLORS from CSS variables
  if (window.__refreshChartColors) window.__refreshChartColors();
  // Update Plotly charts (smart analytics)
  document.querySelectorAll('.js-plotly-plot, [id*="smart-"]').forEach(el => {
    if (el.__plotly && typeof Plotly !== 'undefined') {
      const textColor = getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim() || '#94a3b8';
      const gridColor = getComputedStyle(document.documentElement).getPropertyValue('--border-default').trim() || '#334155';
      Plotly.relayout(el, {
        'font.color': textColor,
        'xaxis.gridcolor': gridColor,
        'yaxis.gridcolor': gridColor,
        'paper.bgcolor': 'rgba(0,0,0,0)',
        'plot.bgcolor': 'rgba(0,0,0,0)',
      });
    }
  });
  // Destroy and recreate Chart.js instances with new colors
  _chartRegistry.forEach(chart => {
    try {
      if (chart && chart.canvas && chart.canvas.parentNode) {
        const canvas = chart.canvas;
        const parent = chart.canvas.parentNode;
        const id = chart.canvas.id;
        chart.destroy();
        _chartRegistry.delete(chart);
        // Dispatch event so owners can recreate
        const evt = new CustomEvent('chartThemeChanged', { detail: { id, parent } });
        document.dispatchEvent(evt);
      }
    } catch(e) { /* ignore */ }
  });
};
