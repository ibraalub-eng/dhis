// ── Rules Manager module ──────────────────────────────────────────
// Split out of settings.js (which was 3.5k+ lines). Owns the rules table,
// details drawer, test modal, history viewer, and export/import flows.
import { API, apiGet, apiPost, apiPut, clearApiCache } from './api.js';

import { DataTable, scoreBadge, trendIcon, confidenceBar } from './table-utils.js';
import { __ } from './i18n.js';
import { esc } from './tree.js';
import { _saveUIState, _restoreUIState, SwitchTab, _tabInited } from './main.js';
import { toastSuccess, toastError, toastWarning } from './toast.js';
import { confirmDestructive, confirmWarning } from './confirm-modal.js';

        // ── Rules Manager ─────────────────────────────────────────
        export let rulesManagerData = [];
        let _rulesImpactMap = {};
        let _rulesSortCol = null;   // null = default order (code asc)
        let _rulesSortAsc = true;
        let rulesSortCol = null, rulesSortAsc = true;
        let _rulesDirty = false;
        let _forceRulesImpactRefresh = false;

        // Called by other modules (rules.js edit modal) after a rule is
        // saved/deleted so the next loadRulesManager() recomputes the impact
        // map (referenced indicators, affected hospitals) instead of reading
        // the server's 5-minute memo.
        export function forceRulesImpactRefresh() { _forceRulesImpactRefresh = true; }
        window.forceRulesImpactRefresh = forceRulesImpactRefresh;

        // ── Search-box anti-autofill guard ──────────────
        // Chrome & co. ignore autocomplete="off" and autofill the saved login
        // username into text-like inputs — the rules search box kept receiving
        // it (type="search" is not reliably excluded in all builds). Since
        // nobody searches rule codes by typing their own username, any value
        // matching the current user's credentials is browser junk: it is
        // reverted on render, dropped from the input event, never persisted.
        function _rulesLoginCandidates() {
            try {
                const u = (typeof window.getUserInfo === 'function') ? window.getUserInfo() : null;
                if (!u) return [];
                return [u.username, u.full_name, u.email].filter(Boolean);
            } catch (e) { return []; }
        }
        function _rulesSearchIsLoginJunk(v) {
            return !!v && _rulesLoginCandidates().indexOf(v) !== -1;
        }
        // App-owned search value + whether the user actually typed since the
        // last restore/reset. window props so main.js can reset them.
        window._rulesSearchAppState = '';
        window._rulesSearchTouched = false;

        function _updateRulesImpactHeader(latestMonth) {
            const hdr = document.querySelector('#rulesTable thead th[data-impact-col]');
            if (hdr) {
                hdr.textContent = 'Affected Hospitals';
                hdr.title = latestMonth
                    ? 'Hospitals where the rule fails right now, live-checked for month ' + latestMonth
                    : 'Hospitals where the rule currently fails';
            }
        }

        export function updateWeightDisplay() {
            const fields = ['rule_compliance', 'historical', 'cross_hospital', 'trend', 'completeness'];
            let total = 0;
            fields.forEach(f => {
                const val = parseFloat(document.getElementById('weight_' + f).value);
                document.getElementById('val_' + f).textContent = val.toFixed(2);
                total += val;
            });
            document.getElementById('weight_total').textContent = total.toFixed(2);
            const status = document.getElementById('weight_total_status');
            if (Math.abs(total - 1.0) < 0.01) {
                status.textContent = '\u2713 OK';
                status.style.color = 'var(--accent-green)';
            } else {
                status.textContent = '\u2717 Must be 1.0';
                status.style.color = 'var(--accent-red)';
            }
            _renderConfPreview();
        }

        export function updateCfgDisplay(category) {
            if (category === 'quality') {
                const fields = ['quality_rule_compliance', 'quality_completeness', 'quality_consistency', 'quality_outlier_penalty'];
                let total = 0;
                fields.forEach(f => {
                    const val = parseFloat(document.getElementById('cfg_' + f).value);
                    document.getElementById('cfgval_' + f).textContent = val.toFixed(2);
                    total += val;
                });
                document.getElementById('cfgtotal_quality').textContent = total.toFixed(2);
                const status = document.getElementById('cfgtotal_status_quality');
                if (Math.abs(total - 1.0) < 0.01) {
                    status.textContent = '\u2713 OK';
                    status.style.color = 'var(--accent-green)';
                } else {
                    status.textContent = '\u2717 Must be 1.0';
                    status.style.color = 'var(--accent-red)';
                }
            }
            _renderQualityPreview();
        }

        export function updateCfgVal(key) {
            const el = document.getElementById('cfg_' + key);
            const valEl = document.getElementById('cfgval_' + key);
            if (el && valEl) valEl.textContent = fmtCfgVal(key, el.value);
            if (key && key.indexOf('clinical_') === 0 && typeof _refreshClinicalPreviews === 'function') _refreshClinicalPreviews();
            if (key && key.indexOf('confidence_') === 0 && typeof _renderConfPreview === 'function') _renderConfPreview();
        }

        function fmtCfgVal(key, value) {
            const v = parseFloat(value);
            const intKeys = ['trend_finding_consecutive', 'ml_clustering_min_k', 'ml_clustering_max_k', 'ml_enabled', 'ml_clustering_enabled', 'ml_anomaly_enabled', 'ml_pca_enabled'];
            const doubleKeys = ['ml_anomaly_contamination', 'ml_pca_variance_threshold'];
            const tripleKeys = ['eq_tolerance'];
            if (intKeys.includes(key)) return Math.round(v).toString();
            if (doubleKeys.includes(key)) return v.toFixed(2);
            if (tripleKeys.includes(key)) return v.toFixed(3);
            return v.toFixed(1);
        }

        export function showSettingsTab(name) {
            ['quality', 'confidence', 'thresholds', 'rules', 'clinical', 'risk', 'trends', 'rates', 'ai', 'database', 'hospitals', 'ml', 'account'].forEach(s => {
                const section = document.getElementById('settings-' + s);
                if (section) section.style.display = s === name ? '' : 'none';
                const btn = document.getElementById('stbtn-' + s);
                if (!btn) return;
                if (s === name) {
                    btn.className = 'btn btn-sm';
                    btn.style.background = s === 'ai' ? 'var(--accent-red)' : s === 'hospitals' ? 'var(--accent-blue)' : 'var(--accent-blue)';
                    btn.style.color = 'white';
                } else {
                    btn.className = 'btn btn-sm btn-outline';
                    btn.style.background = '';
                    btn.style.color = '';
                }
            });
            if (name === 'ai') loadAiSettings();
            if (name === 'hospitals') loadHospitalsSettings();
            if (name === 'account') loadSelfProfile();
            window._activeSettingsTab = name;
            if (typeof settingsApplySearchFilter === 'function') settingsApplySearchFilter();
        }



        
        // Self password change
        window.loadSelfProfile = async function() {
    try {
        var token = getAccessToken();
        var resp = await authFetch(API() + '/auth/me', {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        if (!resp.ok) throw new Error('Failed to load profile');
        var data = await resp.json();
        var unEl = document.getElementById('selfUsername');
        var nameEl = document.getElementById('selfFullName');
        var emailEl = document.getElementById('selfEmail');
        if (unEl) unEl.value = data.username || '';
        if (nameEl) nameEl.value = data.full_name || '';
        if (emailEl) emailEl.value = data.email || '';
    } catch(e) {
        console.error('loadSelfProfile error:', e);
    }
};

window.saveSelfProfile = async function() {
    var nameEl = document.getElementById('selfFullName');
    var emailEl = document.getElementById('selfEmail');
    var errEl = document.getElementById('selfProfileError');
    var okEl = document.getElementById('selfProfileSuccess');
    errEl.style.display = 'none';
    okEl.style.display = 'none';
    var fullName = nameEl ? nameEl.value.trim() : '';
    var email = emailEl ? emailEl.value.trim() : '';
    if (!fullName) { errEl.textContent = 'Full name is required'; errEl.style.display = 'block'; return; }
    if (!email) { errEl.textContent = 'Email is required'; errEl.style.display = 'block'; return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { errEl.textContent = 'Invalid email format'; errEl.style.display = 'block'; return; }
    try {
        var token = getAccessToken();
        var resp = await authFetch(API() + '/auth/me', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
            body: JSON.stringify({ full_name: fullName, email: email })
        });
        var data = await resp.json();
        if (!resp.ok) { errEl.textContent = data.detail || 'Failed to update profile'; errEl.style.display = 'block'; return; }
        okEl.textContent = '✓ Profile updated successfully!';
        okEl.style.display = 'block';
        // Update stored user data
        var stored = JSON.parse(localStorage.getItem('user') || '{}');
        stored.full_name = data.full_name;
        stored.email = data.email;
        localStorage.setItem('user', JSON.stringify(stored));
    } catch(e) {
        errEl.textContent = 'Network error: ' + e.message;
        errEl.style.display = 'block';
    }
};


function loadHospitalsSettings() {
            const container = document.getElementById('settingsHospitalsContent');
            if (!container) return;
            if (container.dataset.loaded === 'true') return;
            container.dataset.loaded = 'true';
            authFetch('/static/tabs/hospitals.html').then(r => r.text()).then(html => {
                container.innerHTML = html;
                if (typeof window.loadHospitalsTab === 'function') {
                    window.loadHospitalsTab();
                } else {
                    // Retry if app.js module hasn't loaded yet
                    setTimeout(function() {
                        if (typeof window.loadHospitalsTab === 'function') window.loadHospitalsTab();
                    }, 500);
                }
            }).catch(err => {
                container.innerHTML = '<div style="padding:1rem;text-align:center;color:var(--accent-red);">Failed to load hospitals management: ' + (err.message || 'Network error') + '</div>';
            });
        }

        function loadWeights() {
            return apiGet('/confidence/weights').then(w => {
                document.getElementById('weight_rule_compliance').value = w.rule_compliance;
                document.getElementById('weight_historical').value = w.historical;
                document.getElementById('weight_cross_hospital').value = w.cross_hospital;
                document.getElementById('weight_trend').value = w.trend;
                document.getElementById('weight_completeness').value = w.completeness;
                updateWeightDisplay();
            }).catch(() => {});
        }

        // ── Mini sparkline (SVG) for factor history ─────────────
        function _rcSparkline(history) {
            const w = 64, h = 18, pad = 1;
            const vals = history.map(p => Number(p.value) || 0);
            if (!vals.length) return '';
            const min = Math.min(...vals), max = Math.max(...vals);
            const span = (max - min) || 1;
            const pts = vals.map((v, i) => {
                const x = pad + (i * (w - 2 * pad)) / (vals.length - 1 || 1);
                const y = h - pad - ((v - min) / span) * (h - 2 * pad);
                return x.toFixed(1) + ',' + y.toFixed(1);
            });
            // القيم تاريخ لنسبة فشل القاعدة: انخفاض = تحسّن (أخضر)، ارتفاع = تدهور (أحمر)
            const color = vals[vals.length - 1] < vals[0] ? 'var(--accent-teal)' : 'var(--accent-red)';
            const lastX = pts[pts.length - 1].split(',')[0];
            const lastY = pts[pts.length - 1].split(',')[1];
            return '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" style="vertical-align:middle;">' +
                '<polyline points="' + pts.join(' ') + '" fill="none" stroke="' + color + '" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>' +
                '<circle cx="' + lastX + '" cy="' + lastY + '" r="2" fill="' + color + '"/></svg>';
        }

        // ── Timeline: indicator value vs peer average (95% CI) ───────────
        let _rcTimelineData = { indicators: [] };
        // Peer-group selector value for Root Cause API calls ('auto' default)
        function _rcPeerQ() {
            const el = document.getElementById('rcPeerMode');
            return '&peer_mode=' + encodeURIComponent(el && el.value ? el.value : 'auto');
        }
        let _rcTimelineSelCode = null;  // يُحفظ كود المؤشر لا فهرسه (الفهرس يتغير باختلاف المستشفى)

        function drawRcTimelineChart(ind) {
            const chartEl = document.getElementById('rcTimelineChart');
            const textEl = document.getElementById('rcTimelineText');
            if (!chartEl || !ind) return;
            // Keep the Peer Hospitals table in sync with the selected indicator
            _renderRcPeerHospitalsTable(ind);

            const months = ind.series.map(p => p.month);
            const hv = ind.series.map(p => p.hospital_value);
            const pm = ind.series.map(p => p.peer_mean);

            // CI band data
            const bandUpper = ind.series.map(p => p.peer_upper);
            const bandLower = ind.series.map(p => p.peer_lower);

            // Destroy existing chart if any
            if (window._rcTimelineChartInstance) {
                window._rcTimelineChartInstance.destroy();
                window._rcTimelineChartInstance = null;
            }

            // Create new Chart.js chart
            const ctx = chartEl.getContext('2d');
            try {
            window._rcTimelineChartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: months,
                    datasets: [
                        {
                            label: (ind.indicator_name || ind.indicator_code) + ' — ' + __('Hospital'),
                            data: hv,
                            borderColor: CHART_COLORS.primary,
                            backgroundColor: CHART_COLORS.primary,
                            _colorRole: 'primary',
                            borderWidth: 2.5,
                            pointRadius: 5,
                            pointHoverRadius: 7,
                            tension: 0.3,
                            fill: false,
                        },
                        {
                            label: __('Peer average'),
                            data: pm,
                            borderColor: CHART_COLORS.secondary,
                            backgroundColor: CHART_COLORS.secondary,
                            _colorRole: 'secondary',
                            borderWidth: 2,
                            borderDash: [5, 5],
                            pointRadius: 4,
                            pointHoverRadius: 6,
                            tension: 0.3,
                            fill: false,
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'top',
                            labels: {
                                font: { size: 10 },
                                color: CHART_COLORS.neutral,
                                usePointStyle: true,
                            }
                        },
                        tooltip: {
                            backgroundColor: getCSSVar('--bg-elevated') || '#1e293b',
                            titleFont: { size: 11 },
                            bodyFont: { size: 11 },
                            padding: 12,
                            cornerRadius: 6,
                            callbacks: {
                                title: function(items) {
                                    return items[0].label;
                                },
                                label: function(context) {
                                    const label = context.dataset.label || '';
                                    const value = context.parsed.y;
                                    return label + ': ' + value.toFixed(1);
            if (window.registerChart) window.registerChart(window._rcTimelineChartInstance);
                                },
                                afterBody: function(items) {
                                    const monthIndex = items[0].dataIndex;
                                    const peerCount = ind.series[monthIndex]?.peer_count;
                                    return peerCount ? 'Peer hospitals: ' + peerCount : '';
                                }
                            }
                        },
                        ciBand: {
                            upper: bandUpper,
                            lower: bandLower
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: CHART_COLORS.grid },
                            ticks: { color: CHART_COLORS.neutral, font: { size: 10 } }
                        },
                        y: {
                            grid: { color: CHART_COLORS.grid },
                            ticks: { color: CHART_COLORS.neutral, font: { size: 10 } },
                            beginAtZero: false,
                        }
                    },
                    interaction: {
                        intersect: false,
                        mode: 'index'
                    }
                },
                plugins: [ciBandPlugin]
            });
            } catch (e) {
                console.error('Chart.js error:', e);
                if (textEl) textEl.textContent = 'Error rendering chart: ' + e.message;
                return;
            }

            if (textEl) {
                const withPeer = ind.series.filter(p => p.peer_count > 0);
                const avgPeers = withPeer.length
                    ? Math.round(withPeer.reduce((a, p) => a + (p.peer_count || 0), 0) / withPeer.length)
                    : 0;
                if (avgPeers > 0) {
                    textEl.innerHTML = __('Solid line: hospital value month by month. Dashed line: peer average. Shaded band: 95% confidence interval around the peer average.') + ' <strong>' + __('Average peer count:') + ' ' + avgPeers + '</strong>';
                } else {
                    textEl.innerHTML = '⚠️ ' + __('No peer data for this hospital. Only the hospital value is shown. For peer comparison, select by hospital using the type info column (type/ownership/governorate).');
                }
            }
        }

        export function renderRcTimeline() {
            const sel = document.getElementById('rcTimelineIndicator');
            const chartEl = document.getElementById('rcTimelineChart');
            const textEl = document.getElementById('rcTimelineText');
            if (!sel || !chartEl) return;
            const inds = (_rcTimelineData.indicators || []).filter(i => (i.series || []).length >= 2);
            if (!inds.length) {
                sel.innerHTML = '<option value="">' + __('Not enough time-series data') + '</option>';
                if (window._rcTimelineChartInstance) {
                    window._rcTimelineChartInstance.destroy();
                    window._rcTimelineChartInstance = null;
                }
                if (textEl) textEl.textContent = __('No data — the timeline comparison needs two or more months for the hospital and its peers.');
                return;
            }
            sel.innerHTML = inds.map((i, idx) =>
                '<option value="' + idx + '">' + esc(i.indicator_name || i.indicator_code) + ' (' + esc(i.indicator_code) + ')</option>'
            ).join('');
            if (_rcTimelineSelCode != null) {
                const match = inds.findIndex(i => i.indicator_code === _rcTimelineSelCode);
                if (match >= 0) {
                    sel.value = String(match);
                } else {
                    _rcTimelineSelCode = inds[0] ? inds[0].indicator_code : null;
                }
            } else if (inds[0]) {
                _rcTimelineSelCode = inds[0].indicator_code;
            }
            drawRcTimelineChart(inds[parseInt(sel.value, 10) || 0]);
        }

        export function renderRcTimelineChart() {
            const sel = document.getElementById('rcTimelineIndicator');
            const inds = (_rcTimelineData.indicators || []).filter(i => (i.series || []).length >= 2);
            if (!sel || !inds.length) return;
            const idx = parseInt(sel.value, 10);
            if (!isNaN(idx) && inds[idx]) _rcTimelineSelCode = inds[idx].indicator_code;
            drawRcTimelineChart(inds[idx || 0]);
        }

        function _loadRootCauseAllMonths(hid) {
            // Fetch root cause for each available month and aggregate
            apiGet('/analysis/months').then(months => {
                if (!months || !months.length) {
                    document.getElementById('rcLoading').style.display = 'none';
                    document.getElementById('rcContent').style.display = 'block';
                    document.getElementById('rcKpiBar').innerHTML = '<div style="text-align:center;padding:1rem;color:var(--text-muted);">No months with data</div>';
                    return;
                }
            const promises = months.map(m =>
                    apiGet('/root-cause/' + hid + '?month=' + m + '&include_history=true&compare_peers=true&months_back=6' + _rcPeerQ())
                        .catch(() => null)
                );
                Promise.all(promises).then(results => {
                    const valid = results.filter(d => d && !d.error);
                    if (!valid.length) {
                        document.getElementById('rcLoading').style.display = 'none';
                        document.getElementById('rcContent').style.display = 'block';
                        document.getElementById('rcKpiBar').innerHTML = '<div style="text-align:center;padding:1rem;color:var(--text-muted);">No root cause data available</div>';
                        return;
                    }
                    // Aggregate: average scores, sum critical issues, combine rule failures
                    const avgQs = valid.reduce((s, d) => s + (d.overall_quality_score || 0), 0) / valid.length;
                    const avgConf = valid.reduce((s, d) => s + (d.overall_confidence || 0), 0) / valid.length;
                    const totalCi = valid.reduce((s, d) => s + (d.critical_issues_count || 0), 0);
                    // Merge priority actions (deduplicate by action text)
                    const actionMap = new Map();
                    valid.forEach(d => {
                        (d.priority_actions || []).forEach(a => {
                            if (!actionMap.has(a)) actionMap.set(a, { action: a, months: [] });
                            actionMap.get(a).months.push(d.month);
                        });
                    });
                    const mergedActions = [...actionMap.values()]
                        .sort((a, b) => b.months.length - a.months.length)
                        .map(a => a.action);
                    // Merge rule failures
                    const rfMap = new Map();
                    valid.forEach(d => {
                        (d.top_rule_failures || []).forEach(rf => {
                            const key = rf.rule_code || rf.rule || JSON.stringify(rf);
                            if (!rfMap.has(key)) rfMap.set(key, { ...rf, count: 0, months: [] });
                            const entry = rfMap.get(key);
                            entry.count++;
                            entry.months.push(d.month);
                            if (rf.failure_rate > (entry.failure_rate || 0)) entry.failure_rate = rf.failure_rate;
                        });
                    });
                    const mergedRf = [...rfMap.values()]
                        .sort((a, b) => b.count - a.count || (b.failure_rate || 0) - (a.failure_rate || 0));
                    // Combine summaries
                    const summaries = valid.map(d => d.summary_arabic || d.summary).filter(Boolean);
                    const combinedSummary = summaries.length > 1
                        ? summaries.map((s, i) => '<div style="margin-bottom:0.3rem;"><span style="font-weight:600;color:var(--accent-blue);">' + valid[i].month + ':</span> ' + esc(s) + '</div>').join('')
                        : (summaries[0] || 'No summary available.');
                    // Merge confidence gaps (deduplicate by indicator, keep worst severity)
                    const cgMap = new Map();
                    const severityOrder = { CRITICAL: 4, HIGH: 3, LOW: 2, MEDIUM: 2, INFO: 1 };
                    valid.forEach(d => {
                        (d.confidence_gaps || []).forEach(cg => {
                            const key = cg.indicator_name || cg.indicator || '';
                            if (!key) return;
                            if (!cgMap.has(key) || (severityOrder[(cg.level||'').toUpperCase()] || 0) > (severityOrder[(cgMap.get(key).level||'').toUpperCase()] || 0)) {
                                cgMap.set(key, { ...cg, _months: (cgMap.get(key)?._months || []).concat([d.month]) });
                            } else if (cgMap.has(key)) {
                                cgMap.get(key)._months.push(d.month);
                            }
                        });
                    });
                    const mergedCg = [...cgMap.values()].sort((a, b) => (severityOrder[(b.level||'').toUpperCase()] || 0) - (severityOrder[(a.level||'').toUpperCase()] || 0));
                    // Merge causal chains (deduplicate by root cause, keep highest confidence)
                    const chainMap = new Map();
                    valid.forEach(d => {
                        (d.causal_chains || []).forEach(c => {
                            const key = c.root_cause || c.root_cause_arabic || JSON.stringify(c.chain_path || []);
                            if (!chainMap.has(key) || (c.confidence || 0) > (chainMap.get(key).confidence || 0)) {
                                chainMap.set(key, { ...c, _months: (chainMap.get(key)?._months || []).concat([d.month]) });
                            } else if (chainMap.has(key)) {
                                chainMap.get(key)._months.push(d.month);
                            }
                        });
                    });
                    const mergedChains = [...chainMap.values()].sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
                    // Merge causal tree (deduplicate by factor, keep highest severity)
                    const treeMap = new Map();
                    const treeSev = { CRITICAL: 4, critical: 4, HIGH: 3, high: 3, MEDIUM: 2, medium: 2, LOW: 1, low: 1 };
                    valid.forEach(d => {
                        (d.causal_tree || []).forEach(n => {
                            const key = n.factor || '';
                            if (!key) return;
                            if (!treeMap.has(key) || (treeSev[n.severity] || 0) > (treeSev[treeMap.get(key).severity] || 0)) {
                                treeMap.set(key, { ...n, _months: (treeMap.get(key)?._months || []).concat([d.month]) });
                            } else if (treeMap.has(key)) {
                                treeMap.get(key)._months.push(d.month);
                            }
                        });
                    });
                    const mergedTree = [...treeMap.values()].sort((a, b) => (treeSev[b.severity] || 0) - (treeSev[a.severity] || 0));
                    // Merge peer comparisons (average peer values across months)
                    const peerMap = new Map();
                    valid.forEach(d => {
                        Object.values(d.peer_comparisons || {}).forEach(p => {
                            const key = p.indicator_code || p.indicator_name || '';
                            if (!key) return;
                            if (!peerMap.has(key)) {
                                peerMap.set(key, { ...p, _sumGap: p.gap_pct || 0, _sumHv: p.hospital_value || 0, _sumPm: p.peer_mean || 0, _count: 1 });
                            } else {
                                const e = peerMap.get(key);
                                e._sumGap += (p.gap_pct || 0);
                                e._sumHv += (p.hospital_value || 0);
                                e._sumPm += (p.peer_mean || 0);
                                e._count++;
                            }
                        });
                    });
                    const mergedPeers = {};
                    peerMap.forEach((v, k) => {
                        mergedPeers[k] = {
                            indicator_code: v.indicator_code,
                            indicator_name: v.indicator_name,
                            gap_pct: Math.round(v._sumGap / v._count * 10) / 10,
                            hospital_value: Math.round(v._sumHv / v._count * 10) / 10,
                            peer_mean: Math.round(v._sumPm / v._count * 10) / 10,
                            peer_count: v.peer_count,
                        };
                    });
                    // Build per-month arrays for trend chart
                    const sortedValid = [...valid].sort((a, b) => (a.month || '').localeCompare(b.month || ''));
                    const monthLabels = sortedValid.map(d => d.month);
                    const monthQs = sortedValid.map(d => d.overall_quality_score || 0);
                    const monthConf = sortedValid.map(d => d.overall_confidence || 0);
                    const monthCi = sortedValid.map(d => d.critical_issues_count || 0);
                    // Build aggregated report object
                    const agg = {
                        hospital: valid[0].hospital,
                        hospital_id: hid,
                        month: 'all (' + valid.length + ' months)',
                        overall_quality_score: Math.round(avgQs * 10) / 10,
                        overall_confidence: Math.round(avgConf * 10) / 10,
                        critical_issues_count: totalCi,
                        summary_arabic: combinedSummary,
                        summary: combinedSummary,
                        priority_actions: mergedActions,
                        priority_action_details: [],
                        top_rule_failures: mergedRf,
                        confidence_gaps: mergedCg,
                        anomaly_patterns: [],
                        causal_tree: mergedTree,
                        causal_chains: mergedChains,
                        historical_trends: {},
                        peer_comparisons: mergedPeers,
                        _allMonths: true,
                        _monthCount: valid.length,
                        _months: monthLabels,
                        _monthQs: monthQs,
                        _monthConf: monthConf,
                        _monthCi: monthCi,
                    };
                    document.getElementById('rcLoading').style.display = 'none';
                    document.getElementById('rcContent').style.display = 'block';
                    _renderRootCauseResult(agg, hid, 'all');
                });
            });
        }

        let _rcReportData = null;

        // Peer Hospitals table — per selected timeline indicator when available:
        // lists each peer with its value for the chosen indicator (report month).
        function _renderRcPeerHospitalsTable(ind) {
            const peerHospEl = document.getElementById('rcPeerHospitals');
            if (!peerHospEl) return;
            const d = _rcReportData;
            if (!d) return;
            const mth = d._month || d.month || '';
            const peersList = (ind && ind.peers_detail && ind.peers_detail.length)
                ? ind.peers_detail
                : (d.peer_hospitals || []);
            const perIndicator = ind && ind.peers_detail && ind.peers_detail.length;
            peerHospEl.innerHTML = '';
            if (perIndicator) {
                const rows = ind.peers_detail.map(p => {
                    const meta = (d.peer_hospitals || []).find(h => h.name === p.hospital) || {};
                    return {
                        ...p,
                        hospital_id: meta.hospital_id,
                        governorate: meta.governorate || '',
                        hospital_type: meta.hospital_type || '',
                    };
                });
                const indName = esc(ind.indicator_name || ind.indicator_code);
                peerHospEl.innerHTML =
                    '<div style="font-size:0.7rem;color:var(--text-secondary);margin-bottom:0.4rem;">' + __('Peers for indicator') + ' <strong>' + indName + '</strong> ' + __('for month') + ' ' + esc(mth) + ' — ' + rows.length + ' ' + __('hospital(s), sorted by value') + '</div>' +
                    '<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;">' +
                    '<thead><tr style="font-size:0.68rem;color:var(--text-muted);text-align:right;">' +
                    '<th style="padding:0.3rem 0.5rem;border-bottom:1px solid var(--border-default);">' + __('Hospital') + '</th>' +
                    '<th style="padding:0.3rem 0.5rem;border-bottom:1px solid var(--border-default);">' + __('Governorate') + '</th>' +
                    '<th style="padding:0.3rem 0.5rem;border-bottom:1px solid var(--border-default);">' + __('Type') + '</th>' +
                    '<th style="padding:0.3rem 0.5rem;border-bottom:1px solid var(--border-default);">' + __('Value') + '</th>' +
                    '</tr></thead><tbody>' +
                    rows.map((p, i) => {
                        const click = p.hospital_id
                            ? ' onclick="goRootCause(' + p.hospital_id + ', \'' + mth + '\')" title="' + __('Open the root cause analysis for this hospital') + '"'
                            : '';
                        const style = 'padding:0.3rem 0.5rem;';
                        const valStyle = (i === 0)
                            ? style + 'font-weight:700;color:var(--accent-green);'
                            : style + 'font-size:0.74rem;';
                        return '<tr' + click + ' style="cursor:pointer;border-bottom:1px dashed #e5e7eb;">' +
                            '<td style="padding:0.3rem 0.5rem;font-weight:600;font-size:0.78rem;">' + esc(p.hospital) + '</td>' +
                            '<td style="padding:0.3rem 0.5rem;font-size:0.74rem;color:var(--text-secondary);">' + esc(p.governorate) + '</td>' +
                            '<td style="padding:0.3rem 0.5rem;font-size:0.74rem;color:var(--text-secondary);">' + esc(p.hospital_type) + '</td>' +
                            '<td style="' + valStyle + 'text-align:left;direction:ltr;">' + p.value + '</td>' +
                        '</tr>';
                    }).join('') +
                    '</tbody></table></div>';
            } else if (peersList.length) {
                const matchLabel = d.peer_match_by === 'type' ? __('Same hospital type')
                    : d.peer_match_by === 'governorate' ? __('Same governorate')
                    : d.peer_match_by === 'ownership' ? __('Same ownership') : __('All active hospitals');
                const basisHtml = matchLabel
                    ? '<div style="font-size:0.7rem;color:var(--text-secondary);margin-bottom:0.4rem;">' + __('Peer matching:') + ' <strong>' + esc(matchLabel) + '</strong> — ' + peersList.length + ' ' + __('hospital(s)') + '</div>'
                    : '';
                peerHospEl.innerHTML = basisHtml + '<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;">' +
                    '<thead><tr style="font-size:0.68rem;color:var(--text-muted);text-align:right;">' +
                    '<th style="padding:0.3rem 0.5rem;border-bottom:1px solid var(--border-default);">' + __('Hospital') + '</th>' +
                    '<th style="padding:0.3rem 0.5rem;border-bottom:1px solid var(--border-default);">' + __('Governorate') + '</th>' +
                    '<th style="padding:0.3rem 0.5rem;border-bottom:1px solid var(--border-default);">' + __('Type') + '</th>' +
                    '</tr></thead><tbody>' +
                    peersList.map(p =>
                        '<tr style="cursor:pointer;border-bottom:1px dashed #e5e7eb;" onclick="goRootCause(' + p.hospital_id + ', \'' + mth + '\')" title="' + __('Open the root cause analysis for this hospital') + '">' +
                            '<td style="padding:0.3rem 0.5rem;font-weight:600;font-size:0.78rem;">' + esc(p.name) + '</td>' +
                            '<td style="padding:0.3rem 0.5rem;font-size:0.74rem;color:var(--text-secondary);">' + esc(p.governorate) + '</td>' +
                            '<td style="padding:0.3rem 0.5rem;font-size:0.74rem;color:var(--text-secondary);">' + esc(p.hospital_type) + '</td>' +
                        '</tr>'
                    ).join('') +
                    '</tbody></table></div>';
            } else {
                peerHospEl.innerHTML = '<div style="padding:0.5rem;color:var(--text-muted);font-size:0.78rem;">' + __('No peer hospitals available for comparison.') + '</div>';
            }
        }

        function _renderRootCauseResult(d, hid, mth) {
            _rcReportData = { ...d, month: d.month || mth, _month: mth };
            // KPI Banner
            const qs = d.overall_quality_score || 0;
            const qsColor = qs >= 80 ? 'var(--accent-green)' : qs >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)';
            const conf = d.overall_confidence || 0;
            const confColor = conf >= 80 ? 'var(--accent-green)' : conf >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)';
            const ci = d.critical_issues_count || 0;
            const isAll = d._allMonths;
            const monthBadge = isAll ? '<span style="display:inline-block;font-size:0.65rem;background:var(--accent-blue);color:#fff;padding:1px 6px;border-radius:8px;margin-left:0.3rem;">' + d._monthCount + ' months</span>' : '';
            document.getElementById('rcKpiBar').innerHTML =
                '<div class="card" style="text-align:center;padding:0.8rem 0.5rem;border-top:4px solid ' + qsColor + ';">' +
                    '<div style="font-size:0.7rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">' + __('Data quality') + monthBadge + '</div>' +
                    '<div style="font-size:2rem;font-weight:700;color:' + qsColor + ';">' + qs + '</div>' +
                    '<div style="height:4px;background:var(--border-default);border-radius:2px;margin:0.3rem 1rem;overflow:hidden;">' +
                        '<div style="width:' + Math.min(qs, 100) + '%;height:100%;background:' + qsColor + ';border-radius:2px;"></div>' +
                    '</div>' +
                '</div>' +
                '<div class="card" style="text-align:center;padding:0.8rem 0.5rem;border-top:4px solid ' + confColor + ';">' +
                    '<div style="font-size:0.7rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">' + __('Confidence') + '</div>' +
                    '<div style="font-size:2rem;font-weight:700;color:' + confColor + ';">' + conf + '</div>' +
                    '<div style="height:4px;background:var(--border-default);border-radius:2px;margin:0.3rem 1rem;overflow:hidden;">' +
                        '<div style="width:' + Math.min(conf, 100) + '%;height:100%;background:' + confColor + ';border-radius:2px;"></div>' +
                    '</div>' +
                '</div>' +
                '<div class="card" style="text-align:center;padding:0.8rem 0.5rem;border-top:4px solid ' + (ci > 0 ? 'var(--accent-red)' : 'var(--accent-green)') + ';">' +
                    '<div style="font-size:0.7rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">' + __('Critical issues') + '</div>' +
                    '<div style="font-size:2rem;font-weight:700;color:' + (ci > 0 ? 'var(--accent-red)' : 'var(--accent-green)') + ';">' + ci + '</div>' +
                    '<div style="font-size:0.72rem;color:var(--text-muted);margin-top:0.2rem;">' + (ci > 0 ? __('Needs attention') : __('No critical issues')) + '</div>' +
                '</div>';
            // ── Month-by-Month Trend Chart (all-months view) ──
            let trendContainer = document.getElementById('rcTrendChart');
            if (isAll && d._monthQs && d._monthQs.length) {
                if (!trendContainer) {
                    trendContainer = document.createElement('div');
                    trendContainer.id = 'rcTrendChart';
                    trendContainer.className = 'card';
                    trendContainer.style.cssText = 'margin-bottom:0.8rem;padding:0.5rem;';
                    const kpi = document.getElementById('rcKpiBar');
                    if (kpi && kpi.nextSibling) kpi.parentNode.insertBefore(trendContainer, kpi.nextSibling);
                    else document.getElementById('rcContent').prepend(trendContainer);
                }
                trendContainer.style.display = 'block';
                trendContainer.innerHTML = '<div style="font-size:0.82rem;font-weight:600;color:var(--text-primary);margin-bottom:0.4rem;">📈 ' + _t('Monthly Quality & Confidence Trend') + '</div><div id="rcTrendPlot" style="width:100%;height:280px;"></div>';
                // Use setTimeout to ensure DOM is ready
                setTimeout(() => {
                    const plotEl = document.getElementById('rcTrendPlot');
                    if (!plotEl) return;
                    const months = d._months;
                    const qsValues = d._monthQs;
                    const confValues = d._monthConf;
                    const ciValues = d._monthCi;
                    // Per-point quality colors
                    const qsPointColors = qsValues.map(v => v >= 80 ? CHART_COLORS.success : v >= 50 ? CHART_COLORS.warning : CHART_COLORS.accent);
                    const barColors = ciValues.map(v => v > 0 ? 'rgba(239,68,68,0.35)' : 'rgba(74,222,128,0.2)');
                    // Destroy existing chart if any
                    if (window._rcTrendChartInstance) {
                        window._rcTrendChartInstance.destroy();
                        window._rcTrendChartInstance = null;
                    }
                    const chartCtx = plotEl.getContext('2d');
                    window._rcTrendChartInstance = new Chart(chartCtx, {
                        type: 'line',
                        data: {
                            labels: months,
                            datasets: [
                                {
                                    label: _t('Quality Score'),
                                    data: qsValues,
                                    borderColor: CHART_COLORS.primary,
                                    backgroundColor: CHART_COLORS.primary,
                                    _colorRole: 'primary',
                                    pointBackgroundColor: qsPointColors,
                                    pointBorderColor: 'rgba(255,255,255,0.3)',
                                    borderWidth: 2.5,
                                    pointRadius: 5,
                                    pointHoverRadius: 7,
                                    tension: 0.3,
                                    fill: false,
                                    yAxisID: 'y',
                                },
                                {
                                    label: _t('Confidence'),
                                    data: confValues,
                                    borderColor: CHART_COLORS.success,
                                    backgroundColor: CHART_COLORS.success,
                                    _colorRole: 'success',
                                    borderDash: [5, 5],
                                    borderWidth: 2,
                                    pointRadius: 3,
                                    pointHoverRadius: 5,
                                    tension: 0.3,
                                    fill: false,
                                    yAxisID: 'y',
                                },
                                {
                                    type: 'bar',
                                    label: _t('Critical Issues'),
                                    data: ciValues,
                                    backgroundColor: barColors,
                                    borderWidth: 1,
                                    borderColor: 'rgba(0,0,0,0)',
                                    yAxisID: 'y1',
                                }
                            ]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: {
                                    position: 'top',
                                    labels: {
                                        font: { size: 10 },
                                        color: CHART_COLORS.neutral,
                                        usePointStyle: true,
                                    }
                                },
                                tooltip: {
                                    backgroundColor: getCSSVar('--bg-elevated') || '#1e293b',
                                    titleFont: { size: 11 },
                                    bodyFont: { size: 11 },
                                    padding: 12,
                                    cornerRadius: 6,
                                }
                            },
                            scales: {
                                x: {
                                    grid: { color: CHART_COLORS.grid },
                                    ticks: { color: CHART_COLORS.neutral, font: { size: 10 }, maxRotation: -30 }
                                },
                                y: {
                                    position: 'left',
                                    min: 0,
                                    max: 105,
                                    grid: { color: CHART_COLORS.grid },
                                    ticks: { color: CHART_COLORS.neutral, font: { size: 10 } },
                                    title: { display: true, text: _t('Score (0-100)'), color: CHART_COLORS.neutral }
                                },
                                y1: {
                                    position: 'right',
                                    beginAtZero: true,
                                    grid: { drawOnChartArea: false },
                                    ticks: { color: CHART_COLORS.neutral, font: { size: 10 } },
                                    title: { display: true, text: _t('Issues'), color: CHART_COLORS.neutral }
                                }
                            },
                            interaction: {
                                intersect: false,
                                mode: 'index'
                            }
                        }
                    });
                    if (window.registerChart) window.registerChart(window._rcTrendChartInstance);
                }, 100);
            } else if (trendContainer) {
                if (window._rcTrendChartInstance) {
                    window._rcTrendChartInstance.destroy();
                    window._rcTrendChartInstance = null;
                }
                trendContainer.style.display = 'none';
            }
            // Summary
            const arSumEl = document.getElementById('rcSummaryArabic');
            const enSumEl = document.getElementById('rcSummary');
            const _rcIsAr0 = (typeof window.currentLang === 'undefined') ? true : (window.currentLang === 'ar');
            if (arSumEl) arSumEl.style.display = _rcIsAr0 ? '' : 'none';
            if (arSumEl) arSumEl.innerHTML = d.summary_arabic || '';
            if (enSumEl) {
                enSumEl.style.display = _rcIsAr0 ? 'none' : '';
                enSumEl.innerHTML = '<span style="color:var(--text-muted);">' + __('Summary') + ':</span> ' + (d.summary || 'No summary available.');
            }
            // Priority Actions
            const al = document.getElementById('rcActionsList');
            al.innerHTML = '';
            const detailByAction = {};
            (d.priority_action_details || []).forEach(p => { detailByAction[p.action] = p; });
            if (d.priority_actions && d.priority_actions.length) {
                d.priority_actions.forEach((a, i) => {
                    const isCritical = a.startsWith('[CRITICAL]');
                    const color = isCritical ? 'var(--accent-red)' : 'var(--accent-orange)';
                    const icon = isCritical ? '\u26a0' : '\u26a1';
                    const det = detailByAction[a] || {};
                    const impact = Math.max(0, Math.min(100, det.impact || 0));
                    const effort = Math.max(1, Math.min(5, det.effort || 3));
                    const roi = det.roi || 0;
                    let barHtml = '<div style="margin-top:0.2rem;font-size:0.62rem;color:var(--text-muted);">— ' + __('No quantitative estimate') + '</div>';
                    if (impact > 0) {
                        const roiCol = roi >= 15 ? 'var(--accent-green)' : roi >= 8 ? 'var(--accent-orange)' : '#888';
                        const impactCol = impact >= 60 ? 'var(--accent-red)' : impact >= 30 ? 'var(--accent-orange)' : 'var(--accent-green)';
                        const effortDots = '<span style="direction:ltr;unicode-bidi:isolate;letter-spacing:2px;color:var(--accent-yellow);font-size:0.7rem;" title="' + __('Effort (1-5)') + ': ' + effort + '">' +
                            '&#9679;'.repeat(effort) + '<span style="color:var(--text-muted);">' + '&#9679;'.repeat(5 - effort) + '</span></span>';
                        barHtml = '<div style="margin-top:0.3rem;">' +
                            '<div style="display:flex;justify-content:space-between;font-size:0.62rem;color:var(--text-muted);margin-bottom:1px;">' +
                                '<span>&#128200; ' + __('Impact') + ': ' + impact.toFixed(0) + ' ' + __('quality points') + '</span>' +
                                '<span style="color:' + roiCol + ';font-weight:700;">&#128176; ' + __('ROI') + ' ' + roi.toFixed(1) + '</span>' +
                                '<span>' + __('Effort') + ': ' + effortDots + '</span>' +
                            '</div>' +
                            '<div style="height:5px;background:var(--border-default);border-radius:3px;overflow:hidden;">' +
                                '<div style="width:' + impact + '%;height:100%;background:linear-gradient(90deg,' + impactCol + 'cc,' + impactCol + ');border-radius:3px;"></div>' +
                            '</div>' +
                        '</div>';
                    }
                    const div = document.createElement('div');
                    div.style.cssText = 'display:flex;align-items:flex-start;gap:0.5rem;padding:0.45rem 0.5rem;margin-bottom:0.4rem;background:' + color + '08;border-radius:4px;font-size:0.8rem;';
                    div.innerHTML = '<span style="color:' + color + ';font-weight:700;min-width:1.2rem;">' + (i + 1) + '.</span>' +
                        '<span style="flex:1;">' + (isCritical ? '<span style="color:' + color + ';font-weight:600;">' + icon + ' </span>' : '') + esc(a.replace('[CRITICAL] ','')) + barHtml +
                        '</span>';
                    al.appendChild(div);
                });
            } else {
                al.innerHTML = '<div style="padding:0.5rem;text-align:center;color:var(--text-muted);font-size:0.8rem;">No urgent actions needed.</div>';
            }
            // Rule Failures
            const rfEl = document.getElementById('rcRuleFailures');
            if (rfEl) {
                const rf = d.top_rule_failures || [];
                if (rf.length) {
                    rfEl.innerHTML = rf.map(r => {
                        const sev = (r.severity || 'medium').toUpperCase();
                        const sevColor = sev === 'CRITICAL' ? 'var(--accent-red)' : sev === 'HIGH' ? 'var(--accent-orange)' : 'var(--accent-yellow)';
                        const countBadge = r.count > 1 ? ' <span style="font-size:0.6rem;background:var(--accent-blue);color:#fff;padding:0 4px;border-radius:6px;">×' + r.count + '</span>' : '';
                        const rfMonths = (r.months && r.months.length > 0 && isAll) ? ' <span style="font-size:0.55rem;background:var(--accent-teal);color:#fff;padding:0 4px;border-radius:6px;margin-left:2px;">' + r.months.join(', ') + '</span>' : '';
                        return '<div style="display:flex;align-items:center;gap:0.5rem;padding:0.3rem 0;border-bottom:1px solid var(--border-default);font-size:0.8rem;">' +
                            '<span style="width:8px;height:8px;border-radius:50%;background:' + sevColor + ';flex-shrink:0;"></span>' +
                            '<span style="font-weight:600;">' + esc(r.rule || r.rule_code || '') + '</span>' +
                            '<span style="color:var(--text-muted);font-size:0.72rem;">' + esc(sev) + '</span>' +
                            countBadge + rfMonths +
                            '<span style="margin-left:auto;font-size:0.72rem;">' + (r.failure_rate || 0).toFixed(1) + '%</span>' +
                        '</div>';
                    }).join('');
                } else {
                    rfEl.innerHTML = '<div style="padding:0.5rem;color:var(--text-muted);font-size:0.78rem;">No rule failures.</div>';
                }
            }
            // Confidence Gaps
            const cgEl = document.getElementById('rcConfidenceGaps');
            if (cgEl) {
                const cg = d.confidence_gaps || [];
                if (cg.length) {
                    cgEl.innerHTML = cg.map(g => {
                        const lvl = (g.level || '').toUpperCase();
                        const lvlColor = lvl === 'CRITICAL' ? 'var(--accent-red)' : lvl === 'LOW' ? 'var(--accent-orange)' : 'var(--accent-yellow)';
                        const cgMonthBadge = (g._months && g._months.length > 0 && isAll) ? ' <span style="font-size:0.55rem;background:var(--accent-teal);color:#fff;padding:0 4px;border-radius:6px;">' + g._months.join(', ') + '</span>' : '';
                        return '<div style="display:flex;align-items:center;gap:0.5rem;padding:0.3rem 0;border-bottom:1px solid var(--border-default);font-size:0.8rem;">' +
                            '<span style="width:8px;height:8px;border-radius:50%;background:' + lvlColor + ';flex-shrink:0;"></span>' +
                            '<span style="font-weight:600;">' + esc(g.indicator_name || g.indicator || '') + '</span>' +
                            '<span style="color:var(--text-muted);font-size:0.72rem;">' + esc(lvl) + cgMonthBadge + '</span>' +
                            '<span style="margin-left:auto;font-size:0.72rem;color:' + lvlColor + ';">' + (g.score != null ? g.score.toFixed(1) : '') + '</span>' +
                        '</div>' +
                            '<div style="font-size:0.7rem;color:var(--text-secondary);margin:0.1rem 0 0.2rem 1.2rem;">Signal: ' + (g.weakest_signal || '') + ' | ' + esc((g.root_cause || '').slice(0, 90)) + '</div>';
                    }).join('');
                } else {
                    cgEl.innerHTML = '<div style="padding:0.5rem;text-align:center;color:var(--text-muted);font-size:0.78rem;">No confidence gaps found.</div>';
                }
            }
            // Causal Chains
            const chainsEl = document.getElementById('rcCausalChains');
            if (chainsEl) {
                chainsEl.innerHTML = '';
                const chains = d.causal_chains || [];
                if (chains.length) {
                    chainsEl.innerHTML = chains.slice(0, 8).map(c => {
                        const pct = Math.round((c.confidence || 0) * 100);
                        const confColor = c.confidence >= 0.7 ? 'var(--accent-teal)' : c.confidence >= 0.5 ? 'var(--accent-orange)' : 'var(--accent-red)';
                        const prio = (c.implementation_priority || '').toUpperCase();
                        const prioColor = prio === 'CRITICAL' ? 'var(--accent-red)' : prio === 'HIGH' ? 'var(--accent-orange)' : 'var(--accent-yellow)';
                        const chainMonthBadge = (c._months && c._months.length > 0 && isAll) ? '<span style="font-size:0.55rem;background:var(--accent-teal);color:#fff;padding:1px 6px;border-radius:8px;margin-left:0.3rem;white-space:nowrap;">' + c._months.join(', ') + '</span>' : '';
                        return '<div style="padding:0.6rem;border:1px solid var(--accent-teal);border-radius:8px;margin-bottom:0.5rem;background:var(--bg-elevated);">' +
                            '<div style="display:flex;justify-content:space-between;align-items:center;gap:0.5rem;">' +
                                '<span style="font-weight:700;font-size:0.82rem;color:var(--accent-teal);">' + esc(c.root_cause_arabic || c.root_cause) + chainMonthBadge + '</span>' +
                                '<span style="font-size:0.65rem;background:' + prioColor + ';padding:1px 8px;border-radius:10px;white-space:nowrap;font-weight:600;">' + esc(prio) + '</span>' +
                            '</div>' +
                            (c.chain_path && c.chain_path.length > 1
                                ? '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:0.2rem;margin:0.35rem 0;direction:ltr;" title="' + __('Full cause-and-effect chain (deepest ← latest)') + '">' +
                                    c.chain_path.map((code, ci) => {
                                        const isRoot = ci === c.chain_path.length - 1;
                                        return '<span style="font-size:0.66rem;padding:1px 8px;border-radius:10px;font-weight:600;white-space:nowrap;' +
                                            (isRoot ? 'background:var(--accent-teal);color:#fff;' : 'background:var(--severity-info-bg);color:var(--accent-teal);border:1px solid var(--accent-teal);') + '">' +
                                            esc(code) + '</span>' +
                                            (ci < c.chain_path.length - 1 ? '<span style="color:var(--accent-teal);font-size:0.7rem;">&#8592;</span>' : '');
                                    }).join('') +
                                '</div>' : '') +
                            (c.chain_path_arabic ? '<div style="font-size:0.68rem;color:#0f766e;margin-bottom:0.3rem;">' + esc(c.chain_path_arabic) + '</div>' : '') +
                            '<div style="margin:0.4rem 0;height:5px;background:var(--border-default);border-radius:3px;overflow:hidden;">' +
                                '<div style="width:' + pct + '%;height:100%;background:' + confColor + ';border-radius:3px;"></div>' +
                            '</div>' +
                            '<div style="display:flex;gap:0.8rem;font-size:0.7rem;color:var(--text-secondary);margin-bottom:0.3rem;">' +                                    '<span title="' + __('Confidence in the root cause') + '">' + __('Confidence') + ' <strong>' + pct + '%</strong></span>' +
                                    '<span title="' + __('Expected impact when fixed') + '">' + __('Impact') + ' <strong>' + (c.impact_if_fixed || 0) + '</strong></span>' +
                            '</div>' +
                            (c.affected_factors && c.affected_factors.length
                                ? '<div style="font-size:0.7rem;color:var(--text-secondary);margin-bottom:0.3rem;"><strong>' + __('Affected factors') + ':</strong> ' + c.affected_factors.map(esc).join(' ← ') + '</div>' : '') +
                            (c.recommended_action ? '<div style="font-size:0.72rem;color:#0f766e;margin-top:0.2rem;">&#128161; ' + esc(c.recommended_action) + '</div>' : '') +
                            (c.evidence && c.evidence.length ? '<div style="font-size:0.68rem;color:var(--text-muted);margin-top:0.2rem;">' + c.evidence.slice(0, 3).map(esc).join(' | ') + '</div>' : '') +
                        '</div>';
                    }).join('');
                } else {
                    chainsEl.innerHTML = '<div style="padding:0.5rem;color:var(--text-muted);font-size:0.78rem;">' + __('No causal chains — enable historical analysis or no critical rule failures.') + '</div>';
                }
            }
            // Causal Tree
            const treeEl = document.getElementById('rcCausalTree');
            if (treeEl) {
                treeEl.innerHTML = '';
                if (d.causal_tree && d.causal_tree.length) {
                    treeEl.innerHTML = d.causal_tree.slice(0, 12).map(n => {
                        const sevColor = n.severity === 'CRITICAL' ? 'var(--accent-red)' : n.severity === 'HIGH' ? 'var(--accent-orange)' : n.severity === 'critical' ? 'var(--accent-red)' : n.severity === 'high' ? 'var(--accent-orange)' : 'var(--accent-teal)';
                        const trendArrow = n.trend === 'declining' ? '&#9660;' : n.trend === 'improving' ? '&#9650;' : '&#8212;';
                        const treeMonthBadge = (n._months && n._months.length > 0 && isAll) ? ' <span style="font-size:0.55rem;background:var(--accent-teal);color:#fff;padding:0 4px;border-radius:6px;">' + n._months.join(', ') + '</span>' : '';
                        return '<div style="display:flex;align-items:center;gap:0.5rem;padding:0.35rem 0;border-bottom:1px dashed #e5e7eb;">' +
                            '<span style="width:9px;height:9px;border-radius:50%;background:' + sevColor + ';flex-shrink:0;"></span>' +
                            '<span style="font-weight:600;font-size:0.78rem;">' + esc(n.factor) + treeMonthBadge + '</span>' +
                            '<span style="font-size:0.7rem;color:var(--text-secondary);">' + (n.current_value != null ? n.current_value : '') + '</span>' +
                            '<span style="margin-right:auto;font-size:0.65rem;color:var(--text-muted);">' + esc(n.factor_type || '') + '</span>' +
                        '</div>';
                    }).join('');
                } else {
                    treeEl.innerHTML = '<div style="padding:0.5rem;color:var(--text-muted);font-size:0.78rem;">' + __('No causal tree data.') + '</div>';
                }
            }
            // Peer Comparisons
            const peerEl = document.getElementById('rcPeerComparisons');
            if (peerEl) {
                peerEl.innerHTML = '';
                const comps = d.peer_comparisons || {};
                const entries = Object.values(comps);
                if (entries.length) {
                    peerEl.innerHTML = entries.slice(0, 10).map(c => {
                        const gap = c.gap_pct || 0;
                        const over = gap > 0;
                        const color = Math.abs(gap) > 20 ? (over ? 'var(--accent-red)' : 'var(--accent-blue)') : 'var(--text-muted)';
                        return '<div style="padding:0.35rem 0;border-bottom:1px dashed #e5e7eb;">' +
                            '<div style="display:flex;justify-content:space-between;align-items:center;">' +
                                '<span style="font-weight:600;font-size:0.78rem;">' + esc(c.indicator_name || c.indicator_code) + '</span>' +
                                '<span style="font-size:0.7rem;color:' + color + ';font-weight:700;">' + (over ? '▲ +' : '▼ ') + Math.abs(gap).toFixed(1) + '%</span>' +
                            '</div>' +
                            '<div style="font-size:0.68rem;color:var(--text-muted);">' + __('Hospital') + ' ' + c.hospital_value + ' ' + __('vs peer average') + ' ' + c.peer_mean + ' (' + c.peer_count + ' ' + __('hospitals') + ')</div>' +
                        '</div>';
                    }).join('');
                } else {
                    peerEl.innerHTML = '<div style="padding:0.5rem;color:var(--text-muted);font-size:0.78rem;">' + __('No peer comparisons.') + '</div>';
                }
            }
            // Timeline (skip for all-months mode)
            if (!isAll && mth !== 'all') {
                apiGet('/root-cause/' + hid + '/timeline?month=' + mth + '&months_back=6' + _rcPeerQ()).then(tl => {
                    _rcTimelineData = tl || { indicators: [] };
                    renderRcTimeline();
                }).catch(() => {
                    _rcTimelineData = { indicators: [] };
                    renderRcTimeline();
                });
                apiGet('/analysis/ml?month=' + mth).then(mlData => {
                    if (mlData && mlData.ml_pca) {
                        const pca = mlData.ml_pca;
                        const features = pca.top_features || {};
                        const entries = Object.entries(features).sort((a, b) => b[1] - a[1]);
                        let html = '<div style="margin-top:0.3rem;">';
                        const cumVar = pca.cumulative_variance ?? 0;
                        html += '<div style="font-size:0.72rem;color:var(--text-secondary);margin-bottom:0.3rem;">Cumulative variance explained: ' + (cumVar * 100).toFixed(0) + '%</div>';
                        if (!entries.length) {
                            html += '<div style="font-size:0.72rem;color:var(--text-muted);">No PCA data available.</div>';
                        } else {
                            const maxVal = Math.max(...entries.map(e => e[1]), 0.01);
                            entries.forEach(([name, variance]) => {
                                const pct = (variance / maxVal * 100).toFixed(0);
                                html += '<div style="display:flex;align-items:center;gap:0.3rem;margin:0.15rem 0;">';
                                html += '<span style="width:120px;font-size:0.72rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + esc(name) + '">' + esc(name) + '</span>';
                                html += '<div style="flex:1;height:14px;background:var(--border-default);border-radius:3px;"><div style="height:100%;width:' + pct + '%;background:var(--accent-blue);border-radius:3px;"></div></div>';
                                html += '<span style="width:40px;text-align:right;font-size:0.7rem;color:var(--text-secondary);">' + (variance * 100).toFixed(0) + '%</span>';
                                html += '</div>';
                            });
                        }
                        html += '</div>';
                        document.getElementById('pcaFeatures').innerHTML = html;
                    }
                }).catch(() => {});
            }
        }

        export function loadRootCause() {
            _saveUIState('root-cause');
            const hid = document.getElementById('rcHospital').value;
            const mth = document.getElementById('rcMonth').value;
            if (!hid || !mth) return;
            document.getElementById('rcLoading').style.display = 'block';
            document.getElementById('rcContent').style.display = 'none';
            if (mth === 'all') {
                _loadRootCauseAllMonths(hid);
                return;
            }
            apiGet('/root-cause/' + hid + '?month=' + mth + '&include_history=true&compare_peers=true&months_back=6' + _rcPeerQ()).then(d => {
                document.getElementById('rcLoading').style.display = 'none';
                document.getElementById('rcContent').style.display = 'block';
                _renderRootCauseResult(d, hid, mth);

                // ── Summary: narrative matches the app language (both available from the engine) ──
                const arSumEl = document.getElementById('rcSummaryArabic');
                const enSumEl = document.getElementById('rcSummary');
                const _rcIsAr = (typeof window.currentLang === 'undefined') ? true : (window.currentLang === 'ar');
                if (arSumEl) arSumEl.style.display = _rcIsAr ? '' : 'none';
                if (arSumEl) arSumEl.textContent = d.summary_arabic || '';
                if (enSumEl) {
                    enSumEl.style.display = _rcIsAr ? 'none' : '';
                    enSumEl.innerHTML = '<span style="color:var(--text-muted);">' + __('Summary') + ':</span> ' + (d.summary || 'No summary available.');
                }

                // ── Priority Actions (with quantified impact/effort/ROI) ──
                const al = document.getElementById('rcActionsList');
                al.innerHTML = '';
                const detailByAction = {};
                (d.priority_action_details || []).forEach(p => { detailByAction[p.action] = p; });
                if (d.priority_actions && d.priority_actions.length) {
                    d.priority_actions.forEach((a, i) => {
                        const isCritical = a.startsWith('[CRITICAL]');
                        const color = isCritical ? 'var(--accent-red)' : 'var(--accent-orange)';
                        const icon = isCritical ? '\u26a0' : '\u26a1';
                        const det = detailByAction[a] || {};
                        const impact = Math.max(0, Math.min(100, det.impact || 0));
                        const effort = Math.max(1, Math.min(5, det.effort || 3));
                        const roi = det.roi || 0;
                        let barHtml = '<div style="margin-top:0.2rem;font-size:0.62rem;color:var(--text-muted);">— ' + __('No quantitative estimate') + '</div>';
                        if (impact > 0) {
                            const roiCol = roi >= 15 ? 'var(--accent-green)' : roi >= 8 ? 'var(--accent-orange)' : '#888';
                            const impactCol = impact >= 60 ? 'var(--accent-red)' : impact >= 30 ? 'var(--accent-orange)' : 'var(--accent-green)';
                            const effortDots = '<span style="direction:ltr;unicode-bidi:isolate;letter-spacing:2px;color:var(--accent-yellow);font-size:0.7rem;" title="' + __('Effort (1-5)') + ': ' + effort + '">' +
                                '&#9679;'.repeat(effort) + '<span style="color:var(--text-muted);">' + '&#9679;'.repeat(5 - effort) + '</span></span>';
                            barHtml = '<div style="margin-top:0.3rem;">' +
                                '<div style="display:flex;justify-content:space-between;font-size:0.62rem;color:var(--text-muted);margin-bottom:1px;">' +
                                    '<span>&#128200; ' + __('Impact') + ': ' + impact.toFixed(0) + ' ' + __('quality points') + '</span>' +
                                    '<span style="color:' + roiCol + ';font-weight:700;">&#128176; ' + __('ROI') + ' ' + roi.toFixed(1) + '</span>' +
                                    '<span>' + __('Effort') + ': ' + effortDots + '</span>' +
                                '</div>' +
                                '<div style="height:5px;background:var(--border-default);border-radius:3px;overflow:hidden;">' +
                                    '<div style="width:' + impact + '%;height:100%;background:linear-gradient(90deg,' + impactCol + 'cc,' + impactCol + ');border-radius:3px;"></div>' +
                                '</div>' +
                            '</div>';
                        }
                        const div = document.createElement('div');
                        div.style.cssText = 'display:flex;align-items:flex-start;gap:0.5rem;padding:0.45rem 0.5rem;margin-bottom:0.4rem;background:' + color + '08;border-radius:4px;font-size:0.8rem;';
                        div.innerHTML = '<span style="color:' + color + ';font-weight:700;min-width:1.2rem;">' + (i + 1) + '.</span>' +
                            '<span style="flex:1;">' + (isCritical ? '<span style="color:' + color + ';font-weight:600;">' + icon + ' </span>' : '') + esc(a.replace('[CRITICAL] ','')) + barHtml +
                            '</span>';
                        al.appendChild(div);
                    });
                } else {
                    al.innerHTML = '<div style="padding:0.5rem;text-align:center;color:var(--text-muted);font-size:0.8rem;">No urgent actions needed.</div>';
                }

                // ── AI Recommendations (ثنائية اللغة حسب لغة التطبيق) ──
                const aiList = document.getElementById('rcAIList');
                aiList.innerHTML = '';
                const isAr = (typeof window.currentLang === 'undefined') ? true : (window.currentLang === 'ar');
                const prioKey = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low' };
                const aiPrioLabel = p => __(prioKey[p] || p);
                if (d.ai_recommendations && d.ai_recommendations.length) {
                    const priorityColors = {critical:'var(--accent-red)',high:'var(--accent-orange)',medium:'var(--accent-yellow)',low:'var(--accent-green)'};
                    d.ai_recommendations.forEach(r => {
                        const pCol = priorityColors[r.priority] || '#888';
                        const title = isAr ? (r.title_ar || r.title) : (r.title || r.title_ar);
                        const desc = isAr ? (r.description_ar || r.description) : (r.description || r.description_ar);
                        const rat = isAr ? (r.rationale_ar || r.rationale) : (r.rationale || r.rationale_ar);
                        const items = isAr
                            ? (r.action_items_ar && r.action_items_ar.length ? r.action_items_ar : r.action_items)
                            : (r.action_items && r.action_items.length ? r.action_items : r.action_items_ar);
                        const catLabel = isAr ? (r.category_ar || r.category) : r.category;
                        const card = document.createElement('div');
                        card.style.cssText = 'padding:0.5rem 0.6rem;border-radius:4px;margin-bottom:0.4rem;border-left:3px solid ' + pCol + ';font-size:0.8rem;';
                        card.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;gap:0.3rem;">' +
                            '<div style="display:flex;align-items:center;gap:0.3rem;flex-wrap:wrap;"><span class="rec-source rec-source-ai" title="AI-generated">&#9889;</span>' +
                            (catLabel ? '<span style="font-size:0.58rem;background:var(--bg-elevated);color:var(--accent-purple);padding:0 6px;border-radius:8px;white-space:nowrap;">' + esc(catLabel) + '</span>' : '') +
                            '<span style="font-weight:600;color:var(--text-primary);">' + esc(title) + '</span></div>' +
                            '<span style="font-size:0.6rem;background:' + pCol + ';color:#fff;padding:0 6px;border-radius:8px;white-space:nowrap;">' + esc(aiPrioLabel(r.priority)) + '</span></div>' +
                            (desc ? '<div style="font-size:0.75rem;color:var(--text-secondary);margin-top:0.2rem;">' + esc(desc) + '</div>' : '') +
                            (rat ? '<div style="font-size:0.7rem;color:var(--text-muted);font-style:italic;margin-top:0.15rem;">' + esc(rat) + '</div>' : '') +
                            (items && items.length ? '<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:0.15rem;"><strong>' + __('Actions') + ':</strong> ' + items.map(esc).join('; ') + '</div>' : '');
                        aiList.appendChild(card);
                    });
                } else {
                    aiList.innerHTML = '<div style="padding:0.6rem;text-align:center;background:var(--bg-elevated);border-radius:4px;font-size:0.8rem;color:var(--text-muted);">' +
                        __('No AI recommendations available.') + '<br><a href="javascript:void(0)" onclick="SwitchTab(\'settings\')" style="color:#3f51b5;">' +
                        __('Configure AI provider') + '</a></div>';
                }

                // ── Rule Failures ──
                const rf = document.getElementById('rcRuleFailures');
                rf.innerHTML = '';
                if (d.top_rule_failures && d.top_rule_failures.length) {
                    rf.innerHTML = d.top_rule_failures.map(f => {
                        const sev = f.severity === 'CRITICAL' ? 'var(--accent-red)' : f.severity === 'HIGH' ? 'var(--accent-orange)' : 'var(--accent-yellow)';
                        return '<div style="padding:0.35rem 0;border-bottom:1px solid #f0f0f0;">' +
                            '<div style="display:flex;align-items:center;gap:0.4rem;">' +
                                '<span style="width:8px;height:8px;border-radius:50%;background:' + sev + ';flex-shrink:0;"></span>' +
                                '<span style="font-weight:600;font-size:0.78rem;">' + esc(f.rule_code) + '</span>' +
                                '<span style="font-size:0.68rem;color:var(--text-muted);">' + f.failure_rate + '%</span>' +
                            '</div>' +
                            '<div style="font-size:0.72rem;color:var(--text-secondary);margin:0.1rem 0 0 1.2rem;">' + esc((f.description || f.primary_cause || '').slice(0, 90)) + '</div>' +
                            '</div>';
                    }).join('');
                } else { rf.innerHTML = '<div style="padding:0.5rem;text-align:center;color:var(--text-muted);font-size:0.78rem;">No rule failures found.</div>'; }

                // ── Quality Drivers ──
                const qd = document.getElementById('rcQualityDrivers');
                qd.innerHTML = '';
                if (d.quality_drivers && d.quality_drivers.length) {
                    qd.innerHTML = d.quality_drivers.map(q => {
                        const statusColor = q.status === 'good' ? 'var(--accent-green)' : q.status === 'needs_improvement' ? 'var(--accent-orange)' : 'var(--accent-red)';
                        const barColor = q.status === 'good' ? 'var(--accent-green)' : q.status === 'needs_improvement' ? 'var(--accent-yellow)' : 'var(--accent-red)';
                        return '<div style="margin-bottom:0.5rem;">' +
                            '<div style="display:flex;justify-content:space-between;font-size:0.78rem;margin-bottom:0.15rem;">' +
                                '<span style="font-weight:600;">' + q.component + '</span>' +
                                '<span style="color:' + statusColor + ';font-weight:600;">' + q.value + '%</span>' +
                            '</div>' +
                            '<div style="height:6px;background:var(--bg-elevated);border-radius:3px;overflow:hidden;">' +
                                '<div style="width:' + Math.min(q.value, 100) + '%;height:100%;background:' + barColor + ';border-radius:3px;transition:width 0.3s;"></div>' +
                            '</div>' +
                            '<div style="font-size:0.68rem;color:var(--text-muted);margin-top:0.1rem;">Impact gap: ' + q.impact + ' pts &mdash; ' + (q.recommendation || '').slice(0, 60) + '</div>' +
                            '</div>';
                    }).join('');
                } else { qd.innerHTML = '<div style="padding:0.5rem;text-align:center;color:var(--text-muted);font-size:0.78rem;">No data available.</div>'; }

                // ── Confidence Gaps ──
                const cg = document.getElementById('rcConfidenceGaps');
                cg.innerHTML = '';
                if (d.confidence_gaps && d.confidence_gaps.length) {
                    cg.innerHTML = d.confidence_gaps.map(g => {
                        const levelColor = g.level === 'CRITICAL' ? 'var(--accent-red)' : g.level === 'LOW' ? 'var(--accent-orange)' : 'var(--accent-yellow)';
                        return '<div style="padding:0.35rem 0;border-bottom:1px solid #f0f0f0;">' +
                            '<div style="display:flex;align-items:center;gap:0.4rem;">' +
                                '<span style="font-size:0.65rem;background:' + levelColor + ';color:#fff;padding:0 5px;border-radius:3px;font-weight:600;">' + g.level + '</span>' +
                                '<span style="font-weight:600;font-size:0.78rem;">' + esc((g.indicator_name || '').slice(0, 35)) + '</span>' +
                                '<span style="font-size:0.68rem;color:var(--text-muted);">' + g.confidence + '</span>' +
                            '</div>' +
                            '<div style="font-size:0.7rem;color:var(--text-secondary);margin:0.1rem 0 0 0;">Signal: ' + (g.weakest_signal || '') + ' | ' + esc((g.root_cause || '').slice(0, 90)) + '</div>' +
                            '</div>';
                    }).join('');
                } else { cg.innerHTML = '<div style="padding:0.5rem;text-align:center;color:var(--text-muted);font-size:0.78rem;">No confidence gaps found.</div>'; }

                // ── Anomaly Patterns ──
                const ap = document.getElementById('rcAnomalyPatterns');
                ap.innerHTML = '';
                if (d.anomaly_patterns && d.anomaly_patterns.length) {
                    ap.innerHTML = d.anomaly_patterns.map(a => {
                        const typeColor = a.pattern_type === 'severe' ? 'var(--accent-red)' : a.pattern_type === 'moderate' ? 'var(--accent-orange)' : 'var(--accent-yellow)';
                        const typeLabel = a.pattern_type === 'severe' ? 'Severe' : a.pattern_type === 'moderate' ? 'Moderate' : 'Mild';
                        return '<div style="padding:0.35rem 0;border-bottom:1px solid #f0f0f0;">' +
                            '<div style="display:flex;align-items:center;gap:0.4rem;">' +
                                '<span style="font-size:0.65rem;background:' + typeColor + ';color:#fff;padding:0 5px;border-radius:3px;font-weight:600;">' + typeLabel + '</span>' +
                                '<span style="font-weight:600;font-size:0.78rem;">' + esc((a.rate_name || '').slice(0, 35)) + '</span>' +
                            '</div>' +
                            '<div style="font-size:0.7rem;color:var(--text-secondary);margin:0.1rem 0 0 0;">|z| = ' + a.avg_z_score + (a.recurrence_count ? ' | Recurring ' + a.recurrence_count + 'x' : '') + '</div>' +
                            '</div>';
                    }).join('');
                } else { ap.innerHTML = '<div style="padding:0.5rem;text-align:center;color:var(--text-muted);font-size:0.78rem;">No anomaly patterns found.</div>'; }


                // ── Causal Chains ──
                const chainsEl = document.getElementById('rcCausalChains');
                if (chainsEl) {
                    chainsEl.innerHTML = '';
                    if (d.causal_chains && d.causal_chains.length) {
                        chainsEl.innerHTML = d.causal_chains.slice(0, 5).map(c => {
                            const pct = Math.round((c.confidence || 0) * 100);
                            const confColor = c.confidence >= 0.7 ? 'var(--accent-teal)' : c.confidence >= 0.5 ? 'var(--accent-orange)' : 'var(--accent-red)';
                            const prio = (c.implementation_priority || '').toUpperCase();
                            const prioColor = prio === 'CRITICAL' ? 'var(--accent-red)' : prio === 'HIGH' ? 'var(--accent-orange)' : 'var(--accent-yellow)';
                            return '<div style="padding:0.6rem;border:1px solid var(--accent-teal);border-radius:8px;margin-bottom:0.5rem;background:var(--bg-elevated);">' +
                                '<div style="display:flex;justify-content:space-between;align-items:center;gap:0.5rem;">' +
                                    '<span style="font-weight:700;font-size:0.82rem;color:var(--accent-teal);">' + esc(c.root_cause_arabic || c.root_cause) + '</span>' +
                                    '<span style="font-size:0.65rem;background:' + prioColor + ';padding:1px 8px;border-radius:10px;white-space:nowrap;font-weight:600;">' + esc(prio) + '</span>' +
                                '</div>' +
                                (c.chain_path && c.chain_path.length > 1
                                    ? '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:0.2rem;margin:0.35rem 0;direction:ltr;" title="' + __('Full cause-and-effect chain (deepest ← latest)') + '">' +
                                        c.chain_path.map((code, ci) => {
                                            const isRoot = ci === c.chain_path.length - 1;
                                            return '<span style="font-size:0.66rem;padding:1px 8px;border-radius:10px;font-weight:600;white-space:nowrap;' +
                                                (isRoot ? 'background:var(--accent-teal);color:#fff;' : 'background:var(--severity-info-bg);color:var(--accent-teal);border:1px solid var(--accent-teal);') + '">' +
                                                esc(code) + '</span>' +
                                                (ci < c.chain_path.length - 1 ? '<span style="color:var(--accent-teal);font-size:0.7rem;">&#8592;</span>' : '');
                                        }).join('') +
                                    '</div>' : '') +
                                (c.chain_path_arabic ? '<div style="font-size:0.68rem;color:#0f766e;margin-bottom:0.3rem;">' + esc(c.chain_path_arabic) + '</div>' : '') +
                                '<div style="margin:0.4rem 0;height:5px;background:var(--border-default);border-radius:3px;overflow:hidden;">' +
                                    '<div style="width:' + pct + '%;height:100%;background:' + confColor + ';border-radius:3px;"></div>' +
                                '</div>' +
                                '<div style="display:flex;gap:0.8rem;font-size:0.7rem;color:var(--text-secondary);margin-bottom:0.3rem;">' +
                                    '<span title="' + __('Confidence in the root cause') + '">' + __('Confidence') + ' <strong>' + pct + '%</strong></span>' +
                                    '<span title="' + __('Expected impact when fixed') + '">' + __('Impact') + ' <strong>' + (c.impact_if_fixed || 0) + '</strong></span>' +
                                '</div>' +
                                (c.affected_factors && c.affected_factors.length
                                    ? '<div style="font-size:0.7rem;color:var(--text-secondary);margin-bottom:0.3rem;"><strong>' + __('Affected factors') + ':</strong> ' + c.affected_factors.map(esc).join(' ← ') + '</div>' : '') +
                                (c.recommended_action ? '<div style="font-size:0.72rem;color:#0f766e;margin-top:0.2rem;">&#128161; ' + esc(c.recommended_action) + '</div>' : '') +
                                (c.evidence && c.evidence.length ? '<div style="font-size:0.68rem;color:var(--text-muted);margin-top:0.2rem;">' + c.evidence.slice(0, 3).map(esc).join(' | ') + '</div>' : '') +
                            '</div>';
                        }).join('');
                    } else {
                        chainsEl.innerHTML = '<div style="padding:0.5rem;color:var(--text-muted);font-size:0.78rem;">' + __('No causal chains — enable historical analysis or no critical rule failures.') + '</div>';
                    }
                }

                // ── Causal Tree ──
                const treeEl = document.getElementById('rcCausalTree');
                if (treeEl) {
                    treeEl.innerHTML = '';
                    if (d.causal_tree && d.causal_tree.length) {
                        treeEl.innerHTML = d.causal_tree.slice(0, 12).map(n => {
                            const sevColor = n.severity === 'CRITICAL' ? 'var(--accent-red)' : n.severity === 'HIGH' ? 'var(--accent-orange)' : n.severity === 'critical' ? 'var(--accent-red)' : n.severity === 'high' ? 'var(--accent-orange)' : 'var(--accent-teal)';
                            const trendArrow = n.trend === 'declining' ? '&#9660;' : n.trend === 'improving' ? '&#9650;' : '&#8212;';
                            return '<div style="display:flex;align-items:center;gap:0.5rem;padding:0.35rem 0;border-bottom:1px dashed #e5e7eb;">' +
                                '<span style="width:9px;height:9px;border-radius:50%;background:' + sevColor + ';flex-shrink:0;"></span>' +
                                '<span style="font-weight:600;font-size:0.78rem;">' + esc(n.factor) + '</span>' +
                                '<span style="font-size:0.7rem;color:var(--text-secondary);">' + (n.current_value != null ? n.current_value : '') + '</span>' +
                                (n.history && n.history.length > 1
                                    ? '<span title="' + __('Trend across months') + ': ' + esc(n.history.map(h => h.month + ' = ' + h.value).join(', ')) + '">' + _rcSparkline(n.history) + '</span>'
                                    : '<span style="font-size:0.7rem;color:var(--text-muted);" title="' + __('Trend across months') + '">' + trendArrow + ' ' + esc(n.trend || '') + '</span>') +
                                '<span style="margin-right:auto;font-size:0.65rem;color:var(--text-muted);">' + esc(n.factor_type || '') + '</span>' +
                            '</div>';
                        }).join('');
                    } else {
                        treeEl.innerHTML = '<div style="padding:0.5rem;color:var(--text-muted);font-size:0.78rem;">' + __('No causal tree data.') + '</div>';
                    }
                }

                // ── Peer Comparisons (per indicator) ──
                const peerEl = document.getElementById('rcPeerComparisons');
                if (peerEl) {
                    peerEl.innerHTML = '';
                    const comps = d.peer_comparisons || {};
                    const entries = Object.values(comps);
                    if (entries.length) {
                        peerEl.innerHTML = entries.slice(0, 10).map(c => {
                            const gap = c.gap_pct || 0;
                            const over = gap > 0;
                            const color = Math.abs(gap) > 20 ? (over ? 'var(--accent-red)' : 'var(--accent-blue)') : 'var(--text-muted)';
                            const govs = (c.peer_governorate_counts || {});
                            const govParts = Object.entries(govs).sort((a, b) => b[1] - a[1])
                                .map(g => g[0] + ' (' + g[1] + ')').join(', ');
                            const types = (c.peer_types || []).join(', ');
                            return '<div style="padding:0.35rem 0;border-bottom:1px dashed #e5e7eb;">' +
                                '<div style="display:flex;justify-content:space-between;align-items:center;">' +
                                    '<span style="font-weight:600;font-size:0.78rem;">' + esc(c.indicator_name || c.indicator_code) + '</span>' +
                                    '<span style="font-size:0.7rem;color:' + color + ';font-weight:700;">' + (over ? '▲ +' : '▼ ') + Math.abs(gap).toFixed(1) + '%</span>' +
                                '</div>' +
                                '<div style="font-size:0.68rem;color:var(--text-muted);">' + __('Hospital') + ' ' + c.hospital_value + ' ' + __('vs peer average') + ' ' + c.peer_mean + ' (' + c.peer_count + ' ' + __('hospitals') + ') — ' + __('percentile') + ' ' + c.hospital_percentile + ' | z=' + c.hospital_z_score + '</div>' +
                                (govParts || types ? '<div style="font-size:0.66rem;color:var(--text-muted);margin-top:0.1rem;">' + __('Peers') + ' — ' + __('governorates') + ': ' + (govParts || '—') + ' | ' + __('types') + ': ' + (types || '—') + '</div>' : '') +
                            '</div>';
                        }).join('');
                    } else {
                        peerEl.innerHTML = '<div style="padding:0.5rem;color:var(--text-muted);font-size:0.78rem;">' + __('No peer comparisons — need 3+ hospitals of the same type or governorate.') + '</div>';
                    }
                }

                // ── Peer Hospitals table: rendered from the stored report by
                // _renderRcPeerHospitalsTable — it follows the selected timeline
                // indicator (peers_detail) and falls back to peer_hospitals.
                _renderRcPeerHospitalsTable(null);

                // ── Timeline: indicator value vs peer average with 95% CI band ──
                apiGet('/root-cause/' + hid + '/timeline?month=' + mth + '&months_back=6' + _rcPeerQ()).then(tl => {
                    _rcTimelineData = tl || { indicators: [] };
                    renderRcTimeline();
                }).catch(() => {
                    _rcTimelineData = { indicators: [] };
                    renderRcTimeline();
                });

                // Fetch ML data for PCA
                const mlUrl = '/analysis/ml?month=' + mth;
                apiGet(mlUrl).then(mlData => {
                    if (mlData && mlData.ml_pca) {
                        const pca = mlData.ml_pca;
                        const features = pca.top_features || {};
                        const entries = Object.entries(features).sort((a, b) => b[1] - a[1]);
                        let html = '<div style="margin-top:0.3rem;">';
                        const cumVar = pca.cumulative_variance ?? 0;
                        html += '<div style="font-size:0.72rem;color:var(--text-secondary);margin-bottom:0.3rem;">Cumulative variance explained: ' + (cumVar * 100).toFixed(0) + '%</div>';
                        if (!entries.length) {
                            html += '<div style="font-size:0.72rem;color:var(--text-muted);">No PCA data available.</div>';
                        } else {
                            const maxVal = Math.max(...entries.map(e => e[1]), 0.01);
                            entries.forEach(([name, variance]) => {
                                const pct = (variance / maxVal * 100).toFixed(0);
                                html += '<div style="display:flex;align-items:center;gap:0.3rem;margin:0.15rem 0;">';
                                html += '<span style="width:120px;font-size:0.72rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + esc(name) + '">' + esc(name) + '</span>';
                                html += '<div style="flex:1;height:14px;background:var(--border-default);border-radius:3px;"><div style="height:100%;width:' + pct + '%;background:var(--accent-blue);border-radius:3px;"></div></div>';
                                html += '<span style="width:40px;text-align:right;font-size:0.7rem;color:var(--text-secondary);">' + (variance * 100).toFixed(0) + '%</span>';
                                html += '</div>';
                            });
                        }
                        html += '</div>';
                        document.getElementById('pcaFeatures').innerHTML = html;
                    }
                }).catch(() => {});

            }).catch(e => {
                document.getElementById('rcLoading').style.display = 'none';
                document.getElementById('rcContent').style.display = 'block';
                document.getElementById('rcSummary').innerHTML = '<p style="color:var(--accent-red);">Error: ' + e.message + '</p>';
            });
        }

        export function initRootCause() {
            const hsel = document.getElementById('rcHospital');
            const msel = document.getElementById('rcMonth');
            if (!hsel || !msel) return; // التبويب لم يُحمَّل — لا شيء لنهيئه
            const phH = '<option value="">Select hospital</option>';
            const phM = '<option value="">Select month</option>';
            hsel.innerHTML = phH;
            msel.innerHTML = phM;
            Promise.all([
                apiGet('/hospitals/').then(data => {
                    const list = data.value || data || [];
                    hsel.innerHTML = phH + list.map(h => '<option value="' + h.id + '">' + h.name + '</option>').join('');
                }),
                populateMonthSelect('rcMonth', true),
            ]).then(() => {
                _restoreUIState('root-cause');
                // إذا وُجد سياق معلّق قادم من شاشة أخرى (التحليل الذكي)، طبّقه بدل الحالة المحفوظة
                if (!applyRootCauseContext() && hsel.value && msel.value) loadRootCause();
            }).catch(() => {
                _restoreUIState('root-cause');
                applyRootCauseContext();
            });
        }

        /**
         * يُنقل المستخدم من أي شاشة إلى تبويب Root Cause مع تمرير سياق
         * (المستشفى + الشهر) تلقائياً. يخزّن السياق، يفتح التبويب، ثم يطبّق
         * السياق فوراً إن كان التبويب مُهيّأ مسبقاً، أو بعد اكتمال تهيئته.
         */
        export function goRootCause(hospitalId, month) {
            window._rootCauseContext = { hospitalId: String(hospitalId), month: String(month) };
            const alreadyInited = _tabInited.has('root-cause');
            SwitchTab('root-cause');
            if (alreadyInited) applyRootCauseContext();
        }

        /**
         * يطبّق سياق السبب الجذري المعلّق على قائمتي المستشفى والشهر
         * ويحمّل النتيجة. يعيد true إذا طُبّق السياق وتحمّل.
         */
        export function applyRootCauseContext() {
            const ctx = window._rootCauseContext;
            if (!ctx) return false;
            const hsel = document.getElementById('rcHospital');
            const msel = document.getElementById('rcMonth');
            if (!hsel || !msel) return false;
            // طبّق السياق فقط عند تطابق الخيارين في القائمتين، حتى لا ينتج
            // مزيج خاطئ (مستشفى من السياق + شهر من الحالة المحفوظة)
            const hasHospital = [...hsel.options].some(o => o.value === ctx.hospitalId);
            const hasMonth = [...msel.options].some(o => o.value === ctx.month);
            window._rootCauseContext = null;
            if (!hasHospital || !hasMonth) return false;
            hsel.value = ctx.hospitalId;
            msel.value = ctx.month;
            loadRootCause();
            return true;
        }

        // ── Shared: Populate month select from DB ───────────────────
        export function populateMonthSelect(selectId, addAllOption) {
            const sel = document.getElementById(selectId);
            const ph = addAllOption ? '<option value="">All</option>' : '<option value="">Select month</option>';
            sel.innerHTML = ph;
            return apiGet('/analysis/months').then(months => {
                sel.innerHTML = ph + months.map(m => '<option value="' + m + '">' + m + '</option>').join('');
            }).catch(() => {});
        }

        // ── Dashboard ──────────────────────────────────────────────
        let trendChartInstance = null, confidenceChartInstance = null, radarChartInstance = null;
        let scorecardTrendInstance = null, scorecardRatesInstance = null;

        function renderKpiCards(hid) {
            const dr = window._dashboardDateRange;
            const yr = document.getElementById('dashYear').value;
            let url = '/dashboard/kpi?';
            if (hid) url += 'hospital_id=' + hid + '&';
            if (dr && dr.from) url += 'month_from=' + dr.from + '&';
            if (dr && dr.to) url += 'month_to=' + dr.to + '&';
            if (yr) url += 'year=' + yr;
            apiGet(url).then(data => {
                const container = document.getElementById('dashKpiCards');
                container.innerHTML = (data.kpis || []).map(k => {
                    const hasTarget = k.target != null;
                    const pct = hasTarget ? Math.min(k.value / k.target, 1) : 0.5;
                    const bg = hasTarget
                        ? (k.higher_is_better ? (pct >= 1 ? 'var(--severity-success-bg)' : pct >= 0.75 ? 'var(--severity-warning-bg)' : 'var(--severity-critical-bg)') : (pct <= 1 ? 'var(--severity-success-bg)' : 'var(--severity-critical-bg)'))
                        : 'var(--bg-surface-hover)';
                    const valColor = hasTarget
                        ? (k.higher_is_better ? (pct >= 1 ? 'var(--accent-green)' : pct >= 0.75 ? 'var(--accent-orange)' : 'var(--accent-red)') : (pct <= 1 ? 'var(--accent-green)' : 'var(--accent-red)'))
                        : '#555';
                    const barPct = Math.min(pct * 100, 100);
                    var _noDrill = k.id === 'report_coverage';
                    return '<div class="card" style="text-align:left;padding:0.8rem 1rem;background:' + bg + ';' + (_noDrill ? '' : 'cursor:pointer;') + '"' + (_noDrill ? '' : ' onclick="window.openKPIDrilldown(\'' + k.id + '\')"') + '>' +
                        '<div style="display:flex;justify-content:space-between;align-items:baseline;">' +
                        '<span style="font-size:0.75rem;color:var(--text-secondary);font-weight:500;">' + k.label + '</span>' +
                        '<span style="font-size:1.1rem;font-weight:700;color:' + valColor + ';">' + k.value + (k.unit ? ' <span style="font-size:0.7rem;">' + k.unit + '</span>' : '') + '</span></div>' +
                        (k.target ? '<div style="margin-top:4px;display:flex;align-items:center;gap:4px;"><div style="flex:1;height:5px;background:var(--border-default);border-radius:3px;"><div style="width:' + barPct + '%;height:5px;background:' + (pct >= 1 ? 'var(--accent-green)' : pct >= 0.75 ? 'var(--accent-yellow)' : 'var(--accent-red)') + ';border-radius:3px;transition:width 0.4s;"></div></div><span style="font-size:0.65rem;color:var(--text-muted);">target ' + k.target + '</span></div>' : '') +
                        '</div>';
                }).join('');
            }).catch(() => {});
        }

        let _dashMonthsCache = null;
        function _dashboardMonths() {
            if (!_dashMonthsCache) {
                _dashMonthsCache = apiGet('/analysis/months')
                    .then(function(m) { return m.months || m || []; })
                    .catch(function() { return []; });
            }
            return _dashMonthsCache;
        }
        function _resolveConfTarget(hid, yr) {
            const dr = window._dashboardDateRange;
            return _dashboardMonths().then(function(months) {
                if (!months.length) return null;
                let hid2 = hid;
                if (!hid2) {
                    const hsel = document.getElementById('dashHospital');
                    if (hsel) {
                        for (let i = 0; i < hsel.options.length; i++) {
                            if (hsel.options[i].value) { hid2 = hsel.options[i].value; break; }
                        }
                    }
                }
                if (!hid2) return null;
                const matched = months.filter(function(m) {
                    if (dr && dr.from && dr.to) return m >= dr.from && m <= dr.to;
                    if (dr && dr.from) return m >= dr.from;
                    if (dr && dr.to) return m <= dr.to;
                    if (yr) return String(m).slice(0, 4) === String(yr);
                    return true;
                });
                const all = matched.length ? matched : months;
                return { hid: hid2, month: all[all.length - 1] };
            });
        }

        let _kpiDrilldownChart = null;
        window.openKPIDrilldown = function(metric) {
            if (metric === 'report_coverage') return; // no drilldown for report count
            const modal = document.getElementById('detailModal');
            const titleEl = document.getElementById('modalTitle');
            const bodyEl = document.getElementById('modalBody');
            if (!modal || !titleEl || !bodyEl) return;

            const metricLabels = {
                quality_score: __('Quality Score'),
                rule_compliance: __('Validation rule'),
                completeness: __('Completeness'),
                consistency: __('Consistency'),
                conf_high: __('High Confidence'),
                outlier_score: __('Outlier Score'),
                report_coverage: __('Report Coverage'),
            };
            const label = metricLabels[metric] || metric;

            titleEl.textContent = label + ' — ' + __('Drilldown');
            bodyEl.innerHTML =
                '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:3rem 1rem;gap:0.9rem;">' +
                '<span class="spinner spinner-lg"></span>' +
                '<span style="color:var(--text-muted);font-size:0.85rem;">' + __('Loading details...') + '</span>' +
                '</div>';
            modal.classList.add('show');

            const hid = document.getElementById('dashHospital').value;
            const yr = document.getElementById('dashYear').value;
            // Honor the dashboard's From/To month filter — the KPI cards above
            // send month_from/month_to (window._dashboardDateRange), and the
            // backend gives the range precedence over year. Omitting it here
            // made every drilldown show unfiltered (all-months) data even
            // when the cards showed the filtered value.
            const dr = window._dashboardDateRange;
            let kpiUrl = '/dashboard/kpi?';
            if (hid) kpiUrl += 'hospital_id=' + hid + '&';
            if (dr && dr.from) kpiUrl += 'month_from=' + dr.from + '&';
            if (dr && dr.to) kpiUrl += 'month_to=' + dr.to + '&';
            if (yr) kpiUrl += 'year=' + yr;

            let overviewUrl = '/dashboard/overview?';
            if (hid) overviewUrl += 'hospital_id=' + hid + '&';
            if (dr && dr.from) overviewUrl += 'month_from=' + dr.from + '&';
            if (dr && dr.to) overviewUrl += 'month_to=' + dr.to + '&';
            if (yr) overviewUrl += 'year=' + yr;

            let diagUrl = '/dashboard/component-diagnostics?';
            if (hid) diagUrl += 'hospital_id=' + hid + '&';
            if (dr && dr.from) diagUrl += 'month_from=' + dr.from + '&';
            if (dr && dr.to) diagUrl += 'month_to=' + dr.to + '&';
            if (yr) diagUrl += 'year=' + yr + '&';
            if (metric && metric !== 'quality_score' && metric !== 'conf_high' && metric !== 'report_coverage') diagUrl += 'metric=' + metric;

            // For conf_high: resolve hospital + month from live data (no hardcoded IDs/months)
            var _confPromise = (metric === 'conf_high')
                ? _resolveConfTarget(hid, yr).then(function(target) {
                    if (!target) return null;
                    var confUrl2 = '/confidence/' + target.hid + '?month=' + target.month;
                    console.log('[conf] confUrl:', confUrl2, 'hid:', hid, 'month:', target.month);
                    return apiGet(confUrl2).catch(function(e){ console.log('[conf] fetch failed:', e); return null; });
                  })
                : Promise.resolve(null);
            var _ctrlPromise = apiGet('/config/control/settings').catch(function(){ return {}; });
            Promise.all([apiGet(kpiUrl), apiGet(overviewUrl), apiGet(diagUrl).catch(function(){ return null; }), _confPromise, _ctrlPromise]).then(function(results) {
                var kpiData = results[0], overviewData = results[1], diag = results[2], confDetail = results[3], ctrlSettings = results[4] || {};
                console.log('[conf] confDetail:', confDetail ? (confDetail.indicators || []).length + ' indicators' : 'null');
                var kpi = (kpiData.kpis || []).find(function(k) { return k.id === metric; });
                var trend = overviewData.quality_trend || [];
                var radar = overviewData.radar_components || {};
                var components = (diag && diag.components) || [];
                var compTrend = (diag && (diag.hosp_trend && diag.hosp_trend.length ? diag.hosp_trend : diag.trend)) || [];

                var html = '';

                // KPI value + target
                if (kpi) {
                    html += '<div class="scorecard-kpi-bar">' +
                        '<div class="scorecard-kpi-item" style="border-top-color:var(--accent-blue);background:var(--bg-elevated);">' +
                        '<div style="font-size:0.65rem;color:var(--text-muted);text-transform:uppercase;">' + label + '</div>' +
                        '<div style="font-size:1.5rem;font-weight:700;color:var(--accent-blue);">' + kpi.value + (kpi.unit ? ' ' + kpi.unit : '') + '</div></div>';
                    if (kpi.target != null) {
                        html += '<div class="scorecard-kpi-item">' +
                            '<div style="font-size:0.65rem;color:var(--text-muted);text-transform:uppercase;">Target</div>' +
                            '<div style="font-size:1.1rem;font-weight:600;">' + kpi.target + (kpi.unit ? ' ' + kpi.unit : '') + '</div></div>';
                    }
                    html += '</div>';
                }

                // Chart: signal factors for conf_high, component trend for others
                if (metric === 'conf_high') {
                    html += '<div class="card" style="margin-top:1rem;"><h3>' + __('Confidence Signal Factors') + '</h3>' +
                        '<div style="position:relative;height:220px;max-height:220px;overflow:hidden;"><canvas id="kpiDrilldownChart"></canvas></div>' +
                        '</div>';
                } else if (compTrend.length) {
                    html += '<div class="card" style="margin-top:1rem;"><h3>' + label + ' ' + __('Trend') + '</h3>' +
                        '<div style="position:relative;height:220px;max-height:220px;overflow:hidden;"><canvas id="kpiDrilldownChart"></canvas></div>' +
                        '</div>';
                } else if (trend.length) {
                    html += '<div class="card" style="margin-top:1rem;"><h3>' + __('Quality Trend') + '</h3>' +
                        '<div style="position:relative;height:200px;max-height:200px;overflow:hidden;"><canvas id="kpiDrilldownChart"></canvas></div></div>';
                }

                // Enhanced Component Breakdown (with diagnostics)
                if (components.length) {
                    html += '<div class="card" style="margin-top:1rem;"><h3>' + __('Component Breakdown') + '</h3>';
                    components.forEach(function(c) {
                        var col = c.avg >= 80 ? 'var(--accent-green)' : c.avg >= 60 ? 'var(--accent-orange)' : 'var(--accent-red)';
                        var dirIcon = c.direction === 'improving' ? '\u2191' : c.direction === 'declining' ? '\u2193' : '\u2192';
                        var dirColor = c.direction === 'improving' ? 'var(--accent-green)' : c.direction === 'declining' ? 'var(--accent-red)' : 'var(--text-muted)';
                        var gapColor = c.gap > 20 ? 'var(--accent-red)' : c.gap > 5 ? 'var(--accent-orange)' : 'var(--accent-green)';
                        var statusLabel = c.gap <= 0 ? '<span style="color:var(--accent-green);font-weight:600;">\u2705 ' + __('On Target') + '</span>' :
                            c.gap <= 5 ? '<span style="color:var(--accent-orange);font-weight:600;">\u26a0\ufe0f ' + c.gap + '% ' + __('gap') + '</span>' :
                            '<span style="color:var(--accent-red);font-weight:600;">\u274c ' + c.gap + '% ' + __('gap') + '</span>';

                        // Main card
                        html += '<div style="border:1px solid var(--border-default);border-radius:8px;margin-bottom:0.8rem;overflow:hidden;">';

                        // Header row
                        html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:0.6rem 0.8rem;background:var(--bg-elevated);cursor:pointer;" onclick="this.parentElement.querySelector(\'._diag-body\').classList.toggle(\'hidden\')">';
                        html += '<div style="display:flex;align-items:center;gap:0.5rem;">';
                        html += '<span style="font-weight:600;font-size:0.85rem;">' + esc(__(c.name)) + '</span>';
                        html += '<span style="font-size:0.75rem;color:' + dirColor + ';">' + dirIcon + '</span>';
                        html += '</div>';
                        html += '<div style="display:flex;align-items:center;gap:0.5rem 0.8rem;flex-wrap:wrap;">';
                        html += '<span style="font-weight:700;color:' + col + ';font-size:0.95rem;">' + c.avg + '%</span>';
                        html += '<span style="font-size:0.7rem;color:var(--text-muted);">/ ' + c.target + '%</span>';
                        html += statusLabel;
                        html += '<span style="font-size:0.7rem;color:var(--text-muted);">\u25bc</span>';
                        html += '</div></div>';

                        // Progress bar
                        html += '<div style="padding:0 0.8rem;">';
                        html += '<div style="height:4px;background:var(--border-default);border-radius:2px;margin:0.3rem 0;">';
                        html += '<div style="width:' + Math.min(c.avg, 100) + '%;height:4px;background:' + col + ';border-radius:2px;transition:width 0.4s;"></div>';
                        html += '</div>';
                        html += '<div style="display:flex;justify-content:space-between;gap:0.3rem 1rem;flex-wrap:wrap;font-size:0.65rem;color:var(--text-muted);margin-bottom:0.2rem;">';
                        html += '<span>' + __('Actual') + ': ' + c.avg + '%</span>';
                        html += '<span>' + __('Target') + ': ' + c.target + '%</span>';
                        html += '<span>' + __('Worst') + ': <span dir="ltr">' + c.worst_month + '</span> (' + c.min + '%)</span>';
                        html += '<span>' + __('Range') + ': ' + c.range + '%</span>';
                        html += '</div></div>';

                        // Diagnosis body (collapsible)
                        html += '<div class="_diag-body" style="padding:0.5rem 0.8rem 0.8rem;border-top:1px solid var(--border-default);">';

                        // Causes table
                        if (c.causes && c.causes.length) {
                            html += '<div style="font-size:0.75rem;font-weight:600;color:var(--text-secondary);margin-bottom:0.3rem;">' + __('Root Causes') + '</div>';
                            c.causes.forEach(function(cause) {
                                var sevColor = cause.severity === 'critical' ? 'var(--accent-red)' : cause.severity === 'warning' ? 'var(--accent-orange)' : cause.severity === 'ok' ? 'var(--accent-green)' : 'var(--text-muted)';
                                var sevBg = cause.severity === 'critical' ? 'rgba(198,40,40,0.08)' : cause.severity === 'warning' ? 'rgba(230,81,0,0.08)' : 'rgba(46,125,50,0.08)';
                                var sevIcon = cause.severity === 'critical' ? '\u274c' : cause.severity === 'warning' ? '\u26a0\ufe0f' : cause.severity === 'ok' ? '\u2705' : '\u2139\ufe0f';
                                html += '<div style="display:flex;align-items:flex-start;gap:6px;padding:0.4rem 0.5rem;border-radius:6px;margin-bottom:0.3rem;background:' + sevBg + ';flex-wrap:wrap;">';
                                html += '<span style="font-size:0.75rem;flex-shrink:0;margin-top:1px;">' + sevIcon + '</span>';
                                html += '<div style="flex:1;min-width:120px;">';
                                html += '<div style="font-size:0.78rem;font-weight:600;color:' + sevColor + ';">' + esc(__(cause.cause)) + '</div>';
                                html += '<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:1px;" dir="auto">' + esc(cause.detail) + '</div>';
                                html += '</div>';
                                if (cause.impact_pct > 0) {
                                    html += '<div style="text-align:right;flex-shrink:0;">';
                                    html += '<div style="font-size:0.65rem;color:var(--text-muted);">' + __('Impact') + '</div>';
                                    html += '<div style="font-size:0.8rem;font-weight:700;color:' + sevColor + ';"><span dir="ltr">-' + cause.impact_pct + '%</span></div>';
                                    html += '</div>';
                                }
                                if (cause.first_month) {
                                    html += '<div style="text-align:right;flex-shrink:0;">';
                                    html += '<div style="font-size:0.65rem;color:var(--text-muted);">' + __('Started') + '</div>';
                                    html += '<div style="font-size:0.72rem;font-weight:600;"><span dir="ltr">' + cause.first_month + '</span></div>';
                                    html += '</div>';
                                }
                                html += '</div>';

                                // Per-hospital affected list (expandable/collapsible cards)
                                var affected = cause.affected_hospitals || [];
                                if (affected.length > 0) {
                                    html += '<div style="margin-top:0.5rem;">';
                                    html += '<div style="font-size:0.72rem;font-weight:600;color:var(--text-secondary);margin-bottom:0.4rem;display:flex;align-items:center;gap:0.4rem;">';
                                    html += '\ud83d\udcca ' + __('Affected Hospitals') + ' <span style="background:var(--accent-red);color:#fff;padding:0 6px;border-radius:10px;font-size:0.65rem;font-weight:700;">' + affected.length + '</span>';
                                    html += '</div>';
                                    html += '<div style="max-height:340px;overflow-y:auto;display:flex;flex-direction:column;gap:0.4rem;padding-right:4px;">';
                                    affected.forEach(function(rawH, idx) {
                                        // Defensive normalization: production payloads have
                                        // occasionally arrived with null scores, missing month
                                        // lists, or failed_rules as a count — any of which made
                                        // the old renderer emit a broken/invisible card. Every
                                        // row must render as a proper visible card.
                                        var h = (rawH && typeof rawH === 'object') ? rawH : (typeof rawH === 'string' ? {hospital_name: rawH} : {});
                                        var avgNum = parseFloat(h.avg_value);
                                        if (isNaN(avgNum)) avgNum = 0;
                                        var hName = (h.hospital_name == null || h.hospital_name === '') ? ('#' + (h.hospital_id != null ? h.hospital_id : (idx + 1))) : String(h.hospital_name);
                                        var problemMonths = Array.isArray(h.problem_months) ? h.problem_months : [];
                                        var failedRules = Array.isArray(h.failed_rules) ? h.failed_rules : [];
                                        var hCol = avgNum >= 80 ? 'var(--accent-green)' : avgNum >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)';
                                        var missRaw = Array.isArray(h.missing_by_indicator) ? h.missing_by_indicator : [];
                                        // Drop malformed entries (null/blank indicator names) so no
                                        // empty rows render in the missing-indicators table.
                                        var missList = missRaw.length
                                            ? missRaw.filter(function(m) { return m && typeof m === 'object' && m.indicator != null && String(m.indicator).trim() !== ''; })
                                            : null;
                                        if (missList && !missList.length) missList = null;
                                        var missTotal = (h.missing_count != null) ? h.missing_count : (missList ? missList.length : ((Array.isArray(h.missing_indicators) && h.missing_indicators.length) ? h.missing_indicators.length : 0));
                                        // flex-shrink:0 — without it, cards inside this max-height flex
                                        // column compress below their content height and overlap.
                                        html += '<div style="border:1px solid var(--border-default);border-radius:6px;overflow:hidden;flex-shrink:0;">';

                                        // Hospital header (click to expand/collapse)
                                        html += '<div class="_hosp-head" style="display:flex;align-items:center;gap:0.5rem;padding:0.45rem 0.6rem;background:var(--bg-surface-hover);cursor:pointer;transition:background 0.15s;" onclick="var b=this.parentElement.querySelector(\'._hosp-body\');var c=this.querySelector(\'._hosp-chev\');var isHidden=b.classList.toggle(\'hidden\');c.textContent=isHidden?\'\u25b8\':\'\u25be\';">';
                                        html += '<span style="flex-shrink:0;width:20px;height:20px;border-radius:50%;background:' + hCol + ';color:#fff;font-size:0.6rem;font-weight:700;display:flex;align-items:center;justify-content:center;">' + (idx + 1) + '</span>';
                                        // Name always wraps fully — clamping long hospital names to
                                        // 2 lines cut them off mid-path ("مستشفيات/…") and read as
                                        // broken. All words stay visible; the row simply grows.
                                        html += '<div style="flex:1 1 110px;min-width:0;font-size:0.75rem;font-weight:600;color:var(--text-primary);line-height:1.35;word-break:break-word;" title="' + esc(hName) + '">' + esc(hName) + '</div>';
                                        if (missTotal > 0) {
                                            html += '<span style="flex-shrink:0;background:rgba(198,40,40,0.15);color:var(--accent-red);padding:1px 7px;border-radius:10px;font-size:0.65rem;font-weight:700;" title="' + __('Missing Indicators') + '">' + missTotal + '</span>';
                                        }
                                        html += '<span style="flex-shrink:0;font-size:0.7rem;font-weight:700;color:' + hCol + ';"><span dir="ltr">' + avgNum + '%</span></span>';
                                        html += '<span class="_hosp-chev" style="flex-shrink:0;font-size:0.7rem;color:var(--text-muted);">\u25b8</span>';
                                        html += '</div>';

                                        // Hospital body (hidden until expanded)
                                        html += '<div class="_hosp-body hidden" style="padding:0.55rem 0.6rem;border-top:1px solid var(--border-default);">';

                                        // Full hospital name first — the header clamps long names to
                                        // 2 lines, and the title tooltip is useless on touch screens.
                                        html += '<div style="font-size:0.72rem;font-weight:600;color:var(--text-primary);word-break:break-word;margin-bottom:0.45rem;line-height:1.4;">' + esc(hName) + '</div>';

                                        // Progress / months summary (score shown once here, not repeated in the header)
                                        html += '<div style="display:flex;align-items:center;gap:0.4rem;margin-bottom:0.4rem;">';
                                        html += '<div style="flex:1;height:5px;background:var(--border-default);border-radius:3px;overflow:hidden;">';
                                        html += '<div style="width:' + Math.min(avgNum, 100) + '%;height:5px;background:' + hCol + ';border-radius:3px;"></div>';
                                        html += '</div>';
                                        html += '</div>';
                                        if (problemMonths.length) {
                                            var pm = problemMonths;
                                            var pmTxt = pm.length <= 3 ? pm.join(', ') : pm[0] + ' → ' + pm[pm.length - 1] + ' (' + pm.length + ' ' + __('months') + ')';
                                            html += '<div style="margin-bottom:0.4rem;font-size:0.63rem;color:var(--text-muted);"><span dir="ltr">' + pmTxt + '</span></div>';
                                        }

                                        // Failed rules: collapsible chip cloud (first 6 inline, rest behind a toggle)
                                        if (failedRules.length) {
                                            var fr = failedRules;
                                            html += '<div style="margin-bottom:0.4rem;">';
                                            html += '<div style="font-size:0.63rem;color:var(--text-muted);margin-bottom:3px;">' + __('Failed rules') + ' (' + fr.length + ')</div>';
                                            html += '<div style="display:flex;flex-wrap:wrap;gap:3px;">';
                                            fr.slice(0, 6).forEach(function(r) {
                                                var rCode = typeof r === 'object' ? r.code : r;
                                                var rSev = typeof r === 'object' ? (r.severity || 'HIGH') : 'HIGH';
                                                var rDesc = typeof r === 'object' ? (r.description || r.code) : r;
                                                var rBg = rSev === 'CRITICAL' ? 'rgba(198,40,40,0.2)' : rSev === 'HIGH' ? 'rgba(198,40,40,0.12)' : 'rgba(230,81,0,0.12)';
                                                var rFg = rSev === 'CRITICAL' || rSev === 'HIGH' ? 'var(--accent-red)' : 'var(--accent-orange)';
                                                html += '<span style="display:inline-block;background:' + rBg + ';color:' + rFg + ';padding:1px 5px;border-radius:3px;font-size:0.58rem;font-weight:600;cursor:help;" title="' + esc(rDesc) + '">' + esc(rCode) + '</span>';
                                            });
                                            if (fr.length > 6) {
                                                html += '<span style="display:inline-block;color:var(--text-muted);font-size:0.6rem;font-weight:600;cursor:pointer;padding:1px 4px;" onclick="var extra=this.nextElementSibling;var hiding=extra.style.display!==\'none\';extra.style.display=hiding?\'none\':\'contents\';this.textContent=(hiding?\'+' + (fr.length - 6) + ' ' + __('more') + '\' : \'show less\');">+' + (fr.length - 6) + ' ' + __('more') + '</span>';
                                                html += '<span style="display:none;">';
                                                fr.slice(6).forEach(function(r) {
                                                    var rCode = typeof r === 'object' ? r.code : r;
                                                    var rSev = typeof r === 'object' ? (r.severity || 'HIGH') : 'HIGH';
                                                    var rDesc = typeof r === 'object' ? (r.description || r.code) : r;
                                                    var rBg = rSev === 'CRITICAL' ? 'rgba(198,40,40,0.2)' : rSev === 'HIGH' ? 'rgba(198,40,40,0.12)' : 'rgba(230,81,0,0.12)';
                                                    var rFg = rSev === 'CRITICAL' || rSev === 'HIGH' ? 'var(--accent-red)' : 'var(--accent-orange)';
                                                    html += '<span style="display:inline-block;background:' + rBg + ';color:' + rFg + ';padding:1px 5px;border-radius:3px;font-size:0.58rem;font-weight:600;cursor:help;" title="' + esc(rDesc) + '">' + esc(rCode) + '</span>';
                                                });
                                                html += '</span>';
                                            }
                                            html += '</div></div>';
                                        }

                                        // Missing indicators: 2-column table (indicator | months)
                                        if (missList) {
                                            html += '<div style="font-size:0.68rem;font-weight:600;color:var(--text-secondary);margin-bottom:0.3rem;">' + __('Missing Indicators') + '</div>';
                                            html += '<div style="overflow-x:auto;">';
                                            html += '<table style="width:100%;border-collapse:collapse;font-size:0.68rem;">';
                                            html += '<thead><tr style="background:var(--bg-surface);">';
                                            html += '<th style="text-align:left;padding:0.25rem 0.4rem;width:55%;">' + __('Indicator') + '</th>';
                                            html += '<th style="text-align:left;padding:0.25rem 0.4rem;">' + __('Missing in Month(s)') + '</th>';
                                            html += '</tr></thead><tbody>';
                                            missList.forEach(function(m) {
                                                var months = (Array.isArray(m.months) ? m.months : []).filter(function(mo) { return mo != null && String(mo).trim() !== ''; });
                                                html += '<tr style="border-bottom:1px solid var(--border-default);">';
                                                html += '<td style="padding:0.25rem 0.4rem;font-weight:500;">' + esc(m.indicator) + '</td>';
                                                html += '<td style="padding:0.25rem 0.4rem;">';
                                                if (months.length > 4) {
                                                    // Production ranges can span 100+ months — a chip per
                                                    // month would bury the row. Compact range instead.
                                                    html += '<span dir="ltr" style="display:inline-block;background:rgba(198,40,40,0.12);color:var(--accent-red);padding:1px 6px;border-radius:4px;font-size:0.62rem;font-weight:600;">' + esc(months[0]) + ' \u2192 ' + esc(months[months.length - 1]) + ' (' + months.length + ')</span>';
                                                } else if (months.length) {
                                                    html += '<div style="display:flex;flex-wrap:wrap;gap:3px;">';
                                                    months.forEach(function(mo) {
                                                        html += '<span style="display:inline-block;background:rgba(198,40,40,0.12);color:var(--accent-red);padding:1px 6px;border-radius:4px;font-size:0.62rem;font-weight:600;">' + esc(mo) + '</span>';
                                                    });
                                                    html += '</div>';
                                                } else {
                                                    html += '<span style="color:var(--text-muted);font-size:0.62rem;">—</span>';
                                                }
                                                html += '</td>';
                                                html += '</tr>';
                                            });
                                            if (missTotal > missList.length) {
                                                html += '<tr style="border-bottom:none;"><td colspan="2" style="padding:0.3rem 0.4rem;color:var(--text-muted);font-size:0.65rem;">+ ' + (missTotal - missList.length) + ' ' + __('more missing indicators') + '</td></tr>';
                                            }
                                            html += '</tbody></table></div>';
                                        } else if (Array.isArray(h.missing_indicators) && h.missing_indicators.length) {
                                            html += '<div style="margin-top:4px;display:flex;flex-wrap:wrap;gap:3px;">';
                                            h.missing_indicators.forEach(function(mi) {
                                                if (mi == null || String(mi).trim() === '') return;
                                                html += '<span style="display:inline-block;background:rgba(198,40,40,0.12);color:var(--accent-red);padding:1px 6px;border-radius:4px;font-size:0.6rem;">' + esc(mi) + '</span>';
                                            });
                                            html += '</div>';
                                        }

                                        html += '</div>'; // _hosp-body
                                        html += '</div>'; // hospital card
                                    });
                                    html += '</div></div>';
                                } else {
                                    // Zero affected hospitals for this cause — say why,
                                    // so an empty list doesn't look like a broken one.
                                    var _anMonths = (c.monthly || []).map(function(m) { return m.month; });
                                    html += '<div class="_cause-zero" style="margin-top:0.5rem;">';
                                    html += '<span style="display:inline-flex;align-items:center;gap:4px;background:var(--severity-success-bg, rgba(46,125,50,0.1));color:var(--accent-green);border:1px solid var(--accent-green);padding:2px 8px;border-radius:10px;font-size:0.65rem;font-weight:700;cursor:pointer;" onclick="var n=this.closest(\'._cause-zero\').querySelector(\'._zero-note\');var isHidden=n.classList.toggle(\'hidden\');this.querySelector(\'._zero-chev\').textContent=isHidden?\'\u25b8\':\'\u25be\';">\u2705 ' + __('No hospitals affected') + ' <span class="_zero-chev" style="font-size:0.6rem;">\u25be</span></span>';
                                    html += '<div class="_zero-note hidden" style="margin-top:0.4rem;padding:0.5rem 0.6rem;border:1px dashed var(--border-default);border-radius:6px;font-size:0.7rem;color:var(--text-secondary);background:var(--bg-elevated);">';
                                    html += '<div>' + __('No hospital-month in this range falls under this cause — nothing to fix here.') + '</div>';
                                    if (_anMonths.length) {
                                        html += '<div style="margin-top:0.3rem;color:var(--text-muted);">' + __('Months analyzed') + ': ' + _anMonths.join(', ') + '</div>';
                                    }
                                    html += '</div>';
                                    html += '</div>';
                                }
                            });
                        }

                        html += '</div>'; // _diag-body
                        html += '</div>'; // card
                    });
                    html += '</div>';
                } else {
                    // Fallback: old radar-based table
                    var componentKeys = Object.keys(radar);
                    if (componentKeys.length) {
                        html += '<div class="card" style="margin-top:1rem;"><h3>' + __('Component Breakdown') + '</h3>';
                        html += '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;">';
                        html += '<thead><tr><th style="text-align:left;padding:0.4rem 0.6rem;border-bottom:2px solid var(--border-default);">' + __('Component') + '</th>';
                        html += '<th style="text-align:right;padding:0.4rem 0.6rem;border-bottom:2px solid var(--border-default);">' + __('Score') + '</th>';
                        html += '<th style="text-align:left;padding:0.4rem 0.6rem;border-bottom:2px solid var(--border-default);width:40%;"></th></tr></thead><tbody>';
                        componentKeys.forEach(function(key) {
                            var val = radar[key];
                            var col2 = val >= 80 ? 'var(--accent-green)' : val >= 60 ? 'var(--accent-orange)' : 'var(--accent-red)';
                            html += '<tr><td style="padding:0.4rem 0.6rem;border-bottom:1px solid var(--border-default);font-weight:500;">' + esc(key) + '</td>';
                            html += '<td style="padding:0.4rem 0.6rem;border-bottom:1px solid var(--border-default);text-align:right;font-weight:700;color:' + col2 + ';">' + val + '%</td>';
                            html += '<td style="padding:0.4rem 0.6rem;border-bottom:1px solid var(--border-default);"><div style="height:6px;background:var(--border-default);border-radius:3px;"><div style="width:' + val + '%;height:6px;background:' + col2 + ';border-radius:3px;"></div></div></td></tr>';
                        });
                        html += '</tbody></table></div>';
                    }
                }

                                // ── High Confidence Detail (5 Signal Factors) ──
                if (metric === 'conf_high' && confDetail && confDetail.indicators) {
                    try {
                    console.log('[conf] DETAIL SECTION ENTERED, indicators:', confDetail.indicators.length);
                    var sd = confDetail;
                    html += '<div class="card" style="margin-top:1rem;max-height:600px;overflow-y:auto;"><h3>' + __('Confidence Factors') + '</h3>';
                    html += '<div style="font-size:0.78rem;color:var(--text-secondary);margin-bottom:0.8rem;">' + esc(sd.summary || '') + '</div>';

                    var _sigData = [
                        {key: 'rule_compliance', name: __('Validation rule compliance'), weight: 55, icon: '\u2705', color: '#e65100'},
                        {key: 'historical', name: __('Historical consistency'), weight: 10, icon: '\ud83d\udcc8', color: '#1565c0'},
                        {key: 'cross_hospital', name: __('Cross-hospital comparison'), weight: 10, icon: '\ud83d\udcca', color: '#6a1b9a'},
                        {key: 'trend', name: __('Trend analysis'), weight: 10, icon: '\ud83d\udcc9', color: '#2e7d32'},
                        {key: 'completeness', name: __('Data completeness'), weight: 15, icon: '\ud83d\udcdd', color: '#00838f'}
                    ];

                    // Compute WEIGHTED avg score per signal (matches backend formula)
                    var _sigAvgs = {}, _sigTotalW = {};
                    _sigData.forEach(function(s) { _sigAvgs[s.key] = 0; _sigTotalW[s.key] = 0; });
                    var _indWeights = {'11':5,'17':5,'2':3,'6':3,'5':2.5,'10':2,'7':2,'6.f':2,'6.g':2,'16':1.5,'8':1,'3':1.5,'4':1.5,'9':1,'12':1,'13':1,'14':0.5,'18':0.5,'26':1.5};
                    // Check auto-disable setting from control panel
                    var _autoDisable = !!ctrlSettings.auto_disable_null_indicators;
                    sd.indicators.forEach(function(ind) {
                        var w = _indWeights[ind.indicator_code] || 1;
                        if (ind.value === null || ind.value === undefined) {
                            if (_autoDisable) return; // skip nulls if auto-disable ON
                            // If OFF, include with 0% signals (data missing but counted)
                        }
                        if (ind.signals) ind.signals.forEach(function(sig) {
                            if (_sigAvgs[sig.factor] !== undefined) {
                                _sigAvgs[sig.factor] += sig.score * w;
                                _sigTotalW[sig.factor] += w;
                            }
                        });
                    });
                    _sigData.forEach(function(s) { s.avg = _sigTotalW[s.key] ? Math.round(_sigAvgs[s.key] / _sigTotalW[s.key] * 100) : 0; });

                    // Signal factor cards
                    html += '<div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(130px, 1fr));gap:0.5rem;margin-bottom:1rem;">';
                    _sigData.forEach(function(s) {
                        var avgColor = s.avg >= 80 ? 'var(--accent-green)' : s.avg >= 60 ? 'var(--accent-orange)' : 'var(--accent-red)';
                        html += '<div style="padding:0.6rem;border-radius:8px;border:2px solid ' + s.color + '33;background:' + s.color + '0a;">';
                        html += '<div style="font-size:0.65rem;color:' + s.color + ';font-weight:600;">' + s.icon + ' ' + s.name + '</div>';
                        html += '<div style="font-size:1.1rem;font-weight:700;color:' + s.color + ';margin:0.2rem 0;">' + s.avg + '%</div>';
                        html += '<div style="height:4px;background:var(--border-default);border-radius:2px;"><div style="width:' + s.avg + '%;height:4px;background:' + avgColor + ';border-radius:2px;"></div></div>';
                        html += '<div style="font-size:0.6rem;color:var(--text-muted);margin-top:2px;">' + __('Weight') + ': ' + s.weight + '%</div>';
                        html += '</div>';
                    });
                    html += '</div>';

                    // Level distribution
                    var _levels = sd.by_level || {};
                    html += '<div style="font-size:0.78rem;font-weight:600;color:var(--text-primary);margin-bottom:0.4rem;">' + __('Indicator Confidence Distribution') + '</div>';
                    html += '<div style="display:flex;gap:0.5rem;margin-bottom:1rem;flex-wrap:wrap;">';
                    [{k:'HIGH',c:'var(--accent-green)'},{k:'MEDIUM',c:'var(--accent-orange)'},{k:'LOW',c:'var(--accent-red)'},{k:'CRITICAL',c:'#b71c1c'}].forEach(function(lev) {
                        var cnt = _levels[lev.k] || 0;
                        html += '<div style="padding:0.4rem 0.8rem;border-radius:8px;background:' + lev.c + '15;border:1px solid ' + lev.c + '33;text-align:center;">';
                        html += '<div style="font-size:0.65rem;color:' + lev.c + ';">' + lev.k + '</div>';
                        html += '<div style="font-size:1rem;font-weight:700;color:' + lev.c + ';">' + cnt + '</div></div>';
                    });
                    html += '</div>';

                    // Group averages
                    var _groups = sd.by_group || {};
                    if (Object.keys(_groups).length) {
                        html += '<div style="font-size:0.78rem;font-weight:600;color:var(--text-primary);margin-bottom:0.4rem;">' + __('Confidence by Group') + '</div>';
                        html += '<div style="display:flex;flex-direction:column;gap:0.35rem;margin-bottom:1rem;">';
                        Object.keys(_groups).forEach(function(grp) {
                            var gv = _groups[grp];
                            var gc = gv >= 80 ? 'var(--accent-green)' : gv >= 60 ? 'var(--accent-orange)' : 'var(--accent-red)';
                            html += '<div style="display:flex;align-items:center;gap:0.6rem;font-size:0.75rem;">';
                            html += '<span style="width:130px;flex-shrink:0;font-weight:600;">' + esc(grp) + '</span>';
                            html += '<div style="flex:1;height:8px;background:var(--border-default);border-radius:4px;overflow:hidden;"><div style="width:' + Math.min(gv,100) + '%;height:8px;background:' + gc + ';border-radius:4px;"></div></div>';
                            html += '<span style="width:40px;text-align:right;font-weight:700;color:' + gc + ';">' + gv.toFixed(1) + '%</span></div>';
                        });
                        html += '</div>';
                    }

                    // Low-confidence indicators
                    var _prio = (sd.indicators || []).filter(function(i) {
                        if (i.level === 'HIGH') return false;
                        if (_autoDisable && (i.value === null || i.value === undefined)) return false;
                        return true;
                    }).slice(0, 20);
                    if (_prio.length) {
                        html += '<div style="font-size:0.78rem;font-weight:600;color:var(--text-primary);margin-bottom:0.4rem;">' + __('Indicators Needing Verification') + ' (' + _prio.length + ')</div>';
                        html += '<div style="max-height:400px;overflow-y:auto;display:flex;flex-direction:column;gap:0.4rem;padding-right:4px;">';
                        _prio.forEach(function(ind) {
                            var ilc = ind.level === 'CRITICAL' ? '#b71c1c' : ind.level === 'LOW' ? 'var(--accent-red)' : 'var(--accent-orange)';
                            var ilbg = ind.level === 'CRITICAL' ? 'rgba(183,28,28,0.08)' : ind.level === 'LOW' ? 'rgba(198,40,40,0.06)' : 'rgba(230,81,0,0.06)';
                            html += '<div style="padding:0.5rem 0.6rem;border-radius:8px;border:1px solid var(--border-default);background:' + ilbg + ';">';
                            html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
                            html += '<span style="font-size:0.78rem;font-weight:600;">' + esc(ind.indicator_name || ind.indicator_code) + ' <span style="font-size:0.62rem;color:var(--text-muted);">(' + esc(ind.indicator_code) + ')</span></span>';
                            html += '<span style="font-size:0.72rem;font-weight:700;color:' + ilc + ';">' + ind.confidence + '% \u2022 ' + ind.level + '</span></div>';
                            if (ind.value !== null && ind.value !== undefined) html += '<div style="font-size:0.65rem;color:var(--text-muted);margin-top:2px;">' + __('Value') + ': ' + ind.value + '</div>';
                            if (ind.signals && ind.signals.length) {
                                html += '<div style="display:flex;flex-wrap:wrap;gap:3px;margin-top:5px;">';
                                ind.signals.forEach(function(sig) {
                                    var sc = sig.passed ? 'var(--accent-green)' : sig.score >= 0.5 ? 'var(--accent-orange)' : 'var(--accent-red)';
                                    var sIcon = sig.passed ? '\u2705' : sig.score >= 0.5 ? '\u26a0\ufe0f' : '\u274c';
                                    var sName = _sigData.find(function(s){return s.key===sig.factor;});
                                    var sLabel = sName ? sName.name : sig.factor;
                                    html += '<span style="font-size:0.6rem;padding:2px 6px;border-radius:4px;background:' + sc + '18;color:' + sc + ';cursor:help;border:1px solid ' + sc + '33;" title="' + esc(sig.detail) + '">';
                                    html += sIcon + ' ' + sLabel + ': ' + (sig.score * 100).toFixed(0) + '%</span>';
                                });
                                html += '</div>';
                            }
                            if (ind.recommendations && ind.recommendations.length) html += '<div style="margin-top:4px;font-size:0.62rem;color:var(--text-muted);line-height:1.4;">' + ind.recommendations.slice(0, 2).map(function(r) { return '\u26a0 ' + esc(r); }).join(' \u2022 ') + '</div>';
                            html += '</div>';
                        });
                        html += '</div>';
                    }
                    html += '</div>';
                    } catch(e) { console.error('[conf] detail error:', e); }
                }

                bodyEl.innerHTML = html || '<p style="color:var(--text-muted);padding:1rem;">' + __('No details available.') + '</p>';

                // Render chart
                var chartCtx = document.getElementById('kpiDrilldownChart');
                if (chartCtx) {
                    if (_kpiDrilldownChart) { _kpiDrilldownChart.destroy(); _kpiDrilldownChart = null; }
                    if (metric === 'conf_high' && confDetail && confDetail.indicators) {
                        // Reuse _sigData from the detail section (weighted, auto-disable aware)
                        var _barLabels = _sigData.map(function(s) { return s.name; });
                        var _barWeights = _sigData.map(function(s) { return s.weight; });
                        var _barAvgs = _sigData.map(function(s) { return s.avg; });
                        var _barColors = _sigData.map(function(s) { return s.color; });
                        _kpiDrilldownChart = new Chart(chartCtx, {
                            type: 'bar',
                            data: {
                                labels: _barLabels,
                                datasets: [
                                    { label: __('Weight'), data: _barWeights, backgroundColor: _barColors.map(function(c) { return c + '44'; }), borderColor: _barColors, borderWidth: 2, borderRadius: 4 },
                                    { label: __('Score'), data: _barAvgs, backgroundColor: _barColors.map(function(c) { return c + '99'; }), borderColor: _barColors, borderWidth: 2, borderRadius: 4 },
                                ]
                            },
                            options: {
                                responsive: true, maintainAspectRatio: false, resizeDelay: 200,
                                plugins: { legend: { position: 'bottom', labels: { font: { size: 9 }, boxWidth: 8, boxHeight: 8, padding: 8 } } },
                                scales: { y: { min: 0, max: 100, ticks: { callback: function(v) { return v + '%'; } } } }
                            }
                        });
                    } else if (compTrend.length) {
                        // Build dataset based on clicked metric
                        var _dsMap = {
                            rule_compliance: { label: __('Validation rule'), key: 'rule_compliance', color: '#e65100' },
                            completeness: { label: __('Completeness'), key: 'completeness', color: '#2e7d32' },
                            consistency: { label: __('Consistency'), key: 'consistency', color: '#6a1b9a' },
                            outlier_score: { label: __('Outlier Score'), key: 'outlier_score', color: '#c62828' },
                            quality_score: { label: __('Quality Score'), key: 'score', color: getCSSVar('--accent-teal') || '#14b8a6' },
                        };
                        var ds = _dsMap[metric];
                        var datasets = [];
                        if (ds) {
                            datasets.push({ label: ds.label, data: compTrend.map(function(d) { return d[ds.key]; }), borderColor: ds.color, borderWidth: 2, tension: 0.3, pointRadius: 4, fill: false });
                        } else {
                            datasets.push({ label: __('Quality Score'), data: compTrend.map(function(d) { return d.score; }), borderColor: getCSSVar('--accent-teal') || '#14b8a6', borderWidth: 2, tension: 0.3, pointRadius: 4, fill: false });
                        }
                        // Always add target reference line if component has one
                        var _targetMap = { rule_compliance: 85, completeness: 90, consistency: 85, outlier_score: 90 };
                        if (_targetMap[metric]) {
                            datasets.push({ label: __('Target') + ' ' + _targetMap[metric] + '%', data: compTrend.map(function() { return _targetMap[metric]; }), borderColor: 'rgba(128,128,128,0.4)', borderDash: [6,4], borderWidth: 1, pointRadius: 0, fill: false });
                        }
                        _kpiDrilldownChart = new Chart(chartCtx, {
                            type: 'line',
                            data: {
                                labels: compTrend.map(function(d) { return d.month; }),
                                datasets: datasets
                            },
                            options: {
                                responsive: true, maintainAspectRatio: false, resizeDelay: 200,
                                plugins: { legend: { position: 'bottom', labels: { font: { size: 9 }, boxWidth: 8, boxHeight: 8, padding: 8 } } },
                                scales: { y: { min: 0, max: 100, ticks: { callback: function(v) { return v + '%'; } } } }
                            }
                        });
                    } else if (trend.length) {
                        // Fallback: single quality score trend
                        _kpiDrilldownChart = new Chart(chartCtx, {
                            type: 'line',
                            data: {
                                labels: trend.map(function(d) { return d.month; }),
                                datasets: [{
                                    label: label,
                                    data: trend.map(function(d) { return d.score; }),
                                    borderColor: getCSSVar('--accent-teal') || '#14b8a6',
                                    backgroundColor: (getCSSVar('--accent-teal') || '#14b8a6') + '1a',
                                    fill: true, tension: 0.3, pointRadius: 4,
                                }]
                            },
                            options: {
                                responsive: true, maintainAspectRatio: false, resizeDelay: 200,
                                plugins: { legend: { display: false } },
                                scales: { y: { min: 0, max: 100, ticks: { callback: function(v) { return v + '%'; } } } }
                            }
                        });
                    }
                    if (_kpiDrilldownChart && window.registerChart) window.registerChart(_kpiDrilldownChart);
                }
            }).catch(function() {
                bodyEl.innerHTML = '<p style="color:var(--accent-red);padding:1.5rem;">' + __('Failed to load details.') + '</p>';
            });
        };

        function renderSparkline(canvasId, dataPoints, color) {
            const canvas = document.getElementById(canvasId);
            if (!canvas || !dataPoints || dataPoints.length < 2) return;
            const rect = canvas.parentElement.getBoundingClientRect();
            const w = Math.max(rect.width - 10, 60);
            const h = 24;
            canvas.width = w * 2;
            canvas.height = h * 2;
            canvas.style.width = w + 'px';
            canvas.style.height = h + 'px';
            const ctx = canvas.getContext('2d');
            ctx.scale(2, 2);
            ctx.clearRect(0, 0, w, h);
            const max = Math.max(...dataPoints, 1);
            const min = Math.min(...dataPoints, 0);
            const range = max - min || 1;
            const pts = dataPoints.map((v, i) => ({
                x: (i / (dataPoints.length - 1)) * (w - 6) + 3,
                y: h - 3 - ((v - min) / range) * (h - 6),
            }));
            ctx.beginPath();
            const defaultColor = getCSSVar('--accent-teal') || '#14b8a6';
            ctx.strokeStyle = color || defaultColor;
            ctx.lineWidth = 1.2;
            pts.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y));
            ctx.stroke();
            ctx.lineTo(pts[pts.length - 1].x, h - 3);
            ctx.lineTo(pts[0].x, h - 3);
            ctx.closePath();
            ctx.fillStyle = (color || defaultColor) + '18';
            ctx.fill();
        }

        // ── Ranking Table ────────────────────────────────────────
        let rankingData = [];
        let rankingSortCol = 'avg_score';
        let rankingSortAsc = false;

        export function loadRankingTable() {
            const hid = document.getElementById('dashHospital').value;
            const dr = window._dashboardDateRange;
            let url = '/dashboard/ranking?';
            if (hid) url += 'hospital_id=' + hid + '&';
            if (dr && dr.from) url += 'month_from=' + dr.from + '&';
            if (dr && dr.to) url += 'month_to=' + dr.to;
            apiGet(url).then(data => {
                rankingData = data || [];
                renderRankingTable();
            }).catch(() => {});
        }

        let _rankingDt = null;
        function renderRankingTable() {
            if (!_rankingDt) {
                _rankingDt = new DataTable({ id: "rankingTable", pageSize: 25, defaultSort: "avg_score", defaultAsc: false });
            }
            _rankingDt.render([
                { key: "rank", label: "#", width: "40px" },
                { key: "name", label: "Hospital", render: r => "<strong>" + esc(r.name) + "</strong>", getValue: r => r.name },
                { key: "avg_score", label: "Quality Score", render: r => scoreBadge(r.avg_score) },
                { key: "trend_direction", label: "Trend", render: r => trendIcon(r.trend_direction), getValue: r => r.trend_direction === "up" ? 1 : r.trend_direction === "down" ? -1 : 0 },
                { key: "confidence", label: "Confidence", render: r => confidenceBar(r.confidence) },
                { key: "completeness", label: "Completeness", render: r => scoreBadge(r.completeness, { decimals: 0 }) },
                { key: "consistency", label: "Consistency", render: r => scoreBadge(r.consistency, { decimals: 0 }) },
                { key: "rule_compliance", label: __('Validation rule'), render: r => scoreBadge(r.rule_compliance || 0, { decimals: 0 }) },
                { key: "reports", label: "Reports", width: "60px" },
                { key: 'alerts', label: 'Alerts', width: '60px', render: function(r) { var s = "color:var(--accent-red);font-weight:600;"; return r.alerts > 0 ? '<span style="' + s + '">' + r.alerts + '</span>' : '0'; } },
            ], rankingData, { onRowClick: (row) => showHospitalScorecard(row.id) });
        }

        // DataTable handles its own sorting via click on headers

        // ── Hospital Scorecard ───────────────────────────────────
        export function showHospitalScorecard(hospitalId) {
            // عرض التفاصيل في نافذة منبثقة (modal) داخل نفس الصفحة
            const modal = document.getElementById('detailModal');
            document.getElementById('modalTitle').textContent = __('Loading...');
            document.getElementById('modalBody').innerHTML =
                '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:3rem 1rem;gap:0.9rem;">' +
                '<span class="spinner spinner-lg"></span>' +
                '<span style="color:var(--text-muted);font-size:0.85rem;">' + __('Loading hospital details...') + '</span>' +
                '</div>';
            modal.classList.add('show');

            apiGet('/dashboard/hospital-performance/' + hospitalId).then(d => {
                const gradeColors = {A:'var(--accent-green)', B:'var(--accent-blue)', C:'var(--accent-orange)', D:'var(--accent-red)'};
                const gc = gradeColors[d.grade] || '#888';
                document.getElementById('modalTitle').innerHTML =
                    '<span class="scorecard-grade" style="background:' + gc + ';">' + d.grade + '</span>' + esc(d.name) +
                    ' <span style="font-size:0.72rem;font-weight:400;color:var(--text-muted);">\u2014 Hospital Scorecard</span>';

                const qc = d.avg_score >= 75 ? 'var(--accent-green)' : d.avg_score >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)';
                let html = '<div class="scorecard-kpi-bar">' +
                    '<div class="scorecard-kpi-item" style="border-top-color:' + qc + ';background:var(--bg-elevated);">' +
                        '<div style="font-size:0.65rem;color:var(--text-muted);text-transform:uppercase;">Quality Score</div>' +
                        '<div style="font-size:1.5rem;font-weight:700;color:' + qc + ';">' + d.avg_score + '%</div></div>' +
                    '<div class="scorecard-kpi-item"><div style="font-size:0.65rem;color:var(--text-muted);text-transform:uppercase;">' + __('Validation rule') + '</div>' +
                        '<div style="font-size:1.1rem;font-weight:600;">' + d.avg_compliance + '%</div></div>' +
                    '<div class="scorecard-kpi-item"><div style="font-size:0.65rem;color:var(--text-muted);text-transform:uppercase;">' + __('Completeness') + '</div>' +
                        '<div style="font-size:1.1rem;font-weight:600;">' + d.avg_completeness + '%</div></div>' +
                    '<div class="scorecard-kpi-item"><div style="font-size:0.65rem;color:var(--text-muted);text-transform:uppercase;">' + __('Consistency') + '</div>' +
                        '<div style="font-size:1.1rem;font-weight:600;">' + d.avg_consistency + '%</div></div>' +
                    '<div class="scorecard-kpi-item"><div style="font-size:0.65rem;color:var(--text-muted);text-transform:uppercase;">' + __('High Confidence') + '</div>' +
                        '<div style="font-size:1.1rem;font-weight:600;color:' + ((d.avg_confidence || 0) >= 60 ? 'var(--accent-green)' : (d.avg_confidence || 0) >= 40 ? 'var(--accent-orange)' : 'var(--accent-red)') + ';">' + (d.avg_confidence || 0) + '%</div></div>' +
                    '<div class="scorecard-kpi-item"><div style="font-size:0.65rem;color:var(--text-muted);text-transform:uppercase;">' + __('Alerts') + '</div>' +
                        '<div style="font-size:1.1rem;font-weight:600;color:' + (d.total_alerts > 0 ? 'var(--accent-red)' : 'var(--accent-green)') + ';">' + d.total_alerts + '</div></div>' +
                '</div>';

                html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;">' +
                    '<div class="card"><h3>Quality Score Trend</h3><canvas id="scorecardTrendChart" style="height:180px;"></canvas></div>' +
                    '<div class="card"><h3>Clinical Rates <span style="font-size:0.7rem;font-weight:400;color:var(--text-muted);">vs Peer Avg</span></h3><canvas id="scorecardRatesChart" style="height:180px;"></canvas></div>' +
                '</div>';

                html += '<div style="margin-top:1rem;"><h3>Recent Alerts</h3>';
                if (d.last_alerts && d.last_alerts.length) {
                    html += d.last_alerts.map(a => {
                        const sc = a.severity === 'CRITICAL' ? 'var(--accent-red)' : a.severity === 'HIGH' ? 'var(--accent-orange)' : 'var(--accent-yellow)';
                        return '<div class="scorecard-alert">' +
                            '<span style="width:8px;height:8px;border-radius:50%;background:' + sc + ';flex-shrink:0;"></span>' +
                            '<span style="font-weight:600;font-size:0.7rem;color:' + sc + ';">' + a.severity + '</span>' +
                            '<span style="font-size:0.75rem;">' + esc(a.rule_code) + '</span>' +
                            '<span style="color:var(--text-muted);font-size:0.7rem;">' + esc(a.details) + '</span>' +
                            '<span style="color:var(--text-muted);font-size:0.65rem;margin-left:auto;">' + a.month + '</span>' +
                        '</div>';
                    }).join('');
                } else {
                    html += '<p style="color:var(--text-muted);font-size:0.8rem;">No alerts for this hospital.</p>';
                }
                html += '</div>';

                document.getElementById('modalBody').innerHTML = html;

                if (scorecardTrendInstance) { scorecardTrendInstance.destroy(); scorecardTrendInstance = null; }
                if (scorecardRatesInstance) { scorecardRatesInstance.destroy(); scorecardRatesInstance = null; }

                const trendCtx = document.getElementById('scorecardTrendChart');
                if (trendCtx && d.quality_trend && d.quality_trend.length) {
                    scorecardTrendInstance = new Chart(trendCtx, {
                        type: 'line',
                        data: {
                            labels: d.quality_trend.map(p => p.month.slice(-2)),
                            datasets: [{
                                data: d.quality_trend.map(p => p.score),
                                borderColor: getCSSVar('--accent-teal') || '#14b8a6',
                                backgroundColor: (getCSSVar('--accent-teal') || '#14b8a6') + '1a',
                                fill: true, tension: 0.3, pointRadius: 3,
                            }]
                        },
                        options: {
                            responsive: true, resizeDelay: 200,
                            plugins: { legend: { display: false } },
                            scales: { y: { min: 0, max: 100, ticks: { callback: v => v + '%' } } }
                        }
                    });
            if (window.registerChart) window.registerChart(scorecardTrendInstance);
                }

                const ratesCtx = document.getElementById('scorecardRatesChart');
                if (ratesCtx && d.clinical_rates && d.clinical_rates.length) {
                    // Shorten long rate names and wrap them so every category is readable
                    const labels = d.clinical_rates.map(r => {
                        let name = r.rate_name.replace(' Rate', '').replace(' Ratio', '');
                        return name.length > 14 ? name.replace(/\s+/g, '\n') : name;
                    });
                    // Inline plugin: draws the numeric value above each bar so zeros
                    // are explicit and never look "missing"; null (no data) values get
                    // a gray hatched placeholder marked "N/A" instead of a bar.
                    const valueLabelPlugin = {
                        id: 'scorecardValueLabels',
                        afterDatasetsDraw(chart) {
                            const { ctx } = chart;
                            const yScale = chart.scales.y;
                            chart.data.datasets.forEach((dataset, di) => {
                                const meta = chart.getDatasetMeta(di);
                                meta.data.forEach((bar, i) => {
                                    const v = dataset.data[i];
                                    if (v === null || v === undefined) {
                                        // No data: draw a small gray hatched placeholder
                                        // instead of a bar so the category is visible.
                                        const phH = 6;
                                        ctx.save();
                                        ctx.strokeStyle = '#bdbdbd';
                                        ctx.fillStyle = 'rgba(158,158,158,0.25)';
                                        ctx.lineWidth = 1.5;
                                        ctx.setLineDash([3, 2]);
                                        ctx.beginPath();
                                        ctx.rect(bar.x - bar.width / 2 + 1, yScale.bottom - phH, bar.width - 2, phH);
                                        ctx.fill();
                                        ctx.stroke();
                                        ctx.setLineDash([]);
                                        ctx.fillStyle = '#9e9e9e';
                                        ctx.font = 'bold 8px sans-serif';
                                        ctx.textAlign = 'center';
                                        ctx.textBaseline = 'top';
                                        ctx.fillText('N/A', bar.x, yScale.bottom + 1);
                                        ctx.restore();
                                        return;
                                    }
                                    ctx.save();
                                    ctx.fillStyle = di === 0 ? '#1a237e' : '#e65100';
                                    ctx.font = 'bold 9px sans-serif';
                                    ctx.textAlign = 'center';
                                    ctx.textBaseline = 'bottom';
                                    ctx.fillText(String(v), bar.x, bar.y - 2);
                                    ctx.restore();
                                });
                            });
                        }
                    };
                    scorecardRatesInstance = new Chart(ratesCtx, {
                        type: 'bar',
                        data: {
                            labels: labels,
                            datasets: [
                                { label: 'Hospital', data: d.clinical_rates.map(r => r.value), backgroundColor: getCSSVar('--accent-teal') || '#14b8a6', borderRadius: 3, minBarLength: 3 },
                                { label: 'Peer Avg', data: d.clinical_rates.map(r => r.peer_avg ?? null), backgroundColor: getCSSVar('--accent-orange') || '#f59e0b', borderRadius: 3, minBarLength: 3 }
                            ]
                        },
                        plugins: [valueLabelPlugin],
                        options: {
                            responsive: true, resizeDelay: 200,
                            // Render instantly: zero-bar slivers + value labels must be
                            // visible immediately, and some embedded webviews never fire
                            // the animation frame that would grow the bars.
                            animation: false,
                            plugins: {
                                legend: { position: 'top', labels: { font: { size: 9 } } },
                                tooltip: {
                                    callbacks: {
                                        title: items => items.length ? d.clinical_rates[items[0].dataIndex].rate_name : '',
                                        label: item => {
                                            const v = item.parsed.y;
                                            if (v === null || v === undefined) return ' ' + item.dataset.label + ': No data';
                                            return ' ' + item.dataset.label + ': ' + v;
                                        }
                                    }
                                }
                            },
                            scales: {
                                y: { beginAtZero: true, ticks: { font: { size: 9 } } },
                                x: { ticks: { autoSkip: false, maxRotation: 45, minRotation: 0, font: { size: 9 } } }
                            }
                        }
                    });
            if (window.registerChart) window.registerChart(scorecardRatesInstance);
                }
            }).catch(e => {
                document.getElementById('modalBody').innerHTML = '<p style="color:var(--accent-red);">Error: ' + e.message + '</p>';
            });
        }

        export function closeScorecard() {
            document.getElementById('detailModal').classList.remove('show');
            // تنظيف الرسوم عند الإغلاق حتى لا تتسرب كائنات Chart المرتبطة بلوحات مفصولة
            if (scorecardTrendInstance) { scorecardTrendInstance.destroy(); scorecardTrendInstance = null; }
            if (scorecardRatesInstance) { scorecardRatesInstance.destroy(); scorecardRatesInstance = null; }
        }

        export function loadDashboard() {
            const hsel = document.getElementById('dashHospital');
            if (!hsel) return; // dashboard tab not loaded
            _saveUIState('dashboard');
            const hid = hsel.value;
            const yr = document.getElementById('dashYear').value;
            const dr = window._dashboardDateRange;
            document.getElementById('dashLoading').style.display = 'inline';

            let url = '/dashboard/overview?';
            if (hid) url += 'hospital_id=' + hid + '&';
            if (dr && dr.from) url += 'month_from=' + dr.from + '&';
            if (dr && dr.to) url += 'month_to=' + dr.to + '&';
            if (yr) url += 'year=' + yr;

            // Quality Score Trend is intentionally filter-immune: it fetches its
            // own param-less endpoint so the chart + sparkline always show every
            // analyzed month even when the KPI cards are narrowed by a range.
            const trendUrl = '/dashboard/trend';

            Promise.all([
                apiGet(url),
                apiGet(trendUrl).catch(e => { console.warn('Quality Score Trend failed to load:', e); return { quality_trend: [] }; }),
            ]).then(([data, trendData]) => {
                document.getElementById('dashHospitals').textContent = data.total_hospitals;
                document.getElementById('dashReports').textContent = data.total_reports;
                document.getElementById('dashAvgScore').textContent = data.avg_quality_score;
                document.getElementById('dashAlerts').textContent = data.total_alerts;

                // KPI cards
                renderKpiCards(hid);

                // Trend line chart
                const trendPoints = trendData.quality_trend || [];
                if (trendChartInstance) trendChartInstance.destroy();
                const trendCtx = document.getElementById('trendChart').getContext('2d');
                trendChartInstance = new Chart(trendCtx, {
                    type: 'line',
                    data: {
                        labels: trendPoints.map(d => d.month),
                        datasets: [{
                            label: __('Quality Score'),
                            data: trendPoints.map(d => d.score),
                            borderColor: getCSSVar('--accent-teal') || '#14b8a6',
                            backgroundColor: (getCSSVar('--accent-teal') || '#14b8a6') + '1a',
                            fill: true,
                            tension: 0.3,
                            pointRadius: 4,
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        resizeDelay: 200,
                        plugins: { legend: { display: false } },
                        scales: { y: { min: 0, max: 100, ticks: { callback: v => v + '%' } } }
                    }
                });
            if (window.registerChart) window.registerChart(trendChartInstance);

                // Confidence distribution (donut)
                if (confidenceChartInstance) confidenceChartInstance.destroy();
                const confData = data.confidence_distribution || {};
                const confCtx = document.getElementById('confidenceChart').getContext('2d');
                confidenceChartInstance = new Chart(confCtx, {
                    type: 'doughnut',
                    data: {
                        labels: [__('CRITICAL'), __('LOW'), __('MEDIUM'), __('HIGH')],
                        datasets: [{
                            data: [confData.CRITICAL || 0, confData.LOW || 0, confData.MEDIUM || 0, confData.HIGH || 0],
                            backgroundColor: [
                                getCSSVar('--accent-red') || '#c62828',
                                getCSSVar('--accent-orange') || '#e65100',
                                getCSSVar('--accent-yellow') || '#f9a825',
                                getCSSVar('--accent-green') || '#2e7d32'
                            ],
                            borderWidth: 0,
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        resizeDelay: 200,
                        plugins: { legend: { position: 'bottom', labels: { font: { size: 10 } } } }
                    }
                });
            if (window.registerChart) window.registerChart(confidenceChartInstance);

                // Radar chart (quality components)
                if (radarChartInstance) radarChartInstance.destroy();
                const radar = data.radar_components || {};
                const radarCtx = document.getElementById('radarChart').getContext('2d');
                radarChartInstance = new Chart(radarCtx, {
                    type: 'radar',
                    data: {
                        labels: Object.keys(radar),
                        datasets: [{
                            label: 'Score',
                            data: Object.values(radar),
                            backgroundColor: (getCSSVar('--accent-teal') || '#14b8a6') + '33',
                            borderColor: getCSSVar('--accent-teal') || '#14b8a6',
                            pointBackgroundColor: getCSSVar('--accent-teal') || '#14b8a6',
                            pointRadius: 3,
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        resizeDelay: 200,
                        scales: { r: { min: 0, max: 100, ticks: { stepSize: 20, font: { size: 9 } } } },
                        plugins: { legend: { display: false } }
                    }
                });
            if (window.registerChart) window.registerChart(radarChartInstance);

                if (trendPoints && trendPoints.length) {
                    const vals = trendPoints.map(d => d.score);
                    renderSparkline('sparkAvgScore', vals, getCSSVar('--accent-teal') || '#14b8a6');
                }

                document.getElementById('dashLoading').style.display = 'none';
                // Load heatmap
                loadHeatmap(hid);
                loadRankingTable();
            }).catch(e => {
                document.getElementById('dashLoading').style.display = 'none';
                console.error('Dashboard error:', e);
            });
        }

        window.applyDashboardFilter = function() {
            const fromEl = document.getElementById('filter-from');
            const toEl = document.getElementById('filter-to');
            const from = fromEl.value;
            const to = toEl.value;
            if (!from || !to) { toastWarning(__('Both From and To months are required.')); return; }
            if (from > to) { toastWarning(__('From month must be before To month.')); return; }
            window._dashboardDateRange = { from: from, to: to };
            loadDashboard();
        };

        window.resetDashboardFilter = function() {
            window._dashboardDateRange = null;
            document.getElementById('filter-from').value = '';
            document.getElementById('filter-to').value = '';
            loadDashboard();
        };

        function loadHeatmap(hospitalId, month) {
            let url = '/analysis/heatmap?';
            if (hospitalId) url += 'hospital_id=' + hospitalId + '&';
            if (month) url += 'month=' + month + '&';
            apiGet(url).then(hm => {
                const container = document.getElementById('heatmapContainer');
                if (!hm.data || !hm.data.length) {
                    container.innerHTML = '<div class="empty-state"><div class="empty-icon">📊</div><div class="empty-text">' + __('No data for heatmap') + '</div></div>';
                    return;
                }
                const months = hm.months;
                let html = '<table style="font-size:0.72rem;border-collapse:collapse;width:100%;"><thead><tr>' +
                    '<th style="padding:0.3rem;text-align:left;position:sticky;left:0;background:var(--bg-surface);z-index:1;">Hospital</th>';
                months.forEach(m => { html += '<th style="padding:0.3rem;text-align:center;min-width:60px;">' + m + '</th>'; });
                html += '<th style="padding:0.3rem;text-align:center;min-width:50px;">Avg</th></tr></thead><tbody>';
                hm.data.forEach(d => {
                    const vals = months.map(m => d[m]).filter(v => v !== null);
                    const avg = vals.length ? (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(1) : '--';
                    html += '<tr><td style="padding:0.2rem 0.4rem;font-weight:600;position:sticky;left:0;background:var(--bg-surface);z-index:1;">' + d.hospital + '</td>';
                    months.forEach(m => {
                        const v = d[m];
                        if (v === null) { html += '<td style="text-align:center;padding:0.2rem;background:var(--bg-surface);color:var(--text-muted);">--</td>'; return; }
                        var bg, fg;
                        if (v >= 90) { bg = '#1b5e20'; fg = '#fff'; }
                        else if (v >= 80) { bg = '#388e3c'; fg = '#fff'; }
                        else if (v >= 70) { bg = '#7cb342'; fg = '#fff'; }
                        else if (v >= 60) { bg = '#fbc02d'; fg = '#333'; }
                        else if (v >= 50) { bg = '#f57c00'; fg = '#fff'; }
                        else if (v >= 40) { bg = '#e64a19'; fg = '#fff'; }
                        else { bg = '#b71c1c'; fg = '#fff'; }
                        html += '<td style="text-align:center;padding:0.2rem;background:' + bg + ';color:' + fg + ';font-weight:600;">' + v.toFixed(1) + '</td>';
                    });
                    html += '<td style="text-align:center;padding:0.2rem;font-weight:700;">' + avg + '</td></tr>';
                });
                html += '</tbody></table>';
                container.innerHTML = html;
            }).catch(() => {
                document.getElementById('heatmapContainer').innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:1rem;font-size:0.85rem;">Heatmap unavailable.</p>';
            });
        }

        export function initDashboard() {
            const hsel = document.getElementById('dashHospital');
            if (!hsel) return; // التبويب لم يُحمَّل
            const ph = '<option value="">All Hospitals</option>';
            hsel.innerHTML = ph;
            apiGet('/hospitals/').then(data => {
                const list = data.value || data || [];
                hsel.innerHTML = ph + list.map(h => '<option value="' + h.id + '">' + h.name + '</option>').join('');
                _restoreUIState('dashboard');
                loadDashboard();
            }).catch(() => {
                _restoreUIState('dashboard');
                loadDashboard();
            });
            // قائمة السنوات مشتقة من الأشهر المتاحة (نقطة /dashboard/yoy أُزيلت)
            apiGet('/analysis/months').then(months => {
                const list = (months.months || months || []).filter(m => /^\d{4}-\d{2}$/.test(String(m)));
                const years = [...new Set(list.map(m => String(m).slice(0, 4)))].sort();
                const ysel = document.getElementById('dashYear');
                if (!ysel) return;
                const cur = ysel.value;
                ysel.innerHTML = '<option value="">All Years</option>' +
                    years.map(y => '<option value="' + y + '">' + y + '</option>').join('');
                if (cur) ysel.value = cur;
            }).catch(() => {});
        }

        export function loadAllSettings() {
            setTimeout(initCollapsibleSections, 100);
            const loadingEl = document.getElementById('settingsLoading');
            if (!loadingEl) return; // التبويب لم يُحمَّل
            loadingEl.classList.remove('hidden');
            Promise.all([
                apiGet('/config/').then(cfg => {
                    Object.keys(cfg).forEach(cat => {
                        Object.keys(cfg[cat]).forEach(key => {
                            const el = document.getElementById('cfg_' + key);
                            const valEl = document.getElementById('cfgval_' + key);
                            if (el) el.value = cfg[cat][key].value;
                            if (valEl) valEl.textContent = fmtCfgVal(key, cfg[cat][key].value);
                        });
                    });
                    updateCfgDisplay('quality');
                }).catch(() => {}),
                loadWeights(),
                loadAiSettings(),
            ]).then(() => {
                const l = document.getElementById('settingsLoading');
                if (l) l.classList.add('hidden');
                _settingsInitUX();
            });
        }

        export function saveAllSettings() {
            const wEl = document.getElementById('weight_total');
            const qEl = document.getElementById('cfgtotal_quality');
            const wTotal = wEl ? parseFloat(wEl.textContent) : 1;
            const qTotal = qEl ? parseFloat(qEl.textContent) : 1;
            if (Math.abs(wTotal - 1.0) >= 0.01 || Math.abs(qTotal - 1.0) >= 0.01) {
                const statusEl = document.getElementById('settingsStatus');
                if (statusEl) {
                    statusEl.textContent = '\u2717 ' + __('Weight totals must equal 1.0 before saving');
                    statusEl.style.color = 'var(--accent-red)';
                    setTimeout(() => { statusEl.textContent = ''; }, 4000);
                }
                const qSec = document.getElementById('settings-quality');
                const cSec = document.getElementById('settings-confidence');
                if (Math.abs(qTotal - 1.0) >= 0.01 && qSec) qSec.classList.add('settings-section-invalid');
                if (Math.abs(wTotal - 1.0) >= 0.01 && cSec) cSec.classList.add('settings-section-invalid');
                setTimeout(() => { if (qSec) qSec.classList.remove('settings-section-invalid'); if (cSec) cSec.classList.remove('settings-section-invalid'); }, 3000);
                return;
            }
            const updates = {};
            ['quality_rule_compliance', 'quality_completeness', 'quality_consistency', 'quality_outlier_penalty',
             'outlier_multiplier', 'severity_high', 'severity_medium', 'severity_low',
             'confidence_high', 'confidence_medium', 'confidence_low', 'zscore_threshold',
             'eq_tolerance', 'cs_rate_threshold', 'nvd_rate_threshold',
             'month_over_factor', 'month_under_factor', 'maternal_over_factor', 'neonatal_over_factor'
             // clinical thresholds
            ].concat([
             'clinical_cs_rate_elevated','clinical_cs_rate_high','clinical_cs_rate_critical',
             'clinical_mmr_elevated','clinical_mmr_high','clinical_mmr_critical',
             'clinical_nmr_elevated','clinical_nmr_high','clinical_nmr_critical',
             'clinical_smm_elevated','clinical_smm_high','clinical_smm_critical',
             'clinical_preterm_elevated','clinical_preterm_high','clinical_preterm_critical',
             'clinical_stillbirth_elevated','clinical_stillbirth_high','clinical_stillbirth_critical',
             'clinical_nicu_elevated','clinical_nicu_high','clinical_nicu_critical',
             'clinical_lbw_elevated','clinical_lbw_high','clinical_lbw_critical',
             'clinical_bf_elevated','clinical_bf_high','clinical_bf_critical',
             'clinical_avd_elevated','clinical_avd_high','clinical_avd_critical',
             'clinical_hemorrhage_elevated','clinical_hemorrhage_high','clinical_hemorrhage_critical',
             'clinical_hypertensive_elevated','clinical_hypertensive_high','clinical_hypertensive_critical',
             'clinical_high_risk_elevated','clinical_high_risk_high','clinical_high_risk_critical',
             'clinical_adolescent_elevated','clinical_adolescent_high','clinical_adolescent_critical',
             'clinical_hysterectomy_elevated','clinical_hysterectomy_high','clinical_hysterectomy_critical'
             // risk
            ]).concat([
             'risk_peer_multiplier_high','risk_peer_multiplier_critical',
             'risk_high_risk_rate_moderate','risk_high_risk_rate_high','risk_high_risk_rate_critical',
             'risk_adolescent_moderate','risk_adolescent_high','risk_adolescent_critical',
             'risk_emergency_cs_moderate','risk_emergency_cs_high','risk_emergency_cs_critical',
             'risk_infacility_moderate','risk_infacility_high','risk_infacility_critical'
             // trends
            ]).concat([
             'trend_slope_stable','trend_slope_low','trend_slope_moderate','trend_slope_high',
             'trend_r_squared','trend_finding_slope','trend_finding_consecutive',
             'trend_finding_deviation','trend_finding_cv','trend_finding_r_squared'
             // rates
            ]).concat([
             'rate_cs_benchmark','rate_mmr_benchmark','rate_nmr_benchmark',
             'rate_preterm_benchmark','rate_smm_benchmark','rate_stillbirth_benchmark','rate_nicu_benchmark'
             // ml
            ]).concat([
             'ml_enabled', 'ml_clustering_enabled', 'ml_clustering_min_k', 'ml_clustering_max_k',
             'ml_anomaly_enabled', 'ml_anomaly_contamination',
             'ml_pca_enabled', 'ml_pca_variance_threshold'
            ]).forEach(key => {
                const el = document.getElementById('cfg_' + key);
                if (el) updates[key] = parseFloat(el.value);
            });
            apiPut('/config/', updates).then(() => {
                const weights = {
                    rule_compliance: parseFloat(document.getElementById('weight_rule_compliance').value),
                    historical: parseFloat(document.getElementById('weight_historical').value),
                    cross_hospital: parseFloat(document.getElementById('weight_cross_hospital').value),
                    trend: parseFloat(document.getElementById('weight_trend').value),
                    completeness: parseFloat(document.getElementById('weight_completeness').value),
                };
                const wTotal = Object.values(weights).reduce((a, b) => a + b, 0);
                if (Math.abs(wTotal - 1.0) < 0.01) {
                    return apiPut('/confidence/weights', weights);
                }
                return Promise.resolve();
            }).then(() => {
                document.getElementById('settingsStatus').textContent = '\u2713 All settings saved';
                document.getElementById('settingsStatus').style.color = 'var(--accent-green)';
                setTimeout(() => { document.getElementById('settingsStatus').textContent = ''; }, 3000);
                _settingsSnapshot();
                _settingsRefreshDirtyUI();
            }).catch(e => {
                document.getElementById('settingsStatus').textContent = '\u2717 Error: ' + e.message;
                document.getElementById('settingsStatus').style.color = 'var(--accent-red)';
            });
        }

        function _setSettingsStatus(text, color) {
            const el = document.getElementById('settingsStatus');
            if (el) { el.textContent = text; el.style.color = color; }
        }

        function _pollTask(taskId, onProgress) {
            let tries = 0;
            return new Promise((resolve, reject) => {
                const timer = setInterval(() => {
                    tries++;
                    if (tries > 300) { clearInterval(timer); reject(new Error('Re-analysis timed out')); return; }
                    apiGet('/tasks/' + taskId).then(task => {
                        if (task.status === 'error') { clearInterval(timer); reject(new Error(task.error || 'Re-analysis failed')); return; }
                        if (task.status === 'done') { clearInterval(timer); resolve(task); return; }
                        if (onProgress) onProgress(task.progress || 0);
                    }).catch(err => { clearInterval(timer); reject(err); });
                }, 2000);
            });
        }

        export function reanalyzeAll(btn) {
            const originalText = btn ? btn.textContent : '';
            if (btn) { btn.textContent = '...'; btn.disabled = true; }
            _setSettingsStatus('Recalculating completeness...', 'var(--accent-blue)');
            showLoader('Recalculating completeness...');
            apiPost('/dashboard/recalculate-completeness')
                .then(() => {
                    _setSettingsStatus('Re-analyzing all hospitals...', 'var(--accent-blue)');
                    showLoader('Re-analyzing all hospitals...');
                    return apiPost('/analysis/reanalyze-all?force=true');
                })
                .then(data => {
                    if (!data || !data.task_id) throw new Error(data && data.message || 'Re-analysis did not start');
                    return _pollTask(data.task_id, progress => _setSettingsStatus('Re-analyzing all hospitals... ' + progress + '%', 'var(--accent-blue)'));
                })
                .then(() => {
                    _setSettingsStatus('\u2713 Re-analysis complete. All hospitals updated.', 'var(--accent-green)');
                    if (typeof clearApiCache === 'function') clearApiCache();
                    if (typeof switchTab === 'function') switchTab('dashboard');
                })
                .catch(e => {
                    _setSettingsStatus('\u2717 Error: ' + e.message, 'var(--accent-red)');
                })
                .finally(() => {
                    hideLoader();
                    if (btn) { btn.textContent = originalText; btn.disabled = false; }
                });
        }

        // قائمة النماذج المتاحة لكل مزوّد (تُبنى القائمة المنسدلة منها)
        const _AI_MODEL_OPTIONS = {
            gemini: [
                { value: 'gemini-3.5-flash-lite', label: 'Gemini 3.5 Flash-Lite (recommended free)' },
                { value: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash' },
                { value: 'gemini-3.7-flash', label: 'Gemini 3.7 Flash' },
            ],
            deepseek: [
                { value: 'deepseek-chat', label: 'DeepSeek Chat' },
                { value: 'deepseek-reasoner', label: 'DeepSeek Reasoner' },
            ],
            minimax: [
                { value: 'minimax-abab5.5s-chat', label: 'MiniMax abab5.5s' },
            ],
            kimi: [
                { value: 'moonshot-v1-8k', label: 'Kimi moonshot-v1-8k' },
                { value: 'moonshot-v1-32k', label: 'Kimi moonshot-v1-32k' },
            ],
            openai: [
                { value: 'gpt-4o-mini', label: 'OpenAI GPT-4o Mini' },
                { value: 'gpt-4o', label: 'OpenAI GPT-4o' },
            ],
        };
        const _AI_MODEL_DEFAULTS = {
            gemini: 'gemini-3.5-flash-lite',
            deepseek: 'deepseek-chat',
            minimax: 'minimax-abab5.5s-chat',
            kimi: 'moonshot-v1-8k',
            openai: 'gpt-4o-mini',
        };

        function buildAiModelSelect(currentValue) {
            const sel = document.getElementById('ai_model');
            if (!sel) return;
            let html = '';
            for (const [provider, opts] of Object.entries(_AI_MODEL_OPTIONS)) {
                html += '<optgroup label="' + provider + '">' +
                    opts.map(o => '<option value="' + esc(o.value) + '">' + esc(o.label) + '</option>').join('') +
                    '</optgroup>';
            }
            sel.innerHTML = html;
            if (currentValue && !Array.from(sel.options).some(o => o.value === currentValue)) {
                const opt = document.createElement('option');
                opt.value = currentValue;
                opt.textContent = currentValue + ' (custom)';
                sel.appendChild(opt);
            }
            if (currentValue) sel.value = currentValue;
        }

        function ensureAiModelForProvider(provider) {
            const sel = document.getElementById('ai_model');
            if (!sel) return;
            const current = sel.value;
            const providerModels = _AI_MODEL_OPTIONS[provider] || _AI_MODEL_OPTIONS.gemini;
            const belongsToProvider = providerModels.some(o => o.value === current);
            const belongsToAny = Object.values(_AI_MODEL_OPTIONS).some(list => list.some(o => o.value === current));
            if (!belongsToProvider && belongsToAny) {
                // المستخدم بدّل المزوّد: اختر النموذج الافتراضي للمزوّد الجديد
                sel.value = _AI_MODEL_DEFAULTS[provider] || _AI_MODEL_DEFAULTS.gemini;
            }
            // قيمة مخصصة (غير موجودة في أي قائمة) تُبقى كما هي
        }

        export function loadAiSettings() {
            return authFetch(API() + '/config/ai/settings').then(r => r.json()).then(cfg => {
                document.getElementById('ai_enabled').value = cfg.ai_enabled || 'true';
                document.getElementById('ai_provider').value = cfg.ai_provider || 'gemini';
                document.getElementById('ai_api_key').value = cfg.ai_api_key || '';
                const provider = document.getElementById('ai_provider').value;
                buildAiModelSelect(cfg.ai_model || _AI_MODEL_DEFAULTS[provider] || 'gemini-3.5-flash-lite');
                document.getElementById('ai_api_url').value = cfg.ai_api_url || '';
                document.getElementById('ai_max_recommendations').value = cfg.ai_max_recommendations || 8;
                document.getElementById('ai_timeout').value = cfg.ai_timeout || 30;
                onAiProviderChange();
            }).catch(() => {});
        }

        export function saveAiSettings() {
            const updates = {
                ai_enabled: document.getElementById('ai_enabled').value,
                ai_provider: document.getElementById('ai_provider').value,
                ai_api_key: document.getElementById('ai_api_key').value,
                ai_model: document.getElementById('ai_model').value,
                ai_api_url: document.getElementById('ai_api_url').value,
                ai_max_recommendations: document.getElementById('ai_max_recommendations').value,
                ai_timeout: document.getElementById('ai_timeout').value,
            };
            const status = document.getElementById('aiSaveStatus');
            status.textContent = 'Saving...';
            status.style.color = 'var(--accent-blue)';
            authFetch(API() + '/config/ai/settings', {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(updates),
            }).then(r => r.json()).then(() => {
                status.textContent = '\u2713 Saved. AI config will be used on next analysis.';
                status.style.color = 'var(--accent-green)';
                setTimeout(() => { status.textContent = ''; }, 4000);
            }).catch(e => {
                status.textContent = '\u2717 Error: ' + e.message;
                status.style.color = 'var(--accent-red)';
            });
        }

        export function onAiProviderChange() {
            const provider = document.getElementById('ai_provider').value;
            const urlRow = document.getElementById('ai_api_url_row');
            const urlInput = document.getElementById('ai_api_url');
            if (provider === 'gemini') {
                urlRow.style.display = 'none';
            } else if (provider === 'deepseek') {
                urlRow.style.display = 'none';
                if (!urlInput.value) urlInput.value = 'https://api.deepseek.com/v1/chat/completions';
            } else if (provider === 'minimax') {
                urlRow.style.display = '';
            } else if (provider === 'kimi') {
                urlRow.style.display = '';
                if (!urlInput.value) urlInput.value = 'https://api.moonshot.cn/v1/chat/completions';
            } else {
                urlRow.style.display = '';
                if (!urlInput.value) urlInput.value = 'https://api.openai.com/v1/chat/completions';
            }
            ensureAiModelForProvider(provider);
        }

        // ── Rules Manager filters (instant, client-side) ───────────────
        const _RULES_FILTER_IDS = ['rulesCategoryFilter', 'rulesTypeFilter', 'rulesSeverityFilter', 'rulesEnabledFilter'];

        function _persistRulesFilterState() {
            try {
                _RULES_FILTER_IDS.forEach(id => {
                    const el = document.getElementById(id);
                    if (el) localStorage.setItem(id, el.value);
                });
            } catch (e) { /* storage unavailable */ }
        }

        export function loadRulesManager() {
            if (!document.getElementById('rulesTbody')) return; // التبويب لم يُحمَّل بعد
            // App-owned UI state: on the FIRST load of the session, restore
            // each filter's stored value so Chrome's form-restore cannot
            // silently narrow the list (autocomplete="off" does not stop it).
            // On later calls (dropdown onchange fires loadRulesManager()) the
            // DOM already holds the user's fresh selection — re-restoring the
            // stored value here would revert the user's pick before the query
            // is built, which made the filters appear dead.
            if (!window._rulesFiltersRestored) {
                window._rulesFiltersRestored = true;
                try {
                    _RULES_FILTER_IDS.forEach(id => {
                        const el = document.getElementById(id);
                        if (!el) return;
                        const saved = localStorage.getItem(id) || '';
                        const hasOption = Array.prototype.some.call(el.options, o => o.value === saved);
                        if (hasOption) el.value = saved;
                    });
                } catch (e) { /* storage unavailable — defaults apply */ }
            }
            // Persist whatever the dropdowns currently hold (user selection or
            // the once-restored app value) so the state is durable.
            _persistRulesFilterState();
            // Filters and search apply instantly CLIENT-SIDE in
            // renderRulesManager — this loader always fetches the FULL rule
            // list, so dropdown changes never need a server round-trip.
            const url = API() + '/rules/';
            const tbody = document.getElementById('rulesTbody');
            document.getElementById('rulesLoading').classList.remove('hidden');
            tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;padding:1.5rem;color:var(--text-muted);">Loading rules...</td></tr>';
            Promise.all([
                authFetch(url).then(r => {
                    if (!r.ok) throw new Error('HTTP ' + r.status + ' loading rules');
                    return r.json();
                }),
                authFetch(_forceRulesImpactRefresh
                    ? API() + '/rules/impact?refresh=true'
                    : API() + '/rules/impact').then(r => r.json()).catch(() => []),
            ]).then(([data, impact]) => {
                _forceRulesImpactRefresh = false;
                document.getElementById('rulesLoading').classList.add('hidden');
                // Restore the app-owned search value over anything the browser
                // form-restored into the box while loading. Legacy junk (a
                // username an older build persisted) is scrubbed here too.
                const searchBox = document.getElementById('rulesSearchInput');
                if (searchBox) {
                    let savedSearch = '';
                    try { savedSearch = localStorage.getItem('rulesSearch') || ''; } catch (e) {}
                    if (_rulesSearchIsLoginJunk(savedSearch)) savedSearch = '';
                    window._rulesSearchAppState = savedSearch;
                    window._rulesSearchTouched = false; // restored, not typed
                    if (searchBox.value !== savedSearch) searchBox.value = savedSearch;
                    // Autofill can land AFTER this restore (browsers run their
                    // autofill scan when the input enters the DOM — it beats any
                    // synchronous clear). Re-check a few times so the junk never
                    // survives the first seconds on screen.
                    [600, 2000].forEach(function(delay) {
                        setTimeout(function() {
                            const sb = document.getElementById('rulesSearchInput');
                            if (sb && _rulesSearchIsLoginJunk(sb.value)) {
                                sb.value = window._rulesSearchAppState || '';
                            }
                        }, delay);
                    });
                }
                if (!Array.isArray(data)) throw new Error('Unexpected response from /rules');
                rulesManagerData = data;
                _rulesImpactMap = {};
                if (Array.isArray(impact)) {
                    impact.forEach(imp => { _rulesImpactMap[imp.code] = imp; });
                    const scope = impact.length ? impact[0].month : null;
                    _updateRulesImpactHeader(scope);
                }
                // Always display sorted by code
                rulesManagerData.sort(function(a, b) {
                    return a.code < b.code ? -1 : a.code > b.code ? 1 : 0;
                });
                _rulesDirty = false;
                renderRulesManager();
                _updateRulesSaveButton();
            }).catch(e => {
                document.getElementById('rulesLoading').classList.add('hidden');
                tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#a00;">Error: ' + e.message + '</td></tr>';
            });
        }

        window.toggleHospital = function(hospitalId, isActive) {
            apiPut('/hospitals/' + hospitalId + '/toggle-active', {}).then(() => {
                clearApiCache();
                if (typeof loadDashboard === 'function') loadDashboard();
                // Refresh hospital dropdowns in other visible tabs
                if (document.getElementById('dashHospital') && document.getElementById('dashHospital').offsetParent !== null) {
                    initDashboard();
                }
                if (document.getElementById('rcHospital') && document.getElementById('rcHospital').offsetParent !== null) {
                    initRootCause();
                }
            }).catch(e => {
                toastError('Error: ' + e.message);
            });
        };

        // ── Month Toggle Settings ──────────────────────────────────────────

        function renderRulesManager() {
            document.getElementById('rulesManagerCount').textContent = rulesManagerData.length + ' ' + __('rule(s)');
            // App-owned search state: a value that appears in the box without
            // user input is browser autofill (e.g. the login username) — revert
            // it instead of filtering or persisting it. Persist only the
            // app-owned value so junk can never enshrine itself in storage.
            const _rsBox = document.getElementById('rulesSearchInput');
            if (_rsBox) {
                const _rsVal = _rsBox.value || '';
                if (_rsVal !== window._rulesSearchAppState) {
                    if (!window._rulesSearchTouched || _rulesSearchIsLoginJunk(_rsVal)) {
                        _rsBox.value = window._rulesSearchAppState; // revert autofill junk
                    } else {
                        window._rulesSearchAppState = _rsVal; // user-edited without an input event (e.g. context-menu paste)
                    }
                }
            }
            try { localStorage.setItem('rulesSearch', window._rulesSearchAppState || ''); } catch (e) {}
            const filtered = document.getElementById('rulesTbody');
            if (!filtered) return;
            if (!rulesManagerData.length) {
                filtered.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:2rem;">No rules found.</td></tr>';
                return;
            }
            const searchBox = document.getElementById('rulesSearchInput');
            const q = (searchBox ? searchBox.value : '').trim().toLowerCase();
            const typeColors = {'LOGIC': 'var(--accent-blue)', 'CLINICAL': 'var(--accent-purple)', 'BENCHMARK': 'var(--accent-orange)', 'DATA_QUALITY': 'var(--accent-red)'};
            const sevClass = {'CRITICAL': 'badge-critical', 'HIGH': 'badge-high', 'MEDIUM': 'badge-medium', 'LOW': 'badge-low'};

            let visible = rulesManagerData;
            if (q) {
                visible = rulesManagerData.filter(r =>
                    (r.code || '').toLowerCase().includes(q) ||
                    (r.name || '').toLowerCase().includes(q) ||
                    (r.description || '').toLowerCase().includes(q) ||
                    (r.category || '').toLowerCase().includes(q) ||
                    (r.expression_type || '').toLowerCase().includes(q)
                );
            }
            // Dropdown filters apply instantly client-side — no refetch.
            const catF = document.getElementById('rulesCategoryFilter') ? document.getElementById('rulesCategoryFilter').value : '';
            const typeF = document.getElementById('rulesTypeFilter') ? document.getElementById('rulesTypeFilter').value : '';
            const sevF = document.getElementById('rulesSeverityFilter') ? document.getElementById('rulesSeverityFilter').value : '';
            const enF = document.getElementById('rulesEnabledFilter') ? document.getElementById('rulesEnabledFilter').value : '';
            if (catF) visible = visible.filter(r => (r.category || '') === catF);
            if (typeF) visible = visible.filter(r => (r.rule_type || '') === typeF);
            if (sevF) visible = visible.filter(r => (r.severity || '') === sevF);
            if (enF) visible = visible.filter(r => String(r.enabled) === enF);

            // Flat list sorted by rule code — categories live in the
            // Category filter dropdown, not as table sections.
            const sevRank = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };
            visible = visible.slice().sort(function(a, b) {
                if (_rulesSortCol === 'severity') {
                    const ra = sevRank[a.severity] !== undefined ? sevRank[a.severity] : 9;
                    const rb = sevRank[b.severity] !== undefined ? sevRank[b.severity] : 9;
                    const d = ra - rb;
                    return _rulesSortAsc ? d : -d;
                }
                if (_rulesSortCol === 'impact') {
                    const fa = (_rulesImpactMap[a.code] && _rulesImpactMap[a.code].hospitals_affected || []).length;
                    const fb = (_rulesImpactMap[b.code] && _rulesImpactMap[b.code].hospitals_affected || []).length;
                    const d = fa - fb;
                    return _rulesSortAsc ? d : -d;
                }
                // Default (and "code"): rule code asc/desc
                const ca = a.code || '', cb = b.code || '';
                const d = ca < cb ? -1 : ca > cb ? 1 : 0;
                return _rulesSortAsc ? d : -d;
            });

            let html = '';
            visible.forEach((r, idx) => {
                {
                    const cat = r.category || 'UNCATEGORIZED';
                    const tc = typeColors[r.rule_type] || '#666';
                    const typeB = '<span class="badge" style="background:'+tc+'22;color:'+tc+';border:1px solid '+tc+'44;">'+r.rule_type+'</span>';
                    const sevB = '<span class="badge ' + (sevClass[r.severity] || 'badge-low') + '">' + r.severity + '</span>';
                    const enabledIcon = r.enabled
                        ? '<span class="tree-toggle on" style="cursor:pointer;" title="Click to disable">✓</span>'
                        : '<span class="tree-toggle off" style="cursor:pointer;" title="Click to enable">✗</span>';
                    const imp = _rulesImpactMap[r.code];
                    let impactCell = '<span style="color:var(--text-muted);">--</span>';
                    if (imp) {
                        const affected = imp.hospitals_affected || [];
                        if (affected.length) {
                            const f = affected.length;
                            const fColor = f === 0 ? 'var(--accent-green)' : f >= 20 ? 'var(--accent-red)' : 'var(--accent-orange)';
                            impactCell = '<span style="color:' + fColor + ';font-weight:600;white-space:nowrap;" title="' + f + ' hospital(s) fail this rule right now (month ' + (imp.month || '?') + ')">' + f + '</span>';
                        } else {
                            impactCell = '<span style="color:var(--accent-green);font-weight:600;" title="No failures recorded">0</span>';
                        }
                    }
                    html += '<tr class="rule-row" data-id="' + r.id + '" data-code="' + esc(r.code) + '" data-cat="' + esc(cat) + '" style="background:var(--bg-surface);cursor:pointer;">' +
                        '<td><code style="white-space:nowrap;">' + esc(r.code) + '</code></td>' +
                        '<td style="max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="' + esc(r.name) + '">' + esc(r.name) + '</td>' +
                        '<td>' + typeB + '</td>' +
                        '<td style="white-space:nowrap;">' + sevB + '</td>' +
                        '<td style="font-size:0.75rem;color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="' + esc(r.category) + '">' + esc(r.category) + '</td>' +
                        '<td style="font-size:0.72rem;font-family:Consolas,monospace;color:var(--text-muted);max-width:280px;" title="' + esc(exprTypeLabel(r.expression_type)) + '">' + esc(exprTypeLabel(r.expression_type)) + '</td>' +
                        '<td style="text-align:center;font-size:0.7rem;white-space:nowrap;">' + impactCell + '</td>' +
                        '<td style="text-align:center;white-space:nowrap;" class="rule-toggle-cell" data-id="' + r.id + '">' + enabledIcon + '</td>' +
                        '<td style="white-space:nowrap;"><button class="btn btn-sm btn-outline" onclick="openRuleModal(' + r.id + ')" style="font-size:0.65rem;padding:0.15rem 0.4rem;">Edit</button> <button class="btn btn-sm btn-outline" onclick="deleteRule(' + r.id + ',\'' + esc(r.code) + '\')" style="font-size:0.65rem;padding:0.15rem 0.4rem;color:var(--accent-red);border-color:#ef5350;">Del</button> <button class="btn btn-sm btn-outline" onclick="_testRuleById(' + r.id + ')" style="font-size:0.65rem;padding:0.15rem 0.4rem;color:var(--accent-blue);border-color:var(--accent-blue);">Test</button> <button class="btn btn-sm btn-outline" onclick="showRuleHistory(' + r.id + ')" style="font-size:0.65rem;padding:0.15rem 0.4rem;color:var(--text-secondary);">' + __('History') + '</button></td>' +
                        '</tr>';
                }
            });
            filtered.innerHTML = html;
            // Row click opens the details drawer. Toggle cell stops propagation,
            // and clicks on the action buttons (Edit/Del/Test/History) are ignored
            // here: they open their own dialogs, and letting the click bubble to
            // the row opened the drawer BEHIND the dialog — the "Edit opens two
            // modals plus a side menu" confusion.
            filtered.querySelectorAll('.rule-row').forEach(row => {
                row.addEventListener('click', function(e) {
                    if (e.target.closest('button')) return;
                    window.openRuleDrawer(parseInt(this.dataset.id, 10));
                });
            });
            document.getElementById('rulesManagerFilteredCount').textContent = visible.length + ' shown' + (q ? ' (search: "' + esc(q) + '")' : '');
            // Sort indicators on the sortable headers (matches th.sort-asc/desc styles)
            document.querySelectorAll('#rulesTable thead th.sortable').forEach(th => {
                th.classList.remove('sort-asc', 'sort-desc');
                if (th.dataset.col === _rulesSortCol) th.classList.add(_rulesSortAsc ? 'sort-asc' : 'sort-desc');
            });
            // Show bulk buttons only when there is something to bulk-toggle
            const bulkOn = document.getElementById('rulesBulkEnableBtn');
            const bulkOff = document.getElementById('rulesBulkDisableBtn');
            if (bulkOn) bulkOn.style.display = visible.length ? '' : 'none';
            if (bulkOff) bulkOff.style.display = visible.length ? '' : 'none';
            // Nothing matched: say so. Distinguish search misses (offer the
            // one-click clear) from filter misses (the dropdowns themselves).
            if (!visible.length) {
                filtered.innerHTML = q
                    ? '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:1.5rem;">No rules match "' + esc(q) + '". <a href="#" onclick="clearRulesSearch();return false;" style="color:var(--accent-blue);">Clear search</a></td></tr>'
                    : '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:1.5rem;">No rules match the current filters.</td></tr>';
            }

            // Wire toggle clicks
            filtered.querySelectorAll('.rule-toggle-cell').forEach(cell => {
                cell.addEventListener('click', function(e) {
                    e.stopPropagation();
                    const ruleId = this.dataset.id;
                    const toggleEl = this.querySelector('.tree-toggle');
                    if (toggleEl.classList.contains('loading')) return;
                    const rule = rulesManagerData.find(x => x.id == ruleId);
                    if (!rule) return;
                    // Local-only toggle: flip the in-memory state and mark dirty.
                    // Nothing reaches the backend until Save.
                    rule.enabled = !rule.enabled;
                    toggleEl.textContent = rule.enabled ? '✓' : '✗';
                    toggleEl.className = 'tree-toggle ' + (rule.enabled ? 'on' : 'off');
                    toggleEl.title = rule.enabled ? 'Click to disable' : 'Click to enable';
                    _rulesDirty = true;
                    _updateRulesSaveButton();
                });
            });

        }

        // Error-surfacing wrapper — a throw inside renderRulesManager leaves the
        // tbody empty with headers intact (the "disappeared rules" symptom).
        // Surface the real error on the page and in the console instead.
        const _renderRulesManagerRaw = renderRulesManager;
        renderRulesManager = function() {
            try {
                _renderRulesManagerRaw();
            } catch (e) {
                const tbody = document.getElementById('rulesTbody');
                if (tbody) tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--accent-red);padding:1.5rem;">⚠ Render error: ' + esc(String(e && e.message || e)) + '</td></tr>';
                console.error('renderRulesManager failed:', e);
            }
        };

        // Search box oninput — fired by typing AND by browser autofill (which
        // dispatches input events). Credential-like values are autofill junk:
        // drop them instead of filtering/persisting the username.
        window.onRulesSearch = function() {
            const box = document.getElementById('rulesSearchInput');
            const v = box ? (box.value || '') : '';
            if (_rulesSearchIsLoginJunk(v)) {
                if (box) box.value = window._rulesSearchAppState || '';
                return;
            }
            window._rulesSearchTouched = true;
            window._rulesSearchAppState = v;
            renderRulesManager();
        };

        // One-click clear of the search box (used by the no-match row link)
        window.clearRulesSearch = function() {
            const searchBox = document.getElementById('rulesSearchInput');
            if (searchBox) searchBox.value = '';
            window._rulesSearchAppState = '';
            window._rulesSearchTouched = false;
            try { localStorage.setItem('rulesSearch', ''); } catch (e) {}
            renderRulesManager();
        };

        // Dropdown change: persist the selection and re-render instantly —
        // deliberately NOT loadRulesManager(), which would refetch from the
        // server. Filtering happens client-side against the loaded list.
        window.onRulesFilterChange = function() {
            _persistRulesFilterState();
            renderRulesManager();
        };

        // ── Rule details drawer ───────────────────────────────────
        // Mirror of the backend's _get_rule_ref_codes_from_expr so the drawer
        // can show referenced indicators even without an impact entry.
        function _drawerRefCodes(expr, params) {
            if (["ge", "eq", "gt", "ge_factor"].indexOf(expr) !== -1) {
                return [params.parent].concat(params.children || []).filter(Boolean);
            }
            if (["le", "le_sum", "lt"].indexOf(expr) !== -1) {
                return (params.parent ? [params.child, params.parent] : [params.child]).filter(Boolean);
            }
            if (["benchmark_rate", "benchmark_low_rate", "cross_hospital_rate"].indexOf(expr) !== -1) {
                return [params.num_code, params.den_code].filter(Boolean);
            }
            if (["month_over", "month_under", "missing"].indexOf(expr) !== -1) {
                return [params.code].filter(Boolean);
            }
            if (["neg_check", "decimal_check"].indexOf(expr) !== -1) return params.codes || [];
            if (expr === "all_zero") return ["2", "3", "4", "5", "6", "7", "8", "10", "11", "16", "17"];
            if (expr === "formula") {
                const codes = (String(params.formula || "").match(/\{([^}]+)\}/g) || []).map(c => c.slice(1, -1));
                return codes.concat(params.target ? [params.target] : []).filter(Boolean);
            }
            return [];
        }

        // Human-readable param rows per expression type (names mirror the
        // Expression Types Reference table).
        function _drawerParamRows(expr, params) {
            const codeName = function(c) { return esc(c); };
            const childrenList = function(list) {
                return (list || []).map(c => '<span class="rule-ref-chip">' + esc(c) + '</span>').join(' ') || '<em>' + __('None') + '</em>';
            };
            const rows = [];
            const row = function(label, valueHtml) {
                rows.push('<dt>' + __(label) + '</dt><dd>' + valueHtml + '</dd>');
            };
            if (["ge", "gt", "eq"].indexOf(expr) !== -1) {
                row("Parent", codeName(params.parent)); row("Children", childrenList(params.children));
            } else if (expr === "ge_factor") {
                row("Parent", codeName(params.parent)); row("Children", childrenList(params.children));
                row("Factor", esc(params.factor));
            } else if (["le", "lt"].indexOf(expr) !== -1) {
                row("Child", codeName(params.child)); row("Parent", codeName(params.parent));
            } else if (expr === "le_sum") {
                row("Child", codeName(params.child)); row("Children", childrenList(params.children));
            } else if (["benchmark_rate", "benchmark_low_rate"].indexOf(expr) !== -1) {
                row("Numerator", codeName(params.num_code)); row("Denominator", codeName(params.den_code));
                row("Threshold", esc(params.threshold) + '%');
            } else if (expr === "cross_hospital_rate") {
                row("Numerator", codeName(params.num_code)); row("Denominator", codeName(params.den_code));
                row("Z-Threshold", esc(params.z_threshold));
            } else if (["month_over", "month_under"].indexOf(expr) !== -1) {
                row("Indicator", codeName(params.code)); row("Factor", esc(params.factor));
            } else if (["neg_check", "decimal_check", "all_zero"].indexOf(expr) !== -1) {
                row("Codes", childrenList(params.codes));
            } else if (expr === "missing") {
                row("Indicator", codeName(params.code));
            } else if (expr === "formula") {
                row("Formula", '<span class="rule-ref-chip" style="font-family:Consolas,monospace;">' + esc(params.formula) + '</span>');
                row("Target", codeName(params.target));
                row("Operator", esc(params.op || '='));
            } else {
                return null; // unknown type → raw JSON fallback
            }
            return '<dl class="rule-drawer-meta" style="margin-bottom:0;">' + rows.join('') + '</dl>';
        }

        window.openRuleDrawer = function(ruleId) {
            const rule = rulesManagerData.find(x => x.id == ruleId);
            if (!rule) return;
            const drawer = document.getElementById('ruleDrawer');
            const overlay = document.getElementById('ruleDrawerOverlay');
            const titleEl = document.getElementById('ruleDrawerTitle');
            const bodyEl = document.getElementById('ruleDrawerBody');
            if (!drawer || !overlay || !titleEl || !bodyEl) return;

            let params = {};
            try { params = JSON.parse(rule.params || '{}'); } catch (e) { params = {}; }
            const imp = _rulesImpactMap[rule.code] || {};
            const typeColors = { LOGIC: 'var(--accent-blue)', CLINICAL: 'var(--accent-purple)', BENCHMARK: 'var(--accent-orange)', DATA_QUALITY: 'var(--accent-red)' };
            const tc = typeColors[rule.rule_type] || '#666';
            const sevClass = { CRITICAL: 'badge-critical', HIGH: 'badge-high', MEDIUM: 'badge-medium', LOW: 'badge-low' };

            // Referenced indicator names: prefer the server-computed impact map
            // (code → name parity with the analysis engine), fall back to codes.
            const refNames = {};
            (imp.ref_codes || []).forEach((c, i) => { refNames[c] = (imp.ref_names || [])[i] || c; });
            const refCodes = _drawerRefCodes(rule.expression_type, params);
            const refChips = refCodes.length
                ? refCodes.map(c => '<span class="rule-ref-chip" title="' + esc(refNames[c] || c) + '">' + esc(c) + (refNames[c] && refNames[c] !== c ? ' — ' + esc(refNames[c]) : '') + '</span>').join(' ')
                : '<em style="color:var(--text-muted);">' + __('None') + '</em>';

            const paramHtml = _drawerParamRows(rule.expression_type, params);
            let rawJson = '';
            try { rawJson = JSON.stringify(JSON.parse(rule.params || '{}'), null, 2); } catch (e) { rawJson = rule.params || '{}'; }

            const affected = imp.hospitals_affected || [];
            let affectedHtml;
            if (!affected.length) {
                affectedHtml = '<em style="color:var(--text-muted);">' + __('No hospitals affected in the latest month.') + '</em>';
            } else {
                affectedHtml = affected.slice(0, 50).map(h =>
                    '<div style="padding:2px 0;border-bottom:1px solid var(--border-default);" title="' + esc(h.details || '') + '">' +
                    '<strong style="color:var(--text-primary);">' + esc(h.name || ('#' + h.id)) + '</strong>' +
                    (h.details ? '<div style="font-size:0.72rem;color:var(--text-muted);">' + esc(h.details) + '</div>' : '') +
                    '</div>'
                ).join('') + (affected.length > 50 ? '<div style="color:var(--text-muted);padding:0.25rem 0;">+ ' + (affected.length - 50) + ' ' + __('more') + '</div>' : '');
            }

            titleEl.innerHTML = '<code>' + esc(rule.code) + '</code> — ' + esc(rule.name);
            bodyEl.innerHTML =
                '<div style="display:flex;gap:0.4rem;align-items:center;flex-wrap:wrap;margin-bottom:0.7rem;">' +
                '<span class="badge" style="background:' + tc + '22;color:' + tc + ';border:1px solid ' + tc + '44;">' + esc(rule.rule_type) + '</span>' +
                '<span class="badge ' + (sevClass[rule.severity] || 'badge-low') + '">' + esc(rule.severity) + '</span>' +
                '<span class="rule-ref-chip">' + esc(rule.category) + '</span>' +
                '<span class="badge" style="background:' + (rule.enabled ? 'var(--accent-green)22' : 'var(--accent-red)22') + ';color:' + (rule.enabled ? 'var(--accent-green)' : 'var(--accent-red)') + ';border:1px solid ' + (rule.enabled ? 'var(--accent-green)44' : 'var(--accent-red)44') + '">' + (rule.enabled ? __('Enabled') : __('Disabled')) + '</span>' +
                '</div>' +
                (rule.description ? '<p style="margin:0 0 0.7rem 0;font-size:0.78rem;color:var(--text-secondary);">' + esc(rule.description) + '</p>' : '') +
                '<div class="rule-drawer-section"><h3>' + __('Expression') + '</h3><div>' + esc(exprTypeLabel(rule.expression_type)) + '</div></div>' +
                '<div class="rule-drawer-section"><h3>' + __('Parameters') + '</h3>' +
                (paramHtml || '<div class="rule-drawer-params">' + esc(rawJson) + '</div>') +
                '<details style="margin-top:0.4rem;"><summary style="cursor:pointer;font-size:0.72rem;color:var(--text-muted);">' + __('Raw params') + '</summary>' +
                '<div class="rule-drawer-params" style="margin-top:0.3rem;">' + esc(rawJson) + '</div></details></div>' +
                '<div class="rule-drawer-section"><h3>' + __('Referenced indicators') + '</h3><div>' + refChips + '</div></div>' +
                '<div class="rule-drawer-section"><h3>' + __('Affected hospitals') + (imp.month ? ' (' + esc(imp.month) + ')' : '') + '</h3><div>' + affectedHtml + '</div></div>' +
                '<div class="rule-drawer-section" style="display:flex;gap:0.4rem;flex-wrap:wrap;"><h3 style="flex-basis:100%;">' + __('Actions') + '</h3>' +
                '<button class="btn btn-sm" onclick="_drawerEditRule(' + rule.id + ')" style="font-size:0.72rem;">' + __('Edit rule') + '</button>' +
                '<button class="btn btn-sm btn-outline" onclick="_drawerTestRule(' + rule.id + ')" style="font-size:0.72rem;color:var(--accent-blue);border-color:var(--accent-blue);">' + __('Test rule') + '</button>' +
                '</div>';

            drawer.classList.add('open');
            overlay.classList.add('open');
            drawer.setAttribute('aria-hidden', 'false');
        };

        window.closeRuleDrawer = function() {
            const drawer = document.getElementById('ruleDrawer');
            const overlay = document.getElementById('ruleDrawerOverlay');
            if (drawer) { drawer.classList.remove('open'); drawer.setAttribute('aria-hidden', 'true'); }
            if (overlay) overlay.classList.remove('open');
        };

        window._drawerEditRule = function(id) { closeRuleDrawer(); openRuleModal(id); };
        window._drawerTestRule = function(id) { closeRuleDrawer(); _testRuleById(id); };

        window.closeRuleTestModal = function() {
            const modal = document.getElementById('ruleTestModal');
            if (modal) modal.classList.remove('show');
        };

        // ESC closes the topmost open rules dialog only — one press per layer
        // (edit modal → test modal → drawer). Bound once, in bubble phase:
        // rules.js closes the edit modal in the capture phase first, so ESC
        // never closes the drawer underneath an open edit modal anymore.
        if (!window._rulesDialogsEscBound) {
            document.addEventListener('keydown', function(e) {
                if (e.key !== 'Escape') return;
                const testModal = document.getElementById('ruleTestModal');
                if (testModal && testModal.classList.contains('show')) {
                    e.preventDefault();
                    window.closeRuleTestModal();
                    return;
                }
                const drawer = document.getElementById('ruleDrawer');
                if (drawer && drawer.classList.contains('open')) {
                    e.preventDefault();
                    window.closeRuleDrawer();
                }
            });
            window._rulesDialogsEscBound = true;
        }

        // Column sorting (Code / Severity / Affected Hospitals). Re-renders
        // from rulesManagerData so the sort survives toggles and filters.
        window.onRulesSort = function(col) {
            if (_rulesSortCol === col) {
                if (_rulesSortAsc) {
                    _rulesSortAsc = false;               // second click: descending
                } else {
                    _rulesSortCol = null; _rulesSortAsc = true;  // third click: back to default
                }
            } else {
                _rulesSortCol = col; _rulesSortAsc = true;       // first click: ascending
            }
            renderRulesManager();
        };

        // Bulk enable/disable for the rules currently shown (filter + search
        // scope). Single confirmation for the destructive direction, then the
        // same immediate-persist path as bulkToggleCategory.
        window.bulkToggleFiltered = function(enable) {
            const tbody = document.getElementById('rulesTbody');
            if (!tbody) return;
            const ids = [...tbody.querySelectorAll('.rule-row')].map(row => parseInt(row.dataset.id, 10));
            if (!ids.length) return;
            const targets = rulesManagerData.filter(r => ids.includes(r.id) && r.enabled !== enable);
            if (!targets.length) { toastWarning(__('All shown rules are already ' + (enable ? 'enabled' : 'disabled'))); return; }
            const catFilter = document.getElementById('rulesCategoryFilter') ? document.getElementById('rulesCategoryFilter').value : '';
            const typeFilter = document.getElementById('rulesTypeFilter') ? document.getElementById('rulesTypeFilter').value : '';
            const sevFilter = document.getElementById('rulesSeverityFilter') ? document.getElementById('rulesSeverityFilter').value : '';
            const scope = [];
            if (catFilter) scope.push(__('Category') + ': ' + catFilter);
            if (typeFilter) scope.push(__('Type') + ': ' + typeFilter);
            if (sevFilter) scope.push(__('Severity') + ': ' + sevFilter);
            const scopeText = scope.length ? scope.join(', ') : __('Current search');
            const msg = __('This will') + ' ' + (enable ? __('enable') : __('disable')) + ' ' + targets.length + ' ' + __('rule(s)') + ' — ' + scopeText + '. ' + (enable ? '' : __('Disabled rules are skipped during analysis.'));
            const doApply = function() {
                targets.forEach(r => { r.enabled = enable; });
                _rulesDirty = false;
                renderRulesManager();
                const btn = document.getElementById('rulesSaveBtn');
                if (btn) { btn.textContent = __('Saving...'); btn.disabled = true; }
                const items = rulesManagerData.map(r => ({ id: r.id, enabled: r.enabled }));
                authFetch(API() + '/rules/save-enabled', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items: items }),
                })
                    .then(r => r.json())
                    .then(data => {
                        toastSuccess((enable ? __('Enabled') : __('Disabled')) + ' ' + targets.length + ' ' + __('rule(s)') + ' (' + __('saved') + ')');
                        loadRulesManager();
                    })
                    .catch(e => {
                        _rulesDirty = true;
                        if (btn) { btn.textContent = __('Save'); btn.disabled = false; }
                        _updateRulesSaveButton();
                        toastError(__('Save failed') + ': ' + e.message);
                    });
            };
            if (enable) {
                doApply();
            } else {
                confirmDestructive({
                    title: __('Disable all'),
                    message: msg,
                    okLabel: __('Disable all'),
                }).then(ok => { if (ok) doApply(); });
            }
        };

        // Bulk toggle all rules in a category — persists immediately (no Save click needed)
        window.bulkToggleCategory = function(cat, enable) {
            let count = 0;
            rulesManagerData.forEach(r => {
                if ((r.category || 'UNCATEGORIZED') === cat) {
                    r.enabled = enable;
                    count++;
                }
            });
            if (!count) return;
            _rulesDirty = false;
            renderRulesManager();
            const btn = document.getElementById('rulesSaveBtn');
            if (btn) { btn.textContent = __('Saving...'); btn.disabled = true; }
            const items = rulesManagerData.map(r => ({ id: r.id, enabled: r.enabled }));
            authFetch(API() + '/rules/save-enabled', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: items }),
            })
                .then(r => r.json())
                .then(data => {
                    toastSuccess(__('Category') + ' "' + cat + '" ' + (enable ? __('enabled') : __('disabled')) + ' (' + count + ' ' + __('rule(s)') + ' ' + __('saved') + ')');
                    loadRulesManager();
                })
                .catch(e => {
                    _rulesDirty = true;
                    if (btn) { btn.textContent = __('Save'); btn.disabled = false; }
                    _updateRulesSaveButton();
                    toastError('Save failed: ' + e.message);
                });
        };

        window._testRuleById = function(id) {
            const r = rulesManagerData.find(x => x.id == id);
            if (!r) return;
            const modal = document.getElementById('ruleTestModal');
            const body = document.getElementById('ruleTestModalBody');
            const title = document.getElementById('ruleTestModalTitle');
            if (!modal || !body || !title) return;
            if (!modal.dataset.bound) {
                modal.addEventListener('click', function(e) { if (e.target === modal) window.closeRuleTestModal(); });
                modal.dataset.bound = '1';
            }
            title.textContent = __('Rule Test') + ' — ' + esc(r.code);
            let paramsRaw;
            try { paramsRaw = JSON.parse(r.params || '{}'); } catch(e) { paramsRaw = {}; }
            const payload = {
                code: r.code,
                name: r.name,
                rule_type: r.rule_type,
                severity: r.severity,
                expression_type: r.expression_type,
                params: paramsRaw,
            };
            // Scope pickers: the test runs across all hospitals for the latest
            // month by default; narrowing re-runs the evaluation instantly.
            body.innerHTML =
                '<div style="display:flex;gap:0.4rem;align-items:center;flex-wrap:wrap;margin-bottom:0.6rem;padding:0.4rem 0.5rem;border:1px solid var(--border-default);border-radius:6px;background:var(--bg-surface);">' +
                '<label style="font-size:0.74rem;color:var(--text-secondary);">' + __('Hospital') + ':</label>' +
                '<select id="ruleModalHospital" onchange="_runRuleTestModal()" style="font-size:0.75rem;padding:0.2rem 0.4rem;min-width:170px;"><option value="">' + __('All hospitals') + '</option></select>' +
                '<label style="font-size:0.74rem;color:var(--text-secondary);">' + __('Month') + ':</label>' +
                '<select id="ruleModalMonth" onchange="_runRuleTestModal()" style="font-size:0.75rem;padding:0.2rem 0.4rem;min-width:110px;"><option value="">' + __('Latest month') + '</option></select>' +
                '</div>' +
                '<div id="ruleModalTestResult"><span class="spinner"></span> ' + __('Running test...') + '</div>';
            modal.classList.add('show');
            const hsel = document.getElementById('ruleModalHospital');
            const msel = document.getElementById('ruleModalMonth');
            if (hsel && hsel.options.length <= 1) {
                apiGet('/hospitals/').then(data => {
                    const list = data.value || data || [];
                    hsel.innerHTML = '<option value="">' + __('All hospitals') + '</option>' + list.map(h => '<option value="' + h.id + '">' + esc(h.name) + '</option>').join('');
                }).catch(() => {});
            }
            if (msel && msel.options.length <= 1) {
                apiGet('/analysis/months').then(months => {
                    msel.innerHTML = '<option value="">' + __('Latest month') + '</option>' + (months || []).map(m => '<option value="' + m + '">' + esc(m) + '</option>').join('');
                }).catch(() => {});
            }
            _runRuleTestModal(payload);
        };

        // Re-runnable rule test against the picked hospital/month scope.
        let _ruleModalTestPayload = null;
        window._runRuleTestModal = function(payloadArg) {
            const payload = payloadArg || _ruleModalTestPayload;
            if (!payload) return;
            _ruleModalTestPayload = payload;
            const container = document.getElementById('ruleModalTestResult');
            if (!container) return;
            const hidEl = document.getElementById('ruleModalHospital');
            const monthEl = document.getElementById('ruleModalMonth');
            const req = Object.assign({}, payload);
            if (hidEl && hidEl.value) req.hospital_id = parseInt(hidEl.value, 10);
            if (monthEl && monthEl.value) req.month = monthEl.value;
            container.innerHTML = '<span class="spinner"></span> ' + __('Running test...');
            authFetch(API() + '/rules/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(req),
            }).then(res => res.json()).then(d => {
                _renderRuleTestModalResult(d, container);
            }).catch(function(e) {
                container.innerHTML = '<span style="color:var(--accent-red);">' + __('Test failed') + ': ' + esc(e.message) + '</span>';
            });
        };

        function _renderRuleTestModalResult(d, body) {
            {
                if (d.detail) { body.innerHTML = '<span style="color:var(--accent-red);">' + __(d.detail) + '</span>'; return; }
                const ok = d.status === 'PASS';
                const color = ok ? 'var(--accent-green)' : d.status === 'FAIL' ? 'var(--accent-red)' : 'var(--accent-orange)';
                let html = '<div style="padding:0.5rem 0.7rem;border:1px solid ' + color + '66;border-radius:4px;background:var(--bg-surface-hover);">';
                if (d.scope === 'all') {
                    const barMax = d.total || 1;
                    const passedPct = Math.round(((d.passed || 0) / barMax) * 100);
                    const failedPct = Math.round(((d.failed || 0) / barMax) * 100);
                    const ndPct = 100 - passedPct - failedPct;
                    html += '<strong style="color:' + color + ';font-size:1rem;">' + d.status + '</strong> <span style="color:var(--text-secondary);font-size:0.72rem;">' + d.month + '</span><br>' +
                        '<span style="color:var(--text-secondary);font-size:0.78rem;">' + __(d.details) + '</span>';
                    html += '<div style="margin-top:0.4rem;display:flex;height:10px;border-radius:6px;overflow:hidden;">' +
                        '<div style="width:' + passedPct + '%;background:var(--accent-green);"></div>' +
                        '<div style="width:' + failedPct + '%;background:var(--accent-red);"></div>' +
                        '<div style="width:' + ndPct + '%;background:var(--text-muted);"></div></div>';
                    html += '<div style="margin-top:0.25rem;font-size:0.72rem;display:flex;gap:0.8rem;">' +
                        '<span style="color:var(--accent-green);">' + (d.passed || 0) + ' ' + __('passed') + '</span>' +
                        '<span style="color:var(--accent-red);">' + (d.failed || 0) + ' ' + __('failed') + '</span>' +
                        '<span style="color:var(--text-muted);">' + (d.no_data || 0) + ' ' + __('no data') + '</span></div>';
                    if (d.hospitals && d.hospitals.length) {
                        html += '<div style="margin-top:0.5rem;max-height:280px;overflow-y:auto;font-size:0.72rem;border-top:1px solid var(--border-default);padding-top:0.3rem;">';
                        d.hospitals.slice(0, 200).forEach(function(h) {
                            const hs = h.status || 'NO_DATA';
                            const hc = hs === 'PASS' ? 'var(--accent-green)' : hs === 'FAIL' ? 'var(--accent-red)' : 'var(--text-muted)';
                            html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:3px 5px;border-radius:4px;cursor:default;">' +
                                '<span style="font-weight:600;color:var(--text-primary);">' + esc(h.hospital) + '</span>' +
                                '<span style="color:' + hc + ';font-weight:600;">' + hs + '</span></div>';
                        });
                        if (d.hospitals.length > 200) html += '<div style="color:var(--text-muted);padding:0.2rem 0.4rem;">+ ' + (d.hospitals.length - 200) + ' more</div>';
                        html += '</div>';
                    }
                } else {
                    html += '<strong style="color:' + color + ';">' + d.status + '</strong> <span style="color:var(--text-secondary);font-size:0.72rem;">' + (d.hospital || '') + ' · ' + d.month + '</span><br>' +
                        '<span style="color:var(--text-secondary);font-size:0.78rem;">' + __(d.details) + '</span>';
                    const hospResult = (d.hospitals && d.hospitals[0]) || {};
                    const rvs = hospResult.ref_values || d.ref_values || {};
                    const keys = Object.keys(rvs);
                    if (keys.length) {
                        html += '<div style="margin-top:0.4rem;font-size:0.74rem;color:var(--text-secondary);"><strong>' + __('Indicator values') + ':</strong> ';
                        keys.forEach(function(k) {
                            html += '<span style="margin-right:0.5rem;">' + k + ' (' + __(rvs[k].name) + ') = <strong>' + rvs[k].value + '</strong></span>';
                        });
                        html += '</div>';
                    }
                }
                html += '</div>';
                body.innerHTML = html;
            }
        }

        // ── Rules export / import (JSON backup & restore) ─────────
        window.exportRulesJson = function() {
            authFetch(API() + '/rules/export')
                .then(r2 => {
                    if (!r2.ok) throw new Error('HTTP ' + r2.status);
                    return r2.json();
                })
                .then(data => {
                    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                    const a = document.createElement('a');
                    a.href = URL.createObjectURL(blob);
                    a.download = 'rules-export-' + new Date().toISOString().slice(0, 10) + '.json';
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(a.href);
                    toastSuccess(__('Export') + ': ' + (data.count || 0) + ' ' + __('rule(s)'));
                })
                .catch(e => toastError(__('Export failed') + ': ' + e.message));
        };

        window.importRulesJson = function(input) {
            const file = input && input.files && input.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = function() {
                let payload;
                try { payload = JSON.parse(String(reader.result)); }
                catch (e) { toastError(__('Import failed') + ': ' + __('Invalid JSON file')); return; }
                authFetch(API() + '/rules/import', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                })
                    .then(r2 => r2.json().then(d => ({ ok: r2.ok, d })))
                    .then(({ ok, d }) => {
                        if (!ok) { toastError(__('Import failed') + ': ' + (d.detail || 'HTTP error')); return; }
                        toastSuccess(d.message || __('Import') + ' OK');
                        loadRulesManager();
                    })
                    .catch(e => toastError(__('Import failed') + ': ' + e.message));
            };
            reader.readAsText(file);
            input.value = ''; // allow re-selecting the same file
        };

        // ── Rule change history (audit trail) ─────────────────────
        const _HISTORY_ACTION_COLORS = {
            created: 'var(--accent-green)', updated: 'var(--accent-blue)',
            enabled: 'var(--accent-green)', disabled: 'var(--accent-orange)',
            deleted: 'var(--accent-red)',
        };

        window.showRuleHistory = function(id) {
            const rule = rulesManagerData.find(x => x.id == id);
            if (!rule) return;
            const modal = document.getElementById('ruleTestModal');
            const body = document.getElementById('ruleTestModalBody');
            const title = document.getElementById('ruleTestModalTitle');
            if (!modal || !body || !title) return;
            if (!modal.dataset.bound) {
                modal.addEventListener('click', function(e) { if (e.target === modal) window.closeRuleTestModal(); });
                modal.dataset.bound = '1';
            }
            title.textContent = __('History') + ' — ' + esc(rule.code);
            body.innerHTML = '<span class="spinner"></span> ' + __('Loading details...');
            modal.classList.add('show');
            authFetch(API() + '/rules/history/' + encodeURIComponent(rule.code) + '?limit=100')
                .then(r2 => {
                    if (!r2.ok) throw new Error('HTTP ' + r2.status);
                    return r2.json();
                })
                .then(d => {
                    const entries = d.entries || [];
                    if (!entries.length) {
                        body.innerHTML = '<em style="color:var(--text-muted);">' + __('No history recorded yet.') + '</em>';
                        return;
                    }
                    let html = '<div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:0.4rem;">' + entries.length + ' ' + __('rule(s)') + '</div>';
                    html += '<div style="max-height:420px;overflow-y:auto;font-size:0.76rem;border-top:1px solid var(--border-default);padding-top:0.4rem;">';
                    entries.forEach(en => {
                        const color = _HISTORY_ACTION_COLORS[en.action] || 'var(--text-secondary)';
                        const changed = (en.changed_fields || []).join(', ');
                        html += '<div style="display:flex;gap:0.5rem;align-items:flex-start;padding:4px 2px;border-bottom:1px solid var(--border-default);">' +
                            '<span class="badge" style="background:' + color + '22;color:' + color + ';border:1px solid ' + color + '44;white-space:nowrap;">' + esc(en.action) + '</span>' +
                            '<div style="flex:1;">' +
                            (en.created_at ? '<div style="color:var(--text-muted);font-size:0.7rem;">' + esc(String(en.created_at).replace('T', ' ').slice(0, 16)) + '</div>' : '') +
                            (changed ? '<div style="color:var(--text-secondary);">' + __('Changed') + ': ' + esc(changed) + '</div>' : '') +
                            (en.snapshot ? '<div style="color:var(--text-muted);font-size:0.72rem;">' + esc(en.snapshot.name || '') + ' · ' + esc(en.snapshot.expression_type || '') + '</div>' : '') +
                            '</div></div>';
                    });
                    html += '</div>';
                    body.innerHTML = html;
                })
                .catch(e => {
                    body.innerHTML = '<span style="color:var(--accent-red);">' + __('Test failed') + ': ' + esc(e.message) + '</span>';
                });
        };

        function _updateRulesSaveButton() {
            const btn = document.getElementById('rulesSaveBtn');
            if (!btn) return;
            btn.style.display = 'inline-block';
            btn.textContent = _rulesDirty ? __('Save') + ' (*)' : __('Save');
            btn.disabled = false;
        }

        export function saveRulesManager() {
            if (!rulesManagerData.length) return;
            const items = rulesManagerData.map(r => ({ id: r.id, enabled: r.enabled }));
            const btn = document.getElementById('rulesSaveBtn');
            btn.textContent = __('Saving...');
            btn.disabled = true;
            authFetch(API() + '/rules/save-enabled', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: items }),
            })
                .then(r => r.json())
                .then(data => {
                    _rulesDirty = false;
                    _updateRulesSaveButton();
                    toastSuccess(data.message || 'Rules saved');
                    btn.disabled = false;
                    loadRulesManager();
                })
                .catch(e => {
                    btn.textContent = __('Save');
                    btn.disabled = false;
                    toastError('Save failed: ' + e.message);
                });
        }

        export const EXPR_EXPLANATIONS = {
            'ge': {title: 'parent >= sum(children)', text: 'FAILs when the parent indicator value is less than the sum of its child indicators. Use for aggregation checks like Total Deliveries >= NVD + Assisted + C-sections.'},
            'gt': {title: 'parent > sum(children)', text: 'FAILs when the parent value is less than or equal to the sum of its children. Strict version of ge — equality does not pass. Use when the parent must strictly exceed its breakdown.'},
            'ge_factor': {title: 'parent × factor >= sum(children)', text: 'FAILs when the sum of children exceeds the parent value multiplied by a factor. Use factor > 1 to allow children to exceed the parent (e.g. 1.1 = +10% tolerance), or factor < 1 to require a stricter margin. Example params: {"parent":"2","children":["3","4","5"],"factor":1.1}'},
            'eq': {title: 'parent == sum(children)', text: 'FAILs when the parent value != sum of children. Use for exact equality checks like Male + Female + Unknown = Live Births.'},
            'le': {title: 'child <= parent', text: 'FAILs when child value exceeds parent value. Use for subset checks like Emergency C/S <= Total C-sections.'},
            'lt': {title: 'child < parent', text: 'FAILs when the child value is greater than or equal to the parent value. Strict version of le — equality does not pass. Use when the child must be strictly below the parent.'},
            'le_sum': {title: 'child >= sum(children)', text: 'FAILs when child value is less than sum of its sub-children. Reverse of ge — use when a parent should be >= its breakdown.'},
            'benchmark_rate': {title: 'FAIL if (num/den*100) > threshold', text: 'Flags when a calculated rate exceeds a fixed threshold. Example: C/S rate > 80%. Requires num_code (numerator indicator), den_code (denominator), threshold (percentage).'},
            'benchmark_low_rate': {title: 'FAIL if (num/den*100) < threshold', text: 'Flags when a rate drops below a minimum threshold. Example: NVD rate < 10%. Same params as benchmark_rate.'},
            'cross_hospital_rate': {title: 'FAIL if |z-score| > z_threshold', text: 'Compares a hospital\'s rate against all other hospitals for the same month. FAIL if the hospital is a statistical outlier (|z| > threshold). Requires num_code, den_code, z_threshold.'},
            'month_over': {title: 'FAIL if current > factor * previous', text: 'Detects unusual spikes. FAIL when current month value exceeds (previous month × factor). Example: factor=2.0 means >200% increase triggers alert.'},
            'month_under': {title: 'FAIL if current < factor * previous', text: 'Detects unusual drops. FAIL when current month value is below (previous month × factor). Example: factor=0.5 means <50% of previous month triggers alert.'},
            'neg_check': {title: 'FAIL if any listed code is negative', text: 'Checks that all listed indicator codes have non-negative values (counts should always be >= 0). Takes codes[] list.'},
            'decimal_check': {title: 'FAIL if any listed code has decimal', text: 'Checks that all listed count indicators are whole numbers (integers). Counts should not have decimal values. Takes codes[] list.'},
            'missing': {title: 'FAIL if indicator has no value', text: 'Checks whether a critical indicator code is present in the data. FAIL if the indicator is missing (null/undefined). Takes a single code.'},
            'all_zero': {title: 'FAIL if ALL listed codes are zero', text: 'Checks if all key indicators are zero, suggesting the facility may not be operational or data is missing. Takes codes[] list.'},
            'formula': {title: 'formula result ≤/≥/=/≠ target indicator', text: 'FAILs when the evaluated arithmetic formula does not satisfy the chosen comparison with the target indicator. Supports +, -, *, /, parentheses, numeric constants, indicator codes, and the operators =, ≠, >, <, ≥, ≤. Example: {"formula":"(6.e * 2) - 7","target":"6","op":">"} evaluates (Number of twins × 2) - Stillbirths and FAILs unless it is strictly greater than Live Births.'},
        };
        // Short human-readable label per expression type — "code — meaning",
        // matching the edit-modal dropdown convention. Falls back to the raw
        // code for unknown types so new backend types never render blank.
        export function exprTypeLabel(expr) {
            const expl = EXPR_EXPLANATIONS[expr];
            return expl ? expr + ' — ' + __(expl.title) : (expr || '--');
        }




// ── Settings UX: search, dirty tracking, safe saving, live previews ────────
let _settingsBaseline = {};

function _settingsInputs() {
    return Array.from(document.querySelectorAll('input[type=range], input[type=checkbox]'))
        .filter(i => (i.id || '').indexOf('cfg_') === 0 || (i.id || '').indexOf('weight_') === 0);
}

function _settingsSnapshot() {
    _settingsBaseline = {};
    _settingsInputs().forEach(el => {
        _settingsBaseline[el.id] = el.type === 'checkbox' ? !!el.checked : el.value;
    });
}

function _settingsChangedKeys() {
    const changed = [];
    _settingsInputs().forEach(el => {
        const v = el.type === 'checkbox' ? !!el.checked : el.value;
        if (_settingsBaseline[el.id] !== undefined && String(_settingsBaseline[el.id]) !== String(v)) changed.push(el.id);
    });
    return changed;
}

function _settingsSectionOf(el) {
    return el.closest('.settings-collapsible');
}

function _settingsTabOf(el) {
    const sec = el.closest('.settings-section');
    if (!sec) return null;
    const m = /^settings-(.+)$/.exec(sec.id || '');
    return m ? m[1] : null;
}

function _settingsTabLabel(name) {
    const btn = document.getElementById('stbtn-' + name);
    if (btn) {
        const t = btn.textContent.replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\uFE0F]/gu, '').trim();
        if (t) return t;
    }
    return name;
}

function _settingsRefreshDirtyUI() {
    const changed = _settingsChangedKeys();
    const bySection = new Set();
    const byTab = new Set();
    changed.forEach(k => {
        const el = document.getElementById(k);
        if (!el) return;
        const sec = _settingsSectionOf(el);
        if (sec) bySection.add(sec);
        const tab = _settingsTabOf(el);
        if (tab) byTab.add(tab);
    });
    document.querySelectorAll('.settings-dirty-dot').forEach(d => d.remove());
    document.querySelectorAll('.settings-section-dirty').forEach(s => s.classList.remove('settings-section-dirty'));
    document.querySelectorAll('.stbtn-dirty').forEach(b => b.classList.remove('stbtn-dirty'));
    bySection.forEach(sec => {
        const hdr = sec.querySelector('.settings-section-header');
        if (!hdr) return;
        const dot = document.createElement('span');
        dot.className = 'settings-dirty-dot';
        dot.title = __('Unsaved changes');
        hdr.appendChild(dot);
        sec.classList.add('settings-section-dirty');
    });
    byTab.forEach(tab => document.getElementById('stbtn-' + tab)?.classList.add('stbtn-dirty'));
    const chip = document.getElementById('settingsSaveChip');
    if (chip) {
        if (changed.length) {
            chip.style.display = '';
            chip.textContent = '💾 ' + __('Save') + ' (' + changed.length + ')';
        } else {
            chip.style.display = 'none';
        }
    }
}

function _settingsWatchInputs() {
    _settingsInputs().forEach(el => {
        if (el.dataset.settingsWatched) return;
        el.dataset.settingsWatched = '1';
        ['input', 'change'].forEach(evt => el.addEventListener(evt, _settingsRefreshDirtyUI));
    });
}

function _settingsActiveTab() {
    return window._activeSettingsTab || 'quality';
}

function settingsApplySearchFilter() {
    const input = document.getElementById('settingsSearch');
    if (input) settingsLiveSearch(input.value);
}

window.settingsLiveSearch = function(q) {
    const info = document.getElementById('settingsSearchInfo');
    const results = document.getElementById('settingsSearchResults');
    q = (q || '').trim().toLowerCase();
    if (!q) {
        document.querySelectorAll('.settings-search-hit, .settings-search-miss').forEach(el => {
            el.classList.remove('settings-search-hit', 'settings-search-miss');
        });
        if (info) info.textContent = '';
        if (results) { results.innerHTML = ''; results.style.display = 'none'; }
        return;
    }
    const active = _settingsActiveTab();
    let activeMatches = 0, totalMatches = 0;
    const otherHits = [];
    document.querySelectorAll('#settings-tabs .settings-section, .settings-section').forEach(sec => {
        const m = /^settings-(.+)$/.exec(sec.id || '');
        if (!m) return;
        const tab = m[1];
        let secMatches = 0;
        sec.querySelectorAll(':scope > .settings-collapsible').forEach(col => {
            const hit = (col.textContent || '').toLowerCase().indexOf(q) !== -1;
            if (hit) secMatches++;
            col.classList.toggle('settings-search-hit', hit);
            col.classList.toggle('settings-search-miss', !hit);
        });
        if (secMatches) {
            totalMatches += secMatches;
            if (tab === active) activeMatches += secMatches;
            else otherHits.push({ tab, count: secMatches });
        }
    });
    if (results) {
        let html = '';
        if (activeMatches) {
            html += '<span>' + __('matches') + ': <strong>' + activeMatches + '</strong></span>';
        } else {
            html += '<span style="color:var(--accent-orange);">' + __('No matches') + ' — ' + esc(_settingsTabLabel(active)) + '</span>';
        }
        if (otherHits.length) {
            html += ' &nbsp;·&nbsp; ' + __('Found in') + ': ';
            html += otherHits.slice(0, 4).map(h =>
                '<button class="btn btn-sm btn-outline settings-jump" style="font-size:0.7rem;padding:0.15rem 0.5rem;margin:0.1rem;" onclick="settingsJumpTo(\'' + h.tab + '\')">' + esc(_settingsTabLabel(h.tab)) + ' (' + h.count + ')</button>'
            ).join('');
        } else if (!totalMatches) {
            html += '<span style="color:var(--text-muted);">' + __('No settings match') + ' &quot;' + esc(q) + '&quot;</span>';
        }
        results.innerHTML = html;
        results.style.display = '';
    }
};

window.settingsJumpTo = function(tabName) {
    showSettingsTab(tabName);
    const sec = document.getElementById('settings-' + tabName);
    if (!sec) return;
    const first = sec.querySelector('.settings-collapsible.settings-search-hit');
    if (first) first.classList.add('open');
    sec.scrollIntoView({ block: 'start', behavior: 'smooth' });
    const results = document.getElementById('settingsSearchResults');
    if (results) results.style.display = 'none';
};

function _settingsFindCollapsible(title) {
    const els = Array.from(document.querySelectorAll('.settings-collapsible .settings-section-header'));
    const hdr = els.find(h => (h.textContent || '').indexOf(title) !== -1);
    return hdr ? hdr.closest('.settings-collapsible') : null;
}

// ── Live previews ──
function _cfgVal(key, def) {
    const el = document.getElementById('cfg_' + key);
    if (!el || el.value === '') return def;
    const v = parseFloat(el.value);
    return isNaN(v) ? def : v;
}

function _weightVal(key, def) {
    const el = document.getElementById('weight_' + key);
    if (!el || el.value === '') return def;
    const v = parseFloat(el.value);
    return isNaN(v) ? def : v;
}

function _settingsInjectPreviews() {
    const qCol = _settingsFindCollapsible('Quality Score Formula Weights');
    if (qCol && !document.getElementById('settingsQualityPreview')) {
        const box = document.createElement('div');
        box.id = 'settingsQualityPreview';
        box.className = 'settings-preview';
        qCol.querySelector('.settings-section-body').appendChild(box);
        _renderQualityPreview();
    }
    const cCol = _settingsFindCollapsible('Confidence Signal Weights');
    if (cCol && !document.getElementById('settingsConfPreview')) {
        const box = document.createElement('div');
        box.id = 'settingsConfPreview';
        box.className = 'settings-preview';
        cCol.querySelector('.settings-section-body').appendChild(box);
        _renderConfPreview();
    }
    _settingsInjectClinicalPreviews();
    _refreshClinicalPreviews();
}

function _renderQualityPreview() {
    const box = document.getElementById('settingsQualityPreview');
    if (!box) return;
    const w1 = _cfgVal('quality_rule_compliance', 0.35);
    const w2 = _cfgVal('quality_completeness', 0.25);
    const w3 = _cfgVal('quality_consistency', 0.25);
    const w4 = _cfgVal('quality_outlier_penalty', 0.15);
    const demo = { rc: 0.92, comp: 0.86, cons: 0.81, pen: 0.08 };
    const parts = [
        { label: __('Rule compliance'), color: '#1a237e', share: w1 * demo.rc },
        { label: __('Completeness'), color: '#2e7d32', share: w2 * demo.comp },
        { label: __('Consistency'), color: '#e65100', share: w3 * demo.cons },
        { label: __('Outlier (1-penalty)'), color: '#6a1b9a', share: w4 * (1 - demo.pen) }
    ];
    const score = Math.max(0, Math.min(100, parts.reduce((a, p) => a + p.share, 0) * 100));
    const tone = score >= 80 ? 'badge-pass' : score >= 70 ? 'badge-medium' : score >= 50 ? 'badge-high' : 'badge-critical';
    box.innerHTML =
        '<div class="settings-preview-title">📊 ' + __('Live preview — sample components') + '</div>' +
        '<div style="display:flex;gap:0.6rem;flex-wrap:wrap;font-size:0.72rem;color:var(--text-secondary);margin:0.35rem 0 0.4rem;">' +
        parts.map(p => '<span><span style="display:inline-block;width:0.55rem;height:0.55rem;background:' + p.color + ';border-radius:2px;vertical-align:middle;"></span> ' + esc(p.label) + ' × ' + p.share.toFixed(3) + '</span>').join('') +
        '</div>' +
        '<div style="display:flex;height:0.7rem;border-radius:4px;overflow:hidden;border:1px solid var(--border-default);direction:ltr;">' +
        parts.map(p => '<div style="width:' + (p.share * 100).toFixed(2) + '%;background:' + p.color + ';" title="' + esc(p.label) + '""></div>').join('') +
        '</div>' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:0.4rem;"><span style="font-size:0.72rem;color:var(--text-muted);">' + __('Example final score') + '</span>' +
        '<span style="font-weight:700;font-size:1rem;">' + score.toFixed(1) + ' <span class="badge ' + tone + '">' + (score >= 80 ? __('Reliable') : score >= 50 ? __('Needs attention') : __('Critical')) + '</span></span></div>';
}

function _renderConfPreview() {
    const box = document.getElementById('settingsConfPreview');
    if (!box) return;
    const ws = [
        { key: 'rule_compliance', label: __('Validation rule'), sig: 0.80, color: '#1a237e' },
        { key: 'historical', label: __('Historical consistency'), sig: 0.62, color: '#2e7d32' },
        { key: 'cross_hospital', label: __('Cross-hospital'), sig: 0.70, color: '#6a1b9a' },
        { key: 'trend', label: __('Trend'), sig: 0.88, color: '#e65100' },
        { key: 'completeness', label: __('Completeness'), sig: 0.84, color: '#00838f' }
    ];
    const conf = Math.max(0, Math.min(100, ws.reduce((a, w) => a + _weightVal(w.key, 0.2) * w.sig, 0) * 100));
    const hi = _cfgVal('confidence_high', 80);
    const med = _cfgVal('confidence_medium', 50);
    const lo = _cfgVal('confidence_low', 25);
    const level = conf >= hi ? 'HIGH' : conf >= med ? 'MEDIUM' : conf >= lo ? 'LOW' : 'CRITICAL';
    const tone = level === 'HIGH' ? 'badge-pass' : level === 'MEDIUM' ? 'badge-medium' : 'badge-critical';
    const tick = v => '<div class="range-tick" style="left:' + v + '%;background:var(--accent-purple);" title="' + __('Confidence cutoff') + ' ' + v + '"></div>';
    const dotColor = level === 'HIGH' ? 'var(--accent-green)' : level === 'MEDIUM' ? 'var(--accent-orange)' : 'var(--accent-red)';
    box.innerHTML =
        '<div class="settings-preview-title">🎯 ' + __('Live preview — sample signals') + '</div>' +
        '<div style="display:flex;gap:0.6rem;flex-wrap:wrap;font-size:0.72rem;color:var(--text-secondary);margin:0.35rem 0 0.4rem;">' +
        ws.map(w => '<span>' + esc(w.label) + ' ' + (w.sig * 100).toFixed(0) + '% × ' + _weightVal(w.key, 0.2).toFixed(2) + '</span>').join('') +
        '</div>' +
        '<div class="range-track" style="margin:0.6rem 0 0.2rem;">' + tick(lo) + tick(med) + tick(hi) +
        '<div class="range-dot" style="left:' + conf.toFixed(1) + '%;background:' + dotColor + ';width:1rem;height:1rem;" title="' + __('Example confidence') + '"></div></div>' +
        '<div class="range-scale"><span>' + __('Levels') + ': ≥' + hi + ' ' + __('High') + ' · ≥' + med + ' ' + __('Medium') + ' · ≥' + lo + ' ' + __('Low') + ' · < ' + lo + ' ' + __('Critical') + '</span></div>' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:0.45rem;"><span style="font-size:0.72rem;color:var(--text-muted);">' + __('Example confidence') + '</span>' +
        '<span style="font-weight:700;font-size:1rem;">' + conf.toFixed(1) + ' <span class="badge ' + tone + '">' + level + '</span></span></div>';
}

// ── Clinical threshold live previews ──
function _settingsInjectClinicalPreviews() {
    document.querySelectorAll('#settings-clinical table tbody tr').forEach(row => {
        const inputs = row.querySelectorAll('input[type=range]');
        if (inputs.length < 3) return;
        const first = inputs[0].id;
        const base = first.replace(/_(elevated|high|critical)$/, '');
        let cell = row.querySelector('td');
        if (!cell) return;
        if (!cell.querySelector('.clinical-preview')) {
            const div = document.createElement('div');
            div.className = 'clinical-preview';
            div.id = 'clp_' + base;
            cell.appendChild(div);
        }
    });
    window._settingsClinicalBases = Array.from(document.querySelectorAll('.clinical-preview')).map(d => d.id.replace(/^clp_/, ''));
}

function _refreshClinicalPreviews() {
    const bases = window._settingsClinicalBases || [];
    bases.forEach(base => {
        const el = document.getElementById('clp_' + base);
        if (!el) return;
        const elevated = _cfgVal(base + '_elevated', 0);
        const high = _cfgVal(base + '_high', 0);
        const critical = _cfgVal(base + '_critical', 0);
        const sample = (elevated + high) / 2;
        const ordered = elevated <= high && high <= critical;
        if (!ordered) {
            el.innerHTML = '<span style="color:var(--accent-red);">⚠ ' + __('Thresholds not in ascending order') + ' (elevated ' + elevated + ', high ' + high + ', critical ' + critical + ')</span>';
            return;
        }
        const level = sample >= critical ? 'CRITICAL' : sample >= high ? 'HIGH' : sample >= elevated ? 'ELEVATED' : 'NORMAL';
        const color = level === 'CRITICAL' ? 'var(--accent-red)' : level === 'HIGH' ? 'var(--accent-orange)' : level === 'ELEVATED' ? 'var(--accent-blue)' : 'var(--accent-green)';
        el.innerHTML = __('Sample rate') + ' <strong>' + sample.toFixed(1) + '</strong> → <span style="color:' + color + ';font-weight:600;">' + level + '</span>';
    });
}

// ── Init + safe saving guards ──
function _settingsInitUX() {
    _settingsSnapshot();
    _settingsWatchInputs();
    _settingsRefreshDirtyUI();
    _settingsInjectPreviews();
    settingsApplySearchFilter();
}

window._settingsGuardSwitch = async function() {
    if (_settingsChangedKeys().length === 0) return true;
    return await confirmWarning({
        title: __('Unsaved changes'),
        message: __('You have unsaved changes in Settings.'),
        details: __('Leave this tab without saving?'),
        okLabel: __('Discard changes'),
        cancelLabel: __('Keep editing')
    });
};

window.addEventListener('beforeunload', function(e) {
    if (_settingsChangedKeys().length > 0) {
        e.preventDefault();
        e.returnValue = '';
    }
});
