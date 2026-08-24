// auth.js — login page, token management, auth guard, permissions.
(function() {
  var API_BASE = document.getElementById('apiBase') ? document.getElementById('apiBase').value : '';

  // ---- Auto-inject auth header into ALL fetch calls ----
  var _origFetch = window.fetch;
  var _refreshInProgress = null;

  function _isApiUrl(urlStr) {
    return urlStr.indexOf('/auth/login') === -1 && urlStr.indexOf('/auth/refresh') === -1
           && urlStr.indexOf('/static/') === -1;
  }

  function _getToken() {
    return typeof window.getAccessToken === 'function' ? window.getAccessToken() : localStorage.getItem('access_token');
  }
  function _getRefresh() {
    return typeof window.getRefreshToken === 'function' ? window.getRefreshToken() : localStorage.getItem('refresh_token');
  }

  function _doFetch(url, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    var urlStr = typeof url === 'string' ? url : (url.url || '');
    if (_isApiUrl(urlStr)) {
      var token = _getToken();
      if (!token) {
        return Promise.resolve(new Response(JSON.stringify({detail: 'Not authenticated'}), {
          status: 401, statusText: 'Unauthorized', headers: {'Content-Type': 'application/json'}
        }));
      }
      if (!opts.headers['Authorization']) {
        opts.headers['Authorization'] = 'Bearer ' + token;
      }
    }
    return _origFetch.call(window, url, opts);
  }

  function _refreshToken() {
    if (_refreshInProgress) return _refreshInProgress;
    _refreshInProgress = (async function() {
      var refresh = _getRefresh();
      if (!refresh) { _refreshInProgress = null; return false; }
      try {
        var resp = await _origFetch.call(window, API_BASE + '/auth/refresh', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refresh }),
        });
        if (resp.ok) {
          var data = await resp.json();
          if (typeof window.setTokens === 'function') {
            window.setTokens(data.access_token, data.refresh_token);
          } else {
            localStorage.setItem('access_token', data.access_token);
            localStorage.setItem('refresh_token', data.refresh_token);
          }
          _refreshInProgress = null;
          return true;
        }
      } catch(e) {}
      if (typeof window.clearTokens === 'function') {
        window.clearTokens();
      } else {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user_info');
      }
      _refreshInProgress = null;
      return false;
    })();
    return _refreshInProgress;
  }

  window.fetch = function(url, opts) {
    return _doFetch(url, opts).then(function(resp) {
      if (resp.status !== 401) return resp;
      var urlStr = typeof url === 'string' ? url : (url.url || '');
      if (!_isApiUrl(urlStr)) return resp;
      return _refreshToken().then(function(refreshed) {
        if (!refreshed) {
          // Session expired — force redirect to login (once)
          if (!window._authRedirecting) {
            window._authRedirecting = true;
            setTimeout(function() {
              window._authRedirecting = false;
              if (typeof window.clearTokens === 'function') window.clearTokens();
              if (typeof window.showLoginPage === 'function') window.showLoginPage();
              var err = document.getElementById('login-error');
              if (err) { err.textContent = 'Session expired. Please log in again.'; err.style.display = 'block'; }
            }, 0);
          }
          return resp;
        }
        // Update the Authorization header with the new token before retrying
        if (opts && opts.headers) {
          var newToken = _getToken();
          if (newToken) opts.headers['Authorization'] = 'Bearer ' + newToken;
        }
        return _doFetch(url, opts);
      });
    });
  };

  // ---- Token storage: localStorage (remember me) or sessionStorage (session only) ----
  function _storage() {
    // If remember_me flag is set, use localStorage; otherwise sessionStorage
    return localStorage.getItem('remember_me') === 'true' ? localStorage : sessionStorage;
  }

  window.getAccessToken = function() {
    // Check both storages for backward compatibility
    return _storage().getItem('access_token') || localStorage.getItem('access_token') || sessionStorage.getItem('access_token');
  };
  window.getRefreshToken = function() {
    return _storage().getItem('refresh_token') || localStorage.getItem('refresh_token') || sessionStorage.getItem('refresh_token');
  };

  window.setTokens = function(access, refresh) {
    _storage().setItem('access_token', access);
    _storage().setItem('refresh_token', refresh);
  };

  window.clearTokens = function() {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user_info');
    localStorage.removeItem('remember_me');
    sessionStorage.removeItem('access_token');
    sessionStorage.removeItem('refresh_token');
    sessionStorage.removeItem('user_info');
  };

  window.getUserInfo = function() {
    try { return JSON.parse(localStorage.getItem('user_info')); } catch(e) { return null; }
  };

  window.setUserInfo = function(info) {
    localStorage.setItem('user_info', JSON.stringify(info));
  };

  window.hasPermission = function(perm) {
    var user = getUserInfo();
    if (!user) return false;
    if (user.permissions && user.permissions.indexOf('*.*') !== -1) return true;
    return user.permissions && user.permissions.indexOf(perm) !== -1;
  };

  // ---- Auth fetch wrapper ----
  window.authFetch = async function(url, options) {
    options = options || {};
    options.headers = options.headers || {};
    var token = getAccessToken();
    if (token) options.headers['Authorization'] = 'Bearer ' + token;
    var resp = await fetch(url, options);
    if (resp.status === 401) {
      var refreshed = await tryRefresh();
      if (refreshed) {
        options.headers['Authorization'] = 'Bearer ' + getAccessToken();
        resp = await fetch(url, options);
      } else {
        showLoginPage();
        throw new Error('Session expired');
      }
    }
    return resp;
  };

  async function tryRefresh() {
    var refresh = getRefreshToken();
    if (!refresh) return false;
    try {
      var resp = await fetch(API_BASE + '/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (resp.ok) {
        var data = await resp.json();
        setTokens(data.access_token, data.refresh_token);
        return true;
      }
    } catch(e) {}
    clearTokens();
    return false;
  }

  // ---- Login page ----
  window.showLoginPage = function() {
    var lp = document.getElementById('login-page');
    if (lp) lp.style.display = 'flex';
    var dc = document.querySelector('.dashboard-container') || document.querySelector('.header');
    if (dc) dc.style.display = 'none';
    var cc = document.querySelector('.container');
    if (cc) cc.style.display = 'none';
  };

  window.hideLoginPage = function() {
    var lp = document.getElementById('login-page');
    if (lp) lp.style.display = 'none';
    var dc = document.querySelector('.dashboard-container') || document.querySelector('.header');
    if (dc) dc.style.display = '';
    var cc = document.querySelector('.container');
    if (cc) cc.style.display = '';
  };

  window.handleLogin = async function(e) {
    e.preventDefault();
    var username = document.getElementById('login-username').value;
    var password = document.getElementById('login-password').value;
    var errorEl = document.getElementById('login-error');
    var submitBtn = document.getElementById('login-submit');
    errorEl.style.display = 'none';
    submitBtn.disabled = true;
    submitBtn.textContent = '...';
    try {
      var rememberMe = document.getElementById('remember-me') && document.getElementById('remember-me').checked;
      // Store remember_me preference BEFORE login
      localStorage.setItem('remember_me', rememberMe ? 'true' : 'false');
      var resp = await fetch(API_BASE + '/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username, password: password, remember_me: rememberMe }),
      });
      var data;
      try { data = await resp.json(); } catch(parseErr) {
        errorEl.textContent = 'Server error (' + resp.status + '). Please try again.';
        errorEl.style.display = 'block';
        return false;
      }
      if (!resp.ok) {
        errorEl.textContent = data.detail || 'Login failed';
        errorEl.style.display = 'block';
        return false;
      }
      setTokens(data.access_token, data.refresh_token);
      setUserInfo(data.user);
      hideLoginPage();
      applyPermissions();
      _startInactivityTimer();
      // Re-run full bootstrap (same as app.js DOMContentLoaded)
      if (typeof window.refreshSavedFiles === 'function') window.refreshSavedFiles();
      fetch(API_BASE + '/reports/').then(function(r) { return r.json(); }).then(function(reports) {
        if (reports && reports.length > 0) {
          var el = document.getElementById('resultsSection');
          if (el) el.classList.remove('hidden');
        }
      }).catch(function() {});
      // Always start at dashboard after login
      localStorage.removeItem('lastTab');
      if (typeof window.switchTab === 'function') {
        window.switchTab('dashboard');
      } else if (typeof window.initDashboard === 'function') {
        window.initDashboard();
      }
    } catch (err) {
      errorEl.textContent = 'Network error';
      errorEl.style.display = 'block';
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = document.documentElement.dir === 'rtl' ? 'تسجيل الدخول' : 'Login';
    }
    return false;
  };

  window.handleLogout = async function() {
    var refresh = getRefreshToken();
    if (refresh) {
      try {
        await fetch(API_BASE + '/auth/logout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refresh }),
        });
      } catch(e) {}
    }
    clearTokens();
    // Reset user info display
    var userInfoEl = document.getElementById('user-info');
    if (userInfoEl) { userInfoEl.textContent = ''; userInfoEl.style.color = ''; }
    showLoginPage();
  };

  // ---- Session timeout / inactivity tracking ----
  var _INACTIVITY_TIMEOUT_MS = 8 * 60 * 60 * 1000;  // 8 hours
  var _WARNING_BEFORE_MS = 15 * 60 * 1000;       // warn 15 minutes before timeout
  var _inactivityTimer = null;
  var _warningTimer = null;
  var _lastActivity = Date.now();

  function _resetInactivityTimer() {
    _lastActivity = Date.now();
    if (_inactivityTimer) clearTimeout(_inactivityTimer);
    if (_warningTimer) clearTimeout(_warningTimer);
    _hideSessionWarning();
    _inactivityTimer = setTimeout(_onInactivityTimeout, _INACTIVITY_TIMEOUT_MS);
    _warningTimer = setTimeout(_showSessionWarning, _INACTIVITY_TIMEOUT_MS - _WARNING_BEFORE_MS);
  }

  function _onInactivityTimeout() {
    clearTokens();
    showLoginPage();
    var err = document.getElementById('login-error');
    if (err) {
      err.textContent = 'Session expired due to inactivity. Please log in again.';
      err.style.display = 'block';
    }
  }

  function _showSessionWarning() {
    var remaining = Math.ceil((_INACTIVITY_TIMEOUT_MS - _WARNING_BEFORE_MS) / 60000);
    var existing = document.getElementById('session-warning');
    if (existing) existing.remove();
    var div = document.createElement('div');
    div.id = 'session-warning';
    div.style.cssText = 'position:fixed;top:1rem;right:1rem;background:#fff3cd;border:1px solid #ffc107;border-radius:10px;padding:1rem 1.2rem;box-shadow:0 4px 16px rgba(0,0,0,0.15);z-index:99999;max-width:380px;font-size:0.85rem;';
    div.innerHTML = '<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem;"><span style="font-size:1.2rem;">⏰</span><strong style="color:#856404;">Session Expiring</strong></div>' +
      '<p style="margin:0 0 0.5rem;color:#856404;">Your session will expire in <strong>' + remaining + ' minutes</strong> due to inactivity.</p>' +
      '<button onclick="window._extendSession()" style="background:#856404;color:white;border:none;border-radius:6px;padding:0.35rem 1rem;font-size:0.82rem;cursor:pointer;font-weight:600;">Keep me signed in</button>';
    document.body.appendChild(div);
  }

  function _hideSessionWarning() {
    var w = document.getElementById('session-warning');
    if (w) w.remove();
  }

  window._extendSession = function() {
    _hideSessionWarning();
    _resetInactivityTimer();
    // Also try to refresh the token silently
    tryRefresh();
  };

  window._startInactivityTimer = function() {
    _resetInactivityTimer();
    // Track user activity to reset timer
    ['mousemove', 'keydown', 'click', 'scroll', 'touchstart'].forEach(function(evt) {
      document.addEventListener(evt, _resetInactivityTimer, { passive: true });
    });
  };

  window.toggleLoginLang = function() {
    var html = document.documentElement;
    var btn = document.getElementById('login-lang-toggle');
    if (html.dir === 'rtl') {
      html.dir = 'ltr'; html.lang = 'en';
      btn.textContent = '\u{1F1F3}\u{1F1DD} \u0639\u0631\u0628\u064A';
    } else {
      html.dir = 'rtl'; html.lang = 'ar';
      btn.textContent = '\u{1F1EC}\u{1F1E7} English';
    }
  };

  // ---- Permissions ----
  // Full map of tab-content IDs to required permissions.
  // The Admin tab uses data-requires on the <div class="tab"> element,
  // but we also include it here for the reset-all logic.
  var _TAB_PERMISSIONS = {
    'tab-dashboard': 'dashboard.read',
    'tab-analysis': 'analysis.read',
    'tab-quality': 'quality.read',
    'tab-outliers': 'outliers.read',
    'tab-clinical': 'clinical.read',
    'tab-alerts': 'alerts.read',
    'tab-hospitals': 'hospitals.read',
    'tab-smart-analytics': 'smart_analytics.read',
    'tab-rules': 'rules.read',
    'tab-root-cause': 'root_cause.read',
    'tab-audit': 'audit.read',
    'tab-settings': 'settings.read',
    'tab-admin': 'system.manage_users',
  };

  /** Show all tab-content panels (reset before applying per-user rules). */
  function _showAllTabs() {
    document.querySelectorAll('.tab-content').forEach(function(el) {
      el.style.display = '';
    });
    document.querySelectorAll('.tab[data-tab]').forEach(function(el) {
      el.style.display = '';
    });
  }

  /** Build a role/permission badge string for the header. */
  function _roleBadge(user) {
    if (!user) return '';
    var roles = user.roles || [];
    var isSuper = user.is_superuser || (user.permissions && user.permissions.indexOf('*.*') !== -1);
    if (isSuper) return ' [Superadmin]';
    if (roles.indexOf('admin') !== -1) return ' [Admin]';
    if (roles.indexOf('doctor') !== -1) return ' [Doctor]';
    if (roles.length > 0) return ' [' + roles[0].charAt(0).toUpperCase() + roles[0].slice(1) + ']';
    return '';
  }

  window.applyPermissions = function() {
    var user = getUserInfo();
    if (!user) return;

    // 1) Reset — make every tab visible before applying restrictions.
    //    This prevents stale visibility when switching users.
    _showAllTabs();

    // 2) Tab-content panels: hide if user lacks required permission.
    Object.keys(_TAB_PERMISSIONS).forEach(function(tabId) {
      var el = document.getElementById(tabId);
      if (el && !hasPermission(_TAB_PERMISSIONS[tabId])) el.style.display = 'none';
    });

    // 3) data-requires on any element (covers the Admin tab <div class="tab">,
    //    plus any future elements that need permission gating).
    document.querySelectorAll('[data-requires]').forEach(function(el) {
      if (!hasPermission(el.dataset.requires)) el.style.display = 'none';
    });

    // 4) Header: show logout button, user name + role badge.
    var logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) logoutBtn.style.display = '';
    var userInfoEl = document.getElementById('user-info');
    if (userInfoEl && user) {
      var displayName = user.full_name || user.username;
      var badge = _roleBadge(user);
      userInfoEl.textContent = displayName + badge;
      // Color the badge
      if (badge) {
        var isSuper = user.is_superuser || (user.permissions && user.permissions.indexOf('*.*') !== -1);
        userInfoEl.style.color = isSuper ? 'var(--accent-purple)' : 'var(--accent-blue)';
      }
    }
  };

  // ---- Auth guard (run on page load) ----
  window.checkAuth = async function() {
    var token = getAccessToken();
    if (!token) { showLoginPage(); return false; }
    try {
      var resp = await fetch(API_BASE + '/auth/me', {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      if (resp.ok) {
        var user;
        try { user = await resp.json(); } catch(e) { showLoginPage(); return false; }
        setUserInfo(user);
        hideLoginPage();
        applyPermissions();
        _startInactivityTimer();
        return true;
      }
    } catch(e) {
      // Network error or server down — try refresh once, then show login
    }
    var refreshed = await tryRefresh();
    if (refreshed) {
      try {
        var meResp = await fetch(API_BASE + '/auth/me', {
          headers: { 'Authorization': 'Bearer ' + getAccessToken() },
        });
        if (meResp.ok) {
          var u; try { u = await meResp.json(); } catch(e) { showLoginPage(); return false; }
          setUserInfo(u);
          hideLoginPage();
          applyPermissions();
          _startInactivityTimer();
          return true;
        }
      } catch(e) {}
    }
    clearTokens();
    showLoginPage();
    return false;
  };
})();
