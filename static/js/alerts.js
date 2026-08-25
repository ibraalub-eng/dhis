        import { API } from './api.js';
        import { esc } from './tree.js';

        // ── Alerts Tab (overview only; rule-failures table merged here) ──
        export function loadAlerts() {
            fetch(API() + '/alerts/overview')
                .then(r => {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.json();
                })
                .then(data => {
                    renderAlertOverview(data);
                    updateAlertBadge(data);
                })
                .catch(err => {
                    const bar = document.getElementById('alertSummaryBar');
                    if (bar) bar.innerHTML =
                        '<span style="color:red;">Failed: ' + err.message + '</span>';
                });
        }

        export function updateAlertBadge(data) {
            const badge = document.getElementById('alertBadge');
            const total = (data.by_severity.CRITICAL?.count || 0) + (data.by_severity.HIGH?.count || 0);
            if (total > 0) {
                badge.textContent = total > 99 ? '99+' : total;
                badge.style.display = 'inline';
            } else {
                badge.style.display = 'none';
            }
        }

        function renderAlertOverview(data) {
            const sev = data.by_severity;
            const order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
            const colors = { CRITICAL: '#b71c1c', HIGH: '#c62828', MEDIUM: '#e65100', LOW: '#1565c0', OUTLIER: '#7b1fa2', TOTAL: '#333' };

            // Summary bar
            let barHtml = '';
            order.forEach(s => {
                const c = sev[s]?.count || 0;
                barHtml += '<span style="display:inline-flex;align-items:center;gap:0.3rem;background:' + colors[s] + '11;border:1px solid ' + colors[s] + '44;border-radius:4px;padding:0.2rem 0.6rem;font-size:0.75rem;">' +
                    '<span style="font-weight:700;color:' + colors[s] + ';">' + c + '</span>' +
                    '<span style="color:' + colors[s] + '66;">' + s + '</span>' +
                    '</span>';
            });
            barHtml += '<span style="display:inline-flex;align-items:center;gap:0.3rem;background:#7b1fa211;border:1px solid #7b1fa244;border-radius:4px;padding:0.2rem 0.6rem;font-size:0.75rem;">' +
                '<span style="font-weight:700;color:#7b1fa2;">' + (data.outlier_count || 0) + '</span>' +
                '<span style="color:#7b1fa266;">Outliers</span>' +
                '</span>';
            barHtml += '<span style="display:inline-flex;align-items:center;gap:0.3rem;border-radius:4px;padding:0.2rem 0.6rem;font-size:0.75rem;">' +
                '<span style="font-weight:700;color:var(--text-primary);">' + (data.total_alerts || 0) + '</span>' +
                '<span style="color:var(--text-muted);">Total</span>' +
                '</span>';
            document.getElementById('alertSummaryBar').innerHTML = barHtml;

            // Top hospitals — horizontal bars
            const topH = data.top_hospitals || [];
            if (topH.length) {
                const maxCount = Math.max(...topH.map(h => h.alert_count), 1);
                let hhtml = '';
                topH.forEach(h => {
                    const pct = (h.alert_count / maxCount * 100).toFixed(0);
                    const barColor = h.alert_count >= 10 ? '#c62828' : '#e65100';
                    hhtml += '<div style="display:flex;align-items:center;gap:0.5rem;margin:0.3rem 0;">' +
                        '<span style="min-width:100px;font-size:0.78rem;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="' + esc(h.hospital) + '">' + esc(h.hospital) + '</span>' +
                        '<div style="flex:1;height:16px;background:var(--border-default);border-radius:3px;overflow:hidden;">' +
                        '<div style="width:' + pct + '%;height:100%;background:' + barColor + ';border-radius:3px;transition:width 0.3s;"></div>' +
                        '</div>' +
                        '<span style="min-width:2rem;text-align:right;font-weight:600;font-size:0.78rem;color:' + barColor + ';">' + h.alert_count + '</span>' +
                        '</div>';
                });
                document.getElementById('alertTopHospitals').innerHTML = hhtml;
            } else {
                document.getElementById('alertTopHospitals').innerHTML = '<span style="color:var(--text-muted);">No hospitals with alerts.</span>';
            }

            // Recent critical alerts
            const crit = data.recent_critical || [];
            let critHtml = '';
            if (crit.length) {
                critHtml = crit.map(r => '<div style="padding:0.35rem 0.5rem;border-left:3px solid #b71c1c;margin:0.25rem 0;background:#fef2f2;border-radius:3px;">' +
                    '<strong style="font-size:0.78rem;">' + esc(r.rule_code) + '</strong>' +
                    '<span style="color:var(--text-muted);font-size:0.72rem;"> | ' + esc(r.hospital) + ' | ' + esc(r.month) + '</span>' +
                    '<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:0.1rem;">' + esc(r.rule_description) + '</div>' +
                    '</div>').join('');
            } else {
                critHtml = '<span style="color:var(--text-muted);font-size:0.78rem;">No critical alerts</span>';
            }
            document.getElementById('alertCriticalList').innerHTML = critHtml;
        }


