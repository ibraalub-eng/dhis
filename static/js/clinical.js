        import { API, apiGet, uploadedData } from './api.js';
        import { __ } from './i18n.js';
        import { esc } from './tree.js';
        import { switchTab } from './main.js';
        import { renderClinical } from './validation.js';

        // ── AI Reports ──────────────────────────────────────────
        export function populateReportMonthSelect() {
            const mSel = document.getElementById('reportMonthSelect');
            const hSel = document.getElementById('reportHospitalSelect');
            if (mSel.options.length > 1 && hSel.options.length > 1) return;
            Promise.all([
                fetch(API() + '/analysis/months').then(r => r.json()).then(data => {
                    const months = data.months || data || [];
                    mSel.innerHTML = '<option value="">All Months</option>' + months.map(m => '<option value="' + m + '">' + m + '</option>').join('');
                }).catch(() => {}),
                apiGet('/hospitals/').then(data => {
                    const list = data.value || data || [];
                    hSel.innerHTML = '<option value="">All Hospitals</option>' + list.map(h => '<option value="' + h.name + '">' + h.name + '</option>').join('');
                }).catch(() => {}),
            ]);
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
                        document.getElementById('reportMonthSelect').innerHTML = '<option value="">' + __('All Months') + '</option>' + (data.months || []).map(m => '<option value="' + m + '">' + m + '</option>').join('');
                        document.getElementById('reportHospitalSelect').innerHTML = '<option value="">' + __('All Hospitals') + '</option>' + (data.hospitals || []).map(h => '<option value="' + h + '">' + h + '</option>').join('');
                        renderReport(data);
                        return true;
                    }
                }
            } catch(e) {}
            return false;
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
                html += '<h3 style="margin:0 0 0.3rem 0;color:#1a237e;font-size:0.95rem;">' + esc(hospital) + ' <span style="font-weight:400;font-size:0.78rem;color:#888;">(' + reports.length + ')</span></h3>';

                reports.sort((a, b) => a.month.localeCompare(b.month)).forEach(r => {
                    const s = r.summary || {};
                    const score = s.overall_assessment || '';
                    const scoreIsGood = score === 'Good' || score === 'جيد';
                    const scoreIsMixed = score === __('Needs Improvement') || score === 'Needs Improvement';
                    const scoreColor = scoreIsGood ? '#2e7d32' : scoreIsMixed ? '#e65100' : '#c62828';

                    html += '<div style="margin:0.4rem 0;padding:0.5rem 0.6rem;background:#fafafa;border-left:3px solid ' + scoreColor + ';border-radius:3px;">';
                    html += '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.3rem;">';
                    html += '<strong style="font-size:0.82rem;">' + r.month + '</strong>';
                    if (score) html += '<span style="font-size:0.78rem;color:' + scoreColor + ';font-weight:600;">' + score + '</span>';
                    html += '</div>';

                    if (s.key_findings && s.key_findings.length) {
                        html += '<ul style="font-size:0.75rem;margin:0.2rem 0;padding-left:1.1rem;color:#555;">';
                        s.key_findings.slice(0, 2).forEach(f => { html += '<li>' + esc(f) + '</li>'; });
                        html += '</ul>';
                    }

                    const rp = r.risk_profile || {};
                    if (rp.overall_risk_level) {
                        const c = rp.overall_risk_level === __('Critical') || rp.overall_risk_level === 'Critical' ? '#b71c1c' : rp.overall_risk_level === 'High' ? '#c62828' : rp.overall_risk_level === __('Moderate') || rp.overall_risk_level === 'Moderate' ? '#e65100' : '#2e7d32';
                        html += '<span style="font-size:0.72rem;">' + __('Risk') + ': <strong style="color:' + c + ';">' + rp.overall_risk_level + '</strong></span>';
                    }

                    if (s.executive_summary) {
                        html += '<div style="margin-top:0.4rem;padding:0.5rem 0.6rem;background:#f3e5f5;border-left:3px solid #7b1fa2;border-radius:4px;font-size:0.75rem;color:#4a148c;line-height:1.5;">';
                        html += '<div style="font-weight:600;font-size:0.82rem;color:#6a1b9a;margin-bottom:0.3rem;">' + __('AI Assessment') + '</div>';
                        html += esc(s.executive_summary).replace(/\n/g,'<br>');
                        html += '</div>';
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

