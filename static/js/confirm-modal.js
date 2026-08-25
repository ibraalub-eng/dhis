/**
 * confirm-modal.js — Styled confirmation dialog replacement
 * Drop-in replacement for browser confirm() with branded modal.
 *
 * Usage:
 *   import { confirmAction, confirmDestructive } from './confirm-modal.js';
 *
 *   const ok = await confirmAction({ title: 'Delete Hospital', message: 'Are you sure?' });
 *   if (ok) { deleteHospital(id); }
 *
 *   // Two-step for dangerous actions:
 *   const ok2 = await confirmDestructive({ title: 'Nuclear Option', message: 'Type DELETE to confirm:', confirmText: 'DELETE' });
 */

let _modalEl = null;
let _resolvePromise = null;

function _ensureModal() {
  if (_modalEl) return _modalEl;
  _modalEl = document.createElement('div');
  _modalEl.id = 'confirm-modal-overlay';
  _modalEl.className = 'cm-overlay';
  _modalEl.innerHTML = '<div class="cm-dialog"><div class="cm-header"><span class="cm-icon"></span><span class="cm-title"></span></div><div class="cm-body"></div><div class="cm-actions"></div></div>';
  document.body.appendChild(_modalEl);

  _modalEl.addEventListener('click', function(e) {
    if (e.target === _modalEl) _close(false);
  });
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && _modalEl && _modalEl.classList.contains('cm-visible')) {
      _close(false);
    }
  });
  return _modalEl;
}

function _open(opts) {
  const modal = _ensureModal();
  const icon = opts.danger ? '⚠️' : opts.warning ? '⚠️' : opts.info ? 'ℹ️' : '❓';
  const titleColor = opts.danger ? 'var(--accent-red)' : opts.warning ? 'var(--accent-orange)' : 'var(--accent-blue)';

  modal.querySelector('.cm-icon').textContent = icon;
  modal.querySelector('.cm-title').innerHTML = '<span style="color:' + titleColor + '">' + (opts.title || 'Confirm') + '</span>';

  let bodyHtml = '<p>' + (opts.message || 'Are you sure?') + '</p>';
  if (opts.details) {
    bodyHtml += '<p class="cm-details">' + opts.details + '</p>';
  }
  if (opts.confirmText) {
    bodyHtml += '<div class="cm-confirm-input"><input type="text" id="cm-confirm-typing" placeholder="Type "' + opts.confirmText + '" to confirm" autocomplete="off"></div>';
  }
  modal.querySelector('.cm-body').innerHTML = bodyHtml;

  const actionsHtml = '<button class="cm-btn cm-cancel">' + (opts.cancelLabel || 'Cancel') + '</button>' +
    '<button class="cm-btn cm-ok ' + (opts.danger ? 'cm-btn-danger' : opts.warning ? 'cm-btn-warning' : '') + '">' + (opts.okLabel || 'Confirm') + '</button>';
  modal.querySelector('.cm-actions').innerHTML = actionsHtml;

  const okBtn = modal.querySelector('.cm-ok');
  const cancelBtn = modal.querySelector('.cm-cancel');
  const input = modal.querySelector('#cm-confirm-typing');

  if (opts.confirmText && input) {
    okBtn.disabled = true;
    input.addEventListener('input', function() {
      okBtn.disabled = input.value.toUpperCase() !== opts.confirmText.toUpperCase();
    });
    setTimeout(function() { input.focus(); }, 100);
  } else {
    setTimeout(function() { okBtn.focus(); }, 100);
  }

  okBtn.addEventListener('click', function() { _close(true); });
  cancelBtn.addEventListener('click', function() { _close(false); });

  modal.classList.add('cm-visible');
}

function _close(result) {
  if (_modalEl) {
    _modalEl.classList.remove('cm-visible');
  }
  if (_resolvePromise) {
    _resolvePromise(result);
    _resolvePromise = null;
  }
}

export function confirmAction(opts) {
  return new Promise(function(resolve) {
    _resolvePromise = resolve;
    _open(opts);
  });
}

export function confirmDestructive(opts) {
  return confirmAction(Object.assign({ danger: true }, opts));
}

export function confirmWarning(opts) {
  return confirmAction(Object.assign({ warning: true }, opts));
}
