// hospital.js — hospital-scope mode: trend, forecast, drilldown, root cause.
import { smartState, apiSmartGet, setSmartLoader, showSmartSectionError,
         showSmartSectionEmpty, _smartEscapeHtml, _t, _fmtNum, _riskBadge, smartTranslateFeature } from './core.js';
import { renderPlot, makeLineChart, renderWaterfall } from './charts.js';

export function initHospitalSelect(hospitals) {
  const select = document.getElementById('smart-hospital-context-select');
  const monthlySelect = document.getElementById('smart-hospital-select');
  if (select) {
    select.innerHTML = '<option value="">-- ' + _t('Select Hospital') + ' --</option>' +
      hospitals.map(h => `<option value="${h.id}">${_smartEscapeHtml(h.name)}</option>`).join('');
  }
  if (monthlySelect && monthlySelect.options.length === 1) {
    monthlySelect.innerHTML = '<option value="">-- ' + _t('All Hospitals') + ' --</option>' +
      hospitals.map(h => `<option value="${h.id}">${_smartEscapeHtml(h.name)}</option>`).join('');
  }
}

export async function loadHospitalMode(hospitalId, months) {
  const panel = document.getElementById('smart-hospital-panel');
  if (!panel) return;
  setSmartLoader('hospital', true);
  try {
    const trend = await apiSmartGet(`/smart/trend/${hospitalId}`);
    if (!trend.hospital_name) { showSmartSectionEmpty('hospital', _t('No data for this hospital')); return; }
    document.getElementById('smart-hospital-name').textContent = trend.hospital_name;
    renderTrend(trend);

    const drill = await apiSmartGet(`/smart/drilldown/${hospitalId}/all`);
    if (!drill.empty) {
      const forecast = drill.forecast || {};
      renderHospitalForecast(forecast);
      renderHospitalFactors(drill.anomaly, drill.explanation);
    } else {
      showSmartSectionEmpty('hospital', drill.message || _t('No data'));
    }
  } catch (e) {
    showSmartSectionError('hospital', e.message);
  } finally {
    setSmartLoader('hospital', false);
  }
}

export function renderTrend(trend) {
  const months = trend.trend.map(t => t.month);
  const scores = trend.trend.map(t => t.anomaly_score);
  const colors = trend.trend.map(t => t.severity === 'critical' ? '#ef4444' : t.severity === 'warning' ? '#f59e0b' : '#22c55e');
  renderPlot('smart-hospital-trend', [{
    x: months, y: scores, type: 'scatter', mode: 'lines+markers',
    line: { color: '#4338ca', width: 2.5 }, marker: { color, size: 8 },
    text: trend.trend.map(t => _t(t.severity)),
  }], { title: _t('Anomaly score over time'), yaxis: { range: [0, 1] } });
}

export function renderHospitalForecast(forecast) {
  const c = document.getElementById('smart-hospital-forecast');
  if (!c) return;
  const forecasts = forecast.forecasts || forecast.forecast || [];
  if (!forecasts.length) { c.innerHTML = `<div class="smart-empty-state">${_t('No forecast available')}</div>`; return; }
  c.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
    <th>${_t('Month')}</th><th>${_t('Predicted score')}</th><th>${_t('Range')}</th></tr></thead><tbody>` +
    forecasts.map(f => `<tr><td>${_smartEscapeHtml(f.month)}</td>
      <td>${_fmtNum(f.prediction, 3)}</td>
      <td style="font-size:0.75rem;">${_fmtNum(f.lower, 3)} – ${_fmtNum(f.upper, 3)}</td></tr>`).join('') +
    `</tbody></table></div>`;
}

export function renderHospitalFactors(anomaly, explanation) {
  const c = document.getElementById('smart-hospital-factors');
  if (!c) return;
  const factors = explanation?.top_factors || [];
  c.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
    <th>${_t('Factor')}</th><th>${_t('Value')}</th><th>${_t('SHAP')}</th></tr></thead><tbody>` +
    factors.map(f => `<tr><td>${_smartEscapeHtml(smartTranslateFeature(f.feature))}</td>
      <td>${_fmtNum(f.value, 3)}</td><td>${_fmtNum(f.shap_value, 3)}</td></tr>`).join('') +
    `</tbody></table></div>`;
  if (factors.length) renderWaterfall('smart-shap-waterfall', factors);
}

export function openDrilldown(hospitalId) {
  const month = smartState.month || '';
  const modal = document.getElementById('smart-drilldown-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  apiSmartGet(`/smart/drilldown/${hospitalId}/${month}`).then(d => {
    if (d.empty || !d.anomaly) {
      document.getElementById('smart-drilldown-name').textContent = d.hospital_name || hospitalId;
      document.getElementById('smart-drilldown-text').textContent = d.message || _t('No data');
      return;
    }
    document.getElementById('smart-drilldown-name').textContent = d.hospital_name;
    document.getElementById('smart-drilldown-text').textContent = d.explanation?.text_ar || d.explanation?.text || '';
    const residuals = d.residuals || [];
    if (residuals.length) renderPlot('smart-trend-line', [{
      x: residuals.map(r => r.month), y: residuals.map(r => r.residual),
      type: 'bar', marker: { color: residuals.map(r => r.residual > 0 ? '#ef4444' : '#3b82f6') },
    }], { title: _t('Monthly residuals') });
    renderHospitalFactors(d.anomaly, d.explanation);
  }).catch(e => {
    document.getElementById('smart-drilldown-text').textContent = e.message;
  });
}

export function goRootCause(hospitalId, month) {
  // Root-cause navigation: switch to hospital mode and load the hospital.
  const btn = document.querySelector('.smart-mode-btn[data-smart-mode="hospital"]');
  if (btn) btn.click();
  const select = document.getElementById('smart-hospital-context-select');
  if (select && select.querySelector(`option[value="${hospitalId}"]`)) {
    select.value = String(hospitalId);
    select.dispatchEvent(new Event('change'));
  }
}

// Exposed for inline onclick attributes (kept for backward compatibility).
window.smartDrilldown = openDrilldown;
window.smartGoRootCause = goRootCause;