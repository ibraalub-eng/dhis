// core.js — shared state, fetch, loaders, mode switching, small utilities.
// Singletons used by the whole smart-analytics screen.

export const SMART_COLORS = {
  normal: '#22c55e', warning: '#f59e0b', critical: '#ef4444',
  clusters: ['#3b82f6', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#06b6d4', '#84cc16'],
  noise: '#6b7280', shap_positive: '#ef4444', shap_negative: '#3b82f6',
  corr_negative: '#3b82f6', corr_zero: '#ffffff', corr_positive: '#ef4444',
};

export const smartState = {
  month: null,
  data: null,
  monthChartsRendered: false,
  reportGenerating: false,
  mode: 'monthly',
  lang: 'ar',
};

// i18n helper: use the global __ from app.js when available, else passthrough.
export function _t(text) {
  if (typeof window.__ === 'function') {
    const translated = window.__(text);
    if (translated && translated !== text) return translated;
  }
  const smartArabic = window.SMART_ARABIC || {};
  return smartArabic[text] || text;
}

export async function apiSmartGet(path) {
  const base = document.getElementById('apiBase')?.value || '';
  const res = await fetch(base + path);
  if (!res.ok) {
    let detail = '';
    try { detail = (await res.json()).detail || ''; } catch (e) { /* ignore */ }
    throw new Error(detail || ('HTTP ' + res.status));
  }
  return res.json();
}

export function smartShowLoading() {
  const el = document.getElementById('smart-loading-overlay');
  if (el) el.style.display = 'flex';
}
export function smartHideLoading() {
  const el = document.getElementById('smart-loading-overlay');
  if (el) el.style.display = 'none';
}

export function setSmartLoader(key, active) {
  const el = document.querySelector(`[data-smart-loader="${key}"]`);
  if (el) el.classList.toggle('active', !!active);
}

export function showSmartSectionError(key, message) {
  const err = document.querySelector(`[data-smart-error="${key}"]`);
  if (err) { err.textContent = message || _t('Failed to load'); err.classList.add('active'); }
  const empty = document.querySelector(`[data-smart-empty="${key}"]`);
  if (empty) empty.textContent = '';
}

export function showSmartSectionEmpty(key, message) {
  const empty = document.querySelector(`[data-smart-empty="${key}"]`);
  if (empty) { empty.textContent = message || _t('No data'); empty.style.display = 'block'; }
  const err = document.querySelector(`[data-smart-error="${key}"]`);
  if (err) err.classList.remove('active');
}

export function clearSmartSectionState(key) {
  const loader = document.querySelector(`[data-smart-loader="${key}"]`);
  if (loader) loader.classList.remove('active');
  const err = document.querySelector(`[data-smart-error="${key}"]`);
  if (err) { err.textContent = ''; err.classList.remove('active'); }
  const empty = document.querySelector(`[data-smart-empty="${key}"]`);
  if (empty) { empty.textContent = ''; empty.style.display = 'none'; }
}

export function _smartEscapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export function _fmtNum(v, digits) {
  if (v == null || isNaN(v)) return '-';
  return Number(v).toFixed(digits == null ? 2 : digits);
}

export function _riskBadge(label, level) {
  const cls = level === 'critical' ? 'smart-badge-critical'
    : level === 'warning' ? 'smart-badge-warning' : 'smart-badge-normal';
  return `<span class="${cls}">${_smartEscapeHtml(label)}</span>`;
}

// Translate feature keys (reuses the global SMART_ARABIC dict registered by charts.js)
export function smartTranslateFeature(name) {
  const ar = window.SMART_ARABIC || {};
  if (!name) return '-';
  if (ar[name]) return ar[name];
  if (name.startsWith('governorate_')) {
    const val = name.substring('governorate_'.length);
    return val.startsWith('محافظة') ? val : 'محافظة ' + val;
  }
  if (name.startsWith('hospital_type_')) {
    const val = name.substring('hospital_type_'.length);
    return val.startsWith('نوع') ? val : 'نوع: ' + val;
  }
  return name;
}

export function toggleSmartSection(header) {
  const card = header.closest('.smart-section-card');
  if (!card) return;
  const isOpen = card.classList.contains('open');
  card.classList.toggle('open', !isOpen);
  const targetId = header.getAttribute('data-smart-collapsible');
  const target = targetId ? document.getElementById(targetId) : null;
  if (isOpen && target && window.Plotly) {
    // collapsing: purge Plotly charts inside to free memory (spec 3.4)
    target.querySelectorAll('[id]').forEach(el => {
      if (el.__plotly) Plotly.purge(el.id);
    });
  }
  if (target && !isOpen) {
    // opening: notify section loader registry (IntersectionObserver re-run)
    const evt = new CustomEvent('smart-section-opened', { detail: { id: targetId } });
    document.dispatchEvent(evt);
  }
}

export function setSmartMode(mode) {
  smartState.mode = mode;
  document.querySelectorAll('.smart-mode-btn').forEach(btn => {
    const active = btn.dataset.smartMode === mode;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.getElementById('smart-monthly-panel').style.display = mode === 'monthly' ? 'block' : 'none';
  document.getElementById('smart-time-panel').style.display = mode === 'time' ? 'block' : 'none';
  document.getElementById('smart-hospital-panel').style.display = mode === 'hospital' ? 'block' : 'none';
  document.getElementById('smart-monthly-context').style.display = mode === 'monthly' ? 'flex' : 'none';
  document.getElementById('smart-time-context').style.display = mode === 'time' ? 'block' : 'none';
  document.getElementById('smart-hospital-context').style.display = mode === 'hospital' ? 'flex' : 'none';
  const evt = new CustomEvent('smart-mode-changed', { detail: { mode } });
  document.dispatchEvent(evt);
}

// Registry: key -> { load: () => Promise, containerId }
const _sectionRegistry = {};
export function registerSectionLoaders(registry) {
  Object.assign(_sectionRegistry, registry);
}

// IntersectionObserver: lazily load each registered section when visible.
export function initSectionObserver() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      const el = entry.target;
      const key = el.getAttribute('data-smart-loader');
      if (!key) return;
      observer.unobserve(el);
      const entryItem = _sectionRegistry[key];
      if (entryItem && typeof entryItem.load === 'function') {
        setSmartLoader(key, true);
        entryItem.load().catch(() => {}).finally(() => setSmartLoader(key, false));
      }
    });
  }, { rootMargin: '200px' });
  document.querySelectorAll('[data-smart-loader]').forEach(el => observer.observe(el));
  return observer;
}

// Focus trap + Escape for modals.
export function trapFocus(modalEl, openFocusEl) {
  const focusables = modalEl.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  function onKey(e) {
    if (e.key === 'Tab') {
      if (e.shiftKey) {
        if (document.activeElement === first || !modalEl.contains(document.activeElement)) {
          e.preventDefault(); last.focus();
        }
      } else {
        if (document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }
    if (e.key === 'Escape') { close(); }
  }
  function close() {
    modalEl.style.display = 'none';
    document.removeEventListener('keydown', onKey);
    if (openFocusEl) openFocusEl.focus();
  }
  document.addEventListener('keydown', onKey);
  (openFocusEl || first)?.focus();
  return { close };
}