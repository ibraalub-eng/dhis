// app.js — Resilient bootstrap: one broken module should NOT block the whole app.
import { API, apiGet, apiPost, apiPut, uploadedData, clearApiCache } from './api.js';
import { toggleLang, __, translateDOM, currentLang } from './i18n.js';
import { _saveUIState, _restoreUIState, showLoader, hideLoader, SwitchTab, switchTab, _tabInited } from './main.js';

// ── Resilient imports: wrap each module in a try/catch fallback ──
// If a module fails to load, provide no-op stubs so the app still works.

async function _safeImport(label, importFn) {
  try {
    return await importFn();
  } catch (err) {
    console.error('[app] Failed to load module: ' + label, err);
    return null;
  }
}

const _upload = await _safeImport('upload', () => import('./upload.js'));
const _outliers = await _safeImport('outliers', () => import('./outliers.js'));
const _alerts = await _safeImport('alerts', () => import('./alerts.js'));
const _savedFiles = await _safeImport('savedFiles', () => import('./saved_files.js'));
const _settings = await _safeImport('settings', () => import('./settings.js'));
const _validation = await _safeImport('validation', () => import('./validation.js'));
const _clinical = await _safeImport('clinical', () => import('./clinical.js'));
const _tree = await _safeImport('tree', () => import('./tree.js'));
const _rules = await _safeImport('rules', () => import('./rules.js'));
const _audit = await _safeImport('audit', () => import('./audit.js'));
const _hospitals = await _safeImport('hospitals', () => import('./hospitals.js'));

// Helper: extract function or return no-op stub
function _fn(mod, name) { return mod && typeof mod[name] === 'function' ? mod[name] : function() {}; }
function _val(mod, name) { return mod ? mod[name] : undefined; }

const confirmImport = _fn(_upload, 'confirmImport');
const cancelPreview = _fn(_upload, 'cancelPreview');
const displayResults = _fn(_upload, 'displayResults');
const filterPriorityTable = _fn(_upload, 'filterPriorityTable');
const filterQualityReports = _fn(_upload, 'filterQualityReports');
const rerenderVal = _fn(_upload, 'rerenderVal');
const rerenderAnom = _fn(_upload, 'rerenderAnom');
const loadQualityReports = _fn(_upload, 'loadQualityReports');

const loadOutliers = _fn(_outliers, 'loadOutliers');
const loadRuleFailures = _fn(_outliers, 'loadRuleFailures');
const exportOutliersCSV = _fn(_outliers, 'exportOutliersCSV');
const exportRuleFailuresCSV = _fn(_outliers, 'exportRuleFailuresCSV');

const loadAlerts = _fn(_alerts, 'loadAlerts');
const updateAlertBadge = _fn(_alerts, 'updateAlertBadge');

const refreshSavedFiles = _fn(_savedFiles, 'refreshSavedFiles');
const toggleAllSaved = _fn(_savedFiles, 'toggleAllSaved');
const analyzeSelectedSaved = _fn(_savedFiles, 'analyzeSelectedSaved');
const analyzeSingleSaved = _fn(_savedFiles, 'analyzeSingleSaved');
const deleteSelectedSaved = _fn(_savedFiles, 'deleteSelectedSaved');

const loadAllSettings = _fn(_settings, 'loadAllSettings');
const saveAllSettings = _fn(_settings, 'saveAllSettings');
const reanalyzeAll = _fn(_settings, 'reanalyzeAll');
const showSettingsTab = _fn(_settings, 'showSettingsTab');
const saveAiSettings = _fn(_settings, 'saveAiSettings');
const loadAiSettings = _fn(_settings, 'loadAiSettings');
const onAiProviderChange = _fn(_settings, 'onAiProviderChange');
const loadRulesManager = _fn(_settings, 'loadRulesManager');
const initRootCause = _fn(_settings, 'initRootCause');
const initDashboard = _fn(_settings, 'initDashboard');
const loadRootCause = _fn(_settings, 'loadRootCause');
const loadDashboard = _fn(_settings, 'loadDashboard');
const updateWeightDisplay = _fn(_settings, 'updateWeightDisplay');
const updateCfgDisplay = _fn(_settings, 'updateCfgDisplay');
const updateCfgVal = _fn(_settings, 'updateCfgVal');
const loadRankingTable = _fn(_settings, 'loadRankingTable');
const showHospitalScorecard = _fn(_settings, 'showHospitalScorecard');
const closeScorecard = _fn(_settings, 'closeScorecard');
const goRootCause = _fn(_settings, 'goRootCause');
const renderRcTimelineChart = _fn(_settings, 'renderRcTimelineChart');

const initTrends = _fn(_validation, 'initTrends');
const initCompare = _fn(_validation, 'initCompare');
const filterComparison = _fn(_validation, 'filterComparison');
const loadClinical = _fn(_validation, 'loadClinical');
const initClinical = _fn(_validation, 'initClinical');
const openRootCauseForHospital = _fn(_validation, 'openRootCauseForHospital');
const loadTrends = _fn(_validation, 'loadTrends');
const loadComparison = _fn(_validation, 'loadComparison');
const loadMLClusters = _fn(_validation, 'loadMLClusters');
const switchAnalysisMode = _fn(_validation, 'switchAnalysisMode');
const initAnalysis = _fn(_validation, 'initAnalysis');

const runAnalysis = _fn(_clinical, 'runAnalysis');
const applyReportFilter = _fn(_clinical, 'applyReportFilter');
const openBatchDetail = _fn(_clinical, 'openBatchDetail');
const showRuleFailureDetail = _fn(_clinical, 'showRuleFailureDetail');
const showModal = _fn(_clinical, 'showModal');
const closeModal = _fn(_clinical, 'closeModal');

const expandAllTree = _fn(_tree, 'expandAllTree');
const collapseAllTree = _fn(_tree, 'collapseAllTree');
const initIndicatorTree = _fn(_tree, 'initIndicatorTree');
const loadIndicatorTree = _fn(_tree, 'loadIndicatorTree');
const saveTreeConfig = _fn(_tree, 'saveTreeConfig');
const esc = _fn(_tree, 'esc');

const _vbDragStart = _fn(_rules, '_vbDragStart');
const _vbDragOver = _fn(_rules, '_vbDragOver');
const _vbDragEnter = _fn(_rules, '_vbDragEnter');
const _vbDragLeave = _fn(_rules, '_vbDragLeave');
const _vbDrop = _fn(_rules, '_vbDrop');
const _vbRemoveFromZone = _fn(_rules, '_vbRemoveFromZone');
const _vbOnPaletteSearch = _fn(_rules, '_vbOnPaletteSearch');
const _vbOnThresholdChange = _fn(_rules, '_vbOnThresholdChange');
const _vbOnZThresholdChange = _fn(_rules, '_vbOnZThresholdChange');
const _vbOnFactorChange = _fn(_rules, '_vbOnFactorChange');
const ruleExprTemplate = _fn(_rules, 'ruleExprTemplate');
const toggleExprHelp = _fn(_rules, 'toggleExprHelp');
const openRuleModal = _fn(_rules, 'openRuleModal');
const closeRuleModal = _fn(_rules, 'closeRuleModal');
const saveRule = _fn(_rules, 'saveRule');
const deleteRule = _fn(_rules, 'deleteRule');

const initAudit = _fn(_audit, 'initAudit');
const loadAudit = _fn(_audit, 'loadAudit');
const downloadAuditJSON = _fn(_audit, 'downloadAuditJSON');
const downloadAuditCSV = _fn(_audit, 'downloadAuditCSV');

const loadHospitalsTab = _fn(_hospitals, 'loadHospitalsTab');

// Attach to window for onclick backward compatibility
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
window.confirmImport = confirmImport;
window.cancelPreview = cancelPreview;
window.displayResults = displayResults;
window.filterPriorityTable = filterPriorityTable;
window.filterQualityReports = filterQualityReports;
window.loadQualityReports = loadQualityReports;
window.rerenderVal = rerenderVal;
window.rerenderAnom = rerenderAnom;
window.refreshSavedFiles = refreshSavedFiles;
window.analyzeSelectedSaved = analyzeSelectedSaved;
window.analyzeSingleSaved = analyzeSingleSaved;
window.deleteSelectedSaved = deleteSelectedSaved;
window.toggleAllSaved = toggleAllSaved;
window.loadOutliers = loadOutliers;
window.updateAlertBadge = updateAlertBadge;
window.loadAlerts = loadAlerts;
window.loadRuleFailures = loadRuleFailures;
window.exportOutliersCSV = exportOutliersCSV;
window.exportRuleFailuresCSV = exportRuleFailuresCSV;
window.loadAllSettings = loadAllSettings;
window.saveAllSettings = saveAllSettings;
window.reanalyzeAll = reanalyzeAll;
window.showSettingsTab = showSettingsTab;
window.saveAiSettings = saveAiSettings;
window.loadAiSettings = loadAiSettings;
window.updateWeightDisplay = updateWeightDisplay;
window.updateCfgDisplay = updateCfgDisplay;
window.updateCfgVal = updateCfgVal;
window.loadRulesManager = loadRulesManager;
window.onAiProviderChange = onAiProviderChange;
window.loadRootCause = loadRootCause;
window.renderRcTimelineChart = renderRcTimelineChart;
window.initRootCause = initRootCause;
window.goRootCause = goRootCause;
window.loadDashboard = loadDashboard;
window.initDashboard = initDashboard;
window.loadRankingTable = loadRankingTable;
window.showHospitalScorecard = showHospitalScorecard;
window.closeScorecard = closeScorecard;
window.initTrends = initTrends;
window.initCompare = initCompare;
window.switchAnalysisMode = switchAnalysisMode;
window.initAnalysis = initAnalysis;
window.filterComparison = filterComparison;
window.loadClinical = loadClinical;
window.openRootCauseForHospital = openRootCauseForHospital;
window.initClinical = initClinical;
window.loadTrends = loadTrends;
window.runAnalysis = runAnalysis;
window.applyReportFilter = applyReportFilter;
window.openBatchDetail = openBatchDetail;
window.showRuleFailureDetail = showRuleFailureDetail;
window.showModal = showModal;
window.closeModal = closeModal;
window.expandAllTree = expandAllTree;
window.collapseAllTree = collapseAllTree;
window.initIndicatorTree = initIndicatorTree;
window.loadIndicatorTree = loadIndicatorTree;
window.saveTreeConfig = saveTreeConfig;
window.esc = esc;
window._vbDragStart = _vbDragStart;
window._vbDragOver = _vbDragOver;
window._vbDragEnter = _vbDragEnter;
window._vbDragLeave = _vbDragLeave;
window._vbDrop = _vbDrop;
window._vbRemoveFromZone = _vbRemoveFromZone;
window._vbOnPaletteSearch = _vbOnPaletteSearch;
window._vbOnThresholdChange = _vbOnThresholdChange;
window._vbOnZThresholdChange = _vbOnZThresholdChange;
window._vbOnFactorChange = _vbOnFactorChange;
window.ruleExprTemplate = ruleExprTemplate;
window.toggleExprHelp = toggleExprHelp;
window.openRuleModal = openRuleModal;
window.closeRuleModal = closeRuleModal;
window.saveRule = saveRule;
window.deleteRule = deleteRule;
window.initAudit = initAudit;
window.loadAudit = loadAudit;
window.downloadAuditJSON = downloadAuditJSON;
window.downloadAuditCSV = downloadAuditCSV;
window.loadHospitalsTab = loadHospitalsTab;

// Also re-export for any other modules that import from app.js
export { showLoader, hideLoader, SwitchTab, switchTab, esc, __, API, apiGet, apiPost, apiPut };

// ── Global error boundary: catch unhandled errors & show toast ──
window.addEventListener('error', function(e) {
  console.error('[app] Uncaught error:', e.message, e.filename, e.lineno);
});
window.addEventListener('unhandledrejection', function(e) {
  console.error('[app] Unhandled promise rejection:', e.reason);
});

// ── Bootstrap ──
document.addEventListener('DOMContentLoaded', async () => {
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

    let authenticated = false;
    if (typeof checkAuth === 'function') {
        authenticated = await checkAuth();
    } else {
        authenticated = true;
    }

    hideLoader();

    if (!authenticated) return;

    const rs = document.getElementById('resultsSection');
    if (rs) rs.classList.remove('hidden');

    refreshSavedFiles();
    localStorage.removeItem('lastTab');
    switchTab('dashboard');
  } catch (err) {
    console.error('[app] Bootstrap error:', err);
    hideLoader();
    const lp = document.getElementById('login-page');
    if (lp) lp.style.display = 'flex';
  }
});
