// auth.js — login page, token management, auth guard, permissions.
(function() {
  var API_BASE = document.getElementById('apiBase') ? document.getElementById('apiBase').value : '';

  // ---- Auto-inject auth header into ALL fetch calls ----
  var _origFetch = window.fetch;
  window.fetch = function(url, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    // Only add token for API calls (not static assets or login/refresh)
    var urlStr = typeof url === 'string' ? url : (url.url || '');
    var isApiCall = urlStr.indexOf('/auth/login') === -1 && urlStr.indexOf('/auth/refresh') === -1
                    && urlStr.indexOf('/static/') === -1;
    if (isApiCall) {
      var token = localStorage.getItem('access_token');
      if (!token) {
        // No token — return synthetic 401 without hitting the server
        return Promise.resolve(new Response(JSON.stringify({detail: 'Not authenticated'}), {
          status: 401, statusText: 'Unauthorized', headers: {'Content-Type': 'application/json'}
        }));
      }
      if (!opts.headers['Authorization']) {
        opts.headers['Authorization'] = 'Bearer ' + token;
      }
    }
    return _origFetch.call(window, url, opts);
  };

  // ---- Token management ----
  window.getAccessToken = function() { return localStorage.getItem('access_token'); };
  window.getRefreshToken = function() { return localStorage.getItem('refresh_token'); };

  window.setTokens = function(access, refresh) {
    localStorage.setItem('access_token', access);
    localStorage.setItem('refresh_token', refresh);
  };

  window.clearTokens = function() {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user_info');
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
      var resp = await fetch(API_BASE + '/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username, password: password }),
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
      // Re-run full bootstrap (same as app.js DOMContentLoaded)
      if (typeof window.refreshSavedFiles === 'function') window.refreshSavedFiles();
      fetch(API_BASE + '/reports/').then(function(r) { return r.json(); }).then(function(reports) {
        if (reports && reports.length > 0) {
          var el = document.getElementById('resultsSection');
          if (el) el.classList.remove('hidden');
        }
      }).catch(function() {});
      var savedTab = localStorage.getItem('lastTab');
      if (typeof window.switchTab === 'function') {
        if (savedTab && savedTab !== 'dashboard') {
          window.switchTab(savedTab);
        } else {
          window.switchTab('dashboard');
        }
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
    showLoginPage();
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
  window.applyPermissions = function() {
    var user = getUserInfo();
    if (!user) return;
    var tabMap = {
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
    };
    Object.keys(tabMap).forEach(function(tabId) {
      var el = document.getElementById(tabId);
      if (el && !hasPermission(tabMap[tabId])) el.style.display = 'none';
    });
    document.querySelectorAll('[data-requires]').forEach(function(el) {
      if (!hasPermission(el.dataset.requires)) el.style.display = 'none';
    });
    var logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) logoutBtn.style.display = '';
    var userInfoEl = document.getElementById('user-info');
    if (userInfoEl && user) userInfoEl.textContent = user.full_name || user.username;
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
          return true;
        }
      } catch(e) {}
    }
    clearTokens();
    showLoginPage();
    return false;
  };
})();
