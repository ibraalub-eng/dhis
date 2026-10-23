        import { apiGet } from './api.js';
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
            const headers = ['Hospital', 'Month', 'Indicator', 'Value', 'Benchmark', 'Z-Score', 'Peers', 'Peer Std', 'Peer Range', 'Peer Median', 'Severity', 'Features', 'Classification'];
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
                    features,
                    d.layered_type || ''
                ];
            });
            downloadCSV('outliers_' + todayStr() + '.csv', headers, rows);
        }

        function _ruleFailureFilterQuery() {
            let q = '';
            const hosp = document.getElementById('ruleFailHospitalFilter')?.value;
            const mon = document.getElementById('ruleFailMonthFilter')?.value;
            const sev = document.getElementById('ruleFailSeverityFilter')?.value;
            const typ = document.getElementById('ruleFailTypeFilter')?.value;
            const search = (document.getElementById('ruleFailSearch')?.value || '').trim();
            if (hosp) q += 'hospital_id=' + hosp + '&';
            if (mon) q += 'month=' + encodeURIComponent(mon) + '&';
            if (sev) q += 'severity=' + encodeURIComponent(sev) + '&';
            if (typ) q += 'rule_type=' + encodeURIComponent(typ) + '&';
            // The CSV must reflect exactly what the table shows.
            if (search) q += 'q=' + encodeURIComponent(search) + '&';
            const sort = (document.getElementById('ruleFailSort')?.value || '');
            if (sort) {
                const [col, dir] = sort.split(':');
                q += 'sort_by=' + encodeURIComponent(col) + '&order=' + encodeURIComponent(dir || 'asc') + '&';
            }
            return q;
        }

        // Typing re-queries on a debounce so a 6-character term costs one
        // request, not six. Enter (or the Clear button) skips the wait.
        let _ruleFailSearchTimer = null;
        window.onRuleFailSearch = function (immediate) {
            if (_ruleFailSearchTimer) { clearTimeout(_ruleFailSearchTimer); _ruleFailSearchTimer = null; }
            const clearBtn = document.getElementById('ruleFailSearchClear');
            const has = (document.getElementById('ruleFailSearch')?.value || '').trim().length > 0;
            if (clearBtn) clearBtn.style.display = has ? 'inline-block' : 'none';
            if (immediate) { loadRuleFailures(); return; }
            _ruleFailSearchTimer = setTimeout(function () { _ruleFailSearchTimer = null; loadRuleFailures(); }, 300);
        };
        window.clearRuleFailSearch = function () {
            const input = document.getElementById('ruleFailSearch');
            if (input) input.value = '';
            window.onRuleFailSearch(true);
        };

        export async function exportRuleFailuresCSV() {
            // Re-query with the active filters and the endpoint's max page size:
            // the table only holds the first page (limit=100), so exporting
            // window._lastRuleFailureData alone silently truncated the CSV.
            let data = window._lastRuleFailureData;
            const btn = document.getElementById('ruleFailExportBtn');
            const label = btn ? btn.textContent : null;
            try {
                if (btn) { btn.disabled = true; btn.textContent = __('Exporting data...'); }
                const resp = await apiGet('/analysis/rule-failures?' + _ruleFailureFilterQuery() + 'limit=1000');
                const fetched = resp.data || resp;
                if (fetched.length) data = fetched;
            } catch (err) {
                console.warn('Rule failure export: full fetch failed, exporting loaded rows', err);
            } finally {
                if (btn) { btn.disabled = false; btn.textContent = label || 'Export CSV'; }
            }
            if (!data || !data.length) return;
            // Every field the /analysis/rule-failures endpoint returns, so the
            // CSV can be pivoted by month/hospital without re-querying.
            // The previous header row mislabelled rule_type as "Indicator" and
            // details as "Failed Months".
            const headers = ['Hospital ID', 'Hospital', 'Month', 'Rule Code', 'Description', 'Status', 'Severity', 'Type', 'Details'];
            const rows = data.map(d => {
                return [
                    d.hospital_id !== undefined && d.hospital_id !== null ? d.hospital_id : '',
                    d.hospital || '',
                    d.month || '',
                    d.rule_code || '',
                    d.rule_description || '',
                    d.status || '',
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

        // Spec §10A: classification badge colors. Gray covers the unmatched
        // case (no layered row) only; every known type gets its own badge so
        // the 8-class legend (layered-faq page) matches the table verbatim.
        // Map to the .badge-c-* classes (styles.css) — one distinct color per
        // type; the old shared severity shades collapsed CLINICAL/RAW/RATE
        // onto the same amber and hid HISTORICAL inside PEER's blue.
        export function classificationBadge(type, interpretation) {
            const cls = type === 'POSSIBLE_DATA_ENTRY_ERROR' ? 'badge-c-entry'
                : type === 'CLINICAL_INVESTIGATION_REQUIRED' ? 'badge-c-clinical'
                : type === 'PEER_ANOMALY' ? 'badge-c-peer'
                : type === 'VOLUME_DRIVEN_ANOMALY' ? 'badge-c-volume'
                : type === 'NORMAL' ? 'badge-c-normal'
                : type === 'RAW_VALUE_ANOMALY' ? 'badge-c-raw'
                : type === 'RATE_ANOMALY' ? 'badge-c-rate'
                : type === 'HISTORICAL_ANOMALY' ? 'badge-c-historical'
                : 'badge-muted';
            const label = type || '--';
            return '<span class="badge ' + cls + '" title="' + esc(interpretation || '') + '">' + esc(label) + '</span>';
        }

        // ── Outliers Tab ──────────────────────────────────────────
        export function loadOutliers() {
            const month = document.getElementById('outlierMonthFilter').value;
            const loadingEl = document.getElementById('outlierLoading');
            if (loadingEl) loadingEl.classList.remove('hidden');
            // statistical mode — Z-Score analysis
            const hosp = document.getElementById('outlierHospitalFilter').value;
            const mon = document.getElementById('outlierMonthFilter').value;
            // The filter carries the definition CODE: two derivative
            // indicators can share a display name (stillbirth per deliveries
            // vs per live births) and a name filter would mix them.
            const rate = document.getElementById('outlierRateFilter').value;
            document.getElementById('outlierTbody').innerHTML = '<tr><td colspan="10" style="text-align:center;padding:2rem;color:var(--text-muted);">Loading outliers...</td></tr>';
            let url = '/analysis/outliers?';
            if (hosp) url += 'hospital_id=' + hosp + '&';
            if (mon) url += 'month=' + encodeURIComponent(mon) + '&';
            if (rate) url += 'indicator_code=' + encodeURIComponent(rate) + '&';
            apiGet(url).then(data => {
                document.getElementById('outlierLoading').classList.add('hidden');
                updateOutlierUI(data, hosp, mon, rate);
            }).catch(err => {
                document.getElementById('outlierLoading').classList.add('hidden');
                document.getElementById('outlierTbody').innerHTML = '<tr><td colspan="10" style="color:red;">Error: ' + err.message + '</td></tr>';
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
            // Hospital options come from /hospitals/ (the full active list),
            // NOT from the filtered rows: rebuilding from `data` made picking
            // one hospital shrink the dropdown to just that hospital — every
            // other option vanished and could never be selected again (the
            // layered tab fixed this same trap the same way). Fire-and-forget;
            // rows read the current value independently, so a user without
            // hospitals.read still gets every outlier row.
            fillHospitalOptions(hospSel, prevHosp);
            populateSelectOptions(monSel, [...new Set(data.map(d => d.month))], currentMon);
            // EVERY derivative indicator from the registry — not only the ones
            // with an outlier this month. Building the options from `data` made
            // the list shrink the moment a rate was selected, so the rest of
            // the catalog could never be picked.
            fillOutlierIndicatorOptions(rateSel, currentRate);
            // Render table
            const tbody = document.getElementById('outlierTbody');
            if (!data.length) {
                tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;color:var(--text-muted);">No outliers found.</td></tr>';
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
                // Peers cell is clickable when drill-down detail exists.
                const rowIdx = d.id != null ? (idxById.get(String(d.id)) ?? i) : i;
                const peerCell = hasPeers && d.peers_detail && d.peers_detail.length
                    ? '<a href="#" onclick="event.preventDefault();togglePeerPopover(this,' + rowIdx + ')" style="text-decoration:underline dotted;cursor:pointer;">' + d.peer_count + '</a>'
                    : (hasPeers ? d.peer_count : '--');
                const formulaTitle = [
                    d.formula ? __('Formula: ') + d.formula : '',
                    d.formula_version ? __('Formula version: ') + d.formula_version : '',
                    d.indicator_id ? __('Indicator ID: ') + d.indicator_id : ''
                ].filter(Boolean).join('\n');
                // Name + formula: two derivative indicators can share a name
                // (stillbirth per deliveries vs per live births), and the
                // formula is the only thing on the row that tells them apart.
                const _formulaLine = [
                    d.formula_version ? __('Formula v') + d.formula_version : '',
                    d.formula || '',
                ].filter(Boolean).join(' · ');
                const indicatorLabel = esc(d.rate_name) + (_formulaLine
                    ? '<div style="font-size:0.66rem;color:var(--text-muted);direction:ltr;">' + esc(_formulaLine) + '</div>'
                    : '');
                // "Why?" — opens the unified explain popup for this anomaly row:
                // formula, peer set, threshold that fired, reproduced z ✓/✗.
                // The indicator CODE travels with the name: now that every
                // derivative is scanned, two rows can share a display name
                // (stillbirth per deliveries vs per live births) and a
                // name-only lookup explained whichever row came first.
                const whyBtn = '<button onclick="window.showWhyPopup({kind:\'anomaly\',hospitalId:' + Number(d.hospital_id)
                    + ',month:' + JSON.stringify(String(d.month)).replace(/"/g, '&quot;')
                    + ',rateName:' + JSON.stringify(String(d.rate_name)).replace(/"/g, '&quot;')
                    + ',indicatorCode:' + JSON.stringify(String(d.indicator_code || '')).replace(/"/g, '&quot;')
                    + '})" '
                    + 'title="' + __('Why? — formula, peers, threshold, reproduction') + '" '
                    + 'style="background:none;border:1px solid var(--border-default,#ccc);border-radius:4px;padding:1px 7px;font-size:0.7rem;cursor:pointer;color:var(--accent-blue,#1565c0);font-weight:600;">\u2139\ufe0f ' + __('Why') + '</button>';
                return '<tr>' +
                    '<td>' + esc(d.hospital) + '</td>' +
                    '<td>' + esc(d.month) + '</td>' +
                    '<td title="' + esc(formulaTitle) + '">' + indicatorLabel + '</td>' +
                    '<td>' + (d.value !== null ? Number(d.value).toFixed(2) : '--') + '</td>' +
                    '<td>' + (d.benchmark !== null ? Number(d.benchmark).toFixed(2) : '--') + '</td>' +
                    '<td><span class="badge ' + zClass + '">' + (z ? Number(d.z_score).toFixed(2) : '--') + '</span></td>' +
                    '<td>' + peerCell + '</td>' +
                    '<td>' + peerRange + '</td>' +
                    '<td>' + classificationBadge(d.layered_type, d.layered_interpretation) + '</td>' +
                    '<td>' + whyBtn + '</td>' +
                    '</tr>';
            }).join('');
            // The endpoint returns the top rows by |Z| (its cap is 100). With
            // the whole derivative catalog scanned, one filter can exceed that
            // — and a silently truncated table is how "some indicators never
            // appear" starts. Say it out loud instead.
            if (total > data.length) {
                tbody.insertAdjacentHTML('beforeend',
                    '<tr data-no-sort><td colspan="10" style="text-align:center;color:var(--text-muted);font-size:0.72rem;padding:0.6rem;">'
                    + esc(__('Showing')) + ': ' + data.length + ' / ' + total + ' — '
                    + esc(__('narrow the filter to see the rest'))
                    + '</td></tr>');
            }
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
                const rateNum = Number(p.rate);
                rate.textContent = (rateNum === 0 ? '0%' : rateNum.toFixed(4).replace(/\.?0+$/, '') + '%');
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

        // Hospital filter options are built from the full active-hospital
        // list (/hospitals/), never from the filtered response rows. When the
        // options were rebuilt from `data`, choosing one hospital emptied the
        // dropdown of every other hospital, with no way back to the full list
        // except switching the month filter. Mirrors the layered tab's filter
        // bootstrap (layered.js _initFilters).
        async function fillHospitalOptions(hospSel, currentVal) {
            try {
                const hosps = await apiGet('/hospitals/');
                const list = Array.isArray(hosps) ? hosps : [];
                const prevVal = hospSel.value;
                hospSel.innerHTML = '<option value="">All</option>';
                list.slice().sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')))
                    .forEach(h => {
                        const opt = document.createElement('option');
                        opt.value = h.id; opt.textContent = h.name;
                        hospSel.appendChild(opt);
                    });
                // Keep whichever selection survives the rebuild (the passed
                // current value wins; the in-flight select is the fallback).
                const keep = (currentVal && list.some(h => String(h.id) === String(currentVal)))
                    ? currentVal : prevVal;
                hospSel.value = list.some(h => String(h.id) === String(keep)) ? keep : '';
            } catch (err) {
                console.warn('Outlier hospital filter failed:', err);
            }
        }

        // Dropdown options for the "Derivative Indicator" filter: the full
        // registry list (/analysis/outlier-indicators), refetched like the
        // hospital list so activating or deactivating an indicator in the
        // Indicators screen shows up without a page reload. Values are
        // definition codes; the label is the display name, plus the formula
        // when two indicators share that name.
        async function fillOutlierIndicatorOptions(sel, currentVal) {
            const prevVal = sel.value;
            try {
                const resp = await apiGet('/analysis/outlier-indicators');
                const list = Array.isArray(resp) ? resp : [];
                const nameCounts = {};
                list.forEach(i => { nameCounts[i.name] = (nameCounts[i.name] || 0) + 1; });
                sel.innerHTML = '<option value="">All</option>';
                list.forEach(i => {
                    const opt = document.createElement('option');
                    opt.value = i.code;
                    opt.textContent = nameCounts[i.name] > 1 && i.formula
                        ? i.name + ' — ' + i.formula
                        : i.name;
                    if (nameCounts[i.name] > 1) opt.title = i.formula || '';
                    sel.appendChild(opt);
                });
                const keep = (currentVal && list.some(i => i.code === currentVal))
                    ? currentVal : prevVal;
                sel.value = list.some(i => i.code === keep) ? keep : '';
            } catch (err) {
                console.warn('Outlier indicator filter failed:', err);
            }
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
        // Header click → the Sort select → a server-side re-query. Sorting the
        // loaded page in the DOM silently ordered only the first 100 rows, and
        // a month column compared as a NUMBER ("2026-08" → 2026) so every month
        // of a year tied. The server sorts the whole filtered result set.
        const RULE_FAIL_SORT_KEY = { hospital: 'hospital', month: 'month', rule_code: 'rule_code', severity: 'severity', rule_type: 'type', rule_description: 'description', details: 'details' };
        function _setRuleFailSort(col, asc, label) {
            const sel = document.getElementById('ruleFailSort');
            if (!sel) return;
            const key = RULE_FAIL_SORT_KEY[col] || col;
            const dir = asc ? 'asc' : 'desc';
            const value = key + ':' + dir;
            if (!Array.from(sel.options).some(o => o.value === value)) {
                // Header-driven sort on a column the select does not list yet
                // (Description, Details): append it, labelled from the header so
                // the drop-down reads the same as the table.
                const opt = document.createElement('option');
                opt.value = value;
                opt.textContent = (label || col) + (dir === 'desc' ? ' ↓' : ' ↑');
                sel.appendChild(opt);
            }
            sel.value = value;
        }
        function _syncRuleFailSortArrows() {
            const sel = document.getElementById('ruleFailSort');
            const cur = (sel && sel.value) ? sel.value : '';
            const [col, dir] = cur.split(':');
            document.querySelectorAll('#ruleFailTable th.sortable').forEach(h => {
                h.classList.remove('sort-asc', 'sort-desc');
                if (!col) return;
                // "severity:asc" means critical-first on the server (rank order).
                const asc = col === 'severity' ? dir === 'asc' : dir !== 'desc';
                if (h.dataset.col === col) h.classList.add(asc ? 'sort-asc' : 'sort-desc');
            });
        }
        function wireRuleFailSort() {
            document.querySelectorAll('#ruleFailTable th.sortable').forEach(th => {
                th.onclick = function() {
                    const col = this.dataset.col;
                    if (ruleFailSortCol === col) ruleFailSortAsc = !ruleFailSortAsc;
                    // First click on Month means "newest first" — the useful
                    // default for a chronological table.
                    else { ruleFailSortCol = col; ruleFailSortAsc = col !== 'month'; }
                    _setRuleFailSort(col, ruleFailSortAsc, this.textContent.trim());
                    loadRuleFailures();
                };
            });
            _syncRuleFailSortArrows();
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
            // Placeholder rows (e.g. a truncation notice) opt out of sorting and
            // stay at the bottom; sorting their text would interleave them with
            // real data rows.
            const pinned = Array.from(tbody.querySelectorAll('tr[data-no-sort]'));
            const rows = Array.from(tbody.querySelectorAll('tr:not([data-no-sort])'));
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
            pinned.forEach(r => tbody.appendChild(r));
        }

        // ── Rule Failures Tab ──────────────────────────────────────
        export function loadRuleFailures() {
            const tbody = document.getElementById('ruleFailTbody');
            if (!tbody) return;
            const hosp = document.getElementById('ruleFailHospitalFilter').value;
            const mon = document.getElementById('ruleFailMonthFilter').value;
            const sev = document.getElementById('ruleFailSeverityFilter').value;
            const typ = document.getElementById('ruleFailTypeFilter').value;
            const search = (document.getElementById('ruleFailSearch')?.value || '').trim();
            const sortVal = (document.getElementById('ruleFailSort')?.value || '');
            const [sortBy, sortOrder] = sortVal ? sortVal.split(':') : [null, 'asc'];
            const loading = document.getElementById('ruleFailLoading');
            if (loading) loading.classList.remove('hidden');
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:2rem;color:var(--text-muted);">Loading rule failures...</td></tr>';
            let url = '/analysis/rule-failures?';
            if (hosp) url += 'hospital_id=' + hosp + '&';
            if (mon) url += 'month=' + encodeURIComponent(mon) + '&';
            if (sev) url += 'severity=' + encodeURIComponent(sev) + '&';
            if (typ) url += 'rule_type=' + encodeURIComponent(typ) + '&';
            if (search) url += 'q=' + encodeURIComponent(search) + '&';
            if (sortBy) url += 'sort_by=' + encodeURIComponent(sortBy) + '&order=' + encodeURIComponent(sortOrder || 'asc') + '&';
            apiGet(url).then(data => {
                if (loading) loading.classList.add('hidden');
                updateRuleFailUI(data, hosp, mon, search);
            }).catch(err => {
                if (loading) loading.classList.add('hidden');
                tbody.innerHTML = '<tr><td colspan="8" style="color:red;text-align:center;">Error loading rule failures: ' + err.message + '</td></tr>';
            });
        }

        function updateRuleFailUI(resp, currentHosp, currentMon, currentSearch) {
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
            // Populate filters (hospital by ID so hospital_id filter works).
            // While a search is active the rows are already narrowed, so
            // rebuilding these lists from them would delete the very hospitals
            // the user still needs to switch to.
            const hospSel = document.getElementById('ruleFailHospitalFilter');
            const monSel = document.getElementById('ruleFailMonthFilter');
            const prevHosp = hospSel.value;
            if (!currentSearch) {
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
            }
            // Render
            const tbody = document.getElementById('ruleFailTbody');
            if (!data.length) {
                // Distinguish "nothing failed" from "your search matched nothing"
                // — otherwise a working search reads as an empty screen.
                tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);">' +
                    (currentSearch
                        ? 'No rule failures match &quot;' + esc(currentSearch) + '&quot;.'
                        : 'No rule failures found.') +
                    '</td></tr>';
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
                    '<td><button onclick="window.showWhyPopup(\'rule\',' + Number(d.hospital_id) + ',\'' + esc(d.month) + '\',null,' + JSON.stringify(String(d.rule_code)).replace(/"/g, '&quot;') + ')" '
                        + 'title="' + __('Why did this rule fail?') + '" '
                        + 'style="background:none;border:1px solid var(--border-default,#ccc);border-radius:4px;padding:1px 7px;font-size:0.7rem;cursor:pointer;color:var(--accent-blue,#1565c0);font-weight:600;">\u2139\ufe0f ' + __('Why') + '</button></td>' +
                    '</tr>';
            }).join('');
            wireRuleFailSort();
        }
