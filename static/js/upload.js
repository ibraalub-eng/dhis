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
        let previewFileBytes = null;  // store raw bytes for re-upload
        let pendingOverride = false;   // true if user confirmed overwrite of duplicate
        const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20 MB
        const ALLOWED_EXTS = ['.xlsx', '.xls', '.csv', '.xlsm', '.xlsb'];

        dropZone.addEventListener('click', () => fileInput.click());
        dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
        dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
        dropZone.addEventListener('drop', e => { e.preventDefault(); dropZone.classList.remove('dragover'); if(e.dataTransfer.files.length) { var f = e.dataTransfer.files[0]; var ext3 = '.' + f.name.split('.').pop().toLowerCase(); if (ALLOWED_EXTS.indexOf(ext3) === -1) { setStatus('error', f.name + ': Unsupported file type (' + ext3 + '). Allowed: ' + ALLOWED_EXTS.join(', ')); return; } showPreview(e.dataTransfer.files); } });
        fileInput.addEventListener('change', () => { if(fileInput.files.length) showPreview(fileInput.files); });
        // Show file names on selection
        fileInput.addEventListener('input', () => {
            const list = document.getElementById('fileList');
            if (fileInput.files.length) {
                list.classList.remove('hidden');
                list.innerHTML = Array.from(fileInput.files).map(f => {
                    var ext2 = '.' + f.name.split('.').pop().toLowerCase();
                    var tooLarge = f.size > MAX_FILE_SIZE;
                    var badType = ALLOWED_EXTS.indexOf(ext2) === -1;
                    var sizeStr = (f.size / 1024).toFixed(1) + ' KB';
                    var warns = [];
                    if (badType) warns.push('⚠️ unsupported type (' + ext2 + ')');
                    if (tooLarge) warns.push('⚠️ exceeds 20 MB');
                    var warnStr = warns.length ? ' ' + warns.join(', ') : '';
                    var warnColor = (badType || tooLarge) ? 'var(--accent-red)' : 'var(--text-muted)';
                    return '<div style="display:flex;align-items:center;gap:0.4rem;font-size:0.82rem;">' +
                        '<span style="color:var(--accent-blue);">📄</span><span>' + f.name + '</span>' +
                        '<span style="color:' + warnColor + ';font-size:0.75rem;">(' + sizeStr + warnStr + ')</span></div>';
                }).join('');
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
            // Reject files larger than MAX_FILE_SIZE before uploading
            if (files[0] && files[0].size > MAX_FILE_SIZE) {
                const sizeMB = (files[0].size / (1024 * 1024)).toFixed(1);
                setStatus('error', files[0].name + ': ' + sizeMB + ' MB exceeds the ' + (MAX_FILE_SIZE / (1024 * 1024)) + ' MB limit. Please choose a smaller file.');
                return;
            }
            // Reject disallowed file types
            if (files[0]) {
                var ext = '.' + files[0].name.split('.').pop().toLowerCase();
                if (ALLOWED_EXTS.indexOf(ext) === -1) {
                    setStatus('error', files[0].name + ': Unsupported file type (' + ext + '). Allowed: ' + ALLOWED_EXTS.join(', '));
                    return;
                }
            }
            // --- Duplicate check before preview ---
            setStatus('loading', 'Checking for duplicates...');
            var checkFd = new FormData();
            checkFd.append('file', files[0]);
            var xhr = new XMLHttpRequest();
            xhr.open('POST', API() + '/upload/check-duplicate');
            xhr.onload = function() {
                var result;
                try { result = JSON.parse(xhr.responseText); } catch(e) { result = null; }
                if (result && result.is_duplicate) {
                    showDuplicateModal(result, files);
                } else {
                    doPreviewUpload(files, false);
                }
            };
            xhr.onerror = function() {
                // Network error — proceed anyway with override=false
                doPreviewUpload(files, false);
            };
            xhr.send(checkFd);
        }

        function doPreviewUpload(files, override) {
            pendingOverride = !!override;
            updateStep(2);
            const fd = new FormData();
            fd.append('file', files[0]);
            previewFiles = files;
            const reader = new FileReader();
            reader.onload = function() { previewFileBytes = new Uint8Array(reader.result); };
            reader.readAsArrayBuffer(files[0]);
            const uploadProg = document.getElementById('uploadProgress');
            const uploadFill = document.getElementById('uploadProgressFill');
            const uploadTxt  = document.getElementById('uploadProgressText');
            uploadProg.classList.remove('hidden');
            uploadFill.style.width = '5%';
            uploadFill.style.background = '#3f51b5';
            uploadTxt.textContent = 'Uploading ' + files[0].name + '...';
            setStatus('loading', 'Uploading file: ' + files[0].name + '...');
            const xhr = new XMLHttpRequest();
            xhr.open('POST', API() + '/upload/preview');
            xhr.upload.onprogress = function(e) {
                if (e.lengthComputable) {
                    var pct = Math.round((e.loaded / e.total) * 90);
                    uploadFill.style.width = pct + '%';
                    var loadedMB = (e.loaded / (1024 * 1024)).toFixed(1);
                    var totalMB = (e.total / (1024 * 1024)).toFixed(1);
                    uploadTxt.textContent = 'Uploading ' + files[0].name + '... ' + loadedMB + '/' + totalMB + ' MB (' + pct + '%)';
                }
            };
            xhr.onload = function() {
                uploadFill.style.width = '95%';
                uploadTxt.textContent = 'Processing file...';
                var data;
                try { data = JSON.parse(xhr.responseText); } catch(e) { data = null; }
                if (xhr.status !== 200 || !data) {
                    uploadProg.classList.add('hidden');
                    var errMsg = (data && data.detail) ? data.detail : 'Server error (' + xhr.status + ')';
                    setStatus('err', 'Preview failed: ' + errMsg);
                    return;
                }
                uploadFill.style.width = '100%';
                uploadTxt.textContent = 'Preview loaded!';
                setTimeout(function() { uploadProg.classList.add('hidden'); uploadFill.style.width = '0%'; }, 1500);
                previewFilePath = data.file_path;
                previewFileName = data.filename;
                var hospitals = data.hospitals || [];
                var months = data.months || [];
                var sampleRows = data.sample_rows || [];
                var totalRows = data.total_rows || sampleRows.length;
                var area = document.getElementById('previewArea');
                area.style.display = 'block';
                document.getElementById('previewInfo').textContent = totalRows + ' rows | ' + hospitals.length + ' hospitals | ' + months.length + ' months';
                var cols = [__('Hospital'), 'Month', __('Indicator'), 'Value'];
                var thead = '<tr>' + cols.map(function(c) { return '<th>' + c + '</th>'; }).join('') + '</tr>';
                var tbody = sampleRows.map(function(r) { return '<tr><td>' + esc(r.hospital) + '</td><td>' + esc(r.month) + '</td><td>' + esc(r.indicator) + '</td><td>' + (r.value !== null ? r.value : '<span style="color:red;">MISSING</span>') + '</td></tr>'; }).join('');
                document.querySelector('#previewTable thead').innerHTML = thead;
                document.querySelector('#previewTable tbody').innerHTML = tbody;
                setStatus('ok', 'Preview ready — ' + totalRows + ' records from ' + hospitals.length + ' hospitals across ' + months.length + ' months. Scroll to review, then click Confirm.');
            };
            xhr.onerror = function() {
                uploadProg.classList.add('hidden');
                setStatus('err', 'Preview failed: Network error');
            };
            xhr.send(fd);
        }

        function showDuplicateModal(result, files) {
            // Create a styled duplicate confirmation modal
            var existing = document.getElementById('duplicateModal');
            if (existing) existing.remove();
            var months = (result.existing_months || []).join(', ');
            var hospitals = (result.existing_hospitals || []).join(', ');
            var overlay = document.createElement('div');
            overlay.id = 'duplicateModal';
            overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:10000;display:flex;align-items:center;justify-content:center;';
            overlay.innerHTML = '<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:12px;padding:1.5rem;max-width:480px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.3);">' +
                '<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1rem;">' +
                    '<span style="font-size:1.5rem;">⚠️</span>' +
                    '<h3 style="margin:0;font-size:1.1rem;color:var(--text-primary);">Duplicate File Detected</h3>' +
                '</div>' +
                '<p style="font-size:0.9rem;color:var(--text-secondary);margin-bottom:0.8rem;">' +
                    'File <strong>' + esc(result.existing_file) + '</strong> was already uploaded with <strong>' + result.existing_records + '</strong> records.' +
                '</p>' +
                '<div style="background:var(--bg-surface-hover);border-radius:6px;padding:0.7rem;margin-bottom:1rem;font-size:0.8rem;">' +
                    '<div>📅 Months: ' + esc(months) + '</div>' +
                    '<div>🏥 Hospitals: ' + esc(hospitals) + (result.existing_hospitals.length >= 10 ? ' (+more)' : '') + '</div>' +
                '</div>' +
                '<p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:1rem;">' +
                    'Uploading again will <strong>replace all existing data</strong> from this file. Are you sure?' +
                '</p>' +
                '<div style="display:flex;gap:0.5rem;justify-content:flex-end;">' +
                    '<button id="dupCancel" class="btn btn-outline" style="padding:0.5rem 1rem;">Cancel</button>' +
                    '<button id="dupOverride" class="btn" style="padding:0.5rem 1rem;background:var(--accent-orange);color:white;">Override & Continue</button>' +
                '</div>' +
            '</div>';
            document.body.appendChild(overlay);
            document.getElementById('dupCancel').addEventListener('click', function() {
                overlay.remove();
                cancelPreview();
            });
            document.getElementById('dupOverride').addEventListener('click', function() {
                overlay.remove();
                doPreviewUpload(files, true);
            });
            overlay.addEventListener('click', function(e) {
                if (e.target === overlay) { overlay.remove(); cancelPreview(); }
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
            fill.style.width = '10%';
            txt.textContent = __('Processing file...');
            showLoader('Analyzing data...');
            const _pfd = new FormData();
                // Use stored bytes for reliable re-upload (file object may be stale on ephemeral disk)
                if (previewFileBytes && previewFileName) {
                    const ext = previewFileName.split('.').pop().toLowerCase();
                    const blob = new Blob([previewFileBytes], { type: 'application/octet-stream' });
                    _pfd.append('file', blob, previewFileName);
                } else if (previewFiles && previewFiles[0]) {
                    _pfd.append('file', previewFiles[0]);
                }
                var procUrl = API() + '/analysis/process-preview?filename=' + encodeURIComponent(previewFileName);
                if (pendingOverride) procUrl += '&override=true';
                authFetch(procUrl, { method: 'POST', body: _pfd })
                .then(r => { if (!r.ok) return r.text().then(t => { throw new Error(t); }); return r.json(); })
                .then(resp => {
                // Server returns {task_id, status} — poll until done
                if (!resp.task_id) throw new Error('No task_id returned');
                const taskId = resp.task_id;
                const pollInterval = 2000;
                const maxPolls = 300; // 10 minutes max
                let polls = 0;
                const poll = () => {
                    authFetch(API() + '/tasks/' + taskId)
                        .then(r => r.json())
                        .then(task => {
                            if (task.status === 'done') {
                                const result = task.result;
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
                            } else if (task.status === 'error') {
                                throw new Error(task.error || 'Analysis failed');
                            } else {
                                // Still running — update progress bar
                                polls++;
                                if (polls > maxPolls) throw new Error('Analysis timed out');
                                const pct = task.progress || Math.min(10 + polls * 3, 90);
                                fill.style.width = pct + '%';
                                txt.textContent = __('Processing file...') + ' (' + pct + '%)';
                                setTimeout(poll, pollInterval);
                            }
                        })
                        .catch(err => {
                            hideLoader();
                            fill.style.width = '0%';
                            progress.classList.add('hidden');
                            let detail = err.message;
                            try { const m = detail.match(/"detail"\s*:\s*"([^"]+)"/); if (m) detail = m[1]; } catch {}
                            setStatus('err', 'Import failed: ' + detail);
                        });
                };
                poll();
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
            previewFileBytes = null;
            pendingOverride = false;
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
            const hospOptsTree = result.hospitals.map(h => '<option value="' + h.id + '">' + esc(h.name) + '</option>').join('');
            const monthOptsTree = result.months.map(m => '<option value="' + m + '">' + m + '</option>').join('');

            _setHtml('qualityMonthFilter', '<option value="all">All Months</option>' + monthOptsAll);
            _setHtml('qualityHospitalFilter', '<option value="all">All Hospitals</option>' + result.hospitals.map(h => '<option value="' + esc(h.name) + '">' + esc(h.name) + '</option>').join(''));
            _setHtml('trendHospitalSelect', hospOpts);
            _setHtml('compareMonthSelect', monthOptsAll);
            _setHtml('clinicalHospitalSelect', '<option value="">All Hospitals</option>' + hospOpts);
            _setHtml('clinicalMonthSelect', '<option value="">All Months</option>' + monthOptsAll);
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
            const qLoading = document.getElementById('qualityLoading');
            if (!qLoading) return; // التبويب لم يُحمَّل
            qLoading.classList.remove('hidden');
            try {
                const [data, months] = await Promise.all([
                    apiGet('/reports/'),
                    apiGet('/analysis/months')
                ]);
                document.getElementById('qualityLoading').classList.add('hidden');
                if (data && data.length > 0) {
                    document.getElementById('resultsSection').classList.remove('hidden');
                }
                allQualityReports = data || [];
                // Populate month filter from ALL months (not just report data)
                const qFilter = document.getElementById('qualityMonthFilter');
                qFilter.innerHTML = '<option value="all">All Months</option>' + (months || []).map(m => '<option value="' + m + '">' + m + '</option>').join('');
                const hFilter = document.getElementById('qualityHospitalFilter');
                const hospitals = [...new Set(allQualityReports.map(r => r.hospital))].sort();
                hFilter.innerHTML = '<option value="all">All Hospitals</option>' + hospitals.map(h => '<option value="' + esc(h) + '">' + esc(h) + '</option>').join('');
                if (!skipRestore) _restoreUIState('quality');
                filterQualityReports();
            } catch(e) {
                document.getElementById('qualityLoading').classList.add('hidden');
                document.getElementById('reportsGrid').innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:2rem;">Unable to load cached reports. Upload data first.</p>';
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
            if (!filtered.length) { grid.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:2rem;">No reports match the selected filters.</p>'; return; }
            filtered.forEach(r => {
                const enabled = r.is_enabled !== false;
                if (enabled) {
                    const score = r.data_quality_score;
                    const scoreColor = score >= 80 ? '#2e7d32' : score >= 50 ? '#e65100' : '#c62828';
                    const barColor = score >= 80 ? '#4caf50' : score >= 50 ? '#ff9800' : '#f44336';
                    const issueCount = r.issues ? r.issues.length : 0;
                    const outlierCount = r.outliers ? r.outliers.length : 0;
                    const card = document.createElement('div');
                    card.className = 'report-card ' + (score >= 80 ? 'good' : score >= 50 ? 'medium' : 'poor');
                    card.setAttribute('data-hospital', r.hospital);
                    card.setAttribute('data-month', r.month);
                    card.innerHTML = '<h3>' + r.hospital + '</h3><div class="month">' + r.month + '</div><div class="score" style="color:' + scoreColor + '">' + score + '</div><div class="progress-bar"><div class="progress-bar-fill" style="width:' + score + '%;background:' + barColor + '"></div></div><div style="margin-top:0.7rem;font-size:0.8rem;color:var(--text-secondary);">' + issueCount + ' issues &bull; ' + outlierCount + ' outliers</div>';
                    card.addEventListener('click', function() { showDetail(r.hospital, r.month); });
                    grid.appendChild(card);
                } else {
                    const card = document.createElement('div');
                    card.className = 'report-card disabled';
                    card.setAttribute('data-hospital', r.hospital);
                    card.setAttribute('data-month', r.month);
                    card.innerHTML = '<h3 style="color:var(--text-muted);">' + r.hospital + '</h3><div class="month" style="color:var(--text-secondary);">' + r.month + '</div><div class="score" style="color:var(--text-muted);">-</div><div class="progress-bar" style="background:var(--border-default);"><div class="progress-bar-fill" style="width:0%;background:var(--text-muted);"></div></div><div style="margin-top:0.7rem;font-size:0.8rem;color:var(--text-secondary);">Analysis disabled</div>';
                    card.style.opacity = '0.6';
                    card.style.cursor = 'default';
                    grid.appendChild(card);
                }
            });
        }

        let currentValidation = [];
        let valSortCol = 'rule_code', valSortDir = 'asc';
        window.valFilterStatus = 'all'; window.valFilterSeverity = 'all'; window.valFilterType = 'all';
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
                body.innerHTML = '<p style="color:var(--accent-red);">Error: ' + e.message + '</p>';
            }
        }



        function sortAndFilterValidation() {
            let data = [...currentValidation];
            if (window.valFilterStatus !== 'all') data = data.filter(v => v.status === window.valFilterStatus);
            if (window.valFilterSeverity !== 'all') data = data.filter(v => v.severity === window.valFilterSeverity);
            if (window.valFilterType !== 'all') data = data.filter(v => v.rule_type === window.valFilterType);
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

        // ── QR sub-tab switching ──
        window.switchQrTab = function(tab) {
            document.querySelectorAll('.qr-subtab').forEach(function(b) {
                b.style.color = 'var(--text-muted)';
                b.style.borderBottom = 'none';
                b.style.fontWeight = '600';
            });
            document.querySelectorAll('.qr-tab-content').forEach(function(el) {
                el.style.display = 'none';
            });
            var active = document.querySelector('.qr-subtab[onclick*="' + tab + '"]');
            if (active) {
                active.style.color = 'var(--accent-blue)';
                active.style.borderBottom = '2px solid var(--accent-blue)';
            }
            var panel = document.getElementById('qrTab-' + tab);
            if (panel) panel.style.display = 'block';
        };

        // ── Load Completeness component breakdown for QR detail ──
        window.loadQrCompleteness = async function(hid, month) {
            var el = document.getElementById('qrCompletenessContent');
            if (!el) return;
            try {
                var diag = await apiGet('/dashboard/component-diagnostics?hospital_id=' + hid + '&month_from=' + month + '&month_to=' + month);
                var components = (diag && diag.components) || [];
                if (!components.length) {
                    el.innerHTML = '<p style="color:var(--text-muted);">No completeness data for this month.</p>';
                    return;
                }
                var html = '';
                components.forEach(function(c) {
                    var col = c.avg >= 80 ? 'var(--accent-green)' : c.avg >= 60 ? 'var(--accent-orange)' : 'var(--accent-red)';
                    var dirIcon = c.direction === 'improving' ? '\u2191' : c.direction === 'declining' ? '\u2193' : '\u2192';
                    var gapColor = c.gap > 20 ? 'var(--accent-red)' : c.gap > 5 ? 'var(--accent-orange)' : 'var(--accent-green)';
                    var statusLabel = c.gap <= 0 ? '<span style="color:var(--accent-green);font-weight:600;">\u2705 On Target</span>' :
                        c.gap <= 5 ? '<span style="color:var(--accent-orange);font-weight:600;">\u26a0\ufe0f ' + c.gap + '% gap</span>' :
                        '<span style="color:var(--accent-red);font-weight:600;">\u274c ' + c.gap + '% gap</span>';

                    // Component card
                    html += '<div style="border:1px solid var(--border-default);border-radius:8px;margin-bottom:0.6rem;overflow:hidden;">';
                    // Header
                    html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:0.5rem 0.7rem;background:var(--bg-elevated);cursor:pointer;" onclick="this.parentElement.querySelector(\'._qrDiagBody\').classList.toggle(\'hidden\')">';
                    html += '<div style="display:flex;align-items:center;gap:0.4rem;">';
                    html += '<span style="font-weight:600;font-size:0.82rem;">' + esc(c.name) + '</span>';
                    html += '<span style="font-size:0.7rem;color:' + (c.direction === 'improving' ? 'var(--accent-green)' : c.direction === 'declining' ? 'var(--accent-red)' : 'var(--text-muted)') + ';">' + dirIcon + '</span>';
                    html += '</div>';
                    html += '<div style="display:flex;align-items:center;gap:0.6rem;">';
                    html += '<span style="font-weight:700;color:' + col + ';font-size:0.9rem;">' + c.avg + '%</span>';
                    html += '<span style="font-size:0.65rem;color:var(--text-muted);">/ ' + c.target + '%</span>';
                    html += statusLabel;
                    html += '<span style="font-size:0.65rem;color:var(--text-muted);">\u25bc</span>';
                    html += '</div></div>';
                    // Progress bar
                    html += '<div style="padding:0 0.7rem;">';
                    html += '<div style="height:4px;background:var(--border-default);border-radius:2px;margin:0.25rem 0;">';
                    html += '<div style="width:' + Math.min(c.avg, 100) + '%;height:4px;background:' + col + ';border-radius:2px;"></div>';
                    html += '</div></div>';
                    // Diagnosis body
                    html += '<div class="_qrDiagBody" style="padding:0.4rem 0.7rem 0.7rem;border-top:1px solid var(--border-default);">';
                    // Causes
                    if (c.causes && c.causes.length) {
                        c.causes.forEach(function(cause) {
                            var sevColor = cause.severity === 'critical' ? 'var(--accent-red)' : cause.severity === 'warning' ? 'var(--accent-orange)' : 'var(--accent-green)';
                            var sevBg = cause.severity === 'critical' ? 'rgba(198,40,40,0.08)' : cause.severity === 'warning' ? 'rgba(230,81,0,0.08)' : 'rgba(46,125,50,0.08)';
                            var sevIcon = cause.severity === 'critical' ? '\u274c' : cause.severity === 'warning' ? '\u26a0\ufe0f' : cause.severity === 'ok' ? '\u2705' : '\u2139\ufe0f';
                            html += '<div style="display:flex;align-items:flex-start;gap:5px;padding:0.3rem 0.4rem;border-radius:5px;margin-bottom:0.25rem;background:' + sevBg + ';">';
                            html += '<span style="font-size:0.7rem;flex-shrink:0;margin-top:1px;">' + sevIcon + '</span>';
                            html += '<div style="flex:1;">';
                            html += '<div style="font-size:0.72rem;font-weight:600;color:' + sevColor + ';">' + esc(cause.cause) + '</div>';
                            html += '<div style="font-size:0.68rem;color:var(--text-secondary);margin-top:1px;">' + esc(cause.detail) + '</div>';
                            html += '</div>';
                            if (cause.impact_pct > 0) {
                                html += '<div style="text-align:right;flex-shrink:0;"><div style="font-size:0.6rem;color:var(--text-muted);">Impact</div><div style="font-size:0.72rem;font-weight:700;color:' + sevColor + ';">-' + cause.impact_pct + '%</div></div>';
                            }
                            html += '</div>';
                            // Affected hospitals
                            var affected = cause.affected_hospitals || [];
                            if (affected.length > 0 && cause.severity !== 'ok') {
                                html += '<div style="margin:0.2rem 0 0.3rem 0.35rem;padding:0.3rem 0.4rem;background:var(--bg-surface);border-radius:5px;border:1px solid var(--border-default);">';
                                html += '<div style="font-size:0.65rem;font-weight:600;color:var(--text-secondary);margin-bottom:0.25rem;">\ud83d\udcca Affected Hospitals (' + affected.length + ')</div>';
                                html += '<div style="display:flex;flex-direction:column;gap:0.25rem;max-height:160px;overflow-y:auto;">';
                                affected.forEach(function(h, hIdx) {
                                    var hCol = h.avg_value >= 80 ? 'var(--accent-green)' : h.avg_value >= 50 ? 'var(--accent-orange)' : 'var(--accent-red)';
                                    html += '<div style="display:flex;align-items:center;gap:0.4rem;font-size:0.65rem;">';
                                    html += '<div style="width:16px;height:16px;border-radius:50%;background:' + hCol + ';color:#fff;font-size:0.55rem;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0;">' + (hIdx + 1) + '</div>';
                                    html += '<div style="flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="' + esc(h.hospital_name) + '">' + esc(h.hospital_name) + '</div>';
                                    html += '<span style="font-weight:700;color:' + hCol + ';flex-shrink:0;">' + h.avg_value + '%</span>';
                                    if (h.problem_months && h.problem_months.length) {
                                        html += '<span style="color:var(--text-muted);flex-shrink:0;">(' + h.problem_months.join(', ') + ')</span>';
                                    }
                                    html += '</div>';
                                });
                                html += '</div></div>';
                            }
                        });
                    }
                    // Monthly detail
                    if (c.monthly && c.monthly.length) {
                        html += '<div style="font-size:0.7rem;font-weight:600;color:var(--text-secondary);margin:0.4rem 0 0.2rem;">Month-by-Month</div>';
                        html += '<table style="width:100%;border-collapse:collapse;font-size:0.65rem;">';
                        html += '<thead><tr style="background:var(--bg-surface);"><th style="text-align:left;padding:0.2rem 0.3rem;">Month</th><th style="text-align:right;padding:0.2rem 0.3rem;">Value</th><th style="text-align:right;padding:0.2rem 0.3rem;">vs Target</th><th style="text-align:left;padding:0.2rem 0.3rem;">Status</th></tr></thead><tbody>';
                        c.monthly.forEach(function(m) {
                            var diff = m.value - c.target;
                            var mCol = m.value >= c.target ? 'var(--accent-green)' : m.value >= c.target - 10 ? 'var(--accent-orange)' : 'var(--accent-red)';
                            var mStatus = m.value >= c.target ? '\u2705 OK' : m.value >= c.target - 10 ? '\u26a0\ufe0f Warning' : '\u274c Critical';
                            html += '<tr style="border-bottom:1px solid var(--border-default);">';
                            html += '<td style="padding:0.2rem 0.3rem;font-weight:500;">' + m.month + '</td>';
                            html += '<td style="text-align:right;padding:0.2rem 0.3rem;font-weight:700;color:' + mCol + ';">' + m.value + '%</td>';
                            html += '<td style="text-align:right;padding:0.2rem 0.3rem;color:' + mCol + ';">' + (diff >= 0 ? '+' : '') + diff.toFixed(1) + '%</td>';
                            html += '<td style="padding:0.2rem 0.3rem;">' + mStatus + '</td>';
                            html += '</tr>';
                        });
                        html += '</tbody></table>';
                    }
                    html += '</div>'; // _qrDiagBody
                    html += '</div>'; // card
                });
                el.innerHTML = html;
            } catch(e) {
                el.innerHTML = '<p style="color:var(--accent-red);">Error loading completeness: ' + e.message + '</p>';
            }
        };

        function renderDetail(container, r) {
            const score = r.data_quality_score;
            const scoreClass = score >= 80 ? 'score-good' : score >= 50 ? 'score-medium' : 'score-poor';
            let html = '<div style="display:flex;gap:0.5rem;justify-content:flex-end;margin-bottom:0.8rem;">';

            html += '</div>';
            html += '<div class="grid-2"><div style="text-align:center;"><div class="score-circle ' + scoreClass + '" style="margin:0 auto;">' + score + '</div><p style="font-size:0.85rem;color:var(--text-muted);margin-top:0.5rem;">Data Quality Score</p><div class="grid-4" style="margin-top:1rem;"><div class="stat-box"><div class="value">' + (r.rule_compliance!==null?r.rule_compliance+'%':'--') + '</div><div class="label">Rule Compliance</div></div><div class="stat-box"><div class="value">' + (r.completeness!==null?r.completeness+'%':'--') + '</div><div class="label">Completeness</div></div><div class="stat-box"><div class="value">' + (r.consistency!==null?r.consistency+'%':'--') + '</div><div class="label">Consistency</div></div><div class="stat-box"><div class="value">' + (r.outlier_penalty!==null?r.outlier_penalty+'%':'--') + '</div><div class="label">Outlier Penalty</div></div></div></div><div><h3 style="font-size:0.95rem;color:var(--text-primary);margin-bottom:0.5rem;">Issues (' + (r.issues?r.issues.length:0) + ')</h3>';
            if (r.issues && r.issues.length > 0) { html += '<ul class="issue-list">'; r.issues.forEach(i => { html += '<li>' + i + '</li>'; }); html += '</ul>'; } else { html += '<p style="color:var(--accent-green);font-size:0.85rem;">No issues found</p>'; }
            html += '</div></div>';

            if (r.confidence) {
                const c = r.confidence;
                const confClass = c.overall_confidence >= 80 ? 'score-good' : c.overall_confidence >= 50 ? 'score-medium' : 'score-poor';
                const levelColors = {'HIGH':'#2e7d32','MEDIUM':'#e65100','LOW':'#c62828','CRITICAL':'#b71c1c'};
                const levelBg = {'HIGH':'var(--severity-success-bg)','MEDIUM':'var(--severity-warning-bg)','LOW':'var(--severity-critical-bg)','CRITICAL':'var(--severity-critical-bg)'};
                html += '<div style="margin-top:1.5rem;border-top:2px solid #e8eaf6;padding-top:1rem;"><h3 style="color:var(--text-primary);">Confidence Score per Indicator</h3>';
                html += '<div class="grid-2" style="align-items:center;">';
                html += '<div style="text-align:center;"><div class="score-circle ' + confClass + '" style="margin:0 auto;width:90px;height:90px;font-size:1.6rem;">' + c.overall_confidence + '%</div><p style="font-size:0.85rem;color:var(--text-muted);margin-top:0.5rem;">Overall Confidence</p><span class="badge" style="background:' + (levelBg[c.level]||'#eee') + ';color:' + (levelColors[c.level]||'#888') + ';font-size:0.8rem;padding:0.3rem 0.8rem;">' + c.level + '</span></div>';
                html += '<div>';
                if (c.by_group) {
                    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:0.4rem;font-size:0.8rem;">';
                    for (const [grp, val] of Object.entries(c.by_group)) {
                        const gc = val >= 80 ? '#2e7d32' : val >= 50 ? '#e65100' : '#c62828';
                        html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:0.2rem 0.5rem;background:var(--bg-surface-hover);border-radius:4px;"><span>' + grp + '</span><span style="font-weight:700;color:' + gc + ';">' + val + '%</span></div>';
                    }
                    html += '</div>';
                }
                html += '</div></div>';
                if (c.by_level || c.priority_verify) {
                    var bl = c.by_level || {};
                    if (!bl.HIGH && c.priority_verify) bl.HIGH = (c.priority_verify.length > 0 ? 0 : 0);
                    html += '<div style="margin-top:0.6rem;display:flex;gap:0.5rem;font-size:0.8rem;flex-wrap:wrap;">';
                    html += '<span class="badge badge-all" style="cursor:pointer;background:var(--accent-blue);color:white;font-weight:700;" onclick="filterPriorityTable(\'ALL\')">ALL</span>'
                    var levels = ['HIGH','MEDIUM','LOW','CRITICAL'];
                    levels.forEach(function(lv) {
                        var cnt = bl[lv] || 0;
                        html += '<span class="badge badge-' + lv.toLowerCase() + '" style="cursor:pointer;" onclick="filterPriorityTable(\'' + lv + '\')">' + lv + ': ' + cnt + '</span>';
                    });
                    html += '</div>';
                }
                if (c.priority_verify && c.priority_verify.length > 0) {
                    html += '<div style="margin-top:0.8rem;"><h4 style="font-size:0.85rem;color:var(--accent-red);margin-bottom:0.4rem;">Priority Verification (' + c.priority_verify.length + ')</h4>';
                    html += '<table id="priorityTable" style="font-size:0.8rem;"><thead><tr><th>Indicator</th><th>Value</th><th>Confidence</th><th>Level</th><th>Recommendations</th></tr></thead><tbody>';
                    c.priority_verify.forEach(p => {
                        const pc = p.confidence >= 80 ? '#2e7d32' : p.confidence >= 50 ? '#e65100' : '#c62828';
                        const recs = (p.recommendations || []).join('; ');
                        html += '<tr data-level="' + p.level + '"><td>' + p.indicator_name + '</td><td>' + (p.value !== null && p.value !== undefined ? p.value : '<span style="color:var(--accent-red);">MISSING</span>') + '</td><td style="font-weight:700;color:' + pc + ';">' + p.confidence + '%</td><td><span class="badge badge-' + p.level.toLowerCase() + '">' + p.level + '</span></td><td style="font-size:0.75rem;color:var(--text-secondary);">' + recs + '</td></tr>';
                    });
                    html += '</tbody></table></div>';
                }
                if (c.summary) {
                    html += '<p style="margin-top:0.6rem;font-size:0.8rem;color:var(--text-secondary);font-style:italic;background:var(--bg-surface-hover);padding:0.5rem;border-radius:4px;">' + c.summary + '</p>';
                }
                html += '</div>';
            }

            // ── Sub-tabs: Validation | Anomaly | Completeness ──
            const valCount = (r.validation_results || []).length;
            const anomCount = (r.anomaly_results || []).length;
            const hasVal = valCount > 0;
            const hasAnom = anomCount > 0;

            html += '<div style="margin-top:1.2rem;border-top:2px solid var(--border-default);padding-top:0.8rem;">';
            html += '<div id="qrSubtabs" style="display:flex;gap:0;border-bottom:2px solid var(--border-default);margin-bottom:0.8rem;">';
            if (hasVal) {
                html += '<button class="qr-subtab active" onclick="switchQrTab('validation')" style="padding:0.4rem 1rem;border:none;background:none;font-weight:600;color:var(--accent-blue);border-bottom:2px solid var(--accent-blue);margin-bottom:-2px;cursor:pointer;font-size:0.82rem;">Validation Results <span class="count-badge">' + valCount + '</span></button>';
            }
            if (hasAnom) {
                html += '<button class="qr-subtab" onclick="switchQrTab('anomaly')" style="padding:0.4rem 1rem;border:none;background:none;font-weight:600;color:var(--text-muted);cursor:pointer;font-size:0.82rem;">Anomaly Detection <span class="count-badge">' + anomCount + '</span></button>';
            }
            html += '<button class="qr-subtab" onclick="switchQrTab('completeness')" style="padding:0.4rem 1rem;border:none;background:none;font-weight:600;color:var(--text-muted);cursor:pointer;font-size:0.82rem;">Completeness</button>';
            html += '</div>';

            // Validation tab content
            html += '<div id="qrTab-validation" class="qr-tab-content">';
            if (hasVal) {
                const failC = r.validation_results.filter(v=>v.status==='FAIL').length;
                const passC = r.validation_results.filter(v=>v.status==='PASS').length;
                const highC = r.validation_results.filter(v=>v.severity==='HIGH').length;
                const medC = r.validation_results.filter(v=>v.severity==='MEDIUM').length;
                const lowC = r.validation_results.filter(v=>v.severity==='LOW').length;
                const types = [...new Set(r.validation_results.map(v=>v.rule_type).filter(Boolean))].sort();
                let typeOpts = '<option value="all">All</option>';
                types.forEach(t => { typeOpts += '<option value="' + t + '">' + t + '</option>'; });
                html += '<div class="filter-bar"><label>Status:</label><select id="filterStatus" onchange="valFilterStatus=this.value;rerenderVal();"><option value="all">All (' + valCount + ')</option><option value="FAIL">FAIL (' + failC + ')</option><option value="PASS">PASS (' + passC + ')</option></select><label>Severity:</label><select id="filterSeverity" onchange="valFilterSeverity=this.value;rerenderVal();"><option value="all">All</option><option value="HIGH">HIGH (' + highC + ')</option><option value="MEDIUM">MEDIUM (' + medC + ')</option><option value="LOW">LOW (' + lowC + ')</option></select><label>Type:</label><select id="filterType" onchange="valFilterType=this.value;rerenderVal();">' + typeOpts + '</select></div><table><thead><tr>' + sh('Rule','rule_code',valSortCol,valSortDir) + sh(__('Description'),'rule_description',valSortCol,valSortDir) + sh(__('Status'),'status',valSortCol,valSortDir) + sh(__('Severity'),'severity',valSortCol,valSortDir) + sh('Type','rule_type',valSortCol,valSortDir) + '<th>Details</th></tr></thead><tbody id="valTbody"></tbody></table>';
            } else {
                html += '<p style="color:var(--text-muted);padding:1rem;">No validation results available.</p>';
            }
            html += '</div>';

            // Anomaly tab content
            html += '<div id="qrTab-anomaly" class="qr-tab-content" style="display:none;">';
            if (hasAnom) {
                const outC = r.anomaly_results.filter(a=>a.is_outlier===true).length;
                const normC = r.anomaly_results.filter(a=>a.is_outlier===false).length;
                html += '<div class="filter-bar"><label>Outlier:</label><select id="filterOutlier" onchange="anomFilterOutlier=this.value;rerenderAnom();"><option value="all">All (' + anomCount + ')</option><option value="yes">Outliers (' + outC + ')</option><option value="no">Normal (' + normC + ')</option></select></div><table><thead><tr>' + sh('Rate','rate_name',anomSortCol,anomSortDir) + sh(__('Value'),'value',anomSortCol,anomSortDir) + sh(__('Benchmark'),'benchmark',anomSortCol,anomSortDir) + sh(__('Z-Score'),'z_score',anomSortCol,anomSortDir) + sh(__('Outlier'),'is_outlier',anomSortCol,anomSortDir) + '</tr></thead><tbody id="anomTbody"></tbody></table>';
            } else {
                html += '<p style="color:var(--text-muted);padding:1rem;">No anomaly results available.</p>';
            }
            html += '</div>';

            // Completeness tab content (loaded async)
            html += '<div id="qrTab-completeness" class="qr-tab-content" style="display:none;">';
            html += '<div id="qrCompletenessContent" style="padding:1rem;text-align:center;color:var(--text-muted);"><span class="spinner"></span> Loading completeness data...</div>';
            html += '</div>';

            html += '</div>'; // end sub-tabs wrapper

            container.innerHTML = html;
            wireTableSort('valTbody', handleValSort);
            wireTableSort('anomTbody', handleAnomSort);
            rerenderVal();
            rerenderAnom();

            // Load Completeness data async
            if (currentHospitalId && currentMonth) {
                loadQrCompleteness(currentHospitalId, currentMonth);
            } else {
                document.getElementById('qrCompletenessContent').innerHTML = '<p style="color:var(--text-muted);">Select a hospital and month to view completeness data.</p>';
            }
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
            if (!data.length) html = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);">No matching results</td></tr>';
            tbody.innerHTML = html;
            const c = document.getElementById('valCount'); if (c) c.textContent = data.length;
        }
        export function rerenderAnom() {
            const tbody = document.getElementById('anomTbody'); if (!tbody) return;
            const data = sortAndFilterAnomalies();
            let html = '';
            data.forEach(a => {
                const isO = a.is_outlier;
                const rs = isO ? 'style="background:var(--severity-warning-bg);"':'';
                html += '<tr '+rs+'><td>'+a.rate_name+'</td><td>'+(a.value!==null&&a.value!==undefined?a.value.toFixed(2):'--')+'</td><td>'+(a.benchmark!==null&&a.benchmark!==undefined?a.benchmark.toFixed(2):'--')+'</td><td>'+(a.z_score!==null&&a.z_score!==undefined?a.z_score.toFixed(2):'--')+'</td><td>'+(isO?'<span class="badge badge-fail">YES</span>':'<span class="badge badge-pass">No</span>')+'</td></tr>';
            });
            if (!data.length) html = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);">No matching results</td></tr>';
            tbody.innerHTML = html;
            const c = document.getElementById('anomCount'); if (c) c.textContent = data.length;
        }

