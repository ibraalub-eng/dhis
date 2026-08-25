// admin.js — user management panel for superadmins.
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
          <p style="font-size:0.78rem;color:var(--text-muted);margin:0 0 0.8rem;">Shows which tabs each role can see. Green = visible, Red = hidden.</p>
          <div id="visMatrixBody"
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
        </div> style="overflow-x:auto;"><div style="text-align:center;padding:1rem;color:var(--text-muted);">Loading...</div></div>
        </div>

        <!-- Create/Edit User Modal -->
        <div id="adminUserModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:9999;align-items:center;justify-content:center;">
          <div style="background:white;border-radius:10px;padding:1.5rem;width:420px;max-width:94%;box-shadow:0 8px 32px rgba(0,0,0,0.2);">
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
          <div style="background:white;border-radius:10px;padding:1.5rem;width:480px;max-width:94%;max-height:80vh;overflow-y:auto;box-shadow:0 8px 32px rgba(0,0,0,0.2);">
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
      </div>
    `;
  } catch(e) {
    container.innerHTML = '<div style="padding:2rem;text-align:center;">' +
      '<h3 style="color:var(--accent-red);margin-bottom:0.5rem;">Error Loading Admin Panel</h3>' +
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
      var tabs = data.tabs || {};
      var roles = data.roles || [];
      var tabIds = Object.keys(tabs);
      if (tabIds.length === 0 || roles.length === 0) {
        el.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--text-muted);">No data</div>';
        return;
      }
      var html = '<table style="width:100%;border-collapse:collapse;font-size:0.78rem;">';
      // Header row
      html += '<thead><tr style="border-bottom:2px solid var(--border-default);">';
      html += '<th style="padding:0.4rem 0.6rem;text-align:left;position:sticky;left:0;background:var(--bg-elevated);z-index:1;min-width:140px;">Role</th>';
      tabIds.forEach(function(tid) {
        html += '<th style="padding:0.4rem;text-align:center;min-width:80px;white-space:nowrap;" title="' + esc(tabs[tid].permission) + '">' + esc(tabs[tid].label.split(' ').slice(1).join(' ')) + '</th>';
      });
      html += '<th style="padding:0.4rem;text-align:center;min-width:50px;">Count</th>';
      html += '</tr></thead><tbody>';
      // Role rows
      roles.forEach(function(r) {
        var visibleCount = 0;
        var isSuper = r.is_superuser;
        tabIds.forEach(function(tid) { if (r.tab_access[tid]) visibleCount++; });
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
    } catch(e) {
      el.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--accent-red);">Error: ' + esc(e.message) + '</div>';
    }
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
    if (resp && resp.detail) { alert(resp.detail); return; }
    loadAdminPanel();
  };

  window.deactivateUser = async function(userId) {
    if (!await confirmDestructive({ title: 'Deactivate User', message: 'Deactivate this user? They will not be able to log in.', okLabel: 'Deactivate' })) return;
    await api('/admin/users/' + userId, { method: 'DELETE' });
    loadAdminPanel();
  };
})();
