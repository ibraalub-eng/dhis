/**
 * explain.js — shared "Why?" popup for every derived number.
 *
 * One popup, reused by every screen (trend points, heatmap cells, outlier
 * rows, drilldown rows, failed rules). It calls GET /audit/explain and
 * renders a slim DIGEST:
 *   what (finding) → classification badge → where (hospital/indicator/month)
 *   → why (triggered rule/threshold) → data-problem examples (≤3)
 *   → how (readable formula; inputs collapsed) → ✓/✗ verified verdict
 *
 * Single source of truth (no duplicated knowledge): the popup is a DIGEST.
 * The full step-by-step verification — inputs table expanded, expected vs
 * stored numbers, traceability chain, full data-problem sweep, component
 * contributions, recommendations — lives ONCE, on the Audit screen. Every
 * popup ends with ONE pointer that opens that screen pre-selected on the
 * same hospital/month (mode 'why' scrolls to its traceability chain).
 *
 * Usage:
 *   import { showWhyPopup } from './explain.js';
 *   showWhyPopup({ kind: 'quality_score', hospitalId: 5, month: '2026-04' });
 *   showWhyPopup({ kind: 'anomaly', hospitalId: 5, month: '2026-04', rateName: 'C-section rate' });
 *   showWhyPopup({ kind: 'rule', hospitalId: 5, month: '2026-04', ruleCode: 'R010' });
 *
 * Buttons can use the global helper (no imports needed in inline onclick):
 *   onclick="window.showWhyPopup('anomaly', 5, '2026-04', 'C-section rate')"
 */
import { apiGet } from './api.js';
import { __, currentLang } from './i18n.js';
import { localizeProse } from './explain-prose.js';
import { esc } from './tree.js';
import { openScreenInNewTab } from './newtab.js';

let _modalEl = null;
let _lastOpts = null; // context of the popup currently open (for the audit jump)

function _ensureModal() {
    if (_modalEl) return _modalEl;
    _modalEl = document.createElement('div');
    _modalEl.id = 'explainModalOverlay';
    _modalEl.style.cssText = 'position:fixed;inset:0;z-index:3000;background:rgba(0,0,0,0.45);display:none;align-items:flex-start;justify-content:center;padding:3rem 1rem;overflow:auto;';
    _modalEl.innerHTML =
        '<div id="explainModalDialog" style="background:var(--bg-surface,#fff);color:var(--text-primary,#222);border:1px solid var(--border-default,#ccc);border-radius:10px;max-width:min(720px,94vw);width:100%;min-width:0;overflow-wrap:break-word;box-shadow:0 8px 32px rgba(0,0,0,0.35);">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;gap:0.5rem;padding:0.7rem 1rem;border-bottom:1px solid var(--border-default,#ddd);">' +
        '<div style="display:flex;align-items:center;gap:0.6rem;min-width:0;">' +
        '<div style="font-weight:700;font-size:0.95rem;">\u2753 ' + __('Why? — How was this number produced?') + '</div>' +
        '<span id="explainBuildStamp" style="font-size:0.62rem;color:var(--text-muted,#888);font-family:monospace;direction:ltr;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="' + __('Data epoch — same stamp means the same snapshot of the data') + '"></span>' +
        '</div>' +
        // Generous hit-area + fixed size so the ✕ is never a 1-2px target and
        // never shifts under RTL float rules (the .modal-close class floats —
        // this one is a plain flex child instead).
        '<button id="explainModalClose" aria-label="' + __('Close') + '" title="' + __('Close') +
        '" style="flex:0 0 auto;width:34px;height:34px;min-width:34px;min-height:34px;display:inline-flex;align-items:center;justify-content:center;background:none;border:1px solid transparent;border-radius:8px;font-size:1.15rem;line-height:1;cursor:pointer;color:var(--text-muted,#888);">\u2715</button>' +
        '</div>' +
        '<div id="explainModalBody" style="padding:0.9rem 1rem;font-size:0.8rem;line-height:1.5;"></div>' +
        '</div>';
    document.body.appendChild(_modalEl);
    // Close on: the ✕ button, clicks on the dark backdrop itself, Escape.
    // All three are delegated from the overlay so re-rendered inner HTML can
    // never orphan a listener — this is what made ✕ feel "dead" before:
    // the button had NO click handler wired at all (only backdrop/Esc worked).
    _modalEl.addEventListener('click', function (e) {
        if (e.target === _modalEl) { closeWhyPopup(); return; }
        const btn = e.target.closest && e.target.closest('#explainModalClose');
        if (btn && _modalEl.contains(btn)) { e.preventDefault(); e.stopPropagation(); closeWhyPopup(); }
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && _modalEl && _modalEl.style.display === 'flex') closeWhyPopup();
    });
    return _modalEl;
}

export function closeWhyPopup() {
    // Defensive close: hide the live element AND any stale clone that might
    // exist after a hot reload / tab re-import, then blur focus out of the
    // removed subtree so Escape keeps working on the page beneath.
    const els = document.querySelectorAll('#explainModalOverlay');
    els.forEach(function (el) { el.style.display = 'none'; });
    if (_modalEl) _modalEl.style.display = 'none';
    try { if (document.activeElement && _modalEl && _modalEl.contains(document.activeElement)) document.activeElement.blur(); } catch (e) { /* non-fatal */ }
}

function _buildExplainQuery(opts) {
    let q = '?kind=' + encodeURIComponent(opts.kind);
    // Month-overview digests (trend point with "All Hospitals") send no
    // hospital_id at all — the dispatcher routes them to explain_month_overview.
    // The Comparative Analysis kinds pass a string context here instead of
    // a number ('Hospital|Rate', a governorate or a rate name).
    if (opts.hospitalId !== undefined && opts.hospitalId !== null && opts.hospitalId !== 'null') {
        q += '&hospital_id=' + encodeURIComponent(opts.hospitalId);
    }
    if (opts.month) q += '&month=' + encodeURIComponent(opts.month);
    if (opts.rateName) q += '&rate_name=' + encodeURIComponent(opts.rateName);
    if (opts.indicatorCode) q += '&indicator_code=' + encodeURIComponent(opts.indicatorCode);
    if (opts.ruleCode) q += '&rule_code=' + encodeURIComponent(opts.ruleCode);
    // Component-specific sparkline (attention-strip component anomalies):
    // shows THIS component's own history, not the overall score's.
    if (opts.component) q += '&component=' + encodeURIComponent(opts.component);
    return q;
}

function _explainErrorHtml(err) {
    return '<div style="color:var(--accent-red,#c62828);padding:0.5rem;">'
        + '\u26a0\ufe0f ' + __('No explanation available') + ': ' + esc(err && err.message ? err.message : 'error')
        + '<div style="margin-top:0.4rem;color:var(--text-muted,#888);font-size:0.72rem;">'
        + __('The underlying result row may not exist for this hospital/month.') + '</div></div>';
}

/**
 * Render the Why explanation into the persistent side panel. The panel is
 * created once and re-used: navigating rows only swaps the body content.
 */
function _classificationBadge(cls) {
    if (!cls) return '';
    const map = {
        data_problem: { icon: '🔧', label: __('Data problem'), color: 'var(--accent-orange,#e65100)' },
        statistical_finding: { icon: '📊', label: __('Statistical finding'), color: 'var(--accent-blue,#1565c0)' },
        clinical_finding: { icon: '🏥', label: __('Clinical finding'), color: 'var(--accent-purple,#7b1fa2)' },
    };
    const m = map[cls];
    if (!m) return '';
    return '<span style="display:inline-flex;align-items:center;gap:4px;border:1px solid ' + m.color + ';color:' + m.color +
        ';border-radius:12px;padding:2px 10px;font-size:0.7rem;font-weight:700;">' + m.icon + ' ' + esc(m.label) + '</span>';
}

function _sectionTitle(text) {
    return '<div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0.04em;color:var(--text-muted,#888);margin:0.8rem 0 0.3rem;padding-bottom:0.15rem;border-bottom:1px solid var(--border-default,#eee);">' + esc(text) + '</div>';
}

function _kvRows(rows) {
    if (!rows || !rows.length) return '';
    return rows.map(r =>
        // Both columns may shrink and wrap: a sentence-valued row (the
        // cross-check list) is long, and flex-shrink:0 made it claim its whole
        // max-content width, collapsing the label and scrolling the page.
        '<div style="display:flex;justify-content:space-between;align-items:baseline;gap:0.8rem;padding:0.12rem 0;border-bottom:1px dashed var(--border-default,#eee);">' +
        '<span style="color:var(--text-secondary,#555);flex:0 1 auto;min-width:0;overflow-wrap:anywhere;">' + esc(String(r.input)) + '</span>' +
        '<span style="font-weight:600;text-align:end;unicode-bidi:plaintext;flex:0 1 auto;min-width:0;max-width:70%;overflow-wrap:anywhere;">' + esc(r.value === null || r.value === undefined ? '--' : String(r.value)) + '</span>' +
        '</div>'
    ).join('');
}


// Reproduce block — DIGEST level: only the ✓/✗ independent-check verdict and
// an optional note. The numbers behind the verdict (expected vs stored, z
// recomputation, weighted contributions) are the Audit screen's job (req:
// nothing audit-verified is duplicated in the popup).
function _renderReproduce(p) {
    const r = p.reproduce;
    if (!r) return '';
    let html = '';
    if (r.verified === true) {
        html += '<div style="margin-top:0.3rem;color:var(--accent-green,#2e7d32);font-weight:700;">\u2705 ' + __('Verified — the number reproduces exactly from the source data') + '</div>';
    } else if (r.verified === false) {
        html += '<div style="margin-top:0.3rem;color:var(--accent-red,#c62828);font-weight:700;">\u274c ' + __('Not verified — recomputed value differs from the stored one (configuration may have changed after analysis)') + '</div>';
    }
    if (r.note) {
        html += '<div style="margin-top:0.3rem;color:var(--text-muted,#888);font-size:0.72rem;">' + esc(_prose(r.note)) + '</div>';
    }
    return html;
}

// Digest footer: ONE pointer into the Audit screen — the single source of
// truth for verification — instead of repeating its content in the popup.
function _renderAuditScreenLink() {
    const trailLabel = currentLang === 'ar' ? '\u0639\u0631\u0636 \u0627\u0644\u0645\u0633\u0627\u0631 \u0627\u0644\u0643\u0627\u0645\u0644' : 'View full trail';
    return '<div data-explain-footer style="display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap;margin-top:0.9rem;padding:0.55rem 0.7rem;border-top:1px solid var(--border-default,#ddd);">' +
        '<span style="font-size:0.72rem;color:var(--text-muted,#888);">' + __('Digest only — every number here is verified step-by-step on the Audit screen') + '</span>' +
        '<button onclick="window._explainJumpFooter()" style="background:var(--accent-blue,#1565c0);color:#fff;border:none;border-radius:4px;padding:4px 12px;font-size:0.72rem;font-weight:700;cursor:pointer;white-space:nowrap;">' + __('Open in audit screen') + ' \u2192</button>' +
        '<button data-explain-trail onclick="window._explainJumpTrail()" style="background:transparent;color:var(--accent-blue,#1565c0);border:1px solid var(--accent-blue,#1565c0);border-radius:4px;padding:4px 12px;font-size:0.72rem;font-weight:700;cursor:pointer;white-space:nowrap;">' + trailLabel + ' \u2192</button>' +
        '</div>';
}

// The rules that actually FAILED for this hospital-month. The score only
// carries a rule-compliance percentage, so without this section a hospital
// can read "all components meet their targets" while rules are failing.
// Each code re-opens the popup on kind=rule (its own calculation).
function _renderFailedRules(p) {
    const rows = p.failed_rules || [];
    if (!rows.length) return '';
    const colors = { CRITICAL: '#b71c1c', HIGH: '#c62828', MEDIUM: '#e65100', LOW: '#1565c0' };
    const icons = { CRITICAL: '\u26a0', HIGH: '\u26a0', MEDIUM: '\u26a1', LOW: '\u2139' };
    const hid = p.hospital_id !== undefined && p.hospital_id !== null ? p.hospital_id : 'null';
    let html = _sectionTitle(__('Failed rules') + ' (' + rows.length + ')');
    html += rows.slice(0, 10).map(function (r) {
        const sev = (r.severity || '').toUpperCase();
        const col = colors[sev] || '#888';
        const ico = icons[sev] || '\u2139';
        const code = String(r.rule_code || '');
        // Aggregate digests (month overview) carry the failing hospital on the
        // row itself; hospital-level digests use the popup's own hospital.
        const rowHid = (r.hospital_id !== undefined && r.hospital_id !== null) ? Number(r.hospital_id) : Number(hid);
        const chip = code
            ? '<span style="background:' + col + ';color:#fff;padding:1px 5px;border-radius:3px;font-size:0.58rem;font-weight:700;cursor:pointer;flex-shrink:0;" ' +
                'onclick="window.showWhyPopup(\'rule\',' + rowHid + ',\'' + esc(String(p.month || '')) + '\',null,\'' +
                code.replace(/\\/g, '\\\\').replace(/'/g, "\\'") + '\')" ' +
                'title="' + __('Why? — formula, inputs, reproduction for this rule') + '">' + esc(code) + '</span>'
            : '';
        return '<div style="padding:0.3rem 0.5rem;margin:0.15rem 0;background:var(--bg-elevated,#f5f5f5);border-radius:4px;">' +
            '<div style="display:flex;align-items:center;gap:0.4rem;flex-wrap:wrap;">' +
            '<span style="color:' + col + ';font-weight:700;flex-shrink:0;">' + ico + '</span>' + chip +
            (r.hospital ? '<span style="font-size:0.66rem;color:var(--text-muted,#888);font-weight:600;">' + esc(r.hospital) + '</span>' : '') +
            '<span style="font-size:0.74rem;line-height:1.45;overflow-wrap:anywhere;">' +
            // The rule NAME and its details are catalog text: a registered
            // shape is localized, anything else keeps the catalog's own wording
            // (machine codes made readable).
            esc(_prose(r.rule_name || r.rule_description || code)) + '</span></div>' +
            (r.details ? '<div style="font-size:0.72rem;color:var(--text-secondary,#555);margin-top:0.15rem;line-height:1.5;overflow-wrap:anywhere;">' +
                esc(_prose(r.details)) + '</div>' : '') +
            '</div>';
    }).join('');
    if (rows.length > 10) {
        html += '<div style="font-size:0.72rem;color:var(--text-muted,#888);margin:0.15rem 0 0;">' +
            __('... and {n} more').replace('{n}', rows.length - 10) + '</div>';
    }
    return html;
}

// Anomaly context: the hospital's own recent score trend as an inline
// sparkline — a drop/jump/drift is only meaningful against this baseline.
// Same-epoch data, rendered inline so no extra request is needed.
function _renderScoreTrend(p) {
    if (!p.score_trend || p.score_trend.length < 2) return '';
    const pts = p.score_trend;
    // Component label (component anomalies show their own series, so the
    // title must say which one is plotted).
    var _compLabels = { quality_score: __('Quality Score'), rule_compliance: __('Validation rule'), completeness: __('Completeness'), consistency: __('Consistency'), outlier_score: __('Outlier Score') };
    var _comp = (p.component && p.component !== 'quality_score') ? (_compLabels[p.component] || p.component) : null;
    const _trendTitle = __('Recent score trend') + (_comp ? ' \u00b7 ' + _comp : '') + ' (' + pts.length + ' ' + __('months') + ')';
    const W = 190, H = 36, PAD = 4;
    let lo = Math.min.apply(null, pts.map(function (d) { return d.score; }));
    let hi = Math.max.apply(null, pts.map(function (d) { return d.score; }));
    if (hi - lo < 1) { hi += 1; lo -= 1; }
    const x = function (i) { return PAD + i * (W - 2 * PAD) / (pts.length - 1); };
    const y = function (v) { return H - PAD - (v - lo) * (H - 2 * PAD) / (hi - lo); };
    const line = pts.map(function (d, i) { return (i ? 'L' : 'M') + x(i).toFixed(1) + ',' + y(d.score).toFixed(1); }).join(' ');
    const first = pts[0], last = pts[pts.length - 1];
    const color = last.score < first.score ? 'var(--accent-red,#c62828)' : 'var(--accent-green,#2e7d32)';
    const hover = pts.map(function (d) { return d.month + ': ' + d.score; }).join('  \u00b7  ');
    let svg = '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" style="flex:none;display:block;">' +
        '<title>' + esc(hover) + '</title>' +
        '<path d="' + line + '" fill="none" stroke="' + color + '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>' +
        '<circle cx="' + x(pts.length - 1).toFixed(1) + '" cy="' + y(last.score).toFixed(1) + '" r="3" fill="' + color + '"/></svg>';
    return '<div style="margin-top:0.55rem;">' +
        '<div style="font-size:0.72rem;color:var(--text-muted,#888);margin-bottom:0.2rem;">' +
        _trendTitle + '</div>' +
        '<div style="display:flex;align-items:center;gap:0.7rem;flex-wrap:wrap;">' + svg +
        '<div dir="ltr" style="font-family:monospace;font-size:0.74rem;line-height:1.5;">' +
        '<span style="font-weight:700;color:' + color + ';">' + first.score + ' \u2192 ' + last.score + '</span><br>' +
        '<span style="color:var(--text-muted,#888);">' + esc(first.month) + ' \u2192 ' + esc(last.month) + '</span></div>' +
        '</div></div>';
}

// Layered-outlier series (kind=layered_outlier): the hospital's own values for
// the flagged indicator, month by month, plus the two baselines the verdict
// was measured against — its historical mean and, when the peer layer fired,
// this month's peer mean. The popup already says "+150% vs baseline" and "z
// 2.1 against 3 peers"; drawing them makes those sentences checkable at a
// glance instead of asking the reviewer to trust them or leave for the trend
// chart.
//
// The unit comes from the payload (p.series_unit): the historical and peer
// layers both z-score the RATE of a rate indicator, so a rate row must draw
// the rate series — plotting the raw numerator with a rate baseline would put
// two different rulers on one axis.
function _renderLayeredSeries(p) {
    const unit = p.series_unit === 'rate' ? 'rate' : 'value';
    const fmt = function (v) {
        const n = Number(v);
        if (!isFinite(n)) return '\u2014';
        return Math.abs(n) >= 100 ? String(Math.round(n)) : String(Math.round(n * 100) / 100);
    };
    const num = function (v) {
        return (v === null || v === undefined || !isFinite(Number(v))) ? null : Number(v);
    };
    const pts = (p.series || []).filter(function (d) {
        return d && num(d[unit]) !== null;
    });
    if (pts.length < 2) return '';
    const inputs = (p.how && p.how.inputs) ? p.how.inputs : {};
    const base = num(inputs.historical_mean);
    // A peer line needs the group it was averaged over, not just a number.
    const peerCount = Number(inputs.peer_count) || 0;
    const peer = peerCount >= 2 ? num(inputs.peer_mean) : null;
    const vals = pts.map(function (d) { return Number(d[unit]); });
    let lo = Math.min.apply(null, vals);
    let hi = Math.max.apply(null, vals);
    [base, peer].forEach(function (v) { if (v !== null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
    if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
    const W = 260, H = 54, PAD = 8;
    const x = function (i) { return PAD + i * (W - 2 * PAD) / (pts.length - 1); };
    const y = function (v) { return H - PAD - (v - lo) * (H - 2 * PAD) / (hi - lo); };
    const line = pts.map(function (d, i) {
        return (i ? 'L' : 'M') + x(i).toFixed(1) + ',' + y(Number(d[unit])).toFixed(1);
    }).join(' ');
    // The row's own month is the point the verdict is about; a series that
    // does not contain it (re-analysis moved on) falls back to the last point.
    let cur = pts.length - 1;
    pts.forEach(function (d, i) { if (d.current) cur = i; });
    const first = pts[0], last = pts[cur];
    const color = 'var(--accent-blue,#1565c0)';
    const hover = pts.map(function (d) { return d.month + ': ' + fmt(d[unit]); }).join('  \u00b7  ');
    let svg = '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '"' +
        ' style="flex:none;display:block;"><title>' + esc(hover) + '</title>';
    if (base !== null) {
        const by = y(base).toFixed(1);
        svg += '<line x1="' + PAD + '" y1="' + by + '" x2="' + (W - PAD) + '" y2="' + by +
            '" stroke="var(--text-muted,#888)" stroke-width="1" stroke-dasharray="3 3" opacity="0.75"/>';
    }
    if (peer !== null) {
        const py = y(peer).toFixed(1);
        svg += '<line x1="' + PAD + '" y1="' + py + '" x2="' + (W - PAD) + '" y2="' + py +
            '" stroke="var(--accent-orange,#e65100)" stroke-width="1" stroke-dasharray="1.5 2.5" opacity="0.9"/>';
    }
    svg += '<path d="' + line + '" fill="none" stroke="' + color +
        '" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>' +
        '<circle cx="' + x(cur).toFixed(1) + '" cy="' + y(Number(last[unit])).toFixed(1) +
        '" r="3.5" fill="var(--accent-orange,#e65100)" stroke="#fff" stroke-width="1.2"/></svg>';
    const name = (p.where && p.where.indicator_name) ? p.where.indicator_name : '';
    let html = _sectionTitle((unit === 'rate' ? __('Rate trend') : __('Raw value trend')) +
        (name ? ' \u00b7 ' + name : '') + ' (' + pts.length + ' ' + __('months') + ')');
    html += '<div style="display:flex;align-items:center;gap:0.7rem;flex-wrap:wrap;">' + svg +
        '<div dir="ltr" style="font-family:monospace;font-size:0.74rem;line-height:1.5;">' +
        '<span style="font-weight:700;color:' + color + ';">' + fmt(first[unit]) + ' \u2192 ' +
        fmt(last[unit]) + '</span><br>' +
        '<span style="color:var(--text-muted,#888);">' + esc(first.month) + ' \u2192 ' +
        esc(last.month) + '</span></div></div>';
    const legend = 'font-size:0.7rem;color:var(--text-muted,#888);margin-top:0.2rem;';
    if (base !== null) {
        html += '<div style="' + legend + '">- - - ' + __('baseline mean') + ': ' + fmt(base) + '</div>';
    }
    if (peer !== null) {
        // "this month" is explicit: the peer mean is a current-month statistic,
        // not a line the earlier points were judged against.
        html += '<div style="' + legend + '"><span style="color:var(--accent-orange,#e65100);">' +
            '\u00b7\u00b7\u00b7</span> ' + __('peer mean') + ' (' + peerCount + ' ' +
            __('hospitals') + ', ' + __('this month') + '): ' + fmt(peer) + '</div>';
    }
    // The band this month carries. The Diagnostics screen shows the EFFECTIVE
    // band (approved caps + the history top-band gate), so the legend names
    // that one; a stored band the policy refused is shown beside it, labelled,
    // never as if it were the band the table renders.
    const bandPoint = pts[cur] || last;
    const shownBand = bandPoint.displayed_level || bandPoint.level;
    if (shownBand) {
        let bandLine = __('Band at this month') + ': <b>' + esc(_codeLabel(shownBand)) + '</b>';
        if (bandPoint.level && bandPoint.level !== shownBand) {
            bandLine += ' <span style="opacity:0.85;">(' + __('stored band') + ': ' +
                esc(_codeLabel(bandPoint.level)) + ')</span>';
        }
        html += '<div style="' + legend + '">' + bandLine + '</div>';
    }
    return html;
}

/**
 * The routed TOP-BAND verdict, in words, for one alert perspective or for the
 * diagnostic row. The states are deliberately different pieces of text: an
 * "undecided" row was NOT judged, and saying nothing there would let it read as
 * a comparison that came back normal.
 *
 * The ROUTE decides which method is named. A HISTORY row is graded by the
 * hospital's own window, so its three sentences say exactly that (unchanged).
 * A PEER row is graded by Rule B on the comparison group's robust scales, so it
 * gets its own sentence per REASON — quoting the history window there described
 * a method that never ran. Every peer sentence separates the two questions:
 * statistical eligibility (what Rule B answers) and clinical/operational
 * comparability between hospitals (which this policy never establishes), so an
 * ``eligible`` verdict can never be read as "these hospitals are comparable".
 *
 * ``not_applicable`` (the row is below the top band, or an approved cap already
 * refused it) yields an empty string: the note is absent, not "normal".
 */
function _eligibilityNote(eligibility) {
    const el = eligibility || {};
    if (!el.decision || el.decision === 'not_applicable') return '';
    if (el.route === 'peer' || el.decision === 'insufficient_robust_scale') {
        // One sentence per REASON the peer policy returns — never inferred from
        // the verdict alone (both scales supporting and a single usable scale
        // supporting are the same decision but different evidence).
        let sentence;
        switch (el.reason) {
            case 'BOTH_SCALES_SUPPORT':
                sentence = __('peer top band supported by both robust scales \u2014 statistical: eligible');
                break;
            case 'ONLY_AVAILABLE_SCALE_SUPPORTS':
                sentence = __('peer top band supported by the only usable robust scale \u2014 statistical: eligible');
                break;
            case 'SCALES_DISAGREE':
                sentence = __('peer robust scales disagree \u2014 statistical: not judged');
                break;
            case 'ONLY_AVAILABLE_SCALE_REFUSES':
                sentence = __('the only usable peer scale rejects the top band \u2014 statistical: not judged');
                break;
            case 'DEFINITION_NOT_ESTABLISHABLE':
                sentence = __('peer indicator definition not establishable \u2014 statistical: not judged');
                break;
            case 'NO_ROBUST_SCALE':
                sentence = __('no usable robust scale in the peer group \u2014 statistical: insufficient robust scale');
                break;
            // ``THIN_PEER_GROUP`` is ``not_applicable`` (the approved cap owns
            // that band), so it never reaches this switch.
            // ``PEER_POLICY`` says the peer policy owns this claim on ANOTHER
            // record; it says nothing about why, because the same reason covers
            // a legacy alert with no stored group AND a Diagnostics row that
            // deliberately does not apply Rule B to a group the alert does
            // store (those two can disagree). Only ``NO_STORED_PEER_VALUES``
            // is a statement about missing evidence.
            case 'PEER_POLICY':
                sentence = __('peer claim not graded on this record \u2014 statistical: not judged');
                break;
            case 'NO_STORED_PEER_VALUES':
                sentence = __('peer comparison group not recorded \u2014 statistical: not judged');
                break;
            case 'INSUFFICIENT_PEER_VALUES':
                sentence = __('too few usable peer values \u2014 statistical: not judged');
                break;
            case 'CURRENT_VALUE_MISSING':
                sentence = __('current value missing \u2014 statistical: not judged');
                break;
            default:
                // A reason this build does not know: still never silent, never
                // described as a history-window verdict, never called normal.
                sentence = __('peer comparison not judged \u2014 statistical: reason not reported');
                break;
        }
        // COMPARABILITY is a different question from statistical eligibility and
        // is never implied by it. The stored status is printed whenever the
        // payload carries one. When it does not, the two absences are NOT the
        // same claim: ``NO_STORED_PEER_VALUES`` / ``PEER_POLICY`` mean no group
        // was available to compare, which is not an unverified comparison; a
        // judgment that did run without the field falls back to not_verified,
        // because a missing field must never read as verified.
        const status = (typeof el.group_comparability_status === 'string'
            && el.group_comparability_status) || '';
        const no_group = el.reason === 'NO_STORED_PEER_VALUES'
            || el.reason === 'PEER_POLICY';
        if (status) {
            sentence += ', ' + __('comparability') + ': ' + _codeLabel(status);
        } else if (!no_group && el.reason) {
            sentence += ', ' + __('comparability') + ': ' + _codeLabel('not_verified');
        }
        // DEFINITION evidence is the third dimension: named only when the row
        // does not carry its own complete definition (catalog-resolved, or not
        // establishable at all), so a statistical verdict never hides which
        // definition it rested on.
        if (el.definition_status && el.definition_status !== 'complete_from_row') {
            sentence += ' \u00b7 ' + __('definition') + ': ' + _codeLabel(el.definition_status);
        }
        return sentence;
    }
    // The window judges the HISTORY route only. A verdict on any other route
    // (volume, raw count, a peer claim that reached neither branch above) must
    // never be attributed to the hospital's own dispersion.
    if (el.route && el.route !== 'history') return __('not judged');
    if (el.decision === 'ineligible') return __('top band refused by the history window');
    if (el.decision === 'undecided') return __('not judged');
    if (el.decision === 'eligible') return __('history window supports the top band');
    return '';
}

/**
 * What ONE stored Quality Alerts peer perspective says.
 *
 * ``verdict`` alone is never turned into a claim: the same decision covers
 * different evidence (both robust scales vs the single usable scale), and
 * ``undecided`` must never read as a confirmation. The sentence is selected by
 * ``reason_code`` and the two fields have to agree; when either is missing the
 * reading is ``unavailable`` — never a default verdict.
 */
function _peerPerspectiveReason(p) {
    const verdict = p && p.verdict;
    const reason = p && p.reason_code;
    if (!verdict || !reason) return __('unavailable');
    const eligibleReason = (reason === 'BOTH_SCALES_SUPPORT'
        || reason === 'ONLY_AVAILABLE_SCALE_SUPPORTS');
    if (eligibleReason !== (verdict === 'eligible')) {
        return __('Not interpreted \u2014 the policy verdict and reason do not agree.');
    }
    switch (reason) {
        case 'BOTH_SCALES_SUPPORT':
            return __('Confirmed \u2014 both robust scales support the top band.');
        case 'ONLY_AVAILABLE_SCALE_SUPPORTS':
            return __('Confirmed \u2014 the only usable robust scale supports the top band.');
        case 'SCALES_DISAGREE':
            return __('Not confirmed \u2014 the available robust scales disagree.');
        case 'ONLY_AVAILABLE_SCALE_REFUSES':
            return __('Not confirmed \u2014 the only usable scale does not support the top band.');
        case 'DEFINITION_NOT_ESTABLISHABLE':
            return __('Not confirmed \u2014 the indicator definition cannot be established.');
        case 'NO_ROBUST_SCALE':
            return __('Not confirmed \u2014 the peer group has no usable robust scale.');
        case 'BOTH_USABLE_SCALES_REFUSE':
            return __('Not confirmed \u2014 both usable robust scales refuse the top band.');
        case 'NO_STORED_PEER_VALUES':
            return __('Not confirmed \u2014 no stored peer values are available.');
        case 'INSUFFICIENT_PEER_VALUES':
            return __('Not confirmed \u2014 too few usable peer values are available.');
        case 'CURRENT_VALUE_MISSING':
            return __('Not confirmed \u2014 the current value is missing.');
        default:
            return __('Not interpreted \u2014 the policy reason is not recognised.');
    }
}

function _peerScaleLine(scale, label) {
    if (!scale || scale.value === null || scale.value === undefined) {
        return esc(label) + ': ' + esc(__('unavailable'));
    }
    let text = esc(label) + ': ' + esc(String(scale.value));
    if (scale.band) text += ' (' + esc(_codeLabel(scale.band)) + ')';
    if (scale.usable === true) text += ' \u00b7 ' + esc(__('usable'));
    else if (scale.usable === false) text += ' \u00b7 ' + esc(__('unusable'));
    else text += ' \u00b7 ' + esc(__('unavailable'));
    return text;
}

/**
 * Quality Alerts peer perspectives for the SAME identity as this Diagnostics
 * row. One card per stored perspective — never merged, and none is selected as
 * the definitive result. The block states the distinction between the two
 * records; it does not reconcile or re-band them.
 */
function _renderPeerPerspectives(cc) {
    const rows = (cc && cc.peer_perspectives) || [];
    if (!rows.length) return '';
    const order = { type: 0, ownership: 1, governorate: 2, facility_type: 3, all: 4 };
    const rank = function (p) {
        return Object.prototype.hasOwnProperty.call(order, p.perspective)
            ? order[p.perspective] : 99;
    };
    const sorted = rows.slice().sort(function (a, b) {
        return rank(a) - rank(b) || (a.alert_id || 0) - (b.alert_id || 0);
    });
    let html = _sectionTitle(__('Quality Alerts \u2014 Peer Perspectives'));
    html += '<div style="font-size:0.74rem;line-height:1.5;color:var(--text-secondary,#555);margin-bottom:0.3rem;">'
        + esc(__('Diagnostics shows this analysis row and its own analytical layers. Quality Alerts may contain separate peer perspectives for the same hospital, month, and indicator. These are different analytical records evaluated under different policies. A peer result at the very high band does not imply that the Diagnostics historical assessment is also at that band.'))
        + '</div>';
    // The cross-check list names EVERY stored perspective; the cards name only
    // the top-band peer claims. Without this line the missing card read as a
    // missing perspective.
    html += '<div style="font-size:0.72rem;line-height:1.45;color:var(--text-muted,#888);margin-bottom:0.3rem;">'
        + esc(__('Only qualifying top-band peer perspectives are shown as cards. Other perspectives may appear in the cross-check list.'))
        + '</div>';
    html += sorted.map(function (p) {
        const tone = p.verdict === 'eligible' ? 'var(--accent-green,#2e7d32)'
            : p.verdict === 'ineligible' ? 'var(--accent-red,#c62828)'
            : p.verdict ? 'var(--accent-orange,#b45309)'
            : 'var(--text-muted,#888)';
        const value = function (v) {
            return (v === null || v === undefined) ? __('unavailable') : v;
        };
        const zs = p.zero_share;
        const hasZeroShare = (typeof zs === 'number' && isFinite(zs));
        const pct = hasZeroShare ? (Math.round(zs * 1000) / 10) : null;
        const scales = (Array.isArray(p.scales_supporting) && p.scales_supporting.length)
            ? p.scales_supporting.map(function (s) { return __(s); }).join(', ')
            : __('unavailable');
        let card = '<div style="border:1px solid var(--border-default,#ddd);border-left:3px solid '
            + tone + ';border-radius:0 6px 6px 0;padding:0.45rem 0.55rem;margin:0.35rem 0;background:var(--bg-elevated,#f7f7f7);">';
        card += '<div style="display:flex;justify-content:space-between;gap:0.6rem;flex-wrap:wrap;align-items:baseline;">'
            + '<strong style="font-size:0.8rem;">' + esc(__(p.label || p.perspective)) + '</strong>'
            + '<span style="direction:ltr;font-size:0.7rem;color:var(--text-muted,#888);">'
            + esc(__('Alert') + ' #' + value(p.alert_id)) + '</span>'
            + '</div>';
        card += '<div style="font-size:0.74rem;line-height:1.55;margin-top:0.15rem;">';
        card += '<div>' + esc(__('Peer hospitals') + ': ' + value(p.peer_count))
            + ' &nbsp;\u00b7&nbsp; ' + esc(__('Current') + ': ' + value(p.current))
            + ' &nbsp;\u00b7&nbsp; ' + esc(__('Threshold') + ': ' + value(p.threshold))
            + '</div>';
        card += '<div>' + esc(__('Rule B verdict') + ': ' + (p.verdict ? __(p.verdict) : __('unavailable'))) + '</div>';
        card += '<div>' + esc(__('Reason') + ': ' + (p.reason_code ? _codeLabel(p.reason_code) : __('unavailable'))) + '</div>';
        card += '<div style="font-weight:600;color:' + tone + ';">' + esc(_peerPerspectiveReason(p)) + '</div>';
        card += '<div>' + _peerScaleLine(p.mad, __('MAD')) + '</div>';
        card += '<div>' + _peerScaleLine(p.iqr, __('IQR')) + '</div>';
        card += '<div>' + esc(__('Scales supporting') + ': ' + scales) + '</div>';
        card += '<div>' + esc(__('Comparability') + ': '
            + (p.group_comparability_status ? _codeLabel(p.group_comparability_status) : __('unavailable'))) + '</div>';
        card += '<div>' + esc(__('Zero share') + ': '
            + (hasZeroShare ? String(pct) + '%' : __('unavailable'))) + '</div>';
        if (hasZeroShare && (p.zero_share_warning === true
                || (p.zero_share_warning == null && zs >= 0.5))) {
            card += '<div style="margin-top:0.15rem;padding:0.2rem 0.4rem;background:rgba(230,81,0,0.08);border-radius:4px;color:var(--accent-orange,#b45309);">'
                + esc(String(pct) + '% ' + __('of peer values are zero. Review the source-data semantics.'))
                + '</div>';
        }
        card += '</div></div>';
        return card;
    }).join('');
    return html;
}

/**
 * Peer comparison EVIDENCE, grouped by comparison identity (Step 10D-5).
 *
 * A perspective label says WHY a peer group was chosen (all, facility type,
 * ownership ...); the peer set says WHICH hospitals were compared. Two labels
 * over one peer set are ONE statistical sample, so this block counts
 * comparisons rather than labels and prints both labels on the comparison they
 * share. History rows are a different evidence class and get their own
 * section: they never enter a peer count. Unreadable evidence is kept as
 * `unknown` (absent or truncated) or `invalid` (self-contradictory) — it is
 * never dropped because a valid comparison also exists, and no group is ever
 * inferred from a label, a band or another perspective.
 */
function _cmpRelationWord(kind) {
    switch (kind) {
        case 'nested': return 'Nested peer groups';
        case 'overlapping': return 'Overlapping peer groups';
        case 'disjoint': return 'Disjoint peer groups';
        default: return 'Unknown relationship';
    }
}

function _cmpList(items) {
    const values = (items || []).filter(function (item) {
        return item !== null && item !== undefined && item !== '';
    });
    if (!values.length) return __('unavailable');
    return values.join(currentLang === 'ar' ? '\u060c ' : ', ');
}

/** Fill a registered sentence template; the dictionary KEY is the sentence. */
function _cmpSentence(text, values) {
    let out = __(text);
    Object.keys(values || {}).forEach(function (name) {
        out = out.split('{' + name + '}').join(String(values[name]));
    });
    return out;
}

function _cmpRow(inner, tone) {
    return '<div style="font-size:0.74rem;line-height:1.5;color:'
        + (tone || 'var(--text-secondary,#555)')
        + ';margin:0.18rem 0;overflow-wrap:anywhere;">' + inner + '</div>';
}

function _cmpLine(text, tone) {
    return _cmpRow(esc(text), tone);
}

function _renderComparisonEvidence(cc) {
    const ev = cc && cc.comparison_evidence;
    if (!ev) return '';
    const comparisons = ev.comparisons || [];
    const labelsOf = function (item) {
        return _cmpList((item.perspective_labels || []).map(function (label) {
            return __(label);
        }));
    };
    let html = _sectionTitle(__('Peer comparison evidence'));
    if (!comparisons.length) {
        html += _cmpLine(__('No stored perspective label holds a complete peer group, so no peer comparison is described here.'));
    } else if (comparisons.length === 1) {
        if (ev.duplicate_perspective_rows) {
            html += _cmpLine(_cmpSentence('{rows} stored perspective labels describe one peer comparison: the labels name the same peer set, so it is counted once.', {rows: ev.peer_rows}));
        } else {
            html += _cmpLine(_cmpSentence('One stored perspective label describes one peer comparison ({labels}).', {labels: labelsOf(comparisons[0])}));
        }
    } else {
        html += _cmpLine(_cmpSentence('{rows} stored perspective labels describe {comparisons} distinct peer comparisons.', {rows: ev.peer_rows, comparisons: comparisons.length}));
        if (ev.duplicate_perspective_rows) {
            html += _cmpLine(_cmpSentence('{duplicates} of those labels name a peer set that is already counted, so they add no second comparison.', {duplicates: ev.duplicate_perspective_rows}));
        }
    }

    comparisons.forEach(function (item, index) {
        const labels = labelsOf(item);
        let card = '<div style="border:1px solid var(--border-default,#ddd);border-left:3px solid var(--accent-blue,#1565c0);border-radius:0 6px 6px 0;padding:0.4rem 0.55rem;margin:0.35rem 0;background:var(--bg-elevated,#f7f7f7);">';
        card += '<div style="font-size:0.78rem;font-weight:700;overflow-wrap:anywhere;">'
            + esc(__('Peer comparison') + ' ' + (index + 1) + ' \u00b7 ' + labels) + '</div>';
        const peers = (item.peer_count === null || item.peer_count === undefined)
            ? __('unavailable') : String(item.peer_count);
        const rows = (item.perspective_rows === null || item.perspective_rows === undefined)
            ? __('unavailable') : String(item.perspective_rows);
        card += _cmpLine(__('Peer hospitals') + ': ' + peers
            + ' \u00b7 ' + __('Stored labels') + ': ' + rows
            + ' \u00b7 ' + __('Effective severity') + ': ' + _codeLabel(item.effective_severity));
        if (Array.isArray(item.stored_severities) && item.stored_severities.length) {
            card += _cmpLine(__('Stored severity') + ': '
                + _cmpList(item.stored_severities.map(_codeLabel)));
        }
        // The identity hash is an opaque token, so it keeps LTR order.
        card += _cmpRow(esc(__('Comparison identity')) + ': <bdo dir="ltr">'
            + esc(String(item.identity || '')) + '</bdo>'
            + (item.source
                ? ' \u00b7 ' + esc(__('Comparison source') + ': '
                    + _codeLabel(item.source))
                : ''));
        if (Array.isArray(item.relationships) && item.relationships.length) {
            card += _cmpLine(__('Relationship') + ': '
                + _cmpList(item.relationships.map(function (rel) {
                    let text = __(_cmpRelationWord(rel.relationship));
                    if (rel.shared_peers) {
                        text += ' \u2014 ' + rel.shared_peers + ' '
                            + __('shared hospitals');
                    }
                    return text;
                })));
        }
        if (Array.isArray(item.policy_versions)
                && item.policy_versions.length) {
            card += _cmpLine(__('Policy version') + ': '
                + _cmpList(item.policy_versions));
        }
        if (item.evidence_conflict) {
            card += _cmpLine(_cmpSentence('{labels}: the stored rows on this one peer set disagree on {fields}; that is conflicting statistics on one comparison, not a second comparison.', {
                labels: labels,
                fields: _cmpList((item.conflict_fields || []).map(function (name) {
                    return _codeLabel(name);
                })),
            }), 'var(--accent-orange,#b45309)');
        }
        html += card + '</div>';
    });

    const flags = [];
    if (ev.unknown_evidence_present) flags.push(__('Unknown evidence'));
    if (ev.invalid_evidence_present) flags.push(__('Invalid evidence'));
    if (ev.truncated_evidence_present) flags.push(__('Truncated peer evidence'));
    if (ev.evidence_conflict) flags.push(__('Conflicting statistics'));
    if (ev.policy_mixed) flags.push(__('Mixed policy versions'));
    if (flags.length) {
        html += _cmpLine(__('Evidence quality flags') + ': ' + _cmpList(flags));
    }
    const truncation = ['truncated_nested_peer_ids',
                        'top_level_truncation_possible',
                        'incomplete_top_level_peer_ids'];
    (ev.unreadable || []).forEach(function (item) {
        const label = __(item.label || item.perspective);
        const reason = _codeLabel(item.reason || 'unspecified');
        let sentence;
        if (item.state === 'invalid') {
            sentence = _cmpSentence('{label}: the stored peer evidence contradicts itself ({reason}), so it is not counted as a comparison.', {label: label, reason: reason});
        } else if (truncation.indexOf(item.reason) !== -1) {
            sentence = _cmpSentence('{label}: the stored peer evidence is incomplete, so the comparison cannot be established and is reported as unknown.', {label: label});
        } else {
            sentence = _cmpSentence('{label}: the stored peer evidence does not name the compared hospitals ({reason}), so the comparison is unknown.', {label: label, reason: reason});
        }
        html += _cmpLine(sentence, 'var(--accent-orange,#b45309)');
    });
    if (ev.policy_mixed) {
        html += _cmpLine(_cmpSentence('More than one comparison-policy version is stored for this formula ({versions}); that is provenance, not another sample.', {versions: _cmpList(ev.policy_versions || [])}), 'var(--accent-orange,#b45309)');
    }

    if (ev.temporal_present) {
        html += _sectionTitle(__('Temporal evidence (history)'));
        html += _cmpLine(ev.temporal_state === 'valid'
            ? __('The history perspective is temporal evidence, not a peer comparison: it compares the hospital with its own earlier months and is never counted as a peer comparison.')
            : __('The history perspective stores no readable window, so its temporal evidence is unknown; it is not turned into a peer comparison.'));
        (ev.temporal || []).forEach(function (item) {
            const bits = [__(item.label || item.perspective)];
            if (item.state === 'valid') {
                bits.push(__('Observations') + ': ' + String(item.observations));
            } else {
                bits.push(__('Unknown evidence') + ': '
                    + _codeLabel(item.reason || 'unknown'));
            }
            if (item.band) {
                bits.push(__('Effective severity') + ': ' + _codeLabel(item.band));
            }
            html += _cmpLine(bits.join(' \u00b7 '));
        });
    }
    return html;
}

/**
 * A backend policy sentence in the reader's language.
 *
 * ``__`` matches whole strings, and THIN_PEER_POLICY is formatted with a peer
 * count, so the formatted English sentence can never be a dictionary key. The
 * TEMPLATE is translated instead and the count is carried over; every other
 * policy sentence (the zero-spread cap, the route policies) is looked up as-is.
 */
/**
 * A stored machine identifier in the reader's language.
 *
 * The API keeps its reason codes, bands and statuses verbatim — they are the
 * stored contract and must not be renamed. This is the ONE place the popup
 * turns them into words: the translation dictionary when it has an entry,
 * otherwise the code itself made readable (``not_verified`` -> "not verified").
 * An unknown code is never mapped onto a label it might not mean.
 */
function _codeLabel(code) {
    if (code === null || code === undefined || code === '') return __('unavailable');
    const raw = String(code);
    const translated = __(raw);
    if (translated && translated !== raw) return translated;
    // A stored LABEL ("Similar hospitals (type)", "Ownership peers") is already
    // words, so it keeps its own capitalization and its identity. Only a real
    // machine identifier (snake_case / UPPER_SNAKE) is turned into readable
    // words: `not_verified` -> "not verified", `VERY_HIGH` -> "Very high".
    // A machine identifier is all-upper (with optional underscores) or
    // all-lower with underscores; anything else is a stored label.
    const machine = /^[A-Z0-9_]+$/.test(raw) || /^[a-z0-9_]+$/.test(raw);
    if (!machine) return raw;
    const words = raw.replace(/_/g, ' ').toLowerCase();
    return /^[A-Z]/.test(raw)
        ? words.charAt(0).toUpperCase() + words.slice(1)
        : words;
}

/**
 * Is this sentence already printed above? The layered-outlier payload folds
 * the cross-check explanation into ``why`` when the two screens disagree, so
 * rendering ``cc.explanation`` unconditionally printed the same paragraph
 * twice. Whitespace is normalised: the two copies are the same text.
 */
function _alreadyShown(container, sentence) {
    const hay = String(container || '').replace(/\s+/g, ' ').trim();
    const needle = String(sentence || '').replace(/\s+/g, ' ').trim();
    return !!needle && hay.indexOf(needle) !== -1;
}

/**
 * Backend prose (``what`` / ``why`` / ``explanation`` / layer details) embeds
 * machine codes such as ``HISTORICAL_ANOMALY (VERY_HIGH level)``. This is a
 * presentation-only rewrite of the STRING: known codes take their localized
 * label, unknown ones are only made readable. The payload is never mutated.
 */
function _humanizeCodes(text, localize) {
    if (!text) return text;
    return String(text).replace(/\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b/g, function (code) {
        // Backend prose is composed in English, so the substituted words stay
        // English too unless the sentence itself was localized (policy
        // sentences): splicing an Arabic band into an English sentence reads
        // as a half-translated gloss.
        if (localize) return _codeLabel(code);
        const words = code.replace(/_/g, ' ').toLowerCase();
        return /^[A-Z0-9_]+$/.test(code)
            ? words.charAt(0).toUpperCase() + words.slice(1)
            : words;
    });
}

/**
 * Render one backend prose field. A registered template renders the
 * sentence in the active language with the backend's own parameters;
 * anything unregistered keeps the original wording (machine codes made
 * readable). The payload itself is never modified.
 */
function _prose(text) {
    if (text === null || text === undefined) return text;
    // ``_humanizeCodes`` is handed in as the per-sentence fallback: a paragraph
    // whose FIRST sentence is registered must not carry a raw machine code
    // ("peer comparison also VERY_HIGH") out of its unmatched neighbours. It
    // only ever makes the identifier readable - it never translates wording.
    const localized = localizeProse(text, currentLang, _codeLabel, _humanizeCodes);
    return localized === null ? _humanizeCodes(text) : localized;
}

/**
 * Render a short TECHNICAL line (the read-only formula) through the registry
 * only: a registered shape is localized, anything else is kept byte-for-byte.
 * Machine codes are deliberately NOT rewritten here - in a formula the token
 * order and the operators are the meaning, so only an exact template may
 * touch it.
 */
function _templateOnly(text) {
    if (text === null || text === undefined) return text;
    const localized = localizeProse(text, currentLang, _codeLabel);
    return localized === null ? text : localized;
}

/**
 * One detection-layer VALUE, in the reader's language.
 *
 * The layer values are backend-composed phrases ("10 (previous 4, +150.0%)",
 * "+218.2% vs baseline mean 3.14286", "not applicable (count indicator)") that
 * already have registered ``layered.value.*`` templates; rendering the raw
 * string made the whole Detection-layers block stay English in Arabic mode.
 * An unregistered value (a bare number, a new shape) is kept verbatim.
 */
function _layerValue(value) {
    if (value === null || value === undefined) return '\u2014';
    const raw = String(value);
    const localized = localizeProse(raw, currentLang, _codeLabel);
    return localized === null ? raw : localized;
}

function _policyLabel(text) {
    // Dynamic prose first: a registered template renders the sentence in the
    // active language with the backend's own parameters; anything unregistered
    // keeps the original text (codes humanized) instead of a guessed wording.
    const localized = localizeProse(text, currentLang, _codeLabel);
    if (localized !== null) return localized;
    const policy = String(text || '');
    const thin = policy.match(/^The peer group is too small \((\d+) peers\)/);
    if (thin) {
        return _humanizeCodes(
            __('The peer group is too small ({peers} peers) to measure a spread, so the deviation cannot be graded; the level is capped at HIGH')
                .replace('{peers}', thin[1]));
    }
    // Policy sentences quote bands and reason codes verbatim; only the
    // rendered copy is made readable, the payload keeps them untouched.
    return _humanizeCodes(__(policy), true);
}

function _renderPayload(p) {
    let html = '';
    html += '<div style="display:flex;justify-content:space-between;gap:0.6rem;flex-wrap:wrap;align-items:center;">';
    html += '<div style="font-size:0.92rem;font-weight:700;line-height:1.45;overflow-wrap:anywhere;">' + esc(_prose(p.what || '')) + '</div>';
    html += _classificationBadge(p.classification);
    html += '</div>';

    if (p.where) {
        html += _sectionTitle(__('Where'));
        html += '<div style="color:var(--text-secondary,#555);line-height:1.7;overflow-wrap:anywhere;">';
        const wbits = [];
        if (p.where.hospital) wbits.push(__('Hospital') + ': ' + p.where.hospital);
        if (p.where.month) wbits.push(__('Month') + ': ' + p.where.month);
        if (p.where.rate_name) wbits.push(__('Rate') + ': ' + p.where.rate_name);
        if (p.where.indicator_code) {
            // Code + human-readable name (name may be Arabic → dir:auto so it
            // renders right-to-left correctly inside the LTR metadata line).
            const _iname = p.where.indicator_name;
            wbits.push(__('Indicator') + ': <bdo dir="ltr">' + esc(p.where.indicator_code) + '</bdo>' +
                (_iname ? ' <span dir="auto">(' + esc(_iname) + ')</span>' : ''));
        }
        if (p.where.rule_code) wbits.push(__('Rule') + ': ' + p.where.rule_code);
        if (p.where.source_files && p.where.source_files.length) {
            wbits.push(__('Source file(s)') + ': ' + p.where.source_files.join(', '));
        }
        html += wbits.join(' &nbsp;•&nbsp; ') + '</div>';
    }

                if (p.why) {
        html += _sectionTitle(__('Why (triggered rule / threshold)'));
            html += '<div style="background:rgba(230,81,0,0.06);border-left:3px solid var(--accent-orange,#e65100);padding:0.45rem 0.6rem;border-radius:0 4px 4px 0;line-height:1.55;overflow-wrap:anywhere;">' + esc(_prose(p.why)) + '</div>';
    }

    html += _renderFailedRules(p);

    // Outliers that produced an outlier score: the rows the penalty counts
    // (HIGH/VERY_HIGH), with the number they were compared against. Without
    // this the popup explained the score with unrelated source-data gaps.
    if (p.outliers && p.outliers.length) {
        html += _sectionTitle(__('Outliers that lowered the score'));
        html += p.outliers.slice(0, 8).map(function (o) {
            const lv = String(o.level || '').toUpperCase();
            const tone = lv === 'VERY_HIGH' ? 'var(--accent-red,#c62828)' : 'var(--accent-orange,#e65100)';
            const value = (o.value != null) ? Number(o.value).toFixed(2) : '\u2014';
            const bench = (o.benchmark != null) ? Number(o.benchmark).toFixed(2) : '\u2014';
            return '<div style="padding:0.3rem 0.5rem;margin:0.2rem 0;background:var(--bg-elevated,#f5f5f5);border-left:3px solid ' + tone + ';border-radius:0 4px 4px 0;font-size:0.76rem;">' +
                '<div><span style="font-weight:700;color:' + tone + ';">' + esc(_codeLabel(lv)) + '</span> \u00b7 <strong>' + esc(o.indicator || o.indicator_code) + '</strong>' +
                ' <span style="color:var(--text-muted,#888);font-size:0.7rem;">' + esc(o.indicator_code || '') + '</span></div>' +
                '<div style="color:var(--text-secondary,#555);">' + esc(__('Value')) + ': ' + value + ' \u00b7 ' + esc(__('Benchmark')) + ': ' + bench +
                // The stored detection type (HISTORICAL_ANOMALY, PEER_ANOMALY,
                // ...) is a machine identifier: render it as words in the
                // reader's language like every other code in the popup, never
                // as the raw enum.
                (o.type ? ' \u00b7 ' + esc(_codeLabel(o.type)) : '') + '</div>' +
                (o.interpretation ? '<div style="color:var(--text-muted,#888);font-size:0.7rem;line-height:1.45;">' + esc(_prose(o.interpretation)) + '</div>' : '') +
                '</div>';
        }).join('');
        if (p.outliers.length > 8) {
            html += '<div style="font-size:0.72rem;color:var(--text-muted,#888);">' +
                __('... and {n} more').replace('{n}', p.outliers.length - 8) + '</div>';
        }
    }

    if (p.data_problems && p.data_problems.length) {
        // Digest: at most 3 examples — the FULL sweep lives on the Audit
        // screen (Data Auditor section), one press away via the footer.
        html += _sectionTitle(__('Data problems in the source values'));
        // The digest shows 3 of them, so a stale benchmark (the anomaly row no
        // longer matching the uploaded data) must not be pushed out by the
        // month's 30 missing cells — it is the one that changes the verdict.
        const _prio = function (d) {
            return d.kind === 'stale_benchmark' ? 0
                : d.severity === 'critical' ? 1
                : d.severity === 'high' ? 2 : 3;
        };
        const _dp = (p.data_problems || []).slice().sort(function (a, b) { return _prio(a) - _prio(b); });
        html += _dp.slice(0, 3).map(function (d) {
            const sevIcon = d.severity === 'critical' ? '❌' : d.severity === 'high' ? '🔧' : '⚠️';
            return '<div style="padding:0.25rem 0.5rem;margin:0.15rem 0;background:var(--bg-elevated,#f5f5f5);border-radius:4px;font-size:0.74rem;">' +
                sevIcon + ' ' + esc(_prose(d.message)) + '</div>';
        }).join('');
        if (_dp.length > 3) {
            html += '<div style="font-size:0.72rem;color:var(--text-muted,#888);margin:0.15rem 0 0;">' +
                __('... and {n} more').replace('{n}', _dp.length - 3) + '</div>';
        }
    }

    if (p.how) {
        html += _sectionTitle(__('How it was calculated'));
        if (p.how.formula_readable) {
            html += '<div style="margin-bottom:0.2rem;">' + esc(_templateOnly(p.how.formula_readable)) + '</div>';
        }
        if (p.how.formula) {
            html += '<div style="font-family:monospace;font-size:0.74rem;background:var(--bg-elevated,#f5f5f5);border:1px solid var(--border-default,#ddd);border-radius:4px;padding:0.4rem 0.6rem;direction:ltr;overflow-x:auto;max-width:100%;white-space:pre-wrap;overflow-wrap:anywhere;">' + esc(p.how.formula) + '</div>';
        }
        if (p.how.thresholds && Object.keys(p.how.thresholds).length) {
            const tbits = Object.entries(p.how.thresholds).map(function (kv) {
                return esc(kv[0]) + ' = ' + esc(typeof kv[1] === 'object' ? JSON.stringify(kv[1]) : String(kv[1]));
            });
            html += '<div style="font-size:0.72rem;color:var(--text-muted,#888);margin-top:0.25rem;direction:ltr;">' + __('Thresholds') + ': ' + tbits.join(' &nbsp;|&nbsp; ') + '</div>';
        }
        if (p.how.inputs && p.how.inputs.length) {
            // Digest: the inputs table collapses behind a toggle — the Audit
            // screen (Calculation Steps) shows it expanded and verified.
            html += '<details style="margin-top:0.3rem;">';
            html += '<summary style="cursor:pointer;font-size:0.72rem;color:var(--accent-blue,#1565c0);">' +
                __('Inputs used') + ' (' + p.how.inputs.length + ')</summary>';
            html += _kvRows(p.how.inputs);
            html += '</details>';
        }
    }

    html += _renderReproduce(p);
    html += _renderScoreTrend(p);
    html += _renderLayeredSeries(p);

    // Layered-outlier detection layers (kind=layered_outlier). The Why popup
    // previously dropped p.layers entirely — the backend built the five-layer
    // breakdown (raw/rate/historical/volume/peer) but nothing rendered it, so
    // a RATE_ANOMALY row looked "empty" in the table: the rate value only
    // lived inside layers['rate'].value.
    if (p.layers && p.layers.length) {
        html += _sectionTitle(__('Detection layers'));
        const _LAYER_ICON = { raw: '\u2139', rate: '\u2139', historical: '\u2139', volume: '\u26a1', peer: '\u2139' };
        html += p.layers.map(function (L) {
            const lvl = L.level || (L.score === null || L.score === undefined ? '\u2014' : '');
            return '<div style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:0.15rem 0.8rem;padding:0.12rem 0;border-bottom:1px dashed var(--border-default,#eee);">'
                + '<span style="color:var(--text-secondary,#555);flex:1 1 auto;min-width:min(12rem,100%);overflow-wrap:anywhere;">'
                + esc(_prose(L.name || L.key)) + (L.detail ? ' <span style="color:var(--text-muted,#888);font-size:0.66rem;">' + esc(_prose(L.detail)) + '</span>' : '') + '</span>'
                + '<span style="font-weight:600;text-align:end;unicode-bidi:plaintext;flex:0 1 auto;min-width:0;max-width:100%;overflow-wrap:anywhere;">'
                + esc(_layerValue(L.value))
                + (L.score !== null && L.score !== undefined ? ' <span style="color:var(--text-muted,#888);font-size:0.66rem;">score ' + Number(L.score).toFixed(2) +' · ' + esc(_codeLabel(lvl)) + '</span>' : '')
                // A score of 1.00 mapping to HIGH is the documented cap, not a
                // rounding artefact: say so where the mismatch is visible.
                + (L.zero_spread ? ' <span style="color:var(--text-muted,#888);font-size:0.66rem;" title="' + esc(__('Every value in this comparison is identical, so the deviation cannot be graded. The level is capped at HIGH.')) + '">' + __('no spread') + '</span>' : '')
                // Too few peers to measure a spread: no z-score is produced for
                // this comparison (the score and the peer list are kept).
                + (L.peer_z_withheld ? ' <span style="color:var(--text-muted,#888);font-size:0.66rem;" title="' + esc(__('Fewer than 4 peer hospitals cannot measure a spread, so no z-score is produced for this comparison. The peer values, their mean and the score are kept.')) + '">' + __('no z') + '</span>' : '')
                + '</span></div>';
        }).join('');
    }

    // Quality Alerts cross-check (kind=layered_outlier). Alerts scores each
    // labelled peer perspective; Diagnostics uses one all-hospital baseline.
    // When the two screens show different severities the popup must state the
    // reason instead of leaving the reader to guess which screen is wrong.
    if (p.cross_check) {
        const cc = p.cross_check;
        html += _sectionTitle(__('Quality Alerts cross-check'));
        const _ccColor = cc.agreement === 'agree' ? 'var(--accent-green,#2e7d32)'
            : cc.agreement === 'no_stored_alert' ? 'var(--text-muted,#888)'
            : 'var(--accent-orange,#b45309)';
        html += '<div style="font-size:0.76rem;line-height:1.45;">'
            + '<div style="font-weight:700;color:' + _ccColor + ';unicode-bidi:plaintext;">'
            + esc(cc.agreement ? _codeLabel(cc.agreement) : '') + '</div>'
            + ((cc.explanation && !_alreadyShown(p.why, cc.explanation))
                ? '<div style="margin-top:0.2rem;">' + esc(_prose(cc.explanation)) + '</div>'
                : '') + '</div>';
        // Which band this row is being compared at. The Diagnostics table shows
        // the band the approved policy allows, while the row on disk can still
        // carry a higher stored band the top-band gate refuses; the comparison
        // above is made at the shown band, so both are named here rather than
        // leaving the popup and the table quoting different severities.
        const _ccDiag = cc.diagnostic || {};
        if (_ccDiag.displayed_level) {
            html += '<div style="font-size:0.72rem;color:var(--text-muted,#888);margin-top:0.2rem;unicode-bidi:plaintext;">'
                + esc(__('Diagnostics band') + ': ' + _codeLabel(_ccDiag.displayed_level))
                + (_ccDiag.stored_level && _ccDiag.stored_level !== _ccDiag.displayed_level
                    ? ' \u00b7 ' + esc(__('stored') + ': ' + _codeLabel(_ccDiag.stored_level))
                    : '') + '</div>';
        }
        if (cc.perspectives && cc.perspectives.length) {
            html += _kvRows(cc.perspectives.map(function (a) {
                return {
                    input: a.label + (a.scope === 'stratified' ? ' \u00b7 stratified' : '') + ' (n=' + (a.peer_count || 0) + ')',
                    // The band is the policy band the Quality Alerts screen
                    // shows; when the row was written higher, the stored band is
                    // named instead of being silently dropped.
                    value: _codeLabel(a.severity) + (a.score !== null && a.score !== undefined ? ' \u00b7 score ' + Number(a.score).toFixed(2) : '') +
                        (a.stored_severity && a.stored_severity !== a.severity
                            ? ' \u00b7 ' + __('Stored') + ' ' + _codeLabel(a.stored_severity) : '') +
                        // The routed top-band verdict, so a row the history
                        // window refused (or could not judge) says so beside the
                        // band instead of looking like an ordinary top-band row.
                        (_eligibilityNote(a.top_band_eligibility)
                            ? ' \u00b7 ' + _eligibilityNote(a.top_band_eligibility) : '') +
                        // A closed row (Resolved / skipped) is still evidence, but
                        // it is not what the Quality Alerts screen is raising now.
                        (a.closed ? ' \u00b7 ' + __('closed') + ' (' + _codeLabel(a.status || '') + ')' : ''),
                };
            }));
        }
        // The diagnostic row's own top-band verdict. Its policy sentence is
        // quoted, so "undecided" is explained (peer / volume / no window)
        // rather than left to read as a clean comparison. The label names WHICH
        // record and calculation this sentence describes: the entries above are
        // the stored Quality Alert perspectives, this one is the analysis ROW
        // Outlier Diagnostics classified — the two can answer differently
        // without either being wrong.
        const diagEl = (cc.diagnostic || {}).top_band_eligibility || {};
        if (diagEl.decision && diagEl.decision !== 'not_applicable') {
            html += '<div style="font-size:0.7rem;color:var(--text-muted,#888);margin-top:0.25rem;">'
                + esc(__('Diagnostics row top band') + ': ' + _eligibilityNote(diagEl)
                      + (diagEl.policy ? ' \u2014 ' + _policyLabel(diagEl.policy) : '')) + '</div>';
        }
        if (cc.policy) {
            // Through ``__`` so a translated policy sentence is used when one
            // exists; an untranslated route keeps the backend's own wording
            // verbatim (the two peer sentences are translated, the rest are not).
            html += '<div style="font-size:0.7rem;color:var(--text-muted,#888);margin-top:0.25rem;">' + esc(_policyLabel(cc.policy)) + '</div>';
        }
        // The same identity's stored peer perspectives. They are separate
        // analytical records, so each keeps its own card and verdict; none is
        // merged with the Diagnostics row or selected as definitive.
        // Labels vs peer SETS (Step 10D-5): one comparison per stored
        // peer set, with its relationships, temporal evidence and
        // evidence-quality flags stated beside it.
        html += _renderComparisonEvidence(cc);
        html += _renderPeerPerspectives(cc);
    }

    if (p.components_below_target && p.components_below_target.length) {
        html += _sectionTitle(__('Components below target'));
        html += _kvRows(p.components_below_target.map(function (c) { return { input: c.component + ' (' + __('target') + ' ' + c.target + ')', value: c.value }; }));
    }

    // No traceability chain here — it renders identically on the Audit
    // screen, and the footer button below is THE one pointer to it.
    html += _renderAuditScreenLink();
    return html;
}

/**
 * Open the Why popup. With one object argument, or the global convenience
 * signature (kind, hospitalId, month, rateName, ruleCode).
 */
export function showWhyPopup(optsOrKind, hospitalId, month, rateName, ruleCode) {
    let opts = optsOrKind;
    if (typeof optsOrKind === 'string') {
        opts = { kind: optsOrKind, hospitalId: hospitalId, month: month, rateName: rateName, ruleCode: ruleCode };
    }
    _lastOpts = opts;
    const modal = _ensureModal();
    const body = modal.querySelector('#explainModalBody');
    modal.style.display = 'flex';
    body.innerHTML = '<div style="text-align:center;padding:1.5rem;color:var(--text-muted,#888);">' + __('Building explanation…') + '</div>';

    let q = _buildExplainQuery(opts);

    apiGet('/audit/explain' + q).then(function (p) {
        const stamp = modal.querySelector('#explainBuildStamp');
        if (stamp) stamp.textContent = p && p.data_epoch ? '· ' + p.data_epoch : '';
        body.innerHTML = _renderPayload(p);
    }).catch(function (err) {
        body.innerHTML = _explainErrorHtml(err);
    });
}

// Global hook so inline onclick handlers in table rows / heatmap cells can
// open the popup without needing the module import in scope.
/**
 * Global alias of showWhyPopup for the Comparative Analysis sub-tabs: they
 * are rendered by validation.js, whose module namespace does not import
 * explain.js — the app.js _bind('showWhyPopup2') would warn about a missing
 * export. Wrapping the same global keeps theWhy buttons on those sub-tabs
 * functional without duplicating the popup logic.
 */
window.showWhyPopup2 = function (kindOrOpts, hospitalId, month, rateName, ruleCode, mode) {
    return window.showWhyPopup(kindOrOpts, hospitalId, month, rateName, ruleCode, mode);
};

window.showWhyPopup = function (kindOrOpts, hospitalId, month, rateName, ruleCode, mode) {
    // Accept BOTH call styles: the positional signature above and the object
    // form inline onclick handlers use (e.g. rules-manager.js passes
    // {kind, hospitalId, month, component}). Passing the object through as
    // `kind` built the request as "?kind=[object Object]", so every object-form
    // call silently rendered "No explanation available".
    if (kindOrOpts && typeof kindOrOpts === 'object') {
        const o = kindOrOpts;
        showWhyPopup({
            kind: o.kind, hospitalId: o.hospitalId, month: o.month,
            rateName: o.rateName, indicatorCode: o.indicatorCode,
            ruleCode: o.ruleCode, component: o.component, mode: o.mode,
        });
        return;
    }
    showWhyPopup({ kind: kindOrOpts, hospitalId: hospitalId, month: month, rateName: rateName, ruleCode: ruleCode, mode: mode });
};
// Global close hook — main.js's browser-Back overlay closer (and anything
// else outside this module) must be able to dismiss the Why popup.
window.closeWhyPopup = function () { closeWhyPopup(); };

/**
 * Deep link into the Audit screen — the single source of truth for the full
 * verification. `encodedEndpoint` carries the section endpoint (and often
 * hospital id + month); `mode` picks the scroll target:
 *   'why'   → the audit screen's traceability chain (the digest equivalent)
 *   'steps' | 'bench' | 'da' | 'report' → the matching collapsible section
 */
window._explainJump = function (encodedEndpoint, mode) {
    const endpoint = decodeURIComponent(encodedEndpoint || '');
    const path = endpoint.split('?')[0];
    const query = endpoint.split('?')[1] || '';
    const seg = path.split('/').filter(Boolean);
    const monthMatch = query.match(/month=([\d-]+)/);
    let month = monthMatch ? monthMatch[1] : null;
    let hid = null;
    for (let i = 0; i < seg.length; i++) {
        if (/^\d+$/.test(seg[i])) { hid = Number(seg[i]); break; }
    }
    // Chain/footer links that carry no endpoint context fall back to the
    // popup's own hospital/month so the audit screen opens pre-selected.
    if (hid == null && _lastOpts && _lastOpts.hospitalId != null) hid = Number(_lastOpts.hospitalId);
    if (!month && _lastOpts && _lastOpts.month) month = _lastOpts.month;
    let jump = null;
    if (path.indexOf('calculation-steps') !== -1) jump = 'steps';
    else if (path.indexOf('benchmark') !== -1 || path.indexOf('outliers') !== -1) jump = 'bench';
    else if (path.indexOf('data-auditor') !== -1) jump = 'da';
    else if (path.indexOf('report') !== -1) jump = 'report';
    if (mode === 'why') jump = 'why';
    window._explainJumpTo(hid, month, jump);
};
window._explainJumpFooter = function () { window._explainJump(null, 'why'); };
window._explainJumpTrail = function () {
    if (!_lastOpts) return;
    closeWhyPopup();
    if (typeof window.closeModal === 'function') { try { window.closeModal(); } catch (e) { /* non-fatal */ } }
    // Audit trail in a NEW tab: the popup belongs to a screen (Outliers,
    // Quality Alerts, the drilldown…) that must stay where it is.
    if (typeof window.openAuditTrailInNewTab === 'function') {
        window.openAuditTrailInNewTab({
            kind: _lastOpts.kind,
            hospitalId: _lastOpts.hospitalId,
            month: _lastOpts.month,
            rateName: _lastOpts.rateName,
            indicatorCode: _lastOpts.indicatorCode,
            ruleCode: _lastOpts.ruleCode,
            component: _lastOpts.component,
        });
        return;
    }
    openScreenInNewTab('audit', {
        mode: 'trail',
        kind: _lastOpts.kind,
        hospital_id: _lastOpts.hospitalId,
        month: _lastOpts.month,
        indicator_code: _lastOpts.indicatorCode,
        rule_code: _lastOpts.ruleCode,
    });
};

/**
 * Global cross-screen jump FROM A MODAL: open the Audit screen in a NEW
 * browser tab with the given hospital/month preselected, run the audit, then
 * scroll to `mode`:
 *   'why'   → traceability chain   'steps' | 'bench' | 'da' | 'report' → section
 * Used by the Why popup (single source of truth for verification) AND by
 * drilldown rows so any finding is one press from its full verification.
 * The tab that owns the popup keeps its screen, filters and scroll position —
 * that is the whole point of the jump living in a new tab.
 */
window._explainJumpTo = function (hid, month, mode) {
    closeWhyPopup();
    // Dismiss the overlay the button was clicked in, so the user comes back to
    // a clean screen when they close the new tab.
    if (typeof window.closeModal === 'function') { try { window.closeModal(); } catch (e) { /* non-fatal */ } }
    openScreenInNewTab('audit', {
        mode: mode || 'why',
        hospital_id: hid,
        month: month,
    });
};

/**
 * In-page half of the jump, run inside that new tab by main.js's
 * `applyBootScreen` (the Audit screen is already active): preselect the
 * hospital/month, run the audit, scroll to `mode`.
 */
window._explainApplyJump = function (hid, month, mode) {
    if (typeof window.SwitchTab !== 'function') return;
    // No hospital AND no month context → just open the screen; the user picks
    // the selection there. A month WITHOUT a hospital (e.g. the drilldown's
    // Data Auditor jump while the dashboard shows All Hospitals) must still
    // preselect the month — so only bail out when both are missing.
    if (!hid && !month) return;
    // Wait for the audit module to be bound AND its selects populated
    // (initAudit fills them asynchronously and would otherwise wipe the
    // preselection), then set the same hospital/month and run the audit.
    let tries = 0;
    (function _go() {
        const _h = document.getElementById('auditHospitalSelect');
        const _m = document.getElementById('auditMonthSelect');
        const ready = typeof window.loadAudit === 'function' && _h && _m && _h.options.length > 1 && _m.options.length > 1;
        if (!ready && ++tries < 80) { setTimeout(_go, 100); return; }
        if (typeof window.loadAudit !== 'function') return;
        const hSel = document.getElementById('auditHospitalSelect');
        const mSel = document.getElementById('auditMonthSelect');
        if (hSel && hid != null) {
            if (!hSel.querySelector('option[value="' + hid + '"]')) {
                const opt = document.createElement('option');
                opt.value = String(hid); opt.textContent = 'Hospital #' + hid;
                hSel.appendChild(opt);
            }
            hSel.value = String(hid);
        } else if (hSel && month) {
            // All-hospitals jump: reset the scope so the audit matches the
            // drilldown (All Hospitals) instead of a stale selection.
            if (Array.prototype.some.call(hSel.options, function (o) { return o.value === ''; })) hSel.value = '';
        }
        if (month && mSel) {
            if (!mSel.querySelector('option[value="' + month + '"]')) {
                const opt = document.createElement('option');
                opt.value = month; opt.textContent = month;
                mSel.appendChild(opt);
            }
            mSel.value = month;
        }
        // Run the audit only when a hospital is preselected — without one it
        // would just toast "Please select hospital and month"; the user picks
        // a hospital there instead.
        if (hid != null) window.loadAudit();
        if (mode) {
            setTimeout(function () {
                const container = document.getElementById('auditResults');
                if (!container) return;
                const chainStrip = container.querySelector('[data-audit-why]');
                if (mode === 'why') {
                    if (chainStrip) chainStrip.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    return;
                }
                const idxMap = { steps: 0, bench: 1, da: 2, report: 3 };
                const idx = idxMap[mode];
                const cards = container.querySelectorAll(':scope > .card > details');
                if (idx != null && cards[idx]) {
                    cards[idx].open = true;
                    cards[idx].scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }, 900);
        }
    })();
}
