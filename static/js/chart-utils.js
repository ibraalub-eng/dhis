// Chart color palette - unified design system
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
