// report.js — comprehensive report, data export, and peer comparison.
import { smartState, apiSmartGet, _smartEscapeHtml, _t, _fmtNum, _riskBadge, smartTranslateFeature } from './core.js';
import { renderPlot } from './charts.js';

function reportLang() {
  return smartState.lang || 'ar';
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
  const month = smartState.month || '';
  const url = scope === 'all' ? '/smart/overview/all' : `/smart/overview/${month}`;
  try {
    const data = await apiSmartGet(url);
    const rows = [];
    const anomalies = data.data ? data.data.anomalies : (data.anomalies || []);
    (anomalies || []).forEach(a => rows.push({
      month: month, hospital: a.hospital_name, governorate: a.governorate,
      score: a.anomaly_score, severity: a.severity,
    }));
    const csv = ['month,hospital,governorate,score,severity',
      ...rows.map(r => [r.month, r.hospital, r.governorate, r.score, r.severity].join(','))].join('\n');
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `smart_export_${month}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (e) {
    alert(e.message || _t('Export failed'));
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
    const data = await apiSmartGet(`/smart/overview/${month}`);
    smartState.data = data.data || data;
    renderReportSection(data.data || data, month);
    section.style.display = 'block';
    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) {
    alert(e.message || _t('Report generation failed'));
  } finally {
    smartState.reportGenerating = false;
    if (overlay) overlay.style.display = 'none';
  }
}

export function renderReportSection(data, month) {
  const kpi = data.kpi || {};
  const isEn = reportLang() === 'en';
  const k = key => _t(key);
  const kpiDashboard = document.getElementById('smart-report-kpi-dashboard');
  if (kpiDashboard) {
    kpiDashboard.innerHTML = `
      <div class="smart-kpi-card"><div class="smart-kpi-value">${kpi.total_anomalies ?? '-'}</div><div class="smart-kpi-label">${k('Hospitals with anomalies')}</div></div>
      <div class="smart-kpi-card"><div class="smart-kpi-value">${kpi.critical_count ?? '-'}</div><div class="smart-kpi-label">${k('Critical')}</div></div>
      <div class="smart-kpi-card"><div class="smart-kpi-value">${kpi.warning_count ?? '-'}</div><div class="smart-kpi-label">${k('Warning')}</div></div>
      <div class="smart-kpi-card"><div class="smart-kpi-value">${kpi.affected_governorates ?? '-'}</div><div class="smart-kpi-label">${k('Governorates affected')}</div></div>
      <div class="smart-kpi-card"><div class="smart-kpi-value" style="font-size:1.1rem;">${_smartEscapeHtml(smartTranslateFeature(kpi.top_contributing_factor))}</div><div class="smart-kpi-label">${k('Top factor')}</div></div>`;
  }
  const verdict = document.getElementById('smart-decision-verdict');
  if (verdict) {
    const st = kpi.month_status || 'normal';
    const colors = { critical: '#dc2626', attention_needed: '#f59e0b', normal: '#22c55e' };
    verdict.style.color = colors[st] || '#22c55e';
    verdict.textContent = st === 'critical' ? k('Needs urgent action')
      : st === 'attention_needed' ? k('Needs ongoing monitoring') : k('Within normal range');
  }
  const risk = document.getElementById('smart-decision-risk');
  if (risk) risk.textContent = k('Risk level') + ': ' + (stLabel(kpi.month_status, isEn));
  const hotspots = document.getElementById('smart-decision-hotspots');
  if (hotspots) hotspots.innerHTML = renderHospitalRows(data.anomalies.filter(a => a.severity === 'critical'), k);
  const watchlist = document.getElementById('smart-decision-watchlist');
  if (watchlist) watchlist.innerHTML = renderHospitalRows(data.anomalies.filter(a => a.severity === 'warning'), k);
  const priorities = document.getElementById('smart-decision-priorities');
  if (priorities) priorities.innerHTML = renderPriorityRows(data.anomalies, k);
  const output = document.getElementById('smart-report-output');
  if (output) output.innerHTML = '';
}

function stLabel(status, isEn) {
  const map = { critical: isEn ? 'Critical' : 'حرج', attention_needed: isEn ? 'Attention needed' : 'يحتاج متابعة', normal: isEn ? 'Normal' : 'طبيعي' };
  return map[status] || map.normal;
}

function renderHospitalRows(list, k) {
  if (!list.length) return `<div class="smart-priority-item smart-priority-normal"><div>✅ ${k('None')}</div></div>`;
  return list.map(h => `<div class="smart-priority-item smart-priority-${h.severity}">
    <div><div class="smart-priority-name">${_smartEscapeHtml(h.hospital_name)}</div>
    <div class="smart-priority-meta">${_smartEscapeHtml(h.governorate || '')}</div></div>
    <div>${_riskBadge(_fmtNum(h.anomaly_score, 3), h.severity)}</div>
  </div>`).join('');
}

function renderPriorityRows(list, k) {
  const sorted = list.slice().sort((a, b) => b.anomaly_score - a.anomaly_score);
  return renderHospitalRows(sorted.slice(0, 10), k);
}

export function initComparisonSelect() {
  const select = document.getElementById('smart-comparison-type');
  if (!select) return;
  select.addEventListener('change', () => renderComparison(select.value));
}

export async function renderComparison(scope) {
  const month = smartState.month || '';
  try {
    const data = await apiSmartGet(`/smart/overview/${month}`);
    const anomalies = data.data ? data.data.anomalies : data.anomalies || [];
    const peer = document.getElementById('smart-peer-comparison-table');
    if (peer) peer.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
      <th>${_t('Hospital')}</th><th>${_t('Governorate')}</th><th>${_t('Score')}</th><th>${_t('Severity')}</th></tr></thead><tbody>` +
      anomalies.map(a => `<tr><td>${_smartEscapeHtml(a.hospital_name)}</td>
        <td>${_smartEscapeHtml(a.governorate)}</td>
        <td>${_fmtNum(a.anomaly_score, 3)}</td>
        <td>${_riskBadge(a.severity, a.severity)}</td></tr>`).join('') + `</tbody></table></div>`;
  } catch (e) { /* ignored */ }
}

// Exposed for inline onclick attributes.
window.smartExportData = exportSmartData;
window.smartGenerateComprehensiveReport = generateComprehensiveReport;
window.smartToggleReportLang = toggleReportLang;