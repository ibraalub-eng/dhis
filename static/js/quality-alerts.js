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
// This screen shows ONLY Very High (Red) alerts — every KPI, count and the
// issue table are scoped to them. Detection still records all severities
// server-side (audit trail intact); lower bands are simply not displayed.
const _PINNED_SEVERITY = 'VERY_HIGH';
const _state = {
    inited: false,
    page: 1,
    perspectives: new Set(),   // multi-select chips; empty = all
    meta: null,
    issues: [],
    issuesTotal: 0,           // grouped issues matching the filters (pager unit)
    summary: null,
};

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

// ── Filter query string ────────────────────────────────────────────────
function _filterQuery() {
    const p = new URLSearchParams();
    // Pinned severity: this screen is the Red-Alerts screen (see above).
    p.set('severity', _PINNED_SEVERITY);
    const pairs = [
        ['month', 'qaMonthFilter'], ['hospital_id', 'qaHospitalFilter'],
        ['indicator', 'qaIndicatorFilter'],
        ['indicator_type', 'qaIndicatorTypeFilter'],
        ['status', 'qaStatusFilter'], ['ownership_id', 'qaOwnershipFilter'],
        ['governorate_id', 'qaGovernorateFilter'],
        ['hospital_type_id', 'qaTypeFilter'],
    ];
    pairs.forEach(([param, id]) => {
        const el = document.getElementById(id);
        if (el && el.value) p.set(param, el.value);
    });
    const search = document.getElementById('qaSearchFilter');
    if (search && search.value.trim()) p.set('q', search.value.trim());
    const persps = [..._state.perspectives];
    if (persps.length === 1) p.set('perspective', persps[0]);
    else if (persps.length > 1) {
        // Multi-select: the server takes one perspective, so chip filtering
        // for >1 chips is applied client-side over the fetched page.
    }
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
        // Severity is pinned to VERY_HIGH — no severity dropdown on purpose.
        _fillSelect('qaStatusFilter', (metaR.statuses || []).map(s => ({ value: s, label: s })));
        _renderPerspectiveChips(metaR.perspectives || []);
    }
}

// ── Perspective chips ──────────────────────────────────────────────────
function _renderPerspectiveChips(perspectives) {
    const wrap = document.getElementById('qaPerspectiveChips');
    if (!wrap) return;
    wrap.innerHTML = perspectives.map(p => {
        const selectable = p.available !== false;
        return '<button data-perspective="' + esc(p.key) + '" ' +
            (selectable ? 'onclick="qualityAlertsTogglePerspective(this)"' : 'disabled title="' + esc(p.unavailable_reason || '') + '"') +
            ' class="badge ' + (selectable ? 'badge-muted' : 'badge-muted" style="opacity:0.45') +
            '" style="cursor:' + (selectable ? 'pointer' : 'not-allowed') + ';font-size:0.7rem;">' +
            esc(p.label) + (p.available === false ? ' — ' + __('not configured') : '') + '</button>';
    }).join('');
    const note = document.getElementById('qaPerspectiveNote');
    if (note) {
        const missing = perspectives.filter(p => p.available === false);
        note.textContent = missing.length
            ? missing.map(p => p.label + ': ' + (p.unavailable_reason || '')).join(' · ')
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
export function qualityAlertsFilterChanged() {
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

export async function loadQualityAlerts() {
    const loading = document.getElementById('qaLoading');
    if (loading) loading.classList.remove('hidden');
    try {
        const qs = _filterQuery();
        const [summary, issues] = await Promise.all([
            apiGet('/quality-alerts/summary' + (qs ? '?' + qs : '')),
            apiGet('/quality-alerts/issues?' + qs +
                (qs ? '&' : '') + 'page=' + _state.page + '&page_size=' + PAGE_SIZE +
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
            body.innerHTML = '<tr><td colspan="10" style="color:var(--accent-red);padding:1rem;">' +
                __('Error: ') + esc(err && err.message ? err.message : __('error')) + '</td></tr>';
        }
    } finally {
        if (loading) loading.classList.add('hidden');
    }
}

function _renderKpis(s) {
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    // Issue units: one card number per risk issue, matching the table's rows.
    // The row-level counts (total_active, red_alerts…) count comparison
    // perspectives, so they would overstate every card and the page count.
    // Every issue listed here is red by construction, so the useful split is
    // whether red came alone or alongside lower bands on the same issue.
    set('qaKpiRedOnly', s.red_only_issues ?? 0);
    set('qaKpiMixed', s.mixed_severity_issues ?? 0);
    set('qaKpiTotal', s.total_issues ?? 0);
    set('qaKpiHospitals', s.hospitals_affected ?? 0);
    set('qaKpiIndicators', s.indicators_affected ?? 0);
    set('qaKpiNew', s.new_issues ?? 0);
    set('qaKpiUnresolved', s.unresolved_issues ?? 0);
}

function _updateChipCounts(summary) {
    const counts = (summary && summary.by_perspective) || {};
    document.querySelectorAll('#qaPerspectiveChips [data-perspective]').forEach(btn => {
        const key = btn.getAttribute('data-perspective');
        const base = btn.textContent.replace(/\s*\(\d+\)\s*$/, '');
        const count = counts[key];
        if (count !== undefined) btn.textContent = base + ' (' + count + ')';
    });
}

// ── Table rendering ────────────────────────────────────────────────────
function _visibleIssues() {
    if (_state.perspectives.size <= 1) return _state.issues;
    // Multi-chip selection: the server filtered nothing (or one chip), so
    // narrow client-side by any perspective in the selection.
    return _state.issues.filter(issue =>
        (issue.perspectives || []).some(p => _state.perspectives.has(p.perspective)));
}

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

function _renderTable() {
    const body = document.getElementById('qaTableBody');
    const empty = document.getElementById('qaEmpty');
    if (!body) return;
    const issues = _visibleIssues();
    const count = document.getElementById('qaCount');
    if (count) count.textContent = issues.length + ' / ' + _state.issuesTotal;
    if (!issues.length) {
        body.innerHTML = '';
        if (empty) empty.style.display = '';
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
        const perspChips = (issue.perspectives || []).map(p =>
            '<span class="badge badge-muted" style="font-size:0.62rem;padding:0 4px;" title="' +
            esc((p.reason || '')) + '">' + esc(p.perspective_label || p.perspective) + '</span>').join(' ');
        // Open the STRONGEST perspective: alert_ids is id-ordered, so opening
        // [0] used to land on whichever perspective happened to be scanned
        // first — often history, whose detail has no peer group to show.
        return '<tr onclick="openQualityAlert(' +
            (primary.id || issue.alert_ids[0]) + ')" ' +
            'style="border-bottom:1px solid var(--border-default);cursor:pointer;">' +
            '<td style="padding:0.4rem;"><span class="' + sevBadge + '">' + esc(issue.primary_severity) + '</span>' + lowConf + staleBadge + '</td>' +
            '<td style="padding:0.4rem;">' + esc(issue.hospital) + '</td>' +
            '<td style="padding:0.4rem;">' + esc(issue.indicator_name) +
            ' <span style="color:var(--text-muted);font-size:0.68rem;">' + esc(issue.indicator_code) + '</span></td>' +
            '<td style="padding:0.4rem;">' + _fmtValue(primary.current_value, unit) + ' ' + interpIcon + '</td>' +
            '<td style="padding:0.4rem;">' + _fmtValue(primary.baseline_value, unit) +
            ' <span style="color:var(--text-muted);font-size:0.68rem;">' + esc(primary.perspective_label || '') + '</span></td>' +
            '<td style="padding:0.4rem;">' + _fmtPct(primary.deviation_pct) + '</td>' +
            '<td style="padding:0.3rem 0.4rem;">' + _sparkline(issue) + '</td>' +
            '<td style="padding:0.4rem;">' + perspChips + '</td>' +
            '<td style="padding:0.4rem;">' + esc(issue.month) + '</td>' +
            '<td style="padding:0.4rem;"><span class="badge ' + statusBadge + '">' + esc(issue.status) + '</span></td>' +
            '<td style="padding:0.4rem;">' + _fmtDate(issue.detected_at) + '</td>' +
            '</tr>';
    }).join('');
    _renderPager(_state.issuesTotal || issues.length);
}

function _renderPager(total) {
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    const info = document.getElementById('qaPageInfo');
    if (info) info.textContent = __('Page') + ' ' + _state.page + ' / ' + pages;
    const prev = document.getElementById('qaPrevBtn');
    const next = document.getElementById('qaNextBtn');
    if (prev) prev.disabled = _state.page <= 1;
    if (next) next.disabled = _state.page >= pages;
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
            label: trend.baseline_label || __('Baseline'),
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
            label: trend.baseline_label || __('Baseline'),
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
        '<span class="' + sevBadge + '">' + esc(a.severity) + '</span>' +
        (a.policy_state === 'stale'
            ? '<span class="badge badge-medium" title="' +
              esc(__('Computed under a different saved severity and trend policy than the one in effect now. The stored result is unchanged — re-run the scan to apply the current policy.')) +
              '">' + __('stale policy') + '</span>'
            : '') +
        '<span class="badge ' + (_STATUS_TONE[a.status] || 'badge-muted') + '">' + esc(a.status) + '</span>' +
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
        '<div class="qa-verdict-src">' + __('Flagged by') + ' <strong>' +
        esc(a.perspective_label) + '</strong> · ' + esc(_methodLabel(a.method)) +
        (n ? ' · ' + (isHistory ? __('baseline points') : __('peers')) + ': ' + esc(String(n)) : '') +
        '</div></div></div>';

    // 3 — The four numbers that define the finding (never duplicated below).
    html += '<div class="qa-kpis">' +
        _kpi(__('Current value'), _fmtValue(a.current_value, unit), esc(a.month)) +
        _kpi(__('Baseline'), _fmtValue(a.baseline_value, unit),
            esc(ev.baseline_label || a.perspective_label) +
            (n ? ' · ' + (isHistory ? __('months') : __('hospitals')) + ': ' + esc(String(n)) : '')) +
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
                : (ev.z_threshold != null
                    ? __('Threshold') + ' |z| ≥ ' + Number(ev.z_threshold).toFixed(2)
                    : '')) +
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
                    esc(trend.baseline_label || __('Baseline')) + '</span>'
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
                 label: ev.baseline_label || a.perspective_label,
                 peers: p.peers }]
            : []);
    let compRows = _kv(__('Method'), esc(_methodLabel(a.method))) +
        _kv(__('Comparison group'),
            esc(ev.baseline_label || a.perspective_label) +
            (n ? ' · ' + (isHistory ? __('months') : __('hospitals')) + ': ' + esc(String(n)) : '')) +
        _kv(__('Reporting period'), esc(a.month));
    if (ev.z_threshold != null) {
        compRows += _kv(__('Alert threshold'), '|z| ≥ ' + Number(ev.z_threshold).toFixed(2));
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
                    '<td>' + esc(s.perspective_label || s.perspective) +
                    (here ? ' <span class="qa-here">' + __('viewing') + '</span>' : '') + '</td>' +
                    '<td><span class="' + (_SEVERITY_BADGES[s.severity] || 'badge badge-muted') + '">' +
                    esc(s.severity) + '</span></td>' +
                    '<td>' + _fmtValue(s.current_value, unit) + '</td>' +
                    '<td>' + _fmtValue(s.baseline_value, unit) + '</td>' +
                    '<td>' + _fmtPct(s.deviation_pct) + '</td>' +
                    '<td>' + esc(_methodLabel(s.method)) + '</td>' +
                    '<td>' + esc(s.status) + '</td></tr>';
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
                '<td>' + esc(pa.perspective_label || pa.perspective) + '</td>' +
                '<td><span class="' + (_SEVERITY_BADGES[pa.severity] || 'badge badge-muted') + '">' +
                esc(pa.severity) + '</span></td>' +
                '<td>' + _fmtValue(pa.current_value, unit) + '</td>' +
                '<td>' + _fmtValue(pa.baseline_value, unit) + '</td>' +
                '<td>' + esc(pa.status) + '</td></tr>').join('') +
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
            (s === a.status ? ' selected' : '') + '>' + esc(s) + '</option>').join('') +
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
                    ? esc(e.from_status) + ' → ' + esc(e.to_status)
                    : (e.to_status ? esc(e.to_status) : __('note')));
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
        esc(JSON.stringify({ kind: audit.kind || 'quality_score', hospitalId: audit.hospital_id, month: audit.month })) +
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
    try {
        await apiPostJSON('/quality-alerts/' + alertId + '/status', {
            status: statusEl.value,
            note: noteEl && noteEl.value.trim() ? noteEl.value.trim() : null,
            assignee: assigneeEl ? assigneeEl.value : null,
        });
        if (window.closeModal) window.closeModal();
        await loadQualityAlerts();
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
    const issues = _visibleIssues();
    if (!issues.length) return;
    const headers = ['severity', 'hospital', 'indicator', 'indicator_code', 'current', 'baseline',
        'deviation_pct', 'perspectives', 'period', 'method', 'status', 'detected', 'confidence', 'interpretation'];
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
        _fillSelect('qaStatusFilter', (meta.statuses || []).map(s => ({ value: s, label: s })));
    } catch (e) { /* meta optional — the screen still loads */ }
    await _loadOptions();
    loadQualityAlerts();
}
