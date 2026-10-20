// smart-forecast.js — ES-module entry: wires the Smart Forecast (prediction) screen.
//
// The screen owns its month + horizon controls and is split into lazy sub-tabs
// (models / quality / signals / indicator / hospital). Opening the tab loads
// only the month + hospital lists; each panel fetches its data on first
// activation. Nothing is registered in core's shared section registry, so a
// month change on the analytics screen never refetches this screen — and never
// repaints charts into a hidden tab.
//
// The prediction section (XGBoost forecasts, trajectory, accuracy, tracking,
// early-warning signals, per-indicator forecast, walk-forward, scatter) and the
// single-hospital forecast were moved here from the Smart Analytics screen.

import { apiSmartGet, setSmartLoader, showSmartSectionError,
         showSmartSectionEmpty, clearSmartSectionState,
         _smartEscapeHtml, _t } from './smart/core.js';
import { loadXGBoostTab, loadForecastQuality, loadForecastSignalsPanel,
         initHorizonSelect, getForecastMonth, setForecastMonth,
         initIndicatorForecast, renderActionBoard } from './smart/advanced.js';
import { renderHospitalForecast } from './smart/hospital.js';

// ── Lazy sub-tabs ──────────────────────────────────────────────────────────
// Each panel is loaded the first time it is activated; switching back to a
// loaded panel costs nothing. Horizon-dependent panels are marked stale when
// the month/horizon changes and reload the next time they are shown.
const HORIZON_PANELS = new Set(['models', 'quality', 'signals', 'indicator', 'actions']);
const _loaded = new Set();
let _active = 'models';

function _selectedHospital() {
  return document.getElementById('smart-forecast-hospital-select')?.value || '';
}

// ── single-hospital forecast (moved from the analytics hospital mode) ──
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

function loadActionBoard() {
  const month = getForecastMonth() || 'all';
  const horizonSelect = document.getElementById('smart-horizon-select');
  let horizon = 3;
  if (horizonSelect && horizonSelect.value) {
    const v = parseInt(horizonSelect.value, 10);
    if (v === 1 || v === 3 || v === 6 || v === 9 || v === 12) horizon = v;
  }
  return apiSmartGet(`/smart/forecast-action-board/${month}?horizon=${horizon}`)
    .then(d => renderActionBoard(d))
    .catch(e => showSmartSectionError('smart-action-board', e.message || _t('Failed to load')));
}

// One loader per panel — called only when that panel is (re)activated.
const _panelLoaders = {
  models: () => loadXGBoostTab(getForecastMonth()),
  quality: () => loadForecastQuality(getForecastMonth()),
  signals: () => loadForecastSignalsPanel(getForecastMonth()),
  indicator: () => initIndicatorForecast(),
  actions: () => loadActionBoard(),
  hospital: () => loadHospitalForecast(_selectedHospital()),
};

function _loadForecastPanel(name) {
  const loader = _panelLoaders[name];
  if (!loader) return Promise.resolve();
  _loaded.add(name);
  if (name === 'models') setSmartLoader('xgboost', true);
  return Promise.resolve(loader()).finally(() => {
    if (name === 'models') setSmartLoader('xgboost', false);
  });
}

function _showPanel(name) {
  document.querySelectorAll('.smart-forecast-panel[data-forecast-panel]').forEach(p => {
    p.style.display = (p.dataset.forecastPanel === name) ? '' : 'none';
  });
  document.querySelectorAll('.smart-forecast-tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.forecastTab === name);
  });
}

function _activate(name) {
  _active = name;
  _showPanel(name);
  if (!_loaded.has(name)) _loadForecastPanel(name);
}

// Drop the loaded flag for every panel the predicate accepts and refresh the
// visible one; the others reload lazily when the user next opens them.
function _resetPanels(predicate) {
  [..._loaded].forEach(n => { if (predicate(n)) _loaded.delete(n); });
  if (predicate(_active)) _loadForecastPanel(_active);
}

// ── screen bootstrap ──
async function loadMonths() {
  const select = document.getElementById('smart-forecast-month-select');
  if (!select) return;
  try {
    const months = await apiSmartGet('/smart/months');
    select.innerHTML = (months || []).map(m =>
      `<option value="${_smartEscapeHtml(m)}">${_smartEscapeHtml(m)}</option>`).join('');
    if (!months || !months.length) {
      showSmartSectionEmpty('xgboost', _t('No data for this period. Upload data and try again.'));
      return;
    }
    const latest = months[months.length - 1];
    select.value = latest;
    setForecastMonth(latest);
    _loadForecastPanel(_active);   // lazy: only the visible panel
  } catch (e) {
    showSmartSectionError('xgboost', e.message);
  }
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

// ── screen wiring (idempotent) ──
let _wired = false;
function wireScreen() {
  if (_wired) return;
  _wired = true;

  document.querySelectorAll('.smart-forecast-tab-btn[data-forecast-tab]').forEach(btn => {
    btn.addEventListener('click', () => _activate(btn.dataset.forecastTab));
  });
  document.getElementById('smart-forecast-month-select')?.addEventListener('change', e => {
    setForecastMonth(e.target.value);
    _resetPanels(() => true);   // every panel is anchored on the month
  });
  document.getElementById('smart-forecast-hospital-select')?.addEventListener('change', e => {
    if (_active === 'hospital') loadHospitalForecast(e.target.value);
    else _loaded.delete('hospital');   // reload on next activation
  });
  document.getElementById('smart-forecast-refresh')?.addEventListener('click', () => {
    const status = document.getElementById('smart-forecast-status');
    if (status) status.textContent = _t('Refreshed');
    _loaded.delete(_active);
    _loadForecastPanel(_active);
  });
  // Horizon select lives on this screen; advanced.js owns its change handler
  // and broadcasts the event so the visible horizon-dependent panel reloads.
  initHorizonSelect();
  document.addEventListener('smart-forecast:horizon-change', () => {
    _resetPanels(n => HORIZON_PANELS.has(n));
  });
}

// ── startup ──
let _initDone = false;
function initSmartForecast() {
  if (!document.getElementById('smart-forecast-section')) return;
  wireScreen();
  // Language toggle re-runs init: refresh labels on the already-open panel.
  if (_loaded.has('indicator')) initIndicatorForecast().catch(() => {});
  if (_initDone) return;
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
