/**
 * toast.js — Non-blocking toast notifications
 * Replaces browser alert() with slide-in notifications.
 *
 * Usage:
 *   import { toastSuccess, toastError, toastInfo, toastWarning } from './toast.js';
 *   toastSuccess('Settings saved successfully');
 *   toastError('Failed to upload file');
 *   toastInfo('Processing in background...');
 */

let _container = null;

function _getContainer() {
  if (_container) return _container;
  _container = document.createElement('div');
  _container.id = 'toast-container';
  _container.style.cssText = 'position:fixed;top:1rem;right:1rem;z-index:99999;display:flex;flex-direction:column;gap:0.5rem;max-width:380px;pointer-events:none;';
  document.body.appendChild(_container);
  return _container;
}

function _show(type, message, duration) {
  const container = _getContainer();
  const icons = { success: '\u2705', error: '\u274C', warning: '\u26A0\uFE0F', info: '\u2139\uFE0F' };
  const colors = {
    success: { bg: '#f0fdf4', border: '#86efac', text: '#166534' },
    error:   { bg: '#fef2f2', border: '#fca5a5', text: '#991b1b' },
    warning: { bg: '#fffbeb', border: '#fcd34d', text: '#92400e' },
    info:    { bg: '#eff6ff', border: '#93c5fd', text: '#1e40af' }
  };
  const darkColors = {
    success: { bg: '#14532d', border: '#166534', text: '#86efac' },
    error:   { bg: '#7f1d1d', border: '#991b1b', text: '#fca5a5' },
    warning: { bg: '#78350f', border: '#92400e', text: '#fcd34d' },
    info:    { bg: '#1e3a5f', border: '#1e40af', text: '#93c5fd' }
  };
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const c = isDark ? darkColors[type] : colors[type];

  const el = document.createElement('div');
  el.className = 'toast toast-' + type;
  el.style.cssText = 'pointer-events:auto;display:flex;align-items:flex-start;gap:0.5rem;padding:0.7rem 1rem;border-radius:10px;border-left:4px solid ' + c.border + ';background:' + c.bg + ';color:' + c.text + ';box-shadow:0 4px 16px rgba(0,0,0,0.15);font-size:0.85rem;line-height:1.4;animation:toast-in 0.3s ease-out;cursor:pointer;max-width:100%;word-break:break-word;';
  el.innerHTML = '<span style="font-size:1rem;flex-shrink:0;">' + (icons[type] || '') + '</span><span style="flex:1;">' + message + '</span><span style="font-size:0.7rem;opacity:0.5;flex-shrink:0;cursor:pointer;" onclick="this.parentElement.remove()">\u2715</span>';

  el.addEventListener('click', function() { el.remove(); });

  container.appendChild(el);

  // Auto-remove
  const ms = duration || (type === 'error' ? 6000 : type === 'warning' ? 5000 : 3500);
  setTimeout(function() {
    if (el.parentElement) {
      el.style.animation = 'toast-out 0.3s ease-in forwards';
      setTimeout(function() { el.remove(); }, 300);
    }
  }, ms);
}

export function toastSuccess(msg, duration) { _show('success', msg, duration); }
export function toastError(msg, duration) { _show('error', msg, duration); }
export function toastWarning(msg, duration) { _show('warning', msg, duration); }
export function toastInfo(msg, duration) { _show('info', msg, duration); }
