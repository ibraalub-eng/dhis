        import { API, apiGet, apiPost, apiPut } from './api.js';
        import { __ } from './i18n.js';
        import { esc } from './tree.js';
        import { _saveUIState, _restoreUIState } from './main.js';

        // ── Rules Manager ─────────────────────────────────────────
        export let rulesManagerData = [];
        let rulesSortCol = null, rulesSortAsc = true;

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
                status.style.color = '#2e7d32';
            } else {
                status.textContent = '\u2717 Must be 1.0';
                status.style.color = '#c62828';
            }
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
                    status.style.color = '#2e7d32';
                } else {
                    status.textContent = '\u2717 Must be 1.0';
                    status.style.color = '#c62828';
                }
            }
        }

        export function updateCfgVal(key) {
            const el = document.getElementById('cfg_' + key);
            const valEl = document.getElementById('cfgval_' + key);
            if (el && valEl) valEl.textContent = fmtCfgVal(key, el.value);
        }

        function fmtCfgVal(key, value) {
            const v = parseFloat(value);
            const intKeys = ['trend_finding_consecutive'];
            const tripleKeys = ['eq_tolerance'];
            if (intKeys.includes(key)) return Math.round(v).toString();
            if (tripleKeys.includes(key)) return v.toFixed(3);
            return v.toFixed(1);
        }

        export function showSettingsTab(name) {
            ['quality', 'confidence', 'thresholds', 'rules', 'clinical', 'risk', 'trends', 'rates', 'ai', 'control'].forEach(s => {
                const section = document.getElementById('settings-' + s);
                if (section) section.style.display = s === name ? '' : 'none';
                const btn = document.getElementById('stbtn-' + s);
                if (!btn) return;
                if (s === name) {
                    btn.className = 'btn btn-sm';
                    btn.style.background = s === 'ai' ? '#d32f2f' : '#1a237e';
                    btn.style.color = 'white';
                } else {
                    btn.className = 'btn btn-sm btn-outline';
                    btn.style.background = '';
                    btn.style.color = '';
                }
            });
            if (name === 'ai') loadAiSettings();
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

        export function loadRootCause() {
            _saveUIState('root-cause');
            const hid = document.getElementById('rcHospital').value;
            const mth = document.getElementById('rcMonth').value;
            if (!hid || !mth) return;
            document.getElementById('rcLoading').style.display = 'block';
            document.getElementById('rcContent').style.display = 'none';
            apiGet('/root-cause/' + hid + '?month=' + mth).then(d => {
                document.getElementById('rcLoading').style.display = 'none';
                document.getElementById('rcContent').style.display = 'block';

                // ── KPI Banner ──
                const qs = d.overall_quality_score || 0;
                const qsColor = qs >= 80 ? '#2e7d32' : qs >= 50 ? '#e65100' : '#c62828';
                const conf = d.overall_confidence || 0;
                const confColor = conf >= 80 ? '#2e7d32' : conf >= 50 ? '#e65100' : '#c62828';
                const ci = d.critical_issues_count || 0;
                document.getElementById('rcKpiBar').innerHTML =
                    '<div class="card" style="text-align:center;padding:0.8rem 0.5rem;border-top:4px solid ' + qsColor + ';">' +
                        '<div style="font-size:0.7rem;color:#888;text-transform:uppercase;letter-spacing:0.5px;">Quality Score</div>' +
                        '<div style="font-size:2rem;font-weight:700;color:' + qsColor + ';">' + qs + '</div>' +
                        '<div style="height:4px;background:#e0e0e0;border-radius:2px;margin:0.3rem 1rem;overflow:hidden;">' +
                            '<div style="width:' + Math.min(qs, 100) + '%;height:100%;background:' + qsColor + ';border-radius:2px;"></div>' +
                        '</div>' +
                    '</div>' +
                    '<div class="card" style="text-align:center;padding:0.8rem 0.5rem;border-top:4px solid ' + confColor + ';">' +
                        '<div style="font-size:0.7rem;color:#888;text-transform:uppercase;letter-spacing:0.5px;">Confidence</div>' +
                        '<div style="font-size:2rem;font-weight:700;color:' + confColor + ';">' + conf + '</div>' +
                        '<div style="height:4px;background:#e0e0e0;border-radius:2px;margin:0.3rem 1rem;overflow:hidden;">' +
                            '<div style="width:' + Math.min(conf, 100) + '%;height:100%;background:' + confColor + ';border-radius:2px;"></div>' +
                        '</div>' +
                    '</div>' +
                    '<div class="card" style="text-align:center;padding:0.8rem 0.5rem;border-top:4px solid ' + (ci > 0 ? '#c62828' : '#2e7d32') + ';">' +
                        '<div style="font-size:0.7rem;color:#888;text-transform:uppercase;letter-spacing:0.5px;">Critical Issues</div>' +
                        '<div style="font-size:2rem;font-weight:700;color:' + (ci > 0 ? '#c62828' : '#2e7d32') + ';">' + ci + '</div>' +
                        '<div style="font-size:0.72rem;color:#888;margin-top:0.2rem;">' + (ci > 0 ? 'Requires attention' : 'No critical issues') + '</div>' +
                    '</div>';

                // ── Summary ──
                document.getElementById('rcSummary').innerHTML =
                    '<strong style="color:#3949ab;">Diagnostic Summary</strong><br>' + (d.summary || 'No summary available.');

                // ── Priority Actions ──
                const al = document.getElementById('rcActionsList');
                al.innerHTML = '';
                if (d.priority_actions && d.priority_actions.length) {
                    d.priority_actions.forEach((a, i) => {
                        const isCritical = a.startsWith('[CRITICAL]');
                        const color = isCritical ? '#c62828' : '#e65100';
                        const icon = isCritical ? '\u26a0' : '\u26a1';
                        const div = document.createElement('div');
                        div.style.cssText = 'display:flex;align-items:flex-start;gap:0.5rem;padding:0.4rem 0.5rem;margin-bottom:0.35rem;background:' + color + '08;border-radius:4px;font-size:0.8rem;';
                        div.innerHTML = '<span style="color:' + color + ';font-weight:700;min-width:1.2rem;">' + (i + 1) + '.</span>' +
                            '<span>' + (isCritical ? '<span style="color:' + color + ';font-weight:600;">' + icon + ' </span>' : '') + esc(a.replace('[CRITICAL] ','')) + '</span>';
                        al.appendChild(div);
                    });
                } else {
                    al.innerHTML = '<div style="padding:0.5rem;text-align:center;color:#888;font-size:0.8rem;">No urgent actions needed.</div>';
                }

                // ── AI Recommendations ──
                const aiList = document.getElementById('rcAIList');
                aiList.innerHTML = '';
                if (d.ai_recommendations && d.ai_recommendations.length) {
                    const priorityColors = {critical:'#c62828',high:'#e65100',medium:'#f9a825',low:'#388e3c'};
                    d.ai_recommendations.forEach(r => {
                        const pCol = priorityColors[r.priority] || '#888';
                        const card = document.createElement('div');
                        card.style.cssText = 'padding:0.5rem 0.6rem;border-radius:4px;margin-bottom:0.4rem;border-left:3px solid ' + pCol + ';font-size:0.8rem;';
                        card.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;gap:0.3rem;">' +
                            '<span style="font-weight:600;color:#333;">' + esc(r.title) + '</span>' +
                            '<span style="font-size:0.6rem;background:' + pCol + ';color:#fff;padding:0 6px;border-radius:8px;white-space:nowrap;">' + r.priority + '</span></div>' +
                            (r.description ? '<div style="font-size:0.75rem;color:#555;margin-top:0.2rem;">' + esc(r.description) + '</div>' : '') +
                            (r.rationale ? '<div style="font-size:0.7rem;color:#888;font-style:italic;margin-top:0.15rem;">' + esc(r.rationale) + '</div>' : '') +
                            (r.action_items && r.action_items.length ? '<div style="font-size:0.72rem;color:#666;margin-top:0.15rem;"><strong>Actions:</strong> ' + r.action_items.join('; ') + '</div>' : '');
                        aiList.appendChild(card);
                    });
                } else {
                    aiList.innerHTML = '<div style="padding:0.6rem;text-align:center;background:#fff8e1;border-radius:4px;font-size:0.8rem;color:#888;">' +
                        __('No AI recommendations available.') + '<br><a href="javascript:void(0)" onclick="SwitchTab(\'settings\')" style="color:#3f51b5;">' +
                        __('Configure AI provider') + '</a></div>';
                }

                // ── Rule Failures ──
                const rf = document.getElementById('rcRuleFailures');
                rf.innerHTML = '';
                if (d.top_rule_failures && d.top_rule_failures.length) {
                    rf.innerHTML = d.top_rule_failures.map(f => {
                        const sev = f.severity === 'CRITICAL' ? '#c62828' : f.severity === 'HIGH' ? '#e65100' : '#f9a825';
                        return '<div style="padding:0.35rem 0;border-bottom:1px solid #f0f0f0;">' +
                            '<div style="display:flex;align-items:center;gap:0.4rem;">' +
                                '<span style="width:8px;height:8px;border-radius:50%;background:' + sev + ';flex-shrink:0;"></span>' +
                                '<span style="font-weight:600;font-size:0.78rem;">' + esc(f.rule_code) + '</span>' +
                                '<span style="font-size:0.68rem;color:#999;">' + f.failure_rate + '%</span>' +
                            '</div>' +
                            '<div style="font-size:0.72rem;color:#555;margin:0.1rem 0 0 1.2rem;">' + esc((f.description || f.primary_cause || '').slice(0, 90)) + '</div>' +
                            '</div>';
                    }).join('');
                } else { rf.innerHTML = '<div style="padding:0.5rem;text-align:center;color:#888;font-size:0.78rem;">No rule failures found.</div>'; }

                // ── Quality Drivers ──
                const qd = document.getElementById('rcQualityDrivers');
                qd.innerHTML = '';
                if (d.quality_drivers && d.quality_drivers.length) {
                    qd.innerHTML = d.quality_drivers.map(q => {
                        const statusColor = q.status === 'good' ? '#2e7d32' : q.status === 'needs_improvement' ? '#e65100' : '#c62828';
                        const barColor = q.status === 'good' ? '#4caf50' : q.status === 'needs_improvement' ? '#ff9800' : '#f44336';
                        return '<div style="margin-bottom:0.5rem;">' +
                            '<div style="display:flex;justify-content:space-between;font-size:0.78rem;margin-bottom:0.15rem;">' +
                                '<span style="font-weight:600;">' + q.component + '</span>' +
                                '<span style="color:' + statusColor + ';font-weight:600;">' + q.value + '%</span>' +
                            '</div>' +
                            '<div style="height:6px;background:#f0f0f0;border-radius:3px;overflow:hidden;">' +
                                '<div style="width:' + Math.min(q.value, 100) + '%;height:100%;background:' + barColor + ';border-radius:3px;transition:width 0.3s;"></div>' +
                            '</div>' +
                            '<div style="font-size:0.68rem;color:#888;margin-top:0.1rem;">Impact gap: ' + q.impact + ' pts &mdash; ' + (q.recommendation || '').slice(0, 60) + '</div>' +
                            '</div>';
                    }).join('');
                } else { qd.innerHTML = '<div style="padding:0.5rem;text-align:center;color:#888;font-size:0.78rem;">No data available.</div>'; }

                // ── Confidence Gaps ──
                const cg = document.getElementById('rcConfidenceGaps');
                cg.innerHTML = '';
                if (d.confidence_gaps && d.confidence_gaps.length) {
                    cg.innerHTML = d.confidence_gaps.map(g => {
                        const levelColor = g.level === 'CRITICAL' ? '#c62828' : g.level === 'LOW' ? '#e65100' : '#f9a825';
                        return '<div style="padding:0.35rem 0;border-bottom:1px solid #f0f0f0;">' +
                            '<div style="display:flex;align-items:center;gap:0.4rem;">' +
                                '<span style="font-size:0.65rem;background:' + levelColor + ';color:#fff;padding:0 5px;border-radius:3px;font-weight:600;">' + g.level + '</span>' +
                                '<span style="font-weight:600;font-size:0.78rem;">' + esc((g.indicator_name || '').slice(0, 35)) + '</span>' +
                                '<span style="font-size:0.68rem;color:#999;">' + g.confidence + '</span>' +
                            '</div>' +
                            '<div style="font-size:0.7rem;color:#666;margin:0.1rem 0 0 0;">Signal: ' + (g.weakest_signal || '') + ' | ' + esc((g.root_cause || '').slice(0, 90)) + '</div>' +
                            '</div>';
                    }).join('');
                } else { cg.innerHTML = '<div style="padding:0.5rem;text-align:center;color:#888;font-size:0.78rem;">No confidence gaps found.</div>'; }

                // ── Anomaly Patterns ──
                const ap = document.getElementById('rcAnomalyPatterns');
                ap.innerHTML = '';
                if (d.anomaly_patterns && d.anomaly_patterns.length) {
                    ap.innerHTML = d.anomaly_patterns.map(a => {
                        const typeColor = a.pattern_type === 'severe' ? '#c62828' : a.pattern_type === 'moderate' ? '#e65100' : '#f9a825';
                        const typeLabel = a.pattern_type === 'severe' ? 'Severe' : a.pattern_type === 'moderate' ? 'Moderate' : 'Mild';
                        return '<div style="padding:0.35rem 0;border-bottom:1px solid #f0f0f0;">' +
                            '<div style="display:flex;align-items:center;gap:0.4rem;">' +
                                '<span style="font-size:0.65rem;background:' + typeColor + ';color:#fff;padding:0 5px;border-radius:3px;font-weight:600;">' + typeLabel + '</span>' +
                                '<span style="font-weight:600;font-size:0.78rem;">' + esc((a.rate_name || '').slice(0, 35)) + '</span>' +
                            '</div>' +
                            '<div style="font-size:0.7rem;color:#666;margin:0.1rem 0 0 0;">|z| = ' + a.avg_z_score + (a.recurrence_count ? ' | Recurring ' + a.recurrence_count + 'x' : '') + '</div>' +
                            '</div>';
                    }).join('');
                } else { ap.innerHTML = '<div style="padding:0.5rem;text-align:center;color:#888;font-size:0.78rem;">No anomaly patterns found.</div>'; }

            }).catch(e => {
                document.getElementById('rcLoading').style.display = 'none';
                document.getElementById('rcContent').style.display = 'block';
                document.getElementById('rcSummary').innerHTML = '<p style="color:#c62828;">Error: ' + e.message + '</p>';
            });
        }

        export function initRootCause() {
            const hsel = document.getElementById('rcHospital');
            const msel = document.getElementById('rcMonth');
            const phH = '<option value="">Select hospital</option>';
            const phM = '<option value="">Select month</option>';
            hsel.innerHTML = phH;
            msel.innerHTML = phM;
            Promise.all([
                apiGet('/hospitals/').then(data => {
                    const list = data.value || data || [];
                    hsel.innerHTML = phH + list.map(h => '<option value="' + h.id + '">' + h.name + '</option>').join('');
                }),
                populateMonthSelect('rcMonth', false),
            ]).then(() => {
                _restoreUIState('root-cause');
                if (hsel.value && msel.value) loadRootCause();
            }).catch(() => {
                _restoreUIState('root-cause');
            });
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
        let trendChartInstance = null, yoyChartInstance = null, confidenceChartInstance = null, radarChartInstance = null;

        function renderKpiCards(hid) {
            let url = '/dashboard/kpi?';
            if (hid) url += 'hospital_id=' + hid + '&';
            apiGet(url).then(data => {
                const container = document.getElementById('dashKpiCards');
                container.innerHTML = (data.kpis || []).map(k => {
                    const pct = k.target ? Math.min(k.value / k.target, 1) : 1;
                    const bg = k.higher_is_better
                        ? (pct >= 1 ? '#e8f5e9' : pct >= 0.75 ? '#fff8e1' : '#ffebee')
                        : (pct <= 1 ? '#e8f5e9' : '#ffebee');
                    const valColor = k.higher_is_better
                        ? (pct >= 1 ? '#2e7d32' : pct >= 0.75 ? '#e65100' : '#c62828')
                        : (pct <= 1 ? '#2e7d32' : '#c62828');
                    const barPct = Math.min(pct * 100, 100);
                    const barColor = k.higher_is_better
                        ? (pct >= 1 ? '#4caf50' : pct >= 0.75 ? '#ff9800' : '#f44336')
                        : (pct <= 1 ? '#4caf50' : '#f44336');
                    return '<div class="card" style="text-align:left;padding:0.8rem 1rem;background:' + bg + ';">' +
                        '<div style="display:flex;justify-content:space-between;align-items:baseline;">' +
                        '<span style="font-size:0.75rem;color:#555;font-weight:500;">' + k.label + '</span>' +
                        '<span style="font-size:1.1rem;font-weight:700;color:' + valColor + ';">' + k.value + (k.unit ? '<span style="font-size:0.7rem;margin-left:2px;">' + k.unit + '</span>' : '') + '</span></div>' +
                        (k.target ? '<div style="margin-top:4px;display:flex;align-items:center;gap:4px;"><div style="flex:1;height:5px;background:#ddd;border-radius:3px;"><div style="width:' + barPct + '%;height:5px;background:' + barColor + ';border-radius:3px;transition:width 0.4s;"></div></div><span style="font-size:0.65rem;color:#888;">target ' + k.target + '</span></div>' : '') +
                        '</div>';
                }).join('');
            }).catch(() => {});
        }

        function renderYoyChart(hid) {
            let url = '/dashboard/yoy?';
            if (hid) url += 'hospital_id=' + hid;
            apiGet(url).then(d => {
                if (yoyChartInstance) yoyChartInstance.destroy();
                const canvas = document.getElementById('yoyChart');
                if (!d.labels || !d.labels.length) {
                    canvas.parentElement.innerHTML = '<p style="font-size:0.85rem;color:#888;text-align:center;padding:1rem;">No data for year-over-year comparison.</p>';
                    return;
                }
                const colors = ['#3f51b5', '#ff5722', '#4caf50', '#ff9800'];
                const datasets = (d.years || []).map((y, i) => ({
                    label: String(y),
                    data: d.labels.map(m => (d.data['year_' + y] || {})[m] ?? null),
                    borderColor: colors[i % colors.length],
                    backgroundColor: colors[i % colors.length] + '22',
                    fill: false,
                    tension: 0.3,
                    pointRadius: 4,
                }));
                const ctx = canvas.getContext('2d');
                yoyChartInstance = new Chart(ctx, {
                    type: 'line',
                    data: { labels: d.labels, datasets },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { position: 'top', labels: { font: { size: 10 } } } },
                        scales: { y: { min: 0, max: 100, ticks: { callback: v => v + '%' } } }
                    }
                });
            }).catch(() => {});
        }

        export function loadDashboard() {
            _saveUIState('dashboard');
            const hid = document.getElementById('dashHospital').value;
            const yr = document.getElementById('dashYear').value;
            document.getElementById('dashLoading').style.display = 'inline';

            let url = '/dashboard/overview?';
            if (hid) url += 'hospital_id=' + hid + '&';
            if (yr) url += 'year=' + yr;

            apiGet(url).then(data => {
                document.getElementById('dashHospitals').textContent = data.total_hospitals;
                document.getElementById('dashReports').textContent = data.total_reports;
                document.getElementById('dashAvgScore').textContent = data.avg_quality_score;
                document.getElementById('dashAlerts').textContent = data.total_alerts;

                // KPI cards
                renderKpiCards(hid);

                // Trend line chart
                if (trendChartInstance) trendChartInstance.destroy();
                const trendCtx = document.getElementById('trendChart').getContext('2d');
                trendChartInstance = new Chart(trendCtx, {
                    type: 'line',
                    data: {
                        labels: data.quality_trend.map(d => d.month),
                        datasets: [{
                            label: __('Quality Score'),
                            data: data.quality_trend.map(d => d.score),
                            borderColor: '#3f51b5',
                            backgroundColor: 'rgba(63,81,181,0.1)',
                            fill: true,
                            tension: 0.3,
                            pointRadius: 4,
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: { y: { min: 0, max: 100, ticks: { callback: v => v + '%' } } }
                    }
                });

                // YoY chart
                renderYoyChart(hid);

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
                            backgroundColor: ['#c62828', '#e65100', '#f9a825', '#2e7d32'],
                            borderWidth: 0,
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { position: 'bottom', labels: { font: { size: 10 } } } }
                    }
                });

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
                            backgroundColor: 'rgba(63,81,181,0.2)',
                            borderColor: '#3f51b5',
                            pointBackgroundColor: '#3f51b5',
                            pointRadius: 3,
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        scales: { r: { min: 0, max: 100, ticks: { stepSize: 20, font: { size: 9 } } } },
                        plugins: { legend: { display: false } }
                    }
                });

                document.getElementById('dashLoading').style.display = 'none';
                // Load heatmap
                loadHeatmap(hid);
            }).catch(e => {
                document.getElementById('dashLoading').style.display = 'none';
                console.error('Dashboard error:', e);
            });
        }

        function loadHeatmap(hospitalId, month) {
            let url = '/analysis/heatmap?';
            if (month) url += 'month=' + month + '&';
            apiGet(url).then(hm => {
                const container = document.getElementById('heatmapContainer');
                if (!hm.data || !hm.data.length) {
                    container.innerHTML = '<div class="empty-state"><div class="empty-icon">📊</div><div class="empty-text">' + __('No data for heatmap') + '</div></div>';
                    return;
                }
                const months = hm.months;
                let html = '<table style="font-size:0.72rem;border-collapse:collapse;width:100%;"><thead><tr>' +
                    '<th style="padding:0.3rem;text-align:left;position:sticky;left:0;background:#f5f5f5;z-index:1;">Hospital</th>';
                months.forEach(m => { html += '<th style="padding:0.3rem;text-align:center;min-width:60px;">' + m + '</th>'; });
                html += '<th style="padding:0.3rem;text-align:center;min-width:50px;">Avg</th></tr></thead><tbody>';
                hm.data.forEach(d => {
                    const vals = months.map(m => d[m]).filter(v => v !== null);
                    const avg = vals.length ? (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(1) : '--';
                    html += '<tr><td style="padding:0.2rem 0.4rem;font-weight:600;position:sticky;left:0;background:#fff;z-index:1;">' + d.hospital + '</td>';
                    months.forEach(m => {
                        const v = d[m];
                        if (v === null) { html += '<td style="text-align:center;padding:0.2rem;background:#f5f5f5;color:#ccc;">--</td>'; return; }
                        const pct = Math.min(v / 100, 1);
                        const r = Math.round(255 * (1 - pct));
                        const g = Math.round(255 * pct);
                        html += '<td style="text-align:center;padding:0.2rem;background:rgb(' + r + ',' + g + ',50);color:' + (pct > 0.5 ? 'white' : '#333') + ';font-weight:600;">' + v.toFixed(1) + '</td>';
                    });
                    html += '<td style="text-align:center;padding:0.2rem;font-weight:700;">' + avg + '</td></tr>';
                });
                html += '</tbody></table>';
                container.innerHTML = html;
            }).catch(() => {
                document.getElementById('heatmapContainer').innerHTML = '<p style="color:#888;text-align:center;padding:1rem;font-size:0.85rem;">Heatmap unavailable.</p>';
            });
        }

        export function initDashboard() {
            const hsel = document.getElementById('dashHospital');
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
            apiGet('/dashboard/yoy').then(d => {
                const ysel = document.getElementById('dashYear');
                const cur = ysel.value;
                ysel.innerHTML = '<option value="">All Years</option>' +
                    (d.years || []).map(y => '<option value="' + y + '">' + y + '</option>').join('');
                if (cur) ysel.value = cur;
            }).catch(() => {});
        }

        export function loadAllSettings() {
            document.getElementById('settingsLoading').classList.remove('hidden');
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
                document.getElementById('settingsLoading').classList.add('hidden');
            });
        }

        export function saveAllSettings() {
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
                document.getElementById('settingsStatus').style.color = '#2e7d32';
                setTimeout(() => { document.getElementById('settingsStatus').textContent = ''; }, 3000);
            }).catch(e => {
                document.getElementById('settingsStatus').textContent = '\u2717 Error: ' + e.message;
                document.getElementById('settingsStatus').style.color = '#c62828';
            });
        }

        export function reanalyzeAll(btn) {
            const originalText = btn.textContent;
            btn.textContent = '...';
            btn.disabled = true;
            showLoader('Re-analyzing all hospitals...');
            apiPost('/analysis/reanalyze-all?force=true').then(data => {
                const statusEl = document.getElementById('settingsStatus');
                statusEl.textContent = '\u2713 Re-analyzed ' + data.total_runs + ' combinations (' + data.hospitals_processed + ' hospitals, ' + data.months_processed + ' months)';
                statusEl.style.color = '#2e7d32';
                if (data.errors && data.errors.length) {
                    statusEl.textContent += ' | Errors: ' + data.errors.length;
                    statusEl.style.color = '#e65100';
                }
                // Redirect to dashboard to show fresh data
                switchTab('dashboard');
            }).catch(e => {
                const statusEl = document.getElementById('settingsStatus');
                statusEl.textContent = '\u2717 Error: ' + e.message;
                statusEl.style.color = '#c62828';
            }).finally(() => {
                hideLoader();
                btn.textContent = originalText;
                btn.disabled = false;
            });
        }

        export function loadAiSettings() {
            return fetch(API() + '/config/ai/settings').then(r => r.json()).then(cfg => {
                document.getElementById('ai_enabled').value = cfg.ai_enabled || 'true';
                document.getElementById('ai_provider').value = cfg.ai_provider || 'gemini';
                document.getElementById('ai_api_key').value = cfg.ai_api_key || '';
                document.getElementById('ai_model').value = cfg.ai_model || 'gemini-2.0-flash-lite';
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
            status.style.color = '#1565c0';
            fetch(API() + '/config/ai/settings', {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(updates),
            }).then(r => r.json()).then(() => {
                status.textContent = '\u2713 Saved. AI config will be used on next analysis.';
                status.style.color = '#2e7d32';
                setTimeout(() => { status.textContent = ''; }, 4000);
            }).catch(e => {
                status.textContent = '\u2717 Error: ' + e.message;
                status.style.color = '#c62828';
            });
        }

        export function onAiProviderChange() {
            const provider = document.getElementById('ai_provider').value;
            const urlRow = document.getElementById('ai_api_url_row');
            const modelInput = document.getElementById('ai_model');
            const urlInput = document.getElementById('ai_api_url');
            if (provider === 'gemini') {
                urlRow.style.display = 'none';
                if (!modelInput.value || !modelInput.value.startsWith('gemini')) {
                    modelInput.value = 'gemini-2.0-flash-lite';
                }
            } else if (provider === 'deepseek') {
                urlRow.style.display = 'none';
                if (!modelInput.value || !modelInput.value.startsWith('deepseek')) {
                    modelInput.value = 'deepseek-chat';
                    if (!urlInput.value) urlInput.value = 'https://api.deepseek.com/v1/chat/completions';
                }
            } else if (provider === 'minimax') {
                urlRow.style.display = '';
                if (!modelInput.value || !modelInput.value.startsWith('minimax')) {
                    modelInput.value = 'minimax-abab5.5s-chat';
                }
            } else if (provider === 'kimi') {
                urlRow.style.display = '';
                if (!modelInput.value || !modelInput.value.startsWith('moonshot')) {
                    modelInput.value = 'moonshot-v1-8k';
                    if (!urlInput.value) urlInput.value = 'https://api.moonshot.cn/v1/chat/completions';
                }
            } else {
                urlRow.style.display = '';
                if (!modelInput.value || modelInput.value.startsWith('deepseek') || modelInput.value.startsWith('minimax') || modelInput.value.startsWith('moonshot')) {
                    modelInput.value = 'gpt-4o-mini';
                    if (!urlInput.value) urlInput.value = 'https://api.openai.com/v1/chat/completions';
                }
            }
        }

        export function loadRulesManager() {
            const typeFilter = document.getElementById('rulesTypeFilter').value;
            const sevFilter = document.getElementById('rulesSeverityFilter').value;
            const enabledFilter = document.getElementById('rulesEnabledFilter').value;
            let url = API() + '/rules/?';
            if (typeFilter) url += 'rule_type=' + encodeURIComponent(typeFilter) + '&';
            if (sevFilter) url += 'severity=' + encodeURIComponent(sevFilter) + '&';
            if (enabledFilter) url += 'enabled=' + enabledFilter + '&';
            const tbody = document.getElementById('rulesTbody');
            document.getElementById('rulesLoading').classList.remove('hidden');
            tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;padding:1.5rem;color:#888;">Loading rules...</td></tr>';
            fetch(url)
                .then(r => r.json())
                .then(data => {
                    document.getElementById('rulesLoading').classList.add('hidden');
                    rulesManagerData = data;
                    renderRulesManager();
                })
                .catch(e => {
                    document.getElementById('rulesLoading').classList.add('hidden');
                    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#a00;">Error: ' + e.message + '</td></tr>';
                });
        }

        function renderRulesManager() {
            document.getElementById('rulesManagerCount').textContent = rulesManagerData.length + ' rule(s)';
            const filtered = document.getElementById('rulesTbody');
            if (!rulesManagerData.length) {
                filtered.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#888;padding:2rem;">No rules found.</td></tr>';
                return;
            }
            const typeColors = {'LOGIC': '#1565c0', 'CLINICAL': '#6a1b9a', 'BENCHMARK': '#e65100', 'DATA_QUALITY': '#c62828'};
            const sevClass = {'CRITICAL': 'badge-critical', 'HIGH': 'badge-high', 'MEDIUM': 'badge-medium', 'LOW': 'badge-low'};
            let html = '';
            rulesManagerData.forEach((r, idx) => {
                const tc = typeColors[r.rule_type] || '#666';
                const typeB = '<span class="badge" style="background:'+tc+'22;color:'+tc+';border:1px solid '+tc+'44;">'+r.rule_type+'</span>';
                const sevB = '<span class="badge ' + (sevClass[r.severity] || 'badge-low') + '">' + r.severity + '</span>';
                const enabledIcon = r.enabled
                    ? '<span class="tree-toggle on" style="cursor:pointer;" title="Click to disable">✓</span>'
                    : '<span class="tree-toggle off" style="cursor:pointer;" title="Click to enable">✗</span>';
                html += '<tr class="rule-row" draggable="true" data-id="' + r.id + '" data-code="' + esc(r.code) + '">' +
                    '<td style="cursor:grab;color:#bbb;font-size:0.9rem;user-select:none;">⠿</td>' +
                    '<td><code>' + esc(r.code) + '</code></td>' +
                    '<td>' + esc(r.name) + '</td>' +
                    '<td>' + typeB + '</td>' +
                    '<td>' + sevB + '</td>' +
                    '<td style="font-size:0.75rem;color:#666;">' + esc(r.category) + '</td>' +
                    '<td style="font-size:0.75rem;font-family:Consolas,monospace;color:#888;">' + esc(r.expression_type) + '</td>' +
                    '<td style="text-align:center;" class="rule-toggle-cell" data-id="' + r.id + '">' + enabledIcon + '</td>' +
                    '<td style="white-space:nowrap;"><button class="btn btn-sm btn-outline" onclick="openRuleModal(' + r.id + ')" style="font-size:0.65rem;padding:0.15rem 0.4rem;">Edit</button> <button class="btn btn-sm btn-outline" onclick="deleteRule(' + r.id + ',\'' + esc(r.code) + '\')" style="font-size:0.65rem;padding:0.15rem 0.4rem;color:#c62828;border-color:#ef5350;">Del</button></td>' +
                    '</tr>';
            });
            filtered.innerHTML = html;
            document.getElementById('rulesManagerFilteredCount').textContent = rulesManagerData.length + ' shown';

            // Wire toggle clicks
            filtered.querySelectorAll('.rule-toggle-cell').forEach(cell => {
                cell.addEventListener('click', function(e) {
                    e.stopPropagation();
                    const ruleId = this.dataset.id;
                    const toggleEl = this.querySelector('.tree-toggle');
                    if (toggleEl.classList.contains('loading')) return;
                    toggleEl.classList.add('loading');
                    fetch(API() + '/rules/' + ruleId + '/toggle', { method: 'PUT' })
                        .then(r => r.json())
                        .then(data => {
                            toggleEl.textContent = data.enabled ? '✓' : '✗';
                            toggleEl.className = 'tree-toggle ' + (data.enabled ? 'on' : 'off');
                            toggleEl.classList.remove('loading');
                            toggleEl.title = data.enabled ? 'Click to disable' : 'Click to enable';
                            // Update data
                            const rule = rulesManagerData.find(x => x.id == ruleId);
                            if (rule) rule.enabled = data.enabled;
                        })
                        .catch(e => {
                            toggleEl.classList.remove('loading');
                            alert('Toggle failed: ' + e.message);
                        });
                });
            });

            // Wire drag-and-drop
            const rows = filtered.querySelectorAll('.rule-row');
            let dragId = null;
            rows.forEach(row => {
                row.addEventListener('dragstart', function(e) {
                    this.classList.add('dragging');
                    dragId = this.dataset.id;
                    e.dataTransfer.effectAllowed = 'move';
                    e.dataTransfer.setData('text/plain', this.dataset.id);
                });
                row.addEventListener('dragend', function() {
                    this.classList.remove('dragging');
                    document.querySelectorAll('.rule-row.drag-over').forEach(el => el.classList.remove('drag-over'));
                    dragId = null;
                });
                row.addEventListener('dragover', function(e) {
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'move';
                    this.classList.add('drag-over');
                });
                row.addEventListener('dragleave', function() {
                    this.classList.remove('drag-over');
                });
                row.addEventListener('drop', function(e) {
                    e.preventDefault();
                    this.classList.remove('drag-over');
                    const fromId = e.dataTransfer.getData('text/plain');
                    if (!fromId || fromId === this.dataset.id) return;
                    const tbody = document.getElementById('rulesTbody');
                    const allRows = Array.from(tbody.querySelectorAll('.rule-row'));
                    const items = [];
                    let dropIdx = 0;
                    allRows.forEach((r, i) => {
                        if (r.dataset.id === this.dataset.id) dropIdx = i;
                    });
                    const ids = allRows.map(r => parseInt(r.dataset.id));
                    const fromIdx = ids.indexOf(parseInt(fromId));
                    const toIdx = ids.indexOf(parseInt(this.dataset.id));
                    if (fromIdx < 0 || toIdx < 0) return;
                    ids.splice(fromIdx, 1);
                    ids.splice(toIdx, 0, parseInt(fromId));
                    ids.forEach((id, i) => {
                        items.push({ id: id, sort_order: i });
                    });
                    fetch(API() + '/rules/reorder', {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({items: items}),
                    }).then(r => r.json()).then(() => {
                        loadRulesManager();
                    }).catch(err => alert('Reorder failed: ' + err.message));
                });
            });
        }

        export const PARAM_TEMPLATES = {
            'ge': '{"parent": "2", "children": ["3", "4", "5"]}',
            'eq': '{"parent": "2", "children": ["2.a", "2.b"]}',
            'le': '{"child": "5.b.1", "parent": "5"}',
            'le_sum': '{"child": "10.a.1", "children": ["10.a.1.1", "10.a.1.2"]}',
            'benchmark_rate': '{"num_code": "5", "den_code": "2", "threshold": 80.0}',
            'benchmark_low_rate': '{"num_code": "3", "den_code": "2", "threshold": 10.0}',
            'cross_hospital_rate': '{"num_code": "6.f", "den_code": "6", "z_threshold": 2.5}',
            'month_over': '{"code": "2", "factor": 2.0}',
            'month_under': '{"code": "2", "factor": 0.5}',
            'neg_check': '{"codes": ["2", "3", "4", "5", "6", "7", "8", "10", "11", "16", "17"]}',
            'decimal_check': '{"codes": ["2", "3", "4", "5", "6", "7", "8", "10", "11", "16", "17"]}',
            'missing': '{"code": "2"}',
            'all_zero': '{"codes": ["2", "3", "4", "5", "6", "7", "8", "10", "11", "16", "17"]}',
        };
        export const PARAM_HINTS = {
            'ge': 'parent indicator code + list of child codes',
            'eq': 'parent indicator code + list of child codes',
            'le': 'child code + parent code',
            'le_sum': 'parent code + list of child codes',
            'benchmark_rate': 'numerator code, denominator code, threshold %',
            'benchmark_low_rate': 'numerator code, denominator code, threshold %',
            'cross_hospital_rate': 'numerator code, denominator code, z_threshold',
            'month_over': 'indicator code, factor (e.g. 2.0)',
            'month_under': 'indicator code, factor (e.g. 0.5)',
            'neg_check': 'list of indicator codes to check',
            'decimal_check': 'list of indicator codes to check',
            'missing': 'indicator code',
            'all_zero': 'list of indicator codes to check',
        };
        export const EXPR_EXPLANATIONS = {
            'ge': {title: 'parent >= sum(children)', text: 'FAILs when the parent indicator value is less than the sum of its child indicators. Use for aggregation checks like Total Deliveries >= NVD + Assisted + C-sections.'},
            'eq': {title: 'parent == sum(children)', text: 'FAILs when the parent value != sum of children. Use for exact equality checks like Male + Female + Unknown = Live Births.'},
            'le': {title: 'child <= parent', text: 'FAILs when child value exceeds parent value. Use for subset checks like Emergency C/S <= Total C-sections.'},
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
        };
        export let ruleEditId = null;
        export let _indicatorsCache = [];
        export let _vbState = {};

        export function loadControlSettings() {
            apiGet('/config/control/settings').then(data => {
                const cb = document.getElementById('cfg_auto_disable_null');
                if (cb) cb.checked = !!data.auto_disable_null_indicators;
                const logCb = document.getElementById('cfg_structured_logging');
                if (logCb) logCb.checked = data.structured_logging_enabled !== false;
            }).catch(() => {});
        }

        export function saveControlSettings() {
            const cb = document.getElementById('cfg_auto_disable_null');
            const logCb = document.getElementById('cfg_structured_logging');
            const val = cb ? cb.checked : false;
            const logVal = logCb ? logCb.checked : true;
            const status = document.getElementById('controlSaveStatus');
            if (status) { status.textContent = 'Saving...'; status.style.color = '#1565c0'; }
            apiPut('/config/control/settings', {
                auto_disable_null_indicators: val ? 'true' : 'false',
                structured_logging_enabled: logVal ? 'true' : 'false',
            }).then(() => {
                if (status) { status.textContent = '\u2713 Saved'; status.style.color = '#2e7d32'; }
            }).catch(e => {
                if (status) { status.textContent = '\u2717 Error: ' + e.message; status.style.color = '#c62828'; }
            });
        }
        }

