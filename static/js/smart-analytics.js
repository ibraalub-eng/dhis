// smart-analytics.js — ES-module entry: wires the smart-analytics screen.
import { smartState, apiSmartGet, smartShowLoading, smartHideLoading,
         setSmartLoader, showSmartSectionError, showSmartSectionEmpty,
         clearSmartSectionState, _smartEscapeHtml, _t, _fmtNum, _riskBadge,
         smartTranslateFeature, toggleSmartSection, setSmartMode,
         registerSectionLoaders, initSectionObserver, reloadSmartSections,
         trapFocus } from './smart/core.js';
import { loadDecisionBoard, renderKPIs, renderCriticalList, renderEarlyWarnings, renderHealthyHospitals } from './smart/decision-board.js';
import { initAdvancedTabs, loadAdvancedSection, loadClustersTab, loadCorrelationsTab,
         loadPatternsTab, loadXGBoostTab, loadFeatureImportanceTab } from './smart/advanced.js';
import { renderPlot } from './smart/charts.js';
import { loadGeoSection } from './smart/geo-regional.js';
import { initHospitalSelect, loadHospitalMode, openDrilldown, goRootCause } from './smart/hospital.js';
import { generateComprehensiveReport, toggleReportLang, exportSmartData, initComparisonSelect, renderComparison } from './smart/report.js';

// Legacy window globals kept for inline onclick compatibility (some live in modules).
window.smartDrilldown = openDrilldown;
window.smartGoRootCause = goRootCause;
window.smartExportData = exportSmartData;
window.smartGenerateComprehensiveReport = generateComprehensiveReport;
window.smartToggleReportLang = toggleReportLang;
// _smartKPI* modal openers are registered by decision-board.js as module side effects —
// do NOT redefine them here (that would overwrite the working implementations).

// ---- month + hospital selects ----
async function loadMonths() {
  const select = document.getElementById('smart-month-select');
  if (!select) return;
  try {
    const months = await apiSmartGet('/smart/months');
    if (!months || !months.length) return;
    select.innerHTML = months.map(m => `<option value="${_smartEscapeHtml(m)}">${_smartEscapeHtml(m)}</option>`).join('');
    const last = months[months.length - 1];
    select.value = last;
    smartState.month = last;
    onMonthChange(last);
  } catch (e) {
    showSmartSectionError('anomalies', e.message);
  }
}

async function loadHospitals() {
  try {
    const hospitals = await apiSmartGet('/smart/hospitals');
    initHospitalSelect(hospitals);
  } catch (e) { /* non-fatal */ }
}

async function onMonthChange(month) {
  smartState.month = month;
  document.getElementById('smart-critical-list').innerHTML = '';
  document.getElementById('smart-kpi-container').innerHTML = '';
  document.getElementById('smart-anomaly-table').innerHTML = '';
  // Fire decision board + section loaders in parallel instead of awaiting
  // the decision board first — the 7-engine pipeline runs on the first
  // request for a month; sections can start fetching immediately.
  loadDecisionBoard(month).catch(() => {});
  reloadSmartSections();
}

// ---- section loaders registry ----
registerSectionLoaders({
  anomalies: { load: () => loadAnomaliesTable(smartState.month) },
  geo: { load: () => loadGeoSection(smartState.month) },
  advanced: { load: () => loadAdvancedSection(smartState.month) },
  xgboost: { load: () => loadXGBoostTab(smartState.month) },
  timeline: { load: () => loadTimeline() },
  'time-overview': { load: () => loadTimeOverview() },
  hospital: { load: () => { const v = getSelectedHospital(); return v ? loadHospitalMode(v, null) : Promise.resolve(); } },
});

async function loadAnomaliesTable(month) {
  try {
    const d = await apiSmartGet(`/smart/anomalies/${month}`);
    if (d.empty) { showSmartSectionEmpty('anomalies', d.message); return; }
    const rows = d.anomalies.map(a => `<tr>
      <td>${_smartEscapeHtml(a.hospital_name)}</td>
      <td>${_smartEscapeHtml(a.governorate)}</td>
      <td>${_fmtNum(a.anomaly_score, 3)}</td>
      <td>${_riskBadge(a.severity, a.severity)}</td>
      <td style="font-size:0.75rem;">${_smartEscapeHtml(a.reason || '')}</td>
      <td><button class="btn btn-sm btn-outline" onclick="window.smartDrilldown(${a.hospital_id})">📊</button></td>
    </tr>`).join('');
    document.getElementById('smart-anomaly-table').innerHTML = rows;
  } catch (e) {
    showSmartSectionError('anomalies', e.message);
  }
}

async function loadTimeline() {
  try {
    const d = await apiSmartGet('/smart/anomaly-timeline');
    const months = d.months || [];
    const hospitals = d.hospitals || [];
    const badge = document.getElementById('smart-timeline-badge');
    if (badge) badge.textContent = months.length ? `${months.length} ${_t('months')} | ${hospitals.length} ${_t('hospitals')}` : '';
    const text = document.getElementById('smart-timeline-text');
    if (!months.length || !hospitals.length) {
      if (text) text.textContent = _t('No data');
      renderPlot('smart-timeline-chart', []);
      return;
    }
    const names = hospitals.map(h => h.hospital_name);
    const makeTrace = (m) => ({
      type: 'bar',
      x: names,
      y: hospitals.map(h => (h.scores && h.scores[m] != null ? h.scores[m] : null)),
      marker: { color: hospitals.map(h => {
        const sev = h.severities && h.severities[m];
        return sev === 'critical' ? '#ef4444' : sev === 'warning' ? '#f59e0b' : '#22c55e';
      }), line: { width: 1, color: '#fff' } },
    });
    const layout = {
      title: { text: _t('Anomaly scores over time'), font: { size: 13, color: '#1a237e' } },
      xaxis: { tickangle: -45, tickfont: { size: 9 }, categoryorder: 'array', categoryarray: names },
      yaxis: { title: _t('Score'), range: [0, 1] },
      shapes: [
        { type: 'line', x0: -0.5, x1: hospitals.length - 0.5, y0: 0.3, y1: 0.3, xref: 'x', yref: 'y', line: { color: '#f59e0b', width: 1.5, dash: 'dash' } },
        { type: 'line', x0: -0.5, x1: hospitals.length - 0.5, y0: 0.6, y1: 0.6, xref: 'x', yref: 'y', line: { color: '#ef4444', width: 1.5, dash: 'dash' } },
      ],
      updatemenus: [{
        type: 'buttons', showactive: false, x: 0.02, y: 1.15, xanchor: 'left', yanchor: 'top',
        buttons: [
          { label: _t('Play'), method: 'animate', args: [null, { mode: 'next', frame: { duration: 500, redraw: true }, transition: { duration: 200 } }] },
          { label: _t('Pause'), method: 'animate', args: [[null], { mode: 'immediate', transition: { duration: 0 } }] },
        ],
      }],
      sliders: [{
        active: 0,
        steps: months.map(m => ({ label: m, method: 'animate', args: [[m], { mode: 'immediate', frame: { duration: 400, redraw: true }, transition: { duration: 150 } }] })),
        pad: { t: 40 }, currentvalue: { prefix: `${_t('Month')}: `, font: { size: 12, color: '#1a237e' } },
      }],
      margin: { t: 60, b: 100, l: 50, r: 20 },
      height: 460, paper_bgcolor: 'white', plot_bgcolor: 'white', hovermode: 'closest',
    };
    if (window.Plotly && window.Plotly.addFrames) {
      Plotly.newPlot('smart-timeline-chart', [makeTrace(months[0])], layout).then(gd => {
        Plotly.addFrames(gd, months.map(m => ({ name: m, data: [makeTrace(m)] })));
      });
    } else {
      renderPlot('smart-timeline-chart', [makeTrace(months[months.length - 1])], layout);
    }
    const last = months[months.length - 1];
    const critical = hospitals.filter(h => h.severities && h.severities[last] === 'critical').length;
    const warning = hospitals.filter(h => h.severities && h.severities[last] === 'warning').length;
    if (text) text.textContent = `${months[0]} → ${last}: ${critical} ${_t('critical')}, ${warning} ${_t('warning')} (${hospitals.length} ${_t('hospitals')})`;
  } catch (e) {
    showSmartSectionError('timeline', e.message);
  }
}

async function loadTimeOverview() {
  try {
    const d = await apiSmartGet('/smart/time-overview');
    if (d.empty) { showSmartSectionEmpty('time-overview', d.message); return; }
    const s = d.series;
    renderPlot('smart-time-avg', [{ x: s.avg_score.map(p => p.month), y: s.avg_score.map(p => p.value), type: 'scatter', mode: 'lines+markers' }], { title: _t('Average anomaly score') });
    renderPlot('smart-time-severity', [
      { x: s.critical_count.map(p => p.month), y: s.critical_count.map(p => p.value), name: _t('Critical'), type: 'bar' },
      { x: s.warning_count.map(p => p.month), y: s.warning_count.map(p => p.value), name: _t('Warning'), type: 'bar' },
    ], { barmode: 'group', title: _t('Severity counts') });
    renderPlot('smart-time-governorates', [{ x: s.affected_governorates.map(p => p.month), y: s.affected_governorates.map(p => p.value), type: 'scatter', mode: 'lines+markers' }], { title: _t('Affected governorates') });
  } catch (e) {
    showSmartSectionError('time-overview', e.message);
  }
}

function getSelectedHospital() {
  const s = document.getElementById('smart-hospital-context-select');
  return s ? s.value : '';
}

let _wired = false;
function wireScreen() {
  if (_wired) return;
  _wired = true;

  // ---- mode buttons ----
  document.querySelectorAll('.smart-mode-btn').forEach(btn => {
    btn.addEventListener('click', () => setSmartMode(btn.dataset.smartMode));
  });

  // ---- collapsible headers ----
  document.querySelectorAll('[data-smart-collapsible]').forEach(header => {
    header.addEventListener('click', () => toggleSmartSection(header));
  });

  // ---- methodology modal ----
  function openMethodology() {
    const modal = document.getElementById('smart-methodology-modal');
    if (modal) { modal.classList.add('active'); trapFocus(modal, document.getElementById('smart-methodology-btn')); }
  }
  function closeMethodology() {
    const modal = document.getElementById('smart-methodology-modal');
    if (modal) modal.classList.remove('active');
  }
  const methodologyBtn = document.getElementById('smart-methodology-btn');
  if (methodologyBtn) methodologyBtn.addEventListener('click', openMethodology);
  const methodologyClose = document.getElementById('smart-methodology-close');
  if (methodologyClose) methodologyClose.addEventListener('click', closeMethodology);

  // ---- KPI / drilldown modals: click-outside + close buttons ----
  ['smart-kpi-modal', 'smart-drilldown-modal'].forEach(id => {
    const modal = document.getElementById(id);
    if (modal) {
      modal.addEventListener('click', e => { if (e.target === modal) modal.style.display = 'none'; });
      const closeBtn = modal.querySelector('button[aria-label="Close"]');
      if (closeBtn) closeBtn.addEventListener('click', () => { modal.style.display = 'none'; });
    }
  });

  // ---- event wiring ----
  document.getElementById('smart-month-select')?.addEventListener('change', e => onMonthChange(e.target.value));
  document.getElementById('smart-hospital-select')?.addEventListener('change', e => {
    const v = e.target.value;
    if (v) loadHospitalMode(v, null);
  });
  document.getElementById('smart-hospital-context-select')?.addEventListener('change', e => {
    const v = e.target.value;
    if (v) loadHospitalMode(v, null);
  });
  document.getElementById('smart-hospital-context-all')?.addEventListener('click', () => {
    const v = getSelectedHospital();
    if (v) loadHospitalMode(v, 'all');
  });
  document.getElementById('smart-refresh')?.addEventListener('click', () => {
    cacheBust();
    onMonthChange(smartState.month);
  });
  initComparisonSelect();
  initAdvancedTabs();
}

// ---- error banner retry (spec 5): clicking an active error banner reloads its section ----
const _retryLoaders = {
  anomalies: () => loadAnomaliesTable(smartState.month),
  geo: () => loadGeoSection(smartState.month),
  advanced: () => loadAdvancedSection(smartState.month),
  xgboost: () => loadXGBoostTab(smartState.month),
  timeline: () => loadTimeline(),
  'time-overview': () => loadTimeOverview(),
  hospital: () => { const v = getSelectedHospital(); return v ? loadHospitalMode(v, null) : Promise.resolve(); },
};
document.addEventListener('click', e => {
  const banner = e.target.closest('.smart-error-banner.active');
  if (!banner) return;
  const key = banner.getAttribute('data-smart-error');
  const fn = key && _retryLoaders[key];
  if (!fn) return;
  setSmartLoader(key, true);
  fn().catch(() => {}).finally(() => setSmartLoader(key, false));
});

function cacheBust() {
  const status = document.getElementById('smart-status');
  if (status) status.textContent = _t('Refreshed');
}

// ---- startup ----
let _smartInitDone = false;
function initSmartAnalytics() {
  if (!document.getElementById('smart-kpi-container')) return;
  wireScreen();
  if (_smartInitDone) return; // IMP-3: idempotent — lang toggle re-runs init, avoid double observers/fetches
  _smartInitDone = true;
  initSectionObserver();
  loadHospitals();
  loadMonths();
}
window.initSmartAnalytics = initSmartAnalytics;