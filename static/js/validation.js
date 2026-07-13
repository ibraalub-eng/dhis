        import { apiGet } from './api.js';
        import { __ } from './i18n.js';
        import { _restoreUIState, _saveUIState } from './main.js';

        // ── Quality Trend ──────────────────────────────────────────
        // Combined Trend Analysis
        export function initTrends() {
            const sel = document.getElementById('trendHospitalSelect');
            if (!sel) return;
            if (sel.options.length <= 1) {
                apiGet('/hospitals/').then(data => {
                    const list = data.value || data || [];
                    sel.innerHTML = list.map(h => '<option value="' + h.id + '">' + h.name + '</option>').join('');
                    _restoreUIState('trends');
                    if (sel.value) loadTrends();
                });
            } else {
                _restoreUIState('trends');
                if (sel.value) loadTrends();
            }
        }

        export async function loadTrends() {
            _saveUIState('trends');
            const hid = document.getElementById('trendHospitalSelect').value;
            if (!hid) { alert(__('Select a hospital')); return; }
            const container = document.getElementById('qualityTrendContent');
            const analysisSection = document.getElementById('trendAnalysisSection');
            document.getElementById('trendLoading').classList.remove('hidden');
            container.innerHTML = '<div style="text-align:center;padding:2rem;color:#888;font-size:0.85rem;"><span class="spinner"></span> Loading trends...</div>';
            analysisSection.classList.add('hidden');
            try {
                const [trendData, histData] = await Promise.all([
                    apiGet('/analysis/quality-trend/' + hid),
                    apiGet('/analysis/historical/' + hid),
                ]);
                document.getElementById('trendLoading').classList.add('hidden');
                renderQualityTrend(trendData, container);
                if (histData && histData.summary) {
                    renderTrends(histData);
                    analysisSection.classList.remove('hidden');
                }
            } catch(e) {
                document.getElementById('trendLoading').classList.add('hidden');
                container.innerHTML = '<div class="card" style="text-align:center;padding:2rem;color:#c62828;font-size:0.85rem;">Error loading trends: ' + e.message + '</div>';
            }
        }

        function renderQualityTrend(data, container) {
            if (!data.data || !data.data.length) {
                container.innerHTML = '<div class="card" style="text-align:center;padding:2rem;color:#888;font-size:0.85rem;"><div style="font-size:1.5rem;margin-bottom:0.3rem;opacity:0.3;">&#128200;</div>No quality score history found for this hospital. Run analysis first.</div>';
                return;
            }

            const scores = data.data;
            const values = scores.map(s => s.score);

            // Direction indicators
            const dirColor = data.trend_direction === 'improving' ? '#2e7d32' : data.trend_direction === 'declining' ? '#c62828' : '#e65100';
            const dirArrow = data.trend_direction === 'improving' ? '&#9650;' : data.trend_direction === 'declining' ? '&#9660;' : '&#9654;';

            // Summary stats
            let changeHtml = '';
            if (data.change !== null) {
                const changeColor = data.change >= 0 ? '#2e7d32' : '#c62828';
                const changeArrow = data.change >= 0 ? '&#9650;' : '&#9660;';
                changeHtml = `<span style="color:${changeColor};font-weight:700;">${changeArrow} ${Math.abs(data.change).toFixed(1)} pts</span>`;
            }

            let declineHtml = '';
            if (data.consecutive_declines > 0) {
                declineHtml = `<span style="color:#c62828;font-weight:700;">&#9660; ${data.consecutive_declines} consecutive decline${data.consecutive_declines > 1 ? 's' : ''}</span>`;
            }

            // Build SVG chart
            const mn = Math.min(...values), mx = Math.max(...values), range = mx - mn || 1;
            const pad = 10;
            const w = 600, h = 200;
            const chartW = w - pad * 2, chartH = h - pad * 2;
            let path = '', areaPath = '';
            const labels = scores.map(s => s.month);
            const n = values.length;

            let prevX = 0, prevY = 0;
            values.forEach((v, i) => {
                const x = pad + (i / (n - 1)) * chartW;
                const y = pad + chartH - ((v - mn) / range) * chartH;
                path += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1);
                areaPath += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1);
                prevX = x; prevY = y;
            });
            areaPath += 'L' + prevX.toFixed(1) + ',' + (pad + chartH) + 'L' + pad.toFixed(1) + ',' + (pad + chartH) + 'Z';

            const lineColor = data.trend_direction === 'improving' ? '#4caf50' : data.trend_direction === 'declining' ? '#f44336' : '#ff9800';

            // Score circles + tooltip for each point
            let circles = '';
            scores.forEach((s, i) => {
                const x = pad + (i / (n - 1)) * chartW;
                const y = pad + chartH - ((s.score - mn) / range) * chartH;
                circles += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="5" fill="${lineColor}" stroke="white" stroke-width="2">
                    <title>${s.month}: ${s.score}/100 (Completeness: ${s.completeness || '--'}, Compliance: ${s.rule_compliance || '--'}, Issues: ${s.issues_count})</title>
                </circle>`;
            });

            // X-axis labels
            let xLabels = '';
            const step = Math.max(1, Math.floor(n / 8));
            labels.forEach((l, i) => {
                if (i % step === 0 || i === n - 1) {
                    const x = pad + (i / (n - 1)) * chartW;
                    xLabels += `<text x="${x.toFixed(1)}" y="${h - 2}" text-anchor="middle" font-size="11" fill="#888">${l}</text>`;
                }
            });

            // Y-axis labels
            const ySteps = 5;
            let yLabels = '';
            for (let i = 0; i <= ySteps; i++) {
                const val = mn + (range / ySteps) * i;
                const y = pad + chartH - (i / ySteps) * chartH;
                yLabels += `<text x="${pad - 3}" y="${y + 4}" text-anchor="end" font-size="11" fill="#888">${Math.round(val)}</text>`;
                yLabels += `<line x1="${pad}" y1="${y}" x2="${w - pad}" y2="${y}" stroke="#eee" stroke-width="1"/>`;
            }

            const svg = `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="width:100%;max-width:${w}px;">
                <defs><linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stop-color="${lineColor}" stop-opacity="0.2"/>
                    <stop offset="100%" stop-color="${lineColor}" stop-opacity="0.02"/>
                </linearGradient></defs>
                ${yLabels}
                <path d="${areaPath}" fill="url(#areaGrad)"/>
                <path d="${path}" fill="none" stroke="${lineColor}" stroke-width="3" stroke-linejoin="round"/>
                ${circles}
                ${xLabels}
            </svg>`;

            const currentColor = data.current_score >= 80 ? '#2e7d32' : data.current_score >= 50 ? '#e65100' : '#c62828';

            const pill = 'display:inline-flex;flex-direction:column;align-items:center;gap:0.15rem;padding:0.4rem 0.8rem;border-radius:6px;font-size:0.72rem;';
            container.innerHTML = `
                <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.8rem;">
                    <div style="${pill}background:${currentColor}11;border:1px solid ${currentColor}44;min-width:80px;">
                        <span style="font-size:1.2rem;font-weight:700;color:${currentColor};">${data.current_score}</span>
                        <span style="color:${currentColor}88;">Current Score</span>
                    </div>
                    <div style="${pill}background:${dirColor}11;border:1px solid ${dirColor}44;min-width:80px;">
                        <span style="font-size:1.2rem;font-weight:700;color:${dirColor};">${dirArrow} ${data.trend_direction}</span>
                        <span style="color:${dirColor}88;">Trend</span>
                    </div>
                    <div style="${pill}background:#33311;border:1px solid #33344;min-width:80px;">
                        <span style="font-size:1.2rem;font-weight:700;color:#333;">${data.avg_score}</span>
                        <span style="color:#888;">Average</span>
                    </div>
                    <div style="${pill}background:#2e7d3211;border:1px solid #2e7d3244;min-width:80px;">
                        <span style="font-size:1.2rem;font-weight:700;color:#2e7d32;">${data.max_score}</span>
                        <span style="color:#2e7d3288;">Best</span>
                    </div>
                    <div style="${pill}background:#c6282811;border:1px solid #c6282844;min-width:80px;">
                        <span style="font-size:1.2rem;font-weight:700;color:#c62828;">${data.min_score}</span>
                        <span style="color:#c6282888;">Worst</span>
                    </div>
                    <div style="${pill}background:#e6510011;border:1px solid #e6510044;min-width:80px;">
                        <span style="font-size:1rem;font-weight:700;color:#e65100;">${changeHtml || '--'}</span>
                        <span style="color:#e6510088;">vs Last Month</span>
                    </div>
                </div>
                ${declineHtml ? `<div style="background:#ffebee;border:1px solid #ef9a9a;border-radius:4px;padding:0.4rem 0.8rem;margin-bottom:0.8rem;font-size:0.82rem;color:#c62828;">${declineHtml}</div>` : ''}
                <div style="text-align:center;">${svg}</div>
            `;
        }

        function renderTrends(data) {
            const summary = data.summary;
            const sDiv = document.getElementById('trendSummary');
            const tPill = 'display:inline-flex;align-items:center;gap:0.2rem;border-radius:4px;padding:0.15rem 0.5rem;font-size:0.7rem;';
            sDiv.innerHTML =
                '<span style="' + tPill + 'background:#33311;border:1px solid #33344;"><span style="font-weight:700;color:#333;">' + summary.total_rates_analyzed + '</span><span style="color:#888;">Rates</span></span>' +
                '<span style="' + tPill + 'background:#e6510011;border:1px solid #e6510044;"><span style="font-weight:700;color:#e65100;">' + summary.increasing_trends + '</span><span style="color:#e6510066;">Increasing</span></span>' +
                '<span style="' + tPill + 'background:#1565c011;border:1px solid #1565c044;"><span style="font-weight:700;color:#1565c0;">' + summary.decreasing_trends + '</span><span style="color:#1565c066;">Decreasing</span></span>' +
                '<span style="' + tPill + 'background:#c6282811;border:1px solid #c6282844;"><span style="font-weight:700;color:#c62828;">' + summary.critical_trends + '</span><span style="color:#c6282866;">Critical</span></span>' +
                '<span style="' + tPill + 'background:#7b1fa211;border:1px solid #7b1fa244;"><span style="font-weight:700;color:#7b1fa2;">' + summary.trend_outliers + '</span><span style="color:#7b1fa266;">Outliers</span></span>' +
                '<span style="' + tPill + 'background:#2e7d3211;border:1px solid #2e7d3244;"><span style="font-weight:700;color:#2e7d32;">' + summary.significant_trends + '</span><span style="color:#2e7d3266;">Significant</span></span>';

            const tbody = document.getElementById('trendTbody');
            tbody.innerHTML = '';
            data.trends.forEach(t => {
                const dirBadge = '<span class="badge badge-' + t.trend_direction + '">' + t.trend_direction + '</span>';
                const sevBadge = '<span class="badge badge-' + t.trend_severity.toLowerCase() + '">' + t.trend_severity + '</span>';
                const sparkline = '<span class="trend-indicator">' + renderSparkline(t.values) + '</span>';
                const findings = t.findings.length ? t.findings.slice(0,2).join('; ') : '-';
                tbody.innerHTML += '<tr><td>' + t.rate_name + '<br>' + sparkline + '</td><td>' + dirBadge + '</td><td>' + sevBadge + '</td><td>' + (t.slope_pct >= 0 ? '+' : '') + t.slope_pct.toFixed(1) + '%</td><td>' + t.cv.toFixed(1) + '%</td><td>' + (t.last_vs_mean_pct_change >= 0 ? '+' : '') + t.last_vs_mean_pct_change.toFixed(1) + '%</td><td>' + t.consecutive_count + ' ' + t.consecutive_direction + '</td><td style="font-size:0.8rem;max-width:200px;">' + findings + '</td></tr>';
            });
        }

        function renderSparkline(values) {
            if (!values || values.length < 2) return '';
            const mn = Math.min(...values), mx = Math.max(...values), range = mx - mn || 1;
            let path = '';
            const w = 80, h = 24;
            values.forEach((v, i) => {
                const x = (i / (values.length - 1)) * w;
                const y = h - ((v - mn) / range) * h;
                path += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1);
            });
            const color = values[values.length-1] > values[0] ? '#e65100' : values[values.length-1] < values[0] ? '#1565c0' : '#2e7d32';
            return '<svg width="' + w + '" height="' + h + '" style="vertical-align:middle;"><path d="' + path + '" fill="none" stroke="' + color + '" stroke-width="2"/></svg>';
        }

        // Hospital Comparison
        export function initCompare() {
            const sel = document.getElementById('compareMonthSelect');
            if (!sel) return;
            if (sel.options.length <= 1) {
                populateMonthSelectFor('compareMonthSelect', () => {
                    _restoreUIState('compare');
                    if (sel.value) loadComparison();
                });
            } else {
                _restoreUIState('compare');
                if (sel.value) loadComparison();
            }
        }

        function populateMonthSelectFor(id, callback) {
            const sel = document.getElementById(id);
            const ph = '<option value="">Select month</option>';
            sel.innerHTML = ph;
            apiGet('/analysis/months').then(months => {
                sel.innerHTML = ph + months.map(m => '<option value="' + m + '">' + m + '</option>').join('');
                if (callback) callback();
            });
        }

        export async function loadComparison() {
            const month = document.getElementById('compareMonthSelect').value;
            if (!month) { alert(__('Select a month')); return; }
            document.getElementById('compareLoading').classList.remove('hidden');
            document.getElementById('compareEmpty').style.display = 'block';
            document.getElementById('compareEmpty').innerHTML = '<div style="font-size:1.3rem;margin-bottom:0.3rem;"><span class="spinner"></span></div><p style="margin:0;font-size:0.85rem;">Loading comparison...</p>';
            document.getElementById('compareTable').style.display = 'none';
            try {
                const data = await apiGet('/analysis/compare?month=' + month);
                document.getElementById('compareLoading').classList.add('hidden');
                // Populate indicator filter
                const filter = document.getElementById('compareIndicatorFilter');
                const currentVal = filter.value;
                const rates = [...new Set(data.map(d => d.rate_name))].sort();
                filter.innerHTML = '<option value="">All Indicators (' + data.length + ')</option>'
                    + rates.map(r => '<option value="' + r.replace(/"/g, '&quot;') + '">' + r + '</option>').join('');
                if (currentVal) filter.value = currentVal;
                window._compareData = data;
                filterComparison();
            } catch(e) {
                document.getElementById('compareLoading').classList.add('hidden');
                document.getElementById('compareEmpty').innerHTML = '<p style="color:#c62828;font-size:0.85rem;">Error: ' + e.message + '</p>';
            }
        }

        export function filterComparison() {
            const data = window._compareData || [];
            const indicator = document.getElementById('compareIndicatorFilter').value;
            const filtered = indicator ? data.filter(d => d.rate_name === indicator) : data;
            renderComparison(filtered);
        }

        function renderComparison(data) {
            const tbody = document.getElementById('compareTbody');
            const empty = document.getElementById('compareEmpty');
            const table = document.getElementById('compareTable');
            if (!data || !data.length) {
                empty.style.display = 'block';
                empty.innerHTML = '<div style="font-size:1.5rem;margin-bottom:0.3rem;opacity:0.3;">&#128200;</div><p style="margin:0;font-size:0.85rem;">No comparison data for this month.</p>';
                table.style.display = 'none';
                return;
            }
            empty.style.display = 'none';
            table.style.display = '';
            tbody.innerHTML = '';
            data.forEach(c => {
                const labelClass = c.comparison_label.includes('critically') ? 'badge-critical' : c.comparison_label.includes('significantly') ? 'badge-high' : c.comparison_label.includes('above') ? 'badge-medium' : c.comparison_label.includes('below') ? 'badge-low' : 'badge-pass';
                tbody.innerHTML += '<tr><td>' + c.hospital + '</td><td>' + c.rate_name + '</td><td>' + c.value.toFixed(2) + '</td><td>' + c.benchmark.toFixed(2) + '</td><td>' + (c.deviation_pct >= 0 ? '+' : '') + c.deviation_pct.toFixed(1) + '%</td><td>' + c.percentile_rank.toFixed(0) + '</td><td><span class="badge ' + labelClass + '">' + c.comparison_label + '</span></td></tr>';
            });
        }

        // Clinical Intelligence
        export async function loadClinical() {
            _saveUIState('clinical');
            const hospSel = document.getElementById('clinicalHospitalSelect');
            const monthSel = document.getElementById('clinicalMonthSelect');
            if (!hospSel.value || !monthSel.value) {
                document.getElementById('clinicalResults').innerHTML = '<p style="color:#888;text-align:center;padding:2rem;">' + __('Select a hospital and month, then click Analyze.') + '</p>';
                return;
            }
            document.getElementById('clinicalLoading').classList.remove('hidden');
            document.getElementById('clinicalResults').innerHTML = '';
            try {
                const analysis = await apiGet('/clinical/' + hospSel.value + '?month=' + monthSel.value);
                document.getElementById('clinicalLoading').classList.add('hidden');
                renderClinical(analysis);
            } catch(e) {
                document.getElementById('clinicalLoading').classList.add('hidden');
                const errMsg = e.message.includes('404') ? __('No data for this hospital/month') : __('No clinical data available. Upload files first.');
                document.getElementById('clinicalResults').innerHTML = '<p style="color:#888;text-align:center;padding:2rem;font-size:0.85rem;">' + errMsg + '</p>';
            }
        }

        export function initClinical() {
            const hsel = document.getElementById('clinicalHospitalSelect');
            const msel = document.getElementById('clinicalMonthSelect');
            const phH = '<option value="">' + __('Select Hospital') + '</option>';
            const phM = '<option value="">' + __('Select Month') + '</option>';
            hsel.innerHTML = phH;
            msel.innerHTML = phM;
            Promise.all([
                apiGet('/hospitals/').then(data => {
                    const list = data.value || data || [];
                    hsel.innerHTML = phH + list.map(h => '<option value="' + h.id + '">' + h.name + '</option>').join('');
                }),
                apiGet('/analysis/months').then(months => {
                    msel.innerHTML = phM + months.map(m => '<option value="' + m + '">' + m + '</option>').join('');
                }),
            ]).then(() => {
                _restoreUIState('clinical');
                if (hsel.value && msel.value) loadClinical();
            }).catch(() => {});
        }

        function _badgeHtml(color, text) {
            return '<span class="badge" style="background:' + color + '22;color:' + color + ';border:1px solid ' + color + '44;">' + text + '</span>';
        }

        export function renderClinical(analysis) {
            const container = document.getElementById('clinicalResults');
            if (!analysis) {
                container.innerHTML = '<div class="empty-state empty-text">' + __('No clinical data for this hospital/month') + '</div>';
                return;
            }
            const a = analysis;
            const s = a.summary;
            const overallColor = s.overall_assessment.startsWith('CRITICAL') ? '#b71c1c' : s.overall_assessment.startsWith('ATTENTION') ? '#e65100' : '#2e7d32';
            let html = '<div class="clinical-card">';
            html += '<h3 class="clinical-header">' + a.hospital + ' &mdash; ' + a.month + '</h3>';

            html += '<div class="clinical-banner" style="background:' + overallColor + '11;border-left:4px solid ' + overallColor + ';"><strong style="color:' + overallColor + ';">' + s.overall_assessment + '</strong></div>';
            html += '<p class="clinical-overview">' + s.overview + '</p>';

            if (s.key_findings && s.key_findings.length) {
                html += '<div class="clinical-section-title">' + __('Key Findings') + '</div><ul class="issue-list">';
                s.key_findings.forEach(f => { html += '<li>' + f + '</li>'; });
                html += '</ul>';
            }

            if (s.clinical_indicators && s.clinical_indicators.length) {
                html += '<div class="clinical-section-title">' + __('Clinical Indicators') + '</div><div class="grid-3" style="margin:0.5rem 0;">';
                s.clinical_indicators.forEach(ind => {
                    const parts = ind.split(': ');
                    html += '<div class="clinical-stat"><div class="value">' + (parts[1]||'') + '</div><div class="label">' + (parts[0]||'') + '</div></div>';
                });
                html += '</div>';
            }

            if (a.classifications && a.classifications.length) {
                html += '<div class="clinical-section-title">' + __('Clinical Classifications') + '</div>';
                html += '<div class="clinical-table-wrap" style="max-height:300px;overflow-y:auto;"><table><thead><tr><th>' + __('Indicator') + '</th><th>' + __('Value') + '</th><th>' + __('Status') + '</th><th>' + __('Narrative') + '</th></tr></thead><tbody>';
                a.classifications.filter(c => c.value !== null).forEach(c => {
                    html += '<tr><td>' + c.rate_name + '</td><td>' + (c.value !== null && c.value !== undefined ? c.value.toFixed(1) + c.unit : '--') + '</td><td>' + _badgeHtml(c.color, c.label) + '</td><td style="font-size:0.8rem;">' + c.narrative + '</td></tr>';
                });
                html += '</tbody></table></div>';
            }

            const rp = a.risk_profile;
            if (rp && rp.metrics && rp.metrics.length) {
                const riskColor = rp.overall_risk_level === 'critical' ? '#b71c1c' : rp.overall_risk_level === 'high' ? '#c62828' : rp.overall_risk_level === 'moderate' ? '#e65100' : '#2e7d32';
                html += '<div class="clinical-section-title">' + __('Risk Profile') + ' ' + _badgeHtml(riskColor, rp.overall_risk_level.toUpperCase()) + '</div>';
                html += '<div class="clinical-table-wrap" style="max-height:250px;overflow-y:auto;"><table><thead><tr><th>' + __('Metric') + '</th><th>' + __('Value') + '</th><th>' + __('Severity') + '</th><th>' + __('Interpretation') + '</th></tr></thead><tbody>';
                rp.metrics.forEach(m => {
                    const sevColor = m.severity === 'critical' ? '#b71c1c' : m.severity === 'high' ? '#c62828' : m.severity === 'moderate' ? '#e65100' : '#2e7d32';
                    html += '<tr><td>' + m.metric_name + '</td><td>' + (m.value !== null ? m.value.toFixed(1) + m.unit : '--') + '</td><td>' + _badgeHtml(sevColor, m.severity) + '</td><td style="font-size:0.8rem;">' + m.interpretation + '</td></tr>';
                });
                html += '</tbody></table></div>';
            }

            const mp = a.morbidity_profile;
            if (mp && mp.key_findings && mp.key_findings.length) {
                html += '<div class="clinical-section-title">' + __('Morbidity-Mortality Assessment') + '</div>';
                html += '<p class="clinical-overview">' + s.morbidity_assessment + '</p>';
                if (mp.mortality_preventability_signals && mp.mortality_preventability_signals.length) {
                    html += '<ul class="issue-list">';
                    mp.mortality_preventability_signals.forEach(sig => { html += '<li class="clinical-mortality-signal">' + sig + '</li>'; });
                    html += '</ul>';
                }
            }

            if (mp && mp.metrics && mp.metrics.length) {
                html += '<div class="clinical-table-wrap" style="max-height:250px;overflow-y:auto;"><table><thead><tr><th>' + __('Metric') + '</th><th>' + __('Value') + '</th><th>' + __('Severity') + '</th><th>' + __('Interpretation') + '</th></tr></thead><tbody>';
                mp.metrics.forEach(m => {
                    const sevColor = m.severity === 'critical' ? '#b71c1c' : m.severity === 'high' ? '#c62828' : m.severity === 'moderate' ? '#e65100' : '#2e7d32';
                    html += '<tr><td>' + m.metric_name + '</td><td>' + (m.value !== null ? m.value.toFixed(1) + m.unit : '--') + '</td><td>' + _badgeHtml(sevColor, m.severity) + '</td><td style="font-size:0.8rem;">' + m.interpretation + '</td></tr>';
                });
                html += '</tbody></table></div>';
            }

            if (a.recommendations && a.recommendations.length) {
                html += '<div class="clinical-section-title">' + __('Recommendations') + ' (' + a.recommendations.length + ')</div>';
                a.recommendations.forEach(rec => {
                    const priColor = rec.priority === 'critical' ? '#b71c1c' : rec.priority === 'high' ? '#c62828' : rec.priority === 'medium' ? '#e65100' : '#2e7d32';
                    html += '<div class="clinical-rec-card" style="border-left-color:' + priColor + ';">';
                    html += '<div class="clinical-rec-header">' + _badgeHtml(priColor, rec.priority.toUpperCase()) + '<strong>' + rec.title + '</strong></div>';
                    html += '<div class="clinical-rec-desc">' + rec.description + '</div>';
                    if (rec.data_reliable === false) {
                        html += '<div class="clinical-reliability-warn">&#x26A0; ' + __('Data reliability concern') + ' &mdash; ' + __('underlying indicators have validation failures') + '</div>';
                    }
                    if (rec.rationale) {
                        html += '<div class="clinical-rec-rationale">' + rec.rationale + '</div>';
                    }
                    if (rec.action_items && rec.action_items.length) {
                        html += '<ul class="clinical-rec-actions">';
                        rec.action_items.forEach(ai => { html += '<li>' + ai + '</li>'; });
                        html += '</ul>';
                    }
                    if (rec.triggered_by_rules && rec.triggered_by_rules.length) {
                        html += '<div class="clinical-rec-rules"><span style="color:#888;">' + __('Triggered by:') + '</span> ';
                        rec.triggered_by_rules.forEach((rc, ri) => {
                            html += '<a href="#" onclick="showRuleFailureDetail(\'' + rc + '\',\'' + a.hospital + '\',\'' + a.month + '\');return false;" style="color:#1565c0;text-decoration:underline;">' + rc + '</a>';
                            if (ri < rec.triggered_by_rules.length - 1) html += ', ';
                        });
                        html += '</div>';
                    }
                    if (rec.indicators_monitored && rec.indicators_monitored.length) {
                        html += '<div class="clinical-rec-indicators">';
                        rec.indicators_monitored.forEach(ind => {
                            html += '<span class="clinical-rec-indicator">' + ind + '</span>';
                        });
                        html += '</div>';
                    }
                    html += '</div>';
                });
            }

            html += '</div>';
            container.innerHTML = html;
        }

