// report.js — comprehensive report, data export, and peer comparison.
// IMP-2: all three flows use the server-side comparative/export endpoints.
import { smartState, apiSmartGet, _smartEscapeHtml, _t, _fmtNum, _riskBadge, smartTranslateFeature, setSmartLoader, showSmartSectionError, showSmartSectionEmpty, clearSmartSectionState } from './core.js';
import { renderPlot } from './charts.js';
import renderReportSections from './report-sections.js';

function reportLang() {
  return smartState.lang || 'en';
}

// Language-agnostic label-to-severity mapping
const _LABEL_LEVELS = {
  // Arabic risk labels
  'حرج': 'critical',
  'عالي': 'warning',
  'متوسط': 'normal',
  'منخفض': 'normal',
  // English risk labels
  'critical': 'critical',
  'high': 'warning',
  'moderate': 'normal',
  'low': 'normal',
};

function _labelToLevel(label) {
  return _LABEL_LEVELS[label] || 'normal';
}

function _labelColor(label) {
  const level = _labelToLevel(label);
  return level === 'critical' ? '#ef4444' : level === 'warning' ? '#f59e0b' : '#22c55e';
}

export function toggleReportLang() {
  smartState.lang = smartState.lang === 'ar' ? 'en' : 'ar';
  const btn = document.getElementById('smart-report-lang-toggle');
  if (btn) btn.textContent = smartState.lang === 'ar' ? '🇬🇧 English' : '🇸🇦 العربية';
  const section = document.getElementById('smart-report-section');
  if (section && section.style.display !== 'none') generateComprehensiveReport();
}

export async function exportSmartData() {
  const scope = document.getElementById('smart-export-scope')?.value || 'current';
  const month = scope === 'all' ? 'all' : (smartState.month || '');
  const lang = reportLang();
  const base = '';
  const url = `${base}/export/full-data?month=${encodeURIComponent(month)}&lang=${lang}`;
  const status = document.getElementById('smart-status');
  if (status) status.textContent = _t('Exporting data...');
  try {
    const res = await authFetch(url);
    if (!res.ok) {
      let detail = '';
      try { detail = (await res.json()).detail || ''; } catch (e) { /* ignore */ }
      throw new Error(detail || ('HTTP ' + res.status));
    }
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `health_export_${month}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
    if (status) status.textContent = _t('Export complete');
  } catch (e) {
    if (status) status.textContent = _t('Export failed') + ': ' + e.message;
  }
}

export async function generateComprehensiveReport() {
  if (smartState.reportGenerating) return;
  const section = document.getElementById('smart-report-section');
  if (!section) return;
  const month = smartState.month || '';
  const overlay = document.getElementById('smart-loading-overlay');
  smartState.reportGenerating = true;
  if (overlay) overlay.style.display = 'flex';
  try {
    const result = await apiSmartGet(`/comparative/comprehensive-report/${month}?lang=${reportLang()}`);
    smartState.data = result.data || result;
    smartState.sections = result.sections || {};
    smartState.can_view_explanations = result.can_view_explanations !== false;
    renderReportSection(result.data || result, month, result.report || '');
    section.style.display = 'block';
    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) {
    alert(e.message || _t('Report generation failed'));
  } finally {
    smartState.reportGenerating = false;
    if (overlay) overlay.style.display = 'none';
  }
}

export function renderReportSection(data, month, reportText) {
  const kpi = data.kpi || {};
  const isEn = reportLang() === 'en';
  const k = key => _t(key);
  const kpiDashboard = document.getElementById('smart-report-kpi-dashboard');
  if (kpiDashboard) {
    kpiDashboard.innerHTML = `
      <div class="smart-kpi-card"><div class="smart-kpi-value">${data.hospitals_count ?? '-'}</div><div class="smart-kpi-label">${k('Hospitals')}</div></div>
      <div class="smart-kpi-card"><div class="smart-kpi-value">${kpi.total_anomalies ?? '-'}</div><div class="smart-kpi-label">${k('Hospitals with anomalies')}</div></div>
      <div class="smart-kpi-card"><div class="smart-kpi-value">${kpi.critical_count ?? '-'}</div><div class="smart-kpi-label">${k('Critical')}</div></div>
      <div class="smart-kpi-card"><div class="smart-kpi-value">${kpi.warning_count ?? '-'}</div><div class="smart-kpi-label">${k('Warning')}</div></div>
      <div class="smart-kpi-card"><div class="smart-kpi-value" style="font-size:1.1rem;">${_smartEscapeHtml(smartTranslateFeature(kpi.top_contributing_factor))}</div><div class="smart-kpi-label">${k('Top factor')}</div></div>`;
  }
  renderDecisionBoard(data.decision || {}, k);
  const output = document.getElementById('smart-report-output');
  if (output) {
    smartState.sections = smartState.sections || {};
    renderReportSections({ data, sections: smartState.sections, lang: reportLang() });
  }
}

function renderDecisionBoard(decision, k) {
  const verdictEl = document.getElementById('smart-decision-verdict');
  const riskEl = document.getElementById('smart-decision-risk');
  const hotspotsEl = document.getElementById('smart-decision-hotspots');
  const watchEl = document.getElementById('smart-decision-watchlist');
  const prioEl = document.getElementById('smart-decision-priorities');

  const verdictColors = { critical: '#dc2626', attention: '#f59e0b', normal: '#22c55e' };
  const vColor = verdictColors[decision.verdict] || '#22c55e';
  if (verdictEl) {
    verdictEl.style.color = vColor;
    verdictEl.textContent = decision.verdict_label || k('Within normal range');
  }
  if (riskEl) riskEl.textContent = k('Risk level') + ': ' + (decision.risk_score != null ? decision.risk_score : '-') + '/100';

  if (hotspotsEl) {
    hotspotsEl.innerHTML = (decision.hotspots && decision.hotspots.length)
      ? decision.hotspots.map(h => {
          const col = h.risk_pct >= 50 ? '#dc2626' : h.risk_pct >= 25 ? '#f59e0b' : '#22c55e';
          return `<div class="smart-report-row">
            <div class="smart-report-row-header">
              <span class="smart-report-row-label">${_smartEscapeHtml(h.governorate)}</span>
              <span class="smart-report-row-value" style="color:${col};">${h.outliers} ${k('outliers')} · ${h.risk_pct}%</span>
            </div>
            <div class="smart-report-bar-track">
              <div class="smart-report-bar-fill" style="width:${Math.min(100, h.risk_pct)}%;background:${col};"></div>
            </div>
          </div>`;
        }).join('')
      : `<div class="smart-empty-state">${k('No anomalous governorates')}</div>`;
  }

  if (watchEl) {
    watchEl.innerHTML = (decision.watchlist && decision.watchlist.length)
      ? decision.watchlist.map(w => {
          const col = w.severity === 'critical' ? '#dc2626' : w.severity === 'warning' ? '#f59e0b' : '#f9a825';
          return `<div class="smart-watchlist-item">
            <span class="smart-watchlist-dot" style="background:${col};"></span>
            <span class="smart-watchlist-name">${_smartEscapeHtml(w.hospital)}</span>
            <span class="smart-watchlist-meta">${_smartEscapeHtml(w.governorate || '')} · ${w.score}</span>
          </div>`;
        }).join('')
      : `<div class="smart-empty-state">${k('No hospitals to watch')}</div>`;
  }

  if (prioEl) {
    const prioColors = { critical: '#dc2626', high: '#e65100', medium: '#f9a825', low: '#388e3c' };
    prioEl.innerHTML = (decision.priorities && decision.priorities.length)
      ? decision.priorities.map((p, i) => {
          const col = prioColors[p.priority] || '#888';
          return `<div class="smart-priority-ranked" style="background:${col}0a;border-left-color:${col};">
            <span class="smart-priority-rank" style="color:${col};">${i + 1}</span>
            <span style="flex:1;">
              <span class="smart-priority-action">${_smartEscapeHtml(p.action)}</span>
              <span class="smart-priority-target">← ${_smartEscapeHtml(p.target)}</span>
            </span>
            <span class="smart-priority-impact" style="color:${col};">${k('Impact')} ${Math.round(p.impact || 0)}%</span>
          </div>`;
        }).join('')
      : `<div class="smart-empty-state">${k('No priorities')}</div>`;
  }
}

export function initComparisonSelect() {
  const select = document.getElementById('smart-comparison-type');
  if (!select) return;
  select.addEventListener('change', () => renderComparison(select.value));
}

// Server-side ranked peer comparison (honors scope via comparison_type).
export async function renderComparison(scope) {
  const month = smartState.month || '';
  const hospitalId = document.getElementById('smart-hospital-select')?.value || '';
  setSmartLoader('comparison', true);
  try {
    const params = new URLSearchParams();
    if (hospitalId) params.append('hospital_id', hospitalId);
    if (scope) params.append('comparison_type', scope);
    params.append('lang', reportLang());
    const qs = params.toString();
    const data = await apiSmartGet(`/comparative/advanced-comparison/${month}${qs ? '?' + qs : ''}`);
    const peers = (data.comparison_data && data.comparison_data.peer_comparison) || [];
    const chart = document.getElementById('smart-comparison-chart');
    if (chart && peers.length) {
      const colors = peers.map(p => _labelColor(p.comparison_label));
      renderPlot('smart-comparison-chart', [{
        x: peers.map(p => p.hospital_name),
        y: peers.map(p => p.percentile),
        type: 'bar',
        marker: { color: colors },
        text: peers.map(p => p.percentile.toFixed(1) + '%'),
        textposition: 'outside',
      }], { yaxis: { title: _t('Percentile'), rangemode: 'tozero' }, xaxis: { tickangle: -45, tickfont: { size: 9 } } });
    }
    const peer = document.getElementById('smart-peer-comparison-table');
    if (peer) {
      peer.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
        <th>${_t('Rank')}</th><th>${_t('Hospital')}</th><th>${_t('Anomaly score')}</th><th>${_t('Percentile')}</th><th>${_t('Assessment')}</th></tr></thead><tbody>` +
        peers.map(p => `<tr><td style="text-align:center;font-weight:600;">${p.rank}</td>
          <td>${_smartEscapeHtml(p.hospital_name)}</td>
          <td style="text-align:center;">${_fmtNum(p.anomaly_score)}</td>
          <td style="text-align:center;">${p.percentile.toFixed(1)}%</td>
          <td>${_riskBadge(p.comparison_label, _labelToLevel(p.comparison_label))}</td></tr>`).join('') +
        `</tbody></table></div>`;
    }
    if (!peers.length) {
      showSmartSectionEmpty('comparison', _t('No data'));
    } else {
      clearSmartSectionState('comparison');
    }
  } catch (e) {
    showSmartSectionError('comparison', e.message || String(e));
  } finally {
    setSmartLoader('comparison', false);
  }
}

// Exposed for inline onclick attributes.
window.smartExportData = exportSmartData;
window.smartGenerateComprehensiveReport = generateComprehensiveReport;
window.smartToggleReportLang = toggleReportLang;