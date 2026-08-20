// advanced.js — heavy analytical sections (clusters, correlations, patterns, forecasts).
import { smartState, apiSmartGet, setSmartLoader, showSmartSectionError,
         showSmartSectionEmpty, _smartEscapeHtml, _t, _fmtNum, smartTranslateFeature } from './core.js';
import { renderPlot, makeScatter, makeHeatmap, makeBarChart, makeLineChart } from './charts.js';

export function initAdvancedTabs() {
  const loaders = {
    'clusters-tab': loadClustersTab,
    'corr-tab': loadCorrelationsTab,
    'patterns-tab': loadPatternsTab,
    'fi-tab': loadFeatureImportanceTab,
  };
  document.querySelectorAll('.smart-tab-btn[data-smart-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.smart-tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll('[id$="-tab"]').forEach(t => t.style.display = 'none');
      const tab = document.getElementById(btn.dataset.smartTab);
      if (tab) tab.style.display = 'block';
      // load the newly selected tab's data on demand
      const loader = loaders[btn.dataset.smartTab];
      if (loader && smartState.month) loader(smartState.month);
    });
  });
}

async function fetchSection(path, key) {
  const res = await apiSmartGet(path);
  if (res && res.empty) {
    showSmartSectionEmpty(key, res.message || _t('No data'));
  }
  return res;
}

export function loadClustersTab(month) {
  return fetchSection(`/smart/clusters/${month}`, 'advanced').then(d => {
    if (!d || d.empty) return;
    const clustering = d.clustering || {};
    const points = clustering.points || [];
    renderClusterScatter(points, clustering.labels || [], clustering.features || []);
    renderClusterProfiles(clustering.profiles || []);
  });
}

export function loadCorrelationsTab(month) {
  return fetchSection(`/smart/correlations/${month}`, 'advanced').then(d => {
    if (!d || d.empty) return;
    const corr = d.correlations || {};
    renderCorrelationHeatmap(corr.matrix || [], corr.features || []);
    return fetchSection(`/smart/residuals/${month}`, 'advanced').then(rd => {
      if (!rd || rd.empty) return;
      renderResidualPlot(rd.residuals || []);
    });
  });
}

export function loadPatternsTab(month) {
  return fetchSection(`/smart/patterns/${month}`, 'advanced').then(d => {
    if (!d || d.empty) return;
    renderCompositePatterns(d.patterns || []);
    return fetchSection(`/smart/lag-analysis/${month}`, 'advanced').then(ld => {
      if (!ld || ld.empty) return;
      renderLagAnalysis(ld.lag_analysis || {});
    });
  });
}

export function loadXGBoostTab(month) {
  return fetchSection(`/smart/xgboost/${month}`, 'xgboost').then(d => {
    if (!d || d.empty) return;
    renderXGBoost(d.xgboost || {});
  });
}

export function loadFeatureImportanceTab(month) {
  // Derived from the anomaly explanations — fetched lazily since the decision-board
  // payload (smartState.data) does not include explanations (CRIT-2).
  return fetchSection(`/smart/anomalies/${month}`, 'advanced').then(d => {
    if (!d || d.empty) return;
    renderFeatureImportance(d.explanations || []);
  });
}

export function loadAdvancedSection(month) {
  // Entry used by the IntersectionObserver: load only the active tab's data.
  const active = document.querySelector('.smart-tab-btn.active');
  const tab = active ? active.dataset.smartTab : 'clusters-tab';
  if (tab === 'clusters-tab') return loadClustersTab(month);
  if (tab === 'corr-tab') return loadCorrelationsTab(month);
  if (tab === 'patterns-tab') return loadPatternsTab(month);
  if (tab === 'fi-tab') return loadFeatureImportanceTab(month);
  return loadXGBoostTab(month);
}

export function renderClusterScatter(points, labels, features) {
  const colors = ['#3b82f6', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#06b6d4', '#84cc16'];
  const clusters = [...new Set(labels)];
  const traces = clusters.map((c, i) => {
    const pts = points.filter((_, idx) => labels[idx] === c);
    return {
      x: pts.map(p => p[0]), y: pts.map(p => p[1]),
      name: `${_t('Cluster')} ${c}`,
      type: 'scatter', mode: 'markers',
      marker: { color: colors[i % colors.length] },
    };
  });
  renderPlot('smart-cluster-scatter', traces, {
    xaxis: { title: features[0] || 'PC1' }, yaxis: { title: features[1] || 'PC2' },
  });
}

export function renderClusterProfiles(profiles) {
  const c = document.getElementById('smart-cluster-profiles');
  if (!c) return;
  c.innerHTML = profiles.map(p => `<div class="smart-priority-item smart-priority-normal">
    <div><div class="smart-priority-name">${_t('Cluster')} ${_smartEscapeHtml(p.cluster)} — ${_fmtNum(p.size)} ${_t('hospitals')}</div>
    <div class="smart-priority-meta">${_smartEscapeHtml(p.description || '')}</div></div>
  </div>`).join('');
}

export function renderCorrelationHeatmap(matrix, features) {
  makeHeatmap('smart-correlation-heatmap', matrix, features, features, { title: _t('Feature correlations') });
}

export function renderResidualPlot(residuals) {
  const c = document.getElementById('smart-residual-plot');
  if (!c) return;
  renderPlot('smart-residual-plot', [{
    x: residuals.map(r => r.hospital_id), y: residuals.map(r => r.residual),
    type: 'bar', marker: { color: residuals.map(r => r.residual > 0 ? '#ef4444' : '#3b82f6') },
  }], { title: _t('Residuals by hospital'), xaxis: { title: _t('Hospital ID') } });
  const _ = c; // container kept for no-op guards
}

export function renderCompositePatterns(patterns) {
  const c = document.getElementById('smart-composite-patterns');
  if (!c) return;
  if (!patterns.length) { c.innerHTML = `<div class="smart-empty-state">${_t('No composite patterns')}</div>`; return; }
  c.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
    <th>${_t('Pattern')}</th><th>${_t('Hospitals')}</th><th>${_t('Description')}</th>
  </tr></thead><tbody>` + patterns.map(p => `<tr>
    <td style="font-weight:600;">${_smartEscapeHtml(p.name)}</td>
    <td>${_smartEscapeHtml((p.hospitals || []).join('، '))}</td>
    <td style="font-size:0.78rem;">${_smartEscapeHtml(p.description_ar || p.description || '')}</td>
  </tr>`).join('') + `</tbody></table></div>`;
}

export function renderLagAnalysis(lag) {
  const c = document.getElementById('smart-lag-analysis');
  if (!c) return;
  const matrix = lag.matrix || [];
  const html = `<div class="smart-table-wrap"><table><thead><tr><th></th>${
    matrix.map(m => `<th>${_smartEscapeHtml(smartTranslateFeature(m.feature))}</th>`).join('')}
  </tr></thead><tbody>` + matrix.map(row => `<tr>
    <td style="font-weight:600;">${_smartEscapeHtml(smartTranslateFeature(row.feature))}</td>
    ${matrix.map(m => `<td style="text-align:center;">${m.feature === row.feature ? '—' : _fmtNum(row.values[m.feature], 2)}</td>`).join('')}
  </tr>`).join('') + `</tbody></table></div>`;
  const note = lag.note_ar || lag.note_en || '';
  c.innerHTML = (note ? `<div class="smart-empty-state">${_smartEscapeHtml(note)}</div>` : '') + html;
}

export function renderXGBoost(xgb) {
  const pred = xgb.predictions || [];
  const c = document.getElementById('smart-xgboost-predictions');
  if (!c) return;
  renderWalkForward(xgb);
  renderPredictedScatter(xgb);
  if (!pred.length) { c.innerHTML = `<div class="smart-empty-state">${_t('Not enough predictions for this month')}</div>`; return; }
  c.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
    <th>${_t('Hospital')}</th><th>${_t('Predicted score')}</th><th>${_t('Risk')}</th></tr></thead><tbody>` +
    pred.map(p => `<tr><td>${_smartEscapeHtml(p.hospital_name)}</td>
      <td>${_fmtNum(p.prediction ?? p.predicted_next_score, 3)}</td>
      <td>${_riskLevel(p.prediction ?? p.predicted_next_score)}</td></tr>`).join('') + `</tbody></table></div>`;
}

export function renderWalkForward(xgb) {
  const c = document.getElementById('smart-walk-forward');
  if (!c) return;
  const folds = xgb.walk_forward || [];
  if (!folds.length) { c.innerHTML = `<div class="smart-empty-state">${_t('No walk-forward validation yet')}</div>`; return; }
  const meanR2 = folds.reduce((s, f) => s + (f.r2 || 0), 0) / folds.length;
  const meanMae = folds.reduce((s, f) => s + (f.mae || 0), 0) / folds.length;
  renderPlot('smart-walk-forward', [{
    type: 'bar',
    x: folds.map(f => `↖ ${f.train_through}`),
    y: folds.map(f => f.r2 || 0),
    marker: { color: folds.map(f => (f.r2 || 0) >= 0 ? '#f97316' : '#ef4444') },
    text: folds.map(f => (f.r2 || 0).toFixed(3)),
    textposition: 'outside', cliponaxis: false,
  }], { margin: { t: 25, b: 45, l: 45, r: 15 }, height: 220,
    xaxis: { title: { text: `${_t('Fold')} (${_t('trained through')})`, font: { size: 9 } }, tickfont: { size: 9 } },
    yaxis: { title: { text: 'R²', font: { size: 9 } }, gridcolor: '#f0f0f0', zeroline: true } });
  c.insertAdjacentHTML('beforeend', `<div class="smart-empty-state" style="margin-top:0.4rem;">${_t('Walk-forward')}: ${folds.length} ${_t('folds')} — ${_t('Avg')} R²=${meanR2.toFixed(3)} · MAE=${meanMae.toFixed(3)}</div>`);
}

export function renderPredictedScatter(xgb) {
  const el = document.getElementById('smart-predicted-scatter');
  if (!el) return;
  const preds = xgb.predictions || [];
  if (!preds.length) {
    if (window.Plotly) Plotly.purge('smart-predicted-scatter');
    return;
  }
  const pred = preds.map(p => ({ ...p, prediction: p.prediction ?? p.predicted_next_score }));
  const data = [{
    type: 'scatter', mode: 'markers',
    x: pred.map(p => p.current_score),
    y: pred.map(p => p.prediction),
    marker: {
      size: pred.map(p => 10 + (p.confidence || 0.5) * 14),
      color: pred.map(p => p.predicted_severity === 'critical' ? '#ef4444' : p.predicted_severity === 'warning' ? '#f59e0b' : '#22c55e'),
      line: { color: '#fff', width: 1 },
    },
    text: pred.map(p => `${p.hospital_name}<br>${_t('Current')}: ${(p.current_score || 0).toFixed(2)}<br>${_t('Predicted')}: ${p.prediction.toFixed(2)}`),
    hovertemplate: '%{text}<extra></extra>',
  }];
  renderPlot('smart-predicted-scatter', data, {
    margin: { t: 20, b: 40, l: 50, r: 20 },
    xaxis: { title: _t('Current anomaly score'), range: [0, 1] },
    yaxis: { title: _t('Predicted score'), range: [0, 1] },
    showlegend: false,
    shapes: [
      { type: 'line', x0: 0, x1: 1, y0: 0, y1: 1, xref: 'x', yref: 'y', line: { color: '#999', width: 1.5, dash: 'dot' } },
    ],
  });
}

export function renderFeatureImportance(explanations) {
  const c = document.getElementById('smart-feature-importance');
  if (!c) return;
  const factors = {};
  (explanations || []).forEach(e => (e.top_factors || []).forEach(f => {
    const key = f.arabic_label || f.feature;
    factors[key] = (factors[key] || 0) + Math.abs(f.shap_value || 0);
  }));
  const sorted = Object.entries(factors).sort((a, b) => b[1] - a[1]).slice(0, 15);
  makeBarChart('smart-feature-importance', sorted.map(x => x[0]), sorted.map(x => x[1]), {
    title: _t('Feature importance (SHAP)'), colors: '#8b5cf6',
  });
  const _ = c;
}

function _riskLevel(score) {
  const label = score >= 0.6 ? _t('critical') : score >= 0.3 ? _t('warning') : _t('normal');
  const cls = score >= 0.6 ? 'smart-badge-critical' : score >= 0.3 ? 'smart-badge-warning' : 'smart-badge-normal';
  return `<span class="${cls}">${_smartEscapeHtml(label)}</span>`;
}