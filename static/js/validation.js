        import { apiGet } from './api.js';
        import { __ } from './i18n.js';
        import { _restoreUIState, _saveUIState } from './main.js';
        import { esc } from './tree.js';

        // ── Merged Comparative Analysis (Trends + Comparison) ────
        export function switchAnalysisMode(mode) {
            const t = document.getElementById('analysisTrendSection');
            const c = document.getElementById('analysisCompareSection');
            const btnT = document.getElementById('analysisModeTrend');
            const btnC = document.getElementById('analysisModeCompare');
            if (!t || !c) return;
            t.style.display = mode === 'trend' ? '' : 'none';
            c.style.display = mode === 'compare' ? '' : 'none';
            const base = 'font-size:0.78rem;padding:0.25rem 0.8rem;cursor:pointer;border-radius:4px;';
            const active = 'background:#1a237e;color:#fff;border:none;font-weight:600;';
            const idle = 'background:white;color:#1a237e;border:1px solid #c7d2fe;font-weight:400;';
            if (btnT) btnT.setAttribute('style', base + (mode === 'trend' ? active : idle));
            if (btnC) btnC.setAttribute('style', base + (mode === 'compare' ? active : idle));
            try { localStorage.setItem('analysisMode', mode); } catch(e) {}
            if (mode === 'trend') {
                initTrends();
            } else {
                initCompare();
            }
        }

        export function initAnalysis() {
            let mode = 'trend';
            try { mode = localStorage.getItem('analysisMode') || 'trend'; } catch(e) {}
            switchAnalysisMode(mode);
        }

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

            // ── Interactive Plotly chart (replaces static SVG) ────
            window._qualityTrendData = data;
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
                <div style="display:flex;align-items:center;gap:0.4rem;flex-wrap:wrap;margin-bottom:0.6rem;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:0.4rem 0.6rem;">
                    <span style="font-size:0.78rem;color:#666;font-weight:600;">المقياس:</span>
                    <button data-metric="score" class="qt-metric-btn" style="font-size:0.75rem;padding:0.25rem 0.7rem;border-radius:4px;cursor:pointer;border:1px solid #1a237e;background:#1a237e;color:#fff;font-weight:700;" onclick="switchQualityTrendMetric('score')">درجة الجودة</button>
                    <button data-metric="completeness" class="qt-metric-btn" style="font-size:0.75rem;padding:0.25rem 0.7rem;border-radius:4px;cursor:pointer;border:1px solid #c7d2fe;background:#fff;color:#1a237e;" onclick="switchQualityTrendMetric('completeness')">الاكتمال</button>
                    <button data-metric="rule_compliance" class="qt-metric-btn" style="font-size:0.75rem;padding:0.25rem 0.7rem;border-radius:4px;cursor:pointer;border:1px solid #c7d2fe;background:#fff;color:#1a237e;" onclick="switchQualityTrendMetric('rule_compliance')">الالتزام</button>
                    <button data-metric="consistency" class="qt-metric-btn" style="font-size:0.75rem;padding:0.25rem 0.7rem;border-radius:4px;cursor:pointer;border:1px solid #c7d2fe;background:#fff;color:#1a237e;" onclick="switchQualityTrendMetric('consistency')">الاتساق</button>
                </div>
                <div id="qualityTrendPlot" style="width:100%;height:340px;"></div>
            `;
            renderQualityTrendPlot(data, 'score');
        }

        // ── Interactive Plotly quality trend chart ────────────────
        const QUALITY_METRICS = {
            score: { label: 'درجة الجودة', color: '#1a237e' },
            completeness: { label: 'الاكتمال', color: '#2e7d32' },
            rule_compliance: { label: 'الالتزام', color: '#e65100' },
            consistency: { label: 'الاتساق', color: '#6a1b9a' },
        };

        function _qtValue(s, key) {
            const v = s[key];
            return (v === null || v === undefined) ? '—' : Number(v).toFixed(1);
        }

        function renderQualityTrendPlot(data, metric) {
            const el = document.getElementById('qualityTrendPlot');
            if (!el || !data || !data.data || !data.data.length) return;
            const scores = data.data;
            const months = scores.map(s => s.month);
            const cfg = QUALITY_METRICS[metric] || QUALITY_METRICS.score;

            const hoverText = scores.map(s => {
                const parts = ['<b>' + s.month + '</b>', cfg.label + ': <b>' + _qtValue(s, metric) + '</b>'];
                if (s.peer_avg !== null && s.peer_avg !== undefined) parts.push('متوسط النظير: <b>' + Number(s.peer_avg).toFixed(1) + '</b>');
                if (metric !== 'score') parts.push('درجة الجودة: ' + _qtValue(s, 'score'));
                parts.push('الاكتمال: ' + _qtValue(s, 'completeness'));
                parts.push('الالتزام: ' + _qtValue(s, 'rule_compliance'));
                parts.push('الاتساق: ' + _qtValue(s, 'consistency'));
                if (s.outlier_penalty !== null && s.outlier_penalty !== undefined) parts.push('خصم الشذوذ: ' + Number(s.outlier_penalty).toFixed(1));
                if (s.issues_count) parts.push('المشكلات: ' + s.issues_count);
                return parts.join('<br>');
            });

            const traces = [{
                type: 'scatter', mode: 'lines+markers',
                x: months,
                y: scores.map(s => s[metric]),
                name: cfg.label,
                line: { color: cfg.color, width: 3, shape: 'spline' },
                marker: { size: 10, color: cfg.color, line: { width: 2, color: '#fff' } },
                fill: 'tozeroy',
                fillcolor: cfg.color + '26',
                text: hoverText,
                hoverinfo: 'text',
            }];

            // Reference: overall score shown as dashed line when a component is selected
            if (metric !== 'score') {
                traces.push({
                    type: 'scatter', mode: 'lines',
                    x: months, y: scores.map(s => s.score),
                    name: 'درجة الجودة (مرجع)',
                    line: { color: '#1a237e', width: 1.5, dash: 'dot' },
                    hoverinfo: 'skip',
                });
            }

            // Peer average line (average of all hospitals per month)
            var peerData = scores.map(s => s.peer_avg !== null && s.peer_avg !== undefined ? s.peer_avg : null);
            var hasPeerData = peerData.some(v => v !== null);
            if (hasPeerData) {
                traces.push({
                    type: 'scatter', mode: 'lines',
                    x: months, y: peerData,
                    name: 'متوسط النظير (Peer Avg)',
                    line: { color: '#d97706', width: 2, dash: 'dashdot' },
                    marker: { size: 6, color: '#d97706', symbol: 'diamond' },
                    hovertemplate: 'متوسط النظير: <b>%{y:.1f}</b><extra></extra>',
                });
            }

            Plotly.newPlot(el, traces, {
                margin: { t: 20, b: 45, l: 45, r: 15 },
                xaxis: { title: 'الشهر', tickangle: -35, gridcolor: '#f0f0f0' },
                yaxis: { title: 'الدرجة (0-100)', range: [0, 100], gridcolor: '#f5f5f5', zeroline: false },
                hovermode: 'x unified',
                legend: { orientation: 'h', y: 1.08, x: 0 },
                paper_bgcolor: 'white',
                plot_bgcolor: 'white',
                font: { family: 'Segoe UI, Tahoma, Arial, sans-serif', size: 12 },
            }, { displayModeBar: true, responsive: true });
        }

        window.switchQualityTrendMetric = function(metric) {
            const data = window._qualityTrendData;
            if (!data) return;
            document.querySelectorAll('.qt-metric-btn').forEach(b => {
                const active = b.getAttribute('data-metric') === metric;
                b.style.background = active ? '#1a237e' : '#fff';
                b.style.color = active ? '#fff' : '#1a237e';
                b.style.borderColor = active ? '#1a237e' : '#c7d2fe';
                b.style.fontWeight = active ? '700' : '400';
            });
            renderQualityTrendPlot(data, metric);
        };

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
                    _restoreUIState('analysis');
                    if (sel.value) loadComparison();
                });
            } else {
                _restoreUIState('analysis');
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

        export function loadMLClusters() {
            const month = document.getElementById('compareMonthSelect').value;
            const container = document.getElementById('mlClusters');
            if (!month) { container.style.display = 'none'; return; }
            apiGet('/analysis/ml?month=' + month).then(data => {
                if (!data || !data.ml_clustering || !data.ml_clustering.clusters) {
                    container.style.display = 'none';
                    return;
                }
                const c = data.ml_clustering;
                const colors = ['#2e7d32','#f57f17','#c62828','#1565c0','#6a1b9a','#00838f','#4e342e','#37474f','#558b2f','#e65100'];
                let html = '<div class="card" style="padding:0.8rem;"><h3 style="font-size:0.9rem;margin:0 0 0.4rem;">Performance Clusters <span style="font-size:0.75rem;color:#888;font-weight:400;">(silhouette: ' + (c.silhouette_score ?? 0).toFixed(2) + ', k=' + c.k + ')</span></h3>';
                const groups = {};
                c.clusters.forEach(cl => {
                    if (!groups[cl.cluster_id]) groups[cl.cluster_id] = [];
                    groups[cl.cluster_id].push(cl);
                });
                Object.keys(groups).sort().forEach(cid => {
                    const members = groups[cid];
                    const color = colors[parseInt(cid) % colors.length];
                    html += '<div style="display:inline-block;margin:0.3rem;padding:0.4rem 0.6rem;border-radius:4px;border-left:4px solid ' + color + ';background:#fafafa;vertical-align:top;min-width:160px;">';
                    html += '<div style="font-size:0.78rem;font-weight:600;color:' + color + ';">Cluster ' + cid + ' (' + members.length + ')</div>';
                    members.forEach(m => {
                        html += '<div style="font-size:0.72rem;color:#555;margin:0.1rem 0;">' + esc(m.hospital_name) + ' <span style="color:#999;">(' + (m.distance_to_centroid ?? 0).toFixed(2) + ')</span></div>';
                    });
                    html += '</div>';
                });
                html += '<div style="font-size:0.7rem;color:#999;margin-top:0.3rem;">Features: ' + (c.features_used || []).join(', ') + '</div>';
                html += '</div>';
                container.innerHTML = html;
                container.style.display = '';
            }).catch(() => { container.style.display = 'none'; });
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
                document.getElementById('clinicalLoading').classList.add('hidden');
                document.getElementById('clinicalResults').innerHTML = '<div class="card" style="text-align:center;padding:2rem 1.5rem;color:#888;"><div style="font-size:1.8rem;margin-bottom:0.4rem;opacity:0.35;">&#128202;</div><p style="margin:0;font-size:0.85rem;">' + __('Select a hospital and month for detailed analysis.') + '</p></div>';
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

        window.onClinicalHospitalChange = async function() {
            const hsel = document.getElementById('clinicalHospitalSelect');
            const msel = document.getElementById('clinicalMonthSelect');
            const hid = hsel.value;
            const prevMonth = msel.value; // الشهر المحدد قبل إعادة بناء القائمة
            const phM = '<option value="">' + __('All Months') + '</option>';

            let months = [];
            if (!hid) {
                // All Hospitals → كل الأشهر المتاحة
                try {
                    const data = await apiGet('/analysis/months');
                    months = data.months || data || [];
                } catch (e) {}
            } else {
                try {
                    const settings = await apiGet('/config/month-settings?hospital_id=' + hid);
                    months = (settings.enabled_months || []).slice().sort();
                } catch (e) {}
            }
            msel.innerHTML = phM + months.map(m => '<option value="' + m + '">' + m + '</option>').join('');

            // استعادة الشهر المحدد سابقاً إن كان متاحاً، وإلا اختيار أحدث شهر متاح تلقائياً
            if (prevMonth && months.includes(prevMonth)) {
                msel.value = prevMonth;
            } else if (hid && months.length) {
                msel.value = months[months.length - 1];
            }

            // نطاق محدد (مستشفى + شهر) → العرض التفصيلي فقط (لا تُعاد تصفية الدفعة فوقه)
            // نطاق واسع (أي «الكل») → إعادة تصفية نتائج الدفعة المجمّعة إن وُجدت
            if (hid && msel.value) {
                loadClinical();
            } else if (typeof window.applyReportFilter === 'function') {
                window.applyReportFilter();
            }
        };

        window.onClinicalMonthChange = function() {
            const hsel = document.getElementById('clinicalHospitalSelect');
            const hid = hsel && hsel.value;
            const msel = document.getElementById('clinicalMonthSelect');
            // نطاق محدد (مستشفى + شهر) → العرض التفصيلي فقط
            if (hid && msel && msel.value) {
                loadClinical();
            } else if (typeof window.applyReportFilter === 'function') {
                // نطاق واسع → إعادة تصفية نتائج الدفعة المجمّعة إن وُجدت
                window.applyReportFilter();
            }
        };

        export function initClinical() {
            const hsel = document.getElementById('clinicalHospitalSelect');
            const msel = document.getElementById('clinicalMonthSelect');
            if (!hsel || !msel) return; // التبويب لم يُحمَّل
            const phH = '<option value="">' + __('All Hospitals') + '</option>';
            const phM = '<option value="">' + __('All Months') + '</option>';
            hsel.innerHTML = phH;
            msel.innerHTML = phM;
            apiGet('/hospitals/').then(data => {
                const list = data.value || data || [];
                hsel.innerHTML = phH + list.map(h => '<option value="' + h.id + '">' + h.name + '</option>').join('');
                _restoreUIState('clinical');
                if (hsel.value) {
                    // Filter months for restored hospital
                    return apiGet('/config/month-settings?hospital_id=' + hsel.value).then(settings => {
                        const enabled = (settings.enabled_months || []).slice().sort();
                        msel.innerHTML = phM + enabled.map(m => '<option value="' + m + '">' + m + '</option>').join('');
                        if (hsel.value && msel.value) {
                            loadClinical();
                        } else if (hsel.value && enabled.length) {
                            // لا يوجد شهر مستعاد → اختيار أحدث شهر متاح وعرضه تلقائياً
                            msel.value = enabled[enabled.length - 1];
                            loadClinical();
                        }
                    });
                }
            }).catch(() => {
                _restoreUIState('clinical');
                if (hsel.value && msel.value) loadClinical();
            });
        }

        function _badgeHtml(color, text) {
            return '<span class="badge" style="background:' + color + '22;color:' + color + ';border:1px solid ' + color + '44;">' + text + '</span>';
        }

        // ينتقل من التوصية الحرجة إلى تحليل السبب الجذري لنفس (المستشفى، الشهر)
        export function openRootCauseForHospital(linkEl) {
            const name = linkEl.getAttribute('data-hosp');
            const month = linkEl.getAttribute('data-month');
            const hsel = document.getElementById('clinicalHospitalSelect');
            if (!hsel || !name || !month) return;
            let hid = null;
            for (let i = 0; i < hsel.options.length; i++) {
                if (hsel.options[i].text === name) { hid = hsel.options[i].value; break; }
            }
            if (!hid) return;
            // إغلاق النافذة المنبثقة عند الانتقال لتبويب السبب الجذري (إن كانت مفتوحة)
            if (typeof window.closeModal === 'function') window.closeModal();
            if (typeof window.goRootCause === 'function') window.goRootCause(hid, month);
        }

        export function renderClinical(analysis, container) {
            container = container || document.getElementById('clinicalResults');
            if (!analysis) {
                container.innerHTML = '<div class="empty-state empty-text">' + __('No clinical data for this hospital/month') + '</div>';
                return;
            }
            const a = analysis;
            const s = a.summary;
            const overallColor = s.overall_assessment.startsWith('CRITICAL') ? '#b71c1c' : s.overall_assessment.startsWith('ATTENTION') ? '#e65100' : '#2e7d32';
            const overallLevel = overallColor === '#b71c1c' ? __('Critical') : overallColor === '#e65100' ? __('Attention') : __('Normal');
            const recs = a.recommendations || [];
            const criticalRecs = recs.filter(r => (r.priority || '').toLowerCase() === 'critical');
            const highRecs = recs.filter(r => (r.priority || '').toLowerCase() === 'high');
            const topIssues = recs.filter(r => { const p = (r.priority || '').toLowerCase(); return p === 'critical' || p === 'high'; }).slice(0, 3);
            let html = '<div class="clinical-card">';
            html += '<h3 class="clinical-header">' + a.hospital + ' &mdash; ' + a.month + '</h3>';

            // ── بطاقة الحالة: قرار أولاً ──
            html += '<div class="clinical-status-card" style="display:flex;flex-wrap:wrap;gap:1rem;align-items:center;padding:0.8rem 1rem;border-radius:8px;background:' + overallColor + '0d;border:1px solid ' + overallColor + '55;">';
            html += '<span style="font-size:1.1rem;font-weight:800;color:' + overallColor + ';">' + overallLevel + '</span>';
            html += '<span style="font-size:0.78rem;color:#555;">' + criticalRecs.length + ' ' + __('critical') + ' &middot; ' + highRecs.length + ' ' + __('high-priority recommendations') + '</span>';
            html += '</div>';

            // ── أهم 3 مشاكل حرجة ──
            if (topIssues.length) {
                html += '<div style="margin:0.6rem 0;padding:0.7rem 1rem;border-radius:8px;background:#b71c1c08;border:1px solid #b71c1c33;">';
                html += '<div style="font-size:0.8rem;font-weight:700;color:#b71c1c;margin-bottom:0.35rem;">&#9888; ' + __('Critical issues — act first') + '</div>';
                topIssues.forEach(rec => {
                    const p = (rec.priority || '').toLowerCase();
                    const pColor = p === 'critical' ? '#b71c1c' : '#c62828';
                    html += '<div style="display:flex;align-items:flex-start;gap:0.45rem;padding:0.28rem 0;">';
                    html += '<span style="font-size:0.62rem;font-weight:700;color:' + pColor + ';background:' + pColor + '11;border:1px solid ' + pColor + '44;border-radius:8px;padding:0.08rem 0.45rem;white-space:nowrap;margin-top:0.05rem;">' + rec.priority.toUpperCase() + '</span>';
                    html += '<span style="flex:1;font-size:0.8rem;color:#333;font-weight:600;">' + esc(rec.title) + '</span>';
                    html += '</div>';
                });
                html += '</div>';
            }

            html += '<p class="clinical-overview">' + s.overview + '</p>';

            if (s.key_findings && s.key_findings.length) {
                html += '<div class="clinical-section-title">' + __('Key Findings') + '</div><ul class="issue-list">';
                s.key_findings.forEach(f => { html += '<li>' + f + '</li>'; });
                html += '</ul>';
            }

            if (a.classifications && a.classifications.length) {
                html += '<details class="clinical-detail" open><summary>' + __('Clinical Classifications') + ' (' + a.classifications.length + ')</summary>';
                html += '<div class="clinical-table-wrap" style="max-height:300px;overflow-y:auto;"><table><thead><tr><th>' + __('Indicator') + '</th><th>' + __('Value') + '</th><th>' + __('Status') + '</th><th>' + __('Narrative') + '</th></tr></thead><tbody>';
                a.classifications.filter(c => c.value !== null).forEach(c => {
                    html += '<tr><td>' + c.rate_name + '</td><td>' + (c.value !== null && c.value !== undefined ? c.value.toFixed(1) + c.unit : '--') + '</td><td>' + _badgeHtml(c.color, c.label) + '</td><td style="font-size:0.8rem;">' + c.narrative + '</td></tr>';
                });
                html += '</tbody></table></div></details>';
            }

            const rp = a.risk_profile;
            if (rp && rp.metrics && rp.metrics.length) {
                const riskColor = rp.overall_risk_level === 'critical' ? '#b71c1c' : rp.overall_risk_level === 'high' ? '#c62828' : rp.overall_risk_level === 'moderate' ? '#e65100' : '#2e7d32';
                const critCount = rp.metrics.filter(m => m.severity === 'critical' || m.severity === 'high').length;
                html += '<details class="clinical-detail"><summary>' + __('Risk Profile') + ' ' + _badgeHtml(riskColor, rp.overall_risk_level.toUpperCase()) + (critCount ? ' <span style="font-weight:400;font-size:0.72rem;color:#c62828;">(' + critCount + ' critical/high)</span>' : '') + '</summary>';
                html += '<div class="clinical-table-wrap" style="max-height:250px;overflow-y:auto;"><table><thead><tr><th>' + __('Metric') + '</th><th>' + __('Value') + '</th><th>' + __('Severity') + '</th><th>' + __('Interpretation') + '</th></tr></thead><tbody>';
                rp.metrics.forEach(m => {
                    const sevColor = m.severity === 'critical' ? '#b71c1c' : m.severity === 'high' ? '#c62828' : m.severity === 'moderate' ? '#e65100' : '#2e7d32';
                    html += '<tr><td>' + m.metric_name + '</td><td>' + (m.value !== null ? m.value.toFixed(1) + m.unit : '--') + '</td><td>' + _badgeHtml(sevColor, m.severity) + '</td><td style="font-size:0.8rem;">' + m.interpretation + '</td></tr>';
                });
                html += '</tbody></table></div></details>';
            }

            const mp = a.morbidity_profile;
            if (mp && mp.key_findings && mp.key_findings.length) {
                html += '<details class="clinical-detail"><summary>' + __('Morbidity-Mortality Assessment') + '</summary>';
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
                html += '</details>';
            }

            if (a.recommendations && a.recommendations.length) {
                html += '<details class="clinical-detail"><summary>' + __('Recommendations') + ' (' + a.recommendations.length + ')</summary>';
                a.recommendations.forEach(rec => {
                    const priColor = rec.priority === 'critical' ? '#b71c1c' : rec.priority === 'high' ? '#c62828' : rec.priority === 'medium' ? '#e65100' : '#2e7d32';
                    const priLow = (rec.priority || '').toLowerCase();
                    html += '<div class="clinical-rec-card" style="border-left-color:' + priColor + ';">';
                    html += '<div class="clinical-rec-header">' + _badgeHtml(priColor, rec.priority.toUpperCase()) + '<strong>' + rec.title + '</strong>';
                    if (priLow === 'critical' || priLow === 'high') {
                        html += '<a href="#" data-hosp="' + esc(a.hospital) + '" data-month="' + a.month + '" onclick="openRootCauseForHospital(this);return false;" style="margin-left:auto;font-size:0.68rem;color:#1565c0;text-decoration:underline;white-space:nowrap;">&#128269; ' + __('Root Cause') + '</a>';
                    }
                    html += '</div>';
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
                html += '</details>';
            }

            html += '</div>';
            container.innerHTML = html;
        }

