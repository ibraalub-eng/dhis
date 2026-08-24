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
