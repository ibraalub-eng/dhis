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

// ── Five-layer sparkline ──────────────────────────────────────────
// A mini severity strip per row: one square per detection layer colored by
// that layer's severity band, so the reviewer sees WHY before opening Why.
// Score→band mirrors BAND_CUTOFFS in app/engine/anomaly/layered.py (the
// first bound a score is <); colors reuse the level badge variables from
// styles.css so the strip and the Level column agree visually. The five
// score columns come straight from /analysis/layered (the endpoint returns
// every stored column), so this is pure client-side rendering.
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
    }    // الشارات التلخيصية هي فلاتر نفسها: النقر يضبط فلتر التصنيف (ويعيد
    // النقر على النشطة يزيله). حالة النشطة مشتقة من قيمة الفلتر نفسه
    // عند كل إعادة رسم في loadLayered، فلا تنفكّ التزامن أبدًا.
    const activeCls = (document.getElementById('layeredClassificationFilter') || {}).value || '';
    el.innerHTML = sum.by_classification.map(e => {
        const isActive = e.outlier_type && e.outlier_type === activeCls;
        return '<button type="button" data-classification="' + esc(e.outlier_type || '') + '"'
            + ' title="' + __('Filter by this classification') + '"'
            + ' style="display:inline-flex;align-items:center;gap:0.3rem;cursor:pointer;'
            + 'padding:0.05rem 0.35rem;border-radius:6px;'
            + 'border:1px solid ' + (isActive ? 'var(--accent-blue,#1565c0)' : 'transparent') + ';'
            + (isActive ? 'background:var(--bg-surface-hover,#f0f4f8);' : '')
            + '"'
            + '>'
            + classificationBadge(e.outlier_type, '')
            + '<span style="font-weight:700;color:var(--text-muted);">' + e.count + '</span></button>';
    }).join('');
    el.querySelectorAll('button[data-classification]').forEach(btn => {
        btn.onclick = function () {
            const sel = document.getElementById('layeredClassificationFilter');
            if (!sel) return;
            // Toggle: النقر على الشارة النشطة يعيد الجدول إلى «All».
            sel.value = (sel.value === this.dataset.classification) ? '' : this.dataset.classification;
            layeredFilterChange();
        };
    });
}

// ── Trend chart: raw value across months, adaptive to the filter ─────
// A raw value is only comparable within one indicator (one unit), so the
// chart needs a specific indicator and then plots the hospitals month by month
// (a single line when a hospital is also selected). Rendered with the global
// Plotly (loaded in index.html) to avoid importing smart/core.js, which
// installs document-level listeners on load.
let _trendCollapsed = false;

const _TREND_COLORS = {
    NORMAL: '#22c55e',
    POSSIBLE_DATA_ENTRY_ERROR: '#ef4444',
    CLINICAL_INVESTIGATION_REQUIRED: '#f59e0b',
    PEER_ANOMALY: '#3b82f6',
    VOLUME_DRIVEN_ANOMALY: '#d97706',
    RAW_VALUE_ANOMALY: '#f97316',
    RATE_ANOMALY: '#f97316',
    HISTORICAL_ANOMALY: '#a855f7',
};
// Light-theme fill palette: the bright dark-theme colors above have poor
// white-text contrast on light paper; these are their darker idols used by
// the classification legend (layered-faq) and the severity ink tokens.
const _TREND_COLORS_LIGHT = {
    NORMAL: '#15803d',
    POSSIBLE_DATA_ENTRY_ERROR: '#b91c1c',
    CLINICAL_INVESTIGATION_REQUIRED: '#b45309',
    PEER_ANOMALY: '#1d4ed8',
    VOLUME_DRIVEN_ANOMALY: '#92400e',
    RAW_VALUE_ANOMALY: '#c2410c',
    RATE_ANOMALY: '#c2410c',
    HISTORICAL_ANOMALY: '#6d28d9',
};
/** Theme-aware classification color: dark on surfaces, dark ink on light. */
function _typeColor(type) {
    const dark = document.documentElement.getAttribute('data-theme') !== 'light';
    const pal = dark ? _TREND_COLORS : _TREND_COLORS_LIGHT;
    return pal[type] || (dark ? '#6b7280' : '#9ca3af');
}
// Read the app's theme tokens for Plotly (it cannot resolve CSS variables).
function _plotlyThemeColors() {
    const cs = getComputedStyle(document.documentElement);
    const v = n => (cs.getPropertyValue(n) || '').trim() || undefined;
    return {
        text: v('--text-secondary'),
        muted: v('--text-muted'),
        line: v('--border-default'),
        bg: dark => v('--bg-base') || (dark ? '#0F1117' : '#F5F6F8'),
    };
}
// Theme change → recolor the heatmap grid and trend chart. Plots cache the
// theme at render time and Plotly cannot restyle via CSS, so re-render from
// the last data on [data-theme] mutations (see chart-utils.js precedent).
new MutationObserver(function () {
    if (document.getElementById('layeredHeatmapBody')) loadLayeredHeatmap();
    const ind = document.getElementById('layeredIndicatorFilter');
    if (ind && ind.value) loadLayeredTrend();
}).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

function _trendHint(msgKey) {
    const hint = document.getElementById('layeredTrendHint');
    const chart = document.getElementById('layeredTrendChart');
    if (hint) { hint.textContent = __(msgKey); hint.classList.remove('hidden'); }
    if (chart) {
        chart.style.display = 'none';
        if (window.Plotly) { try { Plotly.purge(chart); } catch (e) { /* noop */ } }
    }
}

function _renderLayeredTrend(body) {
    const hint = document.getElementById('layeredTrendHint');
    const chart = document.getElementById('layeredTrendChart');
    if (!chart || !window.Plotly) return;
    const series = (body && body.series) || [];
    if (!series.length) { _trendHint('No layered findings for the selected criteria.'); return; }
    if (hint) hint.classList.add('hidden');
    chart.style.display = '';
    const months = (body && body.months) || [];
    const traces = series.map(s => ({
        x: s.points.map(p => p.month),
        y: s.points.map(p => p.raw_value),
        name: s.name,
        type: 'scatter',
        mode: 'lines+markers',
        line: { width: 2 },
        marker: {
            size: 7,
            color: s.points.map(p => _typeColor(p.outlier_type)),
            line: { width: 1, color: _plotlyThemeColors().bg(false) },
        },
        hovertemplate: '%{x}<br>%{y:.2f}<extra>' + s.name + '</extra>',
    }));
    const _tc = _plotlyThemeColors();
    Plotly.react(chart, traces, {
        margin: { l: 48, r: 16, t: 12, b: 40 },
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: _tc.text },
        legend: { orientation: 'h', y: -0.2, x: 0.5, xanchor: 'center' },
        xaxis: { type: 'category', categoryorder: 'array', categoryarray: months, tickfont: { color: _tc.muted }, gridcolor: _tc.line },
        yaxis: { title: __('Raw value'), tickfont: { color: _tc.muted }, gridcolor: _tc.line },
    }, { responsive: true, displaylogo: false });
}

export async function loadLayeredTrend() {
    const ind = document.getElementById('layeredIndicatorFilter').value;
    if (!ind) { _trendHint('Select an indicator to view the trend.'); return; }
    try {
        const body = await apiGet('/analysis/layered/trend?' + _filterQuery());
        _renderLayeredTrend(body);
    } catch (err) {
        console.warn('Layered trend failed:', err);
    }
}

export function layeredTrendToggle() {
    _trendCollapsed = !_trendCollapsed;
    const bodyEl = document.getElementById('layeredTrendBody');
    const btn = document.getElementById('layeredTrendToggle');
    if (bodyEl) bodyEl.style.display = _trendCollapsed ? 'none' : '';
    if (btn) btn.textContent = _trendCollapsed ? __('Show') : __('Hide');
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

// ── Hospital × month heatmap: worst classification per cell ────────
// Same visual doctrine as the Quality Score heatmap (rules-manager.js):
// plain HTML grid, sticky hospital column, colored cells. Here the cell
// color is the worst classification present (severity order lives in the
// /analysis/layered/heatmap endpoint docstring); tooltip = per-type counts.
// Click = filter the table to that hospital+month.
function _renderLayeredHeatmap(body) {
    const bodyEl = document.getElementById('layeredHeatmapBody');
    if (!bodyEl) return;
    const data = (body && body.data) || [];
    const months = (body && body.months) || [];
    if (!data.length) {
        bodyEl.innerHTML = '<div style="font-size:0.8rem;color:var(--text-muted);padding:0.5rem 0;">'
            + __('No layered findings for the selected criteria.') + '</div>';
        return;
    }
    let html = '<table style="font-size:0.72rem;border-collapse:collapse;width:100%;"><thead><tr>'
        + '<th style="padding:0.3rem;text-align:left;position:sticky;left:0;background:var(--bg-surface);z-index:1;">'
        + __('Hospital') + '</th>';
    months.forEach(m => { html += '<th style="padding:0.3rem;text-align:center;min-width:64px;">' + esc(m) + '</th>'; });
    html += '</tr></thead><tbody>';
    data.forEach(d => {
        html += '<tr><td style="padding:0.2rem 0.4rem;font-weight:600;position:sticky;left:0;background:var(--bg-surface);z-index:1;">'
            + esc(d.hospital) + '</td>';
        months.forEach(m => {
            const c = d[m];
            if (!c) {
                html += '<td style="text-align:center;padding:0.2rem;background:var(--bg-surface);color:var(--text-muted);">·</td>';
                return;
            }
            const color = _typeColor(c.type);
            html += '<td onclick="window._layeredHeatmapClick(' + Number(d.hospital_id) + ',' + JSON.stringify(String(m))
                + ')" title="' + esc(d.hospital) + ' — ' + esc(m) + ' — '
                + Object.entries(c.breakdown || {}).map(([t, n]) => t + ':' + n).join(', ')
                + '" style="text-align:center;padding:0.2rem;background:' + color
                + ';color:#fff;font-weight:600;cursor:pointer;">' + c.count + '</td>';
        });
        html += '</tr>';
    });
    bodyEl.innerHTML = html;
}

window._layeredHeatmapClick = function (hospitalId, month) {
    const hsel = document.getElementById('layeredHospitalFilter');
    const msel = document.getElementById('layeredMonthFilter');
    if (hsel) hsel.value = String(hospitalId);
    if (msel) msel.value = month;
    layeredFilterChange();
};

export function loadLayeredHeatmap() {
    return apiGet('/analysis/layered/heatmap?' + _filterQuery())
        .then(body => _renderLayeredHeatmap(body))
        .catch(err => console.warn('Layered heatmap failed:', err));
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
    loadLayeredTrend();   // filter-driven chart; fire-and-forget
    loadLayeredHeatmap();   // worst-classification grid; fire-and-forget
    const loadingEl = document.getElementById('layeredLoading');
    if (loadingEl) loadingEl.classList.remove('hidden');
    const tbody = document.getElementById('layeredTbody');
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:2rem;color:var(--text-muted);">Loading layered findings...</td></tr>';
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
            tbody.innerHTML =                '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);">' + __('No layered findings for the selected criteria.') + '</td></tr>';
            wireLayeredSort();
            return;
        }
        tbody.innerHTML = data.map(d => {
            const rawCell = (d.raw_value !== null && d.raw_value !== undefined)
                ? _fmt(d.raw_value) + _fmtDelta(_rawDelta(d)) : '--';
            const rateCell = (d.rate !== null && d.rate !== undefined)
                ? _fmt(d.rate) + _fmtDelta(d.historical_change_percent) : '--';
            // Object form: the Task 15 dispatcher keys on kind + indicator_code.
            // Unified with every other screen: the shared modal in explain.js.
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
                '<td>' + _levelBadge(d.outlier_level) + '</td>' +
                '<td>' + classificationBadge(d.outlier_type, d.interpretation) + '</td>' +
                '<td>' + whyBtn + '</td>' +
                '</tr>';
        }).join('');
        wireLayeredSort();
    } catch (err) {
        tbody.innerHTML = '<tr><td colspan="8" style="color:red;">Error: ' + err.message + '</td></tr>';
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
        'Raw Value', 'Raw Delta %', 'Rate', 'Rate Delta %',
        'Level', 'Investigation', 'Interpretation'];
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
        // Rate Delta belongs with the rate cell: for count indicators rate is
        // NULL (their delta lives in Raw Delta %), so emitting the historical
        // delta here printed data with an empty Rate column — misleading CSV.
        (d.rate !== null && d.rate !== undefined) ? _deltaCsv(d.historical_change_percent) : '',
        d.outlier_level || '',
        d.investigation_route || '',
        d.interpretation || ''
    ]);
    downloadCSV('layered_' + todayStr() + '.csv', headers, rows);
}