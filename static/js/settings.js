        import { API, apiGet, apiPost, apiPut, clearApiCache } from './api.js';

import { DataTable, scoreBadge, trendIcon, confidenceBar } from './table-utils.js';
        import { __ } from './i18n.js';
        import { esc } from './tree.js';
        import { _saveUIState, _restoreUIState, SwitchTab, _tabInited } from './main.js';
import { toastSuccess, toastError, toastWarning } from './toast.js';

        // ── Progressive Disclosure: auto-wrap <h3> in collapsible sections ──
        function initCollapsibleSections() {
            document.querySelectorAll('.settings-section').forEach(section => {
                // Skip if already processed
                if (section.querySelector('.settings-section-header')) return;
                const h3s = section.querySelectorAll('h3');
                if (h3s.length < 2) return; // Only wrap if 2+ sections

                // Add collapse icon to each h3
                h3s.forEach((h3, i) => {
                    const wrapper = document.createElement('div');
                    wrapper.className = 'settings-collapsible' + (i === 0 ? ' open' : '');
                    wrapper.style.marginTop = i === 0 ? '0' : '0.6rem';

                    // Create clickable header
                    const header = document.createElement('button');
                    header.className = 'settings-section-header';
                    header.innerHTML = h3.innerHTML + '<span class="section-arrow">▶</span>';
                    header.addEventListener('click', function() {
                        wrapper.classList.toggle('open');
                    });

                    // Wrap the h3 and its following siblings until next h3 or end
                    h3.replaceWith(header);
                    wrapper.appendChild(header);

                    // Collect siblings until next h3
                    let next = header.nextElementSibling;
                    const body = document.createElement('div');
                    body.className = 'settings-section-body';
                    while (next && next.tagName !== 'H3' && !next.querySelector('h3')) {
                        const el = next;
                        next = next.nextElementSibling;
                        body.appendChild(el);
                    }
                    wrapper.appendChild(body);

                    // Insert before the next h3 or append to section
                    if (next) {
                        section.insertBefore(wrapper, next);
                    } else {
                        section.appendChild(wrapper);
                    }
                });
            });
        }

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
                status.style.color = 'var(--accent-green)';
            } else {
                status.textContent = '\u2717 Must be 1.0';
                status.style.color = 'var(--accent-red)';
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
                    status.style.color = 'var(--accent-green)';
                } else {
                    status.textContent = '\u2717 Must be 1.0';
                    status.style.color = 'var(--accent-red)';
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
    if (!/^[^@s]+@[^@s]+.[^@s]+$/.test(email)) { errEl.textContent = 'Invalid email format'; errEl.style.display = 'block'; return; }
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

window.changeSelfPassword = async function() {
            var currentEl = document.getElementById('selfPwCurrent');
            var newEl = document.getElementById('selfPwNew');
            var confirmEl = document.getElementById('selfPwConfirm');
            var errEl = document.getElementById('selfPwError');
            var okEl = document.getElementById('selfPwSuccess');
            errEl.style.display = 'none';
            okEl.style.display = 'none';
            if (!currentEl.value) { errEl.textContent = 'Current password is required'; errEl.style.display = 'block'; return; }
            if (!newEl.value || newEl.value.length < 6) { errEl.textContent = 'New password must be at least 6 characters'; errEl.style.display = 'block'; return; }
            if (newEl.value !== confirmEl.value) { errEl.textContent = 'Passwords do not match'; errEl.style.display = 'block'; return; }
            try {
                var token = (typeof getAccessToken === 'function') ? getAccessToken() : '';
                var resp = await authFetch('/auth/change-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
                    body: JSON.stringify({ current_password: currentEl.value, new_password: newEl.value, confirm_password: confirmEl.value })
                });
                var data = await resp.json();
                if (!resp.ok || data.detail) {
                    errEl.textContent = data.detail || 'Failed to change password';
                    errEl.style.display = 'block';
                    return;
                }
                okEl.textContent = 'Password changed successfully!';
                okEl.style.display = 'block';
                currentEl.value = ''; newEl.value = ''; confirmEl.value = '';
                setTimeout(function(){ okEl.style.display = 'none'; }, 3000);
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
        let _rcTimelineSelCode = null;  // يُحفظ كود المؤشر لا فهرسه (الفهرس يتغير باختلاف المستشفى)

        function drawRcTimelineChart(ind) {
            const chartEl = document.getElementById('rcTimelineChart');
            const textEl = document.getElementById('rcTimelineText');
            if (!chartEl || !ind) return;

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
                            label: (ind.indicator_name || ind.indicator_code) + ' — المستشفى',
                            data: hv,
                            borderColor: CHART_COLORS.primary,
                            backgroundColor: CHART_COLORS.primary,
                            borderWidth: 2.5,
                            pointRadius: 5,
                            pointHoverRadius: 7,
                            tension: 0.3,
                            fill: false,
                        },
                        {
                            label: 'متوسط النظير',
                            data: pm,
                            borderColor: CHART_COLORS.secondary,
                            backgroundColor: CHART_COLORS.secondary,
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
                            backgroundColor: '#1e293b',
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
                    textEl.innerHTML = 'الخط الصلب: قيمة المستشفى شهراً بشهر. الخط المتقطع: متوسط النظير. النطاق المظلل: فاصل ثقة 95% حول متوسط النظير. <strong>متوسط عدد النظير: ' + avgPeers + ' مستشفى</strong>';
                } else {
                    textEl.innerHTML = '⚠️ لا توجد بيانات نظير لهذا المستشفى. تم عرض قيمة المستشفى فقط. للمقارنة بالنظير, يجب تحديد حسب المستشفى بعمود معلومات النوع (نوع/الملكية/المحافظة).';
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
                sel.innerHTML = '<option value="">لا توجد بيانات زمنية كافية</option>';
                if (window._rcTimelineChartInstance) {
                    window._rcTimelineChartInstance.destroy();
                    window._rcTimelineChartInstance = null;
                }
                if (textEl) textEl.textContent = 'لا توجد بيانات — تتطلب المقارنة الزمنية شهرين أو أكثر للمستشفى وللنظراء.';
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

        export function loadRootCause() {
            _saveUIState('root-cause');
            const hid = document.getElementById('rcHospital').value;
            const mth = document.getElementById('rcMonth').value;
            if (!hid || !mth) return;
            document.getElementById('rcLoading').style.display = 'block';
            document.getElementById('rcContent').style.display = 'none';
            apiGet('/root-cause/' + hid + '?month=' + mth + '&include_history=true&compare_peers=true&months_back=6').then(d => {
                document.getElementById('rcLoading').style.display = 'none';
                document.getElementById('rcContent').style.display = 'block';

                // ── KPI Banner ──
                const qs = d.overall_quality_score || 0;
                const qsColor = qs >= 80 ? 'var(--accent-green)' : qs >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)';
                const conf = d.overall_confidence || 0;
                const confColor = conf >= 80 ? 'var(--accent-green)' : conf >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)';
                const ci = d.critical_issues_count || 0;
                document.getElementById('rcKpiBar').innerHTML =
                    '<div class="card" style="text-align:center;padding:0.8rem 0.5rem;border-top:4px solid ' + qsColor + ';">' +
                        '<div style="font-size:0.7rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">جودة البيانات / Quality</div>' +
                        '<div style="font-size:2rem;font-weight:700;color:' + qsColor + ';">' + qs + '</div>' +
                        '<div style="height:4px;background:var(--border-default);border-radius:2px;margin:0.3rem 1rem;overflow:hidden;">' +
                            '<div style="width:' + Math.min(qs, 100) + '%;height:100%;background:' + qsColor + ';border-radius:2px;"></div>' +
                        '</div>' +
                    '</div>' +
                    '<div class="card" style="text-align:center;padding:0.8rem 0.5rem;border-top:4px solid ' + confColor + ';">' +
                        '<div style="font-size:0.7rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">الثقة / Confidence</div>' +
                        '<div style="font-size:2rem;font-weight:700;color:' + confColor + ';">' + conf + '</div>' +
                        '<div style="height:4px;background:var(--border-default);border-radius:2px;margin:0.3rem 1rem;overflow:hidden;">' +
                            '<div style="width:' + Math.min(conf, 100) + '%;height:100%;background:' + confColor + ';border-radius:2px;"></div>' +
                        '</div>' +
                    '</div>' +
                    '<div class="card" style="text-align:center;padding:0.8rem 0.5rem;border-top:4px solid ' + (ci > 0 ? 'var(--accent-red)' : 'var(--accent-green)') + ';">' +
                        '<div style="font-size:0.7rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;">المشاكل الحرجة / Critical Issues</div>' +
                        '<div style="font-size:2rem;font-weight:700;color:' + (ci > 0 ? 'var(--accent-red)' : 'var(--accent-green)') + ';">' + ci + '</div>' +
                        '<div style="font-size:0.72rem;color:var(--text-muted);margin-top:0.2rem;">' + (ci > 0 ? 'يتطلب انتباهاً' : 'لا توجد مشاكل حرجة') + '</div>' +
                    '</div>';

                // ── Summary: Arabic primary (rendered into rcSummaryArabic), English secondary line ──
                const arSumEl = document.getElementById('rcSummaryArabic');
                if (arSumEl) arSumEl.textContent = d.summary_arabic || '';
                document.getElementById('rcSummary').innerHTML =
                    '<span style="color:#94a3b8;">EN summary:</span> ' + (d.summary || 'No summary available.');

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
                        let barHtml = '<div style="margin-top:0.2rem;font-size:0.62rem;color:var(--text-muted);">— لا يوجد تقدير كمي</div>';
                        if (impact > 0) {
                            const roiCol = roi >= 15 ? 'var(--accent-green)' : roi >= 8 ? 'var(--accent-orange)' : '#888';
                            const impactCol = impact >= 60 ? 'var(--accent-red)' : impact >= 30 ? 'var(--accent-orange)' : 'var(--accent-green)';
                            const effortDots = '<span style="direction:ltr;unicode-bidi:isolate;letter-spacing:2px;color:var(--accent-yellow);font-size:0.7rem;" title="الجهد (1-5): ' + effort + '">' +
                                '&#9679;'.repeat(effort) + '<span style="color:#ddd;">' + '&#9679;'.repeat(5 - effort) + '</span></span>';
                            barHtml = '<div style="margin-top:0.3rem;">' +
                                '<div style="display:flex;justify-content:space-between;font-size:0.62rem;color:var(--text-muted);margin-bottom:1px;">' +
                                    '<span>&#128200; الأثر: ' + impact.toFixed(0) + ' نقطة جودة</span>' +
                                    '<span style="color:' + roiCol + ';font-weight:700;">&#128176; عائد ' + roi.toFixed(1) + '</span>' +
                                    '<span>الجهد: ' + effortDots + '</span>' +
                                '</div>' +
                                '<div style="height:5px;background:#e5e7eb;border-radius:3px;overflow:hidden;">' +
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
                const prioAr = { critical: 'حرج', high: 'عالٍ', medium: 'متوسط', low: 'منخفض' };
                const aiPrioLabel = p => (isAr && prioAr[p]) ? prioAr[p] : p;
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
                            (catLabel ? '<span style="font-size:0.58rem;background:#eef2ff;color:#4338ca;padding:0 6px;border-radius:8px;white-space:nowrap;">' + esc(catLabel) + '</span>' : '') +
                            '<span style="font-weight:600;color:var(--text-primary);">' + esc(title) + '</span></div>' +
                            '<span style="font-size:0.6rem;background:' + pCol + ';color:#fff;padding:0 6px;border-radius:8px;white-space:nowrap;">' + esc(aiPrioLabel(r.priority)) + '</span></div>' +
                            (desc ? '<div style="font-size:0.75rem;color:var(--text-secondary);margin-top:0.2rem;">' + esc(desc) + '</div>' : '') +
                            (rat ? '<div style="font-size:0.7rem;color:var(--text-muted);font-style:italic;margin-top:0.15rem;">' + esc(rat) + '</div>' : '') +
                            (items && items.length ? '<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:0.15rem;"><strong>' + (isAr ? 'الإجراءات:' : 'Actions:') + '</strong> ' + items.map(esc).join('; ') + '</div>' : '');
                        aiList.appendChild(card);
                    });
                } else {
                    aiList.innerHTML = '<div style="padding:0.6rem;text-align:center;background:#fff8e1;border-radius:4px;font-size:0.8rem;color:var(--text-muted);">' +
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
                            return '<div style="padding:0.6rem;border:1px solid #99f6e4;border-radius:8px;margin-bottom:0.5rem;background:linear-gradient(135deg,#f0fdfa,#f8fafc);">' +
                                '<div style="display:flex;justify-content:space-between;align-items:center;gap:0.5rem;">' +
                                    '<span style="font-weight:700;font-size:0.82rem;color:#134e4a;">' + esc(c.root_cause_arabic || c.root_cause) + '</span>' +
                                    '<span style="font-size:0.65rem;background:' + prioColor + ';color:#fff;padding:1px 8px;border-radius:10px;white-space:nowrap;font-weight:600;">' + esc(prio) + '</span>' +
                                '</div>' +
                                (c.chain_path && c.chain_path.length > 1
                                    ? '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:0.2rem;margin:0.35rem 0;direction:rtl;" title="سلسلة السبب والنتيجة الكاملة (الأعمق ← الأحدث)">' +
                                        c.chain_path.map((code, ci) => {
                                            const isRoot = ci === c.chain_path.length - 1;
                                            return '<span style="font-size:0.66rem;padding:1px 8px;border-radius:10px;font-weight:600;white-space:nowrap;' +
                                                (isRoot ? 'background:#0d9488;color:#fff;' : 'background:#ccfbf1;color:#115e59;border:1px solid #99f6e4;') + '">' +
                                                esc(code) + '</span>' +
                                                (ci < c.chain_path.length - 1 ? '<span style="color:#0d9488;font-size:0.7rem;">&#8592;</span>' : '');
                                        }).join('') +
                                    '</div>' : '') +
                                (c.chain_path_arabic ? '<div style="font-size:0.68rem;color:#0f766e;margin-bottom:0.3rem;">' + esc(c.chain_path_arabic) + '</div>' : '') +
                                '<div style="margin:0.4rem 0;height:5px;background:#e2e8f0;border-radius:3px;overflow:hidden;">' +
                                    '<div style="width:' + pct + '%;height:100%;background:' + confColor + ';border-radius:3px;"></div>' +
                                '</div>' +
                                '<div style="display:flex;gap:0.8rem;font-size:0.7rem;color:var(--text-secondary);margin-bottom:0.3rem;">' +
                                    '<span title="قوة الثقة في السبب الجذري">الثقة <strong>' + pct + '%</strong></span>' +
                                    '<span title="الأثر المتوقع عند الإصلاح">الأثر <strong>' + (c.impact_if_fixed || 0) + '</strong></span>' +
                                '</div>' +
                                (c.affected_factors && c.affected_factors.length
                                    ? '<div style="font-size:0.7rem;color:var(--text-secondary);margin-bottom:0.3rem;"><strong>العوامل المتأثرة:</strong> ' + c.affected_factors.map(esc).join(' ← ') + '</div>' : '') +
                                (c.recommended_action ? '<div style="font-size:0.72rem;color:#0f766e;margin-top:0.2rem;">&#128161; ' + esc(c.recommended_action) + '</div>' : '') +
                                (c.evidence && c.evidence.length ? '<div style="font-size:0.68rem;color:var(--text-muted);margin-top:0.2rem;">' + c.evidence.slice(0, 3).map(esc).join(' | ') + '</div>' : '') +
                            '</div>';
                        }).join('');
                    } else {
                        chainsEl.innerHTML = '<div style="padding:0.5rem;color:var(--text-muted);font-size:0.78rem;">لا توجد سلاسل سببية — فعّل التحليل التاريخي أو لا توجد فشل قواعد حرج.</div>';
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
                                    ? '<span title="الاتجاه عبر الأشهر: ' + esc(n.history.map(h => h.month + ' = ' + h.value).join('، ')) + '">' + _rcSparkline(n.history) + '</span>'
                                    : '<span style="font-size:0.7rem;color:var(--text-muted);" title="الاتجاه عبر الأشهر">' + trendArrow + ' ' + esc(n.trend || '') + '</span>') +
                                '<span style="margin-right:auto;font-size:0.65rem;color:var(--text-muted);">' + esc(n.factor_type || '') + '</span>' +
                            '</div>';
                        }).join('');
                    } else {
                        treeEl.innerHTML = '<div style="padding:0.5rem;color:var(--text-muted);font-size:0.78rem;">لا توجد بيانات شجرة سببية.</div>';
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
                                .map(g => g[0] + ' (' + g[1] + ')').join('، ');
                            const types = (c.peer_types || []).join('، ');
                            return '<div style="padding:0.35rem 0;border-bottom:1px dashed #e5e7eb;">' +
                                '<div style="display:flex;justify-content:space-between;align-items:center;">' +
                                    '<span style="font-weight:600;font-size:0.78rem;">' + esc(c.indicator_name || c.indicator_code) + '</span>' +
                                    '<span style="font-size:0.7rem;color:' + color + ';font-weight:700;">' + (over ? '▲ +' : '▼ ') + Math.abs(gap).toFixed(1) + '%</span>' +
                                '</div>' +
                                '<div style="font-size:0.68rem;color:var(--text-muted);">المستشفى ' + c.hospital_value + ' مقابل متوسط النظير ' + c.peer_mean + ' (' + c.peer_count + ' مستشفى) — مئوية ' + c.hospital_percentile + ' | z=' + c.hospital_z_score + '</div>' +
                                (govParts || types ? '<div style="font-size:0.66rem;color:var(--text-muted);margin-top:0.1rem;">النظير: محافظات: ' + (govParts || '—') + ' | أنواع: ' + (types || '—') + '</div>' : '') +
                            '</div>';
                        }).join('');
                    } else {
                        peerEl.innerHTML = '<div style="padding:0.5rem;color:var(--text-muted);font-size:0.78rem;">لا توجد مقارنات نظير — تحتاج 3+ مستشفيات بنفس النوع/الملكية/المحافظة.</div>';
                    }
                }

                // ── Timeline: indicator value vs peer average with 95% CI band ──
                apiGet('/root-cause/' + hid + '/timeline?month=' + mth + '&months_back=6').then(tl => {
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
                                html += '<div style="flex:1;height:14px;background:#eee;border-radius:3px;"><div style="height:100%;width:' + pct + '%;background:#1a237e;border-radius:3px;"></div></div>';
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
                populateMonthSelect('rcMonth', false),
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
            let url = '/dashboard/kpi?';
            if (hid) url += 'hospital_id=' + hid + '&';
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
                    return '<div class="card" style="text-align:left;padding:0.8rem 1rem;background:' + bg + ';">' +
                        '<div style="display:flex;justify-content:space-between;align-items:baseline;">' +
                        '<span style="font-size:0.75rem;color:var(--text-secondary);font-weight:500;">' + k.label + '</span>' +
                        '<span style="font-size:1.1rem;font-weight:700;color:' + valColor + ';">' + k.value + (k.unit ? ' <span style="font-size:0.7rem;">' + k.unit + '</span>' : '') + '</span></div>' +
                        (k.target ? '<div style="margin-top:4px;display:flex;align-items:center;gap:4px;"><div style="flex:1;height:5px;background:var(--border-default);border-radius:3px;"><div style="width:' + barPct + '%;height:5px;background:' + (pct >= 1 ? 'var(--accent-green)' : pct >= 0.75 ? 'var(--accent-yellow)' : 'var(--accent-red)') + ';border-radius:3px;transition:width 0.4s;"></div></div><span style="font-size:0.65rem;color:var(--text-muted);">target ' + k.target + '</span></div>' : '') +
                        '</div>';
                }).join('');
            }).catch(() => {});
        }

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
            ctx.strokeStyle = color || '#3f51b5';
            ctx.lineWidth = 1.2;
            pts.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y));
            ctx.stroke();
            ctx.lineTo(pts[pts.length - 1].x, h - 3);
            ctx.lineTo(pts[0].x, h - 3);
            ctx.closePath();
            ctx.fillStyle = (color || '#3f51b5') + '18';
            ctx.fill();
        }

        // ── Ranking Table ────────────────────────────────────────
        let rankingData = [];
        let rankingSortCol = 'avg_score';
        let rankingSortAsc = false;

        export function loadRankingTable() {
            const hid = document.getElementById('dashHospital').value;
            let url = '/dashboard/ranking?';
            if (hid) url += 'hospital_id=' + hid;
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
                { key: "avg_clinical_rate", label: "Clinical Rate", render: r => r.avg_clinical_rate + "%" },
                { key: "confidence", label: "Confidence", render: r => confidenceBar(r.confidence) },
                { key: "completeness", label: "Completeness", render: r => scoreBadge(r.completeness, { decimals: 0 }) },
                { key: "consistency", label: "Consistency", render: r => scoreBadge(r.consistency, { decimals: 0 }) },
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
                    '<div class="scorecard-kpi-item" style="border-top-color:' + qc + ';background:#f0f8ff;">' +
                        '<div style="font-size:0.65rem;color:var(--text-muted);text-transform:uppercase;">Quality Score</div>' +
                        '<div style="font-size:1.5rem;font-weight:700;color:' + qc + ';">' + d.avg_score + '%</div></div>' +
                    '<div class="scorecard-kpi-item"><div style="font-size:0.65rem;color:var(--text-muted);text-transform:uppercase;">Compliance</div>' +
                        '<div style="font-size:1.1rem;font-weight:600;">' + d.avg_compliance + '%</div></div>' +
                    '<div class="scorecard-kpi-item"><div style="font-size:0.65rem;color:var(--text-muted);text-transform:uppercase;">Completeness</div>' +
                        '<div style="font-size:1.1rem;font-weight:600;">' + d.avg_completeness + '%</div></div>' +
                    '<div class="scorecard-kpi-item"><div style="font-size:0.65rem;color:var(--text-muted);text-transform:uppercase;">Consistency</div>' +
                        '<div style="font-size:1.1rem;font-weight:600;">' + d.avg_consistency + '%</div></div>' +
                    '<div class="scorecard-kpi-item"><div style="font-size:0.65rem;color:var(--text-muted);text-transform:uppercase;">Alerts</div>' +
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
                                borderColor: '#3f51b5',
                                backgroundColor: 'rgba(63,81,181,0.1)',
                                fill: true, tension: 0.3, pointRadius: 3,
                            }]
                        },
                        options: {
                            responsive: true, resizeDelay: 200,
                            plugins: { legend: { display: false } },
                            scales: { y: { min: 0, max: 100, ticks: { callback: v => v + '%' } } }
                        }
                    });
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
                                { label: 'Hospital', data: d.clinical_rates.map(r => r.value), backgroundColor: '#3f51b5', borderRadius: 3, minBarLength: 3 },
                                { label: 'Peer Avg', data: d.clinical_rates.map(r => r.peer_avg ?? null), backgroundColor: '#ff9800', borderRadius: 3, minBarLength: 3 }
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
                        resizeDelay: 200,
                        plugins: { legend: { display: false } },
                        scales: { y: { min: 0, max: 100, ticks: { callback: v => v + '%' } } }
                    }
                });

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
                        resizeDelay: 200,
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
                        resizeDelay: 200,
                        scales: { r: { min: 0, max: 100, ticks: { stepSize: 20, font: { size: 9 } } } },
                        plugins: { legend: { display: false } }
                    }
                });

                if (data.quality_trend && data.quality_trend.length) {
                    const vals = data.quality_trend.map(d => d.score);
                    renderSparkline('sparkAvgScore', vals, '#3f51b5');
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
            initDevHints();
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

        export function loadHospitalToggles() {
            apiGet('/hospitals/?include_inactive=true').then(hospitals => {
                const container = document.getElementById('hospitalToggleList');
                if (!container) return;
                container.innerHTML = hospitals.map(h =>
                    '<label style="display:flex;align-items:center;gap:0.5rem;padding:0.4rem 0;border-bottom:1px solid #eee;cursor:pointer;">' +
                    '<input type="checkbox" ' + (h.is_active ? 'checked' : '') + ' onchange="toggleHospital(' + h.id + ', this.checked)" style="width:16px;height:16px;">' +
                    '<span style="font-size:0.82rem;">' + esc(h.name) + '</span>' +
                    '</label>'
                ).join('');
            }).catch(() => {});
        }

        window.toggleHospital = function(hospitalId, isActive) {
            apiPut('/hospitals/' + hospitalId + '/toggle-active', {}).then(() => {
                clearApiCache();
                loadHospitalToggles();
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
