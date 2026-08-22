        import { API, apiGet } from './api.js';
        import { __, currentLang, translations, translateDOM } from './i18n.js';
        import { _restoreUIState } from './main.js';

        // ── Indicator Tree ────────────────────────────────────────
        let currentTreeData = null;

        export function expandAllTree() {
            document.querySelectorAll('#treeContainer details').forEach(d => d.open = true);
        }
        export function collapseAllTree() {
            document.querySelectorAll('#treeContainer details').forEach(d => d.open = false);
        }

        export function initIndicatorTree() {
            const hsel = document.getElementById('treeHospitalSelect');
            const msel = document.getElementById('treeMonthSelect');
            if (!hsel || !msel) return; // التبويب لم يُحمَّل
            if (hsel.options.length > 1 && msel.options.length > 1) {
                _restoreUIState('indicator-tree');
                if (hsel.value && msel.value) loadIndicatorTree();
                return;
            }
            const phH = '<option value="">' + __('Select Hospital') + '</option>';
            const phM = '<option value="">' + __('Select Month') + '</option>';
            hsel.innerHTML = phH;
            msel.innerHTML = phM;
            Promise.all([
                apiGet('/hospitals/').then(data => {
                    const list = data.value || data || [];
                    hsel.innerHTML = phH + list.map(h => '<option value="' + h.id + '">' + h.name + '</option>').join('');
                }).catch(() => {}),
                apiGet('/analysis/months').then(months => {
                    msel.innerHTML = phM + months.map(m => '<option value="' + m + '">' + m + '</option>').join('');
                }).catch(() => {}),
            ]).then(() => {
                _restoreUIState('indicator-tree');
                if (hsel.value && msel.value) loadIndicatorTree();
            }).catch(() => {});
        }

        export function loadIndicatorTree() {
            let hospId = document.getElementById('treeHospitalSelect').value;
            let month = document.getElementById('treeMonthSelect').value;
            if (!hospId || !month) {
                document.getElementById('treeContainer').innerHTML = '<div style="color:#888;padding:1rem;">' + __('Select a hospital and month') + '</div>';
                return;
            }
            document.getElementById('treeSaveBtn').style.display = 'none';
            const raBtn = document.getElementById('treeReanalyzeBtn');
            if (raBtn) raBtn.style.display = 'none';
            const el = document.getElementById('treeContainer');
            const savedPageY = window.scrollY;
                  const savedPageX = window.scrollX;
            const savedScrollTop = el.scrollTop;
            document.getElementById('treeLoading').classList.remove('hidden');
            el.innerHTML = '';
            const summary = document.getElementById('treeSummary');
            fetch(API() + '/hospitals/' + hospId + '/indicator-tree?month=' + month)
                .then(r => r.json())
                .then(data => {
                    document.getElementById('treeLoading').classList.add('hidden');
                     sortTree(data.children);
                    currentTreeData = data;
                    renderTree();
                    el.scrollTop = savedScrollTop;
                     window.scrollTo(savedPageX, savedPageY);
                })
                .catch(e => {
                    document.getElementById('treeLoading').classList.add('hidden');
                    el.innerHTML = '<div style="color:#a00;padding:1rem;">Error: ' + e.message + '</div>';
                });
        }

                    function sortTree(nodes) {
                        if (!nodes) return;
                        nodes.sort(function(a, b) {
                            var ac = a.code, bc = b.code;
                            var an = ac.match(/\d+/), bn = bc.match(/\d+/);
                            var anum = an ? parseInt(an[0], 10) : 0;
                            var bnum = bn ? parseInt(bn[0], 10) : 0;
                            if (anum !== bnum) return anum - bnum;
                            return ac < bc ? -1 : ac > bc ? 1 : 0;
                        });
                        nodes.forEach(function(n) { sortTree(n.children); });
                    }

        function renderTree() {
            const data = currentTreeData;
            if (!data) return;
            const hospId = document.getElementById('treeHospitalSelect').value;
            const el = document.getElementById('treeContainer');
            el.innerHTML = '';
            document.getElementById('treeSummary').textContent = data.hospital + ' — ' + data.month;
            const top = document.createElement('div');
            top.className = 'tree-group';
            const header = document.createElement('div');
            header.className = 'tree-group-header';
            header.textContent = data.indicator_group;
            top.appendChild(header);
            data.children.forEach(child => {
                top.appendChild(renderTreeNodes(child, 1, hospId));
            });
            el.appendChild(top);
        }

        function collectTreeState(node, results) {
            if (node.indicator_id) {
                results.push({ indicator_id: node.indicator_id, is_enabled: node.is_enabled !== false });
            }
            (node.children || []).forEach(c => collectTreeState(c, results));
        }

        export function reanalyzeHospital() {
            const hospId = document.getElementById('treeHospitalSelect').value;
            const month = document.getElementById('treeMonthSelect').value;
            if (!hospId || !month) return;
            const btn = document.getElementById('treeReanalyzeBtn');
            if (btn) { btn.textContent = 'Analyzing...'; btn.disabled = true; }
            setStatus('loading', 'Re-analyzing ' + month + '...');
            fetch(API() + '/hospitals/' + hospId + '/re-analyze?month=' + month + '&force=true', { method: 'POST' })
                .then(r => r.json())
                .then(report => {
                    if (btn) { btn.textContent = __('Re-analyze'); btn.disabled = false; }
                    setStatus('ok', 'Analysis complete for ' + (report.hospital || 'hospital') + ' / ' + month);
                    if (report && report.hospital && report.month) {
                        // Insert/update quality report in the display
                        if (typeof displayResults === 'function' && window.uploadedData) {
                            const old = window.uploadedData.quality_reports || [];
                            const idx = old.findIndex(r => r.hospital === report.hospital && r.month === report.month);
                            if (idx >= 0) old[idx] = report;
                            else old.push(report);
                            displayResults(window.uploadedData);
                        }
                    }
                    // Redirect to dashboard to show fresh data
                    switchTab('dashboard');
                })
                .catch(e => {
                    if (btn) { btn.textContent = __('Re-analyze'); btn.disabled = false; }
                    setStatus('err', 'Re-analysis failed: ' + e.message);
                });
        }

        export function saveTreeConfig() {
            const hospId = document.getElementById('treeHospitalSelect').value;
            const month = document.getElementById('treeMonthSelect').value;
            if (!currentTreeData || !hospId || !month) return;
            const items = [];
            currentTreeData.children.forEach(c => collectTreeState(c, items));
            const btn = document.getElementById('treeSaveBtn');
            btn.textContent = __('Saving...');
            btn.disabled = true;
            fetch(API() + '/hospitals/' + hospId + '/save-tree-config?month=' + month, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: items }),
            })
                .then(r => r.json())
                .then(data => {
                    btn.textContent = __('Saved!');
                    btn.disabled = false;
                    // Show re-analyze button
                    let raBtn = document.getElementById('treeReanalyzeBtn');
                    if (!raBtn) {
                        raBtn = document.createElement('button');
                        raBtn.id = 'treeReanalyzeBtn';
                        raBtn.className = 'btn btn-sm';
                        raBtn.textContent = __('Re-analyze');
                        raBtn.style.marginLeft = '0.5rem';
                        raBtn.onclick = reanalyzeHospital;
                        btn.parentNode.insertBefore(raBtn, btn.nextSibling);
                    }
                    raBtn.style.display = 'inline-block';
                    setTimeout(() => {
                        btn.style.display = 'none';
                    }, 2000);
                })
                .catch(e => {
                    btn.textContent = __('Save Config');
                    btn.disabled = false;
                    alert('Save failed: ' + e.message);
                });
        }

        function renderTreeNodes(node, depth, hospitalId) {
            const wrapper = document.createElement('div');
            wrapper.className = 'tree-node';
            if (node.is_enabled === false) wrapper.classList.add('tree-disabled');

            const isParent = node.children && node.children.length > 0;

            const toggle = document.createElement('span');
            toggle.className = 'tree-toggle ' + (node.is_enabled !== false ? 'on' : 'off');
            toggle.textContent = node.is_enabled !== false ? '✓' : '✗';
            toggle.title = isParent
                ? (node.is_enabled !== false ? 'Disable entire branch' : 'Enable entire branch (with sub-indicators)')
                : (node.is_enabled !== false ? 'Disable this indicator' : 'Enable this indicator');
            toggle.onclick = function(e) {
                e.stopPropagation();
                const indicatorId = node.indicator_id;
                if (toggle.classList.contains('loading')) return;
                toggle.classList.add('loading');
                if (!indicatorId) { toggle.classList.remove('loading'); alert('Indicator ID not found.'); return; }
                const url = API() + '/hospitals/' + hospitalId + '/indicators/' + indicatorId + '/toggle' +
                    (isParent ? '?cascade=true' : '');
                fetch(url, { method: 'PUT' })
                    .then(r => r.json())
                    .then(data => {
                        node.is_enabled = data.is_enabled;
                        loadIndicatorTree();
                    })
                    .catch(e => {
                        toggle.classList.remove('loading');
                        alert('Toggle failed: ' + e.message);
                    });
            };

            if (isParent) {
                const details = document.createElement('details');
                details.className = 'tree-details';
                if (depth <= 0) details.open = true;

                const summary = document.createElement('summary');
                summary.className = 'tree-summary';
                summary.appendChild(toggle);
                let valHtml = '';
                if (node.value !== null) {
                    valHtml = ' <span class="tree-val"' + (node.tooltip ? ' title="' + esc(node.tooltip) + '"' : '') + '>' + esc(node.value) + '</span>';
                } else if (node.children_sum !== undefined) {
                    const childTips = (node.child_details || []).map(c => c.code + '=' + c.value).join(', ');
                    valHtml = ' <span class="tree-val tree-val-sum" title="∑ = ' + esc(childTips) + '">∑ ' + esc(node.children_sum.toFixed(1)) + '</span>';
                } else {
                    valHtml = ' <span class="tree-val tree-val-null">—</span>';
                }
                summary.insertAdjacentHTML('beforeend', '<span class="tree-code">' + esc(node.code) + '</span> ' +
                    '<span class="tree-name">' + esc(node.name) + '</span>' + valHtml +
                    ' <span class="tree-branch-badge">branch</span>');
                details.appendChild(summary);

                node.children.forEach(child => {
                    details.appendChild(renderTreeNodes(child, depth + 1, hospitalId));
                });
                wrapper.appendChild(details);
            } else {
                const line = document.createElement('div');
                line.className = 'tree-leaf';
                line.appendChild(toggle);
                const leafVal = node.value !== null
                    ? ' <span class="tree-val"' + (node.tooltip ? ' title="' + esc(node.tooltip) + '"' : '') + '>' + esc(node.value) + '</span>'
                    : ' <span class="tree-val tree-val-null">—</span>';
                line.insertAdjacentHTML('beforeend', '<span class="tree-code">' + esc(node.code) + '</span> ' +
                    '<span class="tree-name">' + esc(node.name) + '</span>' + leafVal);
                wrapper.appendChild(line);
            }
            return wrapper;
        }

        export function setStatus(type, msg) {
            const el = document.getElementById('status');
            if (!el) return;
            el.textContent = msg;
            el.className = 'status-' + type;
            // Translate the status message if possible
            if (currentLang === 'ar') {
                // Try translating the entire message first
                if (translations[msg]) {
                    el.textContent = translations[msg];
                } else {
                    // Try translating individual parts
                    translateDOM(el);
                }
            }
        }

        export function esc(s) { if (s === null || s === undefined) return ''; return String(s).replace(/[&<>"']/g, function(m) {
            return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m];
        }); }


