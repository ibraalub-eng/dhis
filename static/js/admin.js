// admin.js — user management panel for superadmins.

// Toast notifications (inline for non-module script)
function _toastContainer() {
  var c = document.getElementById('toast-container');
  if (!c) { c = document.createElement('div'); c.id = 'toast-container'; c.style.cssText = 'position:fixed;top:1rem;right:1rem;z-index:99999;display:flex;flex-direction:column;gap:0.5rem;max-width:380px;pointer-events:none;'; document.body.appendChild(c); }
  return c;
}
function toastSuccess(m) { _toastShow('success', m); }
function toastError(m) { _toastShow('error', m); }
function toastWarning(m) { _toastShow('warning', m); }
function _toastShow(type, msg) {
  var c = _toastContainer();
  var icons = {success:'✅',error:'❌',warning:'⚠️'};
  var colors = {success:{bg:'#f0fdf4',brd:'#86efac',txt:'#166534'},error:{bg:'#fef2f2',brd:'#fca5a5',txt:'#991b1b'},warning:{bg:'#fffbeb',brd:'#fcd34d',txt:'#92400e'}};
  var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  if (isDark) colors = {success:{bg:'#14532d',brd:'#166534',txt:'#86efac'},error:{bg:'#7f1d1d',brd:'#991b1b',txt:'#fca5a5'},warning:{bg:'#78350f',brd:'#92400e',txt:'#fcd34d'}};
  var co = colors[type] || colors.info;
  var el = document.createElement('div');
  el.style.cssText = 'pointer-events:auto;display:flex;align-items:flex-start;gap:0.5rem;padding:0.7rem 1rem;border-radius:10px;border-left:4px solid '+co.brd+';background:'+co.bg+';color:'+co.txt+';box-shadow:0 4px 16px rgba(0,0,0,0.15);font-size:0.85rem;animation:toast-in 0.3s ease-out;cursor:pointer;word-break:break-word;';
  el.innerHTML = '<span style="font-size:1rem;flex-shrink:0;">'+(icons[type]||'')+'</span><span style="flex:1;">'+msg+'</span><span style="font-size:0.7rem;opacity:0.5;cursor:pointer;" onclick="this.parentElement.remove()">✕</span>';
  el.addEventListener('click', function(){ el.remove(); });
  c.appendChild(el);
  setTimeout(function(){ if(el.parentElement){el.style.animation='toast-out 0.3s ease-in forwards';setTimeout(function(){el.remove();},300);} }, type==='error'?6000:3500);
}

(function() {
  var API_BASE = '';
  API_BASE = '';

  function _adminKpi(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = String(value);
  }

  // Self-contained styled confirm dialog (reuses shared .cm-* CSS).
  var _adminModalEl = null;
  var _adminResolve = null;
  function _adminEnsureModal() {
    if (_adminModalEl) return _adminModalEl;
    _adminModalEl = document.getElementById('confirm-modal-overlay') || document.createElement('div');
    if (!_adminModalEl.parentNode) {
      _adminModalEl.id = 'confirm-modal-overlay';
      _adminModalEl.className = 'cm-overlay';
      _adminModalEl.innerHTML = '<div class="cm-dialog"><div class="cm-header"><span class="cm-icon"></span><span class="cm-title"></span></div><div class="cm-body"></div><div class="cm-actions"></div></div>';
      document.body.appendChild(_adminModalEl);
      _adminModalEl.addEventListener('click', function(e) {
        if (e.target === _adminModalEl) _adminClose(false);
      });
    }
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && _adminModalEl && _adminModalEl.classList.contains('cm-visible')) _adminClose(false);
    });
    return _adminModalEl;
  }
  function _adminClose(result) {
    if (_adminModalEl) _adminModalEl.classList.remove('cm-visible');
    if (_adminResolve) { _adminResolve(result); _adminResolve = null; }
  }
  function _adminOpen(opts) {
    var modal = _adminEnsureModal();
    var icon = opts.danger ? '⚠️' : opts.warning ? '⚠️' : opts.info ? 'ℹ️' : '❓';
    var titleColor = opts.danger ? 'var(--accent-red)' : opts.warning ? 'var(--accent-orange)' : 'var(--accent-blue)';
    modal.querySelector('.cm-icon').textContent = icon;
    modal.querySelector('.cm-title').innerHTML = '<span style="color:' + titleColor + '">' + (opts.title || (__('Confirm'))) + '</span>';
    var bodyHtml = '<p>' + (opts.message || ('Are you sure?')) + '</p>';
    if (opts.details) bodyHtml += '<p class="cm-details">' + opts.details + '</p>';
    if (opts.confirmText) {
      bodyHtml += '<div class="cm-confirm-input"><input type="text" id="cm-confirm-typing" placeholder="Type "' + opts.confirmText + '" to confirm" autocomplete="off"></div>';
    }
    modal.querySelector('.cm-body').innerHTML = bodyHtml;
    modal.querySelector('.cm-actions').innerHTML =
      '<button class="cm-btn cm-cancel">' + (opts.cancelLabel || __('Cancel')) + '</button>' +
      '<button class="cm-btn cm-ok ' + (opts.danger ? 'cm-btn-danger' : opts.warning ? 'cm-btn-warning' : '') + '">' + (opts.okLabel || __('Confirm')) + '</button>';
    var okBtn = modal.querySelector('.cm-ok');
    var cancelBtn = modal.querySelector('.cm-cancel');
    var input = modal.querySelector('#cm-confirm-typing');
    if (opts.confirmText && input) {
      okBtn.disabled = true;
      input.addEventListener('input', function() {
        okBtn.disabled = input.value.toUpperCase() !== opts.confirmText.toUpperCase();
      });
      setTimeout(function() { input.focus(); }, 100);
    } else {
      setTimeout(function() { okBtn.focus(); }, 100);
    }
    okBtn.addEventListener('click', function() { _adminClose(true); });
    cancelBtn.addEventListener('click', function() { _adminClose(false); });
    modal.classList.add('cm-visible');
  }
  window.confirmAction = function(opts) {
    return new Promise(function(resolve) { _adminResolve = resolve; _adminOpen(opts); });
  };
  window.confirmDestructive = function(opts) {
    return window.confirmAction(Object.assign({ danger: true }, opts));
  };
  window.confirmWarning = function(opts) {
    return window.confirmAction(Object.assign({ warning: true }, opts));
  };

  async function api(path, opts) {
    var token = getAccessToken();
    if (!token) { showLoginPage(); return null; }
    opts = opts || {};
    opts.headers = opts.headers || {};
    opts.headers['Authorization'] = 'Bearer ' + token;
    opts.headers['Content-Type'] = 'application/json';
    try {
      var resp = await fetch(API_BASE + path, opts);
      if (resp.status === 401) { showLoginPage(); return null; }
      if (resp.status === 403) { return { _forbidden: true, detail: 'Access denied — admin only' }; }
      if (!resp.ok) {
        try { var errData = await resp.json(); return errData; } catch(e) {}
        return { _error: true, detail: 'Server error (' + resp.status + ')' };
      }
      try { return await resp.json(); } catch(e) { return { _error: true, detail: 'Invalid server response' }; }
    } catch(e) {
      return { _error: true, detail: 'Network error' };
    }
  }


window._adminChangePassword = function(id, btn) {
    changePassword(id, btn.getAttribute('data-username'));
};
window._adminAssignHospitals = function(id, btn) {
    assignHospitals(id, btn.getAttribute('data-username'));
};
  window.loadAdminPanel = async function() {
    var container = document.getElementById('tab-admin');
    if (!container) return;
    container.innerHTML = '<div style="padding:1rem;color:var(--text-muted);">Loading...</div>';
    try {

    var usersData = await api('/admin/users');
    var rolesData = await api('/admin/roles');
    var permsData = await api('/admin/permissions');
    if (!usersData || !rolesData || !permsData) {
      container.innerHTML = '<div style="padding:2rem;text-align:center;">' +
        '<h3 style="color:var(--accent-red);margin-bottom:0.5rem;">Authentication Required</h3>' +
        '<p style="color:var(--text-secondary);">Please log in again to access the Admin panel.</p>' +
        '</div>';
      return;
    }

    // Handle API errors (403, 500, network)
    var firstErr = [usersData, rolesData, permsData].find(function(d) { return d && (d._forbidden || d._error); });
    if (firstErr) {
      var errTitle = firstErr._forbidden ? 'Access Denied' : 'Error';
      container.innerHTML = '<div style="padding:2rem;text-align:center;">' +
        '<h3 style="color:var(--accent-red);margin-bottom:0.5rem;">' + errTitle + '</h3>' +
        '<p style="color:var(--text-secondary);">' + (firstErr.detail || 'Cannot load admin panel') + '</p>' +
        '<p style="color:var(--text-muted);font-size:0.82rem;">You need superadmin privileges to access this section.</p>' +
        '</div>';
      return;
    }

    var users = usersData.users || [];
    var roles = rolesData.roles || [];
    var perms = permsData.permissions || [];

    container.innerHTML = `
      <div style="padding:1rem;">
        <!-- KPI Summary -->
        <div class="admin-kpis">
          <div class="kpi-card"><div class="icon">👥</div><div class="value">${users.filter(function(u){ return u.is_active !== false; }).length}</div><div class="label">${__('Active Users')}</div></div>
          <div class="kpi-card"><div class="icon">🛡️</div><div class="value">${roles.length}</div><div class="label">${__('Roles')}</div></div>
          <div class="kpi-card"><div class="icon">🔑</div><div class="value">${perms.length}</div><div class="label">${__('Permissions')}</div></div>
          <div class="kpi-card"><div class="icon">🟢</div><div class="value" id="adminKpiOnline">—</div><div class="label">${__('Online now')}</div></div>
          <div class="kpi-card"><div class="icon">⚠️</div><div class="value" id="adminKpiLogs">—</div><div class="label">${__('Warnings / Errors')}</div></div>
          <div class="kpi-card"><div class="icon">🗄️</div><div class="value" id="adminKpiDb" style="font-size:1rem;margin-top:0.25rem;">—</div><div class="label">${__('Database')}</div></div>
        </div>
        <!-- Admin Tab Bar -->
        <div style="display:flex;gap:0;border-bottom:2px solid var(--border-default);margin-bottom:1rem;">
          <button class="admin-tab-btn active" onclick="switchAdminTab('users')" id="atab-users" style="padding:0.5rem 1.2rem;border:none;background:var(--accent-purple);color:white;border-radius:6px 6px 0 0;font-size:0.85rem;font-weight:600;cursor:pointer;margin-bottom:-2px;">👥 Users</button>
          <button class="admin-tab-btn" onclick="switchAdminTab('roles')" id="atab-roles" style="padding:0.5rem 1.2rem;border:none;background:var(--bg-surface-hover);color:var(--text-secondary);border-radius:6px 6px 0 0;font-size:0.85rem;cursor:pointer;margin-bottom:-2px;">🏷️ Roles</button>
          <button class="admin-tab-btn" onclick="switchAdminTab('permissions')" id="atab-permissions" style="padding:0.5rem 1.2rem;border:none;background:var(--bg-surface-hover);color:var(--text-secondary);border-radius:6px 6px 0 0;font-size:0.85rem;cursor:pointer;margin-bottom:-2px;">🔑 Permissions</button>
          <button class="admin-tab-btn" onclick="switchAdminTab('database')" id="atab-database" style="padding:0.5rem 1.2rem;border:none;background:var(--bg-surface-hover);color:var(--text-secondary);border-radius:6px 6px 0 0;font-size:0.85rem;cursor:pointer;margin-bottom:-2px;">🗄️ Database</button>
          <button class="admin-tab-btn" onclick="switchAdminTab('control')" id="atab-control" style="padding:0.5rem 1.2rem;border:none;background:var(--bg-surface-hover);color:var(--text-secondary);border-radius:6px 6px 0 0;font-size:0.85rem;cursor:pointer;margin-bottom:-2px;">🎛️ Analysis Control</button>
          <button class="admin-tab-btn" onclick="switchAdminTab('logs')" id="atab-logs" style="padding:0.5rem 1.2rem;border:none;background:var(--bg-surface-hover);color:var(--text-secondary);border-radius:6px 6px 0 0;font-size:0.85rem;cursor:pointer;margin-bottom:-2px;">📋 Logs</button>
          <button class="admin-tab-btn" onclick="switchAdminTab('sessions')" id="atab-sessions" style="padding:0.5rem 1.2rem;border:none;background:var(--bg-surface-hover);color:var(--text-secondary);border-radius:6px 6px 0 0;font-size:0.85rem;cursor:pointer;margin-bottom:-2px;">🟢 Sessions</button>
          <button class="admin-tab-btn" onclick="switchAdminTab('menu')" id="atab-menu" style="padding:0.5rem 1.2rem;border:none;background:var(--bg-surface-hover);color:var(--text-secondary);border-radius:6px 6px 0 0;font-size:0.85rem;cursor:pointer;margin-bottom:-2px;">🧭 Menu Layout</button>
        </div>

        <!-- Users / Roles / Permissions Tab -->
        <div id="adminUsersPanel">
        <!-- Users Sub-Tab -->
        <div id="adminUsersSubPanel">
        <h2 style="color:var(--accent-purple);margin-bottom:0.5rem;">User Management</h2>
        <p style="font-size:0.82rem;color:var(--text-secondary);margin-bottom:1rem;">Create, edit, and deactivate user accounts. Assign roles and direct permissions to control access.</p>
          <div>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
              <h3 style="color:var(--accent-blue);margin:0;">Users (${users.length}) <span class="admin-chip">${users.filter(function(u){ return u.is_active !== false; }).length} ${__('active')}</span></h3>
              <button class="btn btn-sm" onclick="showCreateUserModal()">+ New User</button>
            </div>
            <div style="overflow-x:auto;">
              <table style="width:100%;border-collapse:collapse;font-size:0.82rem;">
                <thead>
                  <tr style="border-bottom:2px solid var(--border-default);">
                    <th style="padding:0.4rem;text-align:left;">Username</th>
                    <th style="padding:0.4rem;text-align:left;">Full Name</th>
                    <th style="padding:0.4rem;text-align:left;">Email</th>
                    <th style="padding:0.4rem;text-align:left;">Roles</th>
                    <th style="padding:0.4rem;text-align:left;">Permissions</th>
                    <th style="padding:0.4rem;text-align:left;">Status</th>
                    <th style="padding:0.4rem;text-align:left;">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  ${users.map(u => `
                    <tr style="border-bottom:1px solid var(--border-default);${!u.is_active ? 'opacity:0.5;' : ''}">
                      <td style="padding:0.4rem;font-weight:600;">${esc(u.username)}</td>
                      <td style="padding:0.4rem;">${esc(u.full_name)}</td>
                      <td style="padding:0.4rem;color:var(--text-secondary);">${esc(u.email)}</td>
                      <td style="padding:0.4rem;">${u.roles.map(r => '<span style="background:var(--bg-surface-hover);color:var(--accent-purple);padding:0.1rem 0.4rem;border-radius:4px;font-size:0.75rem;margin-right:0.2rem;">' + esc(r.name) + '</span>').join('')}</td>
                      <td style="padding:0.4rem;">${(u.direct_permissions || []).map(p => '<span class="admin-user-perm" title="Direct">' + esc(p.codename) + '</span>').join('') || '<span style="color:var(--text-muted);font-size:0.75rem;">—</span>'}</td>
                      <td style="padding:0.4rem;">${u.is_active ? '<span style="color:var(--accent-green);">Active</span>' : '<span style="color:var(--accent-red);">Inactive</span>'}</td>
                      <td style="padding:0.4rem;">
                        <button class="btn btn-sm btn-outline" onclick="editUser(${u.id})" style="font-size:0.72rem;">Edit</button>
                        <button class="btn btn-sm btn-outline" onclick="window._adminChangePassword(${u.id}, this)" data-username="${esc(u.username)}" style="font-size:0.72rem;color:var(--accent-orange);margin-left:0.2rem;">🔑 Password</button>
                        <button class="btn btn-sm btn-outline" onclick="window._adminAssignHospitals(${u.id}, this)" data-username="${esc(u.username)}" style="font-size:0.72rem;color:var(--accent-blue);margin-left:0.2rem;">Hospitals</button>
                        ${u.is_active ? '<button class="btn btn-sm btn-outline" onclick="deactivateUser(' + u.id + ')" style="font-size:0.72rem;color:var(--accent-red);margin-left:0.2rem;">Deactivate</button>' : ''}
                      </td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
          </div>
        </div> <!-- /adminUsersSubPanel -->

        <!-- Roles Sub-Tab -->
        <div id="adminRolesSubPanel" style="display:none;">
        <h2 style="color:var(--accent-purple);margin-bottom:0.5rem;">Role Management</h2>
        <p style="font-size:0.82rem;color:var(--text-secondary);margin-bottom:1rem;">Create, rename, or delete roles. Click a row to preview its permission codenames; to change them, use <strong>⚙ Perms</strong> or the Permissions tab.</p>
          <div>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
              <h3 style="color:var(--accent-blue);margin:0;">Roles (${roles.length})</h3>
              <button class="btn btn-sm" onclick="showCreateRoleModal()">+ New Role</button>
            </div>
            <div style="overflow-x:auto;">
              <table style="width:100%;border-collapse:collapse;font-size:0.82rem;">
                <thead>
                  <tr style="border-bottom:2px solid var(--border-default);">
                    <th style="padding:0.4rem;text-align:left;">Role</th>
                    <th style="padding:0.4rem;text-align:left;">Users</th>
                    <th style="padding:0.4rem;text-align:left;">Permissions</th>
                    <th style="padding:0.4rem;text-align:left;">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  ${roles.map(r => {
                    var rolePerms = perms.filter(function(p){ return (r.permission_ids || []).indexOf(p.id) !== -1; });
                    var expanded = (window._expandedRoleIds || []).indexOf(r.id) !== -1;
                    return `
                    <tr style="border-bottom:1px solid var(--border-default);cursor:pointer;" onclick="toggleRolePerms(${r.id})" title="Show/hide permission codenames">
                      <td style="padding:0.4rem;font-weight:600;"><span id="roleCaret-${r.id}" style="display:inline-block;width:1em;color:var(--text-muted);">${expanded ? '▾' : '▸'}</span>${esc(r.name)}${r.is_system ? ' <span style="font-size:0.7rem;color:var(--text-muted);">(system)</span>' : ''}</td>
                      <td style="padding:0.4rem;">${r.user_count}</td>
                      <td style="padding:0.4rem;font-size:0.75rem;color:var(--text-secondary);">${r.permission_ids.length} perms</td>
                      <td style="padding:0.4rem;" onclick="event.stopPropagation();">
                        <button class="btn btn-sm btn-outline" onclick="editRolePermsInMatrix(' + r.id + ')" style="font-size:0.72rem;color:var(--accent-blue);" title="Edit this role's permissions in the matrix">⚙ Perms</button>
                        ${r.name === 'superadmin' ? '<span style="font-size:0.72rem;color:var(--text-muted);margin-left:0.2rem;">System</span>' : '<button class="btn btn-sm btn-outline" onclick="editRole(' + r.id + ')" style="font-size:0.72rem;">Edit</button>'}
                        ${!r.is_system ? '<button class="btn btn-sm btn-outline" onclick="deleteRole(' + r.id + ')" style="font-size:0.72rem;color:var(--accent-red);margin-left:0.2rem;">Delete</button>' : ''}
                      </td>
                    </tr>
                    <tr id="rolePermsRow-${r.id}" style="display:${expanded ? '' : 'none'};">
                      <td colspan="4" style="padding:0.3rem 0.4rem 0.6rem 1.6rem;background:var(--bg-elevated);">
                        ${r.description ? '<div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:0.3rem;">' + esc(r.description) + '</div>' : ''}
                        ${rolePerms.length ? rolePerms.map(p => '<span class="admin-role-perm-chip" style="display:inline-block;background:var(--bg-surface-hover);color:var(--accent-purple);padding:0.1rem 0.4rem;border-radius:4px;font-size:0.72rem;margin:0.1rem 0.2rem 0.1rem 0;">' + esc(p.codename) + '</span>').join('') : '<span style="font-size:0.75rem;color:var(--text-muted);">No permissions</span>'}
                      </td>
                    </tr>
                  `; }).join('')}
                </tbody>
              </table>
            </div>
          </div>

        <!-- Role Visibility Matrix -->
        <div id="adminVisibilityMatrix" style="margin-top:1.5rem;padding:1rem;background:var(--bg-elevated);border-radius:10px;border:1px solid var(--border-default);">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.8rem;">
            <h3 style="color:var(--accent-purple);margin:0;">🛡️ Role UI Visibility Matrix</h3>
            <button class="btn btn-sm btn-outline" onclick="loadVisibilityMatrix()" style="font-size:0.72rem;">↻ Refresh</button>
          </div>
          <p style="font-size:0.78rem;color:var(--text-muted);margin:0 0 0.5rem;">Shows which tabs each role can see. Green = visible, Red = hidden. Click a role to simulate.</p>
          <div style="display:flex;gap:0.4rem;flex-wrap:wrap;margin-bottom:0.6rem;">
            <span style="font-size:0.78rem;color:var(--text-secondary);line-height:2;">Filter:</span>
            <button class="btn btn-sm vis-filter active" data-filter="all" onclick="filterVisMatrix('all',this)" style="font-size:0.72rem;">All Roles</button>
            <button class="btn btn-sm btn-outline vis-filter" data-filter="full" onclick="filterVisMatrix('full',this)" style="font-size:0.72rem;">✅ Full Access</button>
            <button class="btn btn-sm btn-outline vis-filter" data-filter="partial" onclick="filterVisMatrix('partial',this)" style="font-size:0.72rem;">🟡 Partial</button>
            <button class="btn btn-sm btn-outline vis-filter" data-filter="none" onclick="filterVisMatrix('none',this)" style="font-size:0.72rem;">❌ No Access</button>
            <button class="btn btn-sm btn-outline vis-filter" data-filter="superadmin" onclick="filterVisMatrix('superadmin',this)" style="font-size:0.72rem;">★ Superadmin</button>
          </div>
          <div id="visMatrixBody" style="overflow-x:auto;"><div style="text-align:center;padding:1rem;color:var(--text-muted);">Loading...</div></div>
        </div>

        <!-- Role Simulation Preview -->
        <div id="roleSimulator" style="display:none;margin-top:1rem;border:2px solid var(--accent-blue);border-radius:8px;overflow:hidden;">
            <div style="padding:0.6rem 0.8rem;background:var(--accent-blue);color:white;display:flex;justify-content:space-between;align-items:center;">
                <span style="font-weight:600;font-size:0.85rem;">🎮 Role Simulator: <span id="simRoleName"></span></span>
                <button onclick="document.getElementById('roleSimulator').style.display='none'" style="background:none;border:1px solid rgba(255,255,255,0.3);color:white;border-radius:4px;padding:0.2rem 0.6rem;font-size:0.75rem;cursor:pointer;">✕ Close</button>
            </div>
            <div style="padding:0.8rem;background:var(--bg-elevated);">
                <div style="margin-bottom:0.6rem;font-size:0.78rem;color:var(--text-secondary);">
                    <strong>Permissions:</strong> <span id="simPermCount"></span> · <span id="simPermList" style="font-size:0.72rem;"></span>
                </div>
                <div style="margin-bottom:0.6rem;font-size:0.82rem;color:var(--text-primary);font-weight:600;">Simulated Tab Bar:</div>
                <div id="simTabBar" style="display:flex;flex-wrap:wrap;gap:0.3rem;margin-bottom:0.8rem;"></div>
                <div style="font-size:0.78rem;color:var(--text-secondary);margin-bottom:0.3rem;">Visible tab content panels:</div>
                <div id="simTabContent" style="display:flex;flex-wrap:wrap;gap:0.4rem;"></div>
            </div>
        </div>
        </div> <!-- /adminRolesSubPanel -->

        <!-- Permissions Sub-Tab -->
        <div id="adminPermsSubPanel" style="display:none;">
        <h2 style="color:var(--accent-purple);margin-bottom:0.5rem;">Permissions</h2>
        <p style="font-size:0.82rem;color:var(--text-secondary);margin-bottom:1rem;">The single place to edit what each role grants — toggle a permission per role below. To grant a permission to one specific user instead, use the Users tab.</p>

          <!-- Role x Permission Matrix -->
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
            <h3 style="color:var(--accent-blue);margin:0;">🧩 Role × Permission Matrix</h3>
            <div style="display:flex;gap:0.5rem;align-items:center;">
              <span id="permMatrixDirty" style="display:none;font-size:0.75rem;color:var(--accent-orange);">● Unsaved changes</span>
              <button class="btn btn-sm" id="permMatrixSaveBtn" onclick="permMatrixSaveAll()" style="display:none;">💾 Save Changes</button>
            </div>
          </div>
          <p style="font-size:0.75rem;color:var(--text-muted);margin:0 0 0.5rem;">Check a box to grant the permission to that role. The superadmin role always has every permission.</p>
          <div style="overflow:auto;max-height:480px;border:1px solid var(--border-default);border-radius:6px;background:var(--bg-surface);">
            <table style="border-collapse:collapse;font-size:0.75rem;min-width:100%;">
              <thead>
                <tr style="border-bottom:2px solid var(--border-default);">
                  <th style="position:sticky;left:0;top:0;background:var(--bg-elevated);z-index:2;text-align:left;padding:0.4rem 0.6rem;min-width:180px;">Permission</th>
                  ${roles.map(r => '<th id="permCol-' + r.id + '" title="' + esc(r.name) + '" style="padding:0.4rem 0.5rem;text-align:center;min-width:64px;background:var(--bg-elevated);transition:outline 0.2s;">' + esc(r.name.length > 10 ? r.name.slice(0,9) + '…' : r.name) + (r.is_system ? ' ★' : '') + '</th>').join('')}
                </tr>
              </thead>
              <tbody>
                ${perms.map(p => `
                  <tr style="border-bottom:1px solid var(--border-default);">
                    <td style="position:sticky;left:0;background:var(--bg-surface);z-index:1;padding:0.3rem 0.6rem;">
                      <strong style="color:var(--accent-purple);">${esc(p.codename)}</strong>
                      ${p.description ? '<div style="font-size:0.7rem;color:var(--text-muted);">' + esc(p.description) + '</div>' : ''}
                    </td>
                    ${roles.map(r => {
                      var isSuper = r.is_system && r.name === 'superadmin';
                      var checked = isSuper || (r.permission_ids || []).indexOf(p.id) !== -1;
                      return isSuper
                        ? '<td style="padding:0.3rem 0.5rem;text-align:center;" title="superadmin always has every permission">✓</td>'
                        : '<td style="padding:0.3rem 0.5rem;text-align:center;"><input type="checkbox" class="perm-matrix-cb" data-role="' + r.id + '" data-perm="' + p.id + '"' + (checked ? ' checked' : '') + ' onchange="permMatrixMarkDirty()" style="width:16px;height:16px;cursor:pointer;"></td>';
                    }).join('')}
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>

        <!-- Create/Edit User Modal -->
        <div id="adminUserModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:9999;align-items:center;justify-content:center;">
          <div style="background:var(--bg-surface);border-radius:10px;padding:1.5rem;width:420px;max-width:94%;box-shadow:0 8px 32px rgba(0,0,0,0.2);border:1px solid var(--border-default);">
            <h3 id="adminModalTitle" style="color:var(--accent-blue);margin:0 0 1rem;">New User</h3>
            <input type="hidden" id="adminEditUserId">
            <div style="margin-bottom:0.8rem;">
              <label style="font-size:0.82rem;font-weight:600;">Username</label>
              <input id="adminUsername" style="width:100%;padding:0.4rem;border:1px solid var(--border-default);border-radius:6px;box-sizing:border-box;" ${window._adminEditMode ? 'readonly style="width:100%;padding:0.4rem;border:1px solid var(--border-default);border-radius:6px;box-sizing:border-box;background:var(--bg-elevated);"' : ''}>
            </div>
            <div style="margin-bottom:0.8rem;">
              <label style="font-size:0.82rem;font-weight:600;">Full Name</label>
              <input id="adminFullName" style="width:100%;padding:0.4rem;border:1px solid var(--border-default);border-radius:6px;box-sizing:border-box;">
            </div>
            <div style="margin-bottom:0.8rem;">
              <label style="font-size:0.82rem;font-weight:600;">Email</label>
              <input id="adminEmail" type="email" style="width:100%;padding:0.4rem;border:1px solid var(--border-default);border-radius:6px;box-sizing:border-box;">
            </div>
            <div style="margin-bottom:0.8rem;">
              <label style="font-size:0.82rem;font-weight:600;">Password <span id="adminPassHint" style="font-weight:normal;color:var(--text-muted);"></span></label>
              <input id="adminPassword" type="password" style="width:100%;padding:0.4rem;border:1px solid var(--border-default);border-radius:6px;box-sizing:border-box;">
            </div>
            <div style="margin-bottom:0.8rem;">
              <label style="font-size:0.82rem;font-weight:600;">Roles</label>
              <div id="adminRoleCheckboxes" style="max-height:120px;overflow-y:auto;border:1px solid var(--border-default);border-radius:6px;padding:0.4rem;">
                ${roles.map(r => '<label style="display:flex;align-items:center;gap:0.4rem;padding:0.2rem 0;font-size:0.82rem;cursor:pointer;"><input type="checkbox" class="admin-role-cb" value="' + r.id + '"> ' + esc(r.name) + (r.is_system ? ' <span style="color:var(--text-muted);font-size:0.7rem;">(system)</span>' : '') + '</label>').join('')}
              </div>
            </div>
            <div style="margin-bottom:0.8rem;">
              <label style="font-size:0.82rem;font-weight:600;">${__('Direct Permissions')}</label>
              <div id="adminUserPermCheckboxes" style="max-height:120px;overflow-y:auto;border:1px solid var(--border-default);border-radius:6px;padding:0.4rem;">
                ${perms.map(p => '<label style="display:flex;align-items:center;gap:0.4rem;padding:0.2rem 0;font-size:0.82rem;cursor:pointer;"><input type="checkbox" class="admin-user-perm-cb" value="' + p.id + '"> <strong style="color:var(--accent-purple);">' + esc(p.codename) + '</strong></label>').join('')}
              </div>
            </div>
            <div id="adminModalError" style="display:none;color:var(--accent-red);font-size:0.82rem;margin-bottom:0.5rem;"></div>
            <div style="display:flex;gap:0.5rem;justify-content:flex-end;">
              <button class="btn btn-sm btn-outline" onclick="closeAdminModal()">Cancel</button>
              <button class="btn btn-sm" id="adminSaveBtn" onclick="saveAdminUser()">Save</button>
            </div>
          </div>
        </div>
        <!-- Role Editor Modal -->
        <div id="adminRoleModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:9999;align-items:center;justify-content:center;">
          <div style="background:var(--bg-surface);border-radius:10px;padding:1.5rem;width:480px;max-width:94%;max-height:80vh;overflow-y:auto;box-shadow:0 8px 32px rgba(0,0,0,0.2);border:1px solid var(--border-default);">
            <h3 id="roleModalTitle" style="color:var(--accent-blue);margin:0 0 1rem;">New Role</h3>
            <input type="hidden" id="adminEditRoleId">
            <div style="margin-bottom:0.8rem;">
              <label style="font-size:0.82rem;font-weight:600;">Role Name</label>
              <input id="adminRoleName" style="width:100%;padding:0.4rem;border:1px solid var(--border-default);border-radius:6px;box-sizing:border-box;" placeholder="e.g. data_entry">
            </div>
            <div style="margin-bottom:0.8rem;">
              <label style="font-size:0.82rem;font-weight:600;">Description</label>
              <input id="adminRoleDesc" style="width:100%;padding:0.4rem;border:1px solid var(--border-default);border-radius:6px;box-sizing:border-box;" placeholder="Optional description">
            </div>
            <div style="margin-bottom:0.8rem;">
              <label style="font-size:0.82rem;font-weight:600;">Permissions</label>
              <div style="display:flex;gap:0.3rem;margin-bottom:0.4rem;">
                <button class="btn btn-sm btn-outline" onclick="document.querySelectorAll('#adminPermCheckboxes input').forEach(function(c){c.checked=true})" style="font-size:0.72rem;">Select All</button>
                <button class="btn btn-sm btn-outline" onclick="document.querySelectorAll('#adminPermCheckboxes input').forEach(function(c){c.checked=false})" style="font-size:0.72rem;">Clear All</button>
              </div>
              <div id="adminPermCheckboxes" style="max-height:200px;overflow-y:auto;border:1px solid var(--border-default);border-radius:6px;padding:0.4rem;">
                ${perms.map(p => '<label style="display:flex;align-items:center;gap:0.4rem;padding:0.2rem 0;font-size:0.82rem;cursor:pointer;"><input type="checkbox" class="admin-perm-cb" value="' + p.id + '"> <strong style="color:var(--accent-purple);">' + esc(p.codename) + '</strong>' + (p.description ? ' <span style="color:var(--text-muted);font-size:0.75rem;">— ' + esc(p.description) + '</span>' : '') + '</label>').join('')}
              </div>
            </div>
            <div id="adminRoleModalError" style="display:none;color:var(--accent-red);font-size:0.82rem;margin-bottom:0.5rem;"></div>
            <div style="display:flex;gap:0.5rem;justify-content:flex-end;">
              <button class="btn btn-sm btn-outline" onclick="closeRoleModal()">Cancel</button>
              <button class="btn btn-sm" onclick="saveRole()">Save Role</button>
            </div>
          </div>

        </div>
      </div> <!-- /adminUsersPanel -->

        <!-- Database Tab -->
        <div id="adminDatabasePanel" style="display:none;">
          <div id="dbSubOverview">
            <h2 style="color:var(--accent-purple);margin-bottom:0.5rem;">Database</h2>
            <p style="font-size:0.82rem;color:var(--text-secondary);margin-bottom:1rem;">View database connection status, preview tables, and export data.</p>
            <div style="background:var(--bg-elevated);padding:1rem;border-radius:10px;max-width:700px;border:1px solid var(--border-default);">
              <div id="adminDbStatus" style="font-size:0.85rem;line-height:1.8;">Loading...</div>
            </div>
            <div style="margin-top:1.2rem;display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap;">
              <button class="btn btn-sm" onclick="adminPreviewDb()" id="adminBtnPreviewDb">Preview Tables</button>
              <button class="btn btn-sm" onclick="adminExportDb()" id="adminBtnExportDb" style="background:#22c55e;color:white;">Export Full Database (JSON)</button>
              <span id="adminDbExportStatus" style="font-size:0.8rem;color:var(--text-muted);"></span>
            </div>

            <!-- Quality Score Repair -->
            <div style="margin-top:1.2rem;padding:0.8rem;background:var(--bg-surface-hover);border-radius:8px;border:1px solid var(--border-default);">
              <h4 style="font-size:0.88rem;color:var(--text-primary);margin:0 0 0.3rem;">🔧 Quality Score Repair</h4>
              <p style="font-size:0.75rem;color:var(--text-muted);margin:0 0 0.6rem;">Recomputes every stored Quality Score from its components (validation rule, completeness, consistency, outlier) using the current weights, fixing rows whose stored score diverges. Run “Check” first — nothing is written by the check.</p>
              <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap;">
                <button class="btn btn-sm btn-outline" onclick="adminCheckScoreRepair()" id="adminBtnRepairCheck">🔍 Check</button>
                <button class="btn btn-sm" onclick="adminRunScoreRepair()" id="adminBtnRepairRun" style="display:none;background:var(--accent-orange);color:white;">🔧 Repair ${window._scoreRepairCount !== undefined ? window._scoreRepairCount : ''} Rows</button>
                <span id="adminRepairStatus" style="font-size:0.78rem;color:var(--text-muted);"></span>
              </div>
              <div id="adminRepairPreview" style="display:none;margin-top:0.6rem;max-height:200px;overflow-y:auto;background:var(--bg-surface);border-radius:6px;padding:0.5rem;font-size:0.75rem;"></div>
              <div style="margin-top:0.8rem;padding-top:0.7rem;border-top:1px dashed var(--border-default);">
                <label style="display:flex;align-items:center;gap:0.4rem;font-size:0.78rem;color:var(--text-secondary);cursor:pointer;">
                  <input type="checkbox" id="adminRepairDeepToggle" onchange="adminOnDeepToggle()">
                  <strong>${esc(__('Deep mode'))}</strong> — ${esc(__('also recompute the components themselves from raw indicator values'))}
                </label>
                <p id="adminRepairDeepDesc" style="display:none;font-size:0.72rem;color:var(--text-muted);margin:0.3rem 0 0.5rem 1.4rem;">
                  ${esc(__('Reruns the full analysis engine per hospital/month (the same pipeline as data upload): validation rules, completeness, consistency and outliers are all rebuilt from source data. Slower; runs in the background with progress below.'))}
                </p>
                <div id="adminRepairDeepRow" style="display:none;gap:0.5rem;align-items:center;flex-wrap:wrap;margin-left:1.4rem;">
                  <button class="btn btn-sm btn-outline" onclick="adminDeepCheckScoreRepair()" id="adminBtnDeepCheck">🔍 Deep Check</button>
                  <button class="btn btn-sm" onclick="adminDeepRunScoreRepair()" id="adminBtnDeepRepair" style="display:none;background:var(--accent-orange);color:white;">🏗️ Rebuild ${window._deepTargetCount !== undefined ? window._deepTargetCount : ''} Hospital/Months</button>
                  <span id="adminDeepStatus" style="font-size:0.78rem;color:var(--text-muted);"></span>
                </div>
                <div id="adminDeepProgressWrap" style="display:none;margin:0.5rem 0 0 1.4rem;">
                  <div style="height:6px;background:var(--bg-surface);border-radius:3px;overflow:hidden;">
                    <div id="adminDeepProgressBar" style="height:100%;width:0%;background:var(--accent-orange);transition:width 0.3s;"></div>
                  </div>
                </div>
              </div>
            </div>
            <div id="adminDbPreviewContainer" style="margin-top:1rem;display:none;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
                <h4 style="font-size:0.88rem;color:var(--text-primary);margin:0;">Database Tables Preview</h4>
                <button class="btn btn-sm btn-outline" id="adminDbCloseBtn">Close</button>
              </div>
              <div id="adminDbPreviewContent" style="max-height:600px;overflow-y:auto;background:var(--bg-elevated);padding:0.8rem;border-radius:6px;">
                <p style="color:var(--text-muted);font-size:0.82rem;">Click Preview Tables to load.</p>
              </div>
            </div>
          </div>
        </div>
        <!-- Control Panel -->
        <div id="adminControlPanel" style="display:none;">
            <h2 style="color:var(--accent-purple);margin-bottom:0.5rem;">Analysis Control</h2>
            <p style="font-size:0.82rem;color:var(--text-secondary);margin-bottom:1rem;">Configure analysis behavior, logging, and month toggles.</p>
            <div style="background:var(--bg-elevated);padding:1rem;border-radius:10px;max-width:700px;border:1px solid var(--border-default);">
              <div style="background:var(--bg-surface-hover);padding:0.8rem;border-radius:6px;margin-bottom:1rem;font-size:0.8rem;color:var(--text-primary);line-height:1.6;">
                  Controls how null/missing indicator values are handled during analysis and in the indicator tree.
              </div>
              <div style="background:var(--bg-surface-hover);padding:0.8rem;border-radius:6px;max-width:700px;">
                  <label style="display:flex;align-items:flex-start;gap:0.6rem;cursor:pointer;">
                      <input type="checkbox" id="cfg_auto_disable_null" onchange="adminMarkControlDirty()" style="margin-top:0.2rem;width:18px;height:18px;">
                      <div>
                          <strong>Auto-disable null indicators</strong><br>
                          <span style="font-size:0.8rem;color:var(--text-secondary);">When enabled, indicators with null values are treated as disabled.</span>
                      </div>
                  </label>
              </div>
              <div style="background:var(--bg-surface-hover);padding:0.8rem;border-radius:6px;max-width:700px;margin-top:0.8rem;">
                  <label style="display:flex;align-items:flex-start;gap:0.6rem;cursor:pointer;">
                      <input type="checkbox" id="cfg_structured_logging" onchange="adminMarkControlDirty()" style="margin-top:0.2rem;width:18px;height:18px;">
                      <div>
                          <strong>Structured Logging</strong><br>
                          <span style="font-size:0.8rem;color:var(--text-secondary);">Log all HTTP requests as JSON to stdout.</span>
                      </div>
                  </label>
              </div>
              <div style="background:var(--bg-surface-hover);padding:0.8rem;border-radius:6px;max-width:700px;margin-top:0.8rem;">
                  <label style="display:flex;align-items:flex-start;gap:0.6rem;cursor:pointer;">
                      <input type="checkbox" id="cfg_slow_query_logging" onchange="adminMarkControlDirty()" style="margin-top:0.2rem;width:18px;height:18px;">
                      <div>
                          <strong>Slow Query Logging</strong><br>
                          <span style="font-size:0.8rem;color:var(--text-secondary);">Log SQL queries taking over 1 second.</span>
                      </div>
                  </label>
              </div>
              <div style="background:var(--bg-surface-hover);padding:0.8rem;border-radius:6px;max-width:700px;margin-top:0.8rem;">
                  <label style="display:flex;align-items:flex-start;gap:0.6rem;cursor:pointer;">
                      <input type="checkbox" id="cfg_hide_explanatory" onchange="adminMarkControlDirty()" style="margin-top:0.2rem;width:18px;height:18px;">
                      <div>
                          <strong>Hide Forecast/Explanation Sentences</strong><br>
                          <span style="font-size:0.8rem;color:var(--text-secondary);">When enabled, narrative forecast/explanation sentences are hidden from non-super-admin users (super admins always see them).</span>
                      </div>
                  </label>
              </div>
              <div style="background:var(--bg-surface-hover);padding:0.8rem;border-radius:6px;max-width:700px;margin-top:0.8rem;">
                  <label style="display:flex;align-items:flex-start;gap:0.6rem;cursor:pointer;">
                      <input type="checkbox" id="cfg_incremental_months" onchange="adminMarkControlDirty()" style="margin-top:0.2rem;width:18px;height:18px;">
                      <div>
                          <strong>Incremental Update (Keep Old Months)</strong><br>
                          <span style="font-size:0.8rem;color:var(--text-secondary);">When enabled, re-saving a file only updates data for the months present in the file and keeps previously uploaded months. When disabled, re-saving replaces all existing data from that file.</span>
                      </div>
                  </label>
              </div>
              <div style="background:var(--bg-surface-hover);padding:0.8rem;border-radius:6px;max-width:700px;margin-top:0.8rem;">
                  <label style="display:flex;align-items:flex-start;gap:0.6rem;cursor:pointer;">
                      <input type="checkbox" id="cfg_dev_hints" onchange="adminToggleDevHints(this.checked)" style="margin-top:0.2rem;width:18px;height:18px;">
                      <div>
                          <strong>Show Developer Hints</strong><br>
                          <span style="font-size:0.8rem;color:var(--text-secondary);">Display source code references below each setting control.</span>
                      </div>
                  </label>
              </div>
              <div style="display:flex;gap:0.5rem;align-items:center;margin-top:1rem;padding-top:0.8rem;border-top:1px solid var(--border-default);">
                  <button class="btn btn-sm" id="controlSaveBtn" onclick="adminSaveControlSettings()" style="display:none;background:var(--accent-purple);color:white;">Save</button>
                  <span id="controlSaveStatus" style="font-size:0.8rem;color:var(--text-muted);"></span>
              </div>
            </div>
            <div style="background:var(--bg-elevated);padding:1rem;border-radius:10px;max-width:700px;border:1px solid var(--border-default);margin-top:1rem;">
              <h3 style="font-size:0.95rem;color:var(--text-primary);margin-bottom:0.5rem;">Analysis Months</h3>
              <p style="font-size:0.82rem;color:var(--text-secondary);margin-bottom:0.8rem;">Toggle months on/off per hospital.</p>
              <div style="display:flex;align-items:center;gap:0.4rem;margin-bottom:0.8rem;">
                  <label style="font-size:0.78rem;color:var(--text-secondary);">Hospital:</label>
                  <select id="monthHospitalSelect" onchange="onMonthHospitalChange()" style="font-size:0.78rem;padding:0.2rem 0.4rem;"></select>
              </div>
              <div style="display:flex;gap:0.4rem;margin-bottom:0.5rem;">
                  <button class="btn btn-sm btn-outline" onclick="toggleAllAnalysisMonths(true)" style="font-size:0.7rem;padding:0.2rem 0.5rem;">Enable All</button>
                  <button class="btn btn-sm btn-outline" onclick="toggleAllAnalysisMonths(false)" style="font-size:0.7rem;padding:0.2rem 0.5rem;">Disable All</button>
                  <button class="btn btn-sm" onclick="adminSaveAllMonthSettings()" style="font-size:0.7rem;padding:0.2rem 0.5rem;">Save</button>
              </div>
              <div id="monthToggleList" style="display:flex;flex-wrap:wrap;gap:0.5rem;"></div>
              <div style="margin-top:0.5rem;">
                  <span id="monthSaveStatus" style="font-size:0.8rem;color:var(--text-muted);"></span>
              </div>
            </div>
        </div>
        <!-- Logs Panel -->
        <div id="adminLogsPanel" style="display:none;">
          <h2 style="color:var(--accent-purple);margin-bottom:0.5rem;">📋 Server Logs</h2>
            <p style="font-size:0.82rem;color:var(--text-secondary);margin-bottom:1rem;">Recent server warnings and errors. Auto-refreshes every 10 seconds.</p>
            <div style="display:flex;gap:0.5rem;margin-bottom:1rem;align-items:center;flex-wrap:wrap;">
              <input type="text" id="logsSearchFilter" oninput="adminLogsSearch(this.value)" placeholder="${__('Search logs...')}" autocomplete="off" style="flex:1;min-width:180px;padding:0.3rem 0.5rem;border:1px solid var(--border-default);border-radius:4px;font-size:0.82rem;background:var(--bg-surface);color:var(--text-primary);">
              <select id="logsLevelFilter" style="padding:0.3rem 0.5rem;border:1px solid var(--border-default);border-radius:4px;font-size:0.82rem;">
                <option value="WARNING">⚠️ WARNING+</option>
                <option value="ERROR">🔴 ERROR+</option>
                <option value="CRITICAL">🚨 CRITICAL</option>
                <option value="INFO">ℹ️ INFO+</option>
                <option value="DEBUG">🔍 DEBUG+</option>
              </select>
              <button class="btn btn-sm" onclick="loadAdminLogs()" style="background:var(--accent-blue);color:white;">↻ Refresh</button>
              <button class="btn btn-sm" onclick="exportLogsCSV()" style="background:var(--accent-green);color:white;">📥 Export CSV</button>
              <button class="btn btn-sm btn-outline" onclick="clearAdminLogs()" style="color:var(--accent-red);">🗑️ Clear</button>
              <label style="font-size:0.78rem;color:var(--text-secondary);display:flex;align-items:center;gap:0.3rem;cursor:pointer;">
                <input type="checkbox" id="logsAutoRefresh" checked> Auto-refresh
              </label>
              <span id="logsCount" style="font-size:0.78rem;color:var(--text-muted);"></span>
            </div>
            <div id="logsContainer" style="max-height:500px;overflow-y:auto;background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:8px;padding:0.5rem;font-family:monospace;font-size:0.78rem;line-height:1.6;">
              <div style="text-align:center;padding:2rem;color:var(--text-muted);">Loading logs...</div>
            </div>
        </div>
        <!-- Sessions Panel -->
        <div id="adminSessionsPanel" style="display:none;">
          <h2 style="color:var(--accent-purple);margin-bottom:0.5rem;">🟢 Active Sessions & Login History</h2>
          <p style="font-size:0.82rem;color:var(--text-secondary);margin-bottom:1rem;">Monitor who is logged in, login/logout history, and force-logoff users.</p>
          <div style="display:flex;gap:0.5rem;margin-bottom:1rem;align-items:center;flex-wrap:wrap;">
            <button class="btn btn-sm" onclick="loadSessions()" style="background:var(--accent-blue);color:white;">↻ Refresh</button>
            <span id="sessionsOnlineCount" style="font-size:0.82rem;color:var(--accent-green);font-weight:600;"></span>
            <label style="font-size:0.78rem;color:var(--text-muted);display:flex;align-items:center;gap:0.3rem;margin-left:auto;">
              <input type="checkbox" id="sessionsAutoRefresh" onchange="toggleSessionsAutoRefresh()"> Auto-refresh (10s)
            </label>
          </div>
          <!-- Online users -->
          <div id="sessionsOnline" style="margin-bottom:1rem;"></div>
          <!-- Events table -->
          <div style="overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
              <thead><tr style="background:var(--bg-elevated);">
                <th style="text-align:left;padding:0.4rem;border-bottom:2px solid var(--border-default);">Time</th>
                <th style="text-align:left;padding:0.4rem;border-bottom:2px solid var(--border-default);">User</th>
                <th style="text-align:left;padding:0.4rem;border-bottom:2px solid var(--border-default);">Event</th>
                <th style="text-align:left;padding:0.4rem;border-bottom:2px solid var(--border-default);">IP</th>
                <th style="text-align:left;padding:0.4rem;border-bottom:2px solid var(--border-default);">User Agent</th>
              </tr></thead>
              <tbody id="sessionsTableBody"><tr><td colspan="5" style="text-align:center;padding:1.5rem;color:var(--text-muted);">Click Refresh to load sessions</td></tr></tbody>
            </table>
          </div>
        </div>
        <!-- Menu Layout Panel -->
        <div id="adminMenuLayoutPanel" style="display:none;">
          <h2 style="color:var(--accent-purple);margin-bottom:0.5rem;">📋 Menu Layout</h2>
          <p style="font-size:0.82rem;color:var(--text-secondary);margin-bottom:0.7rem;">
            Manage sidebar groups, add tabs, and reorder items. Changes apply immediately.
          </p>
          <div style="display:flex;gap:0.5rem;margin-bottom:1rem;flex-wrap:wrap;">
            <button class="btn btn-sm btn-outline" onclick="addMenuGroup()">➕ Add Group</button>
          </div>
          <div id="menuLayoutList"></div>
        </div>
      </div>
    `;
    // Reset flags since DOM was rebuilt
    window._adminDbLoaded = false;
  } catch(e) {
    container.innerHTML = '<div style="padding:2rem;text-align:center;">' +
      '<h3 style="color:var(--accent-red);margin-bottom:0.5rem;">Error Loading System Control</h3>' +
      '<p style="color:var(--text-secondary);">' + (e.message || 'An unexpected error occurred') + '</p>' +
      '<button class="btn btn-sm" onclick="loadAdminPanel()" style="margin-top:0.5rem;">Retry</button>' +
      '</div>';
  }
  };

  // ---- Visibility Matrix ----
  window.loadVisibilityMatrix = async function() {
    var el = document.getElementById('visMatrixBody');
    if (!el) return;
    try {
      var data = await api('/admin/visibility-matrix');
      if (!data || data._error || data._forbidden) {
        el.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--accent-red);">Failed to load matrix</div>';
        return;
      }
      window._visMatrixData = data;
      _renderVisMatrix(data, 'all');
    } catch(e) {
      el.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--accent-red);">Error: ' + esc(e.message) + '</div>';
    }
  };

  function _renderVisMatrix(data, filter) {
    var el = document.getElementById('visMatrixBody');
    if (!el) return;
    var tabs = data.tabs || {};
    var roles = data.roles || [];
    var tabIds = Object.keys(tabs);
    if (tabIds.length === 0 || roles.length === 0) {
      el.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--text-muted);">No data</div>';
      return;
    }
    // Filter roles
    var filtered = roles.filter(function(r) {
      var count = 0;
      tabIds.forEach(function(tid) { if (r.tab_access[tid]) count++; });
      r._visibleCount = count;
      r._isFull = count === tabIds.length;
      r._isNone = count === 0;
      r._isPartial = count > 0 && count < tabIds.length;
      if (filter === 'all') return true;
      if (filter === 'full') return r._isFull;
      if (filter === 'partial') return r._isPartial;
      if (filter === 'none') return r._isNone;
      if (filter === 'superadmin') return r.is_superuser;
      return true;
    });
    // Update filter button active states
    document.querySelectorAll('.vis-filter').forEach(function(btn) {
      if (btn.getAttribute('data-filter') === filter) {
        btn.className = 'btn btn-sm vis-filter active';
        btn.style.background = 'var(--accent-blue)';
        btn.style.color = 'white';
      } else {
        btn.className = 'btn btn-sm btn-outline vis-filter';
        btn.style.background = '';
        btn.style.color = '';
      }
    });
    var html = '';
    if (filtered.length === 0) {
      html = '<div style="text-align:center;padding:1rem;color:var(--text-muted);">No roles match this filter</div>';
      el.innerHTML = html;
      return;
    }
    html += '<div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:0.4rem;">Showing ' + filtered.length + ' of ' + roles.length + ' roles</div>';
    html += '<table style="width:100%;border-collapse:collapse;font-size:0.78rem;">';
    // Header row
    html += '<thead><tr style="border-bottom:2px solid var(--border-default);">';
    html += '<th style="padding:0.4rem 0.6rem;text-align:left;position:sticky;left:0;background:var(--bg-elevated);z-index:1;min-width:140px;">Role</th>';
    tabIds.forEach(function(tid) {
      html += '<th style="padding:0.4rem;text-align:center;min-width:80px;white-space:nowrap;" title="' + esc(tabs[tid].permission) + '">' + esc(tabs[tid].label.split(' ').slice(1).join(' ')) + '</th>';
    });
    html += '<th style="padding:0.4rem;text-align:center;min-width:50px;">Count</th>';
    html += '</tr></thead><tbody>';
    // Role rows
    filtered.forEach(function(r) {
      var visibleCount = r._visibleCount;
      var isSuper = r.is_superuser;
      var rowBg = isSuper ? 'background:rgba(106,27,154,0.05);' : '';
      html += '<tr data-role-id="' + r.id + '" style="border-bottom:1px solid var(--border-default);' + rowBg + 'cursor:pointer;" onclick="simulateRole(' + r.id + ')">';
      html += '<td style="padding:0.4rem 0.6rem;font-weight:600;position:sticky;left:0;background:var(--bg-elevated);z-index:1;">';
      html += esc(r.name);
      if (r.is_system) html += ' <span style="font-size:0.65rem;color:var(--text-muted);">(system)</span>';
      if (isSuper) html += ' <span style="font-size:0.65rem;color:var(--accent-purple);">★</span>';
      html += ' <span style="font-size:0.65rem;color:var(--accent-blue);">▸ simulate</span>';
      html += '</td>';
      tabIds.forEach(function(tid) {
        var has = r.tab_access[tid];
        var cellStyle = has
          ? 'color:var(--accent-green);background:rgba(46,125,50,0.08);'
          : 'color:var(--accent-red);background:rgba(244,67,54,0.06);';
        html += '<td style="padding:0.4rem;text-align:center;' + cellStyle + 'font-weight:600;">' + (has ? '✅' : '❌') + '</td>';
      });
      html += '<td style="padding:0.4rem;text-align:center;font-weight:600;color:' + (visibleCount === tabIds.length ? '#2e7d32' : visibleCount === 0 ? 'var(--accent-red)' : 'var(--text-primary)') + ';">' + visibleCount + '/' + tabIds.length + '</td>';
      html += '</tr>';
    });
    html += '</tbody></table>';
    el.innerHTML = html;
  }

  window.filterVisMatrix = function(filter, btn) {
    if (!window._visMatrixData) return;
    _renderVisMatrix(window._visMatrixData, filter);
  };
  
  // Simulate a role -- show exactly which tabs it would see
  window.simulateRole = function(roleId) {
    var data = window._visMatrixData;
    if (!data) return;
    var role = data.roles.find(function(r) { return r.id === roleId; });
    if (!role) return;
    var tabs = data.tabs;
    var tabIds = Object.keys(tabs);
    var sim = document.getElementById('roleSimulator');
    if (!sim) return;

    sim.style.display = 'block';
    document.getElementById('simRoleName').textContent = role.name + (role.is_superuser ? ' ★' : '') + (role.is_system ? ' (system)' : '');

    var permCountVal = role.permission_count || 0;
    document.getElementById('simPermCount').textContent = permCountVal + ' permission(s)';
    document.getElementById('simPermList').textContent = role.is_superuser ? 'All permissions (*.*)' : permCountVal + ' granular permissions assigned';

    var tabBarHtml = '';
    var visibleTabs = [];
    var tabStyles = {
      'dashboard': { label: 'Dashboard' },
      'quality': { label: 'Quality Reports' },
      'analysis': { label: 'Comparative Analysis' },
      'clinical': { label: 'Clinical Intelligence' },
      'outliers': { label: 'Outliers' },
      'alerts': { label: 'Alerts' },
      'indicator-tree': { label: 'Indicator Tree' },
      'rules-manager': { label: 'Rules Manager' },
      'root-cause': { label: 'Root Cause' },
      'audit': { label: 'Audit' },
      'admin': { label: 'Admin' },
      'settings': { label: 'Settings' },
      'smart-analytics': { label: 'Smart Analytics' },
    };
    tabIds.forEach(function(tid) {
      var has = role.tab_access[tid];
      var ts = tabStyles[tid] || { label: tid };
      if (has) {
        visibleTabs.push(tid);
        tabBarHtml += '<span style="padding:0.3rem 0.7rem;border-radius:6px;font-size:0.8rem;background:var(--accent-blue);color:white;">' + ts.label + '</span>';
      } else {
        tabBarHtml += '<span style="padding:0.3rem 0.7rem;border-radius:6px;font-size:0.8rem;background:var(--bg-surface);color:var(--text-muted);text-decoration:line-through;opacity:0.5;">' + ts.label + '</span>';
      }
    });
    document.getElementById('simTabBar').innerHTML = tabBarHtml;

    var contentHtml = '';
    visibleTabs.forEach(function(tid) {
      var ts = tabStyles[tid] || { label: tid };
      contentHtml += '<span style="display:inline-block;padding:0.3rem 0.6rem;border-radius:6px;font-size:0.75rem;background:rgba(46,125,50,0.1);color:var(--accent-green);border:1px solid rgba(46,125,50,0.3);">✅ ' + ts.label + '</span>';
    });
    var hiddenCount = tabIds.length - visibleTabs.length;
    if (hiddenCount > 0) {
      contentHtml += '<span style="display:inline-block;padding:0.3rem 0.6rem;border-radius:6px;font-size:0.75rem;background:rgba(244,67,54,0.1);color:var(--accent-red);border:1px solid rgba(244,67,54,0.3);">❌ ' + hiddenCount + ' hidden</span>';
    }
    document.getElementById('simTabContent').innerHTML = contentHtml;
    sim.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  };

// Auto-load when admin panel opens
  setTimeout(function() { if (document.getElementById('visMatrixBody')) loadVisibilityMatrix(); }, 500);

  // ---- Password Change ----
  window.changePassword = function(userId, username) {
    document.getElementById('pwModalUserId').value = userId;
    document.getElementById('pwModalUsername').textContent = username;
    document.getElementById('adminPwNew').value = '';
    document.getElementById('adminPwConfirm').value = '';
    document.getElementById('pwModalError').style.display = 'none';
    document.getElementById('pwModalSuccess').style.display = 'none';
    document.getElementById('adminPwModal').style.display = 'flex';
  };

  window.closePwModal = function() {
    document.getElementById('adminPwModal').style.display = 'none';
  };

  window.saveNewPassword = async function() {
    var userId = document.getElementById('pwModalUserId').value;
    var newPw = document.getElementById('adminPwNew').value;
    var confirmPw = document.getElementById('adminPwConfirm').value;
    var errEl = document.getElementById('pwModalError');
    var okEl = document.getElementById('pwModalSuccess');

    errEl.style.display = 'none';
    okEl.style.display = 'none';

    if (!newPw) { errEl.textContent = 'Password is required'; errEl.style.display = 'block'; return; }
    if (newPw.length < 6) { errEl.textContent = 'Password must be at least 6 characters'; errEl.style.display = 'block'; return; }
    if (newPw !== confirmPw) { errEl.textContent = 'Passwords do not match'; errEl.style.display = 'block'; return; }

    var resp = await api('/admin/users/' + userId + '/change-password', {
      method: 'POST',
      body: JSON.stringify({ new_password: newPw, confirm_password: confirmPw })
    });

    if (resp && resp.detail) {
      errEl.textContent = resp.detail;
      errEl.style.display = 'block';
      return;
    }
    if (resp && resp._error) {
      errEl.textContent = resp.detail || 'Server error';
      errEl.style.display = 'block';
      return;
    }
    okEl.textContent = '✅ Password changed successfully!';
    okEl.style.display = 'block';
    document.getElementById('adminPwNew').value = '';
    document.getElementById('adminPwConfirm').value = '';
    setTimeout(closePwModal, 1500);
  };

  // ── Hospital assignment modal ──
  window.assignHospitals = async function(userId, username) {
    var modal = document.getElementById('hospAssignModal');
    if (!modal) {
      // Create the modal dynamically if it doesn't exist
      var div = document.createElement('div');
      div.id = 'hospAssignModal';
      div.className = 'modal-overlay';
      div.style.cssText = 'display:none;position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;';
      div.innerHTML = '<div style="background:var(--bg-surface);border-radius:8px;padding:1.5rem;max-width:500px;width:90%;max-height:80vh;display:flex;flex-direction:column;">' +
        '<h3 style="color:var(--accent-blue);margin-bottom:0.5rem;">Assign Hospitals — <span id="hospAssignUser"></span></h3>' +
        '<div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.8rem;">Leave empty = all hospitals (no restriction)</div>' +
        '<div id="hospAssignList" style="flex:1;overflow-y:auto;border:1px solid var(--border-default);border-radius:6px;padding:0.5rem;max-height:50vh;"></div>' +
        '<div id="hospAssignError" style="color:var(--accent-red);font-size:0.82rem;margin-top:0.5rem;display:none;"></div>' +
        '<div style="display:flex;gap:0.5rem;margin-top:1rem;justify-content:flex-end;">' +
          '<button class="btn btn-outline" onclick="document.getElementById(\'hospAssignModal\').style.display=\'none\'">Cancel</button>' +
          '<button class="btn" style="background:var(--accent-blue);color:white;" onclick="window._saveHospAssign()">Save</button>' +
        '</div>' +
      '</div>';
      document.body.appendChild(div);
      modal = div;
    }
    document.getElementById('hospAssignUser').textContent = username;
    document.getElementById('hospAssignError').style.display = 'none';
    modal.style.display = 'flex';
    modal.dataset.userId = userId;

    var listEl = document.getElementById('hospAssignList');
    listEl.innerHTML = '<div style="color:var(--text-muted);padding:1rem;text-align:center;">Loading...</div>';

    try {
      var allHosp = await api('/hospitals/');
      var userHospResp = await api('/admin/users/' + userId + '/hospitals');
      var assignedIds = new Set((userHospResp.hospitals || []).map(function(h) { return h.id; }));
      var isRestricted = userHospResp.is_restricted;

      if (!allHosp || !allHosp.length) {
        listEl.innerHTML = '<div style="color:var(--text-muted);padding:1rem;text-align:center;">No hospitals found</div>';
        return;
      }

      var html = '<label style="display:block;padding:0.3rem 0.4rem;font-size:0.82rem;cursor:pointer;border-bottom:1px solid var(--border-default);font-weight:600;color:var(--accent-blue);">' +
        '<input type="checkbox" id="hospAssignAll" onchange="window._hospAssignToggleAll(this.checked)" style="margin-right:0.4rem;"> All Hospitals (no restriction)' +
        '</label>';
      allHosp.forEach(function(h) {
        var checked = isRestricted ? assignedIds.has(h.id) : true;
        html += '<label style="display:block;padding:0.3rem 0.4rem;font-size:0.82rem;cursor:pointer;border-bottom:1px solid var(--border-default);">' +
          '<input type="checkbox" class="hospAssignCb" value="' + h.id + '" ' + (checked ? 'checked' : '') + ' style="margin-right:0.4rem;"> ' + esc(h.name) +
          '</label>';
      });
      listEl.innerHTML = html;
      // Update "All" checkbox state
      window._hospAssignUpdateAll();
      listEl.querySelectorAll('.hospAssignCb').forEach(function(cb) {
        cb.addEventListener('change', window._hospAssignUpdateAll);
      });
    } catch(e) {
      listEl.innerHTML = '<div style="color:var(--accent-red);padding:1rem;">Failed to load hospitals: ' + esc(e.message) + '</div>';
    }
  };

  window._hospAssignToggleAll = function(checked) {
    document.querySelectorAll('.hospAssignCb').forEach(function(cb) { cb.checked = checked; });
  };

  window._hospAssignUpdateAll = function() {
    var cbs = document.querySelectorAll('.hospAssignCb');
    var allCb = document.getElementById('hospAssignAll');
    if (!allCb || !cbs.length) return;
    var allChecked = Array.from(cbs).every(function(cb) { return cb.checked; });
    allCb.checked = allChecked;
  };

  window._saveHospAssign = async function() {
    var modal = document.getElementById('hospAssignModal');
    var userId = modal.dataset.userId;
    var errEl = document.getElementById('hospAssignError');
    errEl.style.display = 'none';

    var allChecked = document.getElementById('hospAssignAll').checked;
    var hospitalIds = [];
    if (!allChecked) {
      document.querySelectorAll('.hospAssignCb:checked').forEach(function(cb) {
        hospitalIds.push(parseInt(cb.value, 10));
      });
    }

    try {
      var resp = await api('/admin/users/' + userId + '/hospitals', {
        method: 'PUT',
        body: JSON.stringify({ hospital_ids: hospitalIds })
      });
      if (resp && resp._error) {
        errEl.textContent = resp.detail || 'Server error';
        errEl.style.display = 'block';
        return;
      }
      modal.style.display = 'none';
      toastSuccess(resp.message || 'Hospitals updated');
      loadAdminPanel();
    } catch(e) {
      errEl.textContent = 'Failed: ' + (e.message || 'Network error');
      errEl.style.display = 'block';
    }
  };

  function esc(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

  window.showCreateUserModal = function() {
    window._adminEditMode = false;
    document.getElementById('adminModalTitle').textContent = 'New User';
    document.getElementById('adminEditUserId').value = '';
    document.getElementById('adminUsername').value = '';
    document.getElementById('adminUsername').removeAttribute('readonly');
    document.getElementById('adminUsername').style.background = '';
    document.getElementById('adminFullName').value = '';
    document.getElementById('adminEmail').value = '';
    document.getElementById('adminPassword').value = '';
    document.getElementById('adminPassHint').textContent = '(required)';
    document.getElementById('adminModalError').style.display = 'none';
    document.querySelectorAll('.admin-user-perm-cb').forEach(function(c) { c.checked = false; });
    document.getElementById('adminUserModal').style.display = 'flex';
  };

  window.editUser = async function(userId) {
    window._adminEditMode = true;
    var data = await api('/admin/users/' + userId);
    if (!data) return;
    document.getElementById('adminModalTitle').textContent = 'Edit User';
    document.getElementById('adminEditUserId').value = data.id;
    document.getElementById('adminUsername').value = data.username;
    document.getElementById('adminUsername').setAttribute('readonly', true);
    document.getElementById('adminUsername').style.background = 'var(--bg-elevated)';
    document.getElementById('adminFullName').value = data.full_name;
    document.getElementById('adminEmail').value = data.email;
    document.getElementById('adminPassword').value = '';
    document.getElementById('adminPassHint').textContent = '(leave blank to keep)';
    document.getElementById('adminModalError').style.display = 'none';
    var userRoleIds = (data.roles || []).map(function(r) { return r.id; });
    document.querySelectorAll('.admin-role-cb').forEach(function(cb) {
      cb.checked = userRoleIds.indexOf(parseInt(cb.value)) !== -1;
    });
    var userPermIds = (data.direct_permissions || []).map(function(p) { return p.id; });
    document.querySelectorAll('.admin-user-perm-cb').forEach(function(cb) {
      cb.checked = userPermIds.indexOf(parseInt(cb.value)) !== -1;
    });
    document.getElementById('adminUserModal').style.display = 'flex';
  };

  window.closeAdminModal = function() {
    document.getElementById('adminUserModal').style.display = 'none';
  };

  window.saveAdminUser = async function() {
    var errEl = document.getElementById('adminModalError');
    var editId = document.getElementById('adminEditUserId').value;
    var checkedRoles = document.querySelectorAll('.admin-role-cb:checked');
    var roleIds = Array.from(checkedRoles).map(function(c) { return parseInt(c.value); });
    var checkedPerms = document.querySelectorAll('.admin-user-perm-cb:checked');
    var permIds = Array.from(checkedPerms).map(function(c) { return parseInt(c.value); });
    var body = {
      username: document.getElementById('adminUsername').value,
      full_name: document.getElementById('adminFullName').value,
      email: document.getElementById('adminEmail').value,
      role_ids: roleIds,
      permission_ids: permIds,
    };
    var pw = document.getElementById('adminPassword').value;
    if (pw) body.password = pw;

    if (!body.username || !body.full_name || !body.email) {
      errEl.textContent = 'Username, full name, and email are required';
      errEl.style.display = 'block';
      return;
    }

    var resp;
    if (editId) {
      if (!pw) delete body.username; // don't send username on edit
      resp = await api('/admin/users/' + editId, { method: 'PUT', body: JSON.stringify(body) });
    } else {
      if (!pw) { errEl.textContent = 'Password is required for new users'; errEl.style.display = 'block'; return; }
      resp = await api('/admin/users', { method: 'POST', body: JSON.stringify(body) });
    }

    if (resp && resp.detail) {
      errEl.textContent = resp.detail;
      errEl.style.display = 'block';
      return;
    }
    closeAdminModal();
    loadAdminPanel();
  };

  // ---- Role editor modal ----
  window.showCreateRoleModal = function() {
    window._adminEditRoleId = null;
    document.getElementById('roleModalTitle').textContent = 'New Role';
    document.getElementById('adminEditRoleId').value = '';
    document.getElementById('adminRoleName').value = '';
    document.getElementById('adminRoleDesc').value = '';
    document.querySelectorAll('.admin-perm-cb').forEach(function(c) { c.checked = false; });
    document.getElementById('adminRoleModalError').style.display = 'none';
    document.getElementById('adminRoleModal').style.display = 'flex';
  };
  window.editRole = async function(roleId) {
    var data = await api('/admin/roles/' + roleId);
    if (!data || data._error) return;
    window._adminEditRoleId = roleId;
    document.getElementById('roleModalTitle').textContent = 'Edit Role';
    document.getElementById('adminEditRoleId').value = roleId;
    document.getElementById('adminRoleName').value = data.name || '';
    document.getElementById('adminRoleDesc').value = data.description || '';
    var permIds = data.permission_ids || [];
    document.querySelectorAll('.admin-perm-cb').forEach(function(cb) {
      cb.checked = permIds.indexOf(parseInt(cb.value)) !== -1;
    });
    document.getElementById('adminRoleModalError').style.display = 'none';
    document.getElementById('adminRoleModal').style.display = 'flex';
  };
  window.closeRoleModal = function() {
    document.getElementById('adminRoleModal').style.display = 'none';
  };
  window.saveRole = async function() {
    var errEl = document.getElementById('adminRoleModalError');
    var editId = document.getElementById('adminEditRoleId').value;
    var checkedPerms = document.querySelectorAll('.admin-perm-cb:checked');
    var permIds = Array.from(checkedPerms).map(function(c) { return parseInt(c.value); });
    var body = {
      name: document.getElementById('adminRoleName').value,
      description: document.getElementById('adminRoleDesc').value,
      permission_ids: permIds,
    };
    if (!body.name) { errEl.textContent = 'Role name is required'; errEl.style.display = 'block'; return; }
    var resp;
    if (editId) { resp = await api('/admin/roles/' + editId, { method: 'PUT', body: JSON.stringify(body) }); }
    else { resp = await api('/admin/roles', { method: 'POST', body: JSON.stringify(body) }); }
    if (resp && (resp._error || resp._forbidden || resp.detail)) {
      errEl.textContent = resp.detail || 'Error saving role'; errEl.style.display = 'block'; return;
    }
    closeRoleModal(); loadAdminPanel();
  };
  window.deleteRole = async function(roleId) {
    if (!await window.confirmDestructive({ title: __('Delete Role'), message: __('Delete this role? Users with this role will lose its permissions.'), okLabel: __('Delete') })) return;
    var resp = await api('/admin/roles/' + roleId, { method: 'DELETE' });
    if (resp && resp.detail) { toastError(resp.detail); return; }
    loadAdminPanel();
  };

  // -- Role x Permission matrix (Permissions tab) --
  window._permMatrixDirty = false;
  window.permMatrixMarkDirty = function() {
    window._permMatrixDirty = true;
    var dirty = document.getElementById('permMatrixDirty');
    var saveBtn = document.getElementById('permMatrixSaveBtn');
    if (dirty) dirty.style.display = '';
    if (saveBtn) saveBtn.style.display = '';
  };
  window.permMatrixClearDirty = function() {
    window._permMatrixDirty = false;
    var dirty = document.getElementById('permMatrixDirty');
    var saveBtn = document.getElementById('permMatrixSaveBtn');
    if (dirty) dirty.style.display = 'none';
    if (saveBtn) saveBtn.style.display = 'none';
  };

  // -- Cross-tab navigation: edit a role's permissions in the matrix --
  window.editRolePermsInMatrix = function(roleId) {
    window.switchAdminTab('permissions');
    var col = document.getElementById('permCol-' + roleId);
    var tableWrap = col ? col.closest('div') : null;
    if (col && tableWrap) {
      tableWrap.scrollLeft = 0;
      col.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
      col.style.outline = '2px solid var(--accent-blue)';
      setTimeout(function() { col.style.outline = ''; }, 2000);
    }
  };

  window.permMatrixSaveAll = async function() {
    var changed = {};
    document.querySelectorAll('.perm-matrix-cb').forEach(function(cb) {
      var roleId = parseInt(cb.getAttribute('data-role'), 10);
      if (!changed[roleId]) changed[roleId] = { has: [], hasnt: [] };
      if (cb.checked) changed[roleId].has.push(parseInt(cb.getAttribute('data-perm'), 10));
      else changed[roleId].hasnt.push(true);
    });
    var anyError = null;
    for (var roleIdStr in changed) {
      var roleId = parseInt(roleIdStr, 10);
      var cbs = document.querySelectorAll('.perm-matrix-cb[data-role="' + roleId + '"]');
      var permIds = Array.from(cbs).filter(function(c){ return c.checked; }).map(function(c){ return parseInt(c.getAttribute('data-perm'), 10); });
      var resp = await api('/admin/roles/' + roleId, { method: 'PUT', body: JSON.stringify({ permission_ids: permIds }) });
      if (!resp || resp._error || resp._forbidden || resp.detail) {
        anyError = (resp && resp.detail) || 'Failed to save role permissions';
        break;
      }
    }
    if (anyError) {
      toastError(anyError);
      return;
    }
    toastSuccess('Role permissions saved');
    window.permMatrixClearDirty();
    loadAdminPanel();
  };

  // -- Expandable role permission codenames (Roles tab) --
  window._expandedRoleIds = window._expandedRoleIds || [];
  window.toggleRolePerms = function(roleId) {
    var row = document.getElementById('rolePermsRow-' + roleId);
    var caret = document.getElementById('roleCaret-' + roleId);
    if (!row) return;
    var show = row.style.display === 'none';
    row.style.display = show ? '' : 'none';
    if (caret) caret.textContent = show ? '▾' : '▸';
    var ids = window._expandedRoleIds;
    var idx = ids.indexOf(roleId);
    if (show && idx === -1) ids.push(roleId);
    if (!show && idx !== -1) ids.splice(idx, 1);
  };

  window.deactivateUser = async function(userId) {
    if (!await window.confirmDestructive({ title: __('Deactivate User'), message: __('Deactivate this user? They will not be able to log in.'), okLabel: __('Deactivate') })) return;
    await api('/admin/users/' + userId, { method: 'DELETE' });
    loadAdminPanel();
  };

  // -- Admin Tab Switching
  window.switchAdminTab = function(tab) {
    document.querySelectorAll(".admin-tab-btn").forEach(function(btn){
      btn.style.background="var(--bg-surface-hover)";
      btn.style.color="var(--text-secondary)";
    });
    var ab=document.getElementById("atab-"+tab);
    if(ab){ab.style.background="var(--accent-purple)";ab.style.color="white";}
    var u=document.getElementById("adminUsersPanel");
    var d=document.getElementById("adminDatabasePanel");
    var c=document.getElementById("adminControlPanel");
    var l=document.getElementById("adminLogsPanel");
    var s=document.getElementById("adminSessionsPanel");
    var m=document.getElementById("adminMenuLayoutPanel");
    var isUsersFamily = (tab==="users"||tab==="roles"||tab==="permissions");
    if(u)u.style.display=isUsersFamily?"block":"none";
    var us=document.getElementById("adminUsersSubPanel");
    var rs=document.getElementById("adminRolesSubPanel");
    var psn=document.getElementById("adminPermsSubPanel");
    if(us)us.style.display=tab==="users"?"block":"none";
    if(rs)rs.style.display=tab==="roles"?"block":"none";
    if(psn)psn.style.display=tab==="permissions"?"block":"none";
    if(d)d.style.display=tab==="database"?"block":"none";
    if(c)c.style.display=tab==="control"?"block":"none";
    if(l)l.style.display=tab==="logs"?"block":"none";
    if(s)s.style.display=tab==="sessions"?"block":"none";
    if(m)m.style.display=tab==="menu"?"block":"none";
    if(tab==="database"){loadAdminDbStatus();window._adminDbLoaded=true;}
    if(tab==="control"){adminLoadControlSettings();}
    if(tab==="logs"){loadAdminLogs();_startLogsAutoRefresh();}
    if(tab==="sessions"){loadSessions();}
    if(tab==="menu"){adminMenuLayoutPanel();}
  };

  // ── Menu Layout Panel ──────────────────────────────────────────────────────

  window.adminMenuLayoutPanel = function() {
    _loadMenuTabRegistry().then(loadMenuLayout);
  };

  window.loadMenuLayout = async function() {
    var el = document.getElementById('menuLayoutList');
    if (!el) return;
    try {
      var resp = await api('/menu');
      var groups = (resp && resp.groups) || [];
      _renderMenuLayout(groups, el);
    } catch(e) {
      el.innerHTML = '<div style="color:var(--accent-red);padding:1rem;">Failed to load menu: ' + esc(e.message) + '</div>';
    }
  };

  function _renderMenuLayout(groups, el) {
    if (!groups.length) {
      el.innerHTML = '<div style="color:var(--text-muted);padding:1rem;">No groups. Click "Add Group" to create one.</div>';
      return;
    }
    var html = '';
    groups.forEach(function(g, gi) {
      var firstG = gi === 0, lastG = gi === groups.length - 1;
      var liftBtn = '<button class="btn btn-sm btn-outline" style="font-size:0.7rem;padding:0.15rem 0.4rem;' + (firstG ? 'opacity:0.35;' : '') + '" ' + (firstG ? 'disabled' : '') + ' onclick="moveMenuGroup(' + g.id + ',-1)" title="Move up">⬆</button>';
      var dropBtn = '<button class="btn btn-sm btn-outline" style="font-size:0.7rem;padding:0.15rem 0.4rem;' + (lastG ? 'opacity:0.35;' : '') + '" ' + (lastG ? 'disabled' : '') + ' onclick="moveMenuGroup(' + g.id + ',1)" title="Move down">⬇</button>';
      html += '<div style="border:1px solid var(--border-default);border-radius:8px;margin-bottom:0.6rem;overflow:hidden;">';
      html += '<div style="display:flex;align-items:center;gap:0.5rem;padding:0.6rem 0.8rem;background:var(--bg-surface-hover);">';
      html += '<span style="font-size:0.9rem;">' + esc(g.icon) + '</span>';
      html += '<span style="flex:1;font-weight:600;font-size:0.82rem;">' + esc(g.name) + '</span>';
      html += liftBtn + dropBtn;
      html += '<button class="btn btn-sm btn-outline" onclick="editMenuGroup(' + g.id + ')" title="Edit">✏️</button>';
      html += '<button class="btn btn-sm btn-outline" style="color:var(--accent-red);" onclick="deleteMenuGroup(' + g.id + ')" title="Delete">🗑️</button>';
      html += '</div>';
      g.items.forEach(function(item, ii) {
        var firstI = ii === 0, lastI = ii === g.items.length - 1;
        var upBtn = '<button class="btn btn-sm btn-outline" style="font-size:0.6rem;padding:0.1rem 0.35rem;' + (firstI ? 'opacity:0.35;' : '') + '" ' + (firstI ? 'disabled' : '') + ' onclick="moveMenuItem(' + item.id + ',' + g.id + ',-1)" title="Move up">⬆</button>';
        var dnBtn = '<button class="btn btn-sm btn-outline" style="font-size:0.6rem;padding:0.1rem 0.35rem;' + (lastI ? 'opacity:0.35;' : '') + '" ' + (lastI ? 'disabled' : '') + ' onclick="moveMenuItem(' + item.id + ',' + g.id + ',1)" title="Move down">⬇</button>';
        html += '<div style="display:flex;align-items:center;gap:0.5rem;padding:0.4rem 0.8rem 0.4rem 2rem;border-top:1px solid var(--border-default);font-size:0.8rem;">';
        html += '<span>' + esc(item.icon) + '</span>';
        html += '<span style="flex:1;">' + esc(item.label) + '</span>';
        html += '<span style="font-size:0.65rem;color:var(--text-muted);">[ ' + esc(item.tab_key) + ' ]</span>';
        html += upBtn + dnBtn;
        html += '<button class="btn btn-sm btn-outline" style="color:var(--accent-red);font-size:0.7rem;" onclick="deleteMenuItem(' + item.id + ')" title="Remove">✕</button>';
        html += '</div>';
      });
      // Add tab dropdown
      html += '<div style="display:flex;align-items:center;gap:0.5rem;padding:0.4rem 0.8rem 0.4rem 2rem;border-top:1px solid var(--border-default);">';
      html += '<select id="addTabSelect_' + g.id + '" style="flex:1;font-size:0.78rem;padding:0.3rem;border:1px solid var(--border-default);border-radius:4px;background:var(--bg-surface);color:var(--text-primary);">';
      html += '<option value="">+ Add tab to this group...</option>';
      // Populate with tabs not already in this group
      var inGroup = new Set(g.items.map(function(i) { return i.tab_key; }));
      if (window._menuTabRegistry) {
        window._menuTabRegistry.forEach(function(t) {
          if (!inGroup.has(t.key)) {
            html += '<option value="' + t.key + '">' + esc(t.icon) + ' ' + esc(t.label) + '</option>';
          }
        });
      }
      html += '</select>';
      html += '<button class="btn btn-sm" style="background:var(--accent-green);color:white;font-size:0.72rem;" onclick="addMenuItem(' + g.id + ')">Add</button>';
      html += '</div>';
      html += '</div>';
    });
    el.innerHTML = html;
  }

  // Fetch tab registry once for the dropdown
  async function _loadMenuTabRegistry() {
    if (window._menuTabRegistry) return;
    try {
      var resp = await api('/menu/tabs');
      window._menuTabRegistry = (resp && resp.tabs) || [];
    } catch(e) { window._menuTabRegistry = []; }
  }

  function _menuApiFailed(resp) {
    if (resp && resp._forbidden) return 'Access denied — menu.manage permission required';
    if (resp && resp._error) return resp.detail || 'Server error';
    if (resp && resp.detail) return (typeof resp.detail === 'string' ? resp.detail : 'Request failed');
    return null;
  }

  window.addMenuGroup = async function() {
    var name = prompt('Group name (e.g. "Data"):');
    if (!name) return;
    var icon = prompt('Icon emoji (e.g. 📊):', '📁');
    if (icon === null) icon = '📁';
    var resp = await api('/menu/groups', { method:'POST', body: JSON.stringify({name:name, icon:icon}) });
    var err = _menuApiFailed(resp);
    if (err) { toastError(err); return; }
    toastSuccess('Group added');
    loadMenuLayout();
  };

  window.editMenuGroup = async function(id) {
    var name = prompt('New group name:');
    if (!name) return;
    var icon = prompt('New icon emoji:');
    if (icon === null) return;
    var resp = await api('/menu/groups/' + id, { method:'PATCH', body: JSON.stringify({name:name, icon:icon}) });
    var err = _menuApiFailed(resp);
    if (err) { toastError(err); return; }
    toastSuccess('Group updated');
    loadMenuLayout();
  };

  window.deleteMenuGroup = async function(id) {
    if (!confirm('Delete this group and all its tabs?')) return;
    var resp = await api('/menu/groups/' + id, { method:'DELETE' });
    var err = _menuApiFailed(resp);
    if (err) { toastError(err); return; }
    toastSuccess('Group deleted');
    loadMenuLayout();
  };

  window.addMenuItem = async function(groupId) {
    var sel = document.getElementById('addTabSelect_' + groupId);
    var tabKey = sel ? sel.value : '';
    if (!tabKey) return;
    var resp = await api('/menu/items', { method:'POST', body: JSON.stringify({group_id: groupId, tab_key: tabKey}) });
    var err = _menuApiFailed(resp);
    if (err) { toastError(err); return; }
    toastSuccess('Tab added');
    loadMenuLayout();
  };

  window.deleteMenuItem = async function(id) {
    var resp = await api('/menu/items/' + id, { method:'DELETE' });
    var err = _menuApiFailed(resp);
    if (err) { toastError(err); return; }
    toastSuccess('Tab removed');
    loadMenuLayout();
  };

  window.moveMenuGroup = async function(id, dir) {
    var data = await api('/menu');
    if (!data || !data.groups) return;
    var groups = data.groups;
    var i = groups.findIndex(function(g) { return g.id === id; });
    if (i < 0) return;
    var j = i + dir;
    if (j < 0 || j >= groups.length) return;
    var a = groups[i], b = groups[j];
    var r1 = await api('/menu/groups/' + a.id, { method:'PATCH', body: JSON.stringify({sort_order: b.sort_order}) });
    var e1 = _menuApiFailed(r1);
    if (e1) { toastError(e1); return; }
    var r2 = await api('/menu/groups/' + b.id, { method:'PATCH', body: JSON.stringify({sort_order: a.sort_order}) });
    var e2 = _menuApiFailed(r2);
    if (e2) { toastError(e2); return; }
    toastSuccess('Groups reordered');
    loadMenuLayout();
  };

  window.moveMenuItem = async function(id, groupId, dir) {
    var data = await api('/menu');
    if (!data || !data.groups) return;
    var g = data.groups.find(function(x) { return x.id === groupId; });
    if (!g || !g.items) return;
    var i = g.items.findIndex(function(it) { return it.id === id; });
    if (i < 0) return;
    var j = i + dir;
    if (j < 0 || j >= g.items.length) return;
    var a = g.items[i], b = g.items[j];
    var r1 = await api('/menu/items/' + a.id, { method:'PATCH', body: JSON.stringify({sort_order: b.sort_order}) });
    var e1 = _menuApiFailed(r1);
    if (e1) { toastError(e1); return; }
    var r2 = await api('/menu/items/' + b.id, { method:'PATCH', body: JSON.stringify({sort_order: a.sort_order}) });
    var e2 = _menuApiFailed(r2);
    if (e2) { toastError(e2); return; }
    toastSuccess('Tabs reordered');
    loadMenuLayout();
  };

  var _logsInterval=null;
  function _startLogsAutoRefresh(){
    if(_logsInterval){clearInterval(_logsInterval);_logsInterval=null;}
    if(document.getElementById('logsAutoRefresh')&&document.getElementById('logsAutoRefresh').checked){
      _logsInterval=setInterval(loadAdminLogs,10000);
    }
  }
  window.loadAdminLogs = async function() {
    var el=document.getElementById('logsContainer');
    var countEl=document.getElementById('logsCount');
    if(!el)return;
    var level=document.getElementById('logsLevelFilter')?document.getElementById('logsLevelFilter').value:'WARNING';
    try{
      var data=await api('/logs?level='+level+'&limit=200');
      if(!data||data._error){el.innerHTML='<div style="padding:1rem;color:var(--accent-red);">Failed to load logs: '+(data?data.detail||data._error:'No response')+'</div>';return;}
      var entries=data.entries||[];
      window._logsEntries=entries;
      if(countEl)countEl.textContent=entries.length+' / '+data.total+' entries';
      _adminKpi('adminKpiLogs', entries.length);
      _adminRenderLogs();
    }catch(err){
      el.innerHTML='<div style="padding:1rem;color:var(--accent-red);">Error loading logs: '+err.message+'</div>';
    }
  };
  window.adminLogsSearch = function(v) {
    window._logsSearch = (v||'').trim().toLowerCase();
    _adminRenderLogs();
  };
  window.adminLogsClearSearch = function() {
    window._logsSearch = '';
    var input = document.getElementById('logsSearchFilter');
    if (input) input.value = '';
    _adminRenderLogs();
  };
  function _adminRenderLogs() {
    var el=document.getElementById('logsContainer');
    if(!el)return;
    var entries=window._logsEntries||[];
    var q=window._logsSearch||'';
    var filtered=entries;
    if(q){
      filtered=entries.filter(function(e){
        return (e.message||'').toLowerCase().indexOf(q)!==-1
          || (e.logger||'').toLowerCase().indexOf(q)!==-1
          || (e.level||'').toLowerCase().indexOf(q)!==-1;
      });
    }
    if(filtered.length===0){
      el.innerHTML='<div style="padding:1.5rem;text-align:center;color:var(--text-muted);">'+(q?__('No log entries match'):__('No log entries at this level.'))+'</div>';
      return;
    }
    var html='';
    filtered.forEach(function(e){
      var lv=esc(e.level)||'DEBUG';
      html+='<div class="admin-log-row">';
      html+='<span style="color:var(--text-muted);white-space:nowrap;min-width:130px;">'+esc(e.time)+'</span>';
      html+='<span class="log-badge log-badge-'+lv+'">'+lv+'</span>';
      html+='<span style="color:var(--text-muted);min-width:120px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="'+esc(e.logger)+'">'+esc(e.logger)+'</span>';
      html+='<span style="flex:1;word-break:break-word;">'+esc(e.message)+'</span>';
      html+='</div>';
    });
    el.innerHTML=html;
  }
  window.clearAdminLogs = async function() {
    if (!await window.confirmDestructive({ title: __('Clear logs'), message: __('Clear all log entries from memory?'), details: __('This cannot be undone.'), okLabel: __('Clear logs') })) return;
    try{
      await api('/logs',{method:'DELETE'});
      loadAdminLogs();
      if(typeof toastSuccess==='function')toastSuccess(__('Logs cleared'));
    }catch(err){
      if(typeof toastError==='function')toastError(__('Failed to clear logs')+': '+err.message);
    }
  };
  window.exportLogsCSV = function() {
    var container=document.getElementById('logsContainer');
    if(!container)return;
    var rows=container.querySelectorAll('div[style]');
    if(!rows.length){return;}
    var csv='Time,Level,Logger,Message\n';
    rows.forEach(function(row){
      var spans=row.querySelectorAll('span');
      if(spans.length>=4){
        var time=spans[0].textContent.trim();
        var level=spans[1].textContent.trim();
        var logger=spans[2].textContent.trim();
        var message=spans[3].textContent.trim().replace(/"/g,'""');
        csv+='"'+time+'","'+level+'","'+logger+'","'+message+'"\n';
      }
    });
    var blob=new Blob([csv],{type:'text/csv;charset=utf-8;'});
    var url=URL.createObjectURL(blob);
    var a=document.createElement('a');
    a.href=url;
    a.download='server-logs-'+new Date().toISOString().slice(0,10)+'.csv';
    a.click();
    URL.revokeObjectURL(url);
  };
  // Bind auto-refresh checkbox
  document.addEventListener('change',function(e){
    if(e.target&&e.target.id==='logsAutoRefresh'){
      if(e.target.checked){_logsInterval=setInterval(loadAdminLogs,10000);}
      else if(_logsInterval){clearInterval(_logsInterval);_logsInterval=null;}
    }
  });



  async function loadAdminDbStatus() {
    var el=document.getElementById("adminDbStatus");
    if(!el)return;el.innerHTML="Loading...";
    var data=await api("/config/database-status");
    if(!data||data._error){el.innerHTML="<span style=\"color:var(--accent-red)\">Failed to load</span>";_adminKpi('adminKpiDb', '\u2717 ?');return;}
    _adminKpi('adminKpiDb', data.connected ? ('\u2713 ' + (data.engine || __('Connected'))) : '\u2717 ' + __('Not connected'));
    if(data.connected){
      var h="<span style=\"color:var(--accent-green)\">Connected to "+(data.engine||"PostgreSQL")+"</span><br>";
      h+="<div style=\"margin-top:0.5rem;display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:0.5rem;\">";
      var hosp=data.total_hospitals||data.hospital_count||0;var actv=data.active_hospitals||data.active_count||0;
      var iv=data.total_indicator_values||data.indicator_value_count||0;var qs=data.total_quality_scores||data.quality_score_count||0;
      var ind=data.total_indicators||data.indicator_count||0;var rul=data.total_rules||data.rule_count||0;
      var tbl=(data.tables&&data.tables.length)||data.table_count||0;
      h+="<div style=\"background:var(--bg-surface-hover);padding:0.5rem;border-radius:6px;\"><strong style=\"color:var(--accent-blue)\">Hospitals</strong><br>"+hosp+" total ("+actv+" active)</div>";
      h+="<div style=\"background:var(--bg-surface-hover);padding:0.5rem;border-radius:6px;\"><strong style=\"color:var(--accent-blue)\">Indicator Values</strong><br>"+iv.toLocaleString()+" records</div>";
      h+="<div style=\"background:var(--bg-surface-hover);padding:0.5rem;border-radius:6px;\"><strong style=\"color:var(--accent-blue)\">Quality Scores</strong><br>"+qs.toLocaleString()+" records</div>";
      h+="<div style=\"background:var(--bg-surface-hover);padding:0.5rem;border-radius:6px;\"><strong style=\"color:var(--accent-blue)\">Indicators</strong><br>"+ind+" configured</div>";
      h+="<div style=\"background:var(--bg-surface-hover);padding:0.5rem;border-radius:6px;\"><strong style=\"color:var(--accent-blue)\">Rules</strong><br>"+rul+" active</div>";
      h+="<div style=\"background:var(--bg-surface-hover);padding:0.5rem;border-radius:6px;\"><strong style=\"color:var(--accent-blue)\">Tables</strong><br>"+tbl+" created</div></div>";
      el.innerHTML=h;
    }else{el.innerHTML="<span style=\"color:var(--accent-red)\">Not connected</span><br><span style=\"font-size:0.8rem;color:var(--text-muted)\">"+(data.error||"DATABASE_URL not set")+"</span>";}
  }

  window.adminPreviewDb=function(){
    var ct=document.getElementById("adminDbPreviewContainer");var co=document.getElementById("adminDbPreviewContent");
    if(!ct||!co)return;ct.style.display="block";co.innerHTML="Loading...";
    api("/config/database/preview").then(function(data){if(!data)return; // eslint-disable-line
      if(data._error||data._forbidden){co.innerHTML="<p style=\"color:var(--accent-red)\">Error: "+(data.detail||"request failed")+"</p>";return;}
      if(!data.tables||!data.tables.length){co.innerHTML="<p style=\"color:var(--text-muted)\">No tables.</p>";return;}
      var h="<div style=\"margin-bottom:0.6rem;font-size:0.82rem;color:var(--text-secondary)\"><strong>"+data.total_tables+"</strong> tables found</div>";
      data.tables.forEach(function(t){
        h+="<div style=\"margin-bottom:0.6rem;border:1px solid var(--border-default);border-radius:6px;overflow:hidden;\">";
        h+="<div class=\"admin-db-table-toggle\" style=\"cursor:pointer;padding:0.5rem 0.7rem;background:var(--bg-surface-hover);display:flex;justify-content:space-between;align-items:center;\" onclick=\"var b=this.nextElementSibling;b.style.display=b.style.display===\x27none\x27?\x27block\x27:\x27none\x27\">";
        h+="<span><strong style=\"color:var(--accent-blue)\">"+t.name+"</strong> ("+t.row_count+" rows, "+t.columns.length+" cols)</span>";
        h+="<span style=\"color:var(--text-muted);font-size:0.75rem;\">▼ click</span></div><div style=\"display:none;padding:0.5rem;\">";
        if(t.preview&&t.preview.length){
          h+="<table style=\"font-size:0.75rem;width:100%;border-collapse:collapse;\"><thead><tr>"+t.columns.map(function(c){return "<th style=\"padding:0.3rem 0.5rem;border-bottom:2px solid var(--border-default);\">"+c+"</th>";}).join("")+"</tr></thead><tbody>";
          t.preview.forEach(function(r){h+="<tr>"+t.columns.map(function(c){var v=r[c];if(v===null)v="<span style=\"color:var(--text-muted);font-style:italic;\">NULL</span>";return "<td style=\"padding:0.25rem 0.5rem;border-bottom:1px solid var(--border-default);\">"+v+"</td>";}).join("")+"</tr>";});
          h+="</tbody></table>";if(t.row_count>5)h+="<div style=\"font-size:0.72rem;color:var(--text-muted)\">Showing 5 of "+t.row_count+"</div>";
        }else h+="<div style=\"color:var(--text-muted)\">No data.</div>";
        h+="</div></div>";});co.innerHTML=h;
    }).catch(function(e){co.innerHTML="<p style=\"color:var(--accent-red)\">Error: "+e.message+"</p>";});
  };

  window.adminExportDb=function(){
    var s=document.getElementById("adminDbExportStatus");if(s)s.textContent="Preparing export...";
    var btn=document.getElementById("adminBtnExportDb");if(btn)btn.disabled=true;
    window.authFetch(API_BASE+"/config/database/export",{headers:{"Content-Type":"application/json"}}).then(function(r){if(!r.ok)throw new Error("HTTP "+r.status);var d=r.headers.get("Content-Disposition")||"";var m=d.match(/filename=\"?([^"]+)\"?/);return r.blob().then(function(b){return{blob:b,filename:m?m[1]:"export.json"};});}).then(function(r){
      var u=URL.createObjectURL(r.blob);var a=document.createElement("a");a.href=u;a.download=r.filename;document.body.appendChild(a);a.click();document.body.removeChild(a);URL.revokeObjectURL(u);if(s)s.textContent="Downloaded: "+r.filename;
    }).catch(function(e){if(s)s.textContent="Failed: "+e.message;}).finally(function(){if(btn)btn.disabled=false;});
  };

  // -- Control Settings Functions --
  var _controlDirty = false;
  function _updateControlSaveButton() {
    var btn = document.getElementById('controlSaveBtn');
    if (!btn) return;
    btn.style.display = _controlDirty ? 'inline-block' : 'none';
    btn.textContent = _controlDirty ? 'Save (*)' : 'Save';
  }
  window.adminMarkControlDirty = function() {
    _controlDirty = true;
    _updateControlSaveButton();
  };
  async function adminLoadControlSettings() {
    try {
      var data = await api("/config/control/settings");
      if (data && !data._error) {
        var cb = document.getElementById("cfg_auto_disable_null");
        if (cb) cb.checked = !!data.auto_disable_null_indicators;
        var logCb = document.getElementById("cfg_structured_logging");
        if (logCb) logCb.checked = data.structured_logging_enabled !== false;
        var sqCb = document.getElementById("cfg_slow_query_logging");
        if (sqCb) sqCb.checked = data.slow_query_logging_enabled !== false;
        var hideCb = document.getElementById("cfg_hide_explanatory");
        if (hideCb) hideCb.checked = !!data.hide_explanatory_text;
        var incCb = document.getElementById("cfg_incremental_months");
        if (incCb) incCb.checked = !!data.upload_incremental_months;
      }
    } catch(e) {}
    var enabled = localStorage.getItem("dev_hints_enabled") !== "false";
    window._showDevHints = enabled;
    var dhCb = document.getElementById("cfg_dev_hints");
    if (dhCb) dhCb.checked = enabled;
    _controlDirty = false;
    _updateControlSaveButton();
    adminLoadMonthToggles();
  }
  window.adminSaveControlSettings = function() {
    var cb = document.getElementById("cfg_auto_disable_null");
    var logCb = document.getElementById("cfg_structured_logging");
    var sqCb = document.getElementById("cfg_slow_query_logging");
    var hideCb = document.getElementById("cfg_hide_explanatory");
    var incCb = document.getElementById("cfg_incremental_months");
    var val = cb ? cb.checked : false;
    var logVal = logCb ? logCb.checked : true;
    var sqVal = sqCb ? sqCb.checked : true;
    var hideVal = hideCb ? hideCb.checked : false;
    var incVal = incCb ? incCb.checked : false;
    var status = document.getElementById("controlSaveStatus");
    var btn = document.getElementById('controlSaveBtn');
    function setStatus(text, color) {
      if (status) { status.textContent = text; status.style.color = color; }
    }
    if (btn) { btn.textContent = "Saving..."; btn.disabled = true; }
    setStatus("Saving...", "var(--accent-blue)");
    (async function() {
      try {
        var result = await api("/config/control/settings", {
          method: "PUT",
          body: JSON.stringify({
            auto_disable_null_indicators: val ? "true" : "false",
            structured_logging_enabled: logVal ? "true" : "false",
            slow_query_logging_enabled: sqVal ? "true" : "false",
            hide_explanatory_text: hideVal ? "true" : "false",
            upload_incremental_months: incVal ? "true" : "false"
          })
        });
        if (!result || result._error || result._forbidden) {
          if (btn) { btn.textContent = "Save (*)"; btn.disabled = false; }
          setStatus("✗ Save failed", "var(--accent-red)");
          toastError("Analysis Control save failed");
          return;
        }
        _controlDirty = false;
        _updateControlSaveButton();
        setStatus("✓ Saved", "var(--accent-green)");
        toastSuccess("Analysis Control saved");
        try {
          await api("/dashboard/recalculate-completeness", { method: "POST" });
          setStatus("✓ Saved & scores updated", "var(--accent-green)");
        } catch(e) {}
        if (typeof window.loadDashboard === 'function') window.loadDashboard();
      } catch(e) {
        if (btn) { btn.textContent = "Save (*)"; btn.disabled = false; }
        setStatus("✗ Error: " + e.message, "var(--accent-red)");
        toastError("Analysis Control save error: " + e.message);
      }
    })();
  };

  window.adminToggleDevHints = function(show) {
    window._showDevHints = show;
    localStorage.setItem("dev_hints_enabled", show ? "true" : "false");
  };
  async function adminLoadMonthToggles() {
    try {
      var hospitals = await api("/hospitals/");
      var list = hospitals.filter(function(h) { return h.is_active !== false; });
      var sel = document.getElementById("monthHospitalSelect");
      if (list.length === 0 || !sel) return;
      sel.innerHTML = list.map(function(h) { return "<option value=\"" + h.id + "\">" + h.name + "</option>"; }).join("");
      var prevId = window._monthHospitalId;
      if (prevId && list.some(function(h) { return h.id === prevId; })) {
        sel.value = prevId;
      } else {
        window._monthHospitalId = list[0].id;
        sel.value = list[0].id;
      }
      adminLoadMonthTogglesForHospital(parseInt(sel.value));
    } catch(e) {}
  }
  async function adminLoadMonthTogglesForHospital(hospitalId) {
    window._monthHospitalId = hospitalId;
    try {
      var months = await api("/analysis/months");
      window._monthList = months;
      try {
        var settings = await api("/config/month-settings?hospital_id=" + hospitalId);
        var enabled = Array.isArray(settings.enabled_months) ? settings.enabled_months : months;
        window._monthSettings = {};
        months.forEach(function(m) { window._monthSettings[m] = enabled.indexOf(m) >= 0; });
      } catch(e2) {
        window._monthSettings = {};
        months.forEach(function(m) { window._monthSettings[m] = true; });
      }
      adminRenderMonthToggles();
    } catch(e) {}
  }
  window.onMonthHospitalChange = function() {
    var sel = document.getElementById("monthHospitalSelect");
    if (sel && sel.value) adminLoadMonthTogglesForHospital(parseInt(sel.value));
  };
  window.onMonthToggleChange = function(month, checked) {
    window._monthSettings[month] = checked;
    adminRenderMonthToggles();
  };
  function adminRenderMonthToggles() {
    var container = document.getElementById("monthToggleList");
    if (!container || !window._monthList) return;
    container.innerHTML = window._monthList.map(function(m) {
      var enabled = window._monthSettings[m];
      var bg = enabled ? "var(--severity-success-bg)" : "var(--severity-critical-bg)";
      var border = enabled ? "var(--accent-green)" : "var(--accent-red)";
      var label = enabled ? "Enabled" : "Disabled";
      var icon = enabled ? "✓" : "✗";
      return "<label style=\"display:inline-flex;align-items:center;gap:0.4rem;padding:0.3rem 0.6rem;background:" + bg + ";border:1px solid " + border + ";border-radius:4px;cursor:pointer;font-size:0.82rem;\">" +
        "<input type=\"checkbox\" value=\"" + m + "\" " + (enabled ? "checked" : "") + " onchange=\"onMonthToggleChange('" + m + "', this.checked)\" style=\"width:14px;height:14px;\">" +
        "<span>" + m + "</span>" +
        "<span style=\"font-size:0.65rem;color:" + (enabled ? "var(--accent-green)" : "var(--accent-red)") + ";font-weight:600;\">" + icon + " " + label + "</span></label>";
    }).join("");
  }
  window.toggleAllAnalysisMonths = function(enabled) {
    for (var m in window._monthSettings) {
      window._monthSettings[m] = enabled;
    }
    adminRenderMonthToggles();
  };
  window.adminSaveAllMonthSettings = function() {
    var hospitalId = window._monthHospitalId;
    if (!hospitalId) {
      var st = document.getElementById("monthSaveStatus");
      if (st) { st.textContent = "✗ No hospital selected"; st.style.color = "var(--accent-red)"; }
      return;
    }
    var st = document.getElementById("monthSaveStatus");
    if (st) { st.textContent = "Saving..."; st.style.color = "var(--accent-blue)"; }
    var promises = [];
    for (var m in window._monthSettings) {
      promises.push(api("/config/month-settings", {
        method: "PUT",
        body: JSON.stringify({ month: m, enabled: window._monthSettings[m], hospital_id: hospitalId })
      }));
    }
    Promise.all(promises).then(function() {
      if (st) {
        var enabledCount = Object.values(window._monthSettings).filter(Boolean).length;
        var totalCount = Object.keys(window._monthSettings).length;
        st.textContent = "✓ Saved — " + enabledCount + "/" + totalCount + " months enabled";
        st.style.color = "var(--accent-green)";
        setTimeout(function() { st.textContent = ""; }, 5000);
      }
    }).catch(function(e) {
      if (st) { st.textContent = "✗ Error: " + e.message; st.style.color = "var(--accent-red)"; }
    });
  };

  // -- Quality Score Repair (Database tab) --
  window.adminCheckScoreRepair = async function() {
    var statusEl = document.getElementById('adminRepairStatus');
    var previewEl = document.getElementById('adminRepairPreview');
    var runBtn = document.getElementById('adminBtnRepairRun');
    if (statusEl) statusEl.textContent = 'Checking...';
    if (previewEl) previewEl.style.display = 'none';
    if (runBtn) runBtn.style.display = 'none';
    var data = await api('/admin/quality-scores/repair-preview');
    if (!data || data._error || data._forbidden || data.detail) {
      if (statusEl) statusEl.textContent = 'Failed: ' + ((data && (data.detail || data._error)) || 'no response');
      return;
    }
    var n = data.mismatch_count || 0;
    window._scoreRepairCount = n;
    if (statusEl) statusEl.textContent = n === 0
      ? __('All ${n} rows consistent').replace('${n}', data.total_rows)
      : n + ' of ' + data.total_rows + ' rows inconsistent';
    if (previewEl && n > 0) {
      var rows = (data.mismatches || []).slice(0, 50).map(function(m) {
        return '<div style="padding:0.15rem 0;border-bottom:1px solid var(--border-default);">'
          + '<strong>' + esc(String(m.hospital_id)) + '</strong> / ' + esc(m.month)
          + ' — stored <span style="color:var(--accent-red);">' + m.stored_score + '</span>'
          + ' → expected <span style="color:var(--accent-green);">' + m.expected_score + '</span></div>';
      }).join('');
      previewEl.innerHTML = rows + (data.truncated ? '<div style="color:var(--text-muted);">…more not shown</div>' : '');
      previewEl.style.display = 'block';
    }
    if (runBtn && n > 0) {
      runBtn.textContent = '🔧 Repair ' + n + ' Rows';
      runBtn.style.display = '';
    }
  };

  window.adminRunScoreRepair = async function() {
    if (!await window.confirmDestructive({
      title: __('Repair Quality Scores'),
      message: __('Recompute and overwrite the stored scores for all inconsistent rows?'),
      details: __('Component values are kept; only the final score is rewritten using the current weights.'),
      okLabel: __('Repair')
    })) return;
    var statusEl = document.getElementById('adminRepairStatus');
    var runBtn = document.getElementById('adminBtnRepairRun');
    if (statusEl) statusEl.textContent = 'Repairing...';
    var data = await api('/admin/quality-scores/repair', { method: 'POST' });
    if (!data || data._error || data._forbidden || data.detail) {
      if (statusEl) statusEl.textContent = 'Failed: ' + ((data && (data.detail || data._error)) || 'no response');
      return;
    }
    if (statusEl) statusEl.textContent = __('Repaired ${n} rows; ${ok} already consistent').replace('${n}', data.repaired).replace('${ok}', data.already_consistent);
    if (runBtn) runBtn.style.display = 'none';
    var previewEl = document.getElementById('adminRepairPreview');
    if (previewEl) previewEl.style.display = 'none';
    if (typeof toastSuccess === 'function') toastSuccess(__('Repaired') + ' ' + data.repaired + ' ' + __('rows'));
  };

  // -- Deep repair (recompute components from raw indicator values) --
  window.adminOnDeepToggle = function() {
    var on = document.getElementById('adminRepairDeepToggle').checked;
    document.getElementById('adminRepairDeepDesc').style.display = on ? 'block' : 'none';
    var row = document.getElementById('adminRepairDeepRow');
    row.style.display = on ? 'flex' : 'none';
    if (on) window.adminDeepCheckScoreRepair();
  };

  window.adminDeepCheckScoreRepair = async function() {
    var statusEl = document.getElementById('adminDeepStatus');
    var runBtn = document.getElementById('adminBtnDeepRepair');
    if (statusEl) statusEl.textContent = __('Checking...');
    if (runBtn) runBtn.style.display = 'none';
    var data = await api('/admin/quality-scores/repair-preview?deep=true');
    if (!data || data._error || data._forbidden || data.detail) {
      if (statusEl) statusEl.textContent = __('Failed: ') + ((data && (data.detail || data._error)) || 'no response');
      return;
    }
    var n = data.target_count || 0;
    window._deepTargetCount = n;
    if (statusEl) statusEl.textContent = n === 0
      ? __('No hospital/month pairs have raw data to rebuild')
      : __('${n} hospital/month pairs would be rebuilt from raw data').replace('${n}', n);
    if (runBtn && n > 0) {
      runBtn.textContent = '🏗️ Rebuild ' + n + ' Hospital/Months';
      runBtn.style.display = '';
    }
  };

  window._deepRepairPollTimer = null;
  window.adminDeepRunScoreRepair = async function() {
    if (!await window.confirmDestructive({
      title: __('Deep Quality Score Repair'),
      message: __('Rebuild all quality components from raw indicator values?'),
      details: __('Every hospital/month with raw data is re-analyzed with the engine pipeline: validation results, anomalies and quality scores are regenerated. This overwrites stored components and scores.'),
      okLabel: __('Rebuild')
    })) return;
    var statusEl = document.getElementById('adminDeepStatus');
    var runBtn = document.getElementById('adminBtnDeepRepair');
    if (statusEl) statusEl.textContent = __('Starting deep repair...');
    if (runBtn) runBtn.disabled = true;
    var data = await api('/admin/quality-scores/repair?deep=true', { method: 'POST' });
    if (!data || data._error || data._forbidden || data.detail) {
      if (statusEl) statusEl.textContent = __('Failed: ') + ((data && (data.detail || data._error)) || 'no response');
      if (runBtn) runBtn.disabled = false;
      return;
    }
    var taskId = data.task_id;
    if (statusEl) statusEl.textContent = __('Deep repair running for ${n} pairs...').replace('${n}', data.target_count);
    var wrap = document.getElementById('adminDeepProgressWrap');
    var bar = document.getElementById('adminDeepProgressBar');
    if (wrap) wrap.style.display = 'block';
    if (bar) bar.style.width = '0%';
    if (window._deepRepairPollTimer) clearInterval(window._deepRepairPollTimer);
    window._deepRepairPollTimer = setInterval(async function() {
      var t = await api('/tasks/' + taskId);
      if (!t) return;
      if (bar) bar.style.width = (t.progress || 0) + '%';
      if (t.status === 'done') {
        clearInterval(window._deepRepairPollTimer);
        window._deepRepairPollTimer = null;
        var r = t.result || {};
        if (statusEl) statusEl.textContent = __('Rebuilt ${n} hospital/months') + (r.failed ? ' — ' + r.failed + ' ' + __('failed') : '');
        if (runBtn) { runBtn.disabled = false; runBtn.style.display = 'none'; }
        if (wrap) wrap.style.display = 'none';
        if (typeof toastSuccess === 'function') toastSuccess(__('Deep repair finished')); 
        if (typeof loadAdminPanel === 'function') loadAdminPanel();
      } else if (t.status === 'error') {
        clearInterval(window._deepRepairPollTimer);
        window._deepRepairPollTimer = null;
        if (statusEl) statusEl.textContent = __('Failed: ') + (t.error || 'unknown');
        if (runBtn) runBtn.disabled = false;
        if (wrap) wrap.style.display = 'none';
      }
    }, 1500);
  };

  // Close button for DB preview
  var closeBtn=document.getElementById("adminDbCloseBtn");
  if(closeBtn)closeBtn.onclick=function(){document.getElementById("adminDbPreviewContainer").style.display="none";};

  // -- Sessions Panel -----------------------------------------------
  var _sessionsInterval = null;
  window.loadSessions = async function() {
    var tbody = document.getElementById('sessionsTableBody');
    var onlineEl = document.getElementById('sessionsOnline');
    var countEl = document.getElementById('sessionsOnlineCount');
    if (!tbody) return;
    try {
      var data = await api('/auth/sessions?limit=100');
      var events = data.events || [];
      var onlineIds = data.online || [];
      var onlineMap = {};
      events.forEach(function(e) {
        if (onlineIds.indexOf(e.user_id) >= 0 && e.event === 'login') {
          onlineMap[e.user_id] = e;
        }
      });
      var onlineList = Object.values(onlineMap);
      _adminKpi('adminKpiOnline', onlineList.length);
      if (countEl) {
        countEl.textContent = onlineList.length ? '\ud83d\udfe2 ' + onlineList.length + ' online' : '\u2014';
      }
      if (onlineEl) {
        if (onlineList.length) {
          var oh = '';
          onlineList.forEach(function(e) {
            var t = e.created_at ? new Date(e.created_at).toLocaleTimeString() : '';
            oh += '<div class="session-chip">';
            oh += '<span class="online-dot"></span>';
            oh += '<strong>' + esc(e.username) + '</strong>';
            oh += '<span style="color:var(--text-muted);font-size:0.72rem;">' + t + '</span>';
            oh += '<span style="color:var(--text-muted);font-size:0.72rem;">(' + esc(e.ip_address || '\u2014') + ')</span>';
            oh += '<button class="btn btn-sm btn-outline" style="font-size:0.66rem;padding:0.1rem 0.45rem;color:var(--accent-red);border-color:var(--accent-red);" onclick="adminForceLogoff(' + e.user_id + ', decodeURIComponent(\'' + encodeURIComponent(e.username || '') + '\'))">' + __('Force logoff') + '</button>';
            oh += '</div>';
          });
          onlineEl.innerHTML = oh;
        } else {
          onlineEl.innerHTML = '<div style="font-size:0.82rem;color:var(--text-muted);padding:0.5rem 0;">No active sessions</div>';
        }
      }
      if (events.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:1.5rem;color:var(--text-muted);">No session events recorded yet</td></tr>';
        return;
      }
      var rows = '';
      events.forEach(function(e) {
        var time = e.created_at ? new Date(e.created_at).toLocaleString() : '\u2014';
        var evBadge = '';
        if (e.event === 'login') {
          evBadge = '<span style="background:var(--severity-success-bg);color:var(--accent-green);padding:1px 8px;border-radius:8px;font-size:0.72rem;font-weight:600;">LOGIN</span>';
        } else if (e.event === 'logout') {
          evBadge = '<span style="background:var(--severity-warning-bg);color:var(--accent-orange);padding:1px 8px;border-radius:8px;font-size:0.72rem;font-weight:600;">LOGOUT</span>';
        } else if (e.event === 'refresh') {
          evBadge = '<span style="background:var(--severity-info-bg);color:var(--accent-blue);padding:1px 8px;border-radius:8px;font-size:0.72rem;font-weight:600;">REFRESH</span>';
        } else if (e.event === 'failed_login') {
          evBadge = '<span style="background:var(--severity-critical-bg);color:var(--accent-red);padding:1px 8px;border-radius:8px;font-size:0.72rem;font-weight:600;">FAILED</span>';
        } else if (e.event === 'inactive_account') {
          evBadge = '<span style="background:var(--severity-critical-bg);color:var(--accent-red);padding:1px 8px;border-radius:8px;font-size:0.72rem;font-weight:600;">INACTIVE</span>';
        } else {
          evBadge = '<span style="background:var(--bg-elevated);color:var(--text-muted);padding:1px 8px;border-radius:8px;font-size:0.72rem;">' + esc(e.event) + '</span>';
        }
        var isOnline = onlineIds.indexOf(e.user_id) >= 0;
        rows += '<tr style="border-bottom:1px solid var(--border-default);">';
        rows += '<td style="padding:0.35rem 0.5rem;font-size:0.78rem;">' + time + '</td>';
        rows += '<td style="padding:0.35rem 0.5rem;font-weight:600;">' + esc(e.username);
        if (isOnline) {
          rows += ' <span style="width:6px;height:6px;border-radius:50%;background:var(--accent-green);display:inline-block;" title="Online"></span>';
        }
        rows += '</td>';
        rows += '<td style="padding:0.35rem 0.5rem;">' + evBadge + '</td>';
        rows += '<td style="padding:0.35rem 0.5rem;font-size:0.75rem;color:var(--text-secondary);">' + esc(e.ip_address || '\u2014') + '</td>';
        rows += '<td style="padding:0.35rem 0.5rem;font-size:0.72rem;color:var(--text-muted);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + esc(e.user_agent || '') + '">' + esc(e.user_agent || '\u2014') + '</td>';
        rows += '</tr>';
      });
      tbody.innerHTML = rows;
    } catch(err) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:1.5rem;color:var(--accent-red);">Error: ' + esc(err.message) + '</td></tr>';
    }
  };
  window.adminForceLogoff = async function(userId, username) {
    if (!await window.confirmDestructive({
      title: __('Force logoff'),
      message: __('Force logoff') + ' ' + (username || '') + '?',
      details: __('This will revoke all active sessions for this user.'),
      okLabel: __('Force logoff')
    })) return;
    try {
      var resp = await api('/auth/sessions/kick-user', { method: 'POST', body: JSON.stringify({ user_id: userId }) });
      if (resp && (resp.detail || resp._error)) { if (typeof toastError === 'function') toastError(resp.detail || __('Failed')); return; }
      if (typeof toastSuccess === 'function') toastSuccess(__('Logoff') + ' ' + (username || '') + ' — ' + resp.revoked + ' ' + __('session(s)') + ' ' + __('revoked'));
      loadSessions();
    } catch (err) { if (typeof toastError === 'function') toastError(__('Error') + ': ' + err.message); }
  };
  window.toggleSessionsAutoRefresh = function() {
    if (_sessionsInterval) { clearInterval(_sessionsInterval); _sessionsInterval = null; }
    if (document.getElementById('sessionsAutoRefresh') && document.getElementById('sessionsAutoRefresh').checked) {
      _sessionsInterval = setInterval(loadSessions, 10000);
    }
  };
})();
