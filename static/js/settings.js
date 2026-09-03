        import { API, apiGet, apiPost, apiPut, clearApiCache } from './api.js';

import { DataTable, scoreBadge, trendIcon, confidenceBar } from './table-utils.js';
        import { __ } from './i18n.js';
        import { esc } from './tree.js';
        import { _saveUIState, _restoreUIState, SwitchTab, _tabInited } from './main.js';
import { toastSuccess, toastError, toastWarning } from './toast.js';

                        // ── High Confidence Detail ──
                if (metric === 'conf_high' && confDetail && confDetail.indicators) {
                    var sd = confDetail;
                    html += '<div class="card" style="margin-top:1rem;max-height:600px;overflow-y:auto;">';
                    html += '<h3 style="margin-bottom:0.5rem;">\u0639\u0646\u0627\u0635\u0631 \u0627\u0644\u062a\u062d\u0642\u0642</h3>';
                    html += '<div style="font-size:0.78rem;color:var(--text-secondary);margin-bottom:0.8rem;">' + esc(sd.summary || '') + '</div>';

                    var _sigData = [
                        {key: 'rule_compliance', name: '\u0627\u0644\u0642\u0648\u0627\u0639\u062f \u0627\u0644\u062a\u062d\u0642\u0642\u064a\u0629', weight: 55, icon: '\u2705', color: '#e65100'},
                        {key: 'historical', name: '\u0627\u0644\u0627\u062a\u0633\u0627\u0639 \u0627\u0644\u062a\u0627\u0631\u064a\u062e\u064a', weight: 10, icon: '\ud83d\udcc8', color: '#1565c0'},
                        {key: 'cross_hospital', name: '\u0627\u0644\u0645\u0642\u0627\u0631\u0646\u0629 \u0627\u0644\u0637\u0628\u0642\u064a\u0629', weight: 10, icon: '\ud83d\udcca', color: '#6a1b9a'},
                        {key: 'trend', name: '\u062a\u062d\u0644\u064a\u0644 \u0627\u0644\u0627\u062a\u062c\u0627\u0647', weight: 10, icon: '\ud83d\udcc9', color: '#2e7d32'},
                        {key: 'completeness', name: '\u0627\u0643\u062a\u0645\u0627\u0644 \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a', weight: 15, icon: '\ud83d\udcdd', color: '#00838f'}
                    ];

                    var _sigAvgs = {}, _sigCounts = {};
                    _sigData.forEach(function(s) { _sigAvgs[s.key] = 0; _sigCounts[s.key] = 0; });
                    sd.indicators.forEach(function(ind) {
                        if (ind.signals) ind.signals.forEach(function(sig) {
                            if (_sigAvgs[sig.factor] !== undefined) { _sigAvgs[sig.factor] += sig.score; _sigCounts[sig.factor]++; }
                        });
                    });
                    _sigData.forEach(function(s) { s.avg = _sigCounts[s.key] ? Math.round(_sigAvgs[s.key] / _sigCounts[s.key] * 100) : 0; });

                    html += '<div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(130px, 1fr));gap:0.5rem;margin-bottom:1rem;">';
                    _sigData.forEach(function(s) {
                        var avgColor = s.avg >= 80 ? 'var(--accent-green)' : s.avg >= 60 ? 'var(--accent-orange)' : 'var(--accent-red)';
                        html += '<div style="padding:0.6rem;border-radius:8px;border:2px solid ' + s.color + '33;background:' + s.color + '0a;">';
                        html += '<div style="font-size:0.65rem;color:' + s.color + ';font-weight:600;">' + s.icon + ' ' + s.name + '</div>';
                        html += '<div style="font-size:1.1rem;font-weight:700;color:' + s.color + ';margin:0.2rem 0;">' + s.avg + '%</div>';
                        html += '<div style="height:4px;background:var(--border-default);border-radius:2px;"><div style="width:' + s.avg + '%;height:4px;background:' + avgColor + ';border-radius:2px;"></div></div>';
                        html += '<div style="font-size:0.6rem;color:var(--text-muted);margin-top:2px;">\u0627\u0644\u0648\u0632\u0646: ' + s.weight + '%</div>';
                        html += '</div>';
                    });
                    html += '</div>';

                    var _levels = sd.by_level || {};
                    html += '<div style="font-size:0.78rem;font-weight:600;color:var(--text-primary);margin-bottom:0.4rem;">\u062a\u0648\u0632\u064a\u0639 \u0627\u0644\u062a\u062d\u0642\u0642</div>';
                    html += '<div style="display:flex;gap:0.5rem;margin-bottom:1rem;flex-wrap:wrap;">';
                    [{k:'HIGH',c:'var(--accent-green)',l:'HIGH \u2705'},{k:'MEDIUM',c:'var(--accent-orange)',l:'MEDIUM \u26a0\ufe0f'},{k:'LOW',c:'var(--accent-red)',l:'LOW \u274c'},{k:'CRITICAL',c:'#b71c1c',l:'CRITICAL \u2620\ufe0f'}].forEach(function(lev) {
                        var cnt = _levels[lev.k] || 0;
                        html += '<div style="padding:0.4rem 0.8rem;border-radius:8px;background:' + lev.c + '15;border:1px solid ' + lev.c + '33;text-align:center;">';
                        html += '<div style="font-size:0.65rem;color:' + lev.c + ';">' + lev.l + '</div>';
                        html += '<div style="font-size:1rem;font-weight:700;color:' + lev.c + ';">' + cnt + '</div></div>';
                    });
                    html += '</div>';

                    var _groups = sd.by_group || {};
                    if (Object.keys(_groups).length) {
                        html += '<div style="font-size:0.78rem;font-weight:600;color:var(--text-primary);margin-bottom:0.4rem;">\u0627\u0644\u062a\u062d\u0642\u0642 \u062d\u0633\u0628 \u0627\u0644\u0645\u062c\u0645\u0648\u0639\u0629</div>';
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

                    var _prio = (sd.indicators || []).filter(function(i) { return i.level !== 'HIGH'; }).slice(0, 20);
                    if (_prio.length) {
                        html += '<div style="font-size:0.78rem;font-weight:600;color:var(--text-primary);margin-bottom:0.4rem;">\u0627\u0644\u0645\u0648\u0627\u0634\u0631 \u0627\u0644\u062a\u062d\u062a\u0627\u062c \u062a\u062d\u0642\u0642\u0647\u0627 (' + _prio.length + ')</div>';
                        html += '<div style="max-height:400px;overflow-y:auto;display:flex;flex-direction:column;gap:0.4rem;padding-right:4px;">';
                        _prio.forEach(function(ind) {
                            var ilc = ind.level === 'CRITICAL' ? '#b71c1c' : ind.level === 'LOW' ? 'var(--accent-red)' : 'var(--accent-orange)';
                            var ilbg = ind.level === 'CRITICAL' ? 'rgba(183,28,28,0.08)' : ind.level === 'LOW' ? 'rgba(198,40,40,0.06)' : 'rgba(230,81,0,0.06)';
                            html += '<div style="padding:0.5rem 0.6rem;border-radius:8px;border:1px solid var(--border-default);background:' + ilbg + ';">';
                            html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
                            html += '<span style="font-size:0.78rem;font-weight:600;">' + esc(ind.indicator_name || ind.indicator_code) + ' <span style="font-size:0.62rem;color:var(--text-muted);">(' + esc(ind.indicator_code) + ')</span></span>';
                            html += '<span style="font-size:0.72rem;font-weight:700;color:' + ilc + ';">' + ind.confidence + '% \u2022 ' + ind.level + '</span></div>';
                            if (ind.value !== null && ind.value !== undefined) html += '<div style="font-size:0.65rem;color:var(--text-muted);margin-top:2px;">\u0627\u0644\u0642\u064a\u0645\u0629: ' + ind.value + '</div>';
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
                }

                bodyEl.innerHTML = html || || '<p style="color:var(--text-muted);padding:1rem;">' + __('No details available.') + '</p>';

                // Render chart
                var chartCtx = document.getElementById('kpiDrilldownChart');
                if (chartCtx) {
                    if (_kpiDrilldownChart) { _kpiDrilldownChart.destroy(); _kpiDrilldownChart = null; }
                    if (metric === 'conf_high' && confDetail && confDetail.indicators) {
                        // Signal factor weights bar chart for confidence
                        var _sigLabels = ['القواعد التحققية', 'الاتساع التاريخي', 'المقارنة الطبقية', 'تحليل الاتجاه', 'اكتمال البيانات'];
                        var _sigWeights = [55, 10, 10, 10, 15];
                        var _sigColors = ['#e65100', '#1565c0', '#6a1b9a', '#2e7d32', '#00838f'];
                        // Compute average score per signal from indicators
                        var _sigAvgs = [0, 0, 0, 0, 0];
                        var _sigCounts = [0, 0, 0, 0, 0];
                        var _sigKeys = ['rule_compliance', 'historical', 'cross_hospital', 'trend', 'completeness'];
                        confDetail.indicators.forEach(function(ind) {
                            if (ind.signals) ind.signals.forEach(function(sig, si) {
                                var kIdx = _sigKeys.indexOf(sig.factor);
                                if (kIdx >= 0) { _sigAvgs[kIdx] += sig.score; _sigCounts[kIdx]++; }
                            });
                        });
                        for (var si = 0; si < 5; si++) _sigAvgs[si] = _sigCounts[si] ? Math.round(_sigAvgs[si] / _sigCounts[si] * 100) : 0;
                        _kpiDrilldownChart = new Chart(chartCtx, {
                            type: 'bar',
                            data: {
                                labels: _sigLabels,
                                datasets: [
                                    { label: 'الوزن المخصص', data: _sigWeights, backgroundColor: _sigColors.map(function(c) { return c + '44'; }), borderColor: _sigColors, borderWidth: 2, borderRadius: 4 },
                                    { label: 'متوسط المواشر', data: _sigAvgs, backgroundColor: _sigColors.map(function(c) { return c + '99'; }), borderColor: _sigColors, borderWidth: 2, borderRadius: 4 },
                                ]
                            },
                            options: {
                                responsive: true, maintainAspectRatio: false, resizeDelay: 200,
                                plugins: { legend: { position: 'bottom', labels: { font: { size: 10 } } } },
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
                            datasets.push({ label: __('Target') + ' (' + _targetMap[metric] + '%)', data: compTrend.map(function() { return _targetMap[metric]; }), borderColor: 'rgba(128,128,128,0.4)', borderDash: [6,4], borderWidth: 1, pointRadius: 0, fill: false });
                        }
                        _kpiDrilldownChart = new Chart(chartCtx, {
                            type: 'line',
                            data: {
                                labels: compTrend.map(function(d) { return d.month; }),
                                datasets: datasets
                            },
                            options: {
                                responsive: true, maintainAspectRatio: false, resizeDelay: 200,
                                plugins: { legend: { position: 'bottom', labels: { font: { size: 10 } } } },
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
            _saveUIState('dashboard');
            const hid = document.getElementById('dashHospital').value;
            const yr = document.getElementById('dashYear').value;
            const dr = window._dashboardDateRange;
            document.getElementById('dashLoading').style.display = 'inline';

            let url = '/dashboard/overview?';
            if (hid) url += 'hospital_id=' + hid + '&';
            if (dr && dr.from) url += 'month_from=' + dr.from + '&';
            if (dr && dr.to) url += 'month_to=' + dr.to + '&';
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

                if (data.quality_trend && data.quality_trend.length) {
                    const vals = data.quality_trend.map(d => d.score);
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
                const list = months.months || months || [];
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
            }).catch(e => {
                document.getElementById('settingsStatus').textContent = '\u2717 Error: ' + e.message;
                document.getElementById('settingsStatus').style.color = 'var(--accent-red)';
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
                statusEl.style.color = 'var(--accent-green)';
                if (data.errors && data.errors.length) {
                    statusEl.textContent += ' | Errors: ' + data.errors.length;
                    statusEl.style.color = 'var(--accent-orange)';
                }
                // Redirect to dashboard to show fresh data
                switchTab('dashboard');
            }).catch(e => {
                const statusEl = document.getElementById('settingsStatus');
                statusEl.textContent = '\u2717 Error: ' + e.message;
                statusEl.style.color = 'var(--accent-red)';
            }).finally(() => {
                hideLoader();
                btn.textContent = originalText;
                btn.disabled = false;
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

        export function loadRulesManager() {
            if (!document.getElementById('rulesTbody')) return; // التبويب لم يُحمَّل بعد
            const typeFilter = document.getElementById('rulesTypeFilter').value;
            const sevFilter = document.getElementById('rulesSeverityFilter').value;
            const enabledFilter = document.getElementById('rulesEnabledFilter').value;
            let url = API() + '/rules/?';
            if (typeFilter) url += 'rule_type=' + encodeURIComponent(typeFilter) + '&';
            if (sevFilter) url += 'severity=' + encodeURIComponent(sevFilter) + '&';
            if (enabledFilter) url += 'enabled=' + enabledFilter + '&';
            const tbody = document.getElementById('rulesTbody');
            document.getElementById('rulesLoading').classList.remove('hidden');
            tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;padding:1.5rem;color:var(--text-muted);">Loading rules...</td></tr>';
            authFetch(url)
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
            document.getElementById('rulesManagerCount').textContent = rulesManagerData.length + ' rule(s)';
            const filtered = document.getElementById('rulesTbody');
            if (!rulesManagerData.length) {
                filtered.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:2rem;">No rules found.</td></tr>';
                return;
            }
            const typeColors = {'LOGIC': 'var(--accent-blue)', 'CLINICAL': 'var(--accent-purple)', 'BENCHMARK': 'var(--accent-orange)', 'DATA_QUALITY': 'var(--accent-red)'};
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
                    '<td style="cursor:grab;color:var(--text-muted);font-size:0.9rem;user-select:none;">⠿</td>' +
                    '<td><code>' + esc(r.code) + '</code></td>' +
                    '<td>' + esc(r.name) + '</td>' +
                    '<td>' + typeB + '</td>' +
                    '<td>' + sevB + '</td>' +
                    '<td style="font-size:0.75rem;color:var(--text-secondary);">' + esc(r.category) + '</td>' +
                    '<td style="font-size:0.75rem;font-family:Consolas,monospace;color:var(--text-muted);">' + esc(r.expression_type) + '</td>' +
                    '<td style="text-align:center;" class="rule-toggle-cell" data-id="' + r.id + '">' + enabledIcon + '</td>' +
                    '<td style="white-space:nowrap;"><button class="btn btn-sm btn-outline" onclick="openRuleModal(' + r.id + ')" style="font-size:0.65rem;padding:0.15rem 0.4rem;">Edit</button> <button class="btn btn-sm btn-outline" onclick="deleteRule(' + r.id + ',\'' + esc(r.code) + '\')" style="font-size:0.65rem;padding:0.15rem 0.4rem;color:var(--accent-red);border-color:#ef5350;">Del</button></td>' +
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
                    authFetch(API() + '/rules/' + ruleId + '/toggle', { method: 'PUT' })
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
                            toastError('Toggle failed: ' + e.message);
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
                    authFetch(API() + '/rules/reorder', {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({items: items}),
                    }).then(r => r.json()).then(() => {
                        loadRulesManager();
                    }).catch(err => toastError('Reorder failed: ' + err.message));
                });
            });
        }

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







// ---- Self Change Password ----
window.changeSelfPassword = async function() {
    var curEl = document.getElementById('selfPwCurrent');
    var newEl = document.getElementById('selfPwNew');
    var confirmEl = document.getElementById('selfPwConfirm');
    var errEl = document.getElementById('selfPwError');
    var okEl = document.getElementById('selfPwSuccess');

    errEl.style.display = 'none';
    okEl.style.display = 'none';

    var cur = curEl ? curEl.value : '';
    var nw = newEl ? newEl.value : '';
    var cf = confirmEl ? confirmEl.value : '';

    if (!cur) { errEl.textContent = 'Current password is required'; errEl.style.display = 'block'; return; }
    if (!nw) { errEl.textContent = 'New password is required'; errEl.style.display = 'block'; return; }
    if (nw.length < 6) { errEl.textContent = 'Password must be at least 6 characters'; errEl.style.display = 'block'; return; }
    if (nw === cur) { errEl.textContent = 'New password must be different from current'; errEl.style.display = 'block'; return; }
    if (nw !== cf) { errEl.textContent = 'Passwords do not match'; errEl.style.display = 'block'; return; }

    try {
        var token = getAccessToken();
        var resp = await authFetch(API() + '/auth/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
            body: JSON.stringify({ current_password: cur, new_password: nw, confirm_password: cf })
        });
        var data = await resp.json();
        if (!resp.ok) {
            errEl.textContent = data.detail || 'Failed to change password';
            errEl.style.display = 'block';
            return;
        }
        okEl.textContent = '✅ Password changed successfully! You can continue using the app.';
        okEl.style.display = 'block';
        curEl.value = '';
        newEl.value = '';
        confirmEl.value = '';
    } catch(e) {
        errEl.textContent = 'Network error';
        errEl.style.display = 'block';
    }
};
