        import { API, apiGet } from './api.js';
        import { __ } from './i18n.js';
        import { esc, setStatus } from './tree.js';
        import { _restoreUIState } from './main.js';

        // ── Smart Data Entry ──────────────────────────────────────
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const statusDiv = document.getElementById('status');
        const fileListDiv = document.getElementById('fileList');
        let previewFilePath = null;
        let previewFiles = null;
        let previewFileName = null;

        dropZone.addEventListener('click', () => fileInput.click());
        dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
        dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
        dropZone.addEventListener('drop', e => { e.preventDefault(); dropZone.classList.remove('dragover'); if(e.dataTransfer.files.length) showPreview(e.dataTransfer.files); });
        fileInput.addEventListener('change', () => { if(fileInput.files.length) showPreview(fileInput.files); });
        // Show file names on selection
        fileInput.addEventListener('input', () => {
            const list = document.getElementById('fileList');
            if (fileInput.files.length) {
                list.classList.remove('hidden');
                list.innerHTML = Array.from(fileInput.files).map(f => '<div style="display:flex;align-items:center;gap:0.4rem;font-size:0.82rem;">' +
                    '<span style="color:#3f51b5;">📄</span><span>' + f.name + '</span>' +
                    '<span style="color:#999;font-size:0.75rem;">(' + (f.size / 1024).toFixed(1) + ' KB)</span></div>').join('');
            } else { list.classList.add('hidden'); list.innerHTML = ''; }
        });

        function updateStep(step) {
            for (let i = 1; i <= 4; i++) {
                const el = document.querySelector('.step-dot[data-step="' + i + '"]');
                if (!el) continue;
                if (i < step) { el.classList.remove('active'); el.classList.add('done'); }
                else if (i === step) { el.classList.add('active'); el.classList.remove('done'); }
                else { el.classList.remove('active', 'done'); }
            }
        }

        function showPreview(files) {
            updateStep(2);
            const fd = new FormData();
            fd.append('file', files[0]);
            previewFiles = files;
            setStatus('loading', 'Reading file: ' + files[0].name + '...');
            fetch(API() + '/upload/preview', { method: 'POST', body: fd }).then(r => r.json()).then(data => {
                previewFilePath = data.file_path;
                previewFileName = data.filename;
                const area = document.getElementById('previewArea');
                area.style.display = 'block';
                document.getElementById('previewInfo').textContent = data.total_rows + ' rows | ' + data.hospitals.length + ' hospitals | ' + data.months.length + ' months';
                // Build table
                const cols = [__('Hospital'), 'Month', __('Indicator'), __('Value')];
                let thead = '<tr>' + cols.map(c => '<th>' + c + '</th>').join('') + '</tr>';
                let tbody = data.sample_rows.map(r => '<tr><td>' + esc(r.hospital) + '</td><td>' + esc(r.month) + '</td><td>' + esc(r.indicator) + '</td><td>' + (r.value !== null ? r.value : '<span style="color:red;">MISSING</span>') + '</td></tr>').join('');
                document.querySelector('#previewTable thead').innerHTML = thead;
                document.querySelector('#previewTable tbody').innerHTML = tbody;
                setStatus('ok', 'Preview ready — ' + data.total_rows + ' records from ' + data.hospitals.length + ' hospitals across ' + data.months.length + ' months. Scroll to review, then click Confirm.');
            }).catch(err => {
                setStatus('err', 'Preview failed: ' + err.message);
            });
        }

        export function confirmImport() {
            if (!previewFileName) return;
            updateStep(3);
            setStatus('loading', 'Importing and analyzing ' + previewFileName + '...');
            const progress = document.getElementById('uploadProgress');
            progress.classList.remove('hidden');
            const fill = document.getElementById('uploadProgressFill');
            const txt = document.getElementById('uploadProgressText');
            fill.style.width = '30%';
            txt.textContent = __('Processing file...');
            showLoader('Analyzing data...');
            fetch(API() + '/analysis/process-preview?filename=' + encodeURIComponent(previewFileName), { method: 'POST' })
                .then(r => { if (!r.ok) return r.text().then(t => { throw new Error(t); }); return r.json(); })
                .then(result => {
                hideLoader();
                fill.style.width = '100%';
                txt.textContent = __('Analysis complete.');
                setTimeout(() => { progress.classList.add('hidden'); fill.style.width = '0%'; }, 2000);
                uploadedData = result;
                updateStep(4);
                setStatus('ok', result.message + ' ' + __('View results in Dashboard tab.'));
                displayResults(result);
                document.getElementById('previewArea').style.display = 'none';
                previewFilePath = null;
                previewFiles = null;
                previewFileName = null;
                refreshSavedFiles();
                _tabInited.delete('dashboard');
                switchTab('dashboard');
            }).catch(e => {
                hideLoader();
                fill.style.width = '0%';
                progress.classList.add('hidden');
                let detail = e.message;
                try { const m = detail.match(/"detail"\s*:\s*"([^"]+)"/); if (m) detail = m[1]; } catch {}
                setStatus('err', 'Import failed: ' + detail);
            });
        }

        export function cancelPreview() {
            updateStep(1);
            document.getElementById('previewArea').style.display = 'none';
            previewFilePath = null;
            previewFiles = null;
            previewFileName = null;
            fileInput.value = '';
        }



        let allQualityReports = [];

        export function displayResults(result) {
            const section = document.getElementById('resultsSection');
            section.classList.remove('hidden');

            allQualityReports = result.quality_reports || [];

            const months = [...new Set(allQualityReports.map(r => r.month))].sort();
            const hospOpts = result.hospitals.map(h => '<option value="' + h.id + '">' + h.name + '</option>').join('');
            const monthOpts = months.map(m => '<option value="' + m + '">' + m + '</option>').join('');
            const monthOptsAll = result.months.map(m => '<option value="' + m + '">' + m + '</option>').join('');
            const hospOptsEsc = result.hospitals.map(h => '<option value="' + esc(h.name) + '">' + esc(h.name) + '</option>').join('');
            const hospOptsTree = result.hospitals.map(h => '<option value="' + h.id + '">' + esc(h.name) + '</option>').join('');
            const monthOptsTree = result.months.map(m => '<option value="' + m + '">' + m + '</option>').join('');

            _setHtml('qualityMonthFilter', '<option value="all">All Months</option>' + monthOpts);
            _setHtml('qualityHospitalFilter', '<option value="all">All Hospitals</option>' + result.hospitals.map(h => '<option value="' + esc(h.name) + '">' + esc(h.name) + '</option>').join(''));
            _setHtml('trendHospitalSelect', hospOpts);
            _setHtml('compareMonthSelect', monthOptsAll);
            _setHtml('clinicalHospitalSelect', '<option value="">Select Hospital</option>' + hospOpts);
            _setHtml('clinicalMonthSelect', '<option value="">Select Month</option>' + monthOptsAll);
            _setHtml('reportMonthSelect', '<option value="">All Months</option>' + monthOptsAll);
            _setHtml('reportHospitalSelect', '<option value="">All Hospitals</option>' + hospOptsEsc);
            _setHtml('treeHospitalSelect', hospOptsTree);
            _setHtml('treeMonthSelect', monthOptsTree);

            filterQualityReports();
        }
        function _setHtml(id, html) { const el = document.getElementById(id); if (el) el.innerHTML = html; }


        export function filterPriorityTable(level) {
            var table = document.getElementById('priorityTable');
            if (!table) return;
            var rows = table.querySelectorAll('tbody tr');
            rows.forEach(function(row) {
                if (level === 'ALL' || row.getAttribute('data-level') === level) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
            var badges = table.closest('div').querySelectorAll('.badge');
            badges.forEach(function(b) {
                b.style.fontWeight = '400';
                b.style.opacity = '0.5';
            });
            var clickedBadge = table.closest('div').querySelector('.badge-' + level.toLowerCase()) || table.closest('div').querySelector('.badge-all');
            if (clickedBadge) {
                clickedBadge.style.fontWeight = '700';
                clickedBadge.style.opacity = '1';
            }
        }


        export async function loadQualityReports(skipRestore) {
            document.getElementById('qualityLoading').classList.remove('hidden');
            try {
                const data = await apiGet('/reports/');
                document.getElementById('qualityLoading').classList.add('hidden');
                if (data && data.length > 0) {
                    document.getElementById('resultsSection').classList.remove('hidden');
                }
                allQualityReports = data || [];
                // Populate filters
                const qFilter = document.getElementById('qualityMonthFilter');
                const months = [...new Set(allQualityReports.map(r => r.month))].sort();
                qFilter.innerHTML = '<option value="all">All Months</option>' + months.map(m => '<option value="' + m + '">' + m + '</option>').join('');
                const hFilter = document.getElementById('qualityHospitalFilter');
                const hospitals = [...new Set(allQualityReports.map(r => r.hospital))].sort();
                hFilter.innerHTML = '<option value="all">All Hospitals</option>' + hospitals.map(h => '<option value="' + esc(h) + '">' + esc(h) + '</option>').join('');
                if (!skipRestore) _restoreUIState('quality');
                filterQualityReports();
            } catch(e) {
                document.getElementById('qualityLoading').classList.add('hidden');
                document.getElementById('reportsGrid').innerHTML = '<p style="color:#888;text-align:center;padding:2rem;">Unable to load cached reports. Upload data first.</p>';
            }
        }

        export function filterQualityReports() {
            const qf = document.getElementById('qualityMonthFilter');
            const hf = document.getElementById('qualityHospitalFilter');
            if (!qf || !hf) return;
            const month = qf.value;
            const hospital = hf.value;
            let filtered = allQualityReports;
            if (month !== 'all') filtered = filtered.filter(r => r.month === month);
            if (hospital !== 'all') filtered = filtered.filter(r => r.hospital === hospital);
            const grid = document.getElementById('reportsGrid');
            grid.innerHTML = '';
            document.getElementById('qualityCount').textContent = filtered.length + ' report' + (filtered.length !== 1 ? 's' : '');
            if (!filtered.length) { grid.innerHTML = '<p style="color:#888;text-align:center;padding:2rem;">No reports match the selected filters.</p>'; return; }
            filtered.forEach(r => {
                const score = r.data_quality_score;
                const scoreColor = score >= 80 ? '#2e7d32' : score >= 50 ? '#e65100' : '#c62828';
                const barColor = score >= 80 ? '#4caf50' : score >= 50 ? '#ff9800' : '#f44336';
                const issueCount = r.issues ? r.issues.length : 0;
                const outlierCount = r.outliers ? r.outliers.length : 0;
                const card = document.createElement('div');
                card.className = 'report-card ' + (score >= 80 ? 'good' : score >= 50 ? 'medium' : 'poor');
                card.setAttribute('data-hospital', r.hospital);
                card.setAttribute('data-month', r.month);
                card.innerHTML = '<h3>' + r.hospital + '</h3><div class="month">' + r.month + '</div><div class="score" style="color:' + scoreColor + '">' + score + '</div><div class="progress-bar"><div class="progress-bar-fill" style="width:' + score + '%;background:' + barColor + '"></div></div><div style="margin-top:0.7rem;font-size:0.8rem;color:#666;">' + issueCount + ' issues &bull; ' + outlierCount + ' outliers</div>';
                card.addEventListener('click', function() { showDetail(r.hospital, r.month); });
                grid.appendChild(card);
            });
        }

        let currentValidation = [];
        let valSortCol = 'rule_code', valSortDir = 'asc', valFilterStatus = 'all', valFilterSeverity = 'all', valFilterType = 'all';
        let anomSortCol = 'rate_name', anomSortDir = 'asc', anomFilterOutlier = 'all';
        let currentAnomalies = [];
        const SEVERITY_ORDER = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1};
        const STATUS_ORDER = {'FAIL': 2, 'PASS': 1};

        let currentHospitalId = null;
        let currentHospitalName = null;
        let currentMonth = null;

        export async function showDetail(hospitalName, month) {
            const modal = document.getElementById('detailModal');
            const title = document.getElementById('modalTitle');
            const body = document.getElementById('modalBody');
            title.textContent = hospitalName + ' \u2014 ' + month;
            body.innerHTML = '<p style="text-align:center;padding:2rem;">Loading...</p>';
            modal.classList.add('show');
            try {
                const hospitals = await apiGet('/hospitals/');
                const hosp = hospitals.find(h => h.name === hospitalName);
                if (!hosp) throw new Error('Hospital not found');
                currentHospitalId = hosp.id;
                currentHospitalName = hospitalName;
                currentMonth = month;
                const report = await apiGet('/reports/detail/' + hosp.id + '?month=' + month);
                currentValidation = report.validation_results || [];
                currentAnomalies = report.anomaly_results || [];
                renderDetail(body, report);
            } catch(e) {
                body.innerHTML = '<p style="color:#c62828;">Error: ' + e.message + '</p>';
            }
        }



        function sortAndFilterValidation() {
            let data = [...currentValidation];
            if (valFilterStatus !== 'all') data = data.filter(v => v.status === valFilterStatus);
            if (valFilterSeverity !== 'all') data = data.filter(v => v.severity === valFilterSeverity);
            if (valFilterType !== 'all') data = data.filter(v => v.rule_type === valFilterType);
            data.sort((a, b) => {
                let va, vb;
                if (valSortCol === 'rule_code') { va = a.rule_code; vb = b.rule_code; }
                else if (valSortCol === 'rule_description') { va = a.rule_description; vb = b.rule_description; }
                else if (valSortCol === 'status') { va = STATUS_ORDER[a.status]||0; vb = STATUS_ORDER[b.status]||0; }
                else if (valSortCol === 'severity') { va = SEVERITY_ORDER[a.severity]||0; vb = SEVERITY_ORDER[b.severity]||0; }
                else { va = a[valSortCol]||''; vb = b[valSortCol]||''; }
                if (typeof va === 'string') { va = va.toLowerCase(); vb = vb.toLowerCase(); }
                return va < vb ? (valSortDir==='asc'?-1:1) : va > vb ? (valSortDir==='asc'?1:-1) : 0;
            });
            return data;
        }

        function sortAndFilterAnomalies() {
            let data = [...currentAnomalies];
            if (anomFilterOutlier === 'yes') data = data.filter(a => a.is_outlier === true);
            else if (anomFilterOutlier === 'no') data = data.filter(a => a.is_outlier === false);
            data.sort((a, b) => {
                let va, vb;
                if (anomSortCol === 'rate_name') { va = a.rate_name||''; vb = b.rate_name||''; }
                else if (anomSortCol === 'value') { va = a.value||0; vb = b.value||0; }
                else if (anomSortCol === 'benchmark') { va = a.benchmark||0; vb = b.benchmark||0; }
                else if (anomSortCol === 'z_score') { va = a.z_score||0; vb = b.z_score||0; }
                else if (anomSortCol === 'is_outlier') { va = a.is_outlier?1:0; vb = b.is_outlier?1:0; }
                else { va = a[anomSortCol]||''; vb = b[anomSortCol]||''; }
                if (typeof va === 'string') { va = va.toLowerCase(); vb = vb.toLowerCase(); }
                return va < vb ? (anomSortDir==='asc'?-1:1) : va > vb ? (anomSortDir==='asc'?1:-1) : 0;
            });
            return data;
        }

        function sh(text, colKey, curCol, curDir) {
            const isCur = curCol === colKey;
            const cls = isCur ? (curDir==='asc' ? 'sort-asc' : 'sort-desc') : '';
            return '<th class="sortable ' + cls + '" data-col="' + colKey + '">' + text + '</th>';
        }

        function renderDetail(container, r) {
            const score = r.data_quality_score;
            const scoreClass = score >= 80 ? 'score-good' : score >= 50 ? 'score-medium' : 'score-poor';
            let html = '<div style="display:flex;gap:0.5rem;justify-content:flex-end;margin-bottom:0.8rem;">';

            html += '</div>';
            html += '<div class="grid-2"><div style="text-align:center;"><div class="score-circle ' + scoreClass + '" style="margin:0 auto;">' + score + '</div><p style="font-size:0.85rem;color:#888;margin-top:0.5rem;">Data Quality Score</p><div class="grid-4" style="margin-top:1rem;"><div class="stat-box"><div class="value">' + (r.rule_compliance!==null?r.rule_compliance+'%':'--') + '</div><div class="label">Rule Compliance</div></div><div class="stat-box"><div class="value">' + (r.completeness!==null?r.completeness+'%':'--') + '</div><div class="label">Completeness</div></div><div class="stat-box"><div class="value">' + (r.consistency!==null?r.consistency+'%':'--') + '</div><div class="label">Consistency</div></div><div class="stat-box"><div class="value">' + (r.outlier_penalty!==null?r.outlier_penalty+'%':'--') + '</div><div class="label">Outlier Penalty</div></div></div></div><div><h3 style="font-size:0.95rem;color:#1a237e;margin-bottom:0.5rem;">Issues (' + (r.issues?r.issues.length:0) + ')</h3>';
            if (r.issues && r.issues.length > 0) { html += '<ul class="issue-list">'; r.issues.forEach(i => { html += '<li>' + i + '</li>'; }); html += '</ul>'; } else { html += '<p style="color:#2e7d32;font-size:0.85rem;">No issues found</p>'; }
            html += '</div></div>';

            if (r.confidence) {
                const c = r.confidence;
                const confClass = c.overall_confidence >= 80 ? 'score-good' : c.overall_confidence >= 50 ? 'score-medium' : 'score-poor';
                const levelColors = {'HIGH':'#2e7d32','MEDIUM':'#e65100','LOW':'#c62828','CRITICAL':'#b71c1c'};
                const levelBg = {'HIGH':'#e8f5e9','MEDIUM':'#fff3e0','LOW':'#ffebee','CRITICAL':'#fce4ec'};
                html += '<div style="margin-top:1.5rem;border-top:2px solid #e8eaf6;padding-top:1rem;"><h3 style="color:#1a237e;">Confidence Score per Indicator</h3>';
                html += '<div class="grid-2" style="align-items:center;">';
                html += '<div style="text-align:center;"><div class="score-circle ' + confClass + '" style="margin:0 auto;width:90px;height:90px;font-size:1.6rem;">' + c.overall_confidence + '%</div><p style="font-size:0.85rem;color:#888;margin-top:0.5rem;">Overall Confidence</p><span class="badge" style="background:' + (levelBg[c.level]||'#eee') + ';color:' + (levelColors[c.level]||'#888') + ';font-size:0.8rem;padding:0.3rem 0.8rem;">' + c.level + '</span></div>';
                html += '<div>';
                if (c.by_group) {
                    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:0.4rem;font-size:0.8rem;">';
                    for (const [grp, val] of Object.entries(c.by_group)) {
                        const gc = val >= 80 ? '#2e7d32' : val >= 50 ? '#e65100' : '#c62828';
                        html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:0.2rem 0.5rem;background:#f5f5f5;border-radius:4px;"><span>' + grp + '</span><span style="font-weight:700;color:' + gc + ';">' + val + '%</span></div>';
                    }
                    html += '</div>';
                }
                html += '</div></div>';
                if (c.by_level || c.priority_verify) {
                    var bl = c.by_level || {};
                    if (!bl.HIGH && c.priority_verify) bl.HIGH = (c.priority_verify.length > 0 ? 0 : 0);
                    html += '<div style="margin-top:0.6rem;display:flex;gap:0.5rem;font-size:0.8rem;flex-wrap:wrap;">';
                    html += '<span class="badge badge-all" style="cursor:pointer;background:#1a237e;color:white;font-weight:700;" onclick="filterPriorityTable(\'ALL\')">ALL</span>';
                    var levels = ['HIGH','MEDIUM','LOW','CRITICAL'];
                    levels.forEach(function(lv) {
                        var cnt = bl[lv] || 0;
                        html += '<span class="badge badge-' + lv.toLowerCase() + '" style="cursor:pointer;" onclick="filterPriorityTable(\'' + lv + '\')">' + lv + ': ' + cnt + '</span>';
                    });
                    html += '</div>';
                }
                if (c.priority_verify && c.priority_verify.length > 0) {
                    html += '<div style="margin-top:0.8rem;"><h4 style="font-size:0.85rem;color:#c62828;margin-bottom:0.4rem;">Priority Verification (' + c.priority_verify.length + ')</h4>';
                    html += '<table id="priorityTable" style="font-size:0.8rem;"><thead><tr><th>Indicator</th><th>Value</th><th>Confidence</th><th>Level</th><th>Recommendations</th></tr></thead><tbody>';
                    c.priority_verify.forEach(p => {
                        const pc = p.confidence >= 80 ? '#2e7d32' : p.confidence >= 50 ? '#e65100' : '#c62828';
                        const recs = (p.recommendations || []).join('; ');
                        html += '<tr data-level="' + p.level + '"><td>' + p.indicator_name + '</td><td>' + (p.value !== null && p.value !== undefined ? p.value : '<span style="color:#c62828;">MISSING</span>') + '</td><td style="font-weight:700;color:' + pc + ';">' + p.confidence + '%</td><td><span class="badge badge-' + p.level.toLowerCase() + '">' + p.level + '</span></td><td style="font-size:0.75rem;color:#666;">' + recs + '</td></tr>';
                    });
                    html += '</tbody></table></div>';
                }
                if (c.summary) {
                    html += '<p style="margin-top:0.6rem;font-size:0.8rem;color:#555;font-style:italic;background:#f5f5f5;padding:0.5rem;border-radius:4px;">' + c.summary + '</p>';
                }
                html += '</div>';
            }

            if (r.validation_results && r.validation_results.length > 0) {
                const failC = r.validation_results.filter(v=>v.status==='FAIL').length;
                const passC = r.validation_results.filter(v=>v.status==='PASS').length;
                const highC = r.validation_results.filter(v=>v.severity==='HIGH').length;
                const medC = r.validation_results.filter(v=>v.severity==='MEDIUM').length;
                const lowC = r.validation_results.filter(v=>v.severity==='LOW').length;
                const types = [...new Set(r.validation_results.map(v=>v.rule_type).filter(Boolean))].sort();
                let typeOpts = '<option value="all">All</option>';
                types.forEach(t => { typeOpts += '<option value="' + t + '">' + t + '</option>'; });
                html += '<div style="margin-top:1.5rem;"><h3>Validation Results <span class="count-badge" id="valCount">' + r.validation_results.length + '</span></h3><div class="filter-bar"><label>Status:</label><select id="filterStatus" onchange="valFilterStatus=this.value;rerenderVal();"><option value="all">All (' + r.validation_results.length + ')</option><option value="FAIL">FAIL (' + failC + ')</option><option value="PASS">PASS (' + passC + ')</option></select><label>Severity:</label><select id="filterSeverity" onchange="valFilterSeverity=this.value;rerenderVal();"><option value="all">All</option><option value="HIGH">HIGH (' + highC + ')</option><option value="MEDIUM">MEDIUM (' + medC + ')</option><option value="LOW">LOW (' + lowC + ')</option></select><label>Type:</label><select id="filterType" onchange="valFilterType=this.value;rerenderVal();">' + typeOpts + '</select></div><table><thead><tr>' + sh('Rule','rule_code',valSortCol,valSortDir) + sh(__('Description'),'rule_description',valSortCol,valSortDir) + sh(__('Status'),'status',valSortCol,valSortDir) + sh(__('Severity'),'severity',valSortCol,valSortDir) + sh('Type','rule_type',valSortCol,valSortDir) + '<th>Details</th></tr></thead><tbody id="valTbody"></tbody></table></div>';
            }
            if (r.anomaly_results && r.anomaly_results.length > 0) {
                const outC = r.anomaly_results.filter(a=>a.is_outlier===true).length;
                const normC = r.anomaly_results.filter(a=>a.is_outlier===false).length;
                html += '<div style="margin-top:1.5rem;"><h3>Anomaly Detection <span class="count-badge" id="anomCount">' + r.anomaly_results.length + '</span></h3><div class="filter-bar"><label>Outlier:</label><select id="filterOutlier" onchange="anomFilterOutlier=this.value;rerenderAnom();"><option value="all">All (' + r.anomaly_results.length + ')</option><option value="yes">Outliers (' + outC + ')</option><option value="no">Normal (' + normC + ')</option></select></div><table><thead><tr>' + sh('Rate','rate_name',anomSortCol,anomSortDir) + sh(__('Value'),'value',anomSortCol,anomSortDir) + sh(__('Benchmark'),'benchmark',anomSortCol,anomSortDir) + sh(__('Z-Score'),'z_score',anomSortCol,anomSortDir) + sh(__('Outlier'),'is_outlier',anomSortCol,anomSortDir) + '</tr></thead><tbody id="anomTbody"></tbody></table></div>';
            }
            container.innerHTML = html;
            wireTableSort('valTbody', handleValSort);
            wireTableSort('anomTbody', handleAnomSort);
            rerenderVal();
            rerenderAnom();
        }

        function wireTableSort(tbodyId, handler) {
            let tableEl = document.getElementById(tbodyId);
            if (!tableEl) return;
            tableEl = tableEl.closest('table');
            if (!tableEl) return;
            tableEl.querySelectorAll('th.sortable').forEach(th => {
                th.addEventListener('click', function() { handler(this.getAttribute('data-col')); });
            });
        }

        function handleValSort(col) {
            if (valSortCol===col) valSortDir = valSortDir==='asc'?'desc':'asc'; else { valSortCol=col; valSortDir='asc'; }
            rerenderVal();
            let tableEl = document.getElementById('valTbody');
            if (tableEl) { tableEl = tableEl.closest('table'); tableEl.querySelectorAll('th.sortable').forEach(h => { h.classList.remove('sort-asc','sort-desc'); if(h.getAttribute('data-col')===valSortCol) h.classList.add(valSortDir==='asc'?'sort-asc':'sort-desc'); }); }
        }
        function handleAnomSort(col) {
            if (anomSortCol===col) anomSortDir = anomSortDir==='asc'?'desc':'asc'; else { anomSortCol=col; anomSortDir='asc'; }
            rerenderAnom();
            let tableEl = document.getElementById('anomTbody');
            if (tableEl) { tableEl = tableEl.closest('table'); tableEl.querySelectorAll('th.sortable').forEach(h => { h.classList.remove('sort-asc','sort-desc'); if(h.getAttribute('data-col')===anomSortCol) h.classList.add(anomSortDir==='asc'?'sort-asc':'sort-desc'); }); }
        }
        export function rerenderVal() {
            const tbody = document.getElementById('valTbody'); if (!tbody) return;
            const data = sortAndFilterValidation();
            const typeColors = {'LOGIC': '#1565c0', 'CLINICAL': '#6a1b9a', 'BENCHMARK': '#e65100', 'DATA_QUALITY': '#c62828'};
            let html = '';
            data.forEach(v => {
                const sB = v.status==='PASS'?'<span class="badge badge-pass">PASS</span>':'<span class="badge badge-fail">FAIL</span>';
                const sevB = '<span class="badge badge-'+v.severity.toLowerCase()+'">'+v.severity+'</span>';
                const rt = v.rule_type || 'LOGIC';
                const tc = typeColors[rt] || '#666';
                const typeB = '<span class="badge" style="background:'+tc+'22;color:'+tc+';border:1px solid '+tc+'44;">'+rt+'</span>';
                html += '<tr><td>'+v.rule_code+'</td><td>'+v.rule_description+'</td><td>'+sB+'</td><td>'+sevB+'</td><td>'+typeB+'</td><td style="font-size:0.8rem;">'+(v.details||'')+'</td></tr>';
            });
            if (!data.length) html = '<tr><td colspan="6" style="text-align:center;color:#888;">No matching results</td></tr>';
            tbody.innerHTML = html;
            const c = document.getElementById('valCount'); if (c) c.textContent = data.length;
        }
        export function rerenderAnom() {
            const tbody = document.getElementById('anomTbody'); if (!tbody) return;
            const data = sortAndFilterAnomalies();
            let html = '';
            data.forEach(a => {
                const isO = a.is_outlier;
                const rs = isO ? 'style="background:#fff3e0;"':'';
                html += '<tr '+rs+'><td>'+a.rate_name+'</td><td>'+(a.value!==null&&a.value!==undefined?a.value.toFixed(2):'--')+'</td><td>'+(a.benchmark!==null&&a.benchmark!==undefined?a.benchmark.toFixed(2):'--')+'</td><td>'+(a.z_score!==null&&a.z_score!==undefined?a.z_score.toFixed(2):'--')+'</td><td>'+(isO?'<span class="badge badge-fail">YES</span>':'<span class="badge badge-pass">No</span>')+'</td></tr>';
            });
            if (!data.length) html = '<tr><td colspan="5" style="text-align:center;color:#888;">No matching results</td></tr>';
            tbody.innerHTML = html;
            const c = document.getElementById('anomCount'); if (c) c.textContent = data.length;
        }

