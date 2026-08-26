// app.js — Resilient bootstrap: one broken module should NOT block the whole app.
import { API, apiGet, apiPost, apiPut, uploadedData, clearApiCache } from './api.js';
import { toggleLang, __, translateDOM, currentLang } from './i18n.js';
import { _saveUIState, _restoreUIState, showLoader, hideLoader, SwitchTab, switchTab, _tabInited } from './main.js';

// Attach core functions immediately (no await needed)
window.API = API;
window.uploadedData = uploadedData;
window.apiGet = apiGet;
window.apiPost = apiPost;
window.apiPut = apiPut;
window.clearApiCache = clearApiCache;
window.toggleLang = toggleLang;
window.__ = __;
window.translateDOM = translateDOM;
window.currentLang = currentLang;
window.showLoader = showLoader;
window.hideLoader = hideLoader;
window._saveUIState = _saveUIState;
window._restoreUIState = _restoreUIState;
window._tabInited = _tabInited;
window.SwitchTab = SwitchTab;
window.switchTab = switchTab;

// Re-export for other modules
export { showLoader, hideLoader, SwitchTab, switchTab, __, API, apiGet, apiPost, apiPut };

// ── Stub: will be replaced by dynamic imports ──
const _stubs = {};
function _stub(name) { return function() { console.warn('[app] Module not loaded:', name); }; }

// Placeholders — replaced async by _loadModules()
window.confirmImport = _stub('confirmImport');
window.cancelPreview = _stub('cancelPreview');
window.displayResults = _stub('displayResults');
window.filterPriorityTable = _stub('filterPriorityTable');
window.filterQualityReports = _stub('filterQualityReports');
window.rerenderVal = _stub('rerenderVal');
window.rerenderAnom = _stub('rerenderAnom');
window.loadQualityReports = _stub('loadQualityReports');
window.loadOutliers = _stub('loadOutliers');
window.loadRuleFailures = _stub('loadRuleFailures');
window.exportOutliersCSV = _stub('exportOutliersCSV');
window.exportRuleFailuresCSV = _stub('exportRuleFailuresCSV');
window.loadAlerts = _stub('loadAlerts');
window.updateAlertBadge = _stub('updateAlertBadge');
window.refreshSavedFiles = _stub('refreshSavedFiles');
window.toggleAllSaved = _stub('toggleAllSaved');
window.analyzeSelectedSaved = _stub('analyzeSelectedSaved');
window.analyzeSingleSaved = _stub('analyzeSingleSaved');
window.deleteSelectedSaved = _stub('deleteSelectedSaved');
window.loadAllSettings = _stub('loadAllSettings');
window.saveAllSettings = _stub('saveAllSettings');
window.reanalyzeAll = _stub('reanalyzeAll');
window.showSettingsTab = _stub('showSettingsTab');
window.saveAiSettings = _stub('saveAiSettings');
window.loadAiSettings = _stub('loadAiSettings');
window.onAiProviderChange = _stub('onAiProviderChange');
window.loadRulesManager = _stub('loadRulesManager');
window.initRootCause = _stub('initRootCause');
window.initDashboard = _stub('initDashboard');
window.loadRootCause = _stub('loadRootCause');
window.loadDashboard = _stub('loadDashboard');
window.updateWeightDisplay = _stub('updateWeightDisplay');
window.updateCfgDisplay = _stub('updateCfgDisplay');
window.updateCfgVal = _stub('updateCfgVal');
window.loadRankingTable = _stub('loadRankingTable');
window.showHospitalScorecard = _stub('showHospitalScorecard');
window.closeScorecard = _stub('closeScorecard');
window.goRootCause = _stub('goRootCause');
window.renderRcTimelineChart = _stub('renderRcTimelineChart');
window.initTrends = _stub('initTrends');
window.initCompare = _stub('initCompare');
window.filterComparison = _stub('filterComparison');
window.loadClinical = _stub('loadClinical');
window.initClinical = _stub('initClinical');
window.openRootCauseForHospital = _stub('openRootCauseForHospital');
window.loadTrends = _stub('loadTrends');
window.loadComparison = _stub('loadComparison');
window.loadMLClusters = _stub('loadMLClusters');
window.switchAnalysisMode = _stub('switchAnalysisMode');
window.initAnalysis = _stub('initAnalysis');
window.runAnalysis = _stub('runAnalysis');
window.applyReportFilter = _stub('applyReportFilter');
window.openBatchDetail = _stub('openBatchDetail');
window.showRuleFailureDetail = _stub('showRuleFailureDetail');
window.showModal = _stub('showModal');
window.closeModal = _stub('closeModal');
window.expandAllTree = _stub('expandAllTree');
window.collapseAllTree = _stub('collapseAllTree');
window.initIndicatorTree = _stub('initIndicatorTree');
window.loadIndicatorTree = _stub('loadIndicatorTree');
window.saveTreeConfig = _stub('saveTreeConfig');
window.esc = _stub('esc');
window._vbDragStart = _stub('_vbDragStart');
window._vbDragOver = _stub('_vbDragOver');
window._vbDragEnter = _stub('_vbDragEnter');
window._vbDragLeave = _stub('_vbDragLeave');
window._vbDrop = _stub('_vbDrop');
window._vbRemoveFromZone = _stub('_vbRemoveFromZone');
window._vbOnPaletteSearch = _stub('_vbOnPaletteSearch');
window._vbOnThresholdChange = _stub('_vbOnThresholdChange');
window._vbOnZThresholdChange = _stub('_vbOnZThresholdChange');
window._vbOnFactorChange = _stub('_vbOnFactorChange');
window.ruleExprTemplate = _stub('ruleExprTemplate');
window.toggleExprHelp = _stub('toggleExprHelp');
window.openRuleModal = _stub('openRuleModal');
window.closeRuleModal = _stub('closeRuleModal');
window.saveRule = _stub('saveRule');
window.deleteRule = _stub('deleteRule');
window.initAudit = _stub('initAudit');
window.loadAudit = _stub('loadAudit');
window.downloadAuditJSON = _stub('downloadAuditJSON');
window.downloadAuditCSV = _stub('downloadAuditCSV');
window.loadHospitalsTab = _stub('loadHospitalsTab');

// ── Load modules async (non-blocking, replaces stubs) ──
function _bind(mod, name) {
  if (mod && typeof mod[name] === 'function') window[name] = mod[name];
}
function _val(mod, name) { return mod ? mod[name] : undefined; }

async function _loadModules() {
  const mods = [
    ['upload',      () => import('./upload.js')],
    ['outliers',    () => import('./outliers.js')],
    ['alerts',      () => import('./alerts.js')],
    ['savedFiles',  () => import('./saved_files.js')],
    ['settings',    () => import('./settings.js')],
    ['validation',  () => import('./validation.js')],
    ['clinical',    () => import('./clinical.js')],
    ['tree',        () => import('./tree.js')],
    ['rules',       () => import('./rules.js')],
    ['audit',       () => import('./audit.js')],
    ['hospitals',   () => import('./hospitals.js')],
  ];

  const loaded = [];
  const failed = [];

  for (const [label, fn] of mods) {
    try {
      const mod = await fn();
      loaded.push(label);
      _bindAll(mod, label);
    } catch (err) {
      failed.push(label + ': ' + err.message);
      console.warn('[app] Module failed: ' + label, err.message);
    }
  }

  // Store status for debug panel
  window._moduleStatus = { loaded, failed };

  if (failed.length > 0) {
    console.warn('[app] ' + failed.length + ' module(s) failed to load: ' + failed.join(', '));
  }
}

function _bindAll(mod, label) {
  if (!mod) return;
  switch (label) {
    case 'upload':
      _bind(mod, 'confirmImport'); _bind(mod, 'cancelPreview'); _bind(mod, 'displayResults');
      _bind(mod, 'filterPriorityTable'); _bind(mod, 'filterQualityReports');
      _bind(mod, 'rerenderVal'); _bind(mod, 'rerenderAnom'); _bind(mod, 'loadQualityReports');
      break;
    case 'outliers':
      _bind(mod, 'loadOutliers'); _bind(mod, 'loadRuleFailures');
      _bind(mod, 'exportOutliersCSV'); _bind(mod, 'exportRuleFailuresCSV');
      break;
    case 'alerts':
      _bind(mod, 'loadAlerts'); _bind(mod, 'updateAlertBadge');
      break;
    case 'savedFiles':
      _bind(mod, 'refreshSavedFiles'); _bind(mod, 'toggleAllSaved');
      _bind(mod, 'analyzeSelectedSaved'); _bind(mod, 'analyzeSingleSaved');
      _bind(mod, 'deleteSelectedSaved');
      break;
    case 'settings':
      _bind(mod, 'loadAllSettings'); _bind(mod, 'saveAllSettings'); _bind(mod, 'reanalyzeAll');
      _bind(mod, 'showSettingsTab'); _bind(mod, 'saveAiSettings'); _bind(mod, 'loadAiSettings');
      _bind(mod, 'onAiProviderChange'); _bind(mod, 'loadRulesManager');
      _bind(mod, 'initRootCause'); _bind(mod, 'initDashboard');
      _bind(mod, 'loadRootCause'); _bind(mod, 'loadDashboard');
      _bind(mod, 'updateWeightDisplay'); _bind(mod, 'updateCfgDisplay'); _bind(mod, 'updateCfgVal');
      _bind(mod, 'loadRankingTable'); _bind(mod, 'showHospitalScorecard');
      _bind(mod, 'closeScorecard'); _bind(mod, 'goRootCause'); _bind(mod, 'renderRcTimelineChart');
      break;
    case 'validation':
      _bind(mod, 'initTrends'); _bind(mod, 'initCompare'); _bind(mod, 'filterComparison');
      _bind(mod, 'loadClinical'); _bind(mod, 'initClinical');
      _bind(mod, 'openRootCauseForHospital'); _bind(mod, 'loadTrends');
      _bind(mod, 'loadComparison'); _bind(mod, 'loadMLClusters');
      _bind(mod, 'switchAnalysisMode'); _bind(mod, 'initAnalysis');
      break;
    case 'clinical':
      _bind(mod, 'runAnalysis'); _bind(mod, 'applyReportFilter');
      _bind(mod, 'openBatchDetail'); _bind(mod, 'showRuleFailureDetail');
      _bind(mod, 'showModal'); _bind(mod, 'closeModal');
      break;
    case 'tree':
      _bind(mod, 'expandAllTree'); _bind(mod, 'collapseAllTree');
      _bind(mod, 'initIndicatorTree'); _bind(mod, 'loadIndicatorTree');
      _bind(mod, 'saveTreeConfig'); _bind(mod, 'esc');
      break;
    case 'rules':
      _bind(mod, '_vbDragStart'); _bind(mod, '_vbDragOver'); _bind(mod, '_vbDragEnter');
      _bind(mod, '_vbDragLeave'); _bind(mod, '_vbDrop'); _bind(mod, '_vbRemoveFromZone');
      _bind(mod, '_vbOnPaletteSearch'); _bind(mod, '_vbOnThresholdChange');
      _bind(mod, '_vbOnZThresholdChange'); _bind(mod, '_vbOnFactorChange');
      _bind(mod, 'ruleExprTemplate'); _bind(mod, 'toggleExprHelp');
      _bind(mod, 'openRuleModal'); _bind(mod, 'closeRuleModal');
      _bind(mod, 'saveRule'); _bind(mod, 'deleteRule');
      break;
    case 'audit':
      _bind(mod, 'initAudit'); _bind(mod, 'loadAudit');
      _bind(mod, 'downloadAuditJSON'); _bind(mod, 'downloadAuditCSV');
      break;
    case 'hospitals':
      _bind(mod, 'loadHospitalsTab');
      break;
  }
}

// Start loading modules immediately (non-blocking)
_loadModules();

// ── Global error boundary ──
window.addEventListener('error', function(e) {
  console.error('[app] Uncaught error:', e.message, e.filename, e.lineno);
});
window.addEventListener('unhandledrejection', function(e) {
  console.error('[app] Unhandled promise rejection:', e.reason);
});

// ── Bootstrap: runs immediately, doesn't wait for modules ──
(async function bootstrap() {
  try {
    const _token = localStorage.getItem('access_token') || sessionStorage.getItem('access_token');
    if (!_token) {
        const lp = document.getElementById('login-page');
        if (lp) lp.style.display = 'flex';
        const hdr = document.querySelector('.header');
        if (hdr) hdr.style.display = 'none';
        const cc = document.querySelector('.container');
        if (cc) cc.style.display = 'none';
        return;
    }

    showLoader('Authenticating...');

    // Safety: always hide loader after 5s even if checkAuth hangs
    var _loaderTimeout = setTimeout(function() { hideLoader(); }, 5000);

    let authenticated = false;
    if (typeof checkAuth === 'function') {
        authenticated = await checkAuth();
    } else {
        authenticated = true;
    }

    clearTimeout(_loaderTimeout);
    hideLoader();

    if (!authenticated) return;

    const rs = document.getElementById('resultsSection');
    if (rs) rs.classList.remove('hidden');

    // Call function when module loads (retry up to 30 times = ~3s)
    function _whenReady(fn, name, retries) {
        retries = retries || 30;
        if (typeof fn === 'function' && fn.toString().indexOf('Module not loaded') === -1) {
            fn();
        } else if (retries > 0) {
            setTimeout(function() { _whenReady(fn, name, retries - 1); }, 100);
        }
    }
    _whenReady(refreshSavedFiles, 'refreshSavedFiles');
    localStorage.removeItem('lastTab');
    switchTab('dashboard');
  } catch (err) {
    console.error('[app] Bootstrap error:', err);
    hideLoader();
    const lp = document.getElementById('login-page');
    if (lp) lp.style.display = 'flex';
  }
})();
