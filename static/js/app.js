import { API, apiGet, apiPost, apiPut, uploadedData, clearApiCache } from './api.js';
import { toggleLang, __, translateDOM, currentLang } from './i18n.js';
import { _saveUIState, _restoreUIState, showLoader, hideLoader, SwitchTab, switchTab, _tabInited } from './main.js';
import { confirmImport, cancelPreview, displayResults, filterPriorityTable, filterQualityReports, rerenderVal, rerenderAnom, loadQualityReports } from './upload.js';
import { loadOutliers, loadRuleFailures } from './outliers.js';
import { loadAlerts, updateAlertBadge } from './alerts.js';
import { refreshSavedFiles, toggleAllSaved, analyzeSelectedSaved, analyzeSingleSaved, deleteSelectedSaved } from './saved_files.js';
import { loadAllSettings, saveAllSettings, reanalyzeAll, showSettingsTab, saveAiSettings, loadAiSettings, onAiProviderChange, loadRulesManager, initRootCause, initDashboard, loadRootCause, loadDashboard, saveControlSettings, updateWeightDisplay, updateCfgDisplay, updateCfgVal, loadRankingTable, showHospitalScorecard, closeScorecard, goRootCause, renderRcTimelineChart } from './settings.js';
import { initTrends, initCompare, filterComparison, loadClinical, initClinical, openRootCauseForHospital, loadTrends, loadComparison, loadMLClusters, switchAnalysisMode, initAnalysis } from './validation.js';        import { runAnalysis, applyReportFilter, openBatchDetail, showRuleFailureDetail, showModal, closeModal } from './clinical.js';
import { expandAllTree, collapseAllTree, initIndicatorTree, loadIndicatorTree, saveTreeConfig, esc } from './tree.js';
import { _vbDragStart, _vbDragOver, _vbDragEnter, _vbDragLeave, _vbDrop, _vbRemoveFromZone, _vbOnPaletteSearch, _vbOnThresholdChange, _vbOnZThresholdChange, _vbOnFactorChange, ruleExprTemplate, toggleExprHelp, openRuleModal, closeRuleModal, saveRule, deleteRule } from './rules.js';
import { initAudit, loadAudit, downloadAuditJSON, downloadAuditCSV } from './audit.js';
import { loadHospitalsTab } from './hospitals.js';

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
window.loadAllSettings = loadAllSettings;
window.saveAllSettings = saveAllSettings;
window.reanalyzeAll = reanalyzeAll;
window.showSettingsTab = showSettingsTab;
window.saveAiSettings = saveAiSettings;
window.loadAiSettings = loadAiSettings;
window.saveControlSettings = saveControlSettings;
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
window.loadComparison = loadComparison;
window.loadMLClusters = loadMLClusters;        window.runAnalysis = runAnalysis;

window.applyReportFilter = applyReportFilter;
window.openBatchDetail = openBatchDetail;
window.showRuleFailureDetail = showRuleFailureDetail;
window.closeModal = closeModal;
window.showModal = showModal;
window.expandAllTree = expandAllTree;
window.collapseAllTree = collapseAllTree;
window.initIndicatorTree = initIndicatorTree;
window.loadIndicatorTree = loadIndicatorTree;
window.saveTreeConfig = saveTreeConfig;
window.esc = esc;
window.ruleExprTemplate = ruleExprTemplate;
window.saveRule = saveRule;
window.closeRuleModal = closeRuleModal;
window.openRuleModal = openRuleModal;
window.deleteRule = deleteRule;
window.toggleExprHelp = toggleExprHelp;
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
window.initAudit = initAudit;
window.loadAudit = loadAudit;
window.downloadAuditJSON = downloadAuditJSON;
window.downloadAuditCSV = downloadAuditCSV;
window.loadHospitalsTab = loadHospitalsTab;

// Bootstrap
document.addEventListener('DOMContentLoaded', async () => {
    // Auth guard — hard check for token BEFORE any data loading
    const _token = localStorage.getItem('access_token');
    if (!_token) {
        // No token at all — show login page, stop all init
        const lp = document.getElementById('login-page');
        if (lp) lp.style.display = 'flex';
        const hdr = document.querySelector('.header');
        if (hdr) hdr.style.display = 'none';
        const cc = document.querySelector('.container');
        if (cc) cc.style.display = 'none';
        return;
    }

    // Token exists — verify it via checkAuth (validates + refreshes if needed)
    if (typeof checkAuth === 'function') {
        const authenticated = await checkAuth();
        if (!authenticated) return; // login page shown, stop init
    }

    refreshSavedFiles();
    fetch(API() + '/reports/').then(r => r.json()).then(reports => {
        if (reports && reports.length > 0) {
            document.getElementById('resultsSection')?.classList.remove('hidden');
        }
    }).catch(() => {});
    const savedTab = localStorage.getItem('lastTab');
    if (savedTab && savedTab !== 'dashboard') {
        switchTab(savedTab);
    } else {
        switchTab('dashboard');
    }
});
