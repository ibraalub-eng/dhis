// decision-board.js — the above-the-fold decision board for monthly mode.
import { smartState, apiSmartGet, _smartEscapeHtml, _t, _fmtNum, _riskBadge, smartTranslateFeature, SMART_COLORS } from './core.js';

// Arabic labels for feature keys (moved from the monolithic file).
window.SMART_ARABIC = window.SMART_ARABIC || {};
Object.assign(window.SMART_ARABIC, {
  cs_rate: 'معدل القيصارية', smm_total: 'المضاعفات الخطيرة', mat_deaths: 'الوفيات الأمومية',
  nd: 'وفيات المولودين', sb: 'الولادات الميتة', preterm: 'الولادات السابقة لأوانها',
  lbw: 'نقص وزن الولادة', total_births: 'إجمالي المواليد', high_risk: 'حالات الخطر العالي',
  adolescent: 'الحالات المراهقة', governorate: 'المحافظة', hospital_type: 'نوع المستشفى',
  cs_per_birth: 'نسبة القيصارية لكل ولادة', smm_per_1000: 'المضاعفات لكل 1000 ولادة',
  mat_mortality_rate: 'معدل الوفيات الأمومية', stillbirth_rate: 'معدل الولادات الميتة',
  preterm_rate: 'معدل الولادات المبكرة', lbw_rate: 'معدل نقص الوزن',
  high_risk_rate: 'نسبة الخطر العالي', adolescent_rate: 'نسبة الحالات المراهقة',
  cs_x_highrisk: 'قيصارية × خطر عالي', preterm_x_lbw: 'ولادة مبكرة × نقص وزن',
  smm_x_matdeaths: 'مضاعفات × وفيات أمومية', nd_x_sb: 'وفيات جديدة × ولادات ميتة',
  cs_rate_delta: 'تغير معدل القيصارية', smm_delta: 'تغير المضاعفات',
  mat_deaths_delta: 'تغير الوفيات الأمومية', total_births_delta: 'تغير المواليد',
});
['cs_rate', 'smm_total', 'mat_deaths', 'total_births', 'nd', 'sb'].forEach(k => {
  window.SMART_ARABIC['lag1_' + k] = (window.SMART_ARABIC[k] || k) + ' (قيمة الشهر السابق)';
  window.SMART_ARABIC['lag2_' + k] = (window.SMART_ARABIC[k] || k) + ' (قيمة شهرين سابقين)';
});
['cs_rate', 'smm_total', 'mat_deaths', 'nd', 'sb', 'preterm', 'lbw', 'total_births', 'high_risk', 'adolescent'].forEach(k => {
  window.SMART_ARABIC['delta_' + k] = 'التغيّر الشهري في ' + (window.SMART_ARABIC[k] || k);
});

function openSmartModal(title, bodyHtml) {
  const modal = document.getElementById('smart-kpi-modal');
  document.getElementById('smart-kpi-modal-title').textContent = title;
  document.getElementById('smart-kpi-modal-body').innerHTML = bodyHtml;
  modal.style.display = 'flex';
  modal.onclick = function(e) { if (e.target === modal) modal.style.display = 'none'; };
}

export async function loadDecisionBoard(month) {
  const data = await apiSmartGet(`/smart/decision-board/${month}`);
  smartState.month = month;
  smartState.data = data; // CRIT-2: KPI modals must be able to read the board payload
  if (data.empty) {
    const status = document.getElementById('smart-status');
    if (status) status.textContent = data.message || _t('No data for this month');
    const c = document.getElementById('smart-kpi-container');
    if (c) c.innerHTML = `<div class="smart-empty-state">${_smartEscapeHtml(data.message || '')}</div>`;
    return;
  }
  document.getElementById('smart-decision-month').textContent = month;
  renderKPIs(data.kpi, data.hospitals_count);
  renderCriticalList(data.anomalies);
  renderEarlyWarnings(data.early_warnings);
  renderHealthyHospitals(data.healthy_hospitals);
  const status = document.getElementById('smart-status');
  if (status) status.textContent = _t('Updated') + ' — ' + data.hospitals_count + ' ' + _t('hospitals');
}

export function renderKPIs(kpi, hospitalsCount) {
  const c = document.getElementById('smart-kpi-container');
  if (!c) return;
  const statusColor = kpi.month_status === 'critical' ? SMART_COLORS.critical
    : kpi.month_status === 'attention_needed' ? SMART_COLORS.warning : SMART_COLORS.normal;
  const statusText = kpi.month_status === 'critical' ? _t('Needs urgent action')
    : kpi.month_status === 'attention_needed' ? _t('Needs ongoing monitoring') : _t('Within normal range');
  const statusIcon = kpi.month_status === 'critical' ? '❌' : kpi.month_status === 'attention_needed' ? '⚠️' : '✅';
  const criticalPct = hospitalsCount > 0 ? Math.round(kpi.critical_count / hospitalsCount * 100) : 0;
  const warningPct = hospitalsCount > 0 ? Math.round(kpi.warning_count / hospitalsCount * 100) : 0;
  const normalCount = hospitalsCount - kpi.critical_count - kpi.warning_count;

  c.innerHTML = `
    <div class="smart-kpi-card" style="border-top-color:${kpi.total_anomalies > 0 ? SMART_COLORS.critical : SMART_COLORS.normal};" onclick="window._smartKPIAnomalies()">
      <div class="smart-kpi-value" style="color:${kpi.total_anomalies > 0 ? SMART_COLORS.critical : SMART_COLORS.normal};">${kpi.total_anomalies}<span style="font-size:0.9rem;font-weight:400;color:#999;">/${hospitalsCount}</span></div>
      <div class="smart-kpi-label">${_t('Hospitals with anomalies')}</div>
      <div class="smart-kpi-sub">${kpi.critical_count} ${_t('critical')} (${criticalPct}%) + ${kpi.warning_count} ${_t('warning')} (${warningPct}%)</div>
    </div>
    <div class="smart-kpi-card" style="border-top-color:#3b82f6;" onclick="window._smartKPIGovernorates()">
      <div class="smart-kpi-value" style="color:#3b82f6;">${kpi.affected_governorates}<span style="font-size:0.9rem;font-weight:400;color:#999;">/${hospitalsCount > 0 ? Math.min(hospitalsCount, 5) : 5}</span></div>
      <div class="smart-kpi-label">${_t('Governorates with deviations')}</div>
      <div class="smart-kpi-sub">${_t('Contain warning or critical hospitals')}</div>
    </div>
    <div class="smart-kpi-card" style="border-top-color:#8b5cf6;" onclick="window._smartKPIFactors()">
      <div class="smart-kpi-value" style="font-size:1rem;color:#8b5cf6;word-break:break-word;line-height:1.4;">${_smartEscapeHtml(smartTranslateFeature(kpi.top_contributing_factor) || _t('Undefined'))}</div>
      <div class="smart-kpi-label">${_t('Top contributing factor')}</div>
      <div class="smart-kpi-sub">${_t('SHAP analysis of drivers')}</div>
    </div>
    <div class="smart-kpi-card" style="border-top-color:${statusColor};" onclick="window._smartKPIStatus()">
      <div class="smart-kpi-value" style="font-size:1.2rem;">${statusIcon} ${_smartEscapeHtml(statusText)}</div>
      <div class="smart-kpi-label">${_t('Month status')}</div>
      <div class="smart-kpi-sub">${hospitalsCount} ${_t('hospitals')} — ${normalCount} ${_t('normal')}, ${kpi.warning_count} ${_t('warning')}, ${kpi.critical_count} ${_t('critical')}</div>
    </div>
  `;
}

export function renderCriticalList(anomalies) {
  const container = document.getElementById('smart-critical-list');
  const countEl = document.getElementById('smart-critical-count');
  const textEl = document.getElementById('smart-critical-text');
  if (!container) return;
  const critical = (anomalies || []).filter(a => a.severity === 'critical');
  const warnings = (anomalies || []).filter(a => a.severity === 'warning');
  if (countEl) countEl.textContent = `${critical.length} ${_t('critical')} · ${warnings.length} ${_t('warning')}`;
  if (critical.length === 0) {
    container.innerHTML = `<div class="smart-priority-item smart-priority-normal">
      <div>✅ ${_t('No critical hospitals this month')}</div>
    </div>`;
    if (textEl) textEl.textContent = _t('Warning hospitals (0.3-0.6) — open the anomaly table to follow up.');
    return;
  }
  container.innerHTML = critical.map(h => {
    const hid = parseInt(h.hospital_id, 10);
    const month = smartState.month || '';
    return `<div class="smart-priority-item smart-priority-critical">
      <div>
        <div class="smart-priority-name">${_smartEscapeHtml(h.hospital_name)}</div>
        <div class="smart-priority-meta">${_smartEscapeHtml(h.governorate || '')}${h.hospital_type ? ' · ' + _smartEscapeHtml(h.hospital_type) : ''}</div>
      </div>
      <div style="display:flex;gap:0.4rem;align-items:center;">
        ${_riskBadge(h.anomaly_score.toFixed(3), 'critical')}
        <button class="btn btn-sm btn-outline" onclick="window.smartDrilldown(${hid})">📊 ${_t('Details')}</button>
        <button class="btn btn-sm" style="background:#dc2626;color:#fff;border:none;" onclick="window.smartGoRootCause(${hid}, '${month}')">🔍 ${_t('Root cause')}</button>
      </div>
    </div>`;
  }).join('');
  if (textEl) textEl.textContent = _t('Critical hospitals (>0.6) need urgent intervention.');
}

export function renderEarlyWarnings(ew) {
  const container = document.getElementById('smart-early-warnings');
  if (!container) return;
  const warnings = ew?.warnings || [];
  const summary = ew?.summary_ar || '';
  if (!warnings.length) { container.innerHTML = ''; return; }
  const rows = warnings.map(w => {
    const badge = w.severity === 'critical' ? '<span class="smart-badge smart-badge-critical">' + _t('critical') + '</span>'
      : w.severity === 'warning' ? '<span class="smart-badge smart-badge-warning">' + _t('warning') + '</span>'
      : '<span class="smart-badge smart-badge-normal">' + _t('info') + '</span>';
    const metrics = (w.contributing || []).map(l => l.metric_ar || l.metric).join(', ');
    const prob = w.probability != null ? (Math.round(w.probability * 100) + '%') : '';
    const confLabel = w.confidence_label_ar || w.confidence || '';
    return `<div class="smart-priority-item smart-priority-${w.severity === 'critical' ? 'critical' : 'warning'}">
      <div>
        <div class="smart-priority-name">${_smartEscapeHtml(w.hospital_name || '')}</div>
        <div class="smart-priority-meta">${_smartEscapeHtml(w.governorate || '')} · ${_smartEscapeHtml(metrics)}</div>
        <div class="smart-priority-meta" style="font-size:0.72rem;color:#6b7280;">
          ${prob ? _t('Probability') + ': ' + prob : ''}
          ${confLabel ? ' · ' + _smartEscapeHtml(confLabel) : ''}
          ${w.outcome_rising ? ' · ⚠️ ' + _t('outcome rising') : ''}
        </div>
      </div>
      <div>${badge}</div>
    </div>`;
  }).join('');
  container.innerHTML = `<div class="smart-section-card">
    <div class="smart-section-header" data-smart-collapsible="smart-early-warnings-body">
      <span>⚠️ ${_t('Early Warning System')}</span><span class="smart-toggle-icon">▾</span>
    </div>
    <div id="smart-early-warnings-body" class="smart-section-body">
      ${summary ? `<div class="smart-empty-state" style="margin-bottom:0.5rem;">${_smartEscapeHtml(summary)}</div>` : ''}
      <div class="smart-priority-list">${rows}</div>
    </div>
  </div>`;
  _bindDynamicCollapsibles(container);
}

export function renderHealthyHospitals(healthy) {
  const container = document.getElementById('smart-healthy-hospitals');
  if (!container) return;
  const list = healthy || [];
  if (!list.length) { container.innerHTML = ''; return; }
  const rows = list.map(h => `<div class="smart-priority-item smart-priority-normal">
    <div>
      <div class="smart-priority-name">${_smartEscapeHtml(h.hospital_name)}</div>
      <div class="smart-priority-meta">${_smartEscapeHtml(h.governorate || '')} · ${_t('composite')}: ${_fmtNum(h.composite_score, 1)}</div>
    </div>
  </div>`).join('');
  container.innerHTML = `<div class="smart-section-card">
    <div class="smart-section-header" data-smart-collapsible="smart-healthy-body">
      <span>🏆 ${_t('Healthy hospitals (models to follow)')}</span><span class="smart-toggle-icon">▾</span>
    </div>
    <div id="smart-healthy-body" class="smart-section-body"><div class="smart-priority-list">${rows}</div></div>
  </div>`;
  _bindDynamicCollapsibles(container);
}

// Bind collapsible click handlers on dynamically-created section headers.
// The static headers are bound at init time, but dynamically rendered sections
// (early warnings, healthy hospitals) need their own binding.
function _bindDynamicCollapsibles(root) {
  if (!root) return;
  root.querySelectorAll('[data-smart-collapsible]').forEach(header => {
    header.addEventListener('click', () => {
      const card = header.closest('.smart-section-card');
      if (!card) return;
      const isOpen = card.classList.contains('open');
      card.classList.toggle('open', !isOpen);
      const targetId = header.getAttribute('data-smart-collapsible');
      const target = targetId ? document.getElementById(targetId) : null;
      if (isOpen && target && window.Plotly) {
        target.querySelectorAll('.js-plotly-plot').forEach(el => Plotly.purge(el));
      }
    });
  });
}

// KPI modal openers (kept on window for inline onclick compatibility).
window._smartKPIAnomalies = function() {
  if (!smartState.data || !smartState.data.anomalies) return;
  const anomalies = smartState.data.anomalies || [];
  const total = smartState.data.hospitals_count || anomalies.length;
  const sorted = [...anomalies].sort((a, b) => b.anomaly_score - a.anomaly_score);
  const rows = sorted.map((a, i) => `<tr>
    <td class="smart-table-cell-rank">${i + 1}</td>
    <td class="smart-table-cell-name">${_smartEscapeHtml(a.hospital_name)}</td>
    <td class="smart-table-cell-value">${_smartEscapeHtml(a.governorate || '-')}</td>
    <td class="smart-table-cell-center">${_riskBadge(a.anomaly_score.toFixed(3), a.severity)}</td>
  </tr>`).join('');
  openSmartModal('🔍 ' + _t('Anomaly details'), `<div class="smart-table-wrap"><table><thead><tr><th>#</th><th>${_t('Hospital')}</th><th>${_t('Governorate')}</th><th>${_t('Score')}</th></tr></thead><tbody>${rows}</tbody></table></div>`);
};

window._smartKPIGovernorates = async function() {
  const month = smartState.month || '';
  let geo = smartState.data && smartState.data.geo;
  if (!geo) {
    // decision-board payload omits geo — fetch it lazily from the section endpoint (CRIT-2)
    const d = await apiSmartGet(`/smart/geo/${month}`);
    geo = d.geo || {};
  }
  const govs = (geo.governorates || []).slice().sort((a, b) => b.avg_anomaly_score - a.avg_anomaly_score);
  const rows = govs.map(g => `<tr>
    <td class="smart-table-cell-name">${_smartEscapeHtml(g.governorate)}</td>
    <td class="smart-table-cell-value">${g.hospital_count}</td>
    <td class="smart-table-cell-center">${_riskBadge(_fmtNum(g.avg_anomaly_score, 3), g.avg_anomaly_score >= 0.6 ? 'critical' : g.avg_anomaly_score >= 0.3 ? 'warning' : 'normal')}</td>
    <td class="smart-table-cell-value">${g.outlier_count}</td>
  </tr>`).join('');
  openSmartModal('🗺️ ' + _t('Governorates'), `<div class="smart-table-wrap"><table><thead><tr><th>${_t('Governorate')}</th><th>${_t('Hospitals')}</th><th>${_t('Avg score')}</th><th>${_t('Outliers')}</th></tr></thead><tbody>${rows}</tbody></table></div>`);
};

window._smartKPIFactors = async function() {
  const month = smartState.month || '';
  let exps = smartState.data && smartState.data.explanations;
  if (!exps) {
    // decision-board payload omits explanations — fetch lazily (CRIT-2)
    const d = await apiSmartGet(`/smart/anomalies/${month}`);
    exps = d.explanations || [];
  }
  const factors = {};
  exps.forEach(e => (e.top_factors || []).forEach(f => {
    factors[f.arabic_label || f.feature] = (factors[f.arabic_label || f.feature] || 0) + Math.abs(f.shap_value || 0);
  }));
  const sorted = Object.entries(factors).sort((a, b) => b[1] - a[1]);
  const rows = sorted.map(([name, value], i) => `<tr>
    <td class="smart-table-cell-rank">${i + 1}</td>
    <td class="smart-table-cell-name">${_smartEscapeHtml(name)}</td>
    <td class="smart-table-cell-value">${_fmtNum(value, 3)}</td>
  </tr>`).join('');
  openSmartModal('🧠 ' + _t('Top contributing factors'), `<div class="smart-table-wrap"><table><thead><tr><th>#</th><th>${_t('Factor')}</th><th>${_t('Impact')}</th></tr></thead><tbody>${rows}</tbody></table></div>`);
};

window._smartKPIStatus = function() {
  if (!smartState.data) return;
  const kpi = smartState.data.kpi || {};
  const level = kpi.month_status === 'critical' ? 'critical' : kpi.month_status === 'attention_needed' ? 'warning' : 'normal';
  openSmartModal('📊 ' + _t('Month status'), `<div class="smart-priority-list">
    <div class="smart-priority-item smart-priority-${level}">
      <div>
        <div class="smart-priority-name">${_t('Month status')}: ${_smartEscapeHtml(kpi.month_status_ar || kpi.month_status || '')}</div>
        <div class="smart-priority-meta">${_t('Hospitals with anomalies')}: ${kpi.total_anomalies} / ${smartState.data.hospitals_count || 0}</div>
      </div>
    </div>
  </div>`);
};