// smart-forecast.js — ES-module entry: wires the Smart Forecast (prediction) screen.
//
// The prediction section (XGBoost forecasts, trajectory, accuracy, tracking,
// early-warning signals, per-indicator forecast, walk-forward, scatter) and the
// single-hospital forecast were moved here from the Smart Analytics screen.
// This screen owns its month and horizon controls and loads on its own:
// nothing is registered in core's shared section registry, so a month change on
// the analytics screen never refetches this screen — and never repaints charts
// into a hidden tab.

import { apiSmartGet, setSmartLoader, showSmartSectionError,
         showSmartSectionEmpty, clearSmartSectionState,
         _smartEscapeHtml, _t, toggleSmartSection } from './smart/core.js';
import { loadXGBoostTab, initHorizonSelect, getForecastMonth } from './smart/advanced.js';
import { renderHospitalForecast } from './smart/hospital.js';

// ---- error-banner retry (same contract as smart-analytics.js) ----
const _retryLoaders = {
  xgboost: () => refresh(),
  'hospital-forecast': () => loadHospitalForecast(_selectedHospital()),
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

// ---- load one month of forecasts (single entry point for every trigger) ----
function refresh(month) {
  const m = month || getForecastMonth();
  if (!m) return Promise.resolve();
  clearSmartSectionState('xgboost');
  setSmartLoader('xgboost', true);
  return loadXGBoostTab(m).finally(() => setSmartLoader('xgboost', false));
}

async function loadMonths() {
  const select = document.getElementById('smart-forecast-month-select');
  if (!select) return;
  try {
    const months = await apiSmartGet('/smart/months');
    if (!months || !months.length) {
      showSmartSectionEmpty('xgboost', _t('No data for this period. Upload data and try again.'));
      return;
    }
    select.innerHTML = months.map(m => `<option value="${_smartEscapeHtml(m)}">${_smartEscapeHtml(m)}</option>`).join('');
    const last = months[months.length - 1];
    select.value = last;
    await refresh(last);
    loadHospitalForecast(_selectedHospital());
  } catch (e) {
    showSmartSectionError('xgboost', e.message);
  }
}

// ---- single-hospital forecast (moved from the analytics hospital mode) ----
function _selectedHospital() {
  return document.getElementById('smart-forecast-hospital-select')?.value || '';
}

function loadHospitalForecast(hospitalId) {
  if (!hospitalId) return Promise.resolve();
  clearSmartSectionState('hospital-forecast');
  setSmartLoader('hospital-forecast', true);
  // Anchored on the month this screen is showing ('all' → latest available).
  const month = getForecastMonth() || 'all';
  return apiSmartGet(`/smart/drilldown/${hospitalId}/${month}`)
    .then(d => {
      if (!d || d._error) {
        showSmartSectionError('hospital-forecast', (d && d.detail) || _t('Failed to load'));
        return;
      }
      if (d.empty && !d.anomaly) {
        showSmartSectionEmpty('hospital-forecast', d.message || _t('No data'));
        return;
      }
      clearSmartSectionState('hospital-forecast');
      renderHospitalForecast(d.forecast || {});
    })
    .catch(e => showSmartSectionError('hospital-forecast', e.message || _t('Failed to load')))
    .finally(() => setSmartLoader('hospital-forecast', false));
}

async function loadHospitals() {
  const select = document.getElementById('smart-forecast-hospital-select');
  if (!select) return;
  try {
    const hospitals = await apiSmartGet('/smart/hospitals');
    select.innerHTML = (hospitals || []).map(h =>
      `<option value="${h.id}">${_smartEscapeHtml(h.name)}</option>`).join('');
  } catch (e) { /* non-fatal */ }
}

// ---- screen wiring ----
let _wired = false;
function wireScreen() {
  if (_wired) return;
  _wired = true;

  // Collapsible section header — guarded per element because the analytics
  // entry binds every [data-smart-collapsible] header it finds in the DOM.
  document.querySelectorAll('[data-smart-collapsible]').forEach(header => {
    if (header.dataset.smartWired) return;
    header.dataset.smartWired = '1';
    header.addEventListener('click', () => {
      toggleSmartSection(header);
      // Re-opening a section re-runs its loaders (its Plotly charts were
      // purged when it collapsed).
      const card = header.closest('.smart-section-card');
      if (!card || !card.classList.contains('open')) return;
      if (header.getAttribute('data-smart-collapsible') === 'smart-hospital-forecast-section') {
        loadHospitalForecast(_selectedHospital());
      } else {
        refresh();
      }
    });
  });

  document.getElementById('smart-forecast-month-select')?.addEventListener('change', e => {
    refresh(e.target.value);
    loadHospitalForecast(_selectedHospital());
  });
  document.getElementById('smart-forecast-hospital-select')?.addEventListener('change', e => {
    loadHospitalForecast(e.target.value);
  });
  document.getElementById('smart-forecast-refresh')?.addEventListener('click', () => {
    const status = document.getElementById('smart-forecast-status');
    if (status) status.textContent = _t('Refreshed');
    refresh();
  });
  // Horizon select lives on this screen; advanced.js owns its change handler.
  initHorizonSelect();
}

// ---- startup ----
let _initDone = false;
function initSmartForecast() {
  if (!document.getElementById('smart-forecast-section')) return;
  wireScreen();
  if (_initDone) return; // idempotent — a language toggle re-runs init
  _initDone = true;
  loadMonths();
  loadHospitals();
  // Safety net: never leave a section spinner stuck visible.
  setTimeout(() => {
    setSmartLoader('xgboost', false);
    setSmartLoader('hospital-forecast', false);
  }, 8000);
}
window.initSmartForecast = initSmartForecast;
