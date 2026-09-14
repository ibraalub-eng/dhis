        import { API, apiGet } from './api.js';
        import { __ } from './i18n.js';
        import { esc } from './tree.js';

        // ── CSV Export Utility ────────────────────────────────────
        function downloadCSV(filename, headers, rows) {
            const csvContent = [headers.join(','), ...rows.map(r => r.map(c => '"' + String(c).replace(/"/g, '""') + '"').join(','))].join('\n');
            const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = filename; a.click();
            URL.revokeObjectURL(url);
        }

        function todayStr() {
            return new Date().toISOString().slice(0, 10);
        }

        export function exportOutliersCSV() {
            const data = window._lastOutlierData;
            if (!data || !data.length) return;
            const headers = ['Hospital', 'Month', 'Indicator', 'Value', 'Benchmark', 'Z-Score', 'Peers', 'Peer Std', 'Peer Range', 'Peer Median', 'Severity', 'Features'];
            const rows = data.map(d => {
                const features = d.contributing_features
                    ? Object.entries(d.contributing_features).map(([k, v]) => k + ':' + Number(v).toFixed(3)).join('; ')
                    : '';
                return [
                    d.hospital || d.hospital_name || '',
                    d.month || '',
                    d.rate_name || 'Multi-variate',
                    d.value !== null && d.value !== undefined ? Number(d.value).toFixed(2) : '',
                    d.benchmark !== null && d.benchmark !== undefined ? Number(d.benchmark).toFixed(2) : '',
                    d.z_score !== null && d.z_score !== undefined ? Number(d.z_score).toFixed(3) : (d.anomaly_score ? Number(d.anomaly_score).toFixed(3) : ''),
                    d.peer_count !== null && d.peer_count !== undefined ? d.peer_count : '',
                    d.peer_std !== null && d.peer_std !== undefined ? Number(d.peer_std).toFixed(2) : '',
                    d.peer_min != null && d.peer_max != null ? Number(d.peer_min).toFixed(2) + ' - ' + Number(d.peer_max).toFixed(2) : '',
                    d.peer_median !== null && d.peer_median !== undefined ? Number(d.peer_median).toFixed(2) : '',
                    d.is_outlier !== undefined ? (d.is_outlier ? 'Outlier' : 'Normal') : '',
                    features
                ];
            });
            downloadCSV('outliers_' + todayStr() + '.csv', headers, rows);
        }

        export function exportRuleFailuresCSV() {
            const data = window._lastRuleFailureData;
            if (!data || !data.length) return;
            const headers = ['Hospital', 'Rule Code', 'Description', 'Severity', 'Indicator', 'Failed Months'];
            const rows = data.map(d => {
                return [
                    d.hospital || '',
                    d.rule_code || '',
                    d.rule_description || '',
                    d.severity || '',
                    d.rule_type || '',
                    d.details || ''
                ];
            });
            downloadCSV('rule_failures_' + todayStr() + '.csv', headers, rows);
        }

        // ── SHAP Waterfall Chart ──────────────────────────────────


        export function outlierLegend() {
            const box = document.getElementById('outlierLegendBox');
            if (box) box.style.display = box.style.display === 'none' ? 'block' : 'none';
        }

        // ── Outliers Tab ──────────────────────────────────────────
        export function loadOutliers() {
            const month = document.getElementById('outlierMonthFilter').value;
            const loadingEl = document.getElementById('outlierLoading');
            if (loadingEl) loadingEl.classList.remove('hidden');
            // statistical mode — Z-Score analysis
            const hosp = document.getElementById('outlierHospitalFilter').value;
            const mon = document.getElementById('outlierMonthFilter').value;
            const rate = document.getElementById('outlierRateFilter').value;
            document.getElementById('outlierTbody').innerHTML = '<tr><td colspan="8" style="text-align:center;padding:2rem;color:var(--text-muted);">Loading outliers...</td></tr>';
            let url = '/analysis/outliers?';
            if (hosp) url += 'hospital_id=' + hosp + '&';
            if (mon) url += 'month=' + encodeURIComponent(mon) + '&';
            if (rate) url += 'rate_name=' + encodeURIComponent(rate) + '&';
            apiGet(url).then(data => {
                document.getElementById('outlierLoading').classList.add('hidden');
                updateOutlierUI(data, hosp, mon, rate);
            }).catch(err => {
                document.getElementById('outlierLoading').classList.add('hidden');
                document.getElementById('outlierTbody').innerHTML = '<tr><td colspan="8" style="color:red;">Error: ' + err.message + '</td></tr>';
            });
        }

        function updateOutlierUI(resp, currentHosp, currentMon, currentRate) {
            const data = resp.data || resp;
            window._lastOutlierData = data;
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
                tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);">No outliers found.</td></tr>';
                return;
            }
            const idxById = new Map();
            data.forEach((d, i) => { if (d.id != null) idxById.set(String(d.id), i); });
            tbody.innerHTML = data.map((d, i) => {
                const z = d.z_score !== null && d.z_score !== undefined;
                const zClass = Math.abs(d.z_score) >= 3 ? 'badge-critical' : Math.abs(d.z_score) >= 2 ? 'badge-high' : 'badge-medium';
                const hasPeers = d.peer_count !== null && d.peer_count !== undefined;
                const peerRange = (d.peer_min != null && d.peer_max != null)
                    ? Number(d.peer_min).toFixed(2) + ' – ' + Number(d.peer_max).toFixed(2)
                    : '--';
                // Tooltip mirrors the audit benchmark screen's breakdown.
                const peerTip = hasPeers
                    ? ' title="' + esc('Peers: ' + d.peer_count + ' | Std: ' + (d.peer_std != null ? Number(d.peer_std).toFixed(2) : '--')
                        + ' | Median: ' + (d.peer_median != null ? Number(d.peer_median).toFixed(2) : '--')) + '"'
                    : '';
                // Peers cell is clickable when drill-down detail exists.
                const rowIdx = d.id != null ? (idxById.get(String(d.id)) ?? i) : i;
                const peerCell = hasPeers && d.peers_detail && d.peers_detail.length
                    ? '<a href="#" onclick="event.preventDefault();togglePeerPopover(this,' + rowIdx + ')" style="text-decoration:underline dotted;cursor:pointer;">' + d.peer_count + '</a>'
                    : (hasPeers ? d.peer_count : '--');
                return '<tr>' + peerTip +
                    '<td>' + esc(d.hospital) + '</td>' +
                    '<td>' + esc(d.month) + '</td>' +
                    '<td>' + esc(d.rate_name) + '</td>' +
                    '<td>' + (d.value !== null ? Number(d.value).toFixed(2) : '--') + '</td>' +
                    '<td>' + (d.benchmark !== null ? Number(d.benchmark).toFixed(2) : '--') + '</td>' +
                    '<td><span class="badge ' + zClass + '">' + (z ? Number(d.z_score).toFixed(2) : '--') + '</span></td>' +
                    '<td>' + peerCell + '</td>' +
                    '<td>' + peerRange + '</td>' +
                    '</tr>';
            }).join('');
            wireOutlierSort();
        }

        // ── Peer drill-down popover ─────────────────────────────
        // Shows every peer hospital and its rate for one outlier row.
        export function togglePeerPopover(anchor, idx) {
            const existing = document.getElementById('peerPopover');
            if (existing) { existing.remove(); return; }
            const d = (window._lastOutlierData || [])[idx];
            if (!d || !d.peers_detail || !d.peers_detail.length) return;

            const pop = document.createElement('div');
            pop.id = 'peerPopover';
            pop.style.cssText = 'position:absolute;z-index:1000;min-width:240px;max-width:320px;max-height:300px;overflow-y:auto;'
                + 'background:var(--bg-elevated,#fff);color:var(--text-primary,#222);border:1px solid var(--border-default,#ccc);'
                + 'border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,0.25);padding:0.5rem 0.6rem;font-size:0.75rem;';

            const title = document.createElement('div');
            title.style.cssText = 'font-weight:700;margin-bottom:0.35rem;white-space:nowrap;';
            title.textContent = __('Peers') + ' (' + d.peers_detail.length + ') — ' + d.rate_name;
            pop.appendChild(title);

            d.peers_detail.forEach(p => {
                const row = document.createElement('div');
                row.style.cssText = 'display:flex;justify-content:space-between;gap:1rem;padding:0.15rem 0;border-bottom:1px solid var(--border-default,#eee);';
                const name = document.createElement('span');
                name.textContent = p.hospital;
                name.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
                const rate = document.createElement('span');
                rate.textContent = Number(p.rate).toFixed(2) + '%';
                rate.style.cssText = 'font-weight:600;white-space:nowrap;';
                row.appendChild(name); row.appendChild(rate);
                pop.appendChild(row);
            });

            const note = document.createElement('div');
            note.style.cssText = 'margin-top:0.35rem;color:var(--text-muted,#888);font-size:0.68rem;';
            note.textContent = __('This hospital is excluded from its own benchmark');
            pop.appendChild(note);

            document.body.appendChild(pop);
            const rect = anchor.getBoundingClientRect();
            const top = Math.min(rect.bottom + window.scrollY + 4, window.scrollY + window.innerHeight - 310);
            let left = rect.left + window.scrollX;
            // Keep the popover on-screen (flip left if it would overflow right)
            const maxLeft = window.scrollX + document.documentElement.clientWidth - 330;
            if (left > maxLeft) left = Math.max(window.scrollX + 4, maxLeft);
            pop.style.top = Math.max(window.scrollY + 4, top) + 'px';
            pop.style.left = left + 'px';

            // Close on outside click (added after this event finishes)
            setTimeout(() => {
                document.addEventListener('click', function handler(ev) {
                    if (!pop.contains(ev.target) && ev.target !== anchor) {
                        pop.remove();
                        document.removeEventListener('click', handler);
                    }
                });
            });
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
            window._lastRuleFailureData = data;
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

