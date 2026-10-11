import { apiGet } from './api.js';
import { __ } from './i18n.js';
import { esc } from './tree.js';
import { classificationBadge } from './outliers.js';

// ── CSV export utility (same shape as outliers.js) ─────────────────
function downloadCSV(filename, headers, rows) {
    const csvContent = [headers.join(','), ...rows.map(r => r.map(c => '"' + String(c).replace(/"/g, '""') + '"').join(','))].join('\n');
    const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
}

function todayStr() {
    return new Date().toISOString().slice(0, 10);
}

const PAGE_SIZE = 50;
let _page = 1;
let _sort = 'month';
let _order = 'desc';
let _filtersInited = false;
const _indicatorOpts = new Map();

const _LEVEL_BADGES = {
    NONE: 'badge-muted', LOW: 'badge-low', MODERATE: 'badge-medium',
    HIGH: 'badge-high', VERY_HIGH: 'badge-critical',
};

function _filterQuery() {
    const hosp = document.getElementById('layeredHospitalFilter').value;
    const mon = document.getElementById('layeredMonthFilter').value;
    const ind = document.getElementById('layeredIndicatorFilter').value;
    const cls = document.getElementById('layeredClassificationFilter').value;
    const lvl = document.getElementById('layeredLevelFilter').value;
    const inv = document.getElementById('layeredInvestigationFilter').value;
    let q = '';
    if (hosp) q += 'hospital=' + hosp + '&';
    if (mon) q += 'month=' + encodeURIComponent(mon) + '&';
    if (ind) q += 'indicator=' + encodeURIComponent(ind) + '&';
    if (cls) q += 'classification=' + encodeURIComponent(cls) + '&';
    if (lvl) q += 'level=' + encodeURIComponent(lvl) + '&';
    if (inv) q += 'investigation=' + encodeURIComponent(inv) + '&';
    return q;
}

function _fmt(v) {
    return (v !== null && v !== undefined) ? Number(v).toFixed(2) : '--';
}

function _rawDelta(d) {
    if (d.raw_value === null || d.raw_value === undefined) return null;
    if (d.previous_value === null || d.previous_value === undefined || d.previous_value === 0) return null;
    return (d.raw_value - d.previous_value) / Math.abs(d.previous_value) * 100;
}

function _fmtDelta(v) {
    if (v === null || v === undefined) return '';
    return ' (' + (v >= 0 ? '+' : '') + Number(v).toFixed(1) + '%)';
}

function _deltaCsv(v) {
    if (v === null || v === undefined) return '';
    return (v >= 0 ? '+' : '') + Number(v).toFixed(1);
}

function _levelBadge(level) {
    const cls = _LEVEL_BADGES[level] || 'badge-muted';
    return '<span class="badge ' + cls + '">' + esc(level || 'NONE') + '</span>';
}

function populateSelectOptions(sel, values, currentVal) {
    const prevVal = sel.value;
    sel.innerHTML = '<option value="">All</option>';
    values.slice().sort().forEach(x => {
        const opt = document.createElement('option');
        opt.value = x; opt.textContent = x;
        sel.appendChild(opt);
    });
    sel.value = currentVal && values.includes(currentVal) ? currentVal : (prevVal && values.includes(prevVal) ? prevVal : '');
}

// Bootstrap the complete dropdowns once per tab session. Each fetch is
// isolated: a user without hospitals.read still gets months + rows, just an
// unpopulated hospital dropdown (all hospitals).
async function _initFilters() {
    if (_filtersInited) return;
    _filtersInited = true;
    try {
        const months = await apiGet('/analysis/months');
        if (Array.isArray(months)) {
            populateSelectOptions(document.getElementById('layeredMonthFilter'), months, '');
        }
    } catch (err) {
        console.warn('Layered month filter failed:', err);
    }
    try {
        const hosps = await apiGet('/hospitals/');
        const list = Array.isArray(hosps) ? hosps : [];
        const sel = document.getElementById('layeredHospitalFilter');
        const prevVal = sel.value;
        sel.innerHTML = '<option value="">All</option>';
        list.slice().sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''))).forEach(h => {
            const opt = document.createElement('option');
            opt.value = h.id; opt.textContent = h.name;
            sel.appendChild(opt);
        });
        sel.value = prevVal;
    } catch (err) {
        console.warn('Layered hospital filter failed:', err);
    }
}

// The indicator select has no endpoint: analysis codes come from
// build_analysis_specs (count = Indicator.code, rate = rate_*), so the rows
// themselves — which carry indicator_name — are the source. The map only
// grows, so returning to an earlier month keeps its options.
function _updateIndicatorOpts(data) {
    data.forEach(d => {
        if (d.analysis_code) _indicatorOpts.set(d.analysis_code, d.indicator_name || d.analysis_code);
    });
    const sel = document.getElementById('layeredIndicatorFilter');
    const prevVal = sel.value;
    sel.innerHTML = '<option value="">All</option>';
    Array.from(_indicatorOpts.entries())
        .sort((a, b) => a[1].localeCompare(b[1]))
        .forEach(([code, name]) => {
            const opt = document.createElement('option');
            opt.value = code; opt.textContent = name;
            sel.appendChild(opt);
        });
    sel.value = _indicatorOpts.has(prevVal) ? prevVal : '';
}

function _renderSummary(sum) {
    const el = document.getElementById('layeredSummary');
    if (!el) return;
    if (!sum || !sum.by_classification || !sum.by_classification.length) {
        el.innerHTML = '';
        return;
    }
    el.innerHTML = sum.by_classification.map(e =>
        '<span style="display:inline-flex;align-items:center;gap:0.3rem;">'
        + classificationBadge(e.outlier_type, '')
        + '<span style="font-weight:700;color:var(--text-muted);">' + e.count + '</span></span>'
    ).join('');
}

// Server-side sort: header click -> sort/order state -> re-query. First click
// on Month = newest first, first click elsewhere = asc (rule-failures idiom).
function wireLayeredSort() {
    document.querySelectorAll('#layeredTable th.sortable').forEach(th => {
        th.onclick = function () {
            const col = this.dataset.col;
            if (_sort === col) {
                _order = _order === 'asc' ? 'desc' : 'asc';
            } else {
                _sort = col;
                _order = col === 'month' ? 'desc' : 'asc';
            }
            _page = 1;
            loadLayered();
        };
    });
    document.querySelectorAll('#layeredTable th.sortable').forEach(h => {
        h.classList.remove('sort-asc', 'sort-desc');
        if (h.dataset.col === _sort) h.classList.add(_order === 'asc' ? 'sort-asc' : 'sort-desc');
    });
}

export function layeredFilterChange() {
    _page = 1;
    loadLayered();
}

export function layeredPage(delta) {
    const next = _page + delta;
    if (next < 1) return;
    _page = next;
    loadLayered();
}

export async function loadLayered() {
    _initFilters();   // fire-and-forget; selections are read independently
    const loadingEl = document.getElementById('layeredLoading');
    if (loadingEl) loadingEl.classList.remove('hidden');
    const tbody = document.getElementById('layeredTbody');
    tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:2rem;color:var(--text-muted);">Loading layered findings...</td></tr>';
    const month = document.getElementById('layeredMonthFilter').value;
    const url = '/analysis/layered?' + _filterQuery()
        + 'page=' + _page + '&page_size=' + PAGE_SIZE
        + '&sort=' + encodeURIComponent(_sort) + '&order=' + _order;
    try {
        const rows = await apiGet(url);
        let sum = null;
        try {
            sum = await apiGet('/analysis/layered/summary?' + (month ? 'month=' + encodeURIComponent(month) : ''));
        } catch (err) {
            console.warn('Layered summary failed:', err);
        }
        const data = rows.data || rows;
        window._lastLayeredData = data;
        _renderSummary(sum);
        _updateIndicatorOpts(data);
        const total = rows.total !== undefined ? rows.total : data.length;
        const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
        if (!data.length && _page > 1) {
            // The requested page ran past the end (rows changed under us):
            // land on the last real page instead of showing a phantom empty.
            _page = pages;
            return loadLayered();
        }
        document.getElementById('layeredCount').textContent = total + ' finding(s)';
        document.getElementById('layeredPageInfo').textContent = _page + ' / ' + pages;
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;color:var(--text-muted);">' + __('No layered findings for the selected criteria.') + '</td></tr>';
            wireLayeredSort();
            return;
        }
        tbody.innerHTML = data.map(d => {
            const rawCell = (d.raw_value !== null && d.raw_value !== undefined)
                ? _fmt(d.raw_value) + _fmtDelta(_rawDelta(d)) : '--';
            const rateCell = (d.rate !== null && d.rate !== undefined)
                ? _fmt(d.rate) + _fmtDelta(d.historical_change_percent) : '--';
            const denCell = (d.denominator !== null && d.denominator !== undefined)
                ? _fmt(d.denominator) + _fmtDelta(d.denominator_change_percent) : '--';
            const peerCell = (d.peer_outlier_score !== null && d.peer_outlier_score !== undefined)
                ? _fmt(d.peer_outlier_score) : '--';
            // Object form: the Task 15 dispatcher keys on kind + indicator_code.
            const whyBtn = '<button onclick="window.showWhyPopup({kind:\'layered_outlier\',hospitalId:'
                + Number(d.hospital_id)
                + ',month:' + JSON.stringify(String(d.month)).replace(/"/g, '&quot;')
                + ',indicatorCode:' + JSON.stringify(String(d.analysis_code)).replace(/"/g, '&quot;')
                + '})" title="' + __('Why') + '"'
                + ' style="background:none;border:1px solid var(--border-default,#ccc);border-radius:4px;padding:1px 7px;font-size:0.7rem;cursor:pointer;color:var(--accent-blue,#1565c0);font-weight:600;">\u2139\ufe0f ' + __('Why') + '</button>';
            return '<tr>' +
                '<td>' + esc(d.hospital) + '</td>' +
                '<td>' + esc(d.month) + '</td>' +
                '<td>' + esc(d.indicator_name || d.analysis_code || '') + '</td>' +
                '<td>' + rawCell + '</td>' +
                '<td>' + rateCell + '</td>' +
                '<td>' + denCell + '</td>' +
                '<td>' + peerCell + '</td>' +
                '<td>' + _levelBadge(d.outlier_level) + '</td>' +
                '<td>' + classificationBadge(d.outlier_type, d.interpretation) + '</td>' +
                '<td>' + whyBtn + '</td>' +
                '</tr>';
        }).join('');
        wireLayeredSort();
    } catch (err) {
        tbody.innerHTML = '<tr><td colspan="10" style="color:red;">Error: ' + err.message + '</td></tr>';
    } finally {
        if (loadingEl) loadingEl.classList.add('hidden');
    }
}

export async function exportLayeredCSV() {
    const btn = document.getElementById('layeredExportBtn');
    const label = btn ? btn.textContent : null;
    if (btn) { btn.disabled = true; btn.textContent = __('Exporting data...'); }
    // Re-query at the endpoint cap so the CSV is not silently truncated to
    // the loaded page (the rule-failures export pattern).
    const q = _filterQuery() + 'page=1&page_size=500&sort=' + encodeURIComponent(_sort) + '&order=' + _order;
    let data = window._lastLayeredData;
    try {
        const resp = await apiGet('/analysis/layered?' + q);
        const fetched = resp.data || resp;
        if (fetched.length) data = fetched;
    } catch (err) {
        console.warn('Layered export: full fetch failed, exporting loaded rows', err);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = label || 'Export CSV'; }
    }
    if (!data || !data.length) return;
    const headers = ['Hospital ID', 'Hospital', 'Month', 'Indicator', 'Indicator Name', 'Type',
        'Raw Value', 'Raw Delta %', 'Rate', 'Rate Delta %', 'Denominator', 'Denominator Delta %',
        'Peer Score', 'Level', 'Investigation', 'Interpretation'];
    const rows = data.map(d => [
        d.hospital_id || '',
        d.hospital || '',
        d.month || '',
        d.analysis_code || '',
        d.indicator_name || '',
        d.outlier_type || '',
        (d.raw_value !== null && d.raw_value !== undefined) ? Number(d.raw_value).toFixed(2) : '',
        _deltaCsv(_rawDelta(d)),
        (d.rate !== null && d.rate !== undefined) ? Number(d.rate).toFixed(2) : '',
        _deltaCsv(d.historical_change_percent),
        (d.denominator !== null && d.denominator !== undefined) ? Number(d.denominator).toFixed(2) : '',
        _deltaCsv(d.denominator_change_percent),
        (d.peer_outlier_score !== null && d.peer_outlier_score !== undefined) ? Number(d.peer_outlier_score).toFixed(2) : '',
        d.outlier_level || '',
        d.investigation_route || '',
        d.interpretation || ''
    ]);
    downloadCSV('layered_' + todayStr() + '.csv', headers, rows);
}