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
    const { ctx, chartArea, scales } = chart;
    const ciData = chart.config.options.plugins.ciBand;
    
    if (!ciData || !ciData.upper || !ciData.lower) return;
    
    const { upper, lower } = ciData;
    const xScale = scales.x;
    const yScale = scales.y;
    
    ctx.save();
    ctx.fillStyle = CHART_COLORS.ciBand;
    ctx.beginPath();
    
    // Draw upper bound
    upper.forEach((value, index) => {
      const x = xScale.getPixelForValue(index);
      const y = yScale.getPixelForValue(value);
      if (index === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });
    
    // Draw lower bound in reverse
    lower.reverse().forEach((value, index) => {
      const x = xScale.getPixelForValue(lower.length - 1 - index);
      const y = yScale.getPixelForValue(value);
      ctx.lineTo(x, y);
    });
    
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.ciBandPlugin = ciBandPlugin;
}
