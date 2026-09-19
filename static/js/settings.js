        import { API, apiGet, apiPost, apiPut, clearApiCache } from './api.js';

import { DataTable, scoreBadge, trendIcon, confidenceBar } from './table-utils.js';
        import { __ } from './i18n.js';
        import { esc } from './tree.js';
        import { _saveUIState, _restoreUIState, SwitchTab, _tabInited } from './main.js';
import { toastSuccess, toastError, toastWarning } from './toast.js';
import { confirmDestructive, confirmWarning } from './confirm-modal.js';

        // ── Progressive Disclosure: auto-wrap <h3> in collapsible sections ──
        const _SECTION_ICONS = {
            'Quality Score': '📊', 'Outlier': '📈', 'Confidence Signal': '🎯',
            'Confidence Level': '🎚️', 'Global Z-Score': '📐', 'Rule': '📏',
            'Clinical': '🩺', 'Risk': '⚠️', 'Trend': '📉', 'Rate': '📈',
            'Rate Benchmark': '📊', 'AI': '🤖', 'ML': '🧠', 'My Profile': '👤',
            'Change': '🔑', 'Password': '🔑', 'Account': '👤'
        };
        function _findIcon(text) {
            for (var key in _SECTION_ICONS) {
                if (text.indexOf(key) !== -1) return _SECTION_ICONS[key];
            }
            return '⚙️';
        }

        function initCollapsibleSections() {
            // Collapsible structure is now built into settings.html
            // Just ensure click handlers are attached to any buttons that lack them
            document.querySelectorAll('.settings-section-header').forEach(function(btn) {
                if (btn.getAttribute('onclick')) return; // already has handler
                btn.addEventListener('click', function() {
                    this.parentElement.classList.toggle('open');
                });
            });
        }
        // Expose for admin panel and other modules
        window.initCollapsibleSections = initCollapsibleSections;

// ── Rules Manager + settings/dashboard helpers (moved to rules-manager.js) ──
// Re-exported so app.js _bind() and existing importers keep working; new code
// should import from './rules-manager.js' directly.
import { showSettingsTab } from './rules-manager.js';
export {
    rulesManagerData, updateWeightDisplay, updateCfgDisplay, updateCfgVal,
    showSettingsTab, renderRcTimeline, renderRcTimelineChart,
    loadRootCause, initRootCause, goRootCause, applyRootCauseContext,
    populateMonthSelect, loadRankingTable, showHospitalScorecard, closeScorecard,
    loadDashboard, initDashboard, loadAllSettings, saveAllSettings, reanalyzeAll,
    loadAiSettings, saveAiSettings, onAiProviderChange,
    loadRulesManager, saveRulesManager, EXPR_EXPLANATIONS, exprTypeLabel,
} from './rules-manager.js';

// ---- Self Change Password ----
window.changeSelfPassword = async function() {
    var curEl = document.getElementById('selfPwCurrent');
    var newEl = document.getElementById('selfPwNew');
    var confirmEl = document.getElementById('selfPwConfirm');
    var errEl = document.getElementById('selfPwError');
    var okEl = document.getElementById('selfPwSuccess');

    errEl.style.display = 'none';
    okEl.style.display = 'none';

    var cur = curEl ? curEl.value : '';
    var nw = newEl ? newEl.value : '';
    var cf = confirmEl ? confirmEl.value : '';

    if (!cur) { errEl.textContent = 'Current password is required'; errEl.style.display = 'block'; return; }
    if (!nw) { errEl.textContent = 'New password is required'; errEl.style.display = 'block'; return; }
    if (nw.length < 6) { errEl.textContent = 'Password must be at least 6 characters'; errEl.style.display = 'block'; return; }
    if (nw === cur) { errEl.textContent = 'New password must be different from current'; errEl.style.display = 'block'; return; }
    if (nw !== cf) { errEl.textContent = 'Passwords do not match'; errEl.style.display = 'block'; return; }

    try {
        var token = getAccessToken();
        var resp = await authFetch(API() + '/auth/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
            body: JSON.stringify({ current_password: cur, new_password: nw, confirm_password: cf })
        });
        var data = await resp.json();
        if (!resp.ok) {
            errEl.textContent = data.detail || 'Failed to change password';
            errEl.style.display = 'block';
            return;
        }
        okEl.textContent = '✅ Password changed successfully! You can continue using the app.';
        okEl.style.display = 'block';
        curEl.value = '';
        newEl.value = '';
        confirmEl.value = '';
    } catch(e) {
        errEl.textContent = 'Network error';
        errEl.style.display = 'block';
    }
};

