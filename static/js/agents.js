/* AI agent surfaces: chat panel, explain blocks, triage/report buttons. */
(function () {
  'use strict';

  var STATUS_PATH = '/ai/agents/status';

  function apiPath(p) {
    if (typeof window.API === 'function') { return window.API() + p; }
    return '' + p;
  }

  function authFetch(url, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    if (!opts.headers['Content-Type']) { opts.headers['Content-Type'] = 'application/json'; }
    return window.authFetch(url, opts);
  }

  function postJSON(path, body) {
    return authFetch(apiPath(path), { method: 'POST', body: JSON.stringify(body) })
      .then(function (r) {
        if (!r.ok) { throw new Error('HTTP ' + r.status); }
        return r.json();
      });
  }

  function status() {
    return authFetch(apiPath(STATUS_PATH)).then(function (r) {
      if (!r.ok) { throw new Error('HTTP ' + r.status); }
      return r.json();
    });
  }

  function userLang() {
    if (typeof window.LANG !== 'undefined' && window.LANG) { return window.LANG; }
    if (typeof window.currentLang === 'string' && window.currentLang) { return window.currentLang; }
    return 'en';
  }

  function currentMonth() {
    var d = new Date();
    var m = String(d.getMonth() + 1);
    if (m.length < 2) { m = '0' + m; }
    return d.getFullYear() + '-' + m;
  }

  function togglePanels(s) {
    document.querySelectorAll('[data-agent-panel]').forEach(function (el) {
      var needs = el.getAttribute('data-agent-perm') || 'ai.read';
      var ok = s && s.enabled === true && (s.permissions || []).indexOf(needs) !== -1;
      el.style.display = ok ? '' : 'none';
    });
  }

  function renderResult(data, targetEl) {
    if (!targetEl) { return; }
    if (data && data.enabled === true) {
      renderExplain(data, targetEl);
      return data;
    }
    return data;
  }

  function renderExplain(data, el) {
    if (!el) { return; }
    el.innerHTML = '';
    data = data || {};
    var blocks = [
      ['facts', __('Facts'), data.facts],
      ['analysis', __('Analysis'), data.analysis],
      ['contributors', __('Contributors'), data.contributors],
      ['actions', __('Actions'), data.actions]
    ];
    var rendered = false;
    for (var i = 0; i < blocks.length; i += 1) {
      var pair = blocks[i];
      var items = pair[2];
      if (!items || !items.length) { continue; }
      var wrap = document.createElement('div');
      wrap.className = 'agent-' + pair[0];
      var h = document.createElement('h4');
      h.textContent = pair[1];
      wrap.appendChild(h);
      var list = document.createElement('ul');
      for (var j = 0; j < items.length; j += 1) {
        var li = document.createElement('li');
        li.textContent = typeof items[j] === 'string' ? items[j] : JSON.stringify(items[j]);
        list.appendChild(li);
      }
      wrap.appendChild(list);
      el.appendChild(wrap);
      rendered = true;
    }
    if (!rendered && data.answer) {
      var p = document.createElement('p');
      p.className = 'agent-answer';
      p.textContent = data.answer;
      el.appendChild(p);
    }
  }

  function renderError(err, el) {
    if (!el) { return; }
    var msg = (err && err.message) ? err.message : __('Request failed');
    el.innerHTML = '';
    var p = document.createElement('p');
    p.className = 'agent-error';
    p.textContent = msg;
    el.appendChild(p);
  }

  function explain(opts, targetEl) {
    opts = opts || {};
    return postJSON('/ai/agents/explain', {
      month: opts.month || currentMonth(),
      hospital_id: opts.hospital_id,
      entity: opts.entity || '',
      lang: userLang()
    }).then(function (data) { return renderResult(data, targetEl); });
  }

  function triggerDigest(opts, targetEl) {
    opts = opts || {};
    return postJSON('/ai/agents/digest', {
      month: opts.month || currentMonth(),
      lang: userLang()
    }).then(function (data) { return renderResult(data, targetEl); });
  }

  function triggerReport(opts, targetEl) {
    opts = opts || {};
    return postJSON('/ai/agents/report', {
      month: opts.month || currentMonth(),
      hospital_id: opts.hospital_id,
      lang: userLang()
    }).then(function (data) { return renderResult(data, targetEl); });
  }

  function outputOf(panel) {
    var out = panel.querySelector('.agent-output, [data-agent-output]');
    if (!out) {
      out = document.createElement('div');
      out.className = 'agent-output';
      out.setAttribute('data-agent-output', '');
      panel.appendChild(out);
    }
    return out;
  }

  function mountChat(panel) {
    if (!panel || panel.querySelector('.agent-chat-send')) { return; }
    var title = document.createElement('h4');
    title.className = 'agent-chat-title';
    title.textContent = __('AI Assistant');
    var input = document.createElement('input');
    input.type = 'text';
    input.className = 'agent-chat-input';
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'agent-chat-send';
    btn.textContent = __('Send');
    var out = document.createElement('div');
    out.className = 'agent-chat-output';
    panel.appendChild(title);
    panel.appendChild(input);
    panel.appendChild(btn);
    panel.appendChild(out);
    function send() {
      var msg = input.value.trim();
      if (!msg) { return; }
      input.value = '';
      postJSON('/ai/agents/chat', { message: msg, lang: userLang() }).then(function (data) {
        if (!data || data.enabled !== true) { return; }
        var p = document.createElement('p');
        p.className = 'agent-chat-answer';
        p.textContent = data.answer;
        out.appendChild(p);
      }).catch(function (err) {
        var msg = (err && err.message) ? err.message : __('Request failed');
        var pe = document.createElement('p');
        pe.className = 'agent-error';
        pe.textContent = msg;
        out.appendChild(pe);
      });
    }
    btn.addEventListener('click', send);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.keyCode === 13) { send(); }
    });
  }

  function mountExplain(panel) {
    if (!panel || panel.querySelector('.agent-explain-run')) { return; }
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'agent-explain-run';
    btn.textContent = __('Direct AI explain');
    panel.appendChild(btn);
    var out = outputOf(panel);
    btn.addEventListener('click', function () {
      if (out) { out.innerHTML = ''; }
      explain({
        month: panel.getAttribute('data-month') || currentMonth(),
        hospital_id: panel.getAttribute('data-hospital-id'),
        entity: panel.getAttribute('data-entity') || ''
      }, out).catch(function (err) { renderError(err, out); });
    });
  }

  function mountDigest(panel) {
    if (!panel || panel.querySelector('.agent-digest-run')) { return; }
    if (!panel.hasAttribute('data-agent-perm')) { panel.setAttribute('data-agent-perm', 'ai.write'); }
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'agent-digest-run';
    btn.textContent = __('Generate Triage Digest');
    panel.appendChild(btn);
    var out = outputOf(panel);
    btn.addEventListener('click', function () {
      if (out) { out.innerHTML = ''; }
      triggerDigest({ month: panel.getAttribute('data-month') || currentMonth() }, out)
        .catch(function (err) { renderError(err, out); });
    });
  }

  function mountReport(panel) {
    if (!panel || panel.querySelector('.agent-report-run')) { return; }
    if (!panel.hasAttribute('data-agent-perm')) { panel.setAttribute('data-agent-perm', 'ai.write'); }
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'agent-report-run';
    btn.textContent = __('Generate report');
    panel.appendChild(btn);
    var out = outputOf(panel);
    btn.addEventListener('click', function () {
      if (out) { out.innerHTML = ''; }
      triggerReport({
        month: panel.getAttribute('data-month') || currentMonth(),
        hospital_id: panel.getAttribute('data-hospital-id')
      }, out).catch(function (err) { renderError(err, out); });
    });
  }

  function bindAgentButtons() {
    document.querySelectorAll('[data-agent-explain], [data-agent-digest], [data-agent-report]').forEach(function (btn) {
      if (btn.getAttribute('data-agent-bound')) { return; }
      btn.setAttribute('data-agent-bound', '1');
      var action = btn.hasAttribute('data-agent-explain') ? 'explain'
        : btn.hasAttribute('data-agent-digest') ? 'digest' : 'report';
      if (!btn.hasAttribute('data-agent-perm')) {
        btn.setAttribute('data-agent-perm', action === 'explain' ? 'ai.read' : 'ai.write');
      }
      btn.addEventListener('click', function () {
        var outSel = btn.getAttribute('data-output');
        var out = outSel ? document.querySelector(outSel) : outputOf(btn.parentElement);
        if (out) { out.innerHTML = ''; }
        var opts = {
          month: btn.getAttribute('data-month') || currentMonth(),
          hospital_id: btn.getAttribute('data-hospital-id'),
          entity: btn.getAttribute('data-entity') || ''
        };
        var p = action === 'explain' ? explain(opts, out)
          : action === 'digest' ? triggerDigest(opts, out)
          : triggerReport(opts, out);
        p.catch(function (err) { renderError(err, out); });
      });
    });
  }

  function init(containerIds) {
    var ids = containerIds || {};
    var chat = ids.chat ? document.getElementById(ids.chat) : null;
    if (!chat) { chat = document.querySelector('[data-agent-panel="chat"]'); }
    mountChat(chat);
    var explain = ids.explain ? document.getElementById(ids.explain) : null;
    if (!explain) { explain = document.querySelector('[data-agent-panel="explain"]'); }
    mountExplain(explain);
    var digest = ids.digest ? document.getElementById(ids.digest) : null;
    if (!digest) { digest = document.querySelector('[data-agent-panel="digest"]'); }
    mountDigest(digest);
    var report = ids.report ? document.getElementById(ids.report) : null;
    if (!report) { report = document.querySelector('[data-agent-panel="report"]'); }
    mountReport(report);
    bindAgentButtons();
    return status().catch(function () { return null; }).then(function (s) { togglePanels(s); return s; });
  }

  window.AgentUI = {
    init: init,
    renderExplain: renderExplain,
    togglePanels: togglePanels,
    status: status,
    apiPath: apiPath,
    explain: explain,
    triggerDigest: triggerDigest,
    triggerReport: triggerReport
  };
})();