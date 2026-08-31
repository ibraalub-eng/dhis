// auth.js — login page, token management, auth guard, permissions.
(function() {
  var API_BASE = '';

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
    // Always hide any active loader overlay
    var lo = document.getElementById('loaderOverlay');
    if (lo) lo.classList.remove('active');
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
      // Show the main app content (tabs, dashboard, etc.)
      var rs = document.getElementById('resultsSection');
      if (rs) rs.classList.remove('hidden');
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

  // ---- Session timeout / inactivity tracking + JWT token expiry ----
  var _INACTIVITY_TIMEOUT_MS = 8 * 60 * 60 * 1000;  // 8 hours
  var _WARNING_BEFORE_MS = 15 * 60 * 1000;       // warn 15 minutes before timeout
  var _TOKEN_WARN_SECONDS = 300;                   // warn 5 minutes before JWT expiry
  var _inactivityTimer = null;
  var _warningTimer = null;
  var _tokenExpiryTimer = null;
  var _tokenCountdownInterval = null;
  var _lastActivity = Date.now();
  var _tokenExpiresAt = 0; // epoch seconds when access token expires

  /** Parse JWT payload without verifying -- read only exp claim. */
  function _parseJwtExp(token) {
    try {
      var parts = token.split('.');
      if (parts.length !== 3) return 0;
      var payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
      return payload.exp || 0;
    } catch(e) { return 0; }
  }

  /** Start or restart the token-expiry countdown. */
  function _startTokenExpiryWatch() {
    if (_tokenExpiryTimer) clearTimeout(_tokenExpiryTimer);
    if (_tokenCountdownInterval) clearInterval(_tokenCountdownInterval);
    _tokenCountdownInterval = null;

    var token = _getToken();
    if (!token) return;
    var exp = _parseJwtExp(token);
    if (!exp) return;
    _tokenExpiresAt = exp;
    var nowSec = Math.floor(Date.now() / 1000);
    var secondsLeft = exp - nowSec;
    if (secondsLeft <= 0) return;
    var warnAt = Math.max(0, secondsLeft - _TOKEN_WARN_SECONDS);
    _tokenExpiryTimer = setTimeout(_onTokenExpiryWarning, warnAt * 1000);
  }

  function _onTokenExpiryWarning() {
    _showTokenExpiryPopup();
    _tokenCountdownInterval = setInterval(_updateTokenCountdown, 1000);
  }

  function _showTokenExpiryPopup() {
    var existing = document.getElementById('session-warning');
    if (existing) existing.remove();
    var secondsLeft = Math.max(0, _tokenExpiresAt - Math.floor(Date.now() / 1000));
    var mins = Math.floor(secondsLeft / 60);
    var secs = secondsLeft % 60;
    var timeStr = mins > 0 ? mins + 'm ' + secs + 's' : secs + 's';
    var urgent = secondsLeft < 120;
    var bgColor = urgent ? 'var(--severity-critical-bg)' : 'var(--severity-warning-bg)';
    var borderColor = urgent ? 'var(--accent-red)' : 'var(--accent-yellow)';
    var titleColor = urgent ? 'var(--accent-red)' : 'var(--accent-yellow)';
    var icon = urgent ? '\u26a0\ufe0f' : '\u23f0';

    var div = document.createElement('div');
    div.id = 'session-warning';
    div.style.cssText = 'position:fixed;top:1rem;right:1rem;background:' + bgColor + ';border:1px solid ' + borderColor + ';border-radius:10px;padding:1rem 1.2rem;box-shadow:var(--shadow-md);z-index:99999;max-width:380px;font-size:0.85rem;transition:all 0.3s;';
    div.innerHTML = '<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem;">' +
      '<span style="font-size:1.2rem;">' + icon + '</span>' +
      '<strong style="color:' + titleColor + ';">Session Expiring</strong></div>' +
      '<p style="margin:0 0 0.3rem;color:var(--text-primary);">Your session expires in:</p>' +
      '<div id="sw-countdown" style="font-size:1.6rem;font-weight:700;color:' + titleColor + ';margin-bottom:0.5rem;font-variant-numeric:tabular-nums;">' + timeStr + '</div>' +
      '<div style="display:flex;gap:0.5rem;flex-wrap:wrap;">' +
      '<button onclick="window._extendSession()" style="background:' + borderColor + ';color:' + (urgent ? '#fff' : 'var(--bg-base)') + ';border:none;border-radius:6px;padding:0.4rem 1rem;font-size:0.82rem;cursor:pointer;font-weight:600;">Extend Session</button>' +
      '<button onclick="window._logoutFromWarning()" style="background:transparent;color:var(--text-muted);border:1px solid var(--border-default);border-radius:6px;padding:0.4rem 1rem;font-size:0.82rem;cursor:pointer;">Logout</button>' +
      '</div>';
    document.body.appendChild(div);
  }

  function _updateTokenCountdown() {
    var el = document.getElementById('sw-countdown');
    if (!el) { clearInterval(_tokenCountdownInterval); _tokenCountdownInterval = null; return; }
    var secondsLeft = Math.max(0, _tokenExpiresAt - Math.floor(Date.now() / 1000));
    var mins = Math.floor(secondsLeft / 60);
    var secs = secondsLeft % 60;
    el.textContent = mins > 0 ? mins + 'm ' + secs + 's' : secs + 's';
    if (secondsLeft < 120) {
      el.style.color = 'var(--accent-red)';
      var wrapper = document.getElementById('session-warning');
      if (wrapper) {
        wrapper.style.background = 'var(--severity-critical-bg)';
        wrapper.style.borderColor = 'var(--accent-red)';
      }
    }
    if (secondsLeft <= 0) {
      clearInterval(_tokenCountdownInterval);
      _tokenCountdownInterval = null;
      _hideSessionWarning();
    }
  }

  function _resetInactivityTimer() {
    _lastActivity = Date.now();
    if (_inactivityTimer) clearTimeout(_inactivityTimer);
    if (_warningTimer) clearTimeout(_warningTimer);
    _inactivityTimer = setTimeout(_onInactivityTimeout, _INACTIVITY_TIMEOUT_MS);
    _warningTimer = setTimeout(_showInactivityWarning, _INACTIVITY_TIMEOUT_MS - _WARNING_BEFORE_MS);
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

  function _showInactivityWarning() {
    var existing = document.getElementById('session-warning');
    if (existing) return; // token expiry popup takes priority
    var remaining = Math.ceil((_INACTIVITY_TIMEOUT_MS - _WARNING_BEFORE_MS) / 60000);
    var div = document.createElement('div');
    div.id = 'session-warning';
    div.style.cssText = 'position:fixed;top:1rem;right:1rem;background:var(--severity-warning-bg);border:1px solid var(--accent-yellow);border-radius:10px;padding:1rem 1.2rem;box-shadow:var(--shadow-md);z-index:99999;max-width:380px;font-size:0.85rem;';
    div.innerHTML = '<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem;"><span style="font-size:1.2rem;">\u23f0</span><strong style="color:var(--accent-yellow);">Session Expiring</strong></div>' +
      '<p style="margin:0 0 0.5rem;color:var(--text-primary);">Your session will expire in <strong>' + remaining + ' minutes</strong> due to inactivity.</p>' +
      '<button onclick="window._extendSession()" style="background:var(--accent-yellow);color:var(--bg-base);border:none;border-radius:6px;padding:0.35rem 1rem;font-size:0.82rem;cursor:pointer;font-weight:600;">Keep me signed in</button>';
    document.body.appendChild(div);
  }

  function _hideSessionWarning() {
    var w = document.getElementById('session-warning');
    if (w) w.remove();
    if (_tokenCountdownInterval) { clearInterval(_tokenCountdownInterval); _tokenCountdownInterval = null; }
  }

  window._extendSession = function() {
    _hideSessionWarning();
    _resetInactivityTimer();
    tryRefresh().then(function(success) {
      if (success) {
        _startTokenExpiryWatch();
        var t = document.createElement('div');
        t.style.cssText = 'position:fixed;bottom:1rem;right:1rem;background:var(--severity-success-bg);border:1px solid var(--accent-green);border-radius:8px;padding:0.5rem 1rem;font-size:0.82rem;color:var(--accent-green);z-index:99999;font-weight:600;';
        t.textContent = '\u2713 Session extended';
        document.body.appendChild(t);
        setTimeout(function() { t.remove(); }, 2000);
      }
    });
  };

  window._logoutFromWarning = function() {
    _hideSessionWarning();
    if (typeof window.handleLogout === 'function') window.handleLogout();
  };

  window._startInactivityTimer = function() {
    _resetInactivityTimer();
    _startTokenExpiryWatch();
    ['mousemove', 'keydown', 'click', 'scroll', 'touchstart'].forEach(function(evt) {
      document.addEventListener(evt, _resetInactivityTimer, { passive: true });
    });
  };

  // Re-start token expiry watch whenever tokens are refreshed
  var _origSetTokens = window.setTokens;
  window.setTokens = function(access, refresh) {
    _origSetTokens(access, refresh);
    _hideSessionWarning();
    _startTokenExpiryWatch();
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
    'tab-settings': 'system.manage_users',
    // tab-admin uses data-requires-superadmin instead of permission check
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
    // 3b) data-requires-superadmin: only visible to superadmin users
    document.querySelectorAll('[data-requires-superadmin]').forEach(function(el) {
      if (!user.is_superuser) el.style.display = 'none';
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
      // Let the global fetch interceptor handle 401 → refresh → retry
      var resp = await fetch(API_BASE + '/auth/me');
      if (resp.ok) {
        var user;
        try { user = await resp.json(); } catch(e) { showLoginPage(); return false; }
        setUserInfo(user);
        hideLoginPage();
        applyPermissions();
        _startInactivityTimer();
        var rs = document.getElementById('resultsSection');
        if (rs) rs.classList.remove('hidden');
        return true;
      }
      // 401 that the interceptor couldn't fix (refresh token expired)
      clearTokens();
      showLoginPage();
      return false;
    } catch(e) {
      // Network error or server down
      clearTokens();
      showLoginPage();
      return false;
    }
  };
})();

// ── Profile Modal ──────────────────────────────────────────
window.openProfileModal = function() {
    var modal = document.getElementById('profileModal');
    if (!modal) return;
    modal.style.display = 'flex';
    // Focus first editable field
    setTimeout(function() { var el = document.getElementById('pm-fullname'); if (el) el.focus(); }, 100);
    // Click outside to close
    modal.onclick = function(e) { if (e.target === modal) window.closeProfileModal(); };
    // Load current user data
    var user = window.getUserInfo ? window.getUserInfo() : null;
    if (!user) {
        // Fetch from API (global interceptor adds auth header)
        fetch(API_BASE + '/auth/me')
            .then(function(r) { if (!r.ok) throw new Error(); return r.json(); })
            .then(function(data) { _fillProfileModal(data); })
            .catch(function() {});
    } else {
        _fillProfileModal(user);
    }
    // Clear previous messages
    var els = ['pm-profileError','pm-profileSuccess','pm-pwError','pm-pwSuccess'];
    els.forEach(function(id) { var el = document.getElementById(id); if (el) el.style.display = 'none'; });
    // Clear password fields
    ['pm-pw-current','pm-pw-new','pm-pw-confirm'].forEach(function(id) { var el = document.getElementById(id); if (el) el.value = ''; });
};

window.closeProfileModal = function() {
    var modal = document.getElementById('profileModal');
    if (modal) modal.style.display = 'none';
    // Reset to profile tab
    _pmSwitchTab('profile');
};

window._pmSwitchTab = function(tab) {
    var profileTab = document.getElementById('pmTabProfile');
    var passwordTab = document.getElementById('pmTabPassword');
    var profileContent = document.getElementById('pmTabContentProfile');
    var passwordContent = document.getElementById('pmTabContentPassword');
    if (tab === 'profile') {
        if (profileTab) { profileTab.style.color = 'var(--accent-blue)'; profileTab.style.borderBottomColor = 'var(--accent-blue)'; }
        if (passwordTab) { passwordTab.style.color = 'var(--text-muted)'; passwordTab.style.borderBottomColor = 'transparent'; }
        if (profileContent) profileContent.style.display = '';
        if (passwordContent) passwordContent.style.display = 'none';
    } else {
        if (profileTab) { profileTab.style.color = 'var(--text-muted)'; profileTab.style.borderBottomColor = 'transparent'; }
        if (passwordTab) { passwordTab.style.color = 'var(--accent-blue)'; passwordTab.style.borderBottomColor = 'var(--accent-blue)'; }
        if (profileContent) profileContent.style.display = 'none';
        if (passwordContent) passwordContent.style.display = '';
    }
};
// Close modal on Escape key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        var modal = document.getElementById('profileModal');
        if (modal && modal.style.display === 'flex') window.closeProfileModal();
    }
});

function _fillProfileModal(data) {
    var un = document.getElementById('pm-username');
    var fn = document.getElementById('pm-fullname');
    var em = document.getElementById('pm-email');
    if (un) un.value = data.username || '';
    if (fn) fn.value = data.full_name || '';
    if (em) em.value = data.email || '';
}

window._pmSaveProfile = function() {
    var fnEl = document.getElementById('pm-fullname');
    var emEl = document.getElementById('pm-email');
    var errEl = document.getElementById('pm-profileError');
    var okEl = document.getElementById('pm-profileSuccess');
    errEl.style.display = 'none';
    okEl.style.display = 'none';
    var fullName = fnEl ? fnEl.value.trim() : '';
    var email = emEl ? emEl.value.trim() : '';
    if (!fullName) { errEl.textContent = 'Full name is required'; errEl.style.display = 'block'; return; }
    if (!email) { errEl.textContent = 'Email is required'; errEl.style.display = 'block'; return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { errEl.textContent = 'Invalid email format'; errEl.style.display = 'block'; return; }
    fetch(API_BASE + '/auth/me', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ full_name: fullName, email: email })
    }).then(function(r) { return r.json(); }).then(function(data) {
        if (data.detail) { errEl.textContent = data.detail; errEl.style.display = 'block'; return; }
        okEl.textContent = '\u2713 Profile updated!';
        okEl.style.display = 'block';
        // Update header display
        var userInfoEl = document.getElementById('user-info');
        if (userInfoEl && data.full_name) {
            var badge = '';
            try {
                var u = window.getUserInfo ? window.getUserInfo() : null;
                if (u && u.roles) badge = ' [' + u.roles[0] + ']';
            } catch(e) {}
            userInfoEl.textContent = data.full_name + badge;
        }
        // Update stored user info
        if (window.setUserInfo) {
            var stored = window.getUserInfo ? window.getUserInfo() : {};
            if (stored) { stored.full_name = data.full_name; stored.email = data.email; window.setUserInfo(stored); }
        }
    }).catch(function() {
        errEl.textContent = 'Network error';
        errEl.style.display = 'block';
    });
};

window._pmChangePw = function() {
    var curEl = document.getElementById('pm-pw-current');
    var newEl = document.getElementById('pm-pw-new');
    var cfEl  = document.getElementById('pm-pw-confirm');
    var errEl = document.getElementById('pm-pwError');
    var okEl  = document.getElementById('pm-pwSuccess');
    errEl.style.display = 'none';
    okEl.style.display = 'none';
    var cur = curEl ? curEl.value : '';
    var nw  = newEl ? newEl.value : '';
    var cf  = cfEl  ? cfEl.value  : '';
    if (!cur) { errEl.textContent = 'Current password is required'; errEl.style.display = 'block'; return; }
    if (!nw)  { errEl.textContent = 'New password is required'; errEl.style.display = 'block'; return; }
    if (nw.length < 6) { errEl.textContent = 'Password must be at least 6 characters'; errEl.style.display = 'block'; return; }
    if (nw === cur) { errEl.textContent = 'New password must be different from current'; errEl.style.display = 'block'; return; }
    if (nw !== cf) { errEl.textContent = 'Passwords do not match'; errEl.style.display = 'block'; return; }
    fetch(API_BASE + '/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: cur, new_password: nw, confirm_password: cf })
    }).then(function(r) { return r.json(); }).then(function(data) {
        if (!data.success) { errEl.textContent = data.detail || 'Failed'; errEl.style.display = 'block'; return; }
        okEl.textContent = '\u2713 Password changed successfully!';
        okEl.style.display = 'block';
        curEl.value = '';
        newEl.value = '';
        cfEl.value = '';
    }).catch(function() {
        errEl.textContent = 'Network error';
        errEl.style.display = 'block';
    });
};
