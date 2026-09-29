// ── Indicator Groups module ──────────────────────────────────────────
// Bulk enable/disable macros over indicators (design rev 2:
// docs/superpowers/specs/2026-09-28-indicator-groups-design.md).
//
// The group itself is NEVER consulted at runtime — toggling upserts
// IndicatorDefaultConfig (scope 'all') or HospitalIndicatorConfig
// (scope 'hospital') rows and the existing effective-state logic does
// the rest. "is_enabled" shown in the UI is DERIVED server-side from
// member config rows, so it stays correct after single-indicator edits.
//
// Rev-2 constraints surfaced here:
//  * Hospital scope is month-agnostic (hospital_indicator_config has no
//    month column) → month inputs are hidden and cleared for it; the
//    backend 422s a stored range anyway.
//  * Empty range on scope 'all' falls back to all known months — the
//    toggle response includes the effective month list.
//  * Toggles are explicit {"enabled": bool} (idempotent), never a flip.
import { apiGet, apiPostJSON, apiPut, apiDelete } from './api.js';
import { __ } from './i18n.js';
import { esc } from './tree.js';
import { toastSuccess, toastError } from './toast.js';
import { confirmDestructive } from './confirm-modal.js';

let _groups = [];            // cached list payload from GET /indicator-groups
let _hospitals = [];         // for the hospital dropdown
let _pickerTree = null;      // indicator tree for the member pickers
let _pickerExpanded = {};    // id → bool, picker expansion state
let _pickerChecked = {};     // id → bool, checked indicators (editor modal)
let _membersChecked = {};    // id → bool, checked indicators (members modal)
let _editingGroupId = null;  // null = create
let _membersGroupId = null;

// Groups screen always re-fetches: group state changes from other
// screens (tree toggles, never-reported) must not be masked by a cache.
const _fresh = { noCache: true };

// ── Init / data loading ──────────────────────────────────────────────

export async function initIndicatorGroups() {
    // Health check first: a 403 here (missing settings.read) would otherwise
    // leave an empty list that looks like "no groups yet".
    try {
        _groups = await apiGet('/indicator-groups', _fresh);
    } catch (err) {
        _renderLoadError(err);
        return;
    }
    _syncPermissionUI();
    // Hospital dropdown + tree are non-fatal: group list still works.
    _loadHospitals();
    _loadPickerTree();
    _renderGroups();
}

export async function refreshIndicatorGroups() {
    const btn = document.getElementById('igLoading');
    if (btn) btn.style.display = 'block';
    try {
        _groups = await apiGet('/indicator-groups', _fresh);
        _renderGroups();
    } catch (err) {
        _renderLoadError(err);
    } finally {
        if (btn) btn.style.display = 'none';
    }
}

function _renderLoadError(err) {
    const c = document.getElementById('igGroupsContainer');
    const empty = document.getElementById('igEmpty');
    const loading = document.getElementById('igLoading');
    if (loading) loading.style.display = 'none';
    if (empty) empty.style.display = 'none';
    if (c) c.innerHTML =
        '<div style="text-align:center;padding:2rem 1rem;">' +
        '<div style="font-size:1.5rem;margin-bottom:0.4rem;">⚠️</div>' +
        '<div style="color:var(--accent-red);font-weight:600;font-size:0.9rem;margin-bottom:0.3rem;">' + __('Failed to load groups') + '</div>' +
        '<div style="color:var(--text-muted);font-size:0.78rem;word-break:break-word;">' + esc(String(err && err.message || err)) + '</div>' +
        '<button class="btn btn-sm" style="margin-top:0.7rem;" onclick="refreshIndicatorGroups()">↻ ' + __('Retry') + '</button>' +
        '</div>';
}

// Hide write buttons when the token lacks settings.write — matching the
// data-requires pattern used across the other admin screens.
function _syncPermissionUI() {
    let canWrite = true;
    try {
        // window.hasPermission (auth.js) is the canonical gate: it already
        // handles the '*.*' superadmin wildcard — don't reimplement it.
        canWrite = window.hasPermission
            ? window.hasPermission('settings.write')
            : true;
    } catch (e) { /* assume allowed; server enforces anyway */ }
    document.querySelectorAll('#tab-indicator-groups [data-requires="settings.write"]').forEach(el => {
        el.style.display = canWrite ? '' : 'none';
    });
    if (!canWrite) _showNotice(__('Read-only view: you need the settings.write permission to modify groups.'));
}

function _showNotice(msg) {
    const el = document.getElementById('igNotice');
    if (!el) return;
    if (!msg) { el.classList.add('hidden'); return; }
    el.textContent = msg;
    el.classList.remove('hidden');
}

async function _loadHospitals() {
    try {
        const hs = await apiGet('/hospitals/');
        _hospitals = hs && (hs.hospitals || hs) || [];
        const sel = document.getElementById('igHospitalSelect');
        if (sel) {
            sel.innerHTML = '<option value="">' + __('Select hospital…') + '</option>' +
                _hospitals.map(h => '<option value="' + h.id + '">' + esc(h.name) + '</option>').join('');
        }
    } catch (e) { /* dropdown stays empty; server still validates */ }
}

async function _loadPickerTree() {
    try {
        // month=__all__ aggregates every known month; the endpoint REQUIRES
        // the month param (422 without it).
        _pickerTree = await apiGet('/hospitals/indicator-tree/default?month=__all__', _fresh);
    } catch (e) {
        _pickerTree = null;
    }
    const boxes = [document.getElementById('igTreePicker'), document.getElementById('igTreePicker2')];
    boxes.forEach(b => { if (b && !_pickerTree) b.innerHTML = '<div style="text-align:center;color:var(--accent-red);padding:1rem;">' + __('Failed to load indicator tree') + '</div>'; });
    if (_pickerTree && _membersGroupId) igRenderTreePicker('igTreePicker2');
    if (_pickerTree && document.getElementById('igGroupModal').style.display === 'flex') igRenderTreePicker();
}

// ── Group list rendering ─────────────────────────────────────────────

function _fmtRange(g) {
    if (g.scope_type !== 'all') return __('every month');
    if (!g.month_from && !g.month_to) return __('all known months');
    const from = g.month_from || '…';
    const to = g.month_to || '…';
    return from === to ? from : from + ' → ' + to;
}

export function _renderGroups() {
    const wrap = document.getElementById('igGroupsContainer');
    const empty = document.getElementById('igEmpty');
    const loading = document.getElementById('igLoading');
    if (!wrap) return;
    if (loading) loading.style.display = 'none';
    if (!Array.isArray(_groups) || !_groups.length) {
        wrap.innerHTML = '';
        if (empty) empty.style.display = 'block';
        return;
    }
    if (empty) empty.style.display = 'none';
    wrap.innerHTML = _groups.map(g => {
        const scopeBadge = g.scope_type === 'all'
            ? '<span style="font-size:0.7rem;background:var(--accent-blue);color:#fff;padding:1px 8px;border-radius:8px;">' + __('All hospitals') + '</span>'
            : '<span style="font-size:0.7rem;background:var(--accent-purple);color:#fff;padding:1px 8px;border-radius:8px;">🏥 ' + esc(g.hospital_name || ('#' + g.hospital_id)) + '</span>';
        const stateBadge = g.is_enabled
            ? '<span style="font-size:0.72rem;color:var(--accent-green);font-weight:600;">● ' + __('Enabled') + '</span>'
            : '<span style="font-size:0.72rem;color:var(--accent-red);font-weight:600;">● ' + __('Disabled') + '</span>';
        const rangeTxt = _fmtRange(g);
        return '<div class="card" style="padding:0.8rem 1rem;border-left:4px solid ' + (g.is_enabled ? 'var(--accent-green)' : 'var(--accent-red)') + ';">' +
            '<div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:0.5rem;">' +
                '<div style="min-width:220px;flex:1;">' +
                    '<div style="font-weight:700;font-size:0.95rem;color:var(--text-primary);">' + esc(g.name) + ' <span style="font-weight:400;color:var(--text-muted);font-size:0.75rem;">#' + g.id + '</span></div>' +
                    (g.description ? '<div style="font-size:0.78rem;color:var(--text-secondary);margin-top:0.15rem;">' + esc(g.description) + '</div>' : '') +
                    '<div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap;margin-top:0.4rem;">' +
                        scopeBadge + stateBadge +
                        '<span style="font-size:0.74rem;color:var(--text-muted);direction:ltr;">📅 ' + esc(rangeTxt) + '</span>' +
                        '<span style="font-size:0.74rem;color:var(--text-secondary);">' + __('Members:') + ' <strong>' + g.member_count + '</strong></span>' +
                    '</div>' +
                '</div>' +
                '<div style="display:flex;gap:0.4rem;flex-wrap:wrap;align-items:center;">' +
                    '<button class="btn btn-sm" data-requires="settings.write" onclick="igToggleGroup(' + g.id + ', true)" style="background:var(--accent-green);color:#fff;">' + __('Enable All') + '</button>' +
                    '<button class="btn btn-sm" data-requires="settings.write" onclick="igToggleGroup(' + g.id + ', false)" style="background:var(--accent-red);color:#fff;">' + __('Disable All') + '</button>' +
                    '<button class="btn btn-sm btn-outline" onclick="igPreviewImpact(' + g.id + ')" title="' + __('Dry run: what would Enable/Disable All change?') + '">🔍 ' + __('Impact') + '</button>' +
                    '<button class="btn btn-sm btn-outline" onclick="igOpenMembers(' + g.id + ')">' + __('Members') + '</button>' +
                    '<button class="btn btn-sm btn-outline" data-requires="settings.write" onclick="igEditGroup(' + g.id + ')">' + __('Edit') + '</button>' +
                    '<button class="btn btn-sm btn-outline" data-requires="settings.write" onclick="igDeleteGroup(' + g.id + ')" style="color:var(--accent-red);border-color:var(--accent-red);">' + __('Delete') + '</button>' +
                '</div>' +
            '</div>' +
        '</div>';
    }).join('');
    _syncPermissionUI();
}

// ── Toggle (explicit, idempotent — never a flip) ─────────────────────

export async function igToggleGroup(groupId, enabled) {
    const g = _groups.find(x => x.id === groupId);
    if (g && g.member_count === 0) {
        toastError(__('Group has no members — add indicators first.'));
        return;
    }
    if (g && g.scope_type === 'all' && !g.month_from && !g.month_to) {
        _showNotice(__('No month range set: the toggle will apply to ALL known months (every month with values or default configs).'));
    } else {
        _showNotice('');
    }
    try {
        const res = await apiPut('/indicator-groups/' + groupId + '/toggle', { enabled: !!enabled });
        toastSuccess(esc(res.message || (enabled ? __('Enabled') : __('Disabled'))));
        await refreshIndicatorGroups();
    } catch (err) {
        toastError(_errText(err));
    }
}

// ── Create / edit modal ──────────────────────────────────────────────

// The group-card Edit button calls this; openGroupModal doubles as the
// create path when called without an id. (Defined separately so the
// app.js _bind check and the inline onclick both resolve.)
export function igEditGroup(groupId) {
    openGroupModal(groupId);
}

// The three modals share one z-index; the later-in-DOM one paints on top.
// Opening any modal must close the others, or a still-open impact preview
// hides the edit modal that just opened "underneath" it.
function _closeOtherModals(keepId) {
    ['igGroupModal', 'igMembersModal', 'igImpactModal'].forEach(id => {
        if (id !== keepId) {
            const el = document.getElementById(id);
            if (el) el.style.display = 'none';
        }
    });
}

export function openGroupModal(groupId) {
    _closeOtherModals('igGroupModal');
    _editingGroupId = groupId || null;
    _pickerChecked = {};
    const modal = document.getElementById('igGroupModal');
    const err = document.getElementById('igFormError');
    if (err) err.style.display = 'none';
    document.getElementById('igModalTitle').textContent =
        groupId ? __('Edit Group') : __('New Group');
    const g = groupId ? _groups.find(x => x.id === groupId) : null;
    document.getElementById('igGroupName').value = g ? g.name : '';
    document.getElementById('igGroupDesc').value = g && g.description ? g.description : '';
    const scope = g ? g.scope_type : 'all';
    document.querySelectorAll('input[name="igScope"]').forEach(r => { r.checked = r.value === scope; });
    document.getElementById('igHospitalSelect').value = g && g.hospital_id ? String(g.hospital_id) : '';
    document.getElementById('igMonthFrom').value = g && g.month_from ? g.month_from : '';
    document.getElementById('igMonthTo').value = g && g.month_to ? g.month_to : '';
    if (g && g.members && g.members.length) {
        g.members.forEach(m => { _pickerChecked[m.indicator_id] = true; });
    }
    igOnScopeChange();
    modal.style.display = 'flex';
    igRenderTreePicker();
    _loadHospitals(); // ensure dropdown is populated even if the early load raced
    if (groupId) {
        // The LIST payload carries members: [] — fetch the detail so the
        // picker shows the group's real membership as checked.
        apiGet('/indicator-groups/' + groupId, _fresh).then(d => {
            if (_editingGroupId !== groupId) return; // modal closed/reopened meanwhile
            (d.members || []).forEach(m => { _pickerChecked[m.indicator_id] = true; });
            igRenderTreePicker();
        }).catch(() => { /* picker stays at list-level state */ });
    }
}

export function closeGroupModal() {
    const modal = document.getElementById('igGroupModal');
    if (modal) modal.style.display = 'none';
    _editingGroupId = null;
    _pickerChecked = {};
}

export function igOnScopeChange() {
    const scopeEl = document.querySelector('input[name="igScope"]:checked');
    const scope = scopeEl ? scopeEl.value : 'all';
    const isHospital = scope === 'hospital';
    // Rev 2: hospital overrides are month-agnostic — the range CANNOT apply,
    // so it is hidden and cleared (the backend 422s a stored range anyway).
    document.getElementById('igHospitalWrap').style.display = isHospital ? '' : 'none';
    document.getElementById('igMonthFromWrap').style.display = isHospital ? 'none' : '';
    document.getElementById('igMonthToWrap').style.display = isHospital ? 'none' : '';
    if (isHospital) {
        igClearMonths();
    }
}

// Empty range = the toggle falls back to ALL known months — one click to
// get back to that after picking dates.
export function igClearMonths() {
    document.getElementById('igMonthFrom').value = '';
    document.getElementById('igMonthTo').value = '';
}

function _validateMonths(from, to) {
    const re = /^\d{4}-(0[1-9]|1[0-2])$/;
    if (from && !re.test(from)) return __('Month From must be YYYY-MM (e.g. 2025-01)');
    if (to && !re.test(to)) return __('Month To must be YYYY-MM (e.g. 2025-06)');
    if (from && to && from > to) return __('Month From must be ≤ Month To');
    return null;
}

export async function saveGroupModal() {
    const errEl = document.getElementById('igFormError');
    errEl.style.display = 'none';
    const name = document.getElementById('igGroupName').value.trim();
    if (!name) { errEl.textContent = __('Name is required'); errEl.style.display = 'block'; return; }
    const scopeEl = document.querySelector('input[name="igScope"]:checked');
    const scope = scopeEl ? scopeEl.value : 'all';
    const hospitalId = scope === 'hospital' ? parseInt(document.getElementById('igHospitalSelect').value, 10) : null;
    if (scope === 'hospital' && !hospitalId) {
        errEl.textContent = __('Hospital scope requires selecting a hospital');
        errEl.style.display = 'block';
        return;
    }
    const from = scope === 'all' ? document.getElementById('igMonthFrom').value.trim() : null;
    const to = scope === 'all' ? document.getElementById('igMonthTo').value.trim() : null;
    const monthErr = _validateMonths(from, to);
    if (monthErr) { errEl.textContent = monthErr; errEl.style.display = 'block'; return; }
    const indicatorIds = Object.keys(_pickerChecked).filter(k => _pickerChecked[k]).map(Number);

    const body = { name, description: document.getElementById('igGroupDesc').value.trim() || null, scope_type: scope };
    if (scope === 'hospital') body.hospital_id = hospitalId;
    else {
        // Only send the range fields when they changed — the backend treats
        // an explicit null as "clear this field".
        body.month_from = from || null;
        body.month_to = to || null;
    }
    const wasEdit = !!_editingGroupId;
    if (!wasEdit) body.indicator_ids = indicatorIds;
    try {
        let saved;
        if (wasEdit) {
            saved = await apiPut('/indicator-groups/' + _editingGroupId, body);
            if (indicatorIds.length) {
                saved = await apiPostJSON('/indicator-groups/' + _editingGroupId + '/members', { indicator_ids: indicatorIds });
            }
        } else {
            saved = await apiPostJSON('/indicator-groups', body);
        }
        closeGroupModal();
        toastSuccess(__('Group saved'));
        _groups = await apiGet('/indicator-groups', _fresh);
        _renderGroups();
        if (!wasEdit) {
            // Point at the one-click bulk toggle right after creation.
            _showNotice(__('Group created — use Enable All / Disable All to write the config rows.'));
        }
    } catch (e) {
        errEl.textContent = _errText(e);
        errEl.style.display = 'block';
    }
}

// ── Delete ───────────────────────────────────────────────────────────

export async function igDeleteGroup(groupId) {
    const g = _groups.find(x => x.id === groupId);
    const name = g ? g.name : ('#' + groupId);
    const ok = await confirmDestructive({
        title: __('Delete group?'),
        message: __('This removes the group definition only — config rows written by past toggles stay in effect.') + '<br><strong>' + esc(name) + '</strong>',
    });
    if (!ok) return;
    try {
        await apiDelete('/indicator-groups/' + groupId);
        toastSuccess(__('Group deleted') + ': ' + esc(name));
        await refreshIndicatorGroups();
    } catch (e) {
        toastError(_errText(e));
    }
}

// ── Members modal (existing group) ───────────────────────────────────

export async function igOpenMembers(groupId) {
    _closeOtherModals('igMembersModal');
    _membersGroupId = groupId;
    _membersChecked = {};
    const modal = document.getElementById('igMembersModal');
    document.getElementById('igMembersTitle').textContent = __('Members');
    document.getElementById('igMembersList').innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:0.8rem;"><span class="spinner"></span></div>';
    modal.style.display = 'flex';
    try {
        const detail = await apiGet('/indicator-groups/' + groupId, _fresh);
        _renderMembersList(detail);
    } catch (e) {
        document.getElementById('igMembersList').innerHTML =
            '<div style="color:var(--accent-red);font-size:0.8rem;padding:0.5rem;">' + esc(_errText(e)) + '</div>';
    }
    if (_pickerTree) igRenderTreePicker('igTreePicker2');
    else await _loadPickerTree();
}

export function closeMembersModal() {
    const modal = document.getElementById('igMembersModal');
    if (modal) modal.style.display = 'none';
    _membersGroupId = null;
    _membersChecked = {};
}

function _renderMembersList(detail) {
    const wrap = document.getElementById('igMembersList');
    if (!wrap) return;
    const members = (detail && detail.members) || [];
    if (!members.length) {
        wrap.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:0.8rem;font-size:0.82rem;">' + __('No members yet — add indicators below.') + '</div>';
        return;
    }
    const rows = members.map((m, i) =>
        '<tr style="border-bottom:1px solid var(--border-default);">' +
            '<td style="padding:0.25rem 0.4rem;color:var(--text-muted);font-size:0.72rem;width:2rem;">' + (i + 1) + '</td>' +
            '<td style="padding:0.25rem 0.4rem;font-size:0.78rem;direction:ltr;text-align:left;"><code style="color:var(--accent-blue);">' + esc(m.indicator_code) + '</code></td>' +
            '<td style="padding:0.25rem 0.4rem;font-size:0.8rem;color:var(--text-primary);">' + esc(m.indicator_name) + '</td>' +
            '<td style="padding:0.25rem 0.4rem;text-align:left;white-space:nowrap;">' +
                '<button class="btn btn-sm btn-outline" data-requires="settings.write" title="Move up" onclick="igMoveMember(' + detail.id + ', ' + m.indicator_id + ', -1)" style="font-size:0.68rem;padding:0.1rem 0.4rem;">▲</button>' +
                '<button class="btn btn-sm btn-outline" data-requires="settings.write" title="Move down" onclick="igMoveMember(' + detail.id + ', ' + m.indicator_id + ', 1)" style="font-size:0.68rem;padding:0.1rem 0.4rem;">▼</button>' +
                '<button class="btn btn-sm btn-outline" data-requires="settings.write" title="Remove from group" onclick="igRemoveMember(' + detail.id + ', ' + m.indicator_id + ')" style="font-size:0.68rem;padding:0.1rem 0.4rem;color:var(--accent-red);border-color:var(--accent-red);">✕</button>' +
            '</td>' +
        '</tr>'
    ).join('');
    wrap.innerHTML =
        '<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;">' +
        '<thead><tr style="font-size:0.7rem;color:var(--text-muted);">' +
            '<th style="padding:0.25rem 0.4rem;text-align:left;">#</th>' +
            '<th style="padding:0.25rem 0.4rem;text-align:left;">' + __('Code') + '</th>' +
            '<th style="padding:0.25rem 0.4rem;text-align:left;">' + __('Indicator') + '</th>' +
            '<th style="padding:0.25rem 0.4rem;"></th>' +
        '</tr></thead><tbody>' + rows + '</tbody></table></div>';
    _syncPermissionUI();
}

export async function igRemoveMember(groupId, indicatorId) {
    try {
        await apiDelete('/indicator-groups/' + groupId + '/members/' + indicatorId);
        toastSuccess(__('Member removed'));
        const detail = await apiGet('/indicator-groups/' + groupId, _fresh);
        _renderMembersList(detail);
        _groups = await apiGet('/indicator-groups', _fresh);
        _renderGroups();
    } catch (e) {
        toastError(_errText(e));
    }
}

export async function igMoveMember(groupId, indicatorId, delta) {
    try {
        const detail = await apiGet('/indicator-groups/' + groupId, _fresh);
        const ids = (detail.members || []).map(m => m.indicator_id);
        const idx = ids.indexOf(indicatorId);
        const to = idx + delta;
        if (idx < 0 || to < 0 || to >= ids.length) return;
        ids.splice(to, 0, ids.splice(idx, 1)[0]);
        await apiPut('/indicator-groups/' + groupId + '/members/reorder', { indicator_ids: ids });
        const fresh = await apiGet('/indicator-groups/' + groupId, _fresh);
        _renderMembersList(fresh);
    } catch (e) {
        toastError(_errText(e));
    }
}

export async function igAddCheckedMembers() {
    if (!_membersGroupId) return;
    const ids = Object.keys(_membersChecked).filter(k => _membersChecked[k]).map(Number);
    if (!ids.length) {
        toastError(__('Select at least one indicator to add.'));
        return;
    }
    try {
        await apiPostJSON('/indicator-groups/' + _membersGroupId + '/members', { indicator_ids: ids });
        // Exclusive membership: the backend evicted these from other groups —
        // the group list (member counts) must be refreshed too.
        toastSuccess(__('Members added (removed from any other group)'));
        _membersChecked = {};
        const detail = await apiGet('/indicator-groups/' + _membersGroupId, _fresh);
        _renderMembersList(detail);
        if (_pickerTree) igRenderTreePicker('igTreePicker2');
        _groups = await apiGet('/indicator-groups', _fresh);
        _renderGroups();
    } catch (e) {
        toastError(_errText(e));
    }
}

// ── Indicator tree picker (shared by both modals) ────────────────────
// Each control does exactly one thing:
//   checkbox = THAT indicator only (parents are real indicators too —
//              e.g. code 10 with sub-indicators 10.a/10.b)
//   ⤵N chip  = all N sub-indicators WITHOUT the parent
// Whole branch = both controls. Pure category headers (no own
// indicator_id) have no chip; their checkbox covers the subtree.

function _collectIds(node, out) {
    if (!node) return out;
    if (node.indicator_id != null) out.push(node.indicator_id);
    (node.children || []).forEach(ch => _collectIds(ch, out));
    return out;
}

function _treeMatches(node, q) {
    if (!q) return true;
    const hay = ((node.name || '') + ' ' + (node.code || '')).toLowerCase();
    if (hay.indexOf(q) !== -1) return true;
    return (node.children || []).some(ch => _treeMatches(ch, q));
}

function _pickerHtml(nodes, q, checked, depth) {
    if (!nodes || !nodes.length) return '';
    return nodes.filter(n => _treeMatches(n, q)).map(n => {
        const hasChildren = (n.children || []).length > 0;
        // Category nodes can lack an indicator_id — key their expansion
        // state by name so sibling groups don't share one '' bucket.
        const nodeKey = n.indicator_id != null ? String(n.indicator_id) : 'n:' + (n.name || '');
        const isOpen = depth === 0 || !!q || _pickerExpanded[nodeKey];
        const selfId = n.indicator_id != null ? n.indicator_id : null;
        const branchIds = _collectIds(n, []);
        const someOn = branchIds.some(id => checked[id]);
        // Checkbox = THIS indicator only. Pure category nodes (no own
        // indicator_id) have nothing of their own to select, so their
        // checkbox covers the subtree.
        const ownIds = selfId != null ? [selfId] : branchIds;
        const allOn = ownIds.length > 0 && ownIds.every(id => checked[id]);
        const checkbox = ownIds.length
            ? '<input type="checkbox" data-ig-ids="' + ownIds.join(',') + '"' + (allOn ? ' checked' : '') + ' style="accent-color:var(--accent-blue);cursor:pointer;margin-inline-end:0.35rem;">'
            : '<span style="display:inline-block;width:1rem;"></span>';
        // ⤵N selects the DESCENDANTS only — the parent has its own checkbox,
        // so children-without-parent is one click and parent+children is two.
        const childIds = selfId != null ? branchIds.filter(id => id !== selfId) : [];
        const branchBtn = childIds.length
            ? ' <span class="tree-pick-branch" data-ig-branch="' + childIds.join(',') + '" title="' + __('Select all sub-indicators without this one') + ' (' + childIds.length + ')">⤵' + childIds.length + '</span>'
            : '';
        let html = '<div style="margin-inline-start:' + (depth * 1.1) + 'rem;padding:0.12rem 0;' + (someOn && !allOn ? 'font-weight:600;' : '') + '">' +
            checkbox +
            (hasChildren
                ? '<span data-ig-toggle="' + esc(nodeKey) + '" style="cursor:pointer;display:inline-block;width:1rem;color:var(--text-muted);">' + (isOpen ? '▾' : '▸') + '</span> '
                : '<span style="display:inline-block;width:1rem;"></span>') +
            '<span style="color:' + (hasChildren ? 'var(--accent-purple)' : 'var(--text-primary)') + ';">' + esc(n.name || ('#' + n.indicator_id)) + '</span>' +
            (n.code ? ' <code style="font-size:0.68rem;color:var(--text-muted);direction:ltr;">' + esc(n.code) + '</code>' : '') +
            (n.unit ? ' <span style="font-size:0.68rem;color:var(--text-muted);">(' + esc(n.unit) + ')</span>' : '') +
            branchBtn +
            '</div>';
        if (hasChildren && isOpen) {
            html += _pickerHtml(n.children, q, checked, depth + 1);
        }
        return html;
    }).join('');
}

// which: 'igTreePicker' (editor modal) or 'igTreePicker2' (members modal)
export function igRenderTreePicker(which) {
    const box = document.getElementById(which || 'igTreePicker');
    if (!box) return;
    if (!_pickerTree) { _loadPickerTree(); return; }
    const isMembers = box.id === 'igTreePicker2';
    const checked = isMembers ? _membersChecked : _pickerChecked;
    const qEl = document.getElementById('igTreeSearch');
    const q = (!isMembers && qEl ? qEl.value.trim().toLowerCase() : '');
    const roots = (_pickerTree && _pickerTree.children) || [];
    box.innerHTML = _pickerHtml(roots, q, checked, 0) ||
        '<div style="text-align:center;color:var(--text-muted);padding:1rem;">' + __('No indicators match') + '</div>';
    box.querySelectorAll('input[type="checkbox"][data-ig-ids]').forEach(cb => {
        cb.addEventListener('change', function () {
            this.dataset.igIds.split(',').forEach(id => { checked[Number(id)] = this.checked; });
            igRenderTreePicker(box.id);
        });
    });
    box.querySelectorAll('[data-ig-branch]').forEach(btn => {
        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            this.dataset.igBranch.split(',').forEach(id => { checked[Number(id)] = true; });
            igRenderTreePicker(box.id);
        });
    });
    box.querySelectorAll('[data-ig-toggle]').forEach(sp => {
        sp.addEventListener('click', function () {
            const id = this.dataset.igToggle;
            _pickerExpanded[id] = !_pickerExpanded[id];
            igRenderTreePicker(box.id);
        });
    });
    if (isMembers) {
        const g = _groups.find(x => x.id === _membersGroupId);
        const cnt = Object.keys(checked).filter(k => checked[k]).length;
        box.dataset.checkedCount = cnt;
    } else {
        const cnt = Object.keys(_pickerChecked).filter(k => _pickerChecked[k]).length;
        const label = document.getElementById('igMembersCount');
        if (label) label.textContent = '— ' + cnt + ' ' + __('selected');
    }
}

export function igExpandAllPicker() {
    const roots = (_pickerTree && _pickerTree.children) || [];
    _collectIds({ children: roots }, []).forEach(id => { _pickerExpanded[id] = true; });
    igRenderTreePicker(_activePicker());
}

export function igCollapseAllPicker() {
    _pickerExpanded = {};
    igRenderTreePicker(_activePicker());
}

function _activePicker() {
    const m = document.getElementById('igMembersModal');
    return (m && m.style.display === 'flex') ? 'igTreePicker2' : 'igTreePicker';
}

export function igCheckVisible() {
    const isMembers = _activePicker() === 'igTreePicker2';
    const checked = isMembers ? _membersChecked : _pickerChecked;
    const box = document.getElementById(_activePicker());
    box.querySelectorAll('input[type="checkbox"][data-ig-ids]').forEach(cb => {
        cb.dataset.igIds.split(',').forEach(id => { checked[Number(id)] = true; });
    });
    igRenderTreePicker(_activePicker());
}

export function igUncheckAll() {
    const isMembers = _activePicker() === 'igTreePicker2';
    if (isMembers) _membersChecked = {};
    else _pickerChecked = {};
    igRenderTreePicker(_activePicker());
}

// ── Impact preview (dry run) ─────────────────────────────────────────
// Fetches the server's dry-run for BOTH target states and renders them
// side by side. Nothing is written until the user clicks Enable/Disable All.

export async function igPreviewImpact(groupId) {
    _closeOtherModals('igImpactModal');
    const modal = document.getElementById('igImpactModal');
    const body = document.getElementById('igImpactBody');
    if (!modal || !body) return;
    body.innerHTML = '<div style="text-align:center;padding:1.2rem;color:var(--text-muted);"><span class="spinner"></span> <span style="font-size:0.8rem;">' + __('Calculating impact…') + '</span></div>';
    modal.style.display = 'flex';
    try {
        const [off, on] = await Promise.all([
            apiGet('/indicator-groups/' + groupId + '/impact?enabled=false', _fresh),
            apiGet('/indicator-groups/' + groupId + '/impact?enabled=true', _fresh),
        ]);
        _renderImpact(off, on);
    } catch (e) {
        body.innerHTML = '<div style="color:var(--accent-red);font-size:0.8rem;padding:0.8rem;">' + esc(_errText(e)) + '</div>';
    }
}

export function closeImpactModal() {
    const modal = document.getElementById('igImpactModal');
    if (modal) modal.style.display = 'none';
}

function _impactRow(label, val) {
    return '<tr><td style="padding:0.15rem 0;color:var(--text-muted);">' + label + '</td>' +
        '<td style="padding:0.15rem 0;text-align:left;font-weight:600;color:var(--text-primary);direction:ltr;">' + val + '</td></tr>';
}

function _impactCard(d, title, color) {
    const row = _impactRow;
    const rules = (d.rule_impact && d.rule_impact.length)
        ? d.rule_impact.map(r => '<code style="font-size:0.68rem;color:var(--accent-blue);direction:ltr;">' + esc(r.rule_code) + '</code>').join(' ')
        : '<span style="color:var(--text-muted);">' + __('none') + '</span>';
    const c = d.completeness || {};
    let denom = '—';
    if (c.sum_before != null && c.sum_after != null) {
        const delta = c.sum_after - c.sum_before;
        denom = c.sum_before + ' → ' + c.sum_after +
            (delta !== 0 ? ' (' + (delta > 0 ? '+' : '') + delta + ')' : '');
    }
    const changing = (d.changing_indicators || []).map(cd => '<code style="font-size:0.68rem;color:var(--text-secondary);direction:ltr;">' + esc(cd) + '</code>').join(' ') || '—';
    return '<div class="card" style="flex:1;min-width:270px;padding:0.7rem 0.9rem;border-top:3px solid ' + color + ';">' +
        '<div style="font-weight:700;font-size:0.85rem;color:var(--text-primary);margin-bottom:0.35rem;">' + title + '</div>' +
        '<table style="width:100%;font-size:0.76rem;border-collapse:collapse;">' +
            row(__('Hospitals affected'), d.hospitals_affected) +
            row(__('Config rows to write'), d.config_rows_to_write) +
            row(__('Months'), esc(d.months_note || '')) +
            row(__('Completeness denominator'), denom) +
        '</table>' +
        '<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:0.45rem;">' + __('Indicators that would change') + ': ' + changing + '</div>' +
        '<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:0.3rem;">' + __('Rules that would stop evaluating') + ': ' + rules + '</div>' +
    '</div>';
}

function _renderImpact(off, on) {
    const body = document.getElementById('igImpactBody');
    const g = _groups.find(x => x.id === off.group_id);
    body.innerHTML =
        '<div style="font-size:0.82rem;color:var(--text-secondary);margin-bottom:0.6rem;">' +
            __('Group') + ': <strong>' + esc(off.group_name) + '</strong> — ' + off.members + ' ' + __('members') + '. ' +
            __('Dry run — nothing is saved until you click Enable All or Disable All.') +
        '</div>' +
        '<div style="display:flex;gap:0.6rem;flex-wrap:wrap;">' +
            _impactCard(off, __('If DISABLED'), 'var(--accent-red)') +
            _impactCard(on, __('If ENABLED'), 'var(--accent-green)') +
        '</div>' +
        '<div style="font-size:0.72rem;color:var(--text-muted);margin-top:0.6rem;">ℹ️ ' + esc(off.note || '') + '</div>' +
        '<div style="display:flex;justify-content:flex-end;gap:0.5rem;margin-top:0.8rem;">' +
            '<button class="btn btn-sm btn-outline" onclick="closeImpactModal()">' + __('Close') + '</button>' +
            '<button class="btn btn-sm" data-requires="settings.write" onclick="igToggleGroup(' + off.group_id + ', false); closeImpactModal()" style="background:var(--accent-red);color:#fff;">' + __('Disable All') + '</button>' +
            '<button class="btn btn-sm" data-requires="settings.write" onclick="igToggleGroup(' + off.group_id + ', true); closeImpactModal()" style="background:var(--accent-green);color:#fff;">' + __('Enable All') + '</button>' +
        '</div>';
    _syncPermissionUI();
}

// ── Shared helpers ───────────────────────────────────────────────────

function _errText(err) {
    // apiPut/apiPostJSON surface FastAPI {"detail": ...} bodies in .message
    const raw = String((err && err.message) || err || '');
    try {
        const m = raw.match(/HTTP \d+: (.*)$/s);
        if (m) {
            const parsed = JSON.parse(m[1]);
            if (parsed && parsed.detail) {
                const d = parsed.detail;
                return typeof d === 'string' ? d : JSON.stringify(d);
            }
        }
    } catch (e) { /* not JSON — use raw */ }
    return raw;
}
