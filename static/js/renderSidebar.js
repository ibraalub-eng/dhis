/**
 * renderSidebar.js — Fetch /menu and build sidebar DOM.
 * Replaces the static .tab-bar from index.html.
 */
import { switchTab } from './main.js';

var _sidebarData = null;
var _guideLabels = null;   // guide key -> bilingual title ('' is the index)
var _guideLang = null;

/**
 * Expose the server-side names (registry default or per-item rename) so the
 * breadcrumb and search results show the same name as the sidebar.
 */
function _applyLabels(groups) {
    var map = {};
    var defaults = {};
    (groups || []).forEach(function(group) {
        (group.items || []).forEach(function(item) {
            if (!item.tab_key) return;
            if (item.label) map[item.tab_key] = item.label;
            if (item.default_label) defaults[item.tab_key] = item.default_label;
        });
    });
    window._menuLabels = map;
    // Registry names: the screen title only follows a real rename, and this is
    // how the client tells an override apart from the default label.
    window._menuDefaults = defaults;
}

/**
 * Build a sidebar item element (.tab with data-tab + data-requires).
 */
function _buildItem(item) {
    var el = document.createElement('div');
    el.className = 'tab';
    el.setAttribute('data-tab', item.tab_key);
    el.setAttribute('role', 'tab');
    el.setAttribute('tabindex', '-1');
    el.setAttribute('aria-controls', 'tab-' + item.tab_key);
    if (item.permission) {
        el.setAttribute('data-requires', item.permission);
    }
    if (item.superadmin_only) {
        el.setAttribute('data-requires-superadmin', '');
    }
    el.innerHTML =
        '<span class="sidebar-item-icon">' + (item.icon || '') + '</span>' +
        '<span class="sidebar-item-label">' + (item.label || item.tab_key) + '</span>';
    if (item.tab_key === 'alerts') {
        el.style.position = 'relative';
    }
    el.addEventListener('click', function() { switchTab(item.tab_key); });
    return el;
}

// ── Guides submenu: the Data-section manuals, one entry per screen ──────────
// Every manual lives in static/js/guides/*.js and is read by the user-guide
// tab, so the entries hang off the User Guide item. That way a single guide
// can be opened straight from the menu instead of going through the hub page
// first. The modules are imported on demand so their text does not weigh down
// boot.

function _uiLang() {
    return localStorage.getItem('lang') === 'ar' ? 'ar' : 'en';
}

function _guideTitle(pair) {
    return pair ? (pair[_uiLang()] || pair.en || '') : '';
}

function _guideKeyFromHash() {
    var match = String(location.hash || '').match(/^#guide\/(?:data\/)?([a-z0-9-]+)\s*$/i);
    return match ? match[1] : '';
}

/** Keep the open guide highlighted after a click, a deep link or a back/forward. */
function _syncGuideActive() {
    var active = document.querySelector('#sidebarRoot .tab.active');
    var onReader = !!active && active.getAttribute('data-tab') === 'user-guide';
    var key = _guideKeyFromHash();
    document.querySelectorAll('#sidebarRoot .sidebar-subitem').forEach(function(el) {
        var isActive = onReader && el.getAttribute('data-guide-key') === key;
        el.classList.toggle('active', isActive);
        if (isActive) el.setAttribute('aria-current', 'page');
        else el.removeAttribute('aria-current');
    });
}

function _openGuide(key) {
    // switchTab writes ?screen=user-guide and drops any hash, so the anchor is
    // applied afterwards on the same history entry (the trail marker is kept,
    // so Back still walks screens). replaceState is used instead of assigning
    // location.hash because that navigation is refused in some embedded
    // browsers; the reader is then asked to render the new anchor.
    if (!document.querySelector('#sidebarRoot .tab[data-tab="user-guide"]')) {
        switchTab('guides');
        return;
    }
    switchTab('user-guide');
    var hash = key ? '#guide/data/' + key : '#guide';
    try {
        history.replaceState({ __tabtrail: true, tab: 'user-guide' }, '',
            '?screen=user-guide' + hash);
    } catch (e) {
        try { location.hash = hash; } catch (e2) { /* no anchor support */ }
    }
    try {
        window.dispatchEvent(new HashChangeEvent('hashchange'));
    } catch (e) { /* older browser: initUserGuide reads the hash on load */ }
    _syncGuideActive();
}

function _buildSubItem(key, icon, pair) {
    var el = document.createElement('div');
    el.className = 'sidebar-subitem';
    el.setAttribute('data-guide-key', key);
    el.setAttribute('role', 'link');
    el.setAttribute('tabindex', '0');
    el.setAttribute('title', _guideTitle(pair));
    var iconEl = document.createElement('span');
    iconEl.className = 'sidebar-subitem-icon';
    iconEl.setAttribute('aria-hidden', 'true');
    iconEl.textContent = icon || '📄';
    var labelEl = document.createElement('span');
    labelEl.className = 'sidebar-subitem-label';
    labelEl.textContent = _guideTitle(pair);
    el.appendChild(iconEl);
    el.appendChild(labelEl);
    el.addEventListener('click', function(event) {
        event.stopPropagation();   // the parent .tab opens the User Guide hub
        _openGuide(key);
    });
    el.addEventListener('keydown', function(event) {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        event.stopPropagation();
        _openGuide(key);
    });
    return el;
}

function _mountGuideSubmenu() {
    var host = document.querySelector('#sidebarRoot .tab[data-tab="user-guide"]');
    if (!host || host.querySelector('.sidebar-subitems')) return;
    Promise.all([import('./guide-data.js'), import('./guide-kit.js')]).then(function(mods) {
        var guides = (mods[0] && mods[0].DATA_GUIDES) || [];
        var meta = (mods[1] && mods[1].GUIDE_META) || {};
        var wrap = document.createElement('div');
        wrap.className = 'sidebar-subitems';
        wrap.setAttribute('role', 'group');
        _guideLabels = { '': meta.backToIndex || { en: 'All guides', ar: 'كل الأدلة' } };
        _guideLang = _uiLang();
        wrap.setAttribute('aria-label', meta.hubTitle ? _guideTitle(meta.hubTitle) : 'User guides');
        wrap.appendChild(_buildSubItem('', '📖', _guideLabels['']));
        guides.forEach(function(guide) {
            _guideLabels[guide.key] = guide.title;
            wrap.appendChild(_buildSubItem(guide.key, guide.icon, guide.title));
        });
        host.classList.add('has-subitems');
        host.appendChild(wrap);
        _syncGuideActive();
    }).catch(function(err) {
        console.warn('[sidebar] User Guide submenu unavailable:', err);
    });
}

/** Follow the language toggle: guide titles are bilingual pairs, not data-i18n. */
function _relabelGuideSubmenu() {
    var lang = _uiLang();
    if (lang === _guideLang) return;
    _guideLang = lang;
    if (!_guideLabels) return;
    document.querySelectorAll('#sidebarRoot .sidebar-subitem').forEach(function(el) {
        var pair = _guideLabels[el.getAttribute('data-guide-key')];
        if (!pair) return;
        var label = el.querySelector('.sidebar-subitem-label');
        if (label) label.textContent = _guideTitle(pair);
        el.setAttribute('title', _guideTitle(pair));
    });
}

/**
 * Build the full sidebar from /menu response.
 */
function _render(groups) {
    var root = document.getElementById('sidebarRoot');
    if (!root) return;
    root.innerHTML = '';
    groups.forEach(function(group) {
        var section = document.createElement('div');
        section.className = 'sidebar-group';
        section.setAttribute('data-group-id', group.id);

        var title = document.createElement('div');
        title.className = 'sidebar-group-title';
        title.innerHTML =
            '<span class="sidebar-group-icon">' + (group.icon || '') + '</span>' +
            '<span class="sidebar-group-label">' + (group.name || '') + '</span>' +
            '<span class="sidebar-group-chevron">▾</span>';
        title.addEventListener('click', function() {
            section.classList.toggle('collapsed');
        });
        section.appendChild(title);

        var itemsWrap = document.createElement('div');
        itemsWrap.className = 'sidebar-group-items';
        group.items.forEach(function(item) {
            itemsWrap.appendChild(_buildItem(item));
        });
        section.appendChild(itemsWrap);
        root.appendChild(section);
    });

    // Restore collapsed state from localStorage
    try {
        var saved = JSON.parse(localStorage.getItem('sidebar_collapsed_groups') || '[]');
        saved.forEach(function(gid) {
            var sec = root.querySelector('[data-group-id="' + gid + '"]');
            if (sec) sec.classList.add('collapsed');
        });
    } catch(e) {}

    // inject alert count badge target (updateAlertBadge() in alerts.js expects #alertBadge)
    if (!document.getElementById('alertBadge')) {
        var alertsItem = root.querySelector('.tab[data-tab="alerts"]');
        if (alertsItem) {
            var badge = document.createElement('span');
            badge.id = 'alertBadge';
            badge.className = 'count-badge';
            badge.style.display = 'none';
            badge.style.background = 'var(--accent-red)';
            badge.style.color = 'white';
            badge.style.marginInlineStart = 'auto';
            alertsItem.appendChild(badge);
        }
    }

    // Apply permission gating (hides unauthorized items)
    if (typeof window.applyPermissions === 'function') {
        window.applyPermissions();
    }
    // Highlight the active tab
    _highlightActive();
    // Renames can arrive after the header rendered (admin edits a name), so
    // refresh the breadcrumb with the current name of the open screen.
    var activeTab = document.querySelector('#sidebarRoot .tab.active');
    if (activeTab && typeof window.updateBreadcrumb === 'function') {
        window.updateBreadcrumb(activeTab.getAttribute('data-tab'));
    }
    // Translate the dynamically-built sidebar (group names + item labels)
    if (typeof window.applyLang === 'function') {
        window.applyLang();
    }
    _mountGuideSubmenu();
    // A rename saved from the admin panel must also update the open screen's
    // own title without a reload.
    var activeName = document.querySelector('#sidebarRoot .tab.active');
    if (activeName && typeof window.applyScreenTitle === 'function') {
        window.applyScreenTitle(activeName.getAttribute('data-tab'));
    }
}

function _highlightActive() {
    var active = document.querySelector('.tab.active');
    var tabName = active ? active.getAttribute('data-tab') : 'dashboard';
    document.querySelectorAll('#sidebarRoot .tab').forEach(function(el) {
        el.classList.toggle('active', el.getAttribute('data-tab') === tabName);
    });
    _syncGuideActive();
}

/**
 * Fetch /menu and render. Called once at boot.
 */
export async function renderSidebar() {
    try {
        // authFetch is the global installed by auth.js (same pattern api.js
        // uses): attaches the Bearer token, refreshes on 401, redirects to
        // login when the session is dead — instead of hand-rolled headers.
        var resp = await window.authFetch('/menu');
        if (!resp.ok) throw new Error(resp.status);
        var data = await resp.json();
        _sidebarData = data;
        _applyLabels(data.groups);
        _render(data.groups || []);
    } catch(e) {
        console.warn('[sidebar] Failed to load menu:', e);
        // Fallback: use static registry
        _renderFallback();
    }
    _applyCollapseState();
    _showToggleOnMobile();
}

/**
 * Fallback if /menu fails: use DEFAULT_GROUPS from index.html inline data or hardcoded.
 */
function _renderFallback() {
    // Hardcoded minimal fallback (matches seed defaults)
    var fallback = [
        {id:'fb-1', name:'Home', icon:'🏠', items:[{tab_key:'dashboard', label:'Dashboard', icon:'📊', permission:'dashboard.read'}]},
        {id:'fb-2', name:'Data', icon:'📊', items:[
            {tab_key:'upload', label:'Upload Data', icon:'📤', permission:'data.upload'},
            {tab_key:'indicator-tree', label:'Data Tree', icon:'🌳', permission:'settings.read'},
            {tab_key:'indicator-groups', label:'Data Group', icon:'🗂️', permission:'settings.read'},
            {tab_key:'indicators', label:'Indicators', icon:'📐', permission:'settings.read'},
            {tab_key:'rules-manager', label:'Validation Rules', icon:'📋', permission:'rules.read'},
        ]},
        {id:'fb-3', name:'Analysis', icon:'📈', items:[
            {tab_key:'analysis', label:'Hospital Comparisons', icon:'📈', permission:'analysis.read'},
            {tab_key:'smart-analytics', label:'Smart Analytics', icon:'🛡️', permission:'smart_analytics.read'},
            {tab_key:'smart-forecast', label:'Smart Forecast', icon:'🔮', permission:'smart_analytics.read'},
            {tab_key:'clinical', label:'Clinical Intelligence', icon:'🏥', permission:'clinical.read'},
            {tab_key:'root-cause', label:'Root Cause', icon:'🔍', permission:'root_cause.read'},
        ]},
        {id:'fb-4', name:'Oversight', icon:'🛡️', items:[
            {tab_key:'quality', label:'Quality Reports', icon:'✅', permission:'quality.read'},
            {tab_key:'quality-completeness', label:'Completeness', icon:'🧩', permission:'quality.read'},
            {tab_key:'quality-consistency', label:'Consistency', icon:'🔗', permission:'quality.read'},
            {tab_key:'quality-confidence', label:'Confidence', icon:'🎯', permission:'quality.read'},
            {tab_key:'quality-alerts', label:'Quality Alerts', icon:'🚨', permission:'quality_alerts.read'},
            {tab_key:'outliers', label:'Outlier Scan', icon:'⚠️', permission:'outliers.read'},
            {tab_key:'layered', label:'Outlier Diagnostics', icon:'🧱', permission:'analysis.read'},
            {tab_key:'alerts', label:'Validation Alerts', icon:'🔔', permission:'alerts.read'},
            {tab_key:'audit', label:'Audit Log', icon:'📝', permission:'audit.read'},
        ]},
        {id:'fb-5', name:'System', icon:'⚙️', items:[
            {tab_key:'admin', label:'System Control', icon:'⚙️', permission:'system.manage_users', superadmin_only:true},
            {tab_key:'guides', label:'Guides', icon:'📚', permission:'dashboard.read'},
            {tab_key:'settings', label:'Settings', icon:'🔧', permission:'system.manage_users'},
        ]},
    ];
    _render(fallback);
}

function _applyCollapseState() {
    var collapsed = localStorage.getItem('sidebar_collapsed') === '1';
    var sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.toggle('collapsed', collapsed);
    _updateChevrons(collapsed);
}

function _updateChevrons(collapsed) {
    var btn = document.querySelector('.sidebar-collapse-btn');
    if (btn) btn.textContent = collapsed ? '▶' : '◀';
}

window.toggleSidebarCollapse = function() {
    var sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    var collapsed = sidebar.classList.toggle('collapsed');
    localStorage.setItem('sidebar_collapsed', collapsed ? '1' : '0');
    _updateChevrons(collapsed);
};

window.toggleSidebar = function() {
    var sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    sidebar.classList.toggle('open');
};

function _showToggleOnMobile() {
    var btn = document.getElementById('sidebarToggle');
    if (btn && window.innerWidth <= 768) btn.style.display = '';
}

// Close the mobile drawer when a sidebar tab is selected
var _sidebarRoot = document.getElementById('sidebarRoot');
if (_sidebarRoot) {
    _sidebarRoot.addEventListener('click', function(e) {
        if (e.target.closest('.sidebar .tab')) {
            var sidebar = document.getElementById('sidebar');
            if (sidebar) sidebar.classList.remove('open');
        }
    });
}

// A guide opened by hash (deep link, link inside the reader, Back) stays in
// sync with the submenu highlight; the language toggle renames its entries.
window.addEventListener('hashchange', function() { _syncGuideActive(); });
if (typeof MutationObserver === 'function') {
    new MutationObserver(function() { _relabelGuideSubmenu(); })
        .observe(document.documentElement, { attributes: true, attributeFilter: ['dir', 'lang'] });
}

// Save group collapse state on click
document.addEventListener('click', function(e) {
    var title = e.target.closest('.sidebar-group-title');
    if (!title) return;
    var section = title.closest('.sidebar-group');
    if (!section) return;
    var gid = section.getAttribute('data-group-id');
    var saved = [];
    try { saved = JSON.parse(localStorage.getItem('sidebar_collapsed_groups') || '[]'); } catch(e) {}
    if (section.classList.contains('collapsed')) {
        if (saved.indexOf(gid) === -1) saved.push(gid);
    } else {
        saved = saved.filter(function(id) { return id !== gid; });
    }
    localStorage.setItem('sidebar_collapsed_groups', JSON.stringify(saved));
});