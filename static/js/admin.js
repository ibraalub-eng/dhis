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
        <!-- Admin Tab Bar -->
        <div style="display:flex;gap:0;border-bottom:2px solid var(--border-default);margin-bottom:1rem;">
          <button class="admin-tab-btn active" onclick="switchAdminTab('users')" id="atab-users" style="padding:0.5rem 1.2rem;border:none;background:var(--accent-purple);color:white;border-radius:6px 6px 0 0;font-size:0.85rem;font-weight:600;cursor:pointer;margin-bottom:-2px;">👥 Users &amp; Roles</button>
          <button class="admin-tab-btn" onclick="switchAdminTab('database')" id="atab-database" style="padding:0.5rem 1.2rem;border:none;background:var(--bg-surface-hover);color:var(--text-secondary);border-radius:6px 6px 0 0;font-size:0.85rem;cursor:pointer;margin-bottom:-2px;">🗄️ Database</button>
          <button class="admin-tab-btn" onclick="switchAdminTab('tabs')" id="atab-tabs" style="padding:0.5rem 1.2rem;border:none;background:var(--bg-surface-hover);color:var(--text-secondary);border-radius:6px 6px 0 0;font-size:0.85rem;cursor:pointer;margin-bottom:-2px;">📋 Tab Order</button>
        </div>

        <!-- Users and Roles Tab -->
        <div id="adminUsersPanel">
        <h2 style="color:var(--accent-purple);margin-bottom:0.5rem;">User Management</h2>
        <p style="font-size:0.82rem;color:var(--text-secondary);margin-bottom:1rem;">Create, edit, and deactivate user accounts. Assign roles to control access.</p>

        <div style="display:flex;gap:1.5rem;flex-wrap:wrap;">
          <!-- Users -->
          <div style="flex:2;min-width:400px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
              <h3 style="color:var(--accent-blue);margin:0;">Users (${users.length})</h3>
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

          <!-- Roles -->
          <div style="flex:1;min-width:250px;">
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
                  ${roles.map(r => `
                    <tr style="border-bottom:1px solid var(--border-default);">
                      <td style="padding:0.4rem;font-weight:600;">${esc(r.name)}${r.is_system ? ' <span style="font-size:0.7rem;color:var(--text-muted);">(system)</span>' : ''}</td>
                      <td style="padding:0.4rem;">${r.user_count}</td>
                      <td style="padding:0.4rem;font-size:0.75rem;color:var(--text-secondary);">${r.permission_ids.length} perms</td>
                      <td style="padding:0.4rem;">
                        ${r.name === 'superadmin' ? '<span style="font-size:0.72rem;color:var(--text-muted);">System</span>' : '<button class="btn btn-sm btn-outline" onclick="editRole(${r.id})" style="font-size:0.72rem;">Edit</button>'}
                        ${!r.is_system ? '<button class="btn btn-sm btn-outline" onclick="deleteRole(' + r.id + ')" style="font-size:0.72rem;color:var(--accent-red);margin-left:0.2rem;">Delete</button>' : ''}
                      </td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>

            <h3 style="color:var(--accent-blue);margin:1rem 0 0.5rem;">Available Permissions (${perms.length})</h3>
            <div style="max-height:200px;overflow-y:auto;background:var(--bg-elevated);border-radius:6px;padding:0.5rem;font-size:0.78rem;">
              ${perms.map(p => '<div style="padding:0.15rem 0;"><strong style="color:var(--accent-purple);">' + esc(p.codename) + '</strong>' + (p.description ? ' <span style="color:var(--text-muted);">— ' + esc(p.description) + '</span>' : '') + '</div>').join('')}
            </div>
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
            <div id="adminModalError" style="display:none;color:var(--accent-red);font-size:0.82rem;margin-bottom:0.5rem;"></div>
            <div style="display:flex;gap:0.5rem;justify-content:flex-end;">
              <button class="btn btn-sm btn-outline" onclick="closeAdminModal()">Cancel</button>
              <button class="btn btn-sm" id="adminSaveBtn" onclick="saveAdminUser()">Save</button>
            </div>
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

        </div> <!-- /adminUsersPanel -->

        <!-- Database Tab -->
        <div id="adminDatabasePanel" style="display:none;">
          <div style="display:flex;gap:0;border-bottom:2px solid var(--border-default);margin-bottom:1rem;">
            <button class="admin-db-subtab active" onclick="switchAdminDbTab('overview')" id="dbsub-overview" style="padding:0.4rem 1rem;border:none;background:var(--accent-purple);color:white;border-radius:6px 6px 0 0;font-size:0.82rem;font-weight:600;cursor:pointer;margin-bottom:-2px;">📊 Database</button>
            <button class="admin-db-subtab" onclick="switchAdminDbTab('control')" id="dbsub-control" style="padding:0.4rem 1rem;border:none;background:var(--bg-surface-hover);color:var(--text-secondary);border-radius:6px 6px 0 0;font-size:0.82rem;cursor:pointer;margin-bottom:-2px;">🎛️ Control</button>
          </div>
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
          <div id="dbSubControl" style="display:none;">
            <h2 style="color:var(--accent-purple);margin-bottom:0.5rem;">Analysis Control</h2>
            <p style="font-size:0.82rem;color:var(--text-secondary);margin-bottom:1rem;">Configure analysis behavior, logging, and month toggles.</p>
            <div style="background:var(--bg-elevated);padding:1rem;border-radius:10px;max-width:700px;border:1px solid var(--border-default);">
              <div style="background:var(--bg-surface-hover);padding:0.8rem;border-radius:6px;margin-bottom:1rem;font-size:0.8rem;color:var(--text-primary);line-height:1.6;">
                  Controls how null/missing indicator values are handled during analysis and in the indicator tree.
              </div>
              <div style="background:var(--bg-surface-hover);padding:0.8rem;border-radius:6px;max-width:700px;">
                  <label style="display:flex;align-items:flex-start;gap:0.6rem;cursor:pointer;">
                      <input type="checkbox" id="cfg_auto_disable_null" onchange="adminSaveControlSettings()" style="margin-top:0.2rem;width:18px;height:18px;">
                      <div>
                          <strong>Auto-disable null indicators</strong><br>
                          <span style="font-size:0.8rem;color:var(--text-secondary);">When enabled, indicators with null values are treated as disabled.</span>
                      </div>
                  </label>
              </div>
              <div style="background:var(--bg-surface-hover);padding:0.8rem;border-radius:6px;max-width:700px;margin-top:0.8rem;">
                  <label style="display:flex;align-items:flex-start;gap:0.6rem;cursor:pointer;">
                      <input type="checkbox" id="cfg_structured_logging" onchange="adminSaveControlSettings()" style="margin-top:0.2rem;width:18px;height:18px;">
                      <div>
                          <strong>Structured Logging</strong><br>
                          <span style="font-size:0.8rem;color:var(--text-secondary);">Log all HTTP requests as JSON to stdout.</span>
                      </div>
                  </label>
                  <div style="margin-top:0.6rem;">
                      <span id="controlSaveStatus" style="font-size:0.8rem;color:var(--text-muted);"></span>
                  </div>
              </div>
              <div style="background:var(--bg-surface-hover);padding:0.8rem;border-radius:6px;max-width:700px;margin-top:0.8rem;">
                  <label style="display:flex;align-items:flex-start;gap:0.6rem;cursor:pointer;">
                      <input type="checkbox" id="cfg_slow_query_logging" onchange="adminSaveControlSettings()" style="margin-top:0.2rem;width:18px;height:18px;">
                      <div>
                          <strong>Slow Query Logging</strong><br>
                          <span style="font-size:0.8rem;color:var(--text-secondary);">Log SQL queries taking over 1 second.</span>
                      </div>
                  </label>
              </div>
              <div style="background:var(--bg-surface-hover);padding:0.8rem;border-radius:6px;max-width:700px;margin-top:0.8rem;">
                  <label style="display:flex;align-items:flex-start;gap:0.6rem;cursor:pointer;">
                      <input type="checkbox" id="cfg_hide_explanatory" onchange="adminSaveControlSettings()" style="margin-top:0.2rem;width:18px;height:18px;">
                      <div>
                          <strong>Hide Forecast/Explanation Sentences</strong><br>
                          <span style="font-size:0.8rem;color:var(--text-secondary);">When enabled, narrative forecast/explanation sentences are hidden from non-super-admin users (super admins always see them).</span>
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
        </div>
        <!-- Tab Order Panel -->
        <div id="adminTabOrderPanel" style="display:none;">
          <h2 style="color:var(--accent-purple);margin-bottom:0.5rem;">📋 Tab Order</h2>
          <p style="font-size:0.82rem;color:var(--text-secondary);margin-bottom:1rem;">Drag to reorder the main navigation tabs. Changes apply on next page load.</p>
          <div style="display:flex;gap:0.5rem;margin-bottom:1rem;">
            <button class="btn btn-sm btn-outline" onclick="resetTabOrder()">↺ Reset to Default</button>
            <button class="btn btn-sm" onclick="saveTabOrder()" style="background:var(--accent-green);color:white;">💾 Save Order</button>
          </div>
          <div id="tabOrderList"></div>
        </div>
      </div>
    `;
    // Reset flags since DOM was rebuilt
    window._adminDbLoaded = false;
    window._adminTabOrderLoaded = false;
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
  setTimeout(function() { if (document.getElementById('tabOrderList')) loadTabOrder(); }, 500);

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
    var body = {
      username: document.getElementById('adminUsername').value,
      full_name: document.getElementById('adminFullName').value,
      email: document.getElementById('adminEmail').value,
      role_ids: roleIds,
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
    if (!await confirmDestructive({ title: 'Delete Role', message: 'Delete this role? Users with this role will lose its permissions.', okLabel: 'Delete' })) return;
    var resp = await api('/admin/roles/' + roleId, { method: 'DELETE' });
    if (resp && resp.detail) { toastError(resp.detail); return; }
    loadAdminPanel();
  };

  window.deactivateUser = async function(userId) {
    if (!await confirmDestructive({ title: 'Deactivate User', message: 'Deactivate this user? They will not be able to log in.', okLabel: 'Deactivate' })) return;
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
    var t=document.getElementById("adminTabOrderPanel");
    if(u)u.style.display=tab==="users"?"block":"none";
    if(d)d.style.display=tab==="database"?"block":"none";
    if(t)t.style.display=tab==="tabs"?"block":"none";
    if(tab==="database"){loadAdminDbStatus();window._adminDbLoaded=true;}
    if(tab==="tabs"){window.loadTabOrder();window._adminTabOrderLoaded=true;}
  };

  window.switchAdminDbTab = function(sub) {
    document.querySelectorAll('.admin-db-subtab').forEach(function(btn){
      btn.style.background='var(--bg-surface-hover)';
      btn.style.color='var(--text-secondary)';
    });
    var ab=document.getElementById('dbsub-'+sub);
    if(ab){ab.style.background='var(--accent-purple)';ab.style.color='white';}
    var ov=document.getElementById('dbSubOverview');
    var ct=document.getElementById('dbSubControl');
    if(ov)ov.style.display=sub==='overview'?'block':'none';
    if(ct)ct.style.display=sub==='control'?'block':'none';
    if(sub==='control')loadAdminControlSettings();
  };

  function loadAdminControlSettings() {
    var hospitalSel=document.getElementById('monthHospitalSelect');
    if(hospitalSel&&hospitalSel.options.length<=1){
      api('/admin/hospitals').then(function(data){
        if(!data||data._error)return;
        var hosp=data.hospitals||[];
        hospitalSel.innerHTML='<option value="">-- Select Hospital --</option>';
        hosp.forEach(function(h){
          hospitalSel.innerHTML+='<option value="'+h.id+'">'+esc(h.name)+'</option>';
        });
      });
    }
    api('/config/settings').then(function(data){
      if(!data||data._error)return;
      var s=data.settings||data;
      var ids=['cfg_auto_disable_null','cfg_structured_logging','cfg_slow_query_logging','cfg_hide_explanatory'];
      ids.forEach(function(id){
        var el=document.getElementById(id);
        if(el)el.checked=!!s[id.replace('cfg_','')];
      });
    });
  }

  async function loadAdminDbStatus() {
    var el=document.getElementById("adminDbStatus");
    if(!el)return;el.innerHTML="Loading...";
    var data=await api("/config/database-status");
    if(!data||data._error){el.innerHTML="<span style=\"color:var(--accent-red)\">Failed to load</span>";return;}
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
    var tok=getAccessToken();var hdrs={"Authorization":"Bearer "+tok,"Content-Type":"application/json"};
    fetch(API_BASE+"/config/database/preview",{headers:hdrs}).then(function(r){if(!r.ok)throw new Error("HTTP "+r.status);return r.json();}).then(function(data){
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
    var tok=getAccessToken();var hdrs={"Authorization":"Bearer "+tok};
    fetch(API_BASE+"/config/database/export",{headers:hdrs}).then(function(r){if(!r.ok)throw new Error("HTTP "+r.status);var d=r.headers.get("Content-Disposition")||"";var m=d.match(/filename=\"?([^"]+)\"?/);return r.blob().then(function(b){return{blob:b,filename:m?m[1]:"export.json"};});}).then(function(r){
      var u=URL.createObjectURL(r.blob);var a=document.createElement("a");a.href=u;a.download=r.filename;document.body.appendChild(a);a.click();document.body.removeChild(a);URL.revokeObjectURL(u);if(s)s.textContent="Downloaded: "+r.filename;
    }).catch(function(e){if(s)s.textContent="Failed: "+e.message;}).finally(function(){if(btn)btn.disabled=false;});
  };

  // -- Control Settings Functions --
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
      }
    } catch(e) {}
    var enabled = localStorage.getItem("dev_hints_enabled") !== "false";
    window._showDevHints = enabled;
    var dhCb = document.getElementById("cfg_dev_hints");
    if (dhCb) dhCb.checked = enabled;
    adminLoadMonthToggles();
  }
  window.adminSaveControlSettings = function() {
    var cb = document.getElementById("cfg_auto_disable_null");
    var logCb = document.getElementById("cfg_structured_logging");
    var sqCb = document.getElementById("cfg_slow_query_logging");
    var hideCb = document.getElementById("cfg_hide_explanatory");
    var val = cb ? cb.checked : false;
    var logVal = logCb ? logCb.checked : true;
    var sqVal = sqCb ? sqCb.checked : true;
    var hideVal = hideCb ? hideCb.checked : false;
    var status = document.getElementById("controlSaveStatus");
    if (status) { status.textContent = "Saving..."; status.style.color = "var(--accent-blue)"; }
    api("/config/control/settings", {
      method: "PUT",
      body: JSON.stringify({
        auto_disable_null_indicators: val ? "true" : "false",
        structured_logging_enabled: logVal ? "true" : "false",
        slow_query_logging_enabled: sqVal ? "true" : "false",
        hide_explanatory_text: hideVal ? "true" : "false"
      })
    }).then(function() {
      if (status) { status.textContent = "✓ Saved"; status.style.color = "var(--accent-green)"; }
    }).catch(function(e) {
      if (status) { status.textContent = "✗ Error: " + e.message; status.style.color = "var(--accent-red)"; }
    });
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

  // Close button for DB preview
  var closeBtn=document.getElementById("adminDbCloseBtn");
  if(closeBtn)closeBtn.onclick=function(){document.getElementById("adminDbPreviewContainer").style.display="none";};

  // ── Tab Order Manager ──
  var DEFAULT_TAB_ORDER = [
    {id:'dashboard', label:'📊 Dashboard'},
    {id:'quality', label:'📋 Quality Reports'},
    {id:'analysis', label:'📈 Comparative Analysis'},
    {id:'clinical', label:'🏥 Clinical Intelligence'},
    {id:'outliers', label:'🔍 Outliers'},
    {id:'alerts', label:'🚨 Alerts'},
    {id:'indicator-tree', label:'🌲 Indicator Tree'},
    {id:'rules-manager', label:'⚙️ Rules Manager'},
    {id:'root-cause', label:'🎯 Root Cause'},
    {id:'audit', label:'📜 Audit'},
    {id:'admin', label:'👤 Admin'},
    {id:'settings', label:'⚙️ Settings'},
    {id:'smart-analytics', label:'🛡️ Smart Analytics'},
  ];

  window.loadTabOrder = function() {
    var el = document.getElementById('tabOrderList');
    if (!el) return;
    var saved = localStorage.getItem('tab_order');
    var order = saved ? JSON.parse(saved) : DEFAULT_TAB_ORDER.map(function(t) { return t.id; });
    // Build a map from DEFAULT_TAB_ORDER for labels
    var labelMap = {};
    DEFAULT_TAB_ORDER.forEach(function(t) { labelMap[t.id] = t.label; });
    var html = '';
    order.forEach(function(tabId, idx) {
      var label = labelMap[tabId] || tabId;
      html += '<div draggable="true" data-tab-id="' + tabId + '" data-idx="' + idx + '"' +
        ' style="display:flex;align-items:center;gap:0.5rem;padding:0.5rem 0.7rem;margin-bottom:0.3rem;' +
        'background:var(--bg-surface);border:1px solid var(--border-default);border-radius:6px;cursor:grab;' +
        'font-size:0.82rem;transition:border-color 0.15s;"' +
        ' ondragstart="_tabDragStart(event)" ondragover="_tabDragOver(event)" ondrop="_tabDrop(event)"' +
        ' ondragenter="this.style.borderColor=\'var(--accent-blue)\'" ondragleave="this.style.borderColor=\'var(--border-default)\'">' +
        '<span style="color:var(--text-muted);font-size:0.7rem;min-width:20px;">⠿</span>' +
        '<span style="flex:1;">' + label + '</span>' +
        '<span style="font-size:0.7rem;color:var(--text-muted);">#' + (idx + 1) + '</span>' +
        '</div>';
    });
    el.innerHTML = html;
  };

  var _dragTabId = null;
  window._tabDragStart = function(e) {
    _dragTabId = e.currentTarget.getAttribute('data-tab-id');
    e.currentTarget.style.opacity = '0.4';
    e.dataTransfer.effectAllowed = 'move';
  };
  window._tabDragOver = function(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  };
  window._tabDrop = function(e) {
    e.preventDefault();
    e.currentTarget.style.borderColor = 'var(--border-default)';
    var targetId = e.currentTarget.getAttribute('data-tab-id');
    if (_dragTabId === targetId) return;
    var saved = localStorage.getItem('tab_order');
    var order = saved ? JSON.parse(saved) : DEFAULT_TAB_ORDER.map(function(t) { return t.id; });
    var fromIdx = order.indexOf(_dragTabId);
    var toIdx = order.indexOf(targetId);
    if (fromIdx === -1 || toIdx === -1) return;
    order.splice(fromIdx, 1);
    order.splice(toIdx, 0, _dragTabId);
    localStorage.setItem('tab_order', JSON.stringify(order));
    loadTabOrder();
  };
  // Reset opacity on drag end
  document.addEventListener('dragend', function() {
    document.querySelectorAll('[draggable]').forEach(function(el) { el.style.opacity = '1'; });
  });

  window.saveTabOrder = function() {
    // Order is already saved in localStorage by drag-drop.
    // Now apply it to the live tab bar.
    applyTabOrder();
    toastSuccess('Tab order saved! Reloading page to apply...');
    setTimeout(function() { location.reload(); }, 1000);
  };

  window.resetTabOrder = function() {
    localStorage.removeItem('tab_order');
    loadTabOrder();
    toastWarning('Tab order reset to default. Save and reload to apply.');
  };

  function applyTabOrder() {
    var saved = localStorage.getItem('tab_order');
    if (!saved) return;
    var order = JSON.parse(saved);
    var tabBar = document.querySelector('.tab-bar');
    if (!tabBar) return;
    order.forEach(function(tabId) {
      var tab = tabBar.querySelector('.tab[data-tab="' + tabId + '"]');
      if (tab) tabBar.appendChild(tab);
    });
  }
  // Expose for main.js to call on load
  window._applyTabOrder = applyTabOrder;

  // Load tab order UI when admin panel loads
  if (document.getElementById('tabOrderList')) loadTabOrder();
})();
