// charts.js — Plotly wrappers shared by all smart-analytics renderers.
import { SMART_COLORS } from './core.js';

const ARABIC_DIGITS = ['٠', '١', '٢', '٣', '٤', '٥', '٦', '٧', '٨', '٩'];
export function formatArabicDigits(value) {
  return String(value).replace(/[0-9]/g, d => ARABIC_DIGITS[+d]);
}

export const smartChartTheme = {
  font: { family: 'Segoe UI, Tahoma, Arial, sans-serif', size: 12 },
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
  margin: { l: 46, r: 16, t: 36, b: 44 },
  hoverlabel: { align: 'left' },
  legend: { orientation: 'h', y: -0.18, x: 0.5, xanchor: 'center' },
};

export function renderPlot(divId, data, layout, options) {
  const el = document.getElementById(divId);
  if (!el) return;
  Plotly.react(el, data, Object.assign({}, smartChartTheme, layout || {}), Object.assign({ responsive: true, displaylogo: false }, options || {}));
}

export function makeLineChart(divId, x, y, name, opts = {}) {
  renderPlot(divId, [{
    x, y, name, type: 'scatter', mode: 'lines+markers',
    line: { color: opts.color || SMART_COLORS.warning, width: 2.5, shape: opts.shape || 'linear' },
    marker: { size: opts.size || 5 },
  }], { title: opts.title || '', yaxis: { title: opts.yTitle || '' }, xaxis: { title: opts.xTitle || '' } });
}

export function makeBarChart(divId, labels, values, opts = {}) {
  const color = opts.colors || Array(labels.length).fill(SMART_COLORS.warning);
  renderPlot(divId, [{ x: labels, y: values, type: 'bar', marker: { color } }],
    { title: opts.title || '', yaxis: { title: opts.yTitle || '' } });
}

export function makeScatter(divId, traces, opts = {}) {
  renderPlot(divId, traces.map(t => Object.assign({ type: 'scatter', mode: 'markers' }, t)),
    { title: opts.title || '', xaxis: { title: opts.xTitle || '' }, yaxis: { title: opts.yTitle || '' } });
}

export function makeHeatmap(divId, z, x, y, opts = {}) {
  renderPlot(divId, [{ z, x, y, type: 'heatmap', colorscale: opts.colorscale || 'RdBu', zmid: opts.zmid ?? 0 }],
    { title: opts.title || '', xaxis: { tickangle: -45 } });
}

export function makeDonut(divId, labels, values, opts = {}) {
  renderPlot(divId, [{
    labels, values, type: 'pie', hole: 0.55,
    marker: { colors: opts.colors || Object.values(SMART_COLORS.clusters) },
    textinfo: 'label+percent',
  }], { title: opts.title || '', showlegend: opts.showlegend !== false });
}

export function renderWaterfall(divId, factors, opts = {}) {
  // SHAP waterfall: horizontal bars from negative to positive around 0.
  const names = factors.map(f => f.arabic_label || f.feature);
  const values = factors.map(f => f.shap_value || 0);
  renderPlot(divId, [{
    x: values, y: names, type: 'bar', orientation: 'h',
    marker: { color: values.map(v => v >= 0 ? SMART_COLORS.shap_positive : SMART_COLORS.shap_negative) },
    text: values.map(v => v.toFixed(3)),
  }], { title: opts.title || 'SHAP', xaxis: { title: 'SHAP value' }, margin: { l: 140, r: 16, t: 36, b: 40 } });
}