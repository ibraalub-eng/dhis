import { API, apiGet } from './api.js';
import { esc } from './tree.js';
import { toastWarning } from './toast.js';

let _auditData = null;

function riskColor(level) {
    if (!level) return 'var(--text-muted)';
    const l = level.toLowerCase();
    if (l === 'critical') return 'var(--accent-red)';
    if (l === 'high') return 'var(--accent-red)';
    if (l === 'moderate' || l === 'elevated') return 'var(--accent-orange)';
    if (l === 'low' || l === 'normal') return 'var(--accent-green)';
    return 'var(--text-muted)';
}

export function initAudit() {
    const hSel = document.getElementById('auditHospitalSelect');
    const mSel = document.getElementById('auditMonthSelect');
    if (!hSel || !mSel) return; // التبويب لم يُحمَّل — لا شيء لنهيئه
    if (hSel.options.length > 1 && mSel.options.length > 1) return;
    Promise.all([
        apiGet('/hospitals/').then(d => {
            const list = d.value || d || [];
            hSel.innerHTML = '<option value="">Select hospital</option>' + list.map(h => '<option value="' + h.id + '">' + esc(h.name) + '</option>').join('');
        }).catch(() => {}),
        fetch(API() + '/analysis/months').then(r => r.json()).then(d => {
            const months = d.months || d || [];
            mSel.innerHTML = '<option value="">Select month</option>' + months.map(m => '<option value="' + m + '">' + m + '</option>').join('');
        }).catch(() => {}),
    ]);
}

export function loadAudit() {
    const hid = document.getElementById('auditHospitalSelect').value;
    const month = document.getElementById('auditMonthSelect').value;
    if (!hid || !month) { toastWarning('Please select hospital and month.'); return; }
    document.getElementById('auditLoading').classList.remove('hidden');
    document.getElementById('auditBtn').disabled = true;
    const container = document.getElementById('auditResults');
    container.innerHTML = '';

    Promise.all([
        fetch(API() + '/audit/calculation-steps/' + hid + '?month=' + month).then(r => r.json()),
        fetch(API() + '/audit/benchmark/' + hid + '?month=' + month).then(r => r.json()),
        fetch(API() + '/audit/data-auditor/' + hid + '?month=' + month).then(r => r.json()),
        fetch(API() + '/audit/report/' + hid + '?month=' + month).then(r => r.json()),
    ]).then(([steps, bench, dataAudit, report]) => {
        _auditData = { steps, bench, dataAudit, report };
        document.getElementById('auditLoading').classList.add('hidden');
        document.getElementById('auditBtn').disabled = false;
        renderAudit();
    }).catch(err => {
        document.getElementById('auditLoading').classList.add('hidden');
        document.getElementById('auditBtn').disabled = false;
        container.innerHTML = '<p style="color:var(--accent-red);">Error: ' + esc(err.message) + '</p>';
    });
}

function renderAudit() {
    const d = _auditData;
    if (!d) return;
    const container = document.getElementById('auditResults');
    let html = '';

    // Section 1: Calculation Steps
    const steps = d.steps || {};
    html += '<div class="card" style="margin-bottom:0.8rem;padding:0.6rem 0.8rem;">';
    html += '<details open>';
    html += '<summary style="cursor:pointer;font-size:0.9rem;font-weight:600;color:var(--accent-blue);">1. Calculation Steps</summary>';

    if (steps.classifications && steps.classifications.length) {
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:var(--text-primary);">Clinical Rates</div>';
        steps.classifications.forEach(c => {
            const color = c.color || '#888';
            html += '<div style="margin:0.3rem 0;padding:0.4rem 0.5rem;background:var(--bg-elevated);border-left:3px solid ' + color + ';border-radius:3px;font-size:0.78rem;">';
            html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
            html += '<strong>' + esc(c.rate_name) + '</strong>';
            html += '<span style="color:' + color + ';font-weight:600;">' + esc(c.label) + '</span>';
            html += '</div>';
            if (c.formula_readable) html += '<div style="font-size:0.72rem;color:var(--text-secondary);margin:0.1rem 0;">Formula: ' + esc(c.formula_readable) + '</div>';
            else if (c.formula) html += '<div style="font-size:0.72rem;color:var(--text-secondary);margin:0.1rem 0;">Formula: ' + esc(c.formula) + '</div>';
            // Inputs with names
            const numParts = (c.numerator_names || []).map(n => esc(n));
            const denName = esc(c.denominator_name || c.denominator_code || '?');
            html += '<div style="font-size:0.72rem;color:var(--text-secondary);margin:0.1rem 0;">';
            html += '<strong>Input Data:</strong> '
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
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:var(--text-primary);">Quality Score</div>';
        const qs = steps.quality_score;
        const qsColor = qs.final_score != null ? (qs.final_score < 50 ? 'var(--accent-red)' : qs.final_score < 70 ? 'var(--accent-orange)' : 'var(--accent-green)') : 'var(--text-muted)';
        html += '<div style="margin:0.3rem 0;padding:0.4rem 0.5rem;background:var(--bg-elevated);border-left:3px solid ' + qsColor + ';border-radius:3px;font-size:0.78rem;">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;"><strong>Final Score</strong><span style="font-weight:700;font-size:1rem;color:' + qsColor + ';">' + (qs.final_score != null ? Number(qs.final_score).toFixed(1) : '--') + '</span></div>';
        if (qs.components) {
            qs.components.forEach(c => {
                html += '<div style="display:flex;justify-content:space-between;font-size:0.72rem;color:var(--text-secondary);padding:0.1rem 0;border-top:1px solid var(--border-default);">';
                html += '<span>' + esc(c.name) + ' (x' + c.weight + ')</span>';
                html += '<span>' + (c.value != null ? Number(c.value).toFixed(3) : '--') + ' -> ' + (c.weighted != null ? Number(c.weighted).toFixed(4) : '--') + '</span>';
                html += '</div>';
            });
        }
        html += '</div>';
    }

    if (steps.risk_profile && steps.risk_profile.metrics && steps.risk_profile.metrics.length) {
        const rp = steps.risk_profile;
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:var(--text-primary);">Risk Profile <span style="font-weight:400;color:' + riskColor(rp.overall_risk_level) + ';">(' + esc(rp.overall_risk_level || '') + ')</span></div>';
        rp.metrics.forEach(m => {
            html += '<div style="display:flex;justify-content:space-between;font-size:0.72rem;color:var(--text-secondary);padding:0.1rem 0.4rem;border-bottom:1px solid var(--border-default);">';
            html += '<span>' + esc(m.metric_name) + '</span>';
            html += '<span>' + (m.value != null ? Number(m.value).toFixed(1) : '--') + esc(m.unit || '') + ' <span style="color:' + riskColor(m.severity) + ';font-weight:600;">' + esc(m.severity || '') + '</span></span>';
            html += '</div>';
        });
    }

    if (steps.morbidity_profile && steps.morbidity_profile.metrics && steps.morbidity_profile.metrics.length) {
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:var(--text-primary);">Morbidity Profile</div>';
        html += '<div style="font-size:0.72rem;color:var(--text-secondary);padding:0.2rem 0.4rem;">SMM: ' + (steps.morbidity_profile.total_smm || 0) + ' | Maternal Deaths: ' + (steps.morbidity_profile.maternal_deaths || 0) + '</div>';
    }

    // Raw Data Store
    if (steps.raw_data && steps.raw_data.length) {
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:var(--text-primary);">Raw Data Store <span style="font-weight:400;color:var(--text-muted);">(' + steps.raw_data.length + ' indicators)</span></div>';
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
    const bench = d.bench || {};
    html += '<div class="card" style="margin-bottom:0.8rem;padding:0.6rem 0.8rem;">';
    html += '<details>';
    html += '<summary style="cursor:pointer;font-size:0.9rem;font-weight:600;color:var(--accent-blue);">2. Benchmark Comparison</summary>';
    if (bench.comparisons) {
        Object.keys(bench.comparisons).sort().forEach(rname => {
            const c = bench.comparisons[rname];
            const barColor = riskColor(c.status);
            const arrow = (c.percent_deviation || 0) > 0 ? '↑' : '↓';
            html += '<div style="margin:0.4rem 0;padding:0.3rem 0.5rem;background:var(--bg-elevated);border-left:3px solid ' + barColor + ';border-radius:3px;font-size:0.78rem;">';
            html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
            html += '<strong>' + esc(rname) + '</strong>';
            html += '<span style="color:' + barColor + ';font-weight:600;">' + arrow + ' ' + Math.abs(c.percent_deviation || 0).toFixed(1) + '% vs avg</span>';
            html += '</div>';
            html += '<div style="margin:0.2rem 0;height:0.5rem;background:var(--border-default);border-radius:3px;position:relative;">';
            html += '<div style="height:100%;width:' + Math.min(Math.abs(c.percent_deviation || 0), 100) + '%;background:' + barColor + ';border-radius:3px;opacity:0.6;"></div>';
            html += '</div>';
            html += '<div style="font-size:0.72rem;color:var(--text-secondary);">Hospital: <strong>' + (c.hospital_value || 0) + '</strong> | Avg: ' + (c.peer_average || 0) + ' | Median: ' + (c.peer_median || 0) + ' | Range: [' + (c.peer_min || 0) + ' - ' + (c.peer_max || 0) + ']</div>';
            html += '<div style="font-size:0.72rem;color:var(--text-secondary);">Z-score: ' + (c.z_score || 0) + ' | Percentile: ' + (c.percentile || 0) + 'th | Peers: ' + (c.peer_count || 0) + '</div>';
            html += '</div>';
        });
    } else {
        html += '<p style="color:var(--text-muted);text-align:center;padding:1rem;">No benchmark data available.</p>';
    }
    html += '</details></div>';

    // Section 3: Data Auditor
    const da = d.dataAudit || {};
    html += '<div class="card" style="margin-bottom:0.8rem;padding:0.6rem 0.8rem;">';
    html += '<details>';
    html += '<summary style="cursor:pointer;font-size:0.9rem;font-weight:600;color:var(--accent-blue);">3. Data Auditor</summary>';

    if (da.completeness) {
        const comp = da.completeness;
        const pct = comp.total > 0 ? Math.round(comp.present / comp.total * 100) : 0;
        const pctColor = pct >= 80 ? 'var(--accent-green)' : pct >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)';
        html += '<div style="margin:0.3rem 0;font-weight:600;font-size:0.8rem;color:var(--text-primary);">Completeness <span style="font-weight:400;color:' + pctColor + ';">(' + pct + '%)</span></div>';
        html += '<div style="font-size:0.72rem;color:var(--text-secondary);margin-bottom:0.3rem;">' + comp.present + ' / ' + comp.total + ' indicators present (' + comp.missing + ' missing)</div>';

        const missing = (comp.indicators || []).filter(i => i.status === 'missing');
        if (missing.length) {
            html += '<details style="margin:0.2rem 0;font-size:0.72rem;">';
            html += '<summary style="cursor:pointer;color:var(--accent-red);">' + missing.length + ' missing indicators</summary>';
            missing.forEach(i => {
                html += '<div style="padding:0.1rem 0.5rem;color:var(--text-secondary);">' + esc(i.indicator_code) + ' - ' + esc(i.indicator_name) + '</div>';
            });
            html += '</details>';
        }
    }

    if (da.rule_failures && da.rule_failures.items && da.rule_failures.items.length) {
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:var(--text-primary);">Rule Failures (' + da.rule_failures.total + ')</div>';
        da.rule_failures.items.slice(0, 10).forEach(r => {
            html += '<div style="padding:0.2rem 0.5rem;border-left:2px solid ' + riskColor(r.severity) + ';margin:0.15rem 0;background:' + riskColor(r.severity) + '06;border-radius:2px;font-size:0.74rem;">';
            html += '<div style="display:flex;justify-content:space-between;"><span><strong>' + esc(r.rule_code) + '</strong> - ' + esc(r.description) + '</span><span style="color:' + riskColor(r.severity) + ';font-weight:600;">' + esc(r.severity) + '</span></div>';
            if (r.details) html += '<div style="font-size:0.7rem;color:var(--text-secondary);">' + esc(r.details) + '</div>';
            html += '</div>';
        });
        if (da.rule_failures.items.length > 10) {
            html += '<div style="font-size:0.72rem;color:var(--text-muted);text-align:center;">... and ' + (da.rule_failures.items.length - 10) + ' more</div>';
        }
    }

    if (da.quality_score && da.quality_score.components) {
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:var(--text-primary);">Quality Score Impact</div>';
        da.quality_score.components.forEach(c => {
            html += '<div style="display:flex;justify-content:space-between;font-size:0.72rem;color:var(--text-secondary);padding:0.1rem 0.5rem;border-bottom:1px solid var(--border-default);">';
            html += '<span>' + esc(c.name) + '</span>';
            html += '<span>' + (c.raw != null ? (c.raw * 100).toFixed(1) + '%' : '--') + ' x ' + c.weight + ' = ' + (c.weighted != null ? Number(c.weighted).toFixed(4) : '--') + ' (' + (c.contribution_pct || 0) + '%)</span>';
            html += '</div>';
        });
    }

    if (da.outliers && da.outliers.items && da.outliers.items.length) {
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:var(--text-primary);">Outliers (' + da.outliers.total + ')</div>';
        da.outliers.items.forEach(o => {
            html += '<div style="padding:0.2rem 0.5rem;border-left:2px solid var(--accent-red);margin:0.15rem 0;background:var(--bg-elevated);border-radius:2px;font-size:0.74rem;">';
            html += '<div style="display:flex;justify-content:space-between;"><span><strong>' + esc(o.rate_name) + '</strong> (' + esc(o.indicator_code) + ')</span><span style="color:#b71c1c;font-weight:600;">z=' + (o.z_score != null ? Number(o.z_score).toFixed(2) : '--') + '</span></div>';
            html += '<div style="font-size:0.7rem;color:var(--text-secondary);">Value: ' + (o.value != null ? Number(o.value).toFixed(2) : '--') + ' | Benchmark: ' + (o.benchmark != null ? Number(o.benchmark).toFixed(2) : '--') + '</div>';
            html += '</div>';
        });
    }

    if (da.confidence) {
        html += '<div style="margin:0.5rem 0 0.3rem 0;font-weight:600;font-size:0.8rem;color:var(--text-primary);">Confidence</div>';
        const cf = da.confidence;
        html += '<div style="font-size:0.74rem;color:var(--text-secondary);padding:0.2rem 0.5rem;">Overall: <strong>' + esc(cf.overall_confidence != null ? Number(cf.overall_confidence).toFixed(1) : '--') + '</strong> (' + esc(cf.level || '') + ') | Indicators: ' + (cf.indicator_count || 0) + ' | HIGH: ' + (cf.by_level?.high || 0) + ' MED: ' + (cf.by_level?.medium || 0) + ' LOW: ' + (cf.by_level?.low || 0) + ' CRIT: ' + (cf.by_level?.critical || 0) + '</div>';
    }

    html += '</details></div>';

    // Section 4: Audit Report
    const rpt = d.report || {};
    html += '<div class="card" style="margin-bottom:0.8rem;padding:0.6rem 0.8rem;">';
    html += '<details>';
    html += '<summary style="cursor:pointer;font-size:0.9rem;font-weight:600;color:var(--accent-blue);">4. Audit Report</summary>';

    if (rpt.verification) {
        const v = rpt.verification;
        const allOk = v.all_passed;
        html += '<div style="margin:0.3rem 0;padding:0.3rem 0.5rem;background:' + (allOk ? 'var(--severity-success-bg)' : 'var(--severity-critical-bg)') + ';border-radius:4px;font-size:0.8rem;font-weight:600;color:' + (allOk ? 'var(--accent-green)' : 'var(--accent-red)') + ';">';
        html += allOk ? 'All calculations verified' : 'Some calculations have discrepancies';
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
    html += '<button class="btn btn-sm" onclick="downloadAuditJSON()" style="padding:0.3rem 0.6rem;font-size:0.72rem;">Download JSON</button>';
    html += '<button class="btn btn-sm" onclick="downloadAuditCSV()" style="padding:0.3rem 0.6rem;font-size:0.72rem;">Download CSV</button>';
    html += '</div>';

    html += '</details></div>';

    container.innerHTML = html;
}

export function downloadAuditJSON() {
    if (!_auditData) return;
    const blob = new Blob([JSON.stringify(_auditData.report || _auditData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'audit-report.json';
    a.click();
    URL.revokeObjectURL(url);
}

export function downloadAuditCSV() {
    if (!_auditData) return;
    const steps = _auditData.steps || {};
    const cls = steps.classifications || [];
    let csv = 'rate_name,value,unit,classification,label\n';
    cls.forEach(c => {
        csv += '"' + c.rate_name + '",' + (c.raw_rate != null ? c.raw_rate : '') + ',' + (c.unit || '') + ',' + (c.classification || '') + ',' + (c.label || '') + '\n';
    });
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'audit-classifications.csv';
    a.click();
    URL.revokeObjectURL(url);
}
