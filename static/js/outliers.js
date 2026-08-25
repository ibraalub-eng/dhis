        import { API, apiGet } from './api.js';
        import { __ } from './i18n.js';
        import { esc } from './tree.js';

        // ── Outliers Tab ──────────────────────────────────────────
        export function loadOutliers() {
            const modeEl = document.getElementById('outlierMode');
            if (!modeEl) return; // التبويب لم يُحمَّل
            const mode = modeEl.value;
            const month = document.getElementById('outlierMonthFilter').value;
            const loadingEl = document.getElementById('outlierLoading');
            if (loadingEl) loadingEl.classList.remove('hidden');
            if (mode === 'ml') {
                if (!month) {
                    document.getElementById('outlierLoading').classList.add('hidden');
                    document.getElementById('outlierTbody').innerHTML = '<tr><td colspan="6" style="text-align:center;padding:2rem;color:var(--text-muted);">Select a month.</td></tr>';
                    document.getElementById('outlierCount').textContent = '';
                    return;
                }
                apiGet('/analysis/ml?month=' + month).then(data => {
                    document.getElementById('outlierLoading').classList.add('hidden');
                    const anomalies = (data && data.ml_anomalies) || [];
                    document.getElementById('outlierCount').textContent = anomalies.length + ' hospital(s) analyzed';
                    const tbody = document.getElementById('outlierTbody');
                    if (!anomalies.length) {
                        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);">No ML anomaly data.</td></tr>';
                        return;
                    }
                    tbody.innerHTML = anomalies.map(a => {
                        const rowClass = a.is_outlier ? 'style="background:var(--severity-warning-bg);"' : '';
                        return '<tr ' + rowClass + '>' +
                            '<td>' + esc(a.hospital_name) + '</td>' +
                            '<td>' + month + '</td>' +
                            '<td>Multi-variate</td>' +
                            '<td>' + (a.anomaly_score ? a.anomaly_score.toFixed(3) : '--') + '</td>' +
                            '<td>' + (a.is_outlier ? '<span class="badge badge-critical">Outlier</span>' : '<span class="badge badge-pass">Normal</span>') + '</td>' +
                            '<td style="font-size:0.7rem;color:var(--text-muted);">' + esc(Object.keys(a.contributing_features || {}).join(', ')) + '</td>' +
                            '</tr>';
                    }).join('');
                }).catch(err => {
                    document.getElementById('outlierLoading').classList.add('hidden');
                    document.getElementById('outlierTbody').innerHTML = '<tr><td colspan="6" style="color:red;">Error: ' + err.message + '</td></tr>';
                });
                return;
            }
            // statistical mode — existing code
            const hosp = document.getElementById('outlierHospitalFilter').value;
            const mon = document.getElementById('outlierMonthFilter').value;
            const rate = document.getElementById('outlierRateFilter').value;
            document.getElementById('outlierTbody').innerHTML = '<tr><td colspan="6" style="text-align:center;padding:2rem;color:var(--text-muted);">Loading outliers...</td></tr>';
            let url = API() + '/analysis/outliers?';
            if (hosp) url += 'hospital_id=' + hosp + '&';
            if (mon) url += 'month=' + encodeURIComponent(mon) + '&';
            if (rate) url += 'rate_name=' + encodeURIComponent(rate) + '&';
            fetch(url).then(r => r.json()).then(data => {
                document.getElementById('outlierLoading').classList.add('hidden');
                updateOutlierUI(data, hosp, mon, rate);
            }).catch(err => {
                document.getElementById('outlierLoading').classList.add('hidden');
                document.getElementById('outlierTbody').innerHTML = '<tr><td colspan="6" style="color:red;">Error: ' + err.message + '</td></tr>';
            });
        }

        function updateOutlierUI(resp, currentHosp, currentMon, currentRate) {
            const data = resp.data || resp;
            const total = resp.total || data.length;
            document.getElementById('outlierCount').textContent = total + ' outlier(s)';
            // Summary
            const hospCount = new Set(data.map(d => d.hospital)).size;
            const monCount = new Set(data.map(d => d.month)).size;
            const rates = data.map(d => d.rate_name);
            const topRate = rates.length ? rates.sort((a,b)=>rates.filter(v=>v===a).length-rates.filter(v=>v===b).length).pop() : '--';
            const avgZ = data.length ? (data.reduce((s,d)=>s+Math.abs(d.z_score),0)/data.length).toFixed(2) : '--';
            const pillStyle = 'display:inline-flex;align-items:center;gap:0.25rem;border-radius:4px;padding:0.2rem 0.55rem;font-size:0.72rem;';
            document.getElementById('outlierSummary').innerHTML =
                '<span style="' + pillStyle + 'background:#7b1fa211;border:1px solid #7b1fa244;"><span style="font-weight:700;color:#7b1fa2;">' + total + '</span><span style="color:#7b1fa266;">Outliers</span></span>' +
                '<span style="' + pillStyle + 'background:#1565c011;border:1px solid #1565c044;"><span style="font-weight:700;color:#1565c0;">' + hospCount + '</span><span style="color:#1565c066;">Hospitals</span></span>' +
                '<span style="' + pillStyle + 'background:#e6510011;border:1px solid #e6510044;"><span style="font-weight:700;color:#e65100;">' + monCount + '</span><span style="color:#e6510066;">Months</span></span>' +
                '<span style="' + pillStyle + 'background:#2e7d3211;border:1px solid #2e7d3244;"><span style="font-weight:700;color:#2e7d32;">' + avgZ + '</span><span style="color:#2e7d3266;">Avg |Z|</span></span>';
            // Build filters
            const hospSel = document.getElementById('outlierHospitalFilter');
            const monSel = document.getElementById('outlierMonthFilter');
            const rateSel = document.getElementById('outlierRateFilter');
            const prevHosp = hospSel.value;
            const hospMap = {};
            data.forEach(d => { if (d.hospital_id && d.hospital) hospMap[d.hospital_id] = d.hospital; });
            hospSel.innerHTML = '<option value="">All</option>';
            Object.entries(hospMap).sort((a, b) => a[1].localeCompare(b[1])).forEach(([id, name]) => {
                const opt = document.createElement('option');
                opt.value = id; opt.textContent = name;
                hospSel.appendChild(opt);
            });
            hospSel.value = currentHosp && hospMap[currentHosp] ? currentHosp : (prevHosp && hospMap[prevHosp] ? prevHosp : '');
            populateSelectOptions(monSel, [...new Set(data.map(d => d.month))], currentMon);
            populateSelectOptions(rateSel, [...new Set(data.map(d => d.rate_name))], currentRate);
            // Render table
            const tbody = document.getElementById('outlierTbody');
            if (!data.length) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);">No outliers found.</td></tr>';
                return;
            }
            tbody.innerHTML = data.map(d => {
                const z = d.z_score !== null && d.z_score !== undefined;
                const zClass = Math.abs(d.z_score) >= 3 ? 'badge-critical' : Math.abs(d.z_score) >= 2 ? 'badge-high' : 'badge-medium';
                return '<tr>' +
                    '<td>' + esc(d.hospital) + '</td>' +
                    '<td>' + esc(d.month) + '</td>' +
                    '<td>' + esc(d.rate_name) + '</td>' +
                    '<td>' + (d.value !== null ? Number(d.value).toFixed(2) : '--') + '</td>' +
                    '<td>' + (d.benchmark !== null ? Number(d.benchmark).toFixed(2) : '--') + '</td>' +
                    '<td><span class="badge ' + zClass + '">' + (z ? Number(d.z_score).toFixed(2) : '--') + '</span></td>' +
                    '</tr>';
            }).join('');
            wireOutlierSort();
        }

        function populateSelectOptions(sel, values, currentVal) {
            const prevVal = sel.value;
            sel.innerHTML = '<option value="">All</option>';
            values.sort().forEach(x => {
                const opt = document.createElement('option');
                opt.value = x; opt.textContent = x;
                sel.appendChild(opt);
            });
            sel.value = currentVal && values.includes(currentVal) ? currentVal : (prevVal && values.includes(prevVal) ? prevVal : '');
        }

        let ruleFailSortCol = null, ruleFailSortAsc = true;
        function wireRuleFailSort() {
            document.querySelectorAll('#ruleFailTable th.sortable').forEach(th => {
                th.onclick = function() {
                    const col = this.dataset.col;
                    if (ruleFailSortCol === col) ruleFailSortAsc = !ruleFailSortAsc;
                    else { ruleFailSortCol = col; ruleFailSortAsc = true; }
                    document.querySelectorAll('#ruleFailTable th.sortable').forEach(h => { h.classList.remove('sort-asc','sort-desc'); });
                    this.classList.add(ruleFailSortAsc ? 'sort-asc' : 'sort-desc');
                    sortTableRows('ruleFailTbody', col, ruleFailSortAsc);
                };
            });
        }
        let outlierSortCol = null, outlierSortAsc = true;
        function wireOutlierSort() {
            document.querySelectorAll('#outlierTable th.sortable').forEach(th => {
                th.onclick = function() {
                    const col = this.dataset.col;
                    if (outlierSortCol === col) outlierSortAsc = !outlierSortAsc;
                    else { outlierSortCol = col; outlierSortAsc = true; }
                    document.querySelectorAll('#outlierTable th.sortable').forEach(h => { h.classList.remove('sort-asc','sort-desc'); });
                    this.classList.add(outlierSortAsc ? 'sort-asc' : 'sort-desc');
                    sortTableRows('outlierTbody', col, outlierSortAsc);
                };
            });
        }

        export function sortTableRows(tbodyId, col, asc) {
            const tbody = document.getElementById(tbodyId);
            const rows = Array.from(tbody.querySelectorAll('tr'));
            const colIdx = Array.from(tbody.parentElement.querySelectorAll('thead th')).findIndex(th => th.dataset.col === col);
            if (colIdx < 0) return;
            rows.sort((a, b) => {
                let av = a.cells[colIdx]?.textContent.trim() || '';
                let bv = b.cells[colIdx]?.textContent.trim() || '';
                const an = parseFloat(av), bn = parseFloat(bv);
                if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
                return asc ? av.localeCompare(bv) : bv.localeCompare(av);
            });
            rows.forEach(r => tbody.appendChild(r));
        }

        // ── Rule Failures Tab ──────────────────────────────────────
        export function loadRuleFailures() {
            const tbody = document.getElementById('ruleFailTbody');
            if (!tbody) return;
            const hosp = document.getElementById('ruleFailHospitalFilter').value;
            const mon = document.getElementById('ruleFailMonthFilter').value;
            const sev = document.getElementById('ruleFailSeverityFilter').value;
            const typ = document.getElementById('ruleFailTypeFilter').value;
            const loading = document.getElementById('ruleFailLoading');
            if (loading) loading.classList.remove('hidden');
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:2rem;color:var(--text-muted);">Loading rule failures...</td></tr>';
            let url = API() + '/analysis/rule-failures?';
            if (hosp) url += 'hospital_id=' + hosp + '&';
            if (mon) url += 'month=' + encodeURIComponent(mon) + '&';
            if (sev) url += 'severity=' + encodeURIComponent(sev) + '&';
            if (typ) url += 'rule_type=' + encodeURIComponent(typ) + '&';
            fetch(url).then(r => {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            }).then(data => {
                if (loading) loading.classList.add('hidden');
                updateRuleFailUI(data, hosp, mon);
            }).catch(err => {
                if (loading) loading.classList.add('hidden');
                tbody.innerHTML = '<tr><td colspan="7" style="color:red;text-align:center;">Error loading rule failures: ' + err.message + '</td></tr>';
            });
        }

        function updateRuleFailUI(resp, currentHosp, currentMon) {
            const data = resp.data || resp;
            const total = resp.total || data.length;
            document.getElementById('ruleFailCount').textContent = total + ' failure(s)';
            // Summary
            const sevCounts = {};
            const typeCounts = {};
            data.forEach(d => {
                sevCounts[d.severity] = (sevCounts[d.severity] || 0) + 1;
                typeCounts[d.rule_type] = (typeCounts[d.rule_type] || 0) + 1;
            });
            const topSev = Object.entries(sevCounts).sort((a,b) => b[1]-a[1]);
            const rfPill = 'display:inline-flex;align-items:center;gap:0.25rem;border-radius:4px;padding:0.2rem 0.55rem;font-size:0.72rem;';
            document.getElementById('ruleFailSummary').innerHTML =
                '<span style="' + rfPill + 'background:#b71c1c11;border:1px solid #b71c1c44;"><span style="font-weight:700;color:#b71c1c;">' + total + '</span><span style="color:#b71c1c66;">Failures</span></span>' +
                '<span style="' + rfPill + 'background:#e6510011;border:1px solid #e6510044;"><span style="font-weight:700;color:#e65100;">' + (topSev[0] ? topSev[0][0] : '--') + '</span><span style="color:#e6510066;">Top Severity</span></span>' +
                '<span style="' + rfPill + 'background:#1565c011;border:1px solid #1565c044;"><span style="font-weight:700;color:#1565c0;">' + new Set(data.map(d => d.hospital)).size + '</span><span style="color:#1565c066;">Hospitals</span></span>' +
                '<span style="' + rfPill + 'background:#2e7d3211;border:1px solid #2e7d3244;"><span style="font-weight:700;color:#2e7d32;">' + new Set(data.map(d => d.rule_code)).size + '</span><span style="color:#2e7d3266;">Rules</span></span>';
            // Populate filters (hospital by ID so hospital_id filter works)
            const hospSel = document.getElementById('ruleFailHospitalFilter');
            const monSel = document.getElementById('ruleFailMonthFilter');
            const prevHosp = hospSel.value;
            const hospMap = {};
            data.forEach(d => { if (d.hospital_id && d.hospital) hospMap[d.hospital_id] = d.hospital; });
            hospSel.innerHTML = '<option value="">All</option>';
            Object.entries(hospMap).sort((a, b) => a[1].localeCompare(b[1])).forEach(([id, name]) => {
                const opt = document.createElement('option');
                opt.value = id; opt.textContent = name;
                hospSel.appendChild(opt);
            });
            hospSel.value = currentHosp && hospMap[currentHosp] ? currentHosp : (prevHosp && hospMap[prevHosp] ? prevHosp : '');
            populateSelectOptions(monSel, [...new Set(data.map(d => d.month))], currentMon);
            // Render
            const tbody = document.getElementById('ruleFailTbody');
            if (!data.length) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);">No rule failures found.</td></tr>';
                return;
            }
            tbody.innerHTML = data.map(d => {
                const sevBadge = d.severity === 'CRITICAL' ? 'badge-critical' : d.severity === 'HIGH' ? 'badge-high' : d.severity === 'MEDIUM' ? 'badge-medium' : 'badge-low';
                const typeBadge = d.rule_type === 'LOGIC' ? 'badge-pass' : d.rule_type === 'CLINICAL' ? 'badge-medium' : d.rule_type === 'STATISTICAL' ? 'badge-high' : 'badge-stable';
                return '<tr>' +
                    '<td>' + esc(d.hospital) + '</td>' +
                    '<td>' + esc(d.month) + '</td>' +
                    '<td><code>' + esc(d.rule_code) + '</code></td>' +
                    '<td>' + esc(d.rule_description) + '</td>' +
                    '<td><span class="badge ' + sevBadge + '">' + esc(d.severity) + '</span></td>' +
                    '<td><span class="badge ' + typeBadge + '">' + esc(d.rule_type) + '</span></td>' +
                    '<td style="font-size:0.8rem;color:var(--text-secondary);">' + esc(d.details).substring(0,80) + '</td>' +
                    '</tr>';
            }).join('');
            wireRuleFailSort();
        }

