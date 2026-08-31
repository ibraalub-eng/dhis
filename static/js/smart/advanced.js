// advanced.js — heavy analytical sections (clusters, correlations, patterns, forecasts).
import { smartState, apiSmartGet, showSmartSectionError,
         showSmartSectionEmpty, clearSmartSectionState,
         _smartEscapeHtml, _t, _fmtNum, smartTranslateFeature } from './core.js';
import { renderPlot, makeScatter, makeHeatmap, makeBarChart, makeLineChart } from './charts.js';

// Expose fetchSection globally so retry buttons can re-trigger loads
window.__smartFetchSection = fetchSection;

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

async function fetchSection(path, key, _retries) {
  if (_retries === undefined) _retries = 0;
  try {
    const res = await apiSmartGet(path);
    if (res && res.computing && _retries < 15) {
      const mins = Math.floor((_retries * 3) / 60);
      const secs = (_retries * 3) % 60;
      const elapsed = mins > 0 ? mins + 'm ' + secs + 's' : secs + 's';
      showSmartSectionEmpty(key, _t('Computing analysis...') + ' (' + elapsed + ')', {
        retryPath: path, retryKey: key
      });
      await new Promise(r => setTimeout(r, 3000));
      return fetchSection(path, key, _retries + 1);
    }
    if (res && res.computing && _retries >= 15) {
      showSmartSectionError(key, _t('Computation is taking longer than expected.') + ' ' + _t('Try again later.'), {
        retryPath: path, retryKey: key
      });
    } else if (res && res.empty) {
      showSmartSectionEmpty(key, res.message || _t('No data for this period. Upload data and try again.'), {
        retryPath: path, retryKey: key
      });
    } else if (!res || res._error) {
      showSmartSectionError(key, (res && res.detail) || _t('Failed to load data. Check server connection.'), {
        retryPath: path, retryKey: key
      });
    } else {
      clearSmartSectionState(key);
    }
    return res;
  } catch (e) {
    showSmartSectionError(key, e.message || _t('Network error. Please try again.'), {
      retryPath: path, retryKey: key
    });
    return null;
  }
}

export function loadClustersTab(month) {
  return fetchSection(`/smart/clusters/${month}`, 'advanced').then(d => {
    if (!d || d.empty) return;
    const clustering = d.clustering || {};
    const clusterDetails = clustering.clusters || [];
    // Backend returns pca_coordinates as {name: {x,y}} dict
    const pcaDict = clustering.pca_coordinates || {};
    // Build points and labels arrays aligned by hospital order from clusters
    const points = [];
    const labels = [];
    clusterDetails.forEach(function(c) {
      const coord = pcaDict[c.hospital_name];
      if (coord) {
        points.push([coord.x, coord.y]);
        labels.push(c.cluster_id);
      }
    });
    renderClusterScatter(points, labels, clustering.features || ['PC1', 'PC2']);
    renderClusterProfiles(clustering.profiles || [], clustering);
  });
}

export function loadCorrelationsTab(month) {
  return fetchSection(`/smart/correlations/${month}`, 'advanced').then(d => {
    if (!d || d.empty) return;
    const corr = d.correlations || {};
    // Backend returns indicators (not features) and dict-of-dicts matrix
    const indicators = corr.indicators || [];
    const rawMatrix = corr.matrix || {};
    // Convert dict-of-dicts to 2D array matching indicator order
    const matrix2D = indicators.map(row => indicators.map(col => {
      const v = rawMatrix[row] && rawMatrix[row][col];
      return v != null ? v : 0;
    }));
    renderCorrelationHeatmap(matrix2D, indicators);
    renderStrongCorrelations(corr.strong_correlations || []);
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
    return Promise.all([
      fetchSection(`/smart/lag-analysis/${month}`, 'advanced').then(ld => {
        if (!ld || ld.empty) return;
        renderLagAnalysis(ld.lag_analysis || {});
      }).catch(() => {}),
      fetchSection(`/smart/stratified/${month}`, 'advanced').then(sd => {
        if (!sd || sd.empty) return;
        renderStratifiedAnalysis(sd.stratified || [], month);
      }).catch(() => {}),
    ]);
  });
}

export function loadXGBoostTab(month) {
  return fetchSection(`/smart/xgboost/${month}`, 'xgboost').then(d => {
    if (!d) return;
    // Even if empty, try to show the latest month's model info as fallback
    if (d.empty) {
      const c = document.getElementById('smart-xgboost-predictions');
      if (c) c.innerHTML = `<div class="smart-empty-state">${_smartEscapeHtml(d.message || _t('No predictions for this month'))}</div>`;
      // Try to load the latest month's model info as reference
      _showLatestModelInfo(month);
      return;
    }
    renderXGBoost(d.xgboost || {});
  });
}

async function _showLatestModelInfo(currentMonth) {
  try {
    // Try the latest available month
    const months = await apiSmartGet('/smart/months');
    if (!months || !months.length) return;
    const latest = months[months.length - 1];
    if (latest === currentMonth) return; // Already tried this month
    const d = await apiSmartGet(`/smart/xgboost/${latest}`);
    if (d && !d.empty && d.xgboost) {
      const c = document.getElementById('smart-xgboost-predictions');
      if (c) {
        const xgb = d.xgboost;
        c.innerHTML = `<div class="smart-empty-state" style="margin-bottom:0.5rem;">
          <div style="font-weight:600;margin-bottom:0.3rem;">${_t('Latest model')} (${_smartEscapeHtml(latest)})</div>
          <div style="font-size:0.78rem;color:var(--text-muted);">${_smartEscapeHtml(xgb.accuracy_note || '')}</div>
          <div style="font-size:0.78rem;margin-top:0.3rem;">
            <span>${_t('R²')}: ${_fmtNum(xgb.model_r2, 3)}</span> · 
            <span>${_t('MAE')}: ${_fmtNum(xgb.model_mae, 3)}</span> · 
            <span>${_t('Trained on')}: ${xgb.training_months} ${_t('months')}, ${xgb.hospitals_trained} ${_t('hospitals')}</span>
          </div>
        </div>`;
      }
    }
  } catch (e) { /* non-fatal */ }
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

export function renderClusterProfiles(profiles, clustering) {
  const c = document.getElementById('smart-cluster-profiles');
  if (!c) return;
  // Backend profiles may use 'cluster' or 'cluster_id'; size may be in the profile or computed from clusters
  const clusterDetails = (clustering && clustering.clusters) || [];
  const silhouette = clustering && clustering.silhouette_score;
  const method = clustering && clustering.method;
  let header = '';
  if (method || silhouette != null) {
    header = `<div class="smart-empty-state" style="margin-bottom:0.5rem;">${_t('Method')}: ${_smartEscapeHtml(method || '')} · ${_t('Silhouette')}: ${_fmtNum(silhouette, 3)} · ${(clustering.n_clusters || profiles.length)} ${_t('clusters')}</div>`;
  }
  const rows = profiles.map(p => {
    const clusterId = p.cluster != null ? p.cluster : p.cluster_id;
    const hospitals = clusterDetails.filter(c => c.cluster_id === clusterId).map(c => c.hospital_name);
    const size = p.size || hospitals.length;
    const features = (p.distinguishing_features || []).map(f => _smartEscapeHtml(smartTranslateFeature(f.feature || f))).join(', ');
    return `<div class="smart-priority-item smart-priority-normal">
      <div><div class="smart-priority-name">${_t('Cluster')} ${clusterId} — ${size} ${_t('hospitals')}</div>
      <div class="smart-priority-meta">${_smartEscapeHtml(p.description || '')}</div>
      ${features ? `<div style="font-size:0.75rem;color:var(--text-muted);margin-top:0.2rem;">${_t('Key features')}: ${features}</div>` : ''}
      ${hospitals.length ? `<div style="font-size:0.72rem;color:var(--text-muted);margin-top:0.2rem;">${hospitals.map(h => _smartEscapeHtml(h)).join(', ')}</div>` : ''}
      </div>
    </div>`;
  }).join('');
  c.innerHTML = header + rows;
}

export function renderStrongCorrelations(strongCorrelations) {
  // Render a list of significant correlations below the heatmap
  const container = document.getElementById('smart-correlation-heatmap');
  if (!container || !strongCorrelations.length) return;
  let listEl = document.getElementById('smart-strong-corr-list');
  if (!listEl) {
    listEl = document.createElement('div');
    listEl.id = 'smart-strong-corr-list';
    listEl.style.cssText = 'margin-top:0.8rem;';
    container.parentElement.appendChild(listEl);
  }
  listEl.innerHTML = `<div style="font-weight:600;font-size:0.82rem;margin-bottom:0.4rem;">${_t('Strong correlations')}</div>` +
    strongCorrelations.map(c => {
      const strengthCls = Math.abs(c.pearson_r) >= 0.7 ? 'smart-badge smart-badge-critical' : 'smart-badge smart-badge-warning';
      return `<div class="smart-priority-item smart-priority-normal" style="border-left:3px solid ${c.pearson_r > 0 ? '#3b82f6' : '#ef4444'};">
        <div>
          <div class="smart-priority-name">${_smartEscapeHtml(smartTranslateFeature(c.indicator_a))} ↔ ${_smartEscapeHtml(smartTranslateFeature(c.indicator_b))}</div>
          <div class="smart-priority-meta">
            <span class="${strengthCls}" style="margin-right:0.3rem;">r = ${_fmtNum(c.pearson_r, 3)}</span>
            <span>p = ${_fmtNum(c.p_value, 4)}</span>
            <span style="margin-left:0.3rem;">${_smartEscapeHtml(c.strength || '')}</span>
          </div>
        </div>
      </div>`;
    }).join('');
}

export function renderCorrelationHeatmap(matrix, features) {
  makeHeatmap('smart-correlation-heatmap', matrix, features, features, { title: _t('Feature correlations') });
}

export function renderResidualPlot(residuals) {
  const c = document.getElementById('smart-residual-plot');
  if (!c) return;
  if (!residuals.length) { c.innerHTML = `<div class="smart-empty-state">${_t('No residual data')}</div>`; return; }
  // Backend provides actual_value/predicted_value; compute residual
  const data = residuals.slice(0, 40).map(r => ({
    ...r,
    residual: r.residual != null ? r.residual : ((r.actual_value || 0) - (r.predicted_value || 0)),
  }));
  renderPlot('smart-residual-plot', [{
    x: data.map(r => r.hospital_name || r.hospital_id),
    y: data.map(r => r.residual),
    type: 'bar',
    marker: { color: data.map(r => r.residual > 0 ? '#ef4444' : '#3b82f6') },
    text: data.map(r => r.indicator || ''),
    hovertemplate: '%{x}<br>%{text}<br>' + _t('Residual') + ': %{y:.2f}<extra></extra>',
  }], { title: _t('Residuals by hospital'), xaxis: { title: _t('Hospital'), tickangle: -45, tickfont: { size: 9 } }, height: 280 });
}

export function renderCompositePatterns(patterns) {
  const c = document.getElementById('smart-composite-patterns');
  if (!c) return;
  if (!patterns.length) { c.innerHTML = `<div class="smart-empty-state">${_t('No composite patterns')}</div>`; return; }
  c.innerHTML = patterns.map(p => {
    const indicators = p.arabic_names || p.indicators || [];
    const name = indicators.join(' + ');
    const desc = p.summary_ar || '';
    const hospitals = p.hospitals || [];
    const count = p.hospitals_count || hospitals.length;
    const liftBadge = p.lift > 2 ? 'smart-badge smart-badge-critical' : p.lift > 1.5 ? 'smart-badge smart-badge-warning' : 'smart-badge smart-badge-normal';
    const statuses = p.statuses || [];
    // Pair each indicator with its status (elevated/lowered)
    const indicatorStatuses = indicators.map((ind, i) => {
      const st = statuses[i] || '';
      const stLabel = st === 'elevated' ? '↑' : st === 'lowered' ? '↓' : '';
      const stColor = st === 'elevated' ? '#ef4444' : st === 'lowered' ? '#22c55e' : '#94a3b8';
      return `<span style="color:${stColor};">${_smartEscapeHtml(ind)} ${stLabel}</span>`;
    }).join(' + ');
    const hospList = hospitals.length
      ? `<div style="margin-top:0.35rem;font-size:0.75rem;color:var(--text-muted);">${hospitals.map(h => _smartEscapeHtml(h)).join(', ')}</div>`
      : `<div style="margin-top:0.35rem;font-size:0.75rem;color:var(--text-muted);">${count} ${_t('hospitals')}</div>`;
    return `<div class="smart-priority-item smart-priority-normal" style="border-left:3px solid ${p.lift > 2 ? '#ef4444' : p.lift > 1.5 ? '#f59e0b' : '#3b82f6'};">
      <div>
        <div class="smart-priority-name" style="font-weight:600;">${indicatorStatuses}</div>
        <div class="smart-priority-meta">
          <span class="${liftBadge}" style="margin-right:0.3rem;">${_t('Lift')}: ${_fmtNum(p.lift, 2)}</span>
          <span>${_t('Support')}: ${_fmtNum((p.support || 0) * 100, 1)}%</span>
          <span style="margin-left:0.3rem;">${count} ${_t('hospitals')}</span>
        </div>
        <div style="font-size:0.78rem;margin-top:0.2rem;">${_smartEscapeHtml(desc)}</div>
        ${hospList}
      </div>
    </div>`;
  }).join('');
}

export function renderLagAnalysis(lag) {
  const c = document.getElementById('smart-lag-analysis');
  if (!c) return;
  const note = lag.note_ar || lag.note_en || '';
  const lags = lag.lags || [];
  if (!lags.length && !note) { c.innerHTML = ''; return; }

  // Render lag findings as a structured list
  let findingsHtml = '';
  if (lags.length) {
    findingsHtml = '<div style="margin-top:0.5rem;">' + lags.map(f => {
      const strengthCls = (f.strength === 'strong' || Math.abs(f.correlation || 0) >= 0.6) ? 'smart-badge smart-badge-critical' : f.strength === 'moderate' ? 'smart-badge smart-badge-warning' : 'smart-badge smart-badge-normal';
      return `<div class="smart-priority-item smart-priority-normal" style="border-left:3px solid ${f.direction === 'positive' ? '#3b82f6' : '#ef4444'};">
        <div><div class="smart-priority-name">${_smartEscapeHtml(f.summary_ar || f.summary_en || '')}</div>
        <div class="smart-priority-meta">${_smartEscapeHtml(f.prediction_ar || f.prediction_en || '')}
        <span class="${strengthCls}" style="margin-left:0.3rem;">${_t(f.strength || 'info')}</span>
        ${f.correlation != null ? `<span style="margin-left:0.3rem;color:var(--text-muted);">r=${_fmtNum(f.correlation, 3)}</span>` : ''}
        ${f.lag != null ? `<span style="margin-left:0.3rem;color:var(--text-muted);">${_t('lag')}: ${f.lag}m</span>` : ''}
        ${f.granger_pass ? '<span class="smart-badge smart-badge-normal" style="margin-left:0.3rem;">Granger ✓</span>' : ''}
        ${f.is_lead ? '<span class="smart-badge smart-badge-warning" style="margin-left:0.3rem;">' + _t('lead') + '</span>' : ''}
        </div></div></div>`;
    }).join('') + '</div>';
  }

  c.innerHTML = (note ? `<div class="smart-empty-state" style="margin-bottom:0.5rem;">${_smartEscapeHtml(note)}</div>` : '') + findingsHtml;
}

let _stratifiedData = [];
export function renderStratifiedAnalysis(stratified, month) {
  _stratifiedData = stratified;
  const sel = document.getElementById('smart-strat-indicator');
  if (!sel) return;
  const indicators = [...new Set(stratified.map(s => s.indicator))];
  if (!indicators.length) return;
  sel.innerHTML = indicators.map(i => `<option value="${i}">${smartTranslateFeature(i)}</option>`).join('');
  sel.onchange = () => _renderStratifiedChart(sel.value);
  _renderStratifiedChart(indicators[0]);
}

function _renderStratifiedChart(indicator) {
  const filtered = _stratifiedData.filter(s => s.indicator === indicator);
  const chartEl = document.getElementById('smart-stratified-chart');
  const textEl = document.getElementById('smart-strat-text');
  if (!chartEl) return;
  if (!filtered.length) {
    if (window.Plotly) Plotly.purge('smart-stratified-chart');
    if (textEl) textEl.textContent = '';
    return;
  }
  const sorted = [...filtered].sort((a, b) => Math.abs(b.deviation_pct) - Math.abs(a.deviation_pct)).slice(0, 15);
  const xLabels = sorted.map(s => s.hospital_name.length > 22 ? s.hospital_name.substring(0, 20) + '…' : s.hospital_name);
  const barColors = sorted.map(s => Math.abs(s.deviation_pct) > 30 ? '#ef4444' : Math.abs(s.deviation_pct) > 15 ? '#f59e0b' : '#22c55e');
  renderPlot('smart-stratified-chart', [
    { type: 'bar', name: _t('Hospital value'), x: xLabels, y: sorted.map(s => s.hospital_value), marker: { color: barColors } },
    { type: 'bar', name: _t('Peer average'), x: xLabels, y: sorted.map(s => s.peer_group_mean), marker: { color: '#94a3b8' } },
  ], { barmode: 'group', xaxis: { tickangle: -45, tickfont: { size: 10 } }, yaxis: { title: indicator }, height: 300, margin: { t: 15, b: 80 } });
  const significant = filtered.filter(s => Math.abs(s.deviation_pct) > 15).length;
  if (textEl) textEl.textContent = `${significant} ${_t('of')} ${filtered.length} ${_t('hospitals deviate >15% from peer average')}`;
}

export function renderXGBoost(xgb) {
  const pred = xgb.predictions || [];
  const c = document.getElementById('smart-xgboost-predictions');
  if (!c) return;
  renderWalkForward(xgb);
  renderPredictedScatter(xgb);
  // Always show model info header
  const modelInfo = xgb.accuracy_note ? `<div class="smart-empty-state" style="margin-bottom:0.5rem;">
    <div style="font-size:0.78rem;color:var(--text-muted);">${_smartEscapeHtml(xgb.accuracy_note)}</div>
    <div style="font-size:0.78rem;margin-top:0.3rem;">
      <span>${_t('R²')}: ${_fmtNum(xgb.model_r2, 3)}</span> · 
      <span>${_t('MAE')}: ${_fmtNum(xgb.model_mae, 3)}</span> · 
      <span>${_t('Trained on')}: ${xgb.training_months} ${_t('months')}, ${xgb.hospitals_trained} ${_t('hospitals')}</span>
    </div>
  </div>` : '';
  if (!pred.length) {
    c.innerHTML = modelInfo + `<div class="smart-empty-state">${_t('Not enough predictions for this month')}</div>`;
    return;
  }
  c.innerHTML = modelInfo + `<div class="smart-table-wrap"><table><thead><tr>
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
}

function _riskLevel(score) {
  const label = score >= 0.6 ? _t('critical') : score >= 0.3 ? _t('warning') : _t('normal');
  const cls = score >= 0.6 ? 'smart-badge smart-badge-critical' : score >= 0.3 ? 'smart-badge smart-badge-warning' : 'smart-badge smart-badge-normal';
  return `<span class="${cls}">${_smartEscapeHtml(label)}</span>`;
}