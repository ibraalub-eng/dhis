import { apiGet, apiPostJSON } from './api.js';
import { __, currentLang } from './i18n.js';
import { esc } from './tree.js';
import { confirmAction } from './confirm-modal.js';

// ── Quality Alerts screen ───────────────────────────────────────────────
// Every number rendered here was computed server-side by the shared engine
// (app/engine/quality_alerts.py) from the Indicators Registry's authoritative
// calculations. This module only fetches, filters and displays — it never
// computes a rate or embeds an indicator formula.

const PAGE_SIZE = 25;
// The screen opens on the Very High band, as it always has, but the band is no
// longer pinned: the Severity dropdown widens the list to a lower band or to
// every severity. Detection has always recorded all severities server-side;
// this only decides which of them the list, its KPIs and its pager are scoped
// to.
const _DEFAULT_SEVERITY = 'VERY_HIGH';
// The list is an OPEN-alert view: a finding a reviewer closed (Resolved /
// False Positive) leaves it. This sentinel is the explicit "show closed too"
// choice in the Status filter — it sends include_closed, not a status value.
const _ALL_STATUSES = '__all__';
const _state = {
    inited: false,
    page: 1,
    pageSize: PAGE_SIZE,      // rows per page; 0 = every matching issue
    // Very High split, as chosen by clicking one of the two KPI cards:
    // null = both, 'only' = every fired perspective Very High, 'mixed' = a
    // Very High perspective beside a lower band.
    vhScope: null,
    // One evidence-breakdown category, as chosen by clicking a cell: the five
    // categories partition Very High only, so a cell lists exactly the issues
    // it counted. null = no category filter.
    comparisonCategory: null,
    perspectives: new Set(),   // multi-select chips; empty = all
    meta: null,
    issues: [],
    issuesTotal: 0,           // grouped issues matching the filters (pager unit)
    summary: null,
};

// ── One vocabulary ─────────────────────────────────────────────────────
// The API speaks in codes; the screen speaks in one label per code, always
// through the same helper. Printing the raw band in a table cell beside a
// translated "Very High" in the filter made one severity look like two, and
// left the Arabic screen with English statuses and perspective names.
const _SEVERITY_LABELS = {
    VERY_HIGH: 'Very High',
    HIGH: 'High',
    MODERATE: 'Moderate',
    LOW: 'Low',
};
// The engine's perspective keys, for rows that arrive without their label.
const _PERSPECTIVE_KEYS = {
    history: 'Hospital history',
    type: 'Similar hospitals (type)',
    ownership: 'Ownership peers',
    facility_type: 'Facility-type peers',
    governorate: 'Regional peers (governorate)',
    all: 'All hospitals',
};

function _severityLabel(band) {
    return band ? __(_SEVERITY_LABELS[band] || band) : '';
}

// Statuses are stored English workflow names; the dictionary supplies the
// Arabic form, and an unknown status still shows itself.
function _statusLabel(status) {
    return status ? __(status) : '';
}

function _perspectiveLabel(label, key) {
    // The trend payload composes "<perspective label> — mean"; translating the
    // head and keeping the suffix avoids a half-English legend.
    const tail = ' — mean';
    const text = label || _PERSPECTIVE_KEYS[key] || key || '';
    if (text.endsWith(tail)) return __(text.slice(0, -tail.length)) + ' — ' + __('mean');
    return __(text);
}

const _SEVERITY_BADGES = {
    VERY_HIGH: 'badge badge-critical',
    HIGH: 'badge badge-high',
    MODERATE: 'badge badge-medium',
    LOW: 'badge badge-low',
};
const _STATUS_TONE = {
    'New': 'badge-medium',
    'Under Review': 'badge-low',
    'Confirmed Issue': 'badge-critical',
    'False Positive': 'badge-muted',
    'Resolved': 'badge-pass',
};
const _INTERP_ICONS = {
    high_is_concern: '🔺',
    high_is_favorable: '✅',
    low_is_concern: '🔻',
    low_is_favorable: '✅',
    outside_target_range: '🎯',
    within_target_range: '🎯',
    statistical_only: '📊',
};

function _fmtValue(v, unit) {
    if (v === null || v === undefined) return '--';
    const n = Number(v);
    if (!Number.isFinite(n)) return '--';
    // Precision follows magnitude: 2,616 counts and 64.3% rates both read
    // cleanly without showing meaningless trailing zeros.
    const abs = Math.abs(n);
    const digits = abs >= 100 ? 0 : (abs >= 10 ? 1 : 2);
    return n.toLocaleString('en-US', {
        minimumFractionDigits: digits, maximumFractionDigits: digits,
    }) + _unitSuffix(unit);
}

function _fmtPct(v) {
    if (v === null || v === undefined) return '--';
    return (v >= 0 ? '+' : '') + Number(v).toFixed(1) + '%';
}

function _fmtDate(iso) {
    if (!iso) return '--';
    return String(iso).slice(0, 10);
}

// Degenerate comparison: every value in the group was identical, so the
// baseline is simply the level everyone reported (very often 0) and the
// deviation has no measurable scale. The row is still a finding, but its level
// is capped at HIGH — this badge says why, so a bare 0 cannot be read as a
// measured baseline or as broken arithmetic.
function _zeroSpreadBadge() {
    return ' <span class="badge badge-medium" style="font-size:0.62rem;padding:0 4px;" title="' +
        esc(__('The comparison has no measurable spread for the method used, so the deviation cannot be graded. The finding is kept and its level is capped at HIGH.')) +
        '">' + __('no spread') + '</span>';
}

// Why a comparison cannot be graded. A z/mad/iqr method divides by its own
// spread, and MAD or IQR can be zero while the values still differ — so "the
// group has no spread" is only said when that is literally true.
function _spreadNote(a, stats) {
    if (!a.zero_spread) return '';
    if (stats && Number(stats.std) === 0) return __('Comparison group has no spread');
    return __('No measurable spread for this method');
}

// ── Filter query string ────────────────────────────────────────────────
function _selectedSeverity() {
    const el = document.getElementById('qaSeverityFilter');
    // Missing element = an older fragment: keep the historical Very-High-only scope.
    return el ? el.value : _DEFAULT_SEVERITY;
}

function _skipsLowConfidence() {
    const el = document.getElementById('qaSkipLowConfidence');
    return !!(el && el.checked);
}

function _statusFilterOptions(meta) {
    const statuses = ((meta && meta.statuses) || [])
        .map(s => ({ value: s, label: _statusLabel(s) }));
    // Closed rows are reachable, just not by default: one row per status plus
    // one explicit "include the closed ones" choice.
    return statuses.concat([{ value: _ALL_STATUSES, label: __('All statuses (incl. closed)') }]);
}

function _filterQuery() {
    const p = new URLSearchParams();
    // Severity: empty means "all severities", which sends no severity param.
    const severity = _selectedSeverity();
    if (severity) p.set('severity', severity);
    // Status: no selection keeps the open scope (Resolved / False Positive
    // excluded server-side); one status shows exactly those rows; the "all
    // statuses" choice asks the server to include closed ones as well.
    // The two are mutually exclusive BY CONSTRUCTION: asking for one status
    // and for the closed ones together would be contradictory (the server
    // lets the status win), and the sentinel never travels as a status value
    // because it is not one.
    const statusEl = document.getElementById('qaStatusFilter');
    if (statusEl && statusEl.value === _ALL_STATUSES) p.set('include_closed', '1');
    else if (statusEl && statusEl.value) p.set('status', statusEl.value);
    // Low confidence = small comparison group or ML cross-check disagreement.
    // Applied server-side so the KPIs and the pager count exactly the rows the
    // table lists.
    if (_skipsLowConfidence()) p.set('confidence', 'high');
    const pairs = [
        ['month', 'qaMonthFilter'], ['hospital_id', 'qaHospitalFilter'],
        ['indicator', 'qaIndicatorFilter'],
        ['indicator_type', 'qaIndicatorTypeFilter'],
        ['ownership_id', 'qaOwnershipFilter'],
        ['governorate_id', 'qaGovernorateFilter'],
        ['hospital_type_id', 'qaTypeFilter'],
    ];
    pairs.forEach(([param, id]) => {
        const el = document.getElementById(id);
        if (el && el.value) p.set(param, el.value);
    });
    const search = document.getElementById('qaSearchFilter');
    if (search && search.value.trim()) p.set('q', search.value.trim());
    // Chosen on the two Very High cards; the server grades each issue from its
    // whole evidence, so this narrows the list to exactly the card's number.
    if (_state.vhScope) p.set('very_high_scope', _state.vhScope);
    // Chosen on the evidence-breakdown cells: the server narrows the list to
    // the Very High only issues that cell counted, so the table and the cell
    // always describe the same population.
    if (_state.comparisonCategory) p.set('comparison_category', _state.comparisonCategory);
    // Every selected chip is sent, as repeated parameters the server ORs, so
    // the KPIs, the total and every page describe the whole filtered
    // population instead of whichever page happened to load.
    [..._state.perspectives].forEach(key => p.append('perspective', key));
    return p.toString();
}

// ── Options population ─────────────────────────────────────────────────
function _fillSelect(id, items, placeholder) {
    const sel = document.getElementById(id);
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = '<option value="">' + (placeholder || 'All') + '</option>' +
        items.map(it => '<option value="' + esc(it.value) + '">' + esc(it.label) + '</option>').join('');
    sel.value = prev && items.some(i => String(i.value) === prev) ? prev : '';
}

async function _loadOptions() {
    const safe = (promise, fallback) => promise.catch(() => fallback);
    const [monthsR, hospitalsR, indicatorsR, metaR, ownersR, govR, typesR] = await Promise.all([
        safe(apiGet('/analysis/months'), { months: [] }),
        safe(apiGet('/hospitals/'), []),
        // NO status filter here: raw data elements carry status "catalog" in
        // the indicators catalog, so ?status=active collapsed this dropdown to
        // the Derivative Indicator type only. Fetch the full catalog and
        // deactivate-aware filter client-side instead.
        safe(apiGet('/indicators'), { items: [] }),
        safe(apiGet('/quality-alerts/meta'), null),
        safe(apiGet('/facility-ownerships/'), []),
        safe(apiGet('/governorates/'), []),
        safe(apiGet('/hospital-types/'), []),
    ]);
    const months = (monthsR.months || monthsR || []).filter(m => /^\d{4}-\d{2}$/.test(String(m)));
    _fillSelect('qaMonthFilter', months.map(m => ({ value: m, label: m })));
    const hospitals = hospitalsR.value || hospitalsR || [];
    _fillSelect('qaHospitalFilter', hospitals.map(h => ({ value: h.id, label: h.name })));
    // Every indicator type the scanner covers (both Data Elements and
    // Derivative Indicators) — QualityAlert rows exist for both kinds. Only
    // registry rows users deactivated (status "inactive") are hidden: they no
    // longer produce new alerts.
    const indicatorItems = (indicatorsR.items || indicatorsR || [])
        .filter(i => i.code && (i.status === 'active' || i.status === 'catalog'));
    const seenCodes = new Set();
    _fillSelect('qaIndicatorFilter', indicatorItems
        .filter(i => !seenCodes.has(i.code) && seenCodes.add(i.code))
        .map(i => ({
            value: i.code,
            label: (i.name || i.code) + ' (' + i.code + ') · ' + (i.category || i.kind || '')
        }))
        .sort((a, b) => a.label.localeCompare(b.label)));
    _fillSelect('qaOwnershipFilter', (ownersR.value || ownersR || []).map(o => ({ value: o.id, label: o.name })));
    _fillSelect('qaGovernorateFilter', (govR.value || govR || []).map(g => ({ value: g.id, label: g.name })));
    _fillSelect('qaTypeFilter', (typesR.value || typesR || []).map(t => ({ value: t.id, label: t.name })));
    _state.meta = metaR;
    if (metaR) {
        _fillSelect('qaStatusFilter', _statusFilterOptions(metaR), __('Open only'));
        _renderPerspectiveChips(metaR.perspectives || []);
    }
}

// ── Perspective chips ──────────────────────────────────────────────────
function _renderPerspectiveChips(perspectives) {
    const wrap = document.getElementById('qaPerspectiveChips');
    if (!wrap) return;
    wrap.innerHTML = perspectives.map(p => {
        const selectable = p.available !== false;
        return '<button data-perspective="' + esc(p.key) + '"' +
            ' data-label="' + esc(p.label || '') + '" ' +
            (selectable ? 'onclick="qualityAlertsTogglePerspective(this)"' : 'disabled title="' + esc(p.unavailable_reason || '') + '"') +
            ' class="badge ' + (selectable ? 'badge-muted' : 'badge-muted" style="opacity:0.45') +
            '" style="cursor:' + (selectable ? 'pointer' : 'not-allowed') + ';font-size:0.7rem;">' +
            '<span class="qa-chip-label">' + esc(_perspectiveLabel(p.label, p.key)) + '</span>' +
            (p.available === false ? ' — ' + esc(__('not configured')) : '') + '</button>';
    }).join('');
    const note = document.getElementById('qaPerspectiveNote');
    if (note) {
        const missing = perspectives.filter(p => p.available === false);
        note.textContent = missing.length
            ? missing.map(p => _perspectiveLabel(p.label, p.key) + ': ' + (p.unavailable_reason || '')).join(' · ')
            : '';
    }
}

export function qualityAlertsTogglePerspective(btn) {
    const key = btn.getAttribute('data-perspective');
    if (!key) return;
    if (_state.perspectives.has(key)) _state.perspectives.delete(key);
    else _state.perspectives.add(key);
    btn.classList.toggle('badge-high', _state.perspectives.has(key));
    btn.classList.toggle('badge-muted', !_state.perspectives.has(key));
    _state.page = 1;
    loadQualityAlerts();
}

// ── Data loading ───────────────────────────────────────────────────────
function _renderScopeNote() {
    // The "only Very High" explanation is true only while the list really is
    // Very-High-only; the dropdown itself states the scope otherwise.
    const note = document.getElementById('qaScopeNote');
    if (note) note.style.display = _selectedSeverity() === 'VERY_HIGH' ? '' : 'none';
}

export function qualityAlertsFilterChanged() {
    _state.page = 1;
    // Severity and the card scope INTERSECT (D4). Changing the band keeps the
    // card the operator chose: clearing it here made the pair unreachable and
    // silently discarded a filter the screen still showed as active. An empty
    // intersection is explained by the empty state instead.
    _renderScopeNote();
    loadQualityAlerts();
}

// The two Very High cards are filters, not just numbers: clicking one lists
// exactly the issues it counts, and clicking the active card clears it.
export function qualityAlertsToggleVeryHighScope(scope) {
    _state.vhScope = _state.vhScope === scope ? null : scope;
    _state.page = 1;
    // The card narrows the list ON TOP OF the band (D4): it no longer moves the
    // Severity dropdown, because a selection the operator made must not change
    // under them. The pair may legitimately be empty; the empty state says so
    // while the cards keep their own numbers.
    _renderScopeNote();
    loadQualityAlerts();
}

// One evidence-breakdown cell at a time, like the Very High cards: the five
// categories are mutually exclusive, so choosing a second replaces the first
// and clicking the active cell clears it. The cell numbers keep describing the
// whole Very High population, so the clicked cell never drops to its own
// filtered count under the cursor.
export function qualityAlertsToggleComparisonCategory(category) {
    _state.comparisonCategory =
        _state.comparisonCategory === category ? null : category;
    _state.page = 1;
    loadQualityAlerts();
}

let _searchTimer = null;
export function qualityAlertsFilterChangedDebounced() {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => { _state.page = 1; loadQualityAlerts(); }, 350);
}

export function qualityAlertsPage(delta) {
    const next = _state.page + delta;
    if (next < 1) return;
    _state.page = next;
    loadQualityAlerts();
}

// Page sizes the selector offers, in order. 0 is the API's "every matching
// issue" mode (see app/api/quality_alerts.py), shown as "All".
const _PAGE_SIZES = [25, 50, 100, 0];

export function qualityAlertsPageSizeChanged(size) {
    const value = Number(size);
    // Anything unrecognised falls back to the default rather than producing a
    // page size the API would reject.
    _state.pageSize = _PAGE_SIZES.includes(value) ? value : PAGE_SIZE;
    // Row count changes what page 3 means, so the list restarts at the top.
    _state.page = 1;
    loadQualityAlerts();
}

function _pageSize() {
    return _state.pageSize;
}

export async function loadQualityAlerts() {
    _renderScopeNote();
    const loading = document.getElementById('qaLoading');
    if (loading) loading.classList.remove('hidden');
    try {
        const qs = _filterQuery();
        const [summary, issues] = await Promise.all([
            apiGet('/quality-alerts/summary' + (qs ? '?' + qs : '')),
            apiGet('/quality-alerts/issues?' + qs +
                (qs ? '&' : '') + 'page=' + _state.page + '&page_size=' + _pageSize() +
                '&sort=severity&order=desc'),
        ]);
        _state.summary = summary;
        _state.issues = issues.items || [];
        // The table lists grouped issues, so the pager must count issues too.
        // `summary.total_active` counts perspective rows and is never a page unit.
        _state.issuesTotal = issues.total ?? _state.issues.length;
        _renderKpis(summary);
        _updateChipCounts(summary);
        _renderTable();
    } catch (err) {
        const body = document.getElementById('qaTableBody');
        if (body) {
            body.innerHTML = '<tr><td colspan="11" style="color:var(--accent-red);padding:1rem;">' +
                __('Error: ') + esc(err && err.message ? err.message : __('error')) + '</td></tr>';
        }
    } finally {
        if (loading) loading.classList.add('hidden');
    }
}

// ── Very High only: evidence breakdown (Step 10D-6e) ────────────────────
// Five MUTUALLY EXCLUSIVE categories partition "Very High only" by the
// comparison each issue actually made (the server's identity classification).
// Relationship detail is secondary and describes only the multiple-peer
// bucket: it is never added to an issue total. Every number printed here is
// the server's. When a balance fails the discrepancy is printed with both
// stored figures — nothing is re-added, smoothed or corrected in the browser.
// A cell is also a FILTER: clicking one lists exactly the issues it counted.
const _COMPARISON_CATEGORY_ROWS = [
    ['qaKpiMultiplePeer', 'very_high_multiple_peer_issues',
     'Multiple peer comparisons',
     'Two or more distinct groups of hospitals were compared', 'multiple_peer'],
    ['qaKpiSinglePeer', 'very_high_single_peer_issues',
     'Single peer comparison',
     'Exactly one group of hospitals was compared, so nothing else could agree or disagree', 'single_peer'],
    ['qaKpiTemporalOnly', 'very_high_temporal_only_issues',
     'Temporal-only',
     "No peer group was used; the value was compared with the hospital's own earlier months", 'temporal_only'],
    ['qaKpiUnknownIdentity', 'very_high_unknown_identity_issues',
     'Unknown comparison identity',
     'The stored evidence does not say which hospitals were compared, so it is not counted as a peer comparison', 'unknown_identity'],
    ['qaKpiInvalidEvidence', 'very_high_invalid_evidence_issues',
     'Invalid evidence',
     'The stored comparison record is inconsistent and was not used', 'invalid_evidence'],
];

const _RELATIONSHIP_ROWS = [
    ['qaKpiRelDisjoint', 'all_disjoint', 'All disjoint',
     'No shared hospitals between the groups'],
    ['qaKpiRelNested', 'nested_only', 'Nested only',
     'One group is contained in the other'],
    ['qaKpiRelOverlapping', 'overlapping_only', 'Overlapping only',
     'The groups share hospitals without one containing the other'],
    ['qaKpiRelMixed', 'mixed_relationships', 'Mixed relationships',
     'More than one of the three relationships occurs'],
];

// A missing or null field is NOT zero: the API contract publishes these as
// counts, so an absent one means "not measured here" and prints as a dash.
function _countOrNull(value) {
    if (value === null || value === undefined || value === '') return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
}

function _countText(value) {
    if (value === null || value === undefined) return '\u2014';
    const n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString('en-US') : '\u2014';
}

function _fillSentence(text, values) {
    let out = __(text);
    Object.keys(values || {}).forEach(function (name) {
        out = out.split('{' + name + '}').join(String(values[name]));
    });
    return out;
}

function _categoryLabel(category) {
    if (!category) return '';
    const row = _COMPARISON_CATEGORY_ROWS.find(r => r[4] === category);
    return row ? __(row[2]) : category;
}

function _breakdownNote(text, warn, numeric) {
    return '<div' + (numeric ? ' dir="ltr"' : ' dir="auto"') +
        ' style="font-size:0.66rem;line-height:1.5;margin-top:0.25rem;overflow-wrap:anywhere;color:' +
        (warn ? 'var(--accent-orange,#b45309)' : 'var(--text-muted)') + ';">' +
        esc(text) + '</div>';
}

// Tooltip text lives in a hidden node referenced by aria-describedby: title=
// is invisible to keyboard and touch users, and pairing it with a description
// would announce the same sentence twice.
let _tipSeq = 0;
function _tipHelp(text) {
    const id = 'qaTipHelp' + (++_tipSeq);
    return {describedby: ' aria-describedby="' + id + '"',
            html: '<span class="qa-tip-help" id="' + id + '" role="tooltip">' +
                esc(text) + '</span>'};
}

// A prose line with no figures: it inherits the page direction, so the Arabic
// sentence reads RTL while the equation below it stays LTR.
function _breakdownSentence(text) {
    return '<div style="font-size:0.66rem;line-height:1.5;margin-top:0.25rem;overflow-wrap:anywhere;color:var(--text-muted);text-align:start;">' +
        esc(text) + '</div>';
}

function _breakdownCell(id, label, help, value, category) {
    // A cell is a FILTER when its category is known and the count was measured:
    // the five categories partition Very High only, so clicking one lists
    // exactly the issues it counted. The hint states that before the click and
    // the active cell states how to undo it.
    const selectable = Boolean(category) && value !== null;
    const active = selectable && _state.comparisonCategory === category;
    const hint = __(help) + ' — ' + (active
        ? __('click the cell again to clear') : __('click a cell to filter'));
    const tip = _tipHelp(hint);
    // A measured cell is a real <button>: it gets Enter/Space activation, focus
    // and the pressed state natively, so no role or keydown shim is needed. An
    // unmeasured cell stays a plain div and is never announced as a button that
    // does nothing.
    const tag = selectable ? 'button' : 'div';
    const attrs = (selectable
        ? ' aria-pressed="' + (active ? 'true' : 'false') + '"' +
          ' onclick="qualityAlertsToggleComparisonCategory(this.dataset.category)"' +
          ' data-category="' + esc(category) + '"'
        : '');
    return '<' + tag + (selectable ? ' type="button"' : '') +
        ' class="qa-tip' + (selectable ? ' qa-breakdown-cell' : '') +
        (active ? ' is-active' : '') + '" tabindex="0"' + attrs + tip.describedby +
        ' style="padding:0.3rem 0.45rem;background:var(--bg-elevated,#f7f7f7);border:0;border-left:2px solid var(--accent-red,#c62828);border-radius:0 4px 4px 0;min-width:0;' +
        (selectable ? 'display:block;width:100%;appearance:none;font:inherit;color:inherit;text-align:start;cursor:pointer;' : '') + '">' +
        '<span style="display:block;font-size:0.64rem;color:var(--text-muted);line-height:1.35;overflow-wrap:anywhere;">' + esc(__(label)) + '</span>' +
        '<span id="' + id + '" dir="ltr" style="display:block;font-size:0.95rem;font-weight:700;text-align:start;">' + _countText(value) + '</span>' +
        tip.html + '</' + tag + '>';
}

function _relationshipHtml(shadow, multiplePeers) {
    const byRelationship = shadow && shadow.multiple_peer_by_relationship;
    let html = '<div style="margin-top:0.45rem;padding-top:0.35rem;border-top:1px dashed var(--border-default);">' +
        '<div style="font-size:0.72rem;font-weight:700;overflow-wrap:anywhere;">' +
        esc(__('Comparison relationships (inside multiple peer comparisons)')) + '</div>' +
        '<div style="font-size:0.64rem;color:var(--text-muted);overflow-wrap:anywhere;">' +
        esc(__('Secondary detail — these are not additional issues')) + '</div>';
    if (!byRelationship || typeof byRelationship !== 'object') {
        html += _breakdownNote(__('Relationship detail unavailable'), true);
        return html + '</div>';
    }
    let sum = 0;
    let complete = true;
    let chips = '';
    _RELATIONSHIP_ROWS.forEach(function (row) {
        const value = _countOrNull(byRelationship[row[1]]);
        if (value === null) complete = false;
        else sum += value;
        const tip = _tipHelp(__(row[3]));
        chips += '<span class="qa-tip badge badge-muted" tabindex="0"' + tip.describedby +
            ' style="font-size:0.64rem;padding:0 5px;white-space:nowrap;">' +
            esc(__(row[2])) + ': <b id="' + row[0] + '" dir="ltr">' +
            _countText(value) + '</b>' + tip.html + '</span>';
    });
    html += '<div style="display:flex;flex-wrap:wrap;gap:0.3rem;margin-top:0.25rem;">' + chips + '</div>';
    if (complete && multiplePeers !== null && sum !== multiplePeers) {
        html += _breakdownNote(_fillSentence(
            'Relationship counts add up to {sum} but Multiple peer comparisons is {count} (difference {diff}). The stored counts are shown unchanged; nothing was adjusted.',
            {sum: sum.toLocaleString('en-US'),
             count: multiplePeers.toLocaleString('en-US'),
             diff: Math.abs(sum - multiplePeers).toLocaleString('en-US')}), true);
    }
    return html + '</div>';
}

function _comparisonBreakdownHtml(s) {
    const source = s || {};
    const total = _countOrNull(source.very_high_only_issues);
    const categories = _COMPARISON_CATEGORY_ROWS.map(function (row) {
        return {id: row[0], label: row[2], help: row[3],
                value: _countOrNull(source[row[1]]), category: row[4]};
    });
    let html = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:0.4rem;">';
    categories.forEach(function (cell) {
        html += _breakdownCell(cell.id, cell.label, cell.help, cell.value,
                                 cell.category);
    });
    html += '</div>';

    if (categories.some(function (cell) { return cell.value === null; })) {
        // Nothing is added up from a partial set: the missing figure is named
        // and the partition line is withheld rather than shown as if complete.
        return html + _breakdownNote(
            __('Comparison evidence not available for this scope'), true);
    }

    const sum = categories.reduce(function (acc, cell) { return acc + cell.value; }, 0);
    const equation = categories.map(function (cell) {
        return _countText(cell.value);
    }).join(' + ') + ' = ' + _countText(total);
    html += _breakdownNote(equation, false, true);
    if (total !== null && sum !== total) {
        html += _breakdownNote(_fillSentence(
            'The categories add up to {sum} but Very High only is {total} (difference {diff}). The stored counts are shown unchanged; nothing was adjusted.',
            {sum: sum.toLocaleString('en-US'),
             total: total.toLocaleString('en-US'),
             diff: Math.abs(sum - total).toLocaleString('en-US')}), true);
    }

    const mixed = _countOrNull(source.mixed_severity_issues);
    const veryHigh = _countOrNull(source.very_high_issues);
    if (total !== null && mixed !== null) {
        const combined = total + mixed;
        // Sentence first (page direction, so Arabic is fully RTL), then the
        // figures alone in a forced-LTR line. Mixing Arabic label words with
        // digits in one node let bidi reorder 354 + 447 = 801 into 801 = ...
        html += _breakdownSentence(
            __('Very High only + Mixed severity = Very High issues'));
        html += _breakdownNote(total.toLocaleString('en-US') + ' + ' +
            mixed.toLocaleString('en-US') + ' = ' +
            combined.toLocaleString('en-US'), false, true);
        if (veryHigh !== null && combined !== veryHigh) {
            html += _breakdownNote(_fillSentence(
                'Very High only + Mixed severity ({sum}) does not match Very High issues ({total}); difference {diff}. The stored counts are shown unchanged; nothing was adjusted.',
                {sum: combined.toLocaleString('en-US'),
                 total: veryHigh.toLocaleString('en-US'),
                 diff: Math.abs(combined - veryHigh).toLocaleString('en-US')}), true);
        }
    }

    html += _relationshipHtml(source.very_high_comparison_shadow,
                              categories[0].value);
    return html;
}

function _renderComparisonBreakdown(s) {
    const el = document.getElementById('qaComparisonBreakdown');
    if (!el) return;
    el.innerHTML = _comparisonBreakdownHtml(s || {});
}

function _renderKpis(s) {
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    // Issue units: one card number per risk issue, matching the table's rows.
    // The row-level counts (total_active, very_high_rows…) count comparison
    // perspectives, so they would overstate every card and the page count.
    // One band, one name: summary.very_high_issues is the Very High issue
    // count the dashboard card also shows.
    // Very-High-only vs mixed describes the Very High findings of the SCOPE
    // (month, hospital, ownership, governorate, facility type, indicator,
    // confidence, search, status) — never of the selected band. Choosing HIGH
    // or MODERATE narrows the table and "Total issues" only; these cards keep
    // describing the Very High findings they are named for. Perspectives
    // narrow the table too, never the cards.
    set('qaKpiVeryHighOnly', s.very_high_only_issues ?? 0);
    // The part of that bucket two or more comparisons agreed on; a card of its
    // own, because "no lower band" alone also covers a single comparison
    // nothing could have disagreed with.
    set('qaKpiCorroborated', s.very_high_only_corroborated_issues ?? 0);
    set('qaKpiMixed', s.mixed_severity_issues ?? 0);
    set('qaKpiTotal', s.total_issues ?? 0);
    // Very High ISSUES: any issue with at least one Very High comparison,
    // the population Very High only + Mixed severity split. A missing field
    // renders as a dash, never as a measured zero.
    const veryHighIssues = _countOrNull(s.very_high_issues);
    set('qaKpiVeryHighIssues', veryHighIssues === null
        ? '\u2014' : veryHighIssues.toLocaleString('en-US'));
    set('qaKpiHospitals', s.hospitals_affected ?? 0);
    set('qaKpiIndicators', s.indicators_affected ?? 0);
    set('qaKpiNew', s.new_issues ?? 0);
    set('qaKpiUnresolved', s.unresolved_issues ?? 0);
    _renderComparisonBreakdown(s);
    _renderVeryHighOnlyBreakdown(s);
    _renderSeverityReconcile(s);
    _renderScopeCards();
}

// The "Very High only" card is a total, so it states the two parts it is made
// of instead of leaving a reader to guess: the issues two or more distinct
// comparisons agreed on (corroborated) and the issues where only one
// comparison fired, which are "Very High only" by default because nothing was
// compared against them. Both counts come from the server's own fitted bands
// and fired sets, so they add up exactly to the card's value; the shares come
// from the server too, so the pair always reads 100% and an empty scope reads
// 0 rather than a meaningless division.
function _renderVeryHighOnlyBreakdown(s) {
    const b = (s && s.very_high_only_breakdown) || {};
    const num = v => Number(v || 0);
    const n = v => num(v).toLocaleString('en-US');
    const pct = v => num(v).toFixed(1) + '%';
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    // Counts are the server's, never re-added here: it derives both subgroups
    // from the same fitted bands, so the pair is a partition of the card's
    // value and the browser must not "fix" a disagreement it cannot see.
    const total = num(b.total ?? (s && s.very_high_only_issues));
    const corroborated = num(b.corroborated ?? (s && s.very_high_only_corroborated_issues));
    const single = num(b.single_perspective ?? (s && s.very_high_single_perspective_issues));
    const corroboratedPct = b.corroborated_pct !== undefined
        ? num(b.corroborated_pct) : (total > 0 ? 100 * corroborated / total : 0);
    const singlePct = b.single_perspective_pct !== undefined
        ? num(b.single_perspective_pct) : (total > 0 ? 100 * single / total : 0);
    set('qaKpiOnlyCorroborated', n(corroborated));
    set('qaKpiOnlyCorroboratedPct', pct(corroboratedPct));
    set('qaKpiOnlySingle', n(single));
    set('qaKpiOnlySinglePct', pct(singlePct));
    // The arithmetic on the card, so the partition is checked by reading it.
    set('qaKpiOnlySum', n(corroborated) + ' + ' + n(single) + ' = ' + n(total));
    const split = document.getElementById('qaVeryHighOnlySplit');
    if (!split) return;
    split.title = total > 0
        ? __('Corroborated') + ': ' + n(corroborated) + ' (' + pct(corroboratedPct) + ') · '
          + __('Single perspective') + ': ' + n(single) + ' (' + pct(singlePct) + ') — '
          + __('both add up to Very High only')
        : __('No Very High only issues in this scope');
}

// What each card means — not only that it filters. The subset relation and the
// reminder that perspectives are not independent clinical evidence are the two
// readings the screen used to leave to the reader's imagination.
const _VH_SCOPE_HELP = {
    only: 'Every perspective that fired is Very High — no lower band on any comparison',
    mixed: 'At least one perspective is Very High and another came out lower (High, Moderate or Low)',
    corroborated: 'Corroborated is part of Very High only: two or more distinct perspectives all graded Very High — perspectives are not independent clinical evidence',
};

// Which of the two Very High cards is the active filter, so the number and the
// list agree visibly instead of only in the request.
function _renderScopeCards() {
    [['qaCardVeryHighOnly', 'only', 'Very High only'],
     ['qaCardCorroborated', 'corroborated', 'Corroborated'],
     ['qaCardMixed', 'mixed', 'Mixed severity']].forEach(([id, scope, label]) => {
        const el = document.getElementById(id);
        if (!el) return;
        const active = _state.vhScope === scope;
        el.classList.toggle('is-active', active);
        el.setAttribute('aria-pressed', active ? 'true' : 'false');
        // The hint is bilingual: the fragment's static title is only the
        // pre-render fallback. It states what the card MEANS before how to use
        // it, so a tooltip never reduces "Corroborated" to "click to filter".
        const hint = __(_VH_SCOPE_HELP[scope] || label) + ' — '
            + (active ? __('click the card again to clear')
                      : __('click a card to filter'));
        // One description, referenced once. Setting title= on top would
        // announce the same sentence twice, and aria-label would duplicate
        // the whole hint as the accessible name.
        const help = el.querySelector('.qa-tip-help');
        if (help) {
            help.textContent = hint;
            el.setAttribute('aria-describedby', help.id);
        }
    });
}

// The Very High filter and the "Very High only" / "Mixed severity" cards count
// the same population in different ways, which read as two disagreeing numbers:
// the filter lists an issue when AT LEAST ONE perspective is Very High, while
// "Very High only" means NO perspective that fired came out lower. Both cards
// together are exactly the filter's count, so the screen states that
// arithmetic instead of leaving the operator to reconcile 667 with 1,217.
function _renderSeverityReconcile(s) {
    const el = document.getElementById('qaSeverityReconcile');
    if (!el || !s) return;
    const only = Number(s.very_high_only_issues || 0);
    const mixed = Number(s.mixed_severity_issues || 0);
    const total = Number(s.total_issues || 0);
    const n = v => v.toLocaleString('en-US');
    // The split IS the Very High population of the scope (the server computes
    // both from the whole evidence of each issue and ignores the band filter),
    // so the sum is the number the two cards account for — not a third figure
    // counted a different way.
    const veryHigh = only + mixed;
    // The bucket's corroborated / single-perspective split is stated on the
    // "Very High only" card itself — both counts, both shares and the sum — so
    // the line keeps to the bucket and its total instead of quoting the same
    // split a second time in a different shape.
    const onlyText = n(only) + ' ' + __('no lower band');
    // Which comparisons fired together — one hover away, so the line above
    // stays a sentence while the whole distribution is still available.
    const firedSets = s.very_high_only_by_perspectives || [];
    el.title = firedSets.length
        ? __('Perspectives that fired on the Very High only issues') + ': ' +
          firedSets.slice(0, 10).map(f =>
              (f.perspectives || []).join(' + ') + ' — ' + n(f.issues)).join(' · ')
        : '';
    const parts = [
        __('Very High') + ' = ' + onlyText +
        ' + ' + n(mixed) + ' ' + __('mixed') + ' = ' + n(veryHigh),
    ];
    // With a card active the list is that subset, so the line names the filter
    // instead of repeating the whole scope as if nothing were narrowed.
    if (_state.vhScope === 'only') parts.push(__('Very High only') + ': ' + n(total));
    else if (_state.vhScope === 'corroborated') parts.push(__('Corroborated') + ': ' + n(total));
    else if (_state.vhScope === 'mixed') parts.push(__('Mixed severity') + ': ' + n(total));
    else if (_state.comparisonCategory)
        parts.push(_categoryLabel(_state.comparisonCategory) + ': ' + n(total));
    else parts.push(__('total in view') + ': ' + n(total));
    // With a lower band selected the cards and the table answer different
    // questions on purpose, so the line says so instead of leaving the two
    // numbers to look like a contradiction.
    if (_selectedSeverity() !== 'VERY_HIGH') {
        parts.push(__('Very High cards ignore the severity filter'));
    }
    parts.push(_state.vhScope ? __('click the card again to clear')
                              : __('click a card to filter'));
    el.textContent = parts.join(' · ');
}

function _updateChipCounts(summary) {
    const counts = (summary && summary.by_perspective) || {};
    document.querySelectorAll('#qaPerspectiveChips [data-perspective]').forEach(btn => {
        const key = btn.getAttribute('data-perspective');
        // The canonical (English) label travels on the button, so the visible
        // label is always rebuilt through the one vocabulary helper. Reading it
        // back out of textContent failed here: the count lived in the SAME text
        // node, and translateDOM only swaps a node whose ENTIRE text is a
        // dictionary key, so an Arabic chip could never become English again.
        const base = _perspectiveLabel(btn.getAttribute('data-label'), key);
        const labelEl = btn.querySelector('.qa-chip-label');
        if (labelEl) labelEl.textContent = base;
        const count = counts[key];
        // Under a perspective filter the breakdown covers only the selected
        // comparisons, so a chip outside it has no count in this population:
        // the stale number is dropped rather than left beside a filter it no
        // longer describes.
        let countEl = btn.querySelector('.qa-chip-count');
        if (count === undefined) {
            if (countEl) countEl.remove();
            return;
        }
        if (!countEl) {
            countEl = document.createElement('span');
            countEl.className = 'qa-chip-count';
            btn.appendChild(countEl);
        }
        countEl.textContent = ' (' + count + ')';
    });
}

// ── Table rendering ────────────────────────────────────────────────────
// The table lists exactly the rows the server returned: perspective (like
// every other filter) is applied there, so a second client-side pass would
// re-narrow one page against a total computed over the whole population.

// ── Inline trend (list rows) ─────────────────────────────────────────
// Geometry only: the engine supplies the monthly values, this draws the
// shape. The dashed line is the alert's baseline and the ring marks the
// alert month, so a one-month spike and a sustained problem look different
// at a glance — that is what makes a long list triageable.
const _SPARK_W = 84;
const _SPARK_H = 24;

function _sparkline(issue) {
    const spark = issue && issue.sparkline;
    if (!spark || !(spark.months || []).length) {
        return '<span style="color:var(--text-muted);">--</span>';
    }
    const values = spark.values || [];
    // Missing months break the line instead of drawing a value that was never
    // computed: a gap in the record must look like a gap.
    const segments = [];
    let segment = [];
    values.forEach((v, i) => {
        if (v === null || v === undefined || !Number.isFinite(Number(v))) {
            if (segment.length) segments.push(segment);
            segment = [];
            return;
        }
        segment.push([i, Number(v)]);
    });
    if (segment.length) segments.push(segment);
    const points = segments.flat();
    if (!points.length) return '<span style="color:var(--text-muted);">--</span>';

    const pad = 3;
    let lo = Math.min(...points.map(p => p[1]));
    let hi = Math.max(...points.map(p => p[1]));
    const base = (spark.baseline === null || spark.baseline === undefined)
        ? null : Number(spark.baseline);
    if (base !== null) { lo = Math.min(lo, base); hi = Math.max(hi, base); }
    if (hi === lo) { hi += 1; lo -= 1; }

    const n = values.length;
    const px = i => pad + (n === 1 ? (_SPARK_W - 2 * pad) / 2
        : i * (_SPARK_W - 2 * pad) / (n - 1));
    const py = v => _SPARK_H - pad - ((v - lo) / (hi - lo)) * (_SPARK_H - 2 * pad);
    const stroke = issue.primary_severity === 'VERY_HIGH'
        ? 'var(--severity-critical-text)' : 'var(--accent-teal)';
    const alertIdx = (spark.months || []).indexOf(spark.alert_month);
    const alertVal = alertIdx >= 0 ? values[alertIdx] : null;
    const label = __('Trend') + ' · ' + __('Alert month') + ': ' + spark.alert_month;

    let svg = '<svg class="qa-spark" width="' + _SPARK_W + '" height="' + _SPARK_H +
        '" viewBox="0 0 ' + _SPARK_W + ' ' + _SPARK_H + '" role="img" aria-label="' +
        esc(label) + '"><title>' + esc(label) + '</title>';
    if (base !== null) {
        const by = py(base).toFixed(1);
        svg += '<line x1="' + pad + '" x2="' + (_SPARK_W - pad) + '" y1="' + by +
            '" y2="' + by + '" stroke="var(--text-muted)" stroke-width="1" ' +
            'stroke-dasharray="2 3" opacity="0.75"/>';
    }
    segments.forEach(seg => {
        if (seg.length === 1) {
            svg += '<circle cx="' + px(seg[0][0]).toFixed(1) + '" cy="' +
                py(seg[0][1]).toFixed(1) + '" r="1.8" fill="' + stroke + '"/>';
            return;
        }
        svg += '<polyline fill="none" stroke="' + stroke + '" stroke-width="1.6" ' +
            'stroke-linejoin="round" stroke-linecap="round" points="' +
            seg.map(p => px(p[0]).toFixed(1) + ',' + py(p[1]).toFixed(1)).join(' ') +
            '"/>';
    });
    if (alertVal !== null && alertVal !== undefined && alertIdx >= 0) {
        svg += '<circle cx="' + px(alertIdx).toFixed(1) + '" cy="' +
            py(Number(alertVal)).toFixed(1) + '" r="2.8" fill="var(--bg-surface)" ' +
            'stroke="' + stroke + '" stroke-width="1.6"/>';
    }
    return svg + '</svg>';
}

// The table is the INTERSECTION of the severity band and the card scope (D4):
// "High" + "Very High only" is a legitimate request that can legitimately have
// no members. The empty area names the pair that produced it and repeats the
// Very High KPI, so an empty table beside three non-zero cards never reads as
// "the Very High population is zero".
function _scopeLabel(scope) {
    if (scope === 'only') return __('Very High only');
    if (scope === 'corroborated') return __('Corroborated');
    if (scope === 'mixed') return __('Mixed severity');
    return '';
}

function _renderEmptyState() {
    const wrap = document.getElementById('qaEmpty');
    if (!wrap) return;
    const generic = document.getElementById('qaEmptyGeneric');
    const intersection = document.getElementById('qaEmptyIntersection');
    const title = document.getElementById('qaEmptyIntersectionTitle');
    const hint = document.getElementById('qaEmptyIntersectionHint');
    const severity = _selectedSeverity();
    const scope = _state.vhScope;
    const category = _categoryLabel(_state.comparisonCategory);
    const conflict = (Boolean(scope) || Boolean(category))
        && severity !== 'VERY_HIGH';
    if (generic) generic.style.display = conflict ? 'none' : '';
    if (intersection) intersection.style.display = conflict ? '' : 'none';
    if (conflict) {
        const vh = Number((_state.summary && _state.summary.very_high_issues) || 0);
        if (title) {
            title.textContent = _severityLabel(severity) + ' + ' +
                (_scopeLabel(scope) || category) + ' — ' +
                __('No issue satisfies both the selected severity and the card scope.');
        }
        if (hint) {
            hint.textContent = __('The Very High cards still count') + ' ' +
                vh.toLocaleString('en-US') + ' ' +
                __('because they ignore the severity and the card scope.');
        }
    }
    wrap.style.display = '';
}

// Sentences built in JS carry live numbers, so they are rebuilt on a language
// change instead of being translated in place: the perspective chips (label +
// count) and the table-scope line both live outside data-i18n.
window.addEventListener('dhis:lang', function () {
    try {
        if (_state.meta) _renderPerspectiveChips(_state.meta.perspectives || []);
        if (_state.summary) _updateChipCounts(_state.summary);
        _renderTable();
    } catch (e) { /* screen not loaded yet */ }
});

function _renderTable() {
    const body = document.getElementById('qaTableBody');
    const empty = document.getElementById('qaEmpty');
    if (!body) return;
    const issues = _state.issues;
    const count = document.getElementById('qaCount');
    if (count) count.textContent = issues.length + ' / ' + _state.issuesTotal;
    // State the table's scope in words: the severity control filters this
    // list, while the KPI cards describe the whole issue population. Both
    // numbers and the selected band appear together so the difference is
    // visible instead of inferred from '25 / 801' beside a 2,658 card.
    const scopeEl = document.getElementById('qaTableScope');
    if (scopeEl) {
        const sev = _selectedSeverity();
        const sevLabel = sev ? _severityLabel(sev) : __('All severities');
        const shown = Number(issues.length || 0).toLocaleString('en-US');
        const inScope = Number(_state.issuesTotal || 0).toLocaleString('en-US');
        // summary.total_issues is narrowed by the selected band too, so it is
        // the same population as this table — never present it as "all bands".
        // An active breakdown cell is named here too: the list is then that
        // category, not the whole band, and the line must say which.
        const category = _categoryLabel(_state.comparisonCategory);
        scopeEl.textContent = __('Table scope:') + ' ' + sevLabel +
            (category ? ' · ' + category : '') + ' · ' +
            shown + ' ' + __('shown of') + ' ' + inScope + ' ' +
            __('matching issues');
    }
    if (!issues.length) {
        body.innerHTML = '';
        _renderEmptyState();
        _renderPager(0);
        return;
    }
    if (empty) empty.style.display = 'none';
    body.innerHTML = issues.map(issue => {
        const primary = (issue.perspectives || [])[0] || {};
        const unit = issue.unit || '';
        const sevBadge = _SEVERITY_BADGES[issue.primary_severity] || 'badge badge-muted';
        const statusBadge = _STATUS_TONE[issue.status] || 'badge-muted';
        const interpIcon = _INTERP_ICONS[issue.interpretation] || '📊';
        const lowConf = issue.confidence === 'low'
            ? ' <span class="badge badge-medium" title="' + __('Small comparison group or ML cross-check disagreement — treat with caution') + '">' + __('low confidence') + '</span>' : '';
        // Resolved under a different saved severity/trend policy than the one
        // in effect now. Marked only — the stored severity is NOT rewritten.
        const staleCount = issue.policy_stale_count || 0;
        const staleBadge = staleCount
            ? ' <span class="badge badge-medium" title="' +
              esc(__('Computed under a different saved severity and trend policy than the one in effect now. The stored result is unchanged — re-run the scan to apply the current policy.')) +
              '">' + __('stale policy') + (staleCount > 1 ? ' ×' + staleCount : '') + '</span>'
            : '';
        // Each chip carries its OWN band, so a row listed under the Very High
        // filter shows which perspective was Very High and which stayed lower —
        // "mixed" is then visible in the row, not only inferable from the cards.
        const perspChips = (issue.perspectives || []).map(p => {
            const tip = [_severityLabel(p.severity),
                         _perspectiveLabel(p.perspective_label, p.perspective),
                         p.reason || ''].filter(Boolean).join(' · ');
            return '<span class="badge ' +
                (p.severity === 'VERY_HIGH' ? 'badge-critical' : 'badge-muted') +
                '" style="font-size:0.62rem;padding:0 4px;" title="' + esc(tip) + '">' +
                esc(_perspectiveLabel(p.perspective_label, p.perspective)) + '</span>';
        }).join(' ');
        // Open the STRONGEST perspective: alert_ids is id-ordered, so opening
        // [0] used to land on whichever perspective happened to be scanned
        // first — often history, whose detail has no peer group to show.
        // Keyboard path: the row is focusable and Enter/Space replay this same
        // click handler (see _bindRowKeyboard), so activation has exactly one
        // path and no second listener can double-open the modal. No role is
        // added: the row keeps its table semantics instead of claiming to be a
        // button it is not.
        return '<tr class="qa-issue-row" tabindex="0" onclick="openQualityAlert(' +
            (primary.id || issue.alert_ids[0]) + ')" ' +
            'style="border-bottom:1px solid var(--border-default);cursor:pointer;">' +
            '<td style="padding:0.4rem;"><span class="' + sevBadge + '">' + esc(_severityLabel(issue.primary_severity)) + '</span>' + lowConf + staleBadge + _cappedBadge(issue.primary_severity_cap) + '</td>' +
            '<td style="padding:0.4rem;">' + esc(issue.hospital) + '</td>' +
            '<td style="padding:0.4rem;">' + esc(issue.indicator_name) +
            ' <span style="color:var(--text-muted);font-size:0.68rem;">' + esc(issue.indicator_code) + '</span></td>' +
            '<td style="padding:0.4rem;">' + _fmtValue(primary.current_value, unit) + ' ' + interpIcon + '</td>' +
            '<td style="padding:0.4rem;">' + _fmtValue(primary.baseline_value, unit) +
            (primary.zero_spread ? _zeroSpreadBadge() : '') +
            ' <span style="color:var(--text-muted);font-size:0.68rem;">' + esc(_perspectiveLabel(primary.perspective_label, primary.perspective)) + '</span></td>' +
            '<td style="padding:0.4rem;">' + _fmtPct(primary.deviation_pct) + '</td>' +
            '<td style="padding:0.3rem 0.4rem;">' + _sparkline(issue) + '</td>' +
            '<td style="padding:0.4rem;">' + perspChips + '</td>' +
            '<td style="padding:0.4rem;">' + esc(issue.month) + '</td>' +
            '<td style="padding:0.4rem;"><span class="badge ' + statusBadge + '">' + esc(_statusLabel(issue.status)) + '</span></td>' +
            '<td style="padding:0.4rem;">' + _fmtDate(issue.detected_at) + '</td>' +
            '</tr>';
    }).join('');
    _bindRowKeyboard(body);
    _renderPager(_state.issuesTotal || issues.length);
}

// ── Keyboard access for issue rows ─────────────────────────────────────
// One delegated listener for the whole body, bound once: rows are rebuilt on
// every load, so a per-row listener would stack duplicates that reopen the
// detail. Enter/Space replay the row's own click handler, so mouse, touch and
// keyboard share a single activation path.
let _rowKeyboardBound = false;
function _bindRowKeyboard(body) {
    if (_rowKeyboardBound || !body) return;
    _rowKeyboardBound = true;
    body.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
        const row = e.target && e.target.closest
            ? e.target.closest('tr.qa-issue-row') : null;
        // Only the row itself activates: a control inside a row keeps its own
        // keys, and key repeat (a held Enter) must not reopen the modal.
        if (!row || row !== e.target || e.repeat) return;
        e.preventDefault();
        row.click();
    });
}

function _renderPager(total) {
    const size = _pageSize();
    // With "All" there is a single page, so the pager states the whole count
    // and both arrows are inert; otherwise it pages at the chosen size.
    const pages = size ? Math.max(1, Math.ceil(total / size)) : 1;
    const info = document.getElementById('qaPageInfo');
    if (info) {
        info.textContent = size
            ? __('Page') + ' ' + _state.page + ' / ' + pages
            : __('Showing all') + ' ' + total + ' ' + __('issues');
    }
    const prev = document.getElementById('qaPrevBtn');
    const next = document.getElementById('qaNextBtn');
    if (prev) prev.disabled = !size || _state.page <= 1;
    if (next) next.disabled = !size || _state.page >= pages;
    const select = document.getElementById('qaPageSizeSelect');
    // Reflect the state on the control (it also carries the last selection
    // made through it) so the two never disagree after a reload.
    if (select && select.value !== String(size)) select.value = String(size);
}

// ── Scan ───────────────────────────────────────────────────────────────
export async function scanQualityAlerts() {
    const monthSel = document.getElementById('qaMonthFilter');
    const month = monthSel && monthSel.value ? monthSel.value : null;
    // No period selected -> scan ALL reporting periods (catch-up). New
    // uploads are scanned automatically by the pipeline (alerts_auto_scan).
    const question = month
        ? __('Run the Quality Alerts scan for ') + month + '?'
        : __('Scan ALL reporting periods?');
    if (!confirm(question)) return;
    const btn = document.getElementById('qaScanBtn');
    if (btn) btn.disabled = true;
    try {
        const result = await apiPostJSON('/quality-alerts/scan', month ? { month: month } : {});
        alert(__('Scan complete: ') + (result.created || 0) + ' ' + __('new') + ', ' +
            (result.updated || 0) + ' ' + __('updated') + ', ' +
            (result.deactivated || 0) + ' ' + __('no longer detected'));
        await loadQualityAlerts();
    } catch (err) {
        alert(__('Scan failed: ') + (err && err.message ? err.message : __('error')));
    } finally {
        if (btn) btn.disabled = false;
    }
}

// ── Recompute only the results an older policy produced ────────────────────
// Preview → explicit confirmation → targeted rescan. The server rescans only
// the (month, hospital, indicator) rows it reports as stale; every other row
// keeps its stored result.
export async function recomputeStaleQualityAlerts() {
    const btn = document.getElementById('qaRescanStaleBtn');
    if (btn) btn.disabled = true;
    try {
        const preview = await apiPostJSON('/quality-alerts/rescan-stale', { confirm: false });
        const months = (preview && preview.months) || [];
        if (!months.length) {
            alert(__('No stored results were computed under an older severity policy.'));
            return;
        }
        const details = months.map(m =>
            esc(m.month) + ' — ' + m.alerts + ' ' + __('alerts')).join('<br>');
        const ok = await confirmAction({
            title: __('Recompute stale results'),
            message: __('Only the alerts marked stale — those months, hospitals and indicators — are recomputed under the current saved policy. Every other stored result is left untouched.'),
            details: details,
            okLabel: __('Recompute') + ' ' + months.length + ' ' + __('months'),
            cancelLabel: __('Cancel'),
            warning: true,
        });
        if (!ok) return;

        const result = await apiPostJSON('/quality-alerts/rescan-stale', {
            confirm: true,
            months: months.map(m => m.month),
        });
        const rescanned = (result && result.rescanned) || [];
        if (!rescanned.length) {
            alert(__('No stored results were computed under an older severity policy.'));
            return;
        }
        alert(__('Recomputed') + ' ' + ((result.months || []).length) + ' ' + __('months') + ': ' +
            (result.created || 0) + ' ' + __('new') + ', ' +
            (result.updated || 0) + ' ' + __('updated') + ', ' +
            (result.deactivated || 0) + ' ' + __('no longer detected'));
        await loadQualityAlerts();
    } catch (err) {
        alert(__('Recompute failed: ') + (err && err.message ? err.message : __('error')));
    } finally {
        if (btn) btn.disabled = false;
    }
}

// ── Detail modal ───────────────────────────────────────────────────────
export async function openQualityAlert(alertId) {
    // Where the dialog was opened from (a row, a KPI card, a keyboard Enter),
    // so closing it puts focus back there instead of at the top of the page.
    var _opener = document.activeElement;
    if (_opener && _opener !== document.body &&
            !(document.getElementById('detailModal') || {}).contains?.(_opener)) {
        _modalReturnFocus = _opener;
    }
    let payload;
    try {
        payload = await apiGet('/quality-alerts/' + alertId);
    } catch (err) {
        alert(__('Failed to load alert: ') + (err && err.message ? err.message : __('error')));
        return;
    }
    const modal = document.getElementById('detailModal');
    const title = document.getElementById('modalTitle');
    const body = document.getElementById('modalBody');
    if (!modal || !body) return;
    // The body owns the full identity (indicator, code, hospital, month) — a
    // second copy in the modal header only competed with it.
    if (title) title.textContent = __('Quality Alert Detail');
    // The previous modal body (and its chart canvas) is about to be replaced.
    _destroyTrendChart();
    body.innerHTML = _renderDetail(payload);
    // #detailModal is shown by the shared `.show` class (styles.css:
    // `#detailModal.show{display:flex}`) and closed by closeModal(), which only
    // removes that class. An inline `display:block` outranks the stylesheet, so
    // the ✕ / backdrop / Escape all stopped working — clear it and use the class.
    modal.style.display = '';
    modal.classList.add('show');
    // Chart.js measures its canvas: draw only once the modal has layout,
    // otherwise the chart is created at 0×0 and stays invisible.
    requestAnimationFrame(() => _renderTrendChart(payload.trend, payload.alert.unit || ''));
}

// ── Detail helpers ─────────────────────────────────────────────────────
// Every label/value pair below is rendered with an explicit caption: the
// detail screen must never ask the reader to guess what a number means.
const _METHOD_LABELS = {
    peer_zscore: 'Peer z-score',
    zscore: 'Z-score vs own history',
    pct_change: 'Percent change vs own history',
    iqr: 'IQR vs own history',
    rolling_median_mad: 'Rolling median (MAD) vs own history',
    insufficient_history: 'Insufficient history',
};
const _STAT_LABELS = {
    mean: 'Mean', std: 'Std. deviation', median: 'Median',
    min: 'Minimum', max: 'Maximum', points: 'Baseline points',
};
const _DIRECTION_LABELS = {
    higher_is_better: 'Higher is better',
    lower_is_better: 'Lower is better',
    target_range: 'Target range',
    none: 'Not configured (statistical only)',
};
// Clinical desirability of the deviation — decides the colour, never the
// severity (severity is the statistical band computed by the engine).
const _INTERP_TONE = {
    high_is_concern: 'concern', low_is_concern: 'concern',
    outside_target_range: 'concern',
    high_is_favorable: 'good', low_is_favorable: 'good',
    within_target_range: 'good',
    statistical_only: 'neutral',
};

function _methodLabel(method) {
    const key = _METHOD_LABELS[method];
    return key ? __(key) : (method || '--');
}

function _directionLabel(direction) {
    return __(_DIRECTION_LABELS[direction] || _DIRECTION_LABELS.none);
}

function _toneFor(interpretation) {
    return _INTERP_TONE[interpretation] || 'neutral';
}

// Server-provided legend first (it is bilingual); these fallbacks keep the
// modal readable when it is opened before the tab has fetched its meta.
const _INTERP_FALLBACK = {
    high_is_concern: 'High values are undesirable — review indicated',
    high_is_favorable: 'High values are desirable — verify data accuracy',
    low_is_concern: 'Low values are undesirable — possible under-reporting',
    low_is_favorable: 'Low values are desirable',
    outside_target_range: 'Outside the configured target range',
    within_target_range: 'Within the configured target range',
    statistical_only: 'No clinical direction configured — statistical only',
};

function _interpText(interpretation) {
    const legend = _renderDetail.legend || {};
    if (legend[interpretation]) return legend[interpretation];
    const fallback = _INTERP_FALLBACK[interpretation];
    return fallback ? __(fallback) : (interpretation || '');
}

// A band the approved policy lowered. Rows written before the cap was approved
// keep their stored band; the screen shows the policy band and marks the
// difference instead of quietly printing a severity the row contradicts.
//
// The sources are NOT interchangeable: a degenerate comparison has NO
// measurable spread, a thin peer group is too small to measure one, and a
// refusal by the hospital's own window measured a scale and disagreed with it.
// Each reason is named from the provenance block that actually applied, so a
// thin-peer cap cannot read as a zero-spread cap and neither reads as a
// window refusal.
function _capReason(cap) {
    const reasons = [];
    if (cap.dispersion) reasons.push(__('no measurable spread: every value in the comparison is identical'));
    if (cap.thin_peer_group) reasons.push(__('too few peer hospitals to measure a spread'));
    if (cap.very_high_eligibility) reasons.push(__('the hospital\u2019s own history window does not support the top band'));
    return reasons.length ? reasons.join(' \u00b7 ') : __('the comparison cannot be graded');
}

function _cappedBadge(cap) {
    if (!cap || !cap.stored_severity) return '';
    // No badge when the policy band equals the stored one: the row was never
    // lowered, and "HIGH → HIGH" read as a downgrade that did not happen. The
    // provenance stays on the payload; only the no-op is hidden here.
    if (cap.severity === cap.stored_severity) return '';
    return ' <span class="badge badge-medium" title="' +
        esc(__('Stored') + ' ' + _severityLabel(cap.stored_severity) + ' — ' +
            _capReason(cap)) + '">' +
        esc(_severityLabel(cap.stored_severity) + ' \u2192 ' + _severityLabel(cap.severity)) + '</span>';
}


// The engine sentence is written when the row is scanned, so on a capped row it
// names the band that was computed then (the stored, pre-cap severity). That
// sentence is evidence and is never rewritten; instead it is labelled for what
// it is, and the operational band — the one the badge, the list and the KPIs
// use — is restated beside it.
function _capExplanationNote(a) {
    const cap = a.severity_cap;
    if (!cap || !cap.stored_severity || cap.stored_severity === cap.severity) return '';
    const template = __('This explanation reports the pre-cap assessment (stored severity {stored}). The operational band is {effective}.');
    const text = template
        .replace('{stored}', _severityLabel(cap.stored_severity))
        .replace('{effective}', _severityLabel(a.effective_severity || a.severity));
    return '<div class="qa-cap-note">' + esc(text) + '</div>';
}

// ── Detail modal keyboard support ───────────────────────────────────────
// The dialog takes focus on open, holds Tab/Shift+Tab inside itself while it is
// open, and returns focus to its opener on close. No extra roles are invented:
// #detailModal is a real dialog and the close button is a real button.
let _modalReturnFocus = null;

function _modalFocusables() {
    const modal = document.getElementById('detailModal');
    if (!modal) return [];
    return Array.from(modal.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
        'textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'
    )).filter(el => el.offsetParent !== null);
}

function _modalTrapTab(event) {
    const modal = document.getElementById('detailModal');
    if (!modal || !modal.classList.contains('show')) return;
    const items = _modalFocusables();
    if (!items.length) { event.preventDefault(); return; }
    const first = items[0];
    const last = items[items.length - 1];
    if (!modal.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
        return;
    }
    if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    }
}

function _installDetailModalA11y() {
    const modal = document.getElementById('detailModal');
    if (!modal || window._qaModalA11yBound) return;
    window._qaModalA11yBound = true;
    modal.addEventListener('keydown', function (event) {
        if (event.key === 'Tab') _modalTrapTab(event);
    }, true);
    // One observer covers every close path (✕, backdrop, Escape, a module
    // calling closeModal directly), because they all remove `.show`.
    new MutationObserver(function () {
        if (modal.classList.contains('show')) {
            const close = modal.querySelector('.modal-close');
            if (close && !modal.contains(document.activeElement)) close.focus();
            return;
        }
        if (_modalReturnFocus && document.contains(_modalReturnFocus)) {
            try { _modalReturnFocus.focus(); } catch (e) { /* detached */ }
        }
        _modalReturnFocus = null;
    }).observe(modal, { attributes: true, attributeFilter: ['class'] });
}

function _fmtZ(z) {
    if (z === null || z === undefined) return '--';
    return (Number(z) >= 0 ? '+' : '') + Number(z).toFixed(2);
}

// Units like "%" attach to the number; word units get a space.
function _unitSuffix(unit) {
    if (!unit) return '';
    return unit === '%' ? '%' : ' ' + unit;
}

function _kv(label, valueHtml) {
    return '<div class="qa-kv-row"><dt>' + esc(label) + '</dt><dd>' + valueHtml + '</dd></div>';
}

function _kpi(label, valueHtml, sub, tone) {
    return '<div class="qa-kpi">' +
        '<div class="qa-kpi-l">' + esc(label) + '</div>' +
        '<div class="qa-kpi-v' + (tone ? ' ' + tone : '') + '">' + valueHtml + '</div>' +
        (sub ? '<div class="qa-kpi-s">' + sub + '</div>' : '') +
        '</div>';
}

function _cfgVar(name, fallback) {
    try {
        const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        return value || fallback;
    } catch (e) {
        return fallback;
    }
}

// ── Trend chart ─────────────────────────────────────────────────────────
// Draws the exact monthly series the engine recomputed for this alert:
// the hospital's own line, the comparison baseline line, and a marker on the
// flagged month. Colours are read from the theme at draw time, so a theme
// switch (chart-utils refreshes every registered chart) keeps working.
const _alertMonthPlugin = {
    id: 'qaAlertMonth',
    beforeDatasetsDraw(chart) {
        const opts = chart.options.plugins.qaAlertMonth;
        if (!opts || opts.index == null || opts.index < 0) return;
        const xScale = chart.scales.x;
        if (!xScale) return;
        const x = xScale.getPixelForValue(opts.index);
        if (!Number.isFinite(x)) return;
        const area = chart.chartArea || {};
        const ctx = chart.ctx;
        ctx.save();
        ctx.strokeStyle = _cfgVar('--severity-critical-border', 'rgba(248,113,113,0.55)');
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(x, area.top || 0);
        ctx.lineTo(x, area.bottom || chart.height || 0);
        ctx.stroke();
        ctx.restore();
    },
    afterDatasetsDraw(chart) {
        const opts = chart.options.plugins.qaAlertMonth;
        if (!opts || opts.index == null || opts.index < 0) return;
        const meta = chart.getDatasetMeta(0);
        const point = meta && meta.data && meta.data[opts.index];
        if (!point || point.x == null || point.y == null) return;
        const ctx = chart.ctx;
        ctx.save();
        ctx.beginPath();
        ctx.arc(point.x, point.y, 6.5, 0, Math.PI * 2);
        ctx.strokeStyle = _cfgVar('--severity-critical-text', '#F87171');
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.restore();
    },
};

let _trendChart = null;

function _destroyTrendChart() {
    if (!_trendChart) return;
    try { _trendChart.destroy(); } catch (e) { /* canvas already gone */ }
    _trendChart = null;
}

function _renderTrendChart(trend, unit) {
    const canvas = document.getElementById('qaTrendChart');
    if (!canvas || !trend || typeof Chart === 'undefined') return;
    _destroyTrendChart();
    const colors = window.CHART_COLORS || {};
    const months = trend.months || [];
    const unitLabel = unit || trend.unit || '';
    const alertIndex = months.indexOf(trend.alert_month);
    const baselineValues = trend.baseline || [];
    const hasPeerBaseline = baselineValues.some(v => v !== null && v !== undefined);

    const datasets = [{
        label: __('This hospital'),
        data: trend.values || [],
        borderColor: colors.primary,
        backgroundColor: 'transparent',
        _colorRole: 'primary',
        borderWidth: 2.5,
        pointRadius: 3.5,
        pointHoverRadius: 6,
        pointBackgroundColor: colors.primary,
        tension: 0.25,
        spanGaps: true,
        fill: false,
    }];
    if (hasPeerBaseline) {
        datasets.push({
            label: _perspectiveLabel(trend.baseline_label) || __('Baseline'),
            data: baselineValues,
            borderColor: colors.secondary || colors.neutral,
            backgroundColor: 'transparent',
            _colorRole: 'secondary',
            borderWidth: 2,
            borderDash: [6, 4],
            pointRadius: 0,
            pointHoverRadius: 3,
            tension: 0.25,
            spanGaps: true,
            fill: false,
        });
    } else if (trend.reference_value !== null && trend.reference_value !== undefined) {
        datasets.push({
            label: _perspectiveLabel(trend.baseline_label) || __('Baseline'),
            data: months.map(() => trend.reference_value),
            borderColor: colors.secondary || colors.neutral,
            backgroundColor: 'transparent',
            _colorRole: 'secondary',
            borderWidth: 2,
            borderDash: [3, 4],
            pointRadius: 0,
            tension: 0,
            fill: false,
        });
    }

    _trendChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { labels: months, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                // The card's own legend (with the alert-month marker) explains
                // the series; Chart.js's built-in one would repeat it.
                legend: { display: false },
                tooltip: {
                    backgroundColor: _cfgVar('--bg-surface', '#1A1D27'),
                    titleColor: _cfgVar('--text-primary', '#E8EAED'),
                    bodyColor: _cfgVar('--text-secondary', '#9AA0AC'),
                    callbacks: {
                        label: (item) => {
                            let text = item.dataset.label + ': ' +
                                _fmtValue(item.parsed.y, unitLabel);
                            // Peer mean: say how many hospitals were in it —
                            // the size of the comparison group is part of the
                            // meaning, not a footnote.
                            const counts = trend.peer_counts || [];
                            if (item.datasetIndex === 1 && counts[item.dataIndex]) {
                                text += ' · n = ' + counts[item.dataIndex];
                            }
                            return text;
                        },
                    },
                },
                qaAlertMonth: { index: alertIndex },
            },
            scales: {
                x: {
                    ticks: { color: colors.neutral, font: { size: 10 } },
                    grid: { display: false },
                },
                y: {
                    beginAtZero: false,
                    ticks: { color: colors.neutral, font: { size: 10 } },
                    grid: { color: colors.grid },
                    title: unitLabel
                        ? { display: true, text: unitLabel, color: colors.neutral, font: { size: 10 } }
                        : { display: false },
                },
            },
        },
        plugins: [_alertMonthPlugin],
    });
    if (window.registerChart) window.registerChart(_trendChart);
}

// ── Detail modal body ──────────────────────────────────────────────────
function _bandOf(value) {
    if (!value) return '';
    if (typeof value === 'string') return value;
    if (value.applied === false) return '';
    return value.final_severity || value.final_level || value.level ||
        value.band || value.severity || '';
}

function _evidenceSourceLabel(source) {
    const map = {
        canonical_layered: 'Canonical layered',
        independent_audit: 'Independent audit',
        independent_perspective: 'Independent perspective',
        canonical_evidence_unavailable: 'Canonical evidence unavailable',
    };
    return __(map[source] || String(source || ''));
}

function _evidenceStatusLabel(status) {
    const map = {
        equivalent: 'Equivalent',
        not_equivalent: 'Not equivalent',
        independent_perspective: 'Independent perspective',
        missing_layered_result: 'Missing layered result',
        canonical_evidence_unavailable: 'Canonical evidence unavailable',
        stored_level_only: 'Stored level only',
    };
    return __(map[status] || String(status || ''));
}


function _renderDetail(p) {
    const a = p.alert;
    const ev = p.evidence || {};
    const unit = a.unit || '';
    const def = p.definition;
    const trend = p.trend;
    const hospital = p.hospital || {};
    const tone = _toneFor(a.interpretation);
    const sevBadge = _SEVERITY_BADGES[a.severity] || 'badge badge-muted';
    const interpIcon = _INTERP_ICONS[a.interpretation] || '•';
    const stats = ev.stats || {};
    const isHistory = a.perspective === 'history';
    const n = a.peer_count;
    // A peer group too small to measure a spread produces no z-score at all
    // (the engine's thin-peer policy): the dash is a deliberate outcome, and
    // the stored provenance says so.
    const zWithheld = !!(stats.z_provenance && stats.z_provenance.z_produced === false);
    const where = [hospital.name, hospital.governorate, hospital.type]
        .filter(Boolean).join(' · ');
    let html = '<div class="qa-detail">';

    // 1 — What was flagged, where, when, how serious.
    html += '<header class="qa-head">' +
        '<div class="qa-head-txt">' +
        '<div class="qa-name">' + esc(a.indicator_name) + '</div>' +
        '<div class="qa-meta"><code>' + esc(a.indicator_code) + '</code>' +
        (unit ? ' · ' + __('Unit') + ': ' + esc(unit) : '') + '</div>' +
        '<div class="qa-meta">' + esc(where) + (where ? ' · ' : '') + esc(a.month) + '</div>' +
        '</div>' +
        '<div class="qa-head-badges">' +
        // The modal's operational band is the EFFECTIVE one (cap applied) — the
        // same value the list, the KPIs and the pager use. The cap badge below
        // names the stored pre-cap band when the two differ; stored severity is
        // never substituted for effective severity.
        '<span class="' + sevBadge + '">' +
        esc(_severityLabel(a.effective_severity || a.severity)) + '</span>' +
        _cappedBadge(a.severity_cap) +
        (a.policy_state === 'stale'
            ? '<span class="badge badge-medium" title="' +
              esc(__('Computed under a different saved severity and trend policy than the one in effect now. The stored result is unchanged — re-run the scan to apply the current policy.')) +
              '">' + __('stale policy') + '</span>'
            : '') +
        '<span class="badge ' + (_STATUS_TONE[a.status] || 'badge-muted') + '">' + esc(_statusLabel(a.status)) + '</span>' +
        (a.confidence === 'low'
            ? '<span class="badge badge-medium" title="' +
              esc(__('Small comparison group or ML cross-check disagreement — treat with caution')) + '">' +
              __('low confidence') + '</span>'
            : '') +
        '</div></header>';

    // 2 — The verdict in one sentence: is the direction itself concerning?
    html += '<div class="qa-verdict ' + tone + '">' +
        '<div class="qa-verdict-icon">' + interpIcon + '</div>' +
        '<div class="qa-verdict-body">' +
        '<div class="qa-verdict-title">' + esc(_interpText(a.interpretation)) + '</div>' +
        (a.reason ? '<div class="qa-verdict-text">' + esc(a.reason) + '</div>' : '') +
        _capExplanationNote(a) +
        '<div class="qa-verdict-src">' + __('Flagged by') + ' <strong>' +
        esc(_perspectiveLabel(a.perspective_label, a.perspective)) + '</strong> · ' + esc(_methodLabel(a.method)) +
        (n ? ' · ' + (isHistory ? __('baseline points') : __('peers')) + ': ' + esc(String(n)) : '') +
        '</div></div></div>';

    // 2b — Evidence provenance (Phase 8): the canonical base band, the
    // operational trend escalation and the final alert band are three
    // different things. The final band is the operational alert severity and
    // is never labelled canonical when escalation changed it.
    const canonicalEv = a.canonical_evidence || {};
    const baseBand = _bandOf(a.base_severity);
    const finalBand = _bandOf(a.final_severity);
    const trendAssessed = !!a.trend_assessment;
    const trendBand = _bandOf(a.trend_assessment);
    let evidenceRows = '';
    if (baseBand) {
        evidenceRows += _kv(__('Canonical base severity'), esc(baseBand));
    }
    if (trendAssessed) {
        evidenceRows += _kv(__('Trend assessment'),
            esc(trendBand || __('Not escalated')));
    }
    if (finalBand) {
        evidenceRows += _kv(__('Final alert severity'),
            esc(finalBand) + ' · ' + esc(__('operational')));
    }
    if (a.evidence_source) {
        evidenceRows += _kv(__('Evidence source'),
            esc(_evidenceSourceLabel(a.evidence_source)));
    }
    if (canonicalEv.status) {
        evidenceRows += _kv(__('Evidence status'),
            esc(_evidenceStatusLabel(canonicalEv.status)));
    }
    if (canonicalEv.perspective) {
        evidenceRows += _kv(__('Perspective'),
            esc(_perspectiveLabel(canonicalEv.perspective_label || canonicalEv.perspective,
                canonicalEv.perspective)));
    }
    if (evidenceRows) {
        html += '<section class="qa-card"><div class="qa-card-hd">' +
            __('Evidence provenance') + '</div><dl class="qa-kv">' +
            evidenceRows + '</dl></section>';
    }

    // 3 — The four numbers that define the finding (never duplicated below).
    html += '<div class="qa-kpis">' +
        _kpi(__('Current value'), _fmtValue(a.current_value, unit), esc(a.month)) +
        _kpi(__('Baseline'), _fmtValue(a.baseline_value, unit) +
            (a.zero_spread ? _zeroSpreadBadge() : ''),
            esc(_perspectiveLabel(ev.baseline_label || a.perspective_label, a.perspective)) +
            (n ? ' · ' + (isHistory ? __('months') : __('hospitals')) + ': ' + esc(String(n)) : '') +
            (a.zero_spread ? ' · ' + esc(_spreadNote(a, stats)) : '')) +
        // A dash is explained, never left to guess: a zero baseline makes the
        // relative change undefined, and a zero-spread group makes z undefined.
        _kpi(__('Deviation'), _fmtPct(a.deviation_pct),
            a.deviation_pct == null && a.baseline_value === 0
                ? __('Baseline is zero — relative change undefined')
                : __('vs baseline'),
            tone === 'concern' ? 'concern' : (tone === 'good' ? 'good' : 'neutral')) +
        _kpi(__('Z-score'), _fmtZ(a.z_score),
            a.z_score == null && stats.std === 0
                ? __('Comparison group has no spread')
                : (zWithheld
                    ? __('Too few peer hospitals to measure a spread — no z-score is produced for this comparison')
                    : (ev.z_threshold != null
                        ? __('Threshold') + ' |z| ≥ ' + Number(ev.z_threshold).toFixed(2)
                        : ''))) +
        '</div>';

    // 4 — Trend: the same numbers drawn month by month.
    const hasTrend = !!(trend && (trend.months || []).length);
    const hasBaselineLine = !!(trend && ((trend.baseline || []).some(v => v != null) ||
        trend.reference_value != null));
    html += '<section class="qa-card">' +
        '<div class="qa-card-hd">' + __('Trend') +
        (hasTrend
            ? '<span class="qa-card-hd-s">' + esc(String(trend.months.length) + ' ' +
              __('months') + ' · ' + __('Alert month') + ': ' + a.month) + '</span>'
            : '') +
        '</div>' +
        (hasTrend
            ? '<div class="qa-chart"><canvas id="qaTrendChart"></canvas></div>' +
              '<div class="qa-chart-legend">' +
              '<span><i class="qa-lg qa-lg-solid"></i>' + __('This hospital') + '</span>' +
              (hasBaselineLine
                  ? '<span><i class="qa-lg qa-lg-dash"></i>' +
                    esc(_perspectiveLabel(trend.baseline_label) || __('Baseline')) + '</span>'
                  : '') +
              '<span><i class="qa-lg qa-lg-ring"></i>' + __('Alert month') + '</span>' +
              '</div>'
            : '<div class="qa-empty">' +
              __('No month-by-month values are stored for this indicator.') + '</div>') +
        '</section>';

    // 5 — How the comparison was made + the comparison group's distribution.
    const peerGroups = (p.peer_groups || []).length
        ? p.peer_groups
        : ((p.peers || []).length
            ? [{ perspective: a.perspective,
                 label: _perspectiveLabel(ev.baseline_label || a.perspective_label, a.perspective),
                 peers: p.peers }]
            : []);
    let compRows = _kv(__('Method'), esc(_methodLabel(a.method))) +
        _kv(__('Comparison group'),
            esc(_perspectiveLabel(ev.baseline_label || a.perspective_label, a.perspective)) +
            (n ? ' · ' + (isHistory ? __('months') : __('hospitals')) + ': ' + esc(String(n)) : '')) +
        _kv(__('Reporting period'), esc(a.month));
    if (ev.z_threshold != null) {
        compRows += _kv(__('Alert threshold'), '|z| ≥ ' + Number(ev.z_threshold).toFixed(2));
    }
    if (zWithheld) {
        compRows += _kv(__('Z-score'),
            '<span class="qa-warn">' +
            esc(__('Not produced — the comparison group is too small to measure a spread')) +
            '</span>');
    }
    if (a.score != null) compRows += _kv(__('Severity score'), Number(a.score).toFixed(2));
    compRows += _kv(__('Confidence'), esc(a.confidence === 'low' ? __('low confidence') : __('high confidence')));
    if (ev.ml_confirms === true) compRows += _kv(__('ML cross-check'), __('Isolation Forest agrees'));
    if (ev.ml_confirms === false) {
        compRows += _kv(__('ML cross-check'),
            '<span class="qa-warn">' + __('Isolation Forest disagrees — low confidence') + '</span>');
    }
    let compHtml = '<section class="qa-card"><div class="qa-card-hd">' +
        __('How it was compared') + '</div><dl class="qa-kv">' + compRows + '</dl>' +
        '</section>';

    const statKeys = ['mean', 'std', 'median', 'min', 'max', 'points'];
    let statsHtml = '';
    if (statKeys.some(k => stats[k] != null)) {
        statsHtml = '<section class="qa-card"><div class="qa-card-hd">' +
            esc(isHistory ? __('Own-history statistics') : __('Comparison group statistics')) +
            '</div><dl class="qa-kv">' +
            statKeys.filter(k => stats[k] != null).map(k =>
                _kv(__(_STAT_LABELS[k]),
                    _fmtValue(stats[k], k === 'points' ? '' : unit))).join('') +
            '</dl>' +
            (stats.std === 0
                ? '<div class="qa-note">' + __('The comparison group has no spread (std = 0), so any difference scores the maximum.') + '</div>'
                : '') +
            '</section>';
    }
    html += '<div class="qa-cols">' + compHtml + statsHtml + '</div>';

    // 5b — The peers themselves: who was compared, and at what value. Always
    // visible (a collapsed summary hid the only evidence a reader can use to
    // judge the baseline), and every group the issue used is listed so a
    // history alert still shows the peer comparisons run for the same finding.
    let peersHtml = '';
    if (peerGroups.length) {
        peersHtml = peerGroups.map(group => {
            const rows = (group.peers || []).map(peer =>
                '<tr><td>' + esc(peer.name) + '</td>' +
                '<td style="text-align:right;">' +
                esc(_fmtValue(peer.value, unit)) + '</td></tr>').join('');
            return '<div class="qa-peer-group">' +
                '<div class="qa-peer-group-hd">' +
                esc(group.label || group.perspective) + ' · ' +
                ((group.peers || []).length) + ' ' + __('hospitals') + '</div>' +
                '<table class="qa-table qa-peer-table"><thead><tr>' +
                '<th>' + __('Hospital') + '</th>' +
                '<th style="text-align:right;">' + __('Value') + '</th>' +
                '</tr></thead><tbody>' + rows + '</tbody></table></div>';
        }).join('');
    } else {
        peersHtml = '<div class="qa-note">' +
            __('This finding compares the hospital with its own history — no peer hospitals were used.') +
            '</div>';
    }
    html += '<section class="qa-card"><div class="qa-card-hd">' +
        __('Peer hospitals') +
        '<span class="qa-card-hd-s">' +
        __('Who was compared, and their value for this month') +
        '</span></div>' + peersHtml + '</section>';

    // 6 — Indicator definition, straight from the registry.
    if (def) {
        let defRows = _kv(__('Direction'), esc(_directionLabel(def.direction || a.direction)));
        if (def.target_min != null || def.target_max != null) {
            defRows += _kv(__('Target'),
                esc(String(def.target_min ?? '—')) + ' – ' + esc(String(def.target_max ?? '—')));
        }
        if (def.version) defRows += _kv(__('Version'), esc(String(def.version)));
        if (def.unit) defRows += _kv(__('Unit'), esc(def.unit));
        if ((def.numerator_codes || []).length) {
            defRows += _kv(__('Numerator'),
                '<code>' + esc(def.numerator_codes.join(', ')) + '</code>');
        }
        if ((def.denominator_codes || []).length) {
            defRows += _kv(__('Denominator'),
                '<code>' + esc(def.denominator_codes.join(', ')) + '</code>');
        }
        if (def.operator || def.multiplier != null) {
            defRows += _kv(__('Scaling'), esc(String(def.multiplier != null ? def.multiplier : '')) +
                (def.operator ? ' ' + esc(def.operator) : ''));
        }
        html += '<section class="qa-card"><div class="qa-card-hd">' +
            __('Indicator definition') + '</div>' +
            (def.formula ? '<pre class="qa-formula">' + esc(def.formula) + '</pre>' : '') +
            '<dl class="qa-kv">' + defRows + '</dl></section>';
    }

    // 7 — The same value under every perspective that fired.
    const siblings = (p.issue && p.issue.perspectives) || [];
    if (siblings.length > 1) {
        html += '<section class="qa-card"><div class="qa-card-hd">' +
            __('All comparison perspectives') +
            '<span class="qa-card-hd-s">' +
            __('Each row compares the same value with a different reference group') +
            '</span></div><div class="qa-table-wrap"><table class="qa-table"><thead><tr>' +
            ['Perspective', 'Severity', 'Current', 'Baseline', 'Deviation', 'Method', 'Status']
                .map(h => '<th>' + __(h) + '</th>').join('') +
            '</tr></thead><tbody>' +
            siblings.map(s => {
                const here = s.id === a.id;
                return '<tr' + (here ? ' class="is-current"' : '') + '>' +
                    '<td>' + esc(_perspectiveLabel(s.perspective_label, s.perspective)) +
                    (here ? ' <span class="qa-here">' + __('viewing') + '</span>' : '') + '</td>' +
                    '<td><span class="' + (_SEVERITY_BADGES[s.severity] || 'badge badge-muted') + '">' +
                    esc(_severityLabel(s.severity)) + '</span></td>' +
                    '<td>' + _fmtValue(s.current_value, unit) + '</td>' +
                    '<td>' + _fmtValue(s.baseline_value, unit) + '</td>' +
                    '<td>' + _fmtPct(s.deviation_pct) + '</td>' +
                    '<td>' + esc(_methodLabel(s.method)) + '</td>' +
                    '<td>' + esc(_statusLabel(s.status)) + '</td></tr>';
            }).join('') +
            '</tbody></table></div></section>';
    }

    // 8 — Earlier findings for the same hospital + indicator.
    if ((p.previous_alerts || []).length) {
        html += '<section class="qa-card"><div class="qa-card-hd">' + __('Previous alerts') +
            '<span class="qa-card-hd-s">' + __('Same hospital and indicator, other months') +
            '</span></div><div class="qa-table-wrap"><table class="qa-table"><thead><tr>' +
            ['Month', 'Perspective', 'Severity', 'Current', 'Baseline', 'Status']
                .map(h => '<th>' + __(h) + '</th>').join('') +
            '</tr></thead><tbody>' +
            p.previous_alerts.slice(0, 12).map(pa =>
                '<tr><td>' + esc(pa.month) + '</td>' +
                '<td>' + esc(_perspectiveLabel(pa.perspective_label, pa.perspective)) + '</td>' +
                '<td><span class="' + (_SEVERITY_BADGES[pa.severity] || 'badge badge-muted') + '">' +
                esc(_severityLabel(pa.severity)) + '</span></td>' +
                '<td>' + _fmtValue(pa.current_value, unit) + '</td>' +
                '<td>' + _fmtValue(pa.baseline_value, unit) + '</td>' +
                '<td>' + esc(_statusLabel(pa.status)) + '</td></tr>').join('') +
            '</tbody></table></div></section>';
    }

    // 9 — Recommended steps (guidance, no causation claim).
    html += '<section class="qa-card"><div class="qa-card-hd">' +
        __('Recommended review steps') + '</div>' +
        '<ul class="qa-steps">' +
        '<li>' + __('Verify the underlying data elements and recent uploads for this hospital/month') + '</li>' +
        '<li>' + __('Compare with the hospital\'s own explanation before concluding a data or care issue') + '</li>' +
        '<li>' + __('Record the investigation decision (note / status / assignee) below — the audit trail keeps every change') + '</li>' +
        '</ul></section>';

    // 10 — Investigation workflow (labelled fields, not placeholders only).
    const statuses = (_state.meta && _state.meta.statuses) || [];
    html += '<section class="qa-card"><div class="qa-card-hd">' + __('Investigation') + '</div>' +
        '<div class="qa-invest">' +
        '<label class="qa-field"><span>' + __('Status') + '</span>' +
        '<select id="qaDetailStatus">' +
        statuses.map(s => '<option value="' + esc(s) + '"' +
            (s === a.status ? ' selected' : '') + '>' + esc(_statusLabel(s)) + '</option>').join('') +
        '</select></label>' +
        '<label class="qa-field"><span>' + __('Assignee') + '</span>' +
        '<input id="qaDetailAssignee" type="text" value="' + esc(a.assignee || '') + '"></label>' +
        '<label class="qa-field qa-field-wide"><span>' + __('Note (optional)') + '</span>' +
        '<input id="qaDetailNote" type="text"></label>' +
        '</div>' +
        '<div class="qa-actions">' +
        '<button class="btn btn-sm qa-btn-primary" onclick="setQualityAlertStatus(' + a.id + ')">' +
        __('Save') + '</button>' +
        '<button class="btn btn-sm qa-btn-ghost" onclick="addQualityAlertNote(' + a.id + ')">' +
        __('Add note') + '</button>' +
        '</div></section>';

    // 11 — Audit trail of status changes / notes.
    if ((p.events || []).length) {
        html += '<section class="qa-card"><div class="qa-card-hd">' + __('Audit history') +
            '</div><div class="qa-table-wrap"><table class="qa-table"><thead><tr>' +
            ['Date', 'Actor', 'Change'].map(h => '<th>' + __(h) + '</th>').join('') +
            '</tr></thead><tbody>' +
            p.events.map(e => {
                const change = (e.from_status && e.to_status
                    ? esc(_statusLabel(e.from_status)) + ' → ' + esc(_statusLabel(e.to_status))
                    : (e.to_status ? esc(_statusLabel(e.to_status)) : __('note')));
                return '<tr><td>' + esc(_fmtDate(e.created_at)) + '</td>' +
                    '<td>' + esc(e.actor || 'system') + '</td>' +
                    '<td>' + change + (e.note ? ' — ' + esc(e.note) : '') + '</td></tr>';
            }).join('') +
            '</tbody></table></div></section>';
    }

    // 12 — Jumps to the screens that own the underlying data. Both open in a
    // NEW tab so this alert table keeps its filters and scroll position.
    const audit = p.audit_link || {};
    html += '<div class="qa-links">' +
        '<button class="btn btn-sm qa-btn-ghost" onclick="window.closeModal && window.closeModal(); window.openAuditTrailInNewTab && window.openAuditTrailInNewTab(' +
        esc(JSON.stringify({ kind: audit.kind || 'quality_score', hospitalId: audit.hospital_id, month: audit.month, indicatorCode: audit.indicator_code })) +
        ')">' + __('Open in Audit screen') + '</button>' +
        '<button class="btn btn-sm qa-btn-ghost" onclick="window.closeModal && window.closeModal(); window.openScreenInNewTab && window.openScreenInNewTab(\'indicators\')">' +
        __('Open Indicators registry') + '</button>' +
        '</div>';

    return html + '</div>';
}
_renderDetail.legend = {};

// ── Workflow actions ───────────────────────────────────────────────────
export async function setQualityAlertStatus(alertId) {
    const statusEl = document.getElementById('qaDetailStatus');
    const noteEl = document.getElementById('qaDetailNote');
    const assigneeEl = document.getElementById('qaDetailAssignee');
    if (!statusEl) return;
    const status = statusEl.value;
    try {
        await apiPostJSON('/quality-alerts/' + alertId + '/status', {
            status: status,
            note: noteEl && noteEl.value.trim() ? noteEl.value.trim() : null,
            assignee: assigneeEl ? assigneeEl.value : null,
        });
        if (window.closeModal) window.closeModal();
        await loadQualityAlerts();
        // Closing is not a data loss: say where the alert went, or the row
        // simply vanishing from the list looks like the update failed.
        if (status === 'Resolved' || status === 'False Positive') {
            const msg = __('Marked ') + _statusLabel(status) +
                __(' — it left the open alerts and stays available under Status.');
            if (window.toastSuccess) window.toastSuccess(msg); else alert(msg);
        }
    } catch (err) {
        alert(__('Failed to update status: ') + (err && err.message ? err.message : __('error')));
    }
}

export async function addQualityAlertNote(alertId) {
    const noteEl = document.getElementById('qaDetailNote');
    if (!noteEl || !noteEl.value.trim()) {
        alert(__('Type a note first.'));
        return;
    }
    try {
        await apiPostJSON('/quality-alerts/' + alertId + '/note', { note: noteEl.value.trim() });
        noteEl.value = '';
        alert(__('Note saved.'));
    } catch (err) {
        alert(__('Failed to save note: ') + (err && err.message ? err.message : __('error')));
    }
}

// ── CSV export (client-side, same pattern as the other screens) ────────
export function exportQualityAlertsCSV() {
    const issues = _state.issues;
    if (!issues.length) return;
    const headers = ['severity', 'hospital', 'indicator', 'indicator_code', 'current', 'baseline',
        'deviation_pct', 'perspectives', 'period', 'method', 'status', 'detected', 'confidence', 'interpretation'];
    // Codes, not labels: the export stays machine-readable (VERY_HIGH, Resolved).
    const rows = issues.map(issue => {
        const primary = (issue.perspectives || [])[0] || {};
        return [
            issue.primary_severity, issue.hospital, issue.indicator_name, issue.indicator_code,
            primary.current_value ?? '', primary.baseline_value ?? '', primary.deviation_pct ?? '',
            (issue.perspectives || []).map(p => p.perspective).join('|'),
            issue.month, primary.method || '', issue.status, issue.detected_at || '',
            issue.confidence || '', issue.interpretation || '',
        ];
    });
    const csv = [headers.join(','), ...rows.map(r =>
        r.map(c => '"' + String(c).replace(/"/g, '""') + '"').join(','))].join('\n');
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'quality-alerts-' + new Date().toISOString().slice(0, 10) + '.csv';
    a.click();
    URL.revokeObjectURL(url);
}

// ── Init ───────────────────────────────────────────────────────────────
export async function initQualityAlerts() {
    _installDetailModalA11y();
    if (_state.inited) { loadQualityAlerts(); return; }
    _state.inited = true;
    // Legend for the interpretation labels (bilingual from the server)
    try {
        const meta = await apiGet('/quality-alerts/meta');
        _state.meta = meta;
        _renderDetail.legend = {};
        Object.entries(meta.interpretation_legend || {}).forEach(([key, pair]) => {
            _renderDetail.legend[key] = currentLang === 'ar' ? (pair.ar || pair.en) : pair.en;
        });
        _renderPerspectiveChips(meta.perspectives || []);
        _fillSelect('qaStatusFilter', _statusFilterOptions(meta), __('Open only'));
    } catch (e) { /* meta optional — the screen still loads */ }
    await _loadOptions();
    loadQualityAlerts();
}
