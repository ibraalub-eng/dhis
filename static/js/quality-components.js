// quality-components.js — the per-component Quality Score screens.
//
// One page per Quality Score part (Completeness, Rule Compliance, Consistency)
// plus Confidence. Each page lists EVERY hospital-month in the user's scope, so
// a component can be reviewed across the network instead of one report at a
// time. Values come from /quality-components/{component}; nothing is computed
// here beyond sorting, filtering and the summary of the visible rows.
import { apiGet } from './api.js';
import { __ } from './i18n.js';
import { screenUrl } from './newtab.js';

const PAGES = {
    'quality-completeness': 'completeness',
    'quality-compliance': 'compliance',
    'quality-consistency': 'consistency',
    'quality-confidence': 'confidence',
};

// The component keys PAGES maps to — a caller may pass either form.
const PAGE_KEY_LIST = Object.keys(PAGES).map(function(k) { return PAGES[k]; });

const LEVEL_META = {
    on_target: { label: 'On target', color: '#2e7d32' },
    watch: { label: 'Watch', color: '#e65100' },
    below: { label: 'Below target', color: '#c62828' },
    high: { label: 'High', color: '#2e7d32' },
    medium: { label: 'Medium', color: '#e65100' },
    low: { label: 'Low', color: '#c62828' },
    critical: { label: 'Critical', color: '#8e0000' },
};

const LEVEL_ORDER = { critical: 0, below: 0, low: 1, watch: 1, medium: 2, on_target: 3, high: 3 };

const _state = {};

function esc(v) {
    return String(v == null ? '' : v)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _stateFor(key) {
    if (!_state[key]) {
        _state[key] = { data: null, month: 'all', hospital: 'all', declining: false, query: '', sortKey: 'value', sortDir: 'asc' };
    }
    return _state[key];
}

// ``type`` picks the renderer, ``get`` maps a column to a value the row does
// not expose under the same key (e.g. low+critical counts).
function _columns(key) {
    const base = [
        { k: 'hospital', label: 'Hospital', type: 'hospital' },
        { k: 'month', label: 'Month', type: 'text' },
        { k: 'value', label: key === 'confidence' ? 'Confidence' : 'Value', type: 'value' },
        { k: 'delta', label: 'Change vs previous month', type: 'delta' },
    ];
    if (key === 'confidence') {
        return base.concat([
            { k: 'level', label: 'Level', type: 'level' },
            { k: 'assessed', label: 'Assessments', type: 'count',
              get: function(r) { return r.indicator_count; } },
            { k: 'low_assessed', label: 'Low confidence', type: 'count',
              get: function(r) { return (r.low_count == null && r.critical_count == null)
                  ? null : (r.low_count || 0) + (r.critical_count || 0); } },
            { k: 'overall_score', label: 'Overall score', type: 'num' },
        ]);
    }
    return base.concat([
        { k: 'gap', label: 'Vs target', type: 'gap' },
        { k: 'level', label: 'Status', type: 'level' },
        { k: 'overall_score', label: 'Overall score', type: 'num' },
        { k: 'confidence', label: 'Confidence', type: 'num' },
    ]);
}

// The change column is derived from the payload itself: a row's value minus the
// same hospital's previous available month. No extra request is needed, and a
// hospital whose first shown month has no predecessor keeps a null change so it
// renders "—" instead of a misleading 0.
function _seriesByHospital(data) {
    const series = {};
    (data.rows || []).forEach(function(r) {
        if (r.value == null || !r.hospital || !r.month) return;
        if (!series[r.hospital]) series[r.hospital] = {};
        series[r.hospital][r.month] = Number(r.value);
    });
    return series;
}

function _deltaFor(row, series) {
    if (row.value == null || !row.hospital || !row.month) return null;
    const months = Object.keys(series[row.hospital] || {})
        .filter(function(m) { return m < row.month; })
        .sort();
    if (!months.length) return null;
    const previous = series[row.hospital][months[months.length - 1]];
    return Math.round((Number(row.value) - previous) * 10) / 10;
}

function _filteredRows(rows, st) {
    const q = st.query.trim().toLowerCase();
    return rows.filter(function(r) {
        if (st.month !== 'all' && r.month !== st.month) return false;
        if (st.hospital !== 'all' && r.hospital !== st.hospital) return false;
        if (st.declining && !(r.delta < 0)) return false;
        if (q && String(r.hospital || '').toLowerCase().indexOf(q) === -1) return false;
        return true;
    });
}

function _sortValue(row, col) {
    if (col.type === 'level') return LEVEL_ORDER[row.level] == null ? 9 : LEVEL_ORDER[row.level];
    if (col.get) return col.get(row);
    return row[col.k];
}

function _sortRows(rows, st, cols) {
    const dir = st.sortDir === 'asc' ? 1 : -1;
    const col = cols.find(function(c) { return c.k === st.sortKey; }) || cols[0];
    return rows.slice().sort(function(a, b) {
        const av = _sortValue(a, col);
        const bv = _sortValue(b, col);
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        if (typeof av === 'string' || typeof bv === 'string') {
            return String(av).localeCompare(String(bv)) * dir;
        }
        return (av - bv) * dir;
    });
}

function _summary(rows, key) {
    const isConfidence = key === 'confidence';
    let sum = 0;
    let valued = 0;
    let good = 0;
    let bad = 0;
    const hospitals = {};
    rows.forEach(function(r) {
        if (r.value != null) { sum += r.value; valued += 1; }
        if (isConfidence) {
            if (r.level === 'high') good += 1;
            else if (r.level === 'low' || r.level === 'critical') bad += 1;
        } else if (r.level === 'on_target') {
            good += 1;
        } else if (r.level === 'below') {
            bad += 1;
        }
        hospitals[r.hospital_id] = true;
    });
    return {
        average: valued ? Math.round((sum / valued) * 10) / 10 : null,
        good: good,
        bad: bad,
        count: rows.length,
        hospitals: Object.keys(hospitals).length,
    };
}

function _card(value, label, color) {
    return '<div class="kpi-card" style="padding:0.6rem 0.8rem;">'
        + '<div class="value" style="color:' + (color || 'var(--text-primary)') + ';">' + value + '</div>'
        + '<div class="label" data-i18n="' + esc(label) + '">' + esc(label) + '</div>'
        + '</div>';
}

function _levelBadge(level) {
    const meta = LEVEL_META[level];
    if (!meta) return '<span style="color:var(--text-muted);">—</span>';
    return '<span style="display:inline-flex;align-items:center;gap:0.3rem;font-size:0.75rem;color:'
        + meta.color + ';"><span style="width:7px;height:7px;border-radius:50%;background:'
        + meta.color + ';display:inline-block;"></span>'
        + '<span data-i18n="' + esc(meta.label) + '">' + esc(meta.label) + '</span></span>';
}

function _valueCell(row) {
    if (row.value == null) return '<span style="color:var(--text-muted);">—</span>';
    const meta = LEVEL_META[row.level];
    const color = meta ? meta.color : 'var(--accent-blue)';
    const width = Math.max(0, Math.min(100, Number(row.value)));
    return '<div style="display:flex;align-items:center;gap:0.45rem;min-width:110px;">'
        + '<strong style="color:' + color + ';min-width:44px;">' + esc(row.value) + '%</strong>'
        + '<div class="progress-bar" style="flex:1;height:5px;margin:0;">'
        + '<div class="progress-bar-fill" style="width:' + width + '%;background:' + color + ';"></div>'
        + '</div></div>';
}

function _gapCell(gap) {
    if (gap == null) return '<span style="color:var(--text-muted);">—</span>';
    const color = gap >= 0 ? '#2e7d32' : (gap >= -10 ? '#e65100' : '#c62828');
    return '<span style="color:' + color + ';font-weight:600;">' + (gap > 0 ? '+' : '') + esc(gap) + '</span>';
}

function _deltaCell(delta) {
    if (delta == null) return '<span style="color:var(--text-muted);">—</span>';
    if (delta === 0) return '<span style="color:var(--text-muted);font-weight:600;">0</span>';
    const up = delta > 0;
    const color = up ? '#2e7d32' : '#c62828';
    return '<span style="color:' + color + ';font-weight:600;white-space:nowrap;">'
        + (up ? '&#9650; ' : '&#9660; ') + (up ? '+' : '') + esc(delta) + '</span>';
}

// Each row drills into the hospital-month report the Quality Reports screen
// already knows how to open: screenUrl builds that screen's deep link, which
// applyBootScreen hands to openQualityReportFor. A row whose QualityScore row
// is missing (no valid report card) stays plain text.
function _reportLink(row) {
    if (!row.hospital) return '<span style="color:var(--text-muted);">—</span>';
    if (row.overall_score == null) return esc(row.hospital);
    const href = screenUrl('quality', { hospital: row.hospital, month: row.month });
    return '<a href="' + esc(href) + '" target="_blank" rel="noopener" '
        + 'title="' + esc(__('Open the Quality Report')) + '" '
        + 'style="color:var(--accent-blue);text-decoration:none;">'
        + esc(row.hospital)
        + ' <span style="font-size:0.7rem;opacity:0.7;" aria-hidden="true">&#8599;</span></a>';
}

function _cell(row, col) {
    if (col.type === 'hospital') return _reportLink(row);
    if (col.type === 'value') return _valueCell(row);
    if (col.type === 'level') return _levelBadge(row.level);
    if (col.type === 'gap') return _gapCell(row.gap);
    if (col.type === 'delta') return _deltaCell(row.delta);
    const v = col.get ? col.get(row) : row[col.k];
    if (v == null) return '<span style="color:var(--text-muted);">—</span>';
    return col.type === 'num' ? esc(v) + '%' : esc(v);
}

function _paint(root, key) {
    const st = _stateFor(key);
    const data = st.data;
    if (!data) return;
    const cols = _columns(key);
    const series = _seriesByHospital(data);
    const withDelta = (data.rows || []).map(function(r) {
        return Object.assign({}, r, { delta: _deltaFor(r, series) });
    });
    const rows = _filteredRows(withDelta, st);
    const sorted = _sortRows(rows, st, cols);
    const summary = _summary(rows, key);
    const isConfidence = key === 'confidence';

    const summaryEl = root.querySelector('[data-qc-summary]');
    if (summaryEl) {
        const avgText = summary.average == null ? '—' : summary.average + '%';
        const goodLabel = isConfidence ? 'High confidence' : 'On target';
        const badLabel = isConfidence ? 'Low confidence' : 'Below target';
        summaryEl.innerHTML =
            _card(avgText, 'Average')
            + _card(summary.good, goodLabel, '#2e7d32')
            + _card(summary.bad, badLabel, '#c62828')
            + _card(summary.count, 'Hospital-months')
            + _card(summary.hospitals, 'Hospitals');
    }

    const countEl = root.querySelector('[data-qc-count]');
    if (countEl) {
        countEl.textContent = sorted.length + ' / ' + (data.rows || []).length;
    }

    const tableEl = root.querySelector('[data-qc-table]');
    if (!tableEl) return;
    if (!sorted.length) {
        tableEl.innerHTML = '<div class="card" style="padding:1.5rem;text-align:center;color:var(--text-muted);">'
            + '<div style="font-size:1.5rem;margin-bottom:0.4rem;opacity:0.4;">&#128202;</div>'
            + '<div data-i18n="No results match the current filters.">No results match the current filters.</div>'
            + '</div>';
        if (typeof window.applyLang === 'function') window.applyLang();
        return;
    }

    let html = '<div class="card" style="padding:0.4rem 0.6rem;overflow-x:auto;">'
        + '<table style="width:100%;border-collapse:collapse;font-size:0.78rem;">'
        + '<thead><tr style="border-bottom:2px solid var(--border-default);text-align:start;color:var(--text-secondary);">';
    cols.forEach(function(col) {
        const active = st.sortKey === col.k;
        const arrow = active ? (st.sortDir === 'asc' ? ' \u25B2' : ' \u25BC') : '';
        html += '<th scope="col" data-sort="' + col.k + '" title="' + esc(__('Sort by') + ' ' + col.label)
            + '" style="padding:0.4rem;cursor:pointer;white-space:nowrap;text-align:start;'
            + (active ? 'color:var(--accent-blue);' : '') + '">'
            + '<span data-i18n="' + esc(col.label) + '">' + esc(col.label) + '</span>' + arrow + '</th>';
    });
    html += '</tr></thead><tbody>';
    sorted.forEach(function(row) {
        html += '<tr style="border-bottom:1px solid var(--border-default);">';
        cols.forEach(function(col) {
            html += '<td style="padding:0.35rem 0.4rem;">' + _cell(row, col) + '</td>';
        });
        html += '</tr>';
    });
    html += '</tbody></table></div>';
    tableEl.innerHTML = html;
    if (typeof window.applyLang === 'function') window.applyLang();
}

function _shell(root, key, data) {
    const st = _stateFor(key);
    const isConfidence = key === 'confidence';
    const weight = data.weight == null ? null : Math.round(data.weight * 1000) / 10;
    const notes = [];
    if (weight != null) notes.push(__('Weight in the Quality Score') + ': ' + weight + '%');
    if (data.target != null) notes.push(__('Target') + ': ' + data.target + '%');
    if (data.excluded_failed) {
        notes.push(data.excluded_failed + ' ' + __('failed analysis row(s) excluded'));
    }
    const months = (data.months || []).slice().sort().reverse();
    const hospitals = [];
    const seenHospitals = {};
    (data.rows || []).forEach(function(r) {
        if (!r.hospital || seenHospitals[r.hospital]) return;
        seenHospitals[r.hospital] = true;
        hospitals.push(r.hospital);
    });
    hospitals.sort();
    root.innerHTML =
        '<div style="display:flex;flex-wrap:wrap;gap:0.4rem;align-items:center;margin-bottom:0.7rem;'
        + 'font-size:0.78rem;color:var(--text-secondary);">'
        + '<span data-i18n="' + esc(data.label) + '">' + esc(data.label) + '</span>'
        + (notes.length ? '<span style="color:var(--text-muted);">·</span><span>'
            + notes.map(esc).join(' · ') + '</span>' : '')
        + '</div>'
        + '<div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.8rem;">'
        + '<span data-i18n="' + esc(data.description) + '">' + esc(data.description) + '</span></div>'
        + '<div data-qc-summary style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));'
        + 'gap:0.6rem;margin-bottom:1rem;"></div>'
        + '<div class="card" style="padding:0.55rem 0.75rem;margin-bottom:0.8rem;">'
        + '<div style="display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap;">'
        + '<label for="qcMonth-' + key + '" style="font-size:0.75rem;color:var(--text-secondary);" data-i18n="Month">Month</label>'
        + '<select id="qcMonth-' + key + '" data-qc-filter="month" style="font-size:0.78rem;padding:0.2rem 0.4rem;">'
        + '<option value="all" data-i18n="All months">All months</option>'
        + months.map(function(m) { return '<option value="' + esc(m) + '">' + esc(m) + '</option>'; }).join('')
        + '</select>'
        + '<label for="qcHospital-' + key + '" style="font-size:0.75rem;color:var(--text-secondary);" data-i18n="Hospital">Hospital</label>'
        + '<select id="qcHospital-' + key + '" data-qc-filter="hospital" style="font-size:0.78rem;padding:0.2rem 0.4rem;max-width:220px;">'
        + '<option value="all" data-i18n="All hospitals">All hospitals</option>'
        + hospitals.map(function(h) { return '<option value="' + esc(h) + '">' + esc(h) + '</option>'; }).join('')
        + '</select>'
        + '<label style="display:inline-flex;align-items:center;gap:0.3rem;font-size:0.75rem;'
        + 'color:var(--text-secondary);cursor:pointer;">'
        + '<input type="checkbox" data-qc-filter="declining" style="margin:0;">'
        + '<span data-i18n="Declining only">Declining only</span></label>'
        + '<input data-qc-filter="search" type="text" value="' + esc(st.query) + '" '
        + 'placeholder="' + esc(__('Search hospital')) + '" aria-label="' + esc(__('Search hospital'))
        + '" style="font-size:0.78rem;padding:0.25rem 0.5rem;min-width:180px;border:1px solid var(--border-default);'
        + 'border-radius:4px;background:var(--bg-elevated);color:var(--text-primary);">'
        + '<span style="margin-inline-start:auto;font-size:0.72rem;color:var(--text-muted);" data-qc-count></span>'
        + '</div></div>'
        + '<div data-qc-table></div>'
        + '<div style="font-size:0.68rem;color:var(--text-muted);margin-top:0.5rem;" data-i18n="'
        + esc(isConfidence
            ? 'Confidence is a separate reliability score, not a weighted part of the Quality Score.'
            : 'Values are the stored Quality Score components; completeness is recalculated at read time.')
        + '">'
        + esc(isConfidence
            ? 'Confidence is a separate reliability score, not a weighted part of the Quality Score.'
            : 'Values are the stored Quality Score components; completeness is recalculated at read time.')
        + '</div>';
    st.month = 'all';
    st.hospital = 'all';
    st.declining = false;
    _paint(root, key);
}

function _bind(root, key) {
    if (root.dataset.qcBound === '1') return;
    root.dataset.qcBound = '1';
    root.addEventListener('change', function(e) {
        if (e.target.matches('[data-qc-filter="month"]')) {
            _stateFor(key).month = e.target.value;
        } else if (e.target.matches('[data-qc-filter="hospital"]')) {
            _stateFor(key).hospital = e.target.value;
        } else if (e.target.matches('[data-qc-filter="declining"]')) {
            _stateFor(key).declining = e.target.checked;
        } else {
            return;
        }
        _paint(root, key);
    });
    root.addEventListener('input', function(e) {
        if (!e.target.matches('[data-qc-filter="search"]')) return;
        _stateFor(key).query = e.target.value;
        _paint(root, key);
    });
    root.addEventListener('click', function(e) {
        const th = e.target.closest('th[data-sort]');
        if (!th) return;
        const st = _stateFor(key);
        const k = th.getAttribute('data-sort');
        if (st.sortKey === k) {
            st.sortDir = st.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
            st.sortKey = k;
            st.sortDir = 'asc';
        }
        _paint(root, key);
    });
}

async function _load(root, key) {
    const st = _stateFor(key);
    try {
        const data = await apiGet('/quality-components/' + key);
        st.data = data;
        _shell(root, key, data);
    } catch (err) {
        root.innerHTML = '<div class="card" style="padding:1.5rem;text-align:center;color:var(--accent-red);">'
            + esc(err && err.message ? err.message : __('Unable to load this component'))
            + '</div>';
    }
}

/**
 * Mount one component page inside any container. ``key`` is either the
 * component key (completeness, compliance, …) or the tab name that owns it.
 * The merged Validation Result screen uses this to show the compliance view in
 * one of its own sub-tabs.
 */
export function mountQualityComponent(root, key) {
    const compKey = PAGE_KEY_LIST.indexOf(key) !== -1 ? key : PAGES[key];
    if (!root || !compKey) return;
    if (root.dataset.qcMounted === '1') return;
    root.dataset.qcMounted = '1';
    // The container ships its own spinner; replace it once data arrives.
    _bind(root, compKey);
    _load(root, compKey);
}

/**
 * Mount the component page that is currently active. Called from main.js when
 * one of the four quality-component tabs is opened.
 */
export function initQualityComponents() {
    const pane = document.querySelector('.tab-content.active');
    if (!pane) return;
    // The pane id carries the loader's ``tab-`` prefix (tab-quality-completeness);
    // PAGES is keyed by the tab name switchTab uses, so drop it before lookup.
    const key = PAGES[String(pane.id || '').replace(/^tab-/, '')];
    if (!key) return;
    mountQualityComponent(pane.querySelector('[data-qc-component]'), key);
}
