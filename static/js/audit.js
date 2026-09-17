import { API, apiGet } from './api.js';
import { __ } from './i18n.js';
import { esc } from './tree.js';
import { toastWarning } from './toast.js';

let _auditData = null;
let _auditMeta = null;
let _auditErrors = [];

function riskColor(level) {
    if (!level) return 'var(--text-muted)';
    const l = level.toLowerCase();
    if (l === 'critical') return 'var(--accent-red)';
    if (l === 'high') return 'var(--accent-red)';
    if (l === 'moderate' || l === 'elevated') return 'var(--accent-orange)';
    if (l === 'low' || l === 'normal') return 'var(--accent-green)';
    return 'var(--text-muted)';
}

// عرض قيمة أو "--" عند غيابها — لا نطبع صفرًا زائفًا
function nv(v) {
    return (v == null || v === '') ? '--' : v;
}

// severity → existing .badge-* class
function sevClass(sev) {
    const s = String(sev || '').toUpperCase();
    if (s === 'CRITICAL') return 'badge badge-critical';
    if (s === 'HIGH') return 'badge badge-high';
    if (s === 'MEDIUM') return 'badge badge-medium';
    if (s === 'LOW' || s === 'NORMAL') return 'badge badge-low';
    return 'badge badge-pass';
}

// collapsible section header — title on the left, summary badge on the right
function sectTitle(title, badgeHtml) {
    return '<summary class="audit-summary">'
        + '<span class="audit-sect-title">' + title + '</span>'
        + (badgeHtml ? '<span class="audit-sect-badge">' + badgeHtml + '</span>' : '')
        + '</summary>';
}

// small uppercase muted sub-section label
function subLabel(text) {
    return '<div class="audit-label">' + text + '</div>';
}

function emptyState(icon, text, hint) {
    return '<div class="empty-state"><div class="empty-icon">' + icon + '</div>'
        + '<div class="empty-text">' + text + '</div>'
        + (hint ? '<div class="empty-hint">' + hint + '</div>' : '')
        + '</div>';
}

// dashed "how is this calculated" box
function explainBox(title, intro, rows) {
    let out = '<div style="margin:0.4rem 0;padding:0.5rem;background:var(--bg-elevated);border:1px dashed var(--border-default);border-radius:4px;font-size:0.72rem;color:var(--text-secondary);">';
    if (title) out += '<strong style="font-size:0.76rem;color:var(--text-primary);">' + title + '</strong>';
    if (intro) out += '<div style="margin:0.15rem 0 0.3rem 0;">' + intro + '</div>';
    if (rows && rows.length) {
        out += rows.map(r =>
            '<div style="display:flex;justify-content:space-between;gap:0.6rem;padding:0.1rem 0;"><span>' + r[0] + '</span><span style="color:var(--text-muted);text-align:right;">' + r[1] + '</span></div>'
        ).join('');
    }
    out += '</div>';
    return out;
}

// horizontal contribution bar + legend
function stackBar(items) {
    const segs = (items || []).filter(i => (i.pct || 0) > 0);
    if (!segs.length) return '';
    return '<div style="display:flex;height:0.6rem;border-radius:3px;overflow:hidden;margin:0.3rem 0;" dir="ltr">'
        + segs.map(s => '<div style="width:' + s.pct + '%;background:' + s.color + ';opacity:0.85;" title="' + esc(s.label) + ' (' + s.pct + '%)"></div>').join('')
        + '</div>'
        + '<div style="display:flex;flex-wrap:wrap;gap:0.5rem;font-size:0.66rem;color:var(--text-secondary);margin-bottom:0.3rem;">'
        + segs.map(s => '<span><span style="display:inline-block;width:0.5rem;height:0.5rem;border-radius:2px;background:' + s.color + ';vertical-align:middle;margin-inline-end:0.2rem;"></span>'
            + esc(s.label) + ' ' + s.pct + '%</span>').join('')
        + '</div>';
}

const _QS_COLORS = ['var(--accent-blue)', 'var(--accent-teal)', 'var(--accent-purple)', 'var(--accent-orange)'];

export function initAudit() {
    const hSel = document.getElementById('auditHospitalSelect');
    const mSel = document.getElementById('auditMonthSelect');
    if (!hSel || !mSel) return; // التبويب لم يُحمَّل — لا شيء لنهيئه
    if (hSel.options.length > 1 && mSel.options.length > 1) return;
    Promise.all([
        apiGet('/hospitals/').then(d => {
            const list = d.value || d || [];
            hSel.innerHTML = '<option value="">' + __('Select hospital') + '</option>' + list.map(h => '<option value="' + h.id + '">' + esc(h.name) + '</option>').join('');
        }).catch(() => {}),
        apiGet('/analysis/months').then(d => {
            const months = d.months || d || [];
            mSel.innerHTML = '<option value="">' + __('Select month') + '</option>' + months.map(m => '<option value="' + m + '">' + m + '</option>').join('');
        }).catch(() => {}),
    ]);
    const container = document.getElementById('auditResults');
    if (container && !container.innerHTML.trim()) {
        container.innerHTML = emptyState('🔍', __('Choose a hospital and month to generate the audit.'), __('The report is split into four collapsible sections below.'));
    }
}

export function loadAudit() {
    const hSel = document.getElementById('auditHospitalSelect');
    const hid = hSel.value;
    const month = document.getElementById('auditMonthSelect').value;
    if (!hid || !month) { toastWarning(__('Please select hospital and month.')); return; }
    const hospName = (hSel.options[hSel.selectedIndex] || {}).textContent || hid;
    _auditMeta = { hid, month, hospName };
    document.getElementById('auditLoading').classList.remove('hidden');
    document.getElementById('auditBtn').disabled = true;
    const container = document.getElementById('auditResults');
    container.innerHTML = '';

    const q = '?month=' + month;
    // كل قسم مستقل: فشل قسم واحد لا يُسقط الشاشة كلها
    Promise.allSettled([
        apiGet('/audit/calculation-steps/' + hid + q),
        apiGet('/audit/benchmark/' + hid + q),
        apiGet('/audit/data-auditor/' + hid + q),
        apiGet('/audit/report/' + hid + q),
    ]).then(results => {
        document.getElementById('auditLoading').classList.add('hidden');
        document.getElementById('auditBtn').disabled = false;
        const sectionNames = [__('1. Calculation Steps'), __('2. Benchmark Comparison'), __('3. Data Auditor'), __('4. Audit Report')];
        _auditErrors = results
            .map((r, i) => r.status === 'rejected' ? sectionNames[i] + ' — ' + (r.reason && r.reason.message ? r.reason.message : 'error') : null)
            .filter(Boolean);
        if (_auditErrors.length === results.length) {
            container.innerHTML = '<p style="color:var(--accent-red);padding:1rem;">' + __('Error: ') + esc(_auditErrors[0]) + '</p>';
            return;
        }
        _auditData = results.map(r => r.status === 'fulfilled' ? r.value : {});
        renderAudit();
    });
}

// ── Executive summary strip ──────────────────────────────────────
function renderSummaryStrip(steps, da) {
    let cards = '';
    const push = (icon, valueHtml, label, tone) => {
        cards += '<div class="kpi-card' + (tone ? ' ' + tone : '') + '">'
            + '<div class="icon">' + icon + '</div>'
            + '<div class="value">' + valueHtml + '</div>'
            + '<div class="label">' + label + '</div>'
            + '</div>';
    };

    const rp = steps.risk_profile;
    if (rp && rp.overall_risk_level) {
        const lvl = String(rp.overall_risk_level).toLowerCase();
        const tone = (lvl === 'critical') ? 'danger' : (lvl === 'high' || lvl === 'elevated' || lvl === 'moderate') ? 'warning' : 'success';
        push('🎯', esc(rp.overall_risk_level), __('Risk Level'), tone);
    }

    const qs = steps.quality_score;
    const qFinal = qs && qs.final_score != null ? qs.final_score
        : (da.quality_score && da.quality_score.score != null ? da.quality_score.score : null);
    if (qFinal != null) {
        const tone = qFinal < 50 ? 'danger' : qFinal < 70 ? 'warning' : 'success';
        push('⭐', Number(qFinal).toFixed(1), __('Quality Score'), tone);
    }

    if (da.completeness && da.completeness.total) {
        const comp = da.completeness;
        const effective = comp.present + (comp.covered || 0);
        const pct = Math.round(effective / comp.total * 100);
        const tone = pct >= 80 ? 'success' : pct >= 50 ? 'warning' : 'danger';
        push('📥', pct + '%', __('Completeness'), tone);
    }

    if (da.rule_failures) {
        const n = da.rule_failures.total || 0;
        push('📏', n, __('Rule Failures'), n > 0 ? 'danger' : 'success');
    }

    if (da.outliers) {
        const n = da.outliers.total || 0;
        push('⚠️', n, __('Outliers'), n > 0 ? 'danger' : 'success');
    }

    const conf = da.confidence || (steps.confidence ? { overall_confidence: steps.confidence.overall, level: steps.confidence.level } : null);
    if (conf && conf.overall_confidence != null) {
        const tone = conf.overall_confidence >= 80 ? 'success' : conf.overall_confidence >= 50 ? 'warning' : 'danger';
        push('🛡️', Number(conf.overall_confidence).toFixed(1) + '<span style="display:block;font-size:0.5em;font-weight:600;">' + esc(conf.level || '') + '</span>', __('Data Confidence'), tone);
    }

    if (!cards) return '';
    return '<div class="kpi-grid audit-kpis">' + cards + '</div>';
}

// ── Quality Score breakdown ───────────────────────────────────────
function renderQualityScore(qs) {
    let html = '';
    html += subLabel(__('Quality Score'));
    const qsColor = qs.final_score != null ? (qs.final_score < 50 ? 'var(--accent-red)' : qs.final_score < 70 ? 'var(--accent-orange)' : 'var(--accent-green)') : 'var(--text-muted)';
    html += '<div style="margin:0.3rem 0;padding:0.4rem 0.5rem;background:var(--bg-elevated);border-left:3px solid ' + qsColor + ';border-radius:3px;font-size:0.78rem;">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;"><strong>' + __('Final Score') + '</strong><span style="font-weight:700;font-size:1rem;color:' + qsColor + ';">' + (qs.final_score != null ? Number(qs.final_score).toFixed(1) : '--') + '</span></div>';
    const comps = qs.components || [];
    if (comps.length) {
        const totalW = comps.reduce((a, c) => a + Math.abs(c.weighted || 0), 0) || 1;
        html += stackBar(comps.map((c, i) => ({
            label: c.name,
            color: _QS_COLORS[i % _QS_COLORS.length],
            pct: Math.round(((c.weighted || 0) / totalW) * 100),
        })));
        html += explainBox(
            __('How the quality score is calculated'),
            __('final = Σ (component value × weight), scaled to 0–100.'),
            comps.map((c, i) => [esc(c.name) + ' <span style="color:var(--text-muted);">(×' + c.weight + ')</span>', esc(c.formula || '')])
        );
        comps.forEach((c, i) => {
            const pct = totalW ? Math.round((c.weighted || 0) / totalW * 100) : 0;
            html += '<div style="display:flex;justify-content:space-between;font-size:0.72rem;color:var(--text-secondary);padding:0.1rem 0;border-top:1px solid var(--border-default);">';
            html += '<span><span style="display:inline-block;width:0.45rem;height:0.45rem;border-radius:2px;background:' + _QS_COLORS[i % _QS_COLORS.length] + ';vertical-align:middle;margin-inline-end:0.25rem;"></span>' + esc(c.name) + '</span>';
            html += '<span>' + (c.value != null ? Number(c.value).toFixed(3) : '--') + ' × ' + c.weight + ' = <strong>' + (c.weighted != null ? Number(c.weighted).toFixed(4) : '--') + '</strong> <span style="color:var(--text-muted);">(' + pct + '%)</span></span>';
            html += '</div>';
        });
    }
    html += '</div>';
    return html;
}

// ── Confidence breakdown ──────────────────────────────────────────
function renderConfidence(cf) {
    let html = '';
    html += subLabel(__('Confidence'));
    const cfLevel = String(cf.level || '').toUpperCase();
    html += '<div style="margin:0.3rem 0;padding:0.4rem 0.5rem;background:var(--bg-elevated);border-radius:3px;font-size:0.78rem;">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;">'
        + '<strong>' + __('Overall') + '</strong>'
        + '<span style="font-weight:700;font-size:1rem;color:' + riskColor(cf.level) + ';">' + (cf.overall != null ? Number(cf.overall).toFixed(1) : '--') + ' ' + sevClass(cf.level) + '</span>'
        + '</div>';
    const sw = cf.signal_weights || {};
    const w = (k, dflt) => sw[k] != null ? Math.round(sw[k] * 100) : dflt;
    html += explainBox(
        __('How confidence is calculated'),
        __('Per-indicator confidence = Σ (signal score × weight) × 100, capped 0–100. Overall confidence is the clinical-weighted average across indicators.'),
        [
            ['<strong>' + __('Validation rules') + '</strong> — ' + w('rule_compliance', 55) + '%', __('passed rules / total rules')],
            ['<strong>' + __('Historical consistency') + '</strong> — ' + w('historical', 10) + '%', __('z-score vs historical mean')],
            ['<strong>' + __('Cross-hospital comparison') + '</strong> — ' + w('cross_hospital', 10) + '%', __('z-score vs peer rates')],
            ['<strong>' + __('Trend projection') + '</strong> — ' + w('trend', 10) + '%', __('deviation from projected trend')],
            ['<strong>' + __('Sub-indicator completeness') + '</strong> — ' + w('completeness', 15) + '%', __('present children / total children')],
        ]
    );
    html += '<div style="font-size:0.68rem;color:var(--text-muted);margin:0.2rem 0;">' + __('Levels:') + ' ≥80 ' + sevClass('HIGH') + ' · ≥50 ' + sevClass('MEDIUM') + ' · ≥25 ' + sevClass('LOW') + ' · &lt;25 ' + sevClass('CRITICAL') + '</div>';
    html += '</div>';
    return html;
}

function renderAudit() {
    const d = _auditData;
    if (!d) return;
    const container = document.getElementById('auditResults');
    let html = '';

    // ملخص: لمن هذا التدقيق؟
    if (_auditMeta) {
        html += '<div class="card" style="margin-bottom:0.8rem;padding:0.5rem 0.8rem;font-size:0.8rem;">';
        html += '<strong>' + __('Hospital:') + '</strong> ' + esc(_auditMeta.hospName);
        html += ' &nbsp;·&nbsp; <strong>' + __('Month:') + '</strong> ' + esc(_auditMeta.month);
        html += '</div>';
    }
    // أقسام فشل تحميلها
    if (_auditErrors && _auditErrors.length) {
        html += '<div class="card" style="margin-bottom:0.8rem;padding:0.5rem 0.8rem;border-left:3px solid var(--accent-orange);font-size:0.75rem;">';
        html += '<strong style="color:var(--accent-orange);">' + __('Some sections failed to load:') + '</strong>';
        html += '<ul style="margin:0.2rem 0 0 1.2rem;">' + _auditErrors.map(e => '<li>' + esc(e) + '</li>').join('') + '</ul>';
        html += '</div>';
    }

    // Executive summary strip
    const steps = d[0] || {};
    const da = d[2] || {};
    html += renderSummaryStrip(steps, da);

    // Section 1: Calculation Steps
    html += '<div class="card" style="margin-bottom:0.8rem;padding:0.6rem 0.8rem;">';
    html += '<details open>';
    html += sectTitle(__('1. Calculation Steps'), (steps.classifications && steps.classifications.length)
        ? '<span class="badge badge-low">' + steps.classifications.length + ' ' + __('rates') + '</span>' : '');

    if (steps.classifications && steps.classifications.length) {
        html += subLabel(__('Clinical Rates'));
        steps.classifications.forEach(c => {
            const color = c.color || '#888';
            html += '<div style="margin:0.3rem 0;padding:0.4rem 0.5rem;background:var(--bg-elevated);border-left:3px solid ' + color + ';border-radius:3px;font-size:0.78rem;">';
            html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
            html += '<strong>' + esc(c.rate_name) + '</strong>';
            html += '<span style="color:' + color + ';font-weight:600;">' + esc(c.label) + '</span>';
            html += '</div>';
            if (c.formula_readable) html += '<div style="font-size:0.72rem;color:var(--text-secondary);margin:0.1rem 0;">' + __('Formula: ') + esc(c.formula_readable) + '</div>';
            else if (c.formula) html += '<div style="font-size:0.72rem;color:var(--text-secondary);margin:0.1rem 0;">' + __('Formula: ') + esc(c.formula) + '</div>';
            // Inputs with names
            const numParts = (c.numerator_names || []).map(n => esc(n));
            const denName = esc(c.denominator_name || c.denominator_code || '?');
            html += '<div style="font-size:0.72rem;color:var(--text-secondary);margin:0.1rem 0;">';
            html += '<strong>' + __('Input Data:') + '</strong> '
                + numParts.join(' + ')
                + ' / ' + denName
                + ' = ' + esc((c.numerator_value || 0) + ' / ' + (c.denominator_value || 0))
                + ' = <strong>' + (c.raw_rate != null ? Number(c.raw_rate).toFixed(2) : '--') + '</strong> ' + esc(c.unit || '');
            html += '</div>';
            if (c.narrative) html += '<div style="font-size:0.7rem;color:var(--text-muted);margin:0.1rem 0;">' + esc(c.narrative) + '</div>';
            html += '</div>';
        });
    }

    if (steps.quality_score) {
        html += renderQualityScore(steps.quality_score);
    }

    if (steps.confidence) {
        html += renderConfidence(steps.confidence);
    }

    if (steps.risk_profile && steps.risk_profile.metrics && steps.risk_profile.metrics.length) {
        const rp = steps.risk_profile;
        html += subLabel(__('Risk Profile') + ' <span style="font-weight:400;">' + sevClass(rp.overall_risk_level || '') + '</span>');
        rp.metrics.forEach(m => {
            html += '<div style="display:flex;justify-content:space-between;font-size:0.72rem;color:var(--text-secondary);padding:0.1rem 0.4rem;border-bottom:1px solid var(--border-default);">';
            html += '<span>' + esc(m.metric_name) + '</span>';
            html += '<span>' + (m.value != null ? Number(m.value).toFixed(1) : '--') + esc(m.unit || '') + ' ' + sevClass(m.severity || '') + '</span>';
            html += '</div>';
        });
    }

    if (steps.morbidity_profile && steps.morbidity_profile.metrics && steps.morbidity_profile.metrics.length) {
        html += subLabel(__('Morbidity Profile'));
        html += '<div style="font-size:0.72rem;color:var(--text-secondary);padding:0.2rem 0.4rem;">' + __('SMM: ') + (steps.morbidity_profile.total_smm || 0) + ' | ' + __('Maternal Deaths: ') + (steps.morbidity_profile.maternal_deaths || 0) + '</div>';
    }

    // Raw Data Store
    if (steps.raw_data && steps.raw_data.length) {
        html += subLabel(__('Raw Data Store') + ' <span style="font-weight:400;">(' + steps.raw_data.length + ' ' + __('indicators') + ')</span>');
        html += '<div style="margin:0.3rem 0;padding:0.3rem 0.5rem;background:var(--bg-elevated);border-radius:3px;font-size:0.72rem;">';
        steps.raw_data.forEach(r => {
            html += '<div style="display:flex;justify-content:space-between;padding:0.1rem 0;border-bottom:1px solid var(--border-default);">';
            html += '<span>' + esc(r.name) + ' <span style="color:var(--text-muted);">(' + esc(r.code) + ')</span></span>';
            html += '<span>' + esc(r.value) + '</span>';
            html += '</div>';
        });
        html += '</div>';
    }

    html += '</details></div>';

    // Section 2: Benchmark Comparison
    const bench = d[1] || {};
    const benchCounts = bench.comparisons ? Object.keys(bench.comparisons).length : 0;
    const benchAlerts = bench.comparisons
        ? Object.keys(bench.comparisons).filter(k => ['critical', 'high'].indexOf((bench.comparisons[k].status || '').toLowerCase()) >= 0).length
        : 0;
    html += '<div class="card" style="margin-bottom:0.8rem;padding:0.6rem 0.8rem;">';
    html += '<details>';
    html += sectTitle(__('2. Benchmark Comparison'),
        (benchCounts
            ? '<span class="badge badge-low">' + benchCounts + ' ' + __('rates') + '</span>'
            : '') + (benchAlerts ? ' <span class="badge badge-critical">' + benchAlerts + ' ' + __('alerts') + '</span>' : ''));
    html += '<div style="font-size:0.7rem;color:var(--text-muted);font-family:monospace;margin:0.2rem 0 0.4rem 0;" dir="ltr">' + __('z = (hospital value - peer average) / peer standard deviation') + '</div>';
    if (bench.comparisons) {
        html += '<div class="range-legend"><span><span class="legend-dot"></span> ' + __('this hospital') + '</span>'
            + '<span><span class="legend-tick legend-tick-med"></span> ' + __('peer median') + '</span>'
            + '<span><span class="legend-tick legend-tick-avg"></span> ' + __('peer average') + '</span></div>';
        Object.keys(bench.comparisons).sort().forEach(rname => {
            const c = bench.comparisons[rname];
            const barColor = riskColor(c.status);
            const arrow = (c.percent_deviation || 0) > 0 ? '↑' : '↓';
            html += '<div style="margin:0.4rem 0;padding:0.3rem 0.5rem;background:var(--bg-elevated);border-left:3px solid ' + barColor + ';border-radius:3px;font-size:0.78rem;">';
            html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
            html += '<strong>' + esc(rname) + '</strong>';
            html += '<span>' + sevClass(c.status) + ' <span style="font-weight:600;">' + arrow + ' ' + Math.abs(c.percent_deviation || 0).toFixed(1) + '% ' + __('vs avg') + '</span></span>';
            html += '</div>';
            // position on peer range
            const lo = c.peer_min, hi = c.peer_max;
            const span = (hi != null && lo != null) ? (hi - lo) : 0;
            if (span > 0) {
                const px = function (v) {
                    if (v == null) return null;
                    return Math.max(0, Math.min(100, (v - lo) / span * 100));
                };
                html += '<div class="range-track" dir="ltr">';
                const avgPx = px(c.peer_average);
                const medPx = px(c.peer_median);
                const myPx = px(c.hospital_value);
                if (avgPx != null) html += '<span class="range-tick range-tick-avg" style="left:' + avgPx + '%"></span>';
                if (medPx != null) html += '<span class="range-tick range-tick-med" style="left:' + medPx + '%"></span>';
                if (myPx != null) html += '<span class="range-dot" style="left:' + myPx + '%;background:' + barColor + ';box-shadow:0 0 0 2px ' + barColor + '66;"></span>';
                html += '</div>';
                html += '<div class="range-scale"><span>' + __('Min') + ' ' + nv(lo) + '</span><span>' + __('Avg') + ' ' + nv(c.peer_average) + ' · ' + __('Med') + ' ' + nv(c.peer_median) + '</span><span>' + __('Max') + ' ' + nv(hi) + '</span></div>';
            }
            html += '<div style="font-size:0.72rem;color:var(--text-secondary);">' + __('Z-score: ') + nv(c.z_score) + ' | ' + __('Percentile: ') + nv(c.percentile) + 'th | ' + (c.peers_below || 0) + ' ' + __('of') + ' ' + (c.peer_count || 0) + ' ' + __('peers below') + '</div>';
            const _std = (c.peer_std || 0);
            const zcalc = _std > 0
                ? 'z = (' + Number(c.hospital_value || 0).toFixed(2) + ' - ' + Number(c.peer_average || 0).toFixed(2) + ') / ' + _std.toFixed(2) + ' = ' + Number(c.z_score || 0).toFixed(2)
                : __('z = 0.00 - std dev undefined (fewer than 2 peers)');
            html += '<div style="font-size:0.7rem;color:var(--text-muted);font-family:monospace;" dir="ltr">' + zcalc + '</div>';
            const pb = c.peer_breakdown;
            if (pb) {
                const noData = (pb.no_data_month_count || 0);
                const noDen = (pb.no_denominator_count || 0);
                const excluded = (pb.excluded_target || 0);
                const parts = [];
                parts.push('<strong>' + (c.peer_count || 0) + ' ' + __('of') + ' ' + (pb.total_active || 0) + __(' active hospitals') + '</strong>');
                parts.push(excluded + __(' (this hospital) excluded'));
                if (noData) parts.push(noData + __(' with no data this month'));
                if (noDen) parts.push(noDen + __(' with no denominator for this rate'));
                const names = [];
                if (noData && pb.no_data_month_names && pb.no_data_month_names.length) names.push(__('No data: ') + esc(pb.no_data_month_names.join(', ')));
                if (noDen && pb.no_denominator_names && pb.no_denominator_names.length) names.push(__('No denominator: ') + esc(pb.no_denominator_names.join(', ')));
                html += '<div style="font-size:0.7rem;color:var(--text-muted);">' + __('Why ') + (c.peer_count || 0) + __(' peers?') + ' ' + parts.join(' · ') + (names.length ? '<span title="' + esc(names.join('\n')) + '">' + __(' (hover for names)') + '</span>' : '') + '</div>';
            }
            html += '</div>';
        });
    } else {
        html += emptyState('📊', __('No benchmark data available.'), __('Try another hospital or month.'));
    }
    html += '</details></div>';

    // Section 3: Data Auditor
    html += '<div class="card" style="margin-bottom:0.8rem;padding:0.6rem 0.8rem;">';
    html += '<details>';
    html += sectTitle(__('3. Data Auditor'),
        (da.rule_failures && da.rule_failures.total
            ? '<span class="badge badge-fail">' + da.rule_failures.total + ' ' + __('rules') + '</span>'
            : '<span class="badge badge-pass">' + __('rules ok') + '</span>')
        + (da.outliers && da.outliers.total
            ? ' <span class="badge badge-fail">' + da.outliers.total + ' ' + __('outliers') + '</span>'
            : ''));

    if (da.completeness) {
        const comp = da.completeness;
        const effectivePresent = comp.present + (comp.covered || 0);
        const pct = comp.total > 0 ? Math.round(effectivePresent / comp.total * 100) : 0;
        const pctColor = pct >= 80 ? 'var(--accent-green)' : pct >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)';
        html += subLabel(__('Completeness') + ' <span style="font-weight:400;">' + pct + '%</span>');
        html += '<div style="font-size:0.72rem;color:var(--text-secondary);margin-bottom:0.3rem;">' + effectivePresent + ' / ' + comp.total + ' ' + __('indicators present (') + (comp.missing || 0) + __(' missing') + ((comp.covered || 0) ? ', ' + comp.covered + __(' covered by parent total') : '') + ')</div>';

        const missing = (comp.indicators || []).filter(i => i.status === 'missing');
        if (missing.length) {
            html += '<details style="margin:0.2rem 0;font-size:0.72rem;">';
            html += '<summary style="cursor:pointer;color:var(--accent-red);">' + missing.length + ' ' + __('missing indicators') + '</summary>';
            missing.forEach(i => {
                html += '<div style="padding:0.1rem 0.5rem;color:var(--text-secondary);">' + esc(i.indicator_code) + ' - ' + esc(i.indicator_name) + '</div>';
            });
            html += '</details>';
        }
        const covered = (comp.indicators || []).filter(i => i.status === 'covered');
        if (covered.length) {
            html += '<details style="margin:0.2rem 0;font-size:0.72rem;">';
            html += '<summary style="cursor:pointer;color:var(--accent-green);">' + covered.length + ' ' + __('covered by parent total') + '</summary>';
            covered.forEach(i => {
                html += '<div style="padding:0.1rem 0.5rem;color:var(--text-secondary);">' + esc(i.indicator_code) + ' - ' + esc(i.indicator_name) + '</div>';
            });
            html += '</details>';
        }
    }

    if (da.rule_failures && da.rule_failures.items && da.rule_failures.items.length) {
        html += subLabel(__('Rule Failures'));
        da.rule_failures.items.slice(0, 10).forEach(r => {
            html += '<div style="padding:0.2rem 0.5rem;border-left:2px solid ' + riskColor(r.severity) + ';margin:0.15rem 0;background:' + riskColor(r.severity) + '06;border-radius:2px;font-size:0.74rem;">';
            html += '<div style="display:flex;justify-content:space-between;"><span><strong>' + esc(r.rule_code) + '</strong> - ' + esc(r.description) + '</span>' + sevClass(r.severity) + '</div>';
            if (r.details) html += '<div style="font-size:0.7rem;color:var(--text-secondary);">' + esc(r.details) + '</div>';
            html += '</div>';
        });
        if (da.rule_failures.items.length > 10) {
            html += '<div style="font-size:0.72rem;color:var(--text-muted);text-align:center;">' + __('... and {n} more').replace('{n}', da.rule_failures.items.length - 10) + '</div>';
        }
    }

    if (da.quality_score && da.quality_score.components) {
        html += subLabel(__('Quality Score Impact'));
        da.quality_score.components.forEach(c => {
            html += '<div style="display:flex;justify-content:space-between;font-size:0.72rem;color:var(--text-secondary);padding:0.1rem 0.5rem;border-bottom:1px solid var(--border-default);">';
            html += '<span>' + esc(c.name) + '</span>';
            html += '<span>' + (c.raw != null ? (c.raw * 100).toFixed(1) + '%' : '--') + ' × ' + c.weight + ' = ' + (c.weighted != null ? Number(c.weighted).toFixed(4) : '--') + ' <span style="color:var(--text-muted);">(' + (c.contribution_pct || 0) + '%)</span></span>';
            html += '</div>';
        });
    }

    if (da.outliers && da.outliers.items && da.outliers.items.length) {
        html += subLabel(__('Outliers'));
        da.outliers.items.forEach(o => {
            html += '<div style="padding:0.2rem 0.5rem;border-left:2px solid var(--accent-red);margin:0.15rem 0;background:var(--bg-elevated);border-radius:2px;font-size:0.74rem;">';
            html += '<div style="display:flex;justify-content:space-between;"><span><strong>' + esc(o.rate_name) + '</strong> (' + esc(o.indicator_code) + ')</span><span style="color:#b71c1c;font-weight:600;">z=' + (o.z_score != null ? Number(o.z_score).toFixed(2) : '--') + '</span></div>';
            html += '<div style="font-size:0.7rem;color:var(--text-secondary);">' + __('Value: ') + (o.value != null ? Number(o.value).toFixed(2) : '--') + ' | ' + __('Benchmark: ') + (o.benchmark != null ? Number(o.benchmark).toFixed(2) : '--') + '</div>';
            html += '</div>';
        });
    }

    if (da.confidence) {
        html += subLabel(__('Confidence'));
        const cf = da.confidence;
        html += '<div style="font-size:0.74rem;color:var(--text-secondary);padding:0.2rem 0.5rem;">' + __('Overall: ') + '<strong>' + esc(cf.overall_confidence != null ? Number(cf.overall_confidence).toFixed(1) : '--') + '</strong> ' + sevClass(cf.level || '') + ' | ' + __('Indicators: ') + (cf.indicator_count || 0) + ' | HIGH: ' + (cf.by_level?.high || 0) + ' MED: ' + (cf.by_level?.medium || 0) + ' LOW: ' + (cf.by_level?.low || 0) + ' CRIT: ' + (cf.by_level?.critical || 0) + '</div>';
    }

    html += '</details></div>';

    // Section 4: Audit Report
    const rpt = d[3] || {};
    html += '<div class="card" style="margin-bottom:0.8rem;padding:0.6rem 0.8rem;">';
    html += '<details>';
    let rptBadge = '';
    if (rpt.verification) {
        const allOk = rpt.verification.all_passed;
        rptBadge = allOk
            ? '<span class="badge badge-pass">✓ ' + __('All verified') + '</span>'
            : '<span class="badge badge-fail">⚠ ' + __('Discrepancies found') + '</span>';
    }
    html += sectTitle(__('4. Audit Report'), rptBadge);

    if (rpt.verification) {
        const v = rpt.verification;
        const allOk = v.all_passed;
        html += '<div style="margin:0.3rem 0;padding:0.3rem 0.5rem;background:' + (allOk ? 'var(--severity-success-bg)' : 'var(--severity-critical-bg)') + ';border-radius:4px;font-size:0.8rem;font-weight:600;color:' + (allOk ? 'var(--accent-green)' : 'var(--accent-red)') + ';">';
        html += allOk ? __('All calculations verified') : __('Some calculations have discrepancies');
        html += '</div>';
        if (v.checks) {
            v.checks.forEach(c => {
                html += '<div style="display:flex;justify-content:space-between;font-size:0.72rem;color:var(--text-secondary);padding:0.1rem 0.5rem;">';
                html += '<span>' + esc(c.check) + '</span>';
                html += '<span style="color:' + (c.status === 'verified' ? '#2e7d32' : '#c62828') + ';">' + esc(c.status) + '</span>';
                html += '</div>';
            });
        }
    }

    html += '<div style="margin:0.5rem 0;display:flex;gap:0.5rem;">';
    html += '<button class="btn btn-sm" onclick="downloadAuditJSON()" style="padding:0.3rem 0.6rem;font-size:0.72rem;">' + __('Download JSON') + '</button>';
    html += '<button class="btn btn-sm" onclick="downloadAuditCSV()" style="padding:0.3rem 0.6rem;font-size:0.72rem;">' + __('Download CSV') + '</button>';
    html += '</div>';

    html += '</details></div>';

    container.innerHTML = html;
}

export function downloadAuditJSON() {
    if (!_auditData) return;
    const meta = _auditMeta || {};
    const blob = new Blob([JSON.stringify(_auditData[3] || _auditData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'audit-report-' + (meta.hid || 'x') + '-' + (meta.month || 'na') + '.json';
    a.click();
    URL.revokeObjectURL(url);
}

export function downloadAuditCSV() {
    if (!_auditData) return;
    const steps = _auditData[0] || {};
    const cls = steps.classifications || [];
    let csv = 'rate_name,value,unit,classification,label\n';
    cls.forEach(c => {
        csv += '"' + c.rate_name + '",' + (c.raw_rate != null ? c.raw_rate : '') + ',' + (c.unit || '') + ',' + (c.classification || '') + ',' + (c.label || '') + '\n';
    });
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'audit-classifications-' + (_auditMeta ? _auditMeta.hid + '-' + _auditMeta.month : '') + '.csv';
    a.click();
    URL.revokeObjectURL(url);
}