// ── Direction Coverage tab module ────────────────────────────────────────────
// Screen for app/api/direction_coverage.py.
//
// Quality Alerts can only label a deviation as good or bad when the indicator
// carries a clinical direction. This screen lists the families and data
// elements that still have none, ordered by the number of ACTIVE alerts whose
// interpretation is affected, and shows the direction the server proposes —
// with the evidence behind it (a clinical guideline, or the element's role as
// the numerator of a directed rate). Rows without evidence are left blank on
// purpose: the screen never invents a clinical meaning.
//
// The reviewer can override any proposed direction, then apply the reviewed
// rows in one batch. Applying writes the direction only; stored alerts keep
// their old interpretation until Quality Alerts is re-scanned, which the
// banner offers right after the save.
import { apiGet, apiPostJSON } from './api.js';
import { __ } from './i18n.js';
import { esc } from './tree.js';
import { toastSuccess, toastError, toastInfo } from './toast.js';
import { confirmAction } from './confirm-modal.js';
import { screenUrl } from './newtab.js';

const _FRESH = { noCache: true };

const _DIR_LABEL = {
    higher_is_better: 'Higher is better',
    lower_is_better: 'Lower is better',
};

const _BASIS_LABEL = {
    clinical_guideline: 'Clinical guideline',
    none: 'No basis',
};

let _items = [];
let _loaded = false;

function _t(text) { return __(text); }

function _val(id) {
    const el = document.getElementById(id);
    return el ? String(el.value) : '';
}

function _errText(err) {
    const raw = String((err && err.message) || err || '');
    const m = raw.match(/HTTP \d+: (.*)$/s);
    if (!m) return raw;
    try {
        const body = JSON.parse(m[1]);
        const detail = body.detail;
        if (typeof detail === 'string') return detail;
        if (Array.isArray(detail)) return detail.join(' — ');
        if (detail) return JSON.stringify(detail);
    } catch (e) { /* not JSON */ }
    return raw;
}

function _fmtInt(n) {
    const value = Number(n);
    return isFinite(value) ? value.toLocaleString() : String(n);
}

// ── filtering / rendering ───────────────────────────────────────────────────

function _visibleItems() {
    const filter = _val('dcFilter') || 'all';
    const needle = _val('dcSearch').trim().toLowerCase();
    return _items.filter(item => {
        if (filter === 'alerts' && !item.active_alerts) return false;
        if (filter === 'suggested' && !item.suggested_direction) return false;
        if (needle) {
            const hay = [item.code, item.name, item.group_name || '']
                .join(' ').toLowerCase();
            if (!hay.includes(needle)) return false;
        }
        return true;
    });
}

function _dirOptions(item) {
    const suggested = item.suggested_direction || '';
    const options = ['<option value="">' + esc(_t('— choose —')) + '</option>'];
    for (const value of Object.keys(_DIR_LABEL)) {
        const selected = value === suggested ? ' selected' : '';
        options.push('<option value="' + value + '"' + selected + '>' +
            esc(_t(_DIR_LABEL[value])) + '</option>');
    }
    return options.join('');
}

function _rowHtml(item) {
    const key = item.code;
    const suggested = item.suggested_direction || '';
    const basis = _BASIS_LABEL[item.suggestion_basis] || item.suggestion_basis;
    const reason = item.suggestion_reason || '';
    const group = item.group_name
        ? '<div style="font-size:0.68rem;color:var(--text-muted);">' + esc(item.group_name) + '</div>'
        : '';
    const unit = item.unit
        ? '<span style="font-size:0.68rem;color:var(--text-muted);"> · ' + esc(item.unit) + '</span>'
        : '';
    const alertStyle = item.active_alerts
        ? 'font-weight:700;color:var(--text-primary);'
        : 'color:var(--text-muted);';
    // The code opens the family's definition in a new tab, so the reviewer
    // reads the full detail while this reviewed list (selections included)
    // stays put.
    const codeHref = screenUrl('indicators', {
        code: item.code,
        def: item.definition_id || '',
    });
    const codeTitle = _t('Open the indicator definition');
    return '<tr data-code="' + esc(item.code) + '" data-key="' + esc(key) + '">' +
        '<td style="text-align:center;">' +
        '<input type="checkbox" class="dc-pick" data-key="' + esc(key) + '" style="accent-color:var(--accent-blue);">' +
        '</td>' +
        '<td style="text-align:left;white-space:nowrap;">' +
        '<a class="dc-code-link" href="' + esc(codeHref) + '" target="_blank" rel="noopener"' +
        ' title="' + esc(codeTitle) + '"' +
        ' style="font-family:monospace;direction:ltr;color:var(--accent-blue);text-decoration:underline;">' +
        esc(item.code) + '</a></td>' +
        '<td>' + esc(item.name) + unit + group + '</td>' +
        '<td style="text-align:right;' + alertStyle + '">' + _fmtInt(item.active_alerts) + '</td>' +
        '<td><select class="dc-dir" data-key="' + esc(key) + '" style="font-size:0.74rem;padding:0.2rem;border:1px solid var(--border-default);border-radius:6px;background:var(--bg-input);color:var(--text-primary);">' +
        _dirOptions(item) + '</select></td>' +
        '<td style="max-width:340px;">' +
        '<span style="font-size:0.66rem;font-weight:600;color:var(--text-muted);">' + esc(_t(basis)) + '</span>' +
        (suggested ? ' <span style="font-size:0.62rem;color:var(--accent-green);">✓ ' + esc(_t('proposed')) + '</span>' : '') +
        (reason ? '<div style="font-size:0.7rem;color:var(--text-secondary);line-height:1.35;">' + esc(reason) + '</div>' : '') +
        '</td>' +
        '</tr>';
}

function _render() {
    const rows = _visibleItems();
    const tbody = document.getElementById('dcTbody');
    if (!tbody) return;
    tbody.innerHTML = rows.map(_rowHtml).join('');
    tbody.querySelectorAll('.dc-pick').forEach(box => {
        box.addEventListener('change', _updateSelectionCount);
    });
    tbody.querySelectorAll('.dc-dir').forEach(select => {
        select.addEventListener('change', () => {
            // Choosing a direction IS the review decision: tick the row so
            // "Apply selected" never silently ignores a row the reviewer set.
            const box = select.closest('tr').querySelector('.dc-pick');
            if (box && select.value) box.checked = true;
            _updateSelectionCount();
        });
    });
    const empty = document.getElementById('dcEmpty');
    if (empty) {
        empty.style.display = rows.length ? 'none' : 'block';
        const message = empty.querySelector('p');
        if (message) {
            message.textContent = _items.length
                ? _t('No indicators match the current filters.')
                : _t('Every indicator carries a direction — nothing to review.');
        }
    }
    const count = document.getElementById('dcCount');
    if (count) {
        count.textContent = rows.length === _items.length
            ? '' : rows.length + ' / ' + _items.length;
    }
    const selectAll = document.getElementById('dcSelectAll');
    if (selectAll) selectAll.checked = false;
    _updateSelectionCount();
}

function _selectedRows() {
    return Array.from(document.querySelectorAll('#dcTbody tr'))
        .map(tr => {
            const box = tr.querySelector('.dc-pick');
            const select = tr.querySelector('.dc-dir');
            return {
                code: tr.dataset.code,
                checked: !!(box && box.checked),
                direction: select ? select.value : '',
            };
        })
        .filter(row => row.checked);
}

function _updateSelectionCount() {
    const label = document.getElementById('dcApplyCount');
    if (label) {
        const count = _selectedRows().length;
        label.textContent = count ? '(' + count + ')' : '';
    }
}

// ── data ───────────────────────────────────────────────────────────────────

async function loadDirectionCoverage_impl() {
    const loading = document.getElementById('dcLoading');
    const tbody = document.getElementById('dcTbody');
    if (loading) loading.style.display = 'block';
    if (tbody) tbody.innerHTML = '';
    try {
        const data = await apiGet('/direction-coverage', _FRESH);
        _items = (data && data.items) || [];
        const summary = (data && data.summary) || {};
        const set = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.textContent = _fmtInt(value || 0);
        };
        set('dcFamilies', summary.families);

        set('dcAlerts', summary.active_alerts);
        set('dcSuggested', summary.with_suggestion);
        _render();
        _loaded = true;
    } catch (err) {
        toastError(_errText(err));
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--accent-red);padding:1rem;">' +
                esc(_errText(err)) + '</td></tr>';
        }
    } finally {
        if (loading) loading.style.display = 'none';
    }
}

function initDirectionCoverage_impl() {
    if (_loaded) { _render(); return; }
    return loadDirectionCoverage_impl();
}

function _filterChanged() {
    _render();
}

function _toggleAllSuggested(checked) {
    document.querySelectorAll('#dcTbody tr').forEach(tr => {
        const select = tr.querySelector('.dc-dir');
        const box = tr.querySelector('.dc-pick');
        if (!select || !box) return;
        box.checked = !!checked && !!select.value;
    });
    _updateSelectionCount();
}

// ── apply ──────────────────────────────────────────────────────────────────

async function applyDirectionCoverage_impl() {
    const picked = _selectedRows();
    if (!picked.length) {
        toastInfo(_t('Select at least one row to apply.'));
        return;
    }
    const missing = picked.filter(row => !row.direction);
    if (missing.length) {
        toastError(_t('Choose a direction for the selected rows, or clear their selection.') +
            ' (' + missing.map(row => row.code).slice(0, 5).join(', ') +
            (missing.length > 5 ? '…' : '') + ')');
        return;
    }
    const families = picked.length;
    const ok = await confirmAction({
        title: _t('Apply the reviewed directions?'),
        message: _t('This writes the clinical direction of the selected indicators. Nothing else changes.'),
        details: _t('Families') + ': ' + families + '<br>' +
            picked.map(row => esc(row.code) + ' → ' + esc(_t(_DIR_LABEL[row.direction])))
                .join('<br>'),
        okLabel: _t('Apply'),
    });
    if (!ok) return;

    const btn = document.getElementById('dcApplyBtn');
    if (btn) btn.disabled = true;
    try {
        const res = await apiPostJSON('/direction-coverage/apply', {
            items: picked.map(row => ({
                kind: 'family', code: row.code, direction: row.direction,
            })),
        });
        const applied = (res && res.applied) || 0;
        const skipped = (res && res.skipped) || 0;
        if (applied) {
            toastSuccess(applied + ' ' + _t('directions applied') +
                (skipped ? ' · ' + skipped + ' ' + _t('already recorded') : ''));
        } else {
            toastInfo(_t('Nothing to change — every selected row already has that direction.'));
        }
        const banner = document.getElementById('dcRescanBanner');
        if (banner) banner.style.display = (res && res.rescan_required) ? 'block' : 'none';
        await loadDirectionCoverage_impl();
    } catch (err) {
        toastError(_errText(err));
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function rescanAfterDirections_impl() {
    const banner = document.getElementById('dcRescanBanner');
    try {
        toastInfo(_t('Re-scanning every month…'));
        const res = await apiPostJSON('/quality-alerts/scan', {});
        const created = (res && res.created) || 0;
        const updated = (res && res.updated) || 0;
        toastSuccess(_t('Quality Alerts re-scanned') + ' · ' + created + ' ' +
            _t('created') + ' · ' + updated + ' ' + _t('updated'));
        if (banner) banner.style.display = 'none';
        await loadDirectionCoverage_impl();
    } catch (err) {
        toastError(_errText(err));
    }
}

// ── inline-handler hooks referenced by the fragment ────────────────────────
window._dcReload = function () { return loadDirectionCoverage_impl(); };
window._dcFilterChange = _filterChanged;
window._dcToggleAll = _toggleAllSuggested;
window._dcApply = function () { return applyDirectionCoverage_impl(); };
window._dcRescan = function () { return rescanAfterDirections_impl(); };

// ── public exports (app.js `_bind` / main.js `_tryInit`) ────────────────────
export function initDirectionCoverage() { return initDirectionCoverage_impl(); }
export function loadDirectionCoverage() { return loadDirectionCoverage_impl(); }
export function directionCoverageFilterChanged() { return _filterChanged(); }
export function directionCoverageToggleAllSuggested(checked) { return _toggleAllSuggested(checked); }
export function applyDirectionCoverage() { return applyDirectionCoverage_impl(); }
export function rescanAfterDirections() { return rescanAfterDirections_impl(); }
