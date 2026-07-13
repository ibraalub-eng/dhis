        import { API } from './api.js';
        import { __ } from './i18n.js';
        import { esc, setStatus } from './tree.js';
        import { updateAlertBadge } from './alerts.js';

        // ── Saved Files ────────────────────────────────────────────
        export function refreshSavedFiles() {
            fetch(API() + '/analysis/saved-files').then(r => r.json()).then(files => {
                const container = document.getElementById('savedFilesList');
                const actions = document.getElementById('savedActions');
                document.getElementById('savedCount').textContent = files.length + ' file(s)';
                if (!files.length) {
                    container.innerHTML = '<p style="font-size:0.85rem;color:#888;">No saved files found.</p>';
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
                        '<td>' + esc(f.last_modified ? f.last_modified.replace('T',' ').substring(0,16) : '') + '</td>' +
                        '<td>' + f.records_in_db + '</td>' +
                        '<td><button class="btn btn-sm btn-outline" onclick="analyzeSingleSaved(\'' + esc(f.filename) + '\')">Analyze</button></td>' +
                        '</tr>').join('') +
                    '</tbody></table>';
            }).catch(err => {
                document.getElementById('savedFilesList').innerHTML = '<p style="font-size:0.85rem;color:red;">Error: ' + err.message + '</p>';
            });
        }

        export function toggleAllSaved(master) {
            document.querySelectorAll('.saved-file-cb').forEach(cb => cb.checked = master.checked);
        }

        export function analyzeSelectedSaved() {
            const selected = Array.from(document.querySelectorAll('.saved-file-cb:checked')).map(cb => cb.value);
            if (!selected.length) { alert(__('Select at least one file.')); return; }
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
                const res = await fetch(API() + '/analysis/analyze-saved?' + params, { method: 'POST' });
                if (!res.ok) throw new Error('HTTP ' + res.status + ': ' + await res.text());
                const data = await res.json();
                uploadedData = data;
                displayResults(data);
                setStatus('ok', data.message || __('Analysis complete.'));
                fetch(API() + '/alerts/overview').then(r => r.json()).then(d => {
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

        export function deleteSelectedSaved() {
            const selected = Array.from(document.querySelectorAll('.saved-file-cb:checked')).map(cb => cb.value);
            if (!selected.length) { alert(__('Select at least one file.')); return; }
            if (!confirm('Delete ' + selected.length + ' file(s) from disk? (data in DB will NOT be removed)')) return;
            fetch(API() + '/analysis/saved-files', { method: 'DELETE', headers: {'Content-Type':'application/json'}, body: JSON.stringify({filenames: selected}) })
                .then(r => r.json()).then(res => {
                    setStatus('ok', res.message || __('Deleted.'));
                    refreshSavedFiles();
                }).catch(err => setStatus('err', 'Delete failed: ' + err.message));
        }

        // Load saved files and restore last session on page load
        document.addEventListener('DOMContentLoaded', function() {
            refreshSavedFiles();
            // Show results section if cached reports exist
            fetch(API() + '/reports/').then(r => r.json()).then(reports => {
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
