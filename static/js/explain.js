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
import { __ } from './i18n.js';
import { esc } from './tree.js';

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
        '<div style="display:flex;justify-content:space-between;gap:0.8rem;padding:0.12rem 0;border-bottom:1px dashed var(--border-default,#eee);">' +
        '<span style="color:var(--text-secondary,#555);flex:1;min-width:0;overflow-wrap:anywhere;">' + esc(String(r.input)) + '</span>' +
        '<span style="font-weight:600;text-align:right;direction:ltr;flex-shrink:0;">' + esc(r.value === null || r.value === undefined ? '--' : String(r.value)) + '</span>' +
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
        html += '<div style="margin-top:0.3rem;color:var(--text-muted,#888);font-size:0.72rem;">' + esc(r.note) + '</div>';
    }
    return html;
}

// Digest footer: ONE pointer into the Audit screen — the single source of
// truth for verification — instead of repeating its content in the popup.
function _renderAuditScreenLink() {
    return '<div data-explain-footer style="display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap;margin-top:0.9rem;padding:0.55rem 0.7rem;border-top:1px solid var(--border-default,#ddd);">' +
        '<span style="font-size:0.72rem;color:var(--text-muted,#888);">' + __('Digest only — every number here is verified step-by-step on the Audit screen') + '</span>' +
        '<button onclick="window._explainJumpFooter()" style="background:var(--accent-blue,#1565c0);color:#fff;border:none;border-radius:4px;padding:4px 12px;font-size:0.72rem;font-weight:700;cursor:pointer;white-space:nowrap;">' + __('Open in audit screen') + ' \u2192</button>' +
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
            esc(r.rule_name || r.rule_description || code) + '</span></div>' +
            (r.details ? '<div style="font-size:0.72rem;color:var(--text-secondary,#555);margin-top:0.15rem;line-height:1.5;overflow-wrap:anywhere;">' +
                esc(r.details) + '</div>' : '') +
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

function _renderPayload(p) {
    let html = '';
    html += '<div style="display:flex;justify-content:space-between;gap:0.6rem;flex-wrap:wrap;align-items:center;">';
    html += '<div style="font-size:0.92rem;font-weight:700;line-height:1.45;overflow-wrap:anywhere;">' + esc(p.what || '') + '</div>';
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
        html += '<div style="background:rgba(230,81,0,0.06);border-left:3px solid var(--accent-orange,#e65100);padding:0.45rem 0.6rem;border-radius:0 4px 4px 0;line-height:1.55;overflow-wrap:anywhere;">' + esc(p.why) + '</div>';
    }

    html += _renderFailedRules(p);

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
                sevIcon + ' ' + esc(d.message) + '</div>';
        }).join('');
        if (_dp.length > 3) {
            html += '<div style="font-size:0.72rem;color:var(--text-muted,#888);margin:0.15rem 0 0;">' +
                __('... and {n} more').replace('{n}', _dp.length - 3) + '</div>';
        }
    }

    if (p.how) {
        html += _sectionTitle(__('How it was calculated'));
        if (p.how.formula_readable) {
            html += '<div style="margin-bottom:0.2rem;">' + esc(p.how.formula_readable) + '</div>';
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

    apiGet('/audit/explain' + q).then(function (p) {
        const stamp = modal.querySelector('#explainBuildStamp');
        if (stamp) stamp.textContent = p && p.data_epoch ? '· ' + p.data_epoch : '';
        body.innerHTML = _renderPayload(p);
    }).catch(function (err) {
        body.innerHTML = '<div style="color:var(--accent-red,#c62828);padding:0.5rem;">' +
            '\u26a0\ufe0f ' + __('No explanation available') + ': ' + esc(err && err.message ? err.message : 'error') +
            '<div style="margin-top:0.4rem;color:var(--text-muted,#888);font-size:0.72rem;">' +
            __('The underlying result row may not exist for this hospital/month.') + '</div></div>';
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

/**
 * Global cross-screen jump: switch to the Audit screen with the given
 * hospital/month preselected, run the audit, then scroll to `mode`:
 *   'why'   → traceability chain   'steps' | 'bench' | 'da' | 'report' → section
 * Used by the Why popup (single source of truth for verification) AND by
 * drilldown rows so any finding is one press from its full verification.
 */
window._explainJumpTo = function (hid, month, mode) {
    closeWhyPopup();
    // Jumping from inside the KPI drilldown (or any detail modal) must also
    // dismiss that overlay, otherwise it covers the audit screen.
    if (typeof window.closeModal === 'function') { try { window.closeModal(); } catch (e) { /* non-fatal */ } }
    if (typeof window.SwitchTab !== 'function') return;
    window.SwitchTab('audit');
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
