        import { API, apiGet, uploadedData } from './api.js';
        import { __ } from './i18n.js';
        import { esc } from './tree.js';
        import { switchTab } from './main.js';
        import { renderClinical } from './validation.js';

        // ── AI Reports ──────────────────────────────────────────
        let _reportHospitals = [];

        function _populateReportMonthSelect(months) {
            const mSel = document.getElementById('reportMonthSelect');
            const currentVal = mSel.value;
            mSel.innerHTML = '<option value="">All Months</option>' + (months || []).map(m => '<option value="' + m + '">' + m + '</option>').join('');
            if (currentVal && months.includes(currentVal)) mSel.value = currentVal;
        }

        export function onReportHospitalChange() {
            const hSel = document.getElementById('reportHospitalSelect');
            const opt = hSel.options[hSel.selectedIndex];
            const hid = opt ? opt.getAttribute('data-id') : null;
            if (hid) {
                fetch(API() + '/config/month-settings?hospital_id=' + hid)
                    .then(r => r.json())
                    .then(data => {
                        _populateReportMonthSelect(data.enabled_months || []);
                    }).catch(() => {});
            } else {
                fetch(API() + '/analysis/months').then(r => r.json()).then(data => {
                    const months = data.months || data || [];
                    _populateReportMonthSelect(months);
                }).catch(() => {});
            }
            applyReportFilter();
        }

        function _loadReportHospitals() {
            const hSel = document.getElementById('reportHospitalSelect');
            apiGet('/hospitals/').then(data => {
                const list = data.value || data || [];
                _reportHospitals = list;
                const currentVal = hSel.value;
                if (hSel.options.length <= 1) {
                    hSel.innerHTML = '<option value="">All Hospitals</option>' + list.map(h => '<option value="' + h.name + '" data-id="' + h.id + '">' + h.name + '</option>').join('');
                } else {
                    list.forEach(h => {
                        const opt = Array.from(hSel.options).find(o => o.value === h.name);
                        if (opt) opt.setAttribute('data-id', h.id);
                    });
                }
                if (currentVal && list.some(h => h.name === currentVal)) hSel.value = currentVal;
            }).catch(() => {});
        }

        export function populateReportMonthSelect() {
            const mSel = document.getElementById('reportMonthSelect');
            if (mSel.options.length <= 1) {
                fetch(API() + '/analysis/months').then(r => r.json()).then(data => {
                    const months = data.months || data || [];
                    _populateReportMonthSelect(months);
                }).catch(() => {});
            }
            _loadReportHospitals();
        }

        export function generateReport() {
            const sel = document.getElementById('reportMonthSelect');
            const month = sel.value;
            const btn = document.getElementById('generateReportBtn');
            const status = document.getElementById('reportStatus');
            const container = document.getElementById('reportResults');
            const spinner = document.getElementById('reportLoading');

            btn.disabled = true;
            btn.textContent = __('Generating...');
            status.textContent = __('Generating report, please wait...');
            container.innerHTML = '';
            spinner.classList.remove('hidden');

            let url = API() + '/analysis/generate-report';
            if (month) url += '?month=' + encodeURIComponent(month);

            fetch(url, { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    btn.disabled = false;
                    btn.textContent = __('Generate Report');
                    spinner.classList.add('hidden');
                    if (data.errors && data.errors.length) {
                        status.textContent = 'Completed with ' + data.errors.length + ' errors';
                    } else {
                        status.textContent = 'Generated ' + data.total + ' reports';
                    }
                    renderReport(data);
                })
                .catch(err => {
                    btn.disabled = false;
                    btn.textContent = __('Generate Report');
                    spinner.classList.add('hidden');
                    status.textContent = 'Error: ' + err;
                    container.innerHTML = '<p style="color:#c62828;">Failed to generate report: ' + err + '</p>';
                });
        }

        let _reportData = null;

        function renderReport(data) {
            _reportData = data;
            if (data.hospitals && typeof data.hospitals[0] === 'string') {
                data.hospitals = data.hospitals.map(h => {
                    if (typeof h === 'string') {
                        const found = _reportHospitals.find(x => x.name === h);
                        return found || { name: h };
                    }
                    return h;
                });
            }
            try { localStorage.setItem('ai_report_data', JSON.stringify(data)); } catch(e) {}
            const container = document.getElementById('reportResults');
            if (!data.reports || !data.reports.length) {
                container.innerHTML = '<p style="color:#888;text-align:center;padding:2rem;">' + __('No data found for the selected criteria.') + '</p>';
                return;
            }

            const filtSel = document.getElementById('reportHospitalSelect');
            const currentVal = filtSel.value;
            const hospSet = new Set(data.reports.map(r => r.hospital));
            const allOpts = Array.from(filtSel.options);
            allOpts.forEach(o => { o.disabled = !!(o.value && !hospSet.has(o.value)); });
            filtSel.value = currentVal && hospSet.has(currentVal) ? currentVal : '';

            applyReportFilter();
        }

        export function restoreReportData() {
            try {
                const saved = localStorage.getItem('ai_report_data');
                if (saved) {
                    const data = JSON.parse(saved);
                    if (data && data.reports && data.reports.length) {
                _reportData = data;
                _populateReportMonthSelect(data.months || []);
                const hlist = data.hospitals || [];
                document.getElementById('reportHospitalSelect').innerHTML = '<option value="">' + __('All Hospitals') + '</option>' + hlist.map(h => {
                    const name = typeof h === 'string' ? h : h.name;
                    const id = typeof h === 'object' ? h.id : null;
                    return '<option value="' + name + '"' + (id ? ' data-id="' + id + '"' : '') + '>' + name + '</option>';
                }).join('');
                _loadReportHospitals();
                renderReport(data);
                return true;
                    }
                }
            } catch(e) {}
            return false;
        }

        function _riskColor(level) {
            if (!level) return '#888';
            const l = level.toLowerCase();
            if (l === 'critical') return '#b71c1c';
            if (l === 'high') return '#c62828';
            if (l === 'moderate') return '#e65100';
            if (l === 'low') return '#2e7d32';
            return '#888';
        }

        function _scoreBadge(score) {
            if (!score) return '';
            const g = score === 'Good' || score === 'جيد';
            const m = score === 'Needs Improvement' || score === __('Needs Improvement');
            const c = g ? '#2e7d32' : m ? '#e65100' : '#c62828';
            return '<span style="display:inline-block;font-size:0.72rem;font-weight:600;color:#fff;background:' + c + ';padding:0.1rem 0.5rem;border-radius:10px;">' + esc(score) + '</span>';
        }

        function _pill(label, value, color) {
            return '<span style="display:inline-flex;align-items:center;gap:0.2rem;font-size:0.7rem;background:' + color + '11;border:1px solid ' + color + '44;border-radius:4px;padding:0.1rem 0.45rem;"><strong style="color:' + color + ';">' + esc(value) + '</strong><span style="color:' + color + '88;">' + esc(label) + '</span></span>';
        }

        export function applyReportFilter() {
            const data = _reportData;
            const container = document.getElementById('reportResults');
            if (!data || !data.reports) return;

            const selectedHospital = document.getElementById('reportHospitalSelect').value;

            let filtered = data.reports;
            if (selectedHospital) {
                filtered = filtered.filter(r => r.hospital === selectedHospital);
            }

            if (!filtered.length) {
                container.innerHTML = '<p style="color:#888;text-align:center;padding:2rem;">' + __('No reports match the selected filter.') + '</p>';
                return;
            }

            const monthsInFilter = [...new Set(filtered.map(r => r.month))].sort();
            const hospInFilter = [...new Set(filtered.map(r => r.hospital))].sort();

            let html = '<div style="margin-bottom:0.8rem;padding:0.6rem 0.8rem;background:#f5f5f5;border-radius:6px;display:flex;gap:1rem;flex-wrap:wrap;font-size:0.82rem;">';
            html += '<span><strong>' + __('Hospitals') + ':</strong> ' + hospInFilter.join(', ') + '</span>';
            html += '<span><strong>' + __('Months') + ':</strong> ' + monthsInFilter.join(', ') + '</span>';
            html += '<span><strong>' + __('Showing') + ':</strong> ' + filtered.length + ' / ' + data.reports.length + '</span>';
            if (data.errors && data.errors.length) {
                html += '<span style="color:#c62828;"><strong>' + __('Errors') + ':</strong> ' + data.errors.join('; ') + '</span>';
            }
            html += '</div>';

            const byHospital = {};
            filtered.forEach(r => {
                if (!byHospital[r.hospital]) byHospital[r.hospital] = [];
                byHospital[r.hospital].push(r);
            });

            Object.keys(byHospital).sort().forEach(hospital => {
                const reports = byHospital[hospital];
                html += '<div class="card" style="margin-bottom:0.8rem;padding:0.6rem 0.8rem;">';
                html += '<h3 style="margin:0 0 0.5rem 0;color:#1a237e;font-size:0.95rem;">' + esc(hospital) + ' <span style="font-weight:400;font-size:0.78rem;color:#888;">(' + reports.length + ')</span></h3>';

                reports.sort((a, b) => a.month.localeCompare(b.month)).forEach(r => {
                    const s = r.summary || {};
                    const score = s.overall_assessment || '';
                    const rp = r.risk_profile || {};
                    const mp = r.morbidity_profile || {};
                    const recs = r.recommendations || [];
                    const cls = r.classifications || [];

                    const deliveries = rp.total_deliveries || mp.total_deliveries || 0;
                    const csRate = cls.find(c => c.indicator_code === 'rate_cs');
                    const mmrRate = cls.find(c => c.indicator_code === 'rate_mmr');
                    const smmRate = cls.find(c => c.indicator_code === 'rate_smm');
                    const nmrRate = cls.find(c => c.indicator_code === 'rate_nmr');

                    html += '<div style="margin:0.4rem 0;padding:0.6rem 0.7rem;background:#fafafa;border-left:3px solid ' + _riskColor(rp.overall_risk_level) + ';border-radius:4px;">';

                    // ── Header row: month + score + risk + deliveries ──
                    html += '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.3rem;margin-bottom:0.3rem;">';
                    html += '<div style="display:flex;align-items:center;gap:0.5rem;">';
                    html += '<strong style="font-size:0.85rem;">' + r.month + '</strong>';
                    html += _scoreBadge(score);
                    if (rp.overall_risk_level) {
                        html += '<span style="font-size:0.72rem;color:' + _riskColor(rp.overall_risk_level) + ';font-weight:600;">Risk: ' + rp.overall_risk_level + '</span>';
                    }
                    html += '</div>';
                    html += '<span style="font-size:0.72rem;color:#888;">Deliveries: ' + deliveries + '</span>';
                    html += '</div>';

                    // ── Key indicator pills ──
                    let pills = '';
                    if (csRate) pills += _pill('CS Rate', (csRate.value != null ? Number(csRate.value).toFixed(1) : '--') + csRate.unit.replace('%',''), csRate.color);
                    if (mmrRate) pills += _pill('MMR', (mmrRate.value != null ? Number(mmrRate.value).toFixed(0) : '--'), mmrRate.color);
                    if (smmRate) pills += _pill('SMM Rate', (smmRate.value != null ? Number(smmRate.value).toFixed(1) : '--') + '%', smmRate.color);
                    if (nmrRate) pills += _pill('NMR', (nmrRate.value != null ? Number(nmrRate.value).toFixed(1) : '--'), nmrRate.color);
                    html += '<div style="display:flex;gap:0.3rem;flex-wrap:wrap;margin-bottom:0.3rem;">' + pills + '</div>';

                    // ── Key findings ──
                    if (s.key_findings && s.key_findings.length) {
                        html += '<div style="margin:0.2rem 0;">';
                        s.key_findings.forEach(f => {
                            html += '<div style="font-size:0.74rem;color:#555;padding:0.05rem 0;padding-left:0.6rem;">▸ ' + esc(f) + '</div>';
                        });
                        html += '</div>';
                    }

                    // ── Clinical indicators ──
                    if (s.clinical_indicators && s.clinical_indicators.length) {
                        html += '<details style="margin:0.3rem 0;font-size:0.74rem;">';
                        html += '<summary style="cursor:pointer;color:#1a237e;font-weight:600;font-size:0.76rem;">Clinical Indicators</summary>';
                        s.clinical_indicators.forEach(ci => {
                            html += '<div style="padding:0.05rem 0;padding-left:0.6rem;color:#555;">▸ ' + esc(ci) + '</div>';
                        });
                        html += '</details>';
                    }

                    // ── Risk profile metrics (critical/high only) ──
                    if (rp.metrics && rp.metrics.length) {
                        const bad = rp.metrics.filter(m => m.severity === 'critical' || m.severity === 'high');
                        if (bad.length) {
                            html += '<details style="margin:0.3rem 0;font-size:0.74rem;">';
                            html += '<summary style="cursor:pointer;color:' + _riskColor('critical') + ';font-weight:600;font-size:0.76rem;">Risk Metrics (' + bad.length + ' critical/high)</summary>';
                            bad.forEach(m => {
                                const sevColor = _riskColor(m.severity);
                                html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:0.1rem 0.6rem;background:' + sevColor + '08;border-left:2px solid ' + sevColor + ';margin:0.15rem 0;border-radius:2px;">';
                                html += '<span style="color:#333;">' + esc(m.metric_name) + ': <strong>' + (m.value != null ? Number(m.value).toFixed(1) : '--') + m.unit + '</strong></span>';
                                html += '<span style="font-size:0.7rem;color:' + sevColor + ';font-weight:600;">' + m.severity + '</span>';
                                html += '</div>';
                            });
                            html += '</details>';
                        }
                    }

                    // ── Morbidity profile key data ──
                    if (mp.maternal_deaths > 0 || mp.mortality_preventability_signals?.length) {
                        html += '<div style="margin:0.2rem 0;padding:0.2rem 0.5rem;background:#b71c1c08;border-left:2px solid #b71c1c;border-radius:2px;font-size:0.74rem;">';
                        if (mp.maternal_deaths > 0) {
                            html += '<div style="font-weight:600;color:#b71c1c;">Maternal Deaths: ' + mp.maternal_deaths + '</div>';
                        }
                        if (mp.mortality_preventability_signals?.length) {
                            mp.mortality_preventability_signals.forEach(sig => {
                                html += '<div style="color:#555;padding:0.05rem 0;">⚠ ' + esc(sig) + '</div>';
                            });
                        }
                        html += '</div>';
                    }

                    // ── Recommendations ──
                    if (recs.length) {
                        html += '<details style="margin:0.3rem 0;font-size:0.74rem;">';
                        html += '<summary style="cursor:pointer;color:#1a237e;font-weight:600;font-size:0.76rem;">Recommendations (' + recs.length + ')</summary>';
                        recs.forEach(rec => {
                            const pColor = _riskColor(rec.priority);
                            html += '<div style="margin:0.2rem 0;padding:0.3rem 0.5rem;background:' + pColor + '06;border-left:2px solid ' + pColor + ';border-radius:2px;">';
                            html += '<div style="display:flex;justify-content:space-between;align-items:center;gap:0.3rem;">';
                            html += '<strong style="font-size:0.74rem;color:#333;">' + esc(rec.title) + '</strong>';
                            html += '<span style="font-size:0.65rem;font-weight:600;color:' + pColor + ';text-transform:uppercase;">' + rec.priority + '</span>';
                            html += '</div>';
                            if (rec.description) {
                                html += '<div style="font-size:0.72rem;color:#555;margin:0.1rem 0;">' + esc(rec.description) + '</div>';
                            }
                            if (rec.action_items?.length) {
                                html += '<div style="font-size:0.7rem;color:#666;padding:0.1rem 0;">Actions: ' + esc(rec.action_items.join('; ')) + '</div>';
                            }
                            if (rec.data_reliable === false) {
                                html += '<span style="font-size:0.65rem;color:#c62828;">⚠ Data may be unreliable</span>';
                            }
                            html += '</div>';
                        });
                        html += '</details>';
                    }

                    // ── Overview / risk assessment text ──
                    if (s.risk_assessment || s.morbidity_assessment) {
                        html += '<details style="margin:0.3rem 0;font-size:0.74rem;">';
                        html += '<summary style="cursor:pointer;color:#1a237e;font-weight:600;font-size:0.76rem;">Assessments</summary>';
                        if (s.overview) html += '<div style="font-size:0.74rem;color:#555;margin:0.15rem 0;padding:0.2rem 0.5rem;background:#e8eaf608;border-radius:2px;">' + esc(s.overview) + '</div>';
                        if (s.risk_assessment) html += '<div style="font-size:0.74rem;color:#555;margin:0.15rem 0;padding:0.2rem 0.5rem;background:#fff3e008;border-left:2px solid #e65100;border-radius:2px;">' + esc(s.risk_assessment) + '</div>';
                        if (s.morbidity_assessment) html += '<div style="font-size:0.74rem;color:#555;margin:0.15rem 0;padding:0.2rem 0.5rem;background:#fce4ec08;border-left:2px solid #c62828;border-radius:2px;">' + esc(s.morbidity_assessment) + '</div>';
                        html += '</details>';
                    }

                    // ── All classification details ──
                    if (cls.length) {
                        html += '<details style="margin:0.3rem 0;font-size:0.74rem;">';
                        html += '<summary style="cursor:pointer;color:#555;font-size:0.74rem;">All Classifications (' + cls.length + ' indicators)</summary>';
                        cls.forEach(c => {
                            html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:0.1rem 0.5rem;border-bottom:1px solid #eee;">';
                            html += '<span style="color:#333;">' + esc(c.rate_name) + '</span>';
                            html += '<span><span style="color:' + c.color + ';font-weight:600;">' + (c.value != null ? Number(c.value).toFixed(1) : '--') + '</span> <span style="font-size:0.7rem;color:' + c.color + ';">' + esc(c.label) + '</span></span>';
                            html += '</div>';
                        });
                        html += '</details>';
                    }

                    html += '</div>';
                });
                html += '</div>';
            });

            container.innerHTML = html;
        }

        export function showReportDetail(hospital, month) {
            const data = uploadedData;
            let analysis = null;
            if (data && data.clinical_analyses) {
                analysis = data.clinical_analyses.find(a => a.hospital === hospital && a.month === month);
            }
            if (!analysis) {
                // try loading from the uploaded report data — fetch single clinical endpoint
                const hosp = uploadedData && uploadedData.hospitals ? uploadedData.hospitals.find(h => h.name === hospital) : null;
                if (hosp) {
                    fetch(API() + '/clinical/' + hosp.id + '?month=' + encodeURIComponent(month))
                        .then(r => r.json())
                        .then(ca => {
                            if (ca && ca.hospital) {
                                showModal('<h3>Clinical Intelligence: ' + esc(ca.hospital) + ' / ' + ca.month + '</h3><div id="modalClinicalContent"></div>');
                                const tmpContainer = document.createElement('div');
                                document.body.appendChild(tmpContainer);
                                // quick inline render
                                let inner = '';
                                const s = ca.summary || {};
                                inner += '<div style="padding:0.5rem;background:#e8eaf6;border-radius:4px;margin-bottom:0.5rem;">';
                                inner += '<strong>Assessment:</strong> ' + (s.overall_assessment || 'N/A');
                                inner += ' | <strong>Risk:</strong> ' + (ca.risk_profile?.overall_risk_level || 'N/A');
                                inner += '</div>';
                                if (s.executive_summary) {
                                    inner += '<div style="padding:0.5rem;background:#f3e5f5;border-left:3px solid #7b1fa2;border-radius:4px;margin-bottom:0.5rem;font-size:0.85rem;color:#4a148c;line-height:1.6;">';
                                    inner += esc(s.executive_summary).replace(/\n/g,'<br>');
                                    inner += '</div>';
                                }
                                document.getElementById('modalClinicalContent').innerHTML = inner;
                                tmpContainer.remove();
                            }
                        })
                        .catch(() => { showModal('<p>Could not load clinical details for ' + esc(hospital) + ' / ' + month + '</p>'); });
                } else {
                    showModal('<p>No clinical data available for ' + esc(hospital) + ' / ' + month + '</p>');
                }
                return;
            }
            switchTab('clinical');
            document.getElementById('clinicalHospitalSelect').value = analysis.hospital;
            document.getElementById('clinicalMonthSelect').value = analysis.month;
            renderClinical(analysis);
        }

        export function showRuleFailureDetail(ruleCode, hospital, month) {
            fetch(API() + '/analysis/rule-failures?rule_code=' + encodeURIComponent(ruleCode) + '&month=' + encodeURIComponent(month))
                .then(r => r.json())
                .then(resp => {
                    const data = resp.data || resp;
                    let inner = '';
                    if (!data.length) {
                        inner = '<p style="color:#888;">No rule failure details found.</p>';
                    } else {
                        inner = '<table style="font-size:0.8rem;"><thead><tr><th>Rule</th><th>Description</th><th>Severity</th><th>Type</th><th>Details</th></tr></thead><tbody>';
                        data.forEach(d => {
                            const sevColor = d.severity === 'CRITICAL' ? '#b71c1c' : d.severity === 'HIGH' ? '#c62828' : d.severity === __('MEDIUM') ? '#e65100' : '#2e7d32';
                            inner += '<tr><td>' + d.rule_code + '</td><td>' + d.rule_description + '</td><td><span style="color:' + sevColor + ';">' + d.severity + '</span></td><td>' + (d.rule_type || '') + '</td><td style="font-size:0.75rem;">' + (d.details || '') + '</td></tr>';
                        });
                        inner += '</tbody></table>';
                    }
                    document.getElementById('modalTitle').textContent = 'Rule Failure: ' + ruleCode;
                    document.getElementById('modalBody').innerHTML = inner;
                    document.getElementById('detailModal').classList.add('show');
                })
                .catch(err => {
                    document.getElementById('modalTitle').textContent = 'Error';
                    document.getElementById('modalBody').innerHTML = '<p style="color:red;">' + err.message + '</p>';
                    document.getElementById('detailModal').classList.add('show');
                });
        }

        export function showModal(html) {
            document.getElementById('modalTitle').innerHTML = 'AI Report Detail';
            document.getElementById('modalBody').innerHTML = html;
            document.getElementById('detailModal').classList.add('show');
        }
        export function closeModal() { document.getElementById('detailModal').classList.remove('show'); }
        document.getElementById('detailModal').addEventListener('click', function(e) { if (e.target === this) closeModal(); });
        document.getElementById('ruleEditModal').addEventListener('click', function(e) { if (e.target === this) closeRuleModal(); });
        document.addEventListener('keydown', function(e) { if (e.key === 'Escape') { closeModal(); closeRuleModal(); } });

