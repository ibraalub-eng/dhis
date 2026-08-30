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

    const drill = await apiSmartGet(`/smart/drilldown/${hospitalId}/all`);
    if (drill.empty && !drill.anomaly) {
      showSmartSectionEmpty('hospital', drill.message || _t('No data'));
      return;
    }

    renderHospitalProfile(drill);
    renderHospitalGauges(drill);
    renderTrend(trend);
    renderHospitalIndicators(drill.indicators || []);
    renderHospitalPeers(drill.peer_comparison || {}, drill.anomaly);
    const forecast = drill.forecast || {};
    renderHospitalForecast(forecast);
    renderHospitalFactors(drill.anomaly, drill.explanation);
  } catch (e) {
    showSmartSectionError('hospital', e.message);
  } finally {
    setSmartLoader('hospital', false);
  }
}

function renderHospitalProfile(drill) {
  const el = document.getElementById('smart-hospital-profile');
  if (!el) return;
  const meta = drill.metadata || {};
  const score = drill.anomaly?.anomaly_score;
  const severity = drill.anomaly?.severity || 'normal';
  const sevColor = severity === 'critical' ? 'var(--accent-red)' : severity === 'warning' ? 'var(--accent-orange)' : 'var(--accent-green)';
  el.style.display = 'block';
  el.innerHTML = `
    <div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap;">
      <div style="font-size:1.1rem;font-weight:700;color:var(--text-primary);">${_smartEscapeHtml(drill.hospital_name)}</div>
      <span style="padding:2px 10px;border-radius:12px;font-size:0.75rem;font-weight:600;color:#fff;background:${sevColor};">${_t(severity)}</span>
      ${score != null ? `<span style="font-size:0.8rem;color:var(--text-muted);">Score: ${_fmtNum(score, 3)}</span>` : ''}
    </div>
    <div style="display:flex;gap:1rem;flex-wrap:wrap;margin-top:0.5rem;font-size:0.8rem;color:var(--text-secondary);">
      ${meta.governorate ? `<span>📍 ${_smartEscapeHtml(meta.governorate)}</span>` : ''}
      ${meta.hospital_type ? `<span>🏥 ${_smartEscapeHtml(meta.hospital_type)}</span>` : ''}
      ${meta.facility_ownership ? `<span>🏢 ${_smartEscapeHtml(meta.facility_ownership)}</span>` : ''}
      ${meta.facility_type ? `<span>🏗️ ${_smartEscapeHtml(meta.facility_type)}</span>` : ''}
      ${meta.organisation_unit_id ? `<span style="color:var(--text-muted);">ID: ${meta.organisation_unit_id}</span>` : ''}
    </div>
  `;
}

function renderHospitalGauges(drill) {
  const el = document.getElementById('smart-hospital-gauges');
  if (!el) return;
  const q = drill.quality || {};
  const c = drill.confidence;
  if (!q.score && c == null) { el.style.display = 'none'; return; }
  el.style.display = 'grid';
  const items = [];
  if (q.score != null) items.push({ label: _t('Quality'), value: q.score, max: 100, color: 'var(--accent-blue)' });
  if (c != null) items.push({ label: _t('Confidence'), value: c, max: 100, color: 'var(--accent-teal)' });
  if (q.completeness != null) items.push({ label: _t('Completeness'), value: q.completeness, max: 100, color: 'var(--accent-green)' });
  if (q.consistency != null) items.push({ label: _t('Consistency'), value: q.consistency, max: 100, color: 'var(--accent-orange)' });
  if (q.rule_compliance != null) items.push({ label: _t('Rule Compliance'), value: q.rule_compliance, max: 100, color: '#7b1fa2' });
  el.innerHTML = items.map(it => {
    const pct = Math.min(100, Math.max(0, it.value));
    const barColor = pct >= 80 ? 'var(--accent-green)' : pct >= 60 ? 'var(--accent-orange)' : 'var(--accent-red)';
    return `<div style="background:var(--bg-surface);border-radius:8px;padding:0.6rem 0.8rem;border:1px solid var(--border-default);">
      <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:0.2rem;">${it.label}</div>
      <div style="font-size:1.1rem;font-weight:700;color:var(--text-primary);">${_fmtNum(it.value, 1)}%</div>
      <div style="height:4px;background:var(--bg-elevated);border-radius:2px;margin-top:0.3rem;overflow:hidden;">
        <div style="height:100%;width:${pct}%;background:${barColor};border-radius:2px;transition:width 0.5s ease;"></div>
      </div>
    </div>`;
  }).join('');
}

export function renderTrend(trend) {
  const months = trend.trend.map(t => t.month);
  const scores = trend.trend.map(t => t.anomaly_score);
  const colors = trend.trend.map(t => t.severity === 'critical' ? '#ef4444' : t.severity === 'warning' ? '#f59e0b' : '#22c55e');
  const textColor = getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#1a1a2e';
  renderPlot('smart-hospital-trend', [{
    x: months, y: scores, type: 'scatter', mode: 'lines+markers',
    line: { color: '#4338ca', width: 2.5 }, marker: { color: colors, size: 8 },
    text: trend.trend.map(t => _t(t.severity)),
  }], { title: { text: _t('Anomaly score over time'), font: { color: textColor, size: 13 } }, yaxis: { range: [0, 1] }, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)' });
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

function renderHospitalIndicators(indicators) {
  const c = document.getElementById('smart-hospital-indicators');
  if (!c || !indicators.length) { if (c) c.innerHTML = ''; return; }
  c.innerHTML = `<div style="font-size:0.85rem;font-weight:600;color:var(--text-primary);margin-bottom:0.4rem;">📊 ${_t('Clinical Indicators')}</div>
  <div class="smart-table-wrap"><table><thead><tr>
    <th>${_t('Indicator')}</th><th>${_t('Value')}</th><th>${_t('Peer Avg')}</th><th>${_t('vs Peers')}</th></tr></thead><tbody>` +
    indicators.map(ind => {
      const val = ind.value != null ? _fmtNum(ind.value, 3) : '—';
      const peer = ind.peer_avg != null ? _fmtNum(ind.peer_avg, 3) : '—';
      let diff = '';
      if (ind.value != null && ind.peer_avg != null) {
        const d = ind.value - ind.peer_avg;
        const pct = ind.peer_avg !== 0 ? ((d / ind.peer_avg) * 100).toFixed(1) : '—';
        const color = d > 0 ? 'var(--accent-red)' : d < 0 ? 'var(--accent-green)' : 'var(--text-muted)';
        const arrow = d > 0 ? '↑' : d < 0 ? '↓' : '→';
        diff = `<span style="color:${color};font-weight:600;">${arrow} ${pct}%</span>`;
      }
      return `<tr><td>${_smartEscapeHtml(ind.indicator_name)}</td><td>${val}</td><td>${peer}</td><td>${diff}</td></tr>`;
    }).join('') +
    `</tbody></table></div>`;
}

function renderHospitalPeers(peers, anomaly) {
  const c = document.getElementById('smart-hospital-peers');
  if (!c) return;
  if (!peers.peer_count) { c.innerHTML = ''; return; }
  const myScore = anomaly?.anomaly_score ?? null;
  const peerAvg = peers.peer_avg_anomaly;
  let barHtml = '';
  if (myScore != null && peerAvg != null) {
    const maxW = 300;
    const myW = Math.round(myScore * maxW);
    const peerW = Math.round(peerAvg * maxW);
    barHtml = `<div style="margin-top:0.5rem;">
      <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.3rem;">
        <span style="font-size:0.72rem;color:var(--text-muted);width:80px;">${_t('This Hospital')}</span>
        <div style="height:14px;background:var(--bg-elevated);border-radius:3px;flex:1;max-width:${maxW}px;">
          <div style="height:100%;width:${myW}px;background:var(--accent-blue);border-radius:3px;transition:width 0.5s;"></div>
        </div>
        <span style="font-size:0.75rem;font-weight:600;">${_fmtNum(myScore, 3)}</span>
      </div>
      <div style="display:flex;align-items:center;gap:0.5rem;">
        <span style="font-size:0.72rem;color:var(--text-muted);width:80px;">${_t('Peer Average')}</span>
        <div style="height:14px;background:var(--bg-elevated);border-radius:3px;flex:1;max-width:${maxW}px;">
          <div style="height:100%;width:${peerW}px;background:var(--accent-orange);border-radius:3px;transition:width 0.5s;"></div>
        </div>
        <span style="font-size:0.75rem;font-weight:600;">${_fmtNum(peerAvg, 3)}</span>
      </div>
    </div>`;
  }
  c.innerHTML = `<div style="font-size:0.85rem;font-weight:600;color:var(--text-primary);margin-bottom:0.3rem;">👥 ${_t('Peer Comparison')}</div>
    <div style="font-size:0.78rem;color:var(--text-secondary);margin-bottom:0.3rem;">${peers.peer_count} ${_t('peers in same group')}</div>
    ${barHtml}`;
}

export function renderHospitalFactors(anomaly, explanation, containerId) {
  const c = document.getElementById(containerId || 'smart-hospital-factors');
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
  // Show loading state immediately
  const nameEl = document.getElementById('smart-drilldown-name');
  const textEl = document.getElementById('smart-drilldown-text');
  const factorsEl = document.getElementById('smart-drilldown-factors');
  const trendEl = document.getElementById('smart-trend-line');
  if (nameEl) nameEl.textContent = hospitalId;
  if (textEl) textEl.innerHTML = '<div style="text-align:center;padding:1.5rem;"><div class="spinner spinner-lg" style="margin:0 auto 0.5rem;display:block;"></div><span style="color:var(--accent-blue);">' + (_t('Loading analysis...') || 'Loading analysis...') + '</span></div>';
  if (factorsEl) factorsEl.innerHTML = '';
  if (trendEl) trendEl.innerHTML = '';
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
    renderHospitalFactors(d.anomaly, d.explanation, 'smart-drilldown-factors');
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