// report.js — comprehensive report, data export, and peer comparison.
// IMP-2: all three flows use the server-side comparative/export endpoints.
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
  const month = scope === 'all' ? 'all' : (smartState.month || '');
  const lang = reportLang();
  const base = document.getElementById('apiBase')?.value || '';
  const url = `${base}/export/full-data?month=${encodeURIComponent(month)}&lang=${lang}`;
  const status = document.getElementById('smart-status');
  if (status) status.textContent = _t('Exporting data...');
  try {
    const res = await fetch(url);
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
  if (output) output.innerHTML = reportText ? renderReportLines(reportText) : '';
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
          return `<div style="margin-bottom:0.4rem;">
            <div style="display:flex;justify-content:space-between;font-size:0.78rem;">
              <span style="font-weight:600;">${_smartEscapeHtml(h.governorate)}</span>
              <span style="color:${col};font-weight:700;">${h.outliers} ${k('outliers')} · ${h.risk_pct}%</span>
            </div>
            <div style="height:4px;background:#e2e8f0;border-radius:2px;overflow:hidden;">
              <div style="width:${Math.min(100, h.risk_pct)}%;height:100%;background:${col};"></div>
            </div>
          </div>`;
        }).join('')
      : `<div class="smart-empty-state">${k('No anomalous governorates')}</div>`;
  }

  if (watchEl) {
    watchEl.innerHTML = (decision.watchlist && decision.watchlist.length)
      ? decision.watchlist.map(w => {
          const col = w.severity === 'critical' ? '#dc2626' : w.severity === 'warning' ? '#f59e0b' : '#f9a825';
          return `<div style="display:flex;align-items:center;gap:0.4rem;padding:0.3rem 0;border-bottom:1px dashed #e2e8f0;">
            <span style="width:8px;height:8px;border-radius:50%;background:${col};flex-shrink:0;"></span>
            <span style="font-weight:600;font-size:0.8rem;">${_smartEscapeHtml(w.hospital)}</span>
            <span style="font-size:0.72rem;color:#888;">${_smartEscapeHtml(w.governorate || '')} · ${w.score}</span>
          </div>`;
        }).join('')
      : `<div class="smart-empty-state">${k('No hospitals to watch')}</div>`;
  }

  if (prioEl) {
    const prioColors = { critical: '#dc2626', high: '#e65100', medium: '#f9a825', low: '#388e3c' };
    prioEl.innerHTML = (decision.priorities && decision.priorities.length)
      ? decision.priorities.map((p, i) => {
          const col = prioColors[p.priority] || '#888';
          return `<div style="display:flex;align-items:center;gap:0.5rem;padding:0.35rem 0.4rem;margin-bottom:0.3rem;background:${col}0a;border-radius:6px;border-left:3px solid ${col};">
            <span style="font-size:0.7rem;font-weight:700;color:${col};min-width:1.1rem;">${i + 1}</span>
            <span style="flex:1;">
              <span style="font-weight:600;font-size:0.8rem;">${_smartEscapeHtml(p.action)}</span>
              <span style="font-size:0.72rem;color:#666;display:block;">← ${_smartEscapeHtml(p.target)}</span>
            </span>
            <span style="font-size:0.7rem;font-weight:700;color:${col};">${k('Impact')} ${Math.round(p.impact || 0)}%</span>
          </div>`;
        }).join('')
      : `<div class="smart-empty-state">${k('No priorities')}</div>`;
  }
}

// Render the AI report text as formatted lines (reuses report-* CSS classes).
function renderReportLines(reportText) {
  return String(reportText).split('\n').map(line => {
    const t = String(line).trim();
    if (!t) return `<div class="report-line report-line-empty"></div>`;
    if (t.startsWith('- ') || t.startsWith('• ')) {
      let content = t.replace(/^[-•]\s*/, '');
      const segments = content.split('|').map(s => s.trim()).filter(Boolean);
      if (segments.length > 1) {
        const chips = segments.map(seg => {
          const idx = seg.indexOf(': ');
          if (idx > 0) {
            const key = seg.slice(0, idx);
            const val = seg.slice(idx + 2);
            return `<span class="report-chip"><span class="report-chip-key">${_smartEscapeHtml(key)}</span>: ${_smartEscapeHtml(val)}</span>`;
          }
          return `<span class="report-chip">${_smartEscapeHtml(seg)}</span>`;
        });
        return `<div class="report-line report-bullet">${chips.join('')}</div>`;
      }
      const idx = content.indexOf(': ');
      if (idx > 0) {
        const key = content.slice(0, idx);
        const val = content.slice(idx + 2);
        return `<div class="report-line report-bullet"><span class="report-key">${_smartEscapeHtml(key)}</span><span class="report-sep">: </span><span class="report-value">${_smartEscapeHtml(val)}</span></div>`;
      }
      return `<div class="report-line report-bullet">${_smartEscapeHtml(content)}</div>`;
    }
    if (t.endsWith(':') && t.length < 60) {
      return `<div class="report-line report-text" style="font-weight:700;color:#1a237e;">${_smartEscapeHtml(t)}</div>`;
    }
    return `<div class="report-line report-text">${_smartEscapeHtml(t)}</div>`;
  }).join('');
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
  try {
    const params = new URLSearchParams();
    if (hospitalId) params.append('hospital_id', hospitalId);
    if (scope) params.append('comparison_type', scope);
    const qs = params.toString();
    const data = await apiSmartGet(`/comparative/advanced-comparison/${month}${qs ? '?' + qs : ''}`);
    const peers = (data.comparison_data && data.comparison_data.peer_comparison) || [];
    const chart = document.getElementById('smart-comparison-chart');
    if (chart && peers.length) {
      const colors = peers.map(p => p.comparison_label === 'ممتاز' || p.comparison_label === 'Excellent' ? '#22c55e'
        : p.comparison_label === 'حرج' || p.comparison_label === 'Critical' ? '#ef4444'
        : p.comparison_label === 'يحتاج تحسين' || p.comparison_label === 'Needs improvement' ? '#f59e0b'
        : '#6366f1');
      renderPlot('smart-comparison-chart', [{
        x: peers.map(p => p.hospital_name),
        y: peers.map(p => p.percentile),
        type: 'bar',
        marker: { color },
        text: peers.map(p => p.percentile.toFixed(1) + '%'),
        textposition: 'outside',
      }], { yaxis: { title: _t('Percentile'), rangemode: 'tozero' }, xaxis: { tickangle: -45, tickfont: { size: 9 } } });
    }
    const peer = document.getElementById('smart-peer-comparison-table');
    if (peer) {
      peer.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
        <th>${_t('Rank')}</th><th>${_t('Hospital')}</th><th>${_t('Percentile')}</th><th>${_t('Assessment')}</th></tr></thead><tbody>` +
        peers.map(p => `<tr><td style="text-align:center;font-weight:600;">${p.rank}</td>
          <td>${_smartEscapeHtml(p.hospital_name)}</td>
          <td style="text-align:center;">${p.percentile.toFixed(1)}%</td>
          <td>${_riskBadge(p.comparison_label, p.comparison_label === 'حرج' || p.comparison_label === 'Critical' ? 'critical' : p.comparison_label === 'يحتاج تحسين' || p.comparison_label === 'Needs improvement' ? 'warning' : 'normal')}</td></tr>`).join('') +
        `</tbody></table></div>`;
    }
  } catch (e) { /* ignored */ }
}

// Exposed for inline onclick attributes.
window.smartExportData = exportSmartData;
window.smartGenerateComprehensiveReport = generateComprehensiveReport;
window.smartToggleReportLang = toggleReportLang;