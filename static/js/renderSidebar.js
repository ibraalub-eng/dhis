/**
 * renderSidebar.js — Fetch /menu and build sidebar DOM.
 * Replaces the static .tab-bar from index.html.
 */
import { switchTab } from './main.js';

var _sidebarData = null;

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
    // Translate the dynamically-built sidebar (group names + item labels)
    if (typeof window.applyLang === 'function') {
        window.applyLang();
    }
}

function _highlightActive() {
    var active = document.querySelector('.tab.active');
    var tabName = active ? active.getAttribute('data-tab') : 'dashboard';
    document.querySelectorAll('#sidebarRoot .tab').forEach(function(el) {
        el.classList.toggle('active', el.getAttribute('data-tab') === tabName);
    });
}

/**
 * Fetch /menu and render. Called once at boot.
 */
export async function renderSidebar() {
    try {
        var token = (typeof window.getAccessToken === 'function' && window.getAccessToken()) || localStorage.getItem('access_token') || '';
        var resp = await fetch('/menu', { headers: { 'Authorization': 'Bearer ' + token } });
        if (!resp.ok) throw new Error(resp.status);
        var data = await resp.json();
        _sidebarData = data;
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
            {tab_key:'indicator-tree', label:'Indicator Tree', icon:'🌳', permission:'settings.read'},
            {tab_key:'rules-manager', label:'Rules Manager', icon:'📋', permission:'rules.read'},
        ]},
        {id:'fb-3', name:'Analysis', icon:'📈', items:[
            {tab_key:'analysis', label:'Comparative Analysis', icon:'📈', permission:'analysis.read'},
            {tab_key:'smart-analytics', label:'Smart Analytics', icon:'🛡️', permission:'smart_analytics.read'},
            {tab_key:'clinical', label:'Clinical Intelligence', icon:'🏥', permission:'clinical.read'},
            {tab_key:'root-cause', label:'Root Cause', icon:'🔍', permission:'root_cause.read'},
        ]},
        {id:'fb-4', name:'Oversight', icon:'🛡️', items:[
            {tab_key:'quality', label:'Quality Reports', icon:'✅', permission:'quality.read'},
            {tab_key:'outliers', label:'Outliers', icon:'⚠️', permission:'outliers.read'},
            {tab_key:'alerts', label:'Alerts', icon:'🔔', permission:'alerts.read'},
            {tab_key:'audit', label:'Audit Log', icon:'📝', permission:'audit.read'},
        ]},
        {id:'fb-5', name:'System', icon:'⚙️', items:[
            {tab_key:'admin', label:'System Control', icon:'⚙️', permission:'system.manage_users', superadmin_only:true},
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