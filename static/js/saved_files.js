        import { API } from './api.js';
        import { __ } from './i18n.js';
        import { esc, setStatus } from './tree.js';
        import { updateAlertBadge } from './alerts.js';
import { toastSuccess, toastError, toastWarning } from './toast.js';
import { confirmDestructive } from './confirm-modal.js';

        // ── Saved Files ────────────────────────────────────────────
        export function refreshSavedFiles() {
            var tb=document.getElementById("savedFilesTbody");if(tb)tb.innerHTML="<tr><td colspan=\"5\" style=\"text-align:center;padding:1.5rem;color:var(--text-muted);\"><span class=\"spinner\"></span> Loading saved files...</td></tr>";
            // Skip if user lacks data.upload permission (doctor/viewer roles)
            try {
                var userInfo = JSON.parse(localStorage.getItem('user_info') || sessionStorage.getItem('user_info') || '{}');
                var perms = userInfo.permissions || [];
                if (!perms.includes('*.*') && !perms.includes('data.upload')) {
                    // Hide the saved files section for non-upload users
                    var card = document.querySelector('[data-requires="data.upload"]');
                    if (card) card.style.display = 'none';
                    return;
                }
            } catch(e) {}
            authFetch(API() + '/analysis/saved-files').then(r => {
                if (!r.ok) { throw new Error('HTTP ' + r.status); }
                return r.json();
            }).then(files => {
                const container = document.getElementById('savedFilesList');
                const actions = document.getElementById('savedActions');
                const countEl = document.getElementById('savedCount');
                // Upload tab content may not be loaded yet (it's loaded lazily
                // on first visit), so bail out gracefully.
                if (!container || !actions || !countEl) return;
                countEl.textContent = files.length + ' file(s)';
                if (!files.length) {
                    container.innerHTML = '<p style="font-size:0.85rem;color:var(--text-muted);">No saved files found.</p>';
                    actions.style.display = 'none';
                    return;
                }
                actions.style.display = 'block';
                container.innerHTML = '<table style="font-size:0.85rem;"><thead><tr>' +
                    '<th style="width:30px;"><input type="checkbox" id="savedSelectAll" onchange="toggleAllSaved(this)"></th>' +
                    '<th>Filename</th><th>Size (KB)</th><th>Last Modified</th><th>Records</th><th></th>' +
                    '</tr></thead><tbody>' +
                    files.map(f => '<tr>' +
                        '<td><input type="checkbox" class="saved-file-cb" value="' + esc(f.filename) + '"></td>' +
                        '<td><code>' + esc(f.filename) + '</code></td>' +
                        '<td>' + f.size_kb + '</td>' +
                        '<td>' + esc(f.uploaded_at ? f.uploaded_at.replace('T',' ').substring(0,16) : '') + '</td>' +
                        '<td>' + f.records_in_db + '</td>' +
                        '<td style="white-space:nowrap;">' +
                            '<button class="btn btn-sm btn-outline" onclick="analyzeSingleSaved(\'' + esc(f.filename) + '\')">' + __('Analyze') + '</button>&nbsp;' +
                            '<button class="btn btn-sm btn-outline" onclick="updateSingleSaved(\'' + esc(f.filename) + '\')">' + __('Update') + '</button>&nbsp;' +
                            '<button class="btn btn-sm btn-outline" onclick="deleteSingleSaved(\'' + esc(f.filename) + '\')" style="color:var(--accent-red);">' + __('Delete') + '</button>' +
                        '</td>' +
                        '</tr>').join('') +
                    '</tbody></table>';
            }).catch(err => {
                const cl = document.getElementById('savedFilesList');
                if (!cl) return;
                cl.innerHTML = '<p style="font-size:0.85rem;color:red;">Error: ' + err.message + '</p>';
            });
        }

        export function toggleAllSaved(master) {
            document.querySelectorAll('.saved-file-cb').forEach(cb => cb.checked = master.checked);
        }

        export function analyzeSelectedSaved() {
            const selected = Array.from(document.querySelectorAll('.saved-file-cb:checked')).map(cb => cb.value);
            if (!selected.length) { toastWarning(__('Select at least one file.')); return; }
            runAnalyzeSaved(selected);
        }

        export function analyzeSingleSaved(fname) {
            runAnalyzeSaved([fname]);
        }

        async function runAnalyzeSaved(filenames) {
            const btn = document.getElementById('analyzeSavedBtn');
            const originalText = btn.textContent;
            btn.textContent = '...';
            btn.disabled = true;
            showLoader('Analyzing ' + filenames.length + ' file(s)...');
            try {
                const params = filenames.map(f => 'filenames=' + encodeURIComponent(f)).join('&');
                const res = await authFetch(API() + '/analysis/analyze-saved?' + params, { method: 'POST' });
                if (!res.ok) throw new Error('HTTP ' + res.status + ': ' + await res.text());
                const data = await res.json();
                uploadedData = data;
                displayResults(data);
                setStatus('ok', data.message || __('Analysis complete.'));
                authFetch(API() + '/alerts/overview').then(r => r.json()).then(d => {
                    updateAlertBadge(d);
                }).catch(() => {});
                refreshSavedFiles();
            } catch (err) {
                setStatus('err', 'Analysis failed: ' + err.message);
            } finally {
                hideLoader();
                btn.textContent = originalText;
                btn.disabled = false;
            }
        }

        export async function deleteSelectedSaved() {
            const selected = Array.from(document.querySelectorAll('.saved-file-cb:checked')).map(cb => cb.value);
            if (!selected.length) { toastWarning(__('Select at least one file.')); return; }
            if (!await confirmDestructive({ title: 'Delete Files', message: 'Delete ' + selected.length + ' file(s) from disk?', details: 'Data in DB will NOT be removed.', okLabel: 'Delete' })) return;
            authFetch(API() + '/analysis/saved-files', { method: 'DELETE', headers: {'Content-Type':'application/json'}, body: JSON.stringify({filenames: selected}) })
                .then(r => r.json()).then(res => {
                    setStatus('ok', res.message || __('Deleted.'));
                    refreshSavedFiles();
                }).catch(err => setStatus('err', 'Delete failed: ' + err.message));
        }

        export async function deleteSingleSaved(fname) {
            if (!fname) return;
            if (!await confirmDestructive({ title: __('Delete File'), message: __('Delete') + ' <strong>' + esc(fname) + '</strong>?', details: __('This will permanently delete the file and its imported records from the database.'), okLabel: __('Delete') })) return;
            setStatus('loading', __('Deleting') + ' ' + fname + '...');
            authFetch(API() + '/analysis/saved-files', { method: 'DELETE', headers: {'Content-Type':'application/json'}, body: JSON.stringify({filenames: [fname]}) })
                .then(r => {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.json();
                }).then(res => {
                    setStatus('ok', res.message || __('Deleted.'));
                    refreshSavedFiles();
                }).catch(err => setStatus('err', __('Delete failed:') + ' ' + err.message));
        }

        export async function updateSingleSaved(fname) {
            if (!fname) return;
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.xlsx,.xls,.csv,.xlsm,.xlsb';
            input.style.display = 'none';
            input.onchange = function() {
                if (!input.files || !input.files[0]) return;
                const file = input.files[0];
                const ext = '.' + file.name.split('.').pop().toLowerCase();
                if (['.xlsx','.xls','.csv','.xlsm','.xlsb'].indexOf(ext) === -1) {
                    toastError(file.name + ': ' + __('Unsupported file type') + ' (' + ext + '). Allowed: .xlsx, .xls, .csv');
                    return;
                }
                if (file.size > 20 * 1024 * 1024) {
                    const mb = (file.size / (1024 * 1024)).toFixed(1);
                    toastError(file.name + ': ' + mb + ' MB ' + __('exceeds the') + ' 20 MB ' + __('limit'));
                    return;
                }
                runUpdateSaved(fname, file);
            };
            document.body.appendChild(input);
            input.click();
        }

        async function runUpdateSaved(fname, file) {
            setStatus('loading', 'Updating ' + fname + '...');
            const fd = new FormData();
            fd.append('file', file);
            try {
                const res = await authFetch(API() + '/analysis/update-saved?filename=' + encodeURIComponent(fname), { method: 'POST', body: fd });
                if (!res.ok) {
                    let detail = '';
                    try { detail = (await res.json()).detail || ''; } catch(e) {}
                    throw new Error('HTTP ' + res.status + (detail ? ': ' + detail : ''));
                }
                const data = await res.json();
                setStatus('ok', data.message || __('Updated.'));
                await refreshSavedFiles();
            } catch (err) {
                setStatus('err', 'Update failed: ' + err.message);
            }
        }

        // Load saved files and restore last session on page load
        document.addEventListener('DOMContentLoaded', function() {
            refreshSavedFiles();
            // Show results section if cached reports exist
            authFetch(API() + '/reports/').then(r => r.json()).then(reports => {
                if (reports && reports.length > 0) {
                    document.getElementById('resultsSection').classList.remove('hidden');
                }
            }).catch(() => {});
            // Check if we should restore a non-dashboard tab
            const savedTab = localStorage.getItem('lastTab');
            if (savedTab && savedTab !== 'dashboard') {
                switchTab(savedTab);
            } else {
                switchTab('dashboard');
            }
        });
