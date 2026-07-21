# Task 5

Frontend — Root Cause tab PCA feature importance

**Files:**
- Modify: `static/tabs/root-cause.html` (add PCA section)
- Modify: `static/js/settings.js` (update `loadRootCause` to fetch ML data)

**Interfaces:**
- Consumes: `GET /analysis/ml?month=X` → `{"ml_pca": {"n_components": 3, "explained_variance": [0.42, 0.28, 0.08], "cumulative_variance": 0.78, "top_features": {"C-Section Rate": 0.42, "MMR": 0.28}}}`

- [ ] **Step 1: Add PCA section to root-cause.html**

Add after the anomaly patterns section in the diagnostic grid:

```html
                    <div style="background:#fafafa;padding:0.6rem;border-radius:4px;">
                        <h4 style="margin:0 0 0.3rem;font-size:0.82rem;color:#333;">PCA Feature Importance</h4>
                        <div id="pcaFeatures" style="font-size:0.78rem;color:#888;">Not available</div>
                    </div>
```

- [ ] **Step 2: Update `loadRootCause()` in `settings.js`**

After the existing root cause fetch (line 110-130 in settings.js), add:

```javascript
// Fetch ML data for PCA
const mlUrl = '/analysis/ml?month=' + mth;
apiGet(mlUrl).then(mlData => {
    if (mlData && mlData.ml_pca) {
        const pca = mlData.ml_pca;
        const features = pca.top_features || {};
        const entries = Object.entries(features).sort((a, b) => b[1] - a[1]);
        const maxVal = Math.max(...entries.map(e => e[1]), 0.01);
        let html = '<div style="margin-top:0.3rem;">';
        html += '<div style="font-size:0.72rem;color:#666;margin-bottom:0.3rem;">Cumulative variance explained: ' + (pca.cumulative_variance * 100).toFixed(0) + '%</div>';
        entries.forEach(([name, variance]) => {
            const pct = (variance / maxVal * 100).toFixed(0);
            html += '<div style="display:flex;align-items:center;gap:0.3rem;margin:0.15rem 0;">';
            html += '<span style="width:120px;font-size:0.72rem;">' + esc(name) + '</span>';
            html += '<div style="flex:1;height:14px;background:#eee;border-radius:3px;"><div style="height:100%;width:' + pct + '%;background:#1a237e;border-radius:3px;"></div></div>';
            html += '<span style="width:40px;text-align:right;font-size:0.7rem;color:#555;">' + (variance * 100).toFixed(0) + '%</span>';
            html += '</div>';
        });
        html += '</div>';
        document.getElementById('pcaFeatures').innerHTML = html;
    }
}).catch(() => {});
```

- [ ] **Step 3: Manually verify**

Restart server, open Root Cause tab, select hospital/month with data. Verify PCA feature importance bars appear in the diagnostic grid.

- [ ] **Step 4: Commit**

```bash
git add static/tabs/root-cause.html static/js/settings.js
git commit -m "feat: add PCA feature importance to Root Cause tab"
```

---
