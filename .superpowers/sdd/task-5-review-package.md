# Review Package: Task 5

## Commits

6f1b802 feat: add PCA feature importance to Root Cause tab

## Stats

 static/js/settings.js       | 23 +++++++++++++++++++++++
 static/tabs/root-cause.html |  4 ++++
 2 files changed, 27 insertions(+)

## Diff

\\ndiff --git a/static/js/settings.js b/static/js/settings.js
index 006d2a8..d9a1668 100644
--- a/static/js/settings.js
+++ b/static/js/settings.js
@@ -256,20 +256,43 @@
                         return '<div style="padding:0.35rem 0;border-bottom:1px solid #f0f0f0;">' +
                             '<div style="display:flex;align-items:center;gap:0.4rem;">' +
                                 '<span style="font-size:0.65rem;background:' + typeColor + ';color:#fff;padding:0 5px;border-radius:3px;font-weight:600;">' + typeLabel + '</span>' +
                                 '<span style="font-weight:600;font-size:0.78rem;">' + esc((a.rate_name || '').slice(0, 35)) + '</span>' +
                             '</div>' +
                             '<div style="font-size:0.7rem;color:#666;margin:0.1rem 0 0 0;">|z| = ' + a.avg_z_score + (a.recurrence_count ? ' | Recurring ' + a.recurrence_count + 'x' : '') + '</div>' +
                             '</div>';
                     }).join('');
                 } else { ap.innerHTML = '<div style="padding:0.5rem;text-align:center;color:#888;font-size:0.78rem;">No anomaly patterns found.</div>'; }
 
+                // Fetch ML data for PCA
+                const mlUrl = '/analysis/ml?month=' + mth;
+                apiGet(mlUrl).then(mlData => {
+                    if (mlData && mlData.ml_pca) {
+                        const pca = mlData.ml_pca;
+                        const features = pca.top_features || {};
+                        const entries = Object.entries(features).sort((a, b) => b[1] - a[1]);
+                        const maxVal = Math.max(...entries.map(e => e[1]), 0.01);
+                        let html = '<div style="margin-top:0.3rem;">';
+                        html += '<div style="font-size:0.72rem;color:#666;margin-bottom:0.3rem;">Cumulative variance explained: ' + (pca.cumulative_variance * 100).toFixed(0) + '%</div>';
+                        entries.forEach(([name, variance]) => {
+                            const pct = (variance / maxVal * 100).toFixed(0);
+                            html += '<div style="display:flex;align-items:center;gap:0.3rem;margin:0.15rem 0;">';
+                            html += '<span style="width:120px;font-size:0.72rem;">' + esc(name) + '</span>';
+                            html += '<div style="flex:1;height:14px;background:#eee;border-radius:3px;"><div style="height:100%;width:' + pct + '%;background:#1a237e;border-radius:3px;"></div></div>';
+                            html += '<span style="width:40px;text-align:right;font-size:0.7rem;color:#555;">' + (variance * 100).toFixed(0) + '%</span>';
+                            html += '</div>';
+                        });
+                        html += '</div>';
+                        document.getElementById('pcaFeatures').innerHTML = html;
+                    }
+                }).catch(() => {});
+
             }).catch(e => {
                 document.getElementById('rcLoading').style.display = 'none';
                 document.getElementById('rcContent').style.display = 'block';
                 document.getElementById('rcSummary').innerHTML = '<p style="color:#c62828;">Error: ' + e.message + '</p>';
             });
         }
 
         export function initRootCause() {
             const hsel = document.getElementById('rcHospital');
             const msel = document.getElementById('rcMonth');
diff --git a/static/tabs/root-cause.html b/static/tabs/root-cause.html
index 80b870b..3e96477 100644
--- a/static/tabs/root-cause.html
+++ b/static/tabs/root-cause.html
@@ -43,12 +43,16 @@
                             </div>
                             <div class="card" style="padding:0.6rem 0.8rem;border-top:3px solid #e65100;">
                                 <h4 style="margin:0 0 0.5rem 0;font-size:0.85rem;color:#e65100;">&#128270; Confidence Gaps</h4>
                                 <div id="rcConfidenceGaps" style="font-size:0.8rem;"></div>
                             </div>
                             <div class="card" style="padding:0.6rem 0.8rem;border-top:3px solid #7b1fa2;">
                                 <h4 style="margin:0 0 0.5rem 0;font-size:0.85rem;color:#7b1fa2;">&#128200; Anomaly Patterns</h4>
                                 <div id="rcAnomalyPatterns" style="font-size:0.8rem;"></div>
                             </div>
                         </div>
+                        <div style="background:#fafafa;padding:0.6rem;border-radius:4px;">
+                            <h4 style="margin:0 0 0.3rem;font-size:0.82rem;color:#333;">PCA Feature Importance</h4>
+                            <div id="pcaFeatures" style="font-size:0.78rem;color:#888;">Not available</div>
+                        </div>
                     </div>
 

\\n