const SMART_COLORS = {
  normal: '#22c55e', warning: '#f59e0b', critical: '#ef4444',
  clusters: ['#3b82f6', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#06b6d4', '#84cc16'],
  noise: '#6b7280', shap_positive: '#ef4444', shap_negative: '#3b82f6',
  corr_negative: '#3b82f6', corr_zero: '#ffffff', corr_positive: '#ef4444',
};

let smartCurrentMonth = null;
let smartCurrentData = null;

async function apiSmartGet(path) {
  const base = document.getElementById('apiBase')?.value || '';
  const res = await fetch(base + path);
  return res.json();
}

window.initSmartAnalytics = async function() {
  const monthsRes = await apiSmartGet('/analysis/months');
  const months = monthsRes?.months || monthsRes || [];
  const select = document.getElementById('smart-month-select');
  select.innerHTML = '';
  months.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.month || m; opt.textContent = m.month || m;
    select.appendChild(opt);
  });
  select.addEventListener('change', () => loadSmartData(select.value));
  document.getElementById('smart-refresh').addEventListener('click', () => loadSmartData(select.value));
  document.getElementById('smart-close-drilldown').addEventListener('click', () => {
    document.getElementById('smart-drilldown-panel').style.display = 'none';
  });
  document.getElementById('smart-residual-indicator').addEventListener('change', () => {
    if (smartCurrentData) renderResidualPlot(smartCurrentData.data.residuals, document.getElementById('smart-residual-indicator').value);
  });
  document.getElementById('smart-fi-indicator').addEventListener('change', () => {
    if (smartCurrentData) renderFeatureImportance(smartCurrentData.data.correlations, document.getElementById('smart-fi-indicator').value);
  });
  document.getElementById('smart-strat-indicator').addEventListener('change', () => {
    if (smartCurrentData) renderStratifiedComparison(smartCurrentData.data.stratified, document.getElementById('smart-strat-indicator').value);
  });
  if (months.length > 0) {
    const lastMonth = months[months.length - 1];
    select.value = lastMonth.month || lastMonth;
    loadSmartData(select.value);
  }
};

async function loadSmartData(month) {
  smartCurrentMonth = month;
  document.getElementById('smart-status').textContent = 'جاري التحميل...';
  try {
    smartCurrentData = await apiSmartGet(`/smart/overview/${month}`);
    const d = smartCurrentData.data;
    renderKPIs(d.kpi);
    renderGeoMap(d.geo);
    renderClusterScatter(d.clustering, d.anomalies);
    renderCorrelationHeatmap(d.correlations);
    renderResidualPlot(d.residuals, document.getElementById('smart-residual-indicator').value);
    renderAnomalyTable(d.anomalies, d.explanations);
    renderFeatureImportance(d.correlations, document.getElementById('smart-fi-indicator').value);
    renderStratifiedComparison(d.stratified, document.getElementById('smart-strat-indicator').value);
    document.getElementById('smart-status').textContent = `تم التحديث — ${d.hospitals_count} مستشفى`;
  } catch (e) {
    document.getElementById('smart-status').textContent = 'خطأ في التحميل: ' + e.message;
  }
}

function renderKPIs(kpi) {
  const c = document.getElementById('smart-kpi-container');
  const statusColor = kpi.month_status === 'critical' ? SMART_COLORS.critical : kpi.month_status === 'attention_needed' ? SMART_COLORS.warning : SMART_COLORS.normal;
  const statusText = kpi.month_status === 'critical' ? '🔴 حرج' : kpi.month_status === 'attention_needed' ? '🟡 يحتاج مراقبة' : '🟢 طبيعي';
  c.innerHTML = `
    <div class="card" style="text-align:center;padding:1rem;"><div style="font-size:2rem;font-weight:700;color:${kpi.total_anomalies > 0 ? SMART_COLORS.critical : SMART_COLORS.normal};">${kpi.total_anomalies}</div><div style="font-size:0.85rem;color:#666;">حالات شاذة</div></div>
    <div class="card" style="text-align:center;padding:1rem;"><div style="font-size:2rem;font-weight:700;">${kpi.affected_governorates}</div><div style="font-size:0.85rem;color:#666;">محافظات متأثرة</div></div>
    <div class="card" style="text-align:center;padding:1rem;"><div style="font-size:1.2rem;font-weight:600;">${kpi.top_contributing_factor || '-'}</div><div style="font-size:0.85rem;color:#666;">العامل الأبرز</div></div>
    <div class="card" style="text-align:center;padding:1rem;border-left:4px solid ${statusColor};"><div style="font-size:1.5rem;font-weight:700;">${statusText}</div><div style="font-size:0.85rem;color:#666;">حالة الشهر</div></div>
  `;
}

function renderGeoMap(geo) {
  if (!geo || !geo.governorates || geo.governorates.length === 0) {
    document.getElementById('smart-geo-text').textContent = 'لا توجد بيانات جغرافية متاحة.';
    return;
  }
  const data = [{
    type: 'choropleth',
    locations: geo.governorates.map(g => g.governorate),
    z: geo.governorates.map(g => g.avg_anomaly_score),
    text: geo.governorates.map(g => `<b>${g.governorate}</b><br>المستشفيات: ${g.hospital_count}<br>متوسط الشذوذ: ${g.avg_anomaly_score.toFixed(2)}<br>حالات شاذة: ${g.outlier_count}`),
    colorscale: [[0, SMART_COLORS.normal], [0.3, SMART_COLORS.warning], [0.6, SMART_COLORS.critical], [1, SMART_COLORS.critical]],
    showscale: true, colorbar: {title: 'درجة الشذوذ'},
  }];
  Plotly.newPlot('smart-geo-map', data, {geo: {scope: 'asia', center: {lat: 31.4, lon: 34.4}, projection: {scale: 8000}}, margin: {t: 0, b: 0, l: 0, r: 0}});
  const affected = geo.governorates.filter(g => g.avg_anomaly_score > 0.3).length;
  document.getElementById('smart-geo-text').textContent = `${affected} محافظات تظهر انحرافات عن المعدل المتوقع.`;
}

function renderClusterScatter(clustering, anomalies) {
  if (!clustering || !clustering.pca_coordinates) {
    document.getElementById('smart-cluster-text').textContent = 'لا توجد بيانات تجميع متاحة.';
    return;
  }
  const coords = clustering.pca_coordinates;
  const anomalyMap = {};
  anomalies.forEach(a => { anomalyMap[a.hospital_name] = a; });
  const traces = [];
  const clusterColors = {};
  let ci = 0;
  clustering.clusters.forEach(c => {
    if (!(c.cluster_id in clusterColors)) { clusterColors[c.cluster_id] = SMART_COLORS.clusters[ci % SMART_COLORS.clusters.length]; ci++; }
  });
  const grouped = {};
  clustering.clusters.forEach(c => {
    if (!grouped[c.cluster_id]) grouped[c.cluster_id] = [];
    grouped[c.cluster_id].push(c);
  });
  Object.entries(grouped).forEach(([cid, hospitals]) => {
    const x = hospitals.map(h => coords[h.hospital_name]?.x || 0);
    const y = hospitals.map(h => coords[h.hospital_name]?.y || 0);
    const sizes = hospitals.map(h => { const a = anomalyMap[h.hospital_name]; return a ? 8 + a.anomaly_score * 20 : 8; });
    const colors = hospitals.map(h => { const a = anomalyMap[h.hospital_name]; if (a?.severity === 'critical') return SMART_COLORS.critical; if (a?.severity === 'warning') return SMART_COLORS.warning; return clusterColors[cid]; });
    traces.push({ x, y, mode: 'markers', type: 'scatter', name: `عنقود ${cid}`, marker: { size: sizes, color: colors }, text: hospitals.map(h => `${h.hospital_name}<br>عنقود: ${cid}<br>شذوذ: ${(anomalyMap[h.hospital_name]?.anomaly_score || 0).toFixed(2)}`), hoverinfo: 'text' });
  });
  if (clustering.noise_hospitals.length > 0) {
    traces.push({ x: clustering.noise_hospitals.map(h => coords[h]?.x || 0), y: clustering.noise_hospitals.map(h => coords[h]?.y || 0), mode: 'markers', type: 'scatter', name: 'نقاط ضوضاء', marker: { size: 10, color: SMART_COLORS.noise, symbol: 'x' }, text: clustering.noise_hospitals.map(h => `${h}<br>خارج أي عنقود`), hoverinfo: 'text' });
  }
  Plotly.newPlot('smart-cluster-scatter', traces, { xaxis: {title: 'المكون الرئيسي الأول'}, yaxis: {title: 'المكون الرئيسي الثاني'}, margin: {t: 20, b: 40, l: 60, r: 20} });
  const noiseCount = clustering.noise_hospitals.length;
  document.getElementById('smart-cluster-text').textContent = `تم تجميع المستشفيات إلى ${clustering.n_clusters} مجموعات.${noiseCount > 0 ? ` ${noiseCount} مستشفى خرج عن أي مجموعة.` : ''}`;
}

function renderCorrelationHeatmap(correlations) {
  if (!correlations || !correlations.matrix || Object.keys(correlations.matrix).length === 0) {
    document.getElementById('smart-corr-text').textContent = 'لا توجد بيانات ارتباط متاحة.';
    return;
  }
  const indicators = correlations.indicators;
  const z = indicators.map(ind_a => indicators.map(ind_b => correlations.matrix[ind_a]?.[ind_b] || 0));
  const data = [{ type: 'heatmap', z: z, x: indicators, y: indicators, colorscale: [[0, SMART_COLORS.corr_negative], [0.5, SMART_COLORS.corr_zero], [1, SMART_COLORS.corr_positive]], zmin: -1, zmax: 1, showscale: true, colorbar: {title: 'r'} }];
  Plotly.newPlot('smart-correlation-heatmap', data, { margin: {t: 20, b: 80, l: 80, r: 20}, xaxis: {tickangle: -45} });
  const strong = correlations.strong_correlations?.[0];
  document.getElementById('smart-corr-text').textContent = strong ? `أقوى علاقة: ${strong.indicator_a} ↔ ${strong.indicator_b} (r=${strong.pearson_r.toFixed(2)})` : 'لم يتم اكتشاف علاقات قوية.';
}

function renderResidualPlot(residuals, indicator) {
  if (!residuals || residuals.length === 0) { Plotly.purge('smart-residual-plot'); return; }
  const filtered = residuals.filter(r => r.indicator === indicator);
  if (filtered.length === 0) { Plotly.purge('smart-residual-plot'); document.getElementById('smart-residual-text').textContent = 'لا توجد بيانات residuals لهذا المؤشر.'; return; }
  const colors = filtered.map(r => Math.abs(r.residual_z_score) > 2 ? SMART_COLORS.critical : Math.abs(r.residual_z_score) > 1.5 ? SMART_COLORS.warning : SMART_COLORS.normal);
  const data = [{ type: 'scatter', mode: 'markers', x: filtered.map(r => r.predicted_value), y: filtered.map(r => r.residual), marker: { size: 10, color: colors }, text: filtered.map(r => `${r.hospital_name}<br>فعلي: ${r.actual_value.toFixed(1)}<br>متوقع: ${r.predicted_value.toFixed(1)}<br>بواقي: ${r.residual.toFixed(1)}`), hoverinfo: 'text' }];
  const shapes = [
    { type: 'line', x0: 0, x1: 1, y0: 0, y1: 0, xref: 'paper', line: { color: '#999', width: 1, dash: 'dash' } },
    { type: 'line', x0: 0, x1: 1, y0: filtered.reduce((s,r) => s + r.residual, 0) / filtered.length * 2, y1: filtered.reduce((s,r) => s + r.residual, 0) / filtered.length * 2, xref: 'paper', yref: 'y', line: { color: SMART_COLORS.warning, width: 1, dash: 'dot' } },
  ];
  Plotly.newPlot('smart-residual-plot', data, { shapes, xaxis: {title: 'القيمة المتوقعة'}, yaxis: {title: 'البواقي (فعلي - متوقع)'}, margin: {t: 20, b: 40, l: 60, r: 20} });
  const outliers = filtered.filter(r => r.is_anomaly).length;
  document.getElementById('smart-residual-text').textContent = `${outliers} مستشفى يظهر انحرافاً حقيقياً بعد استبعاد تأثير الموقع والنوع.`;
}

function renderAnomalyTable(anomalies, explanations) {
  if (!anomalies || anomalies.length === 0) { document.getElementById('smart-anomaly-table').innerHTML = '<p>لا توجد بيانات شذوذ.</p>'; return; }
  const expMap = {}; explanations?.forEach(e => { expMap[e.hospital_name] = e; });
  const sorted = [...anomalies].sort((a, b) => b.anomaly_score - a.anomaly_score);
  let html = '<table style="width:100%;border-collapse:collapse;font-size:0.85rem;"><thead><tr style="background:#f0f0f0;"><th style="padding:0.5rem;text-align:right;">المستشفى</th><th style="padding:0.5rem;">المحافظة</th><th style="padding:0.5rem;">الدرجة</th><th style="padding:0.5rem;">الحالة</th><th style="padding:0.5rem;">العامل الأساسي</th><th style="padding:0.5rem;">إجراء</th></tr></thead><tbody>';
  sorted.forEach(a => {
    const sevColor = a.severity === 'critical' ? SMART_COLORS.critical : a.severity === 'warning' ? SMART_COLORS.warning : SMART_COLORS.normal;
    const sevText = a.severity === 'critical' ? '🔴 حرج' : a.severity === 'warning' ? '🟡 تنبيه' : '🟢 طبيعي';
    const topFactor = expMap[a.hospital_name]?.top_factors?.[0]?.arabic_label || '-';
    html += `<tr style="border-bottom:1px solid #eee;cursor:pointer;" onclick="window.smartDrilldown(${a.hospital_id})"><td style="padding:0.5rem;font-weight:600;">${a.hospital_name}</td><td style="padding:0.5rem;">${a.governorate}</td><td style="padding:0.5rem;color:${sevColor};font-weight:700;">${a.anomaly_score.toFixed(2)}</td><td style="padding:0.5rem;">${sevText}</td><td style="padding:0.5rem;font-size:0.8rem;">${topFactor}</td><td style="padding:0.5rem;"><button class="btn btn-sm btn-outline" onclick="event.stopPropagation();window.smartDrilldown(${a.hospital_id})">تفاصيل</button></td></tr>`;
  });
  html += '</tbody></table>';
  document.getElementById('smart-anomaly-table').innerHTML = html;
  const critical = anomalies.filter(a => a.severity === 'critical').length;
  document.getElementById('smart-table-text').textContent = critical > 0 ? `${critical} حالة حرجة تحتاج تحقيقاً فورياً.` : 'جميع المستشفيات ضمن النطاق الطبيعي.';
}

function renderFeatureImportance(correlations, targetIndicator) {
  if (!correlations || !correlations.feature_importance) { Plotly.purge('smart-feature-importance'); return; }
  const fi = correlations.feature_importance.find(f => f.target_indicator === targetIndicator);
  if (!fi || fi.features.length === 0) { Plotly.purge('smart-feature-importance'); document.getElementById('smart-fi-text').textContent = 'لا توجد أهمية عوامل متاحة لهذا المؤشر.'; return; }
  const features = fi.features.slice(0, 8);
  const data = [{ type: 'bar', orientation: 'h', y: features.map(f => f.feature_name), x: features.map(f => f.importance), marker: { color: features.map((f, i) => `rgba(26,35,126,${1 - i * 0.1})`) } }];
  Plotly.newPlot('smart-feature-importance', data, { xaxis: {title: 'الأهمية'}, yaxis: {autorange: 'reversed'}, margin: {t: 10, b: 40, l: 120, r: 20} });
  document.getElementById('smart-fi-text').textContent = `أهم عامل يؤثر على ${targetIndicator}: ${features[0]?.feature_name}`;
}

function renderStratifiedComparison(stratified, indicator) {
  if (!stratified || stratified.length === 0) { Plotly.purge('smart-stratified-chart'); return; }
  const filtered = stratified.filter(s => s.indicator === indicator);
  if (filtered.length === 0) { Plotly.purge('smart-stratified-chart'); return; }
  const sorted = [...filtered].sort((a, b) => b.deviation_pct - a.deviation_pct);
  const barColors = sorted.map(s => Math.abs(s.deviation_pct) > 30 ? SMART_COLORS.critical : Math.abs(s.deviation_pct) > 15 ? SMART_COLORS.warning : SMART_COLORS.normal);
  const data = [
    { type: 'bar', name: 'المستشفى', x: sorted.map(s => s.hospital_name), y: sorted.map(s => s.hospital_value), marker: { color: barColors } },
    { type: 'bar', name: 'متوسط النظير', x: sorted.map(s => s.hospital_name), y: sorted.map(s => s.peer_group_mean), marker: { color: '#d1d5db' } },
  ];
  Plotly.newPlot('smart-stratified-chart', data, { barmode: 'group', xaxis: {tickangle: -45}, yaxis: {title: 'القيمة'}, margin: {t: 20, b: 100, l: 60, r: 20} });
  const significant = filtered.filter(s => s.label.includes('significantly')).length;
  document.getElementById('smart-strat-text').textContent = `${significant} مستشفى يختلف بشكل ملحوظ عن مجموعته النظيرة.`;
}

window.smartDrilldown = async function(hospitalId) {
  if (!smartCurrentMonth) return;
  const data = await apiSmartGet(`/smart/drilldown/${hospitalId}/${smartCurrentMonth}`);
  document.getElementById('smart-drilldown-name').textContent = data.hospital_name;
  document.getElementById('smart-drilldown-panel').style.display = 'block';
  if (data.explanation?.top_factors) {
    const factors = data.explanation.top_factors;
    const wfData = [{ type: 'waterfall', orientation: 'v', x: factors.map(f => f.arabic_label), y: factors.map(f => f.shap_value), connector: {line: {color: '#ccc'}}, decreasing: {marker: {color: SMART_COLORS.shap_negative}}, increasing: {marker: {color: SMART_COLORS.shap_positive}} }];
    Plotly.newPlot('smart-shap-waterfall', wfData, { margin: {t: 20, b: 60, l: 60, r: 20}, yaxis: {title: 'قيمة SHAP'} });
  }
  if (data.anomaly) {
    document.getElementById('smart-drilldown-text').textContent = data.explanation?.text_explanation || 'لا توجد تفسيرات متاحة.';
  }
  const trendRes = await apiSmartGet(`/smart/trend/${hospitalId}`);
  if (trendRes?.trend?.length > 0) {
    const trend = trendRes.trend;
    const tColors = trend.map(t => t.severity === 'critical' ? SMART_COLORS.critical : t.severity === 'warning' ? SMART_COLORS.warning : SMART_COLORS.normal);
    Plotly.newPlot('smart-trend-line', [{ type: 'scatter', mode: 'lines+markers', x: trend.map(t => t.month), y: trend.map(t => t.anomaly_score), marker: { size: 10, color: tColors }, line: { color: '#1a237e', width: 2 } }], { shapes: [
      { type: 'rect', x0: 0, x1: 1, y0: 0, y1: 0.3, xref: 'paper', fillcolor: SMART_COLORS.normal, opacity: 0.1 },
      { type: 'rect', x0: 0, x1: 1, y0: 0.3, y1: 0.6, xref: 'paper', fillcolor: SMART_COLORS.warning, opacity: 0.1 },
      { type: 'rect', x0: 0, x1: 1, y0: 0.6, y1: 1, xref: 'paper', fillcolor: SMART_COLORS.critical, opacity: 0.1 },
    ], xaxis: {title: 'الشهر'}, yaxis: {title: 'درجة الشذوذ', range: [0, 1]}, margin: {t: 20, b: 40, l: 50, r: 20} });
  }
};
