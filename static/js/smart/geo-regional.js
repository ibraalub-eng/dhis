// geo-regional.js — map, governorate, and regional analysis for monthly mode.
import { apiSmartGet, showSmartSectionError, showSmartSectionEmpty,
         _smartEscapeHtml, _t, _fmtNum, _riskBadge } from './core.js';
import { renderPlot, makeBarChart } from './charts.js';

export async function loadGeoSection(month) {
  try {
    const d = await apiSmartGet(`/smart/geo/${month}`);
    if (d.empty) { showSmartSectionEmpty('geo', d.message || _t('No data')); return; }
    renderGeoMap(d.geo || {});
    renderGovernorates(d.geo || {});
    renderRegionalAnalysis(d.geo || {});
  } catch (e) {
    showSmartSectionError('geo', e.message);
  }
}

export function renderGeoMap(geo) {
  const mapDiv = document.getElementById('smart-geo-map');
  if (!mapDiv) return;
  const regions = geo.regions || [];
  renderPlot('smart-geo-map', [{
    type: 'choropleth', locationmode: 'ISO-3',
    locations: regions.map(r => r.iso3), z: regions.map(r => r.avg_anomaly_score),
    text: regions.map(r => r.governorate),
    colorscale: [[0, '#22c55e'], [0.5, '#f59e0b'], [1, '#ef4444']],
    zmin: 0, zmax: 1,
    marker: { line: { color: '#fff', width: 1 } },
  }], { title: _t('Geographic distribution'), geo: { showframe: false, showcoastlines: false } });
}

export function renderGovernorates(geo) {
  const c = document.getElementById('smart-governorate-content');
  if (!c) return;
  const govs = (geo.governorates || []).slice().sort((a, b) => b.avg_anomaly_score - a.avg_anomaly_score);
  c.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
    <th>${_t('Governorate')}</th><th>${_t('Hospitals')}</th><th>${_t('Avg score')}</th>
    <th>${_t('Outliers')}</th></tr></thead><tbody>` +
    govs.map(g => `<tr>
      <td style="font-weight:600;">${_smartEscapeHtml(g.governorate)}</td>
      <td style="text-align:center;">${g.hospital_count}</td>
      <td style="text-align:center;">${_riskBadge(_fmtNum(g.avg_anomaly_score, 3), g.avg_anomaly_score >= 0.6 ? 'critical' : g.avg_anomaly_score >= 0.3 ? 'warning' : 'normal')}</td>
      <td style="text-align:center;">${g.outlier_count}</td>
    </tr>`).join('') + `</tbody></table></div>`;
}

export function renderRegionalAnalysis(geo) {
  const c = document.getElementById('smart-regional-content');
  if (!c) return;
  const regions = geo.regions || [];
  if (!regions.length) { c.innerHTML = ''; return; }
  makeBarChart('smart-regional-content-chart', regions.map(r => r.governorate),
    regions.map(r => r.avg_anomaly_score),
    { title: _t('Regional average anomaly score') });
  // makeBarChart renders into a div id; reuse a hidden chart host injected here.
  c.innerHTML = '<div id="smart-regional-content-chart" style="height:240px;"></div>';
  makeBarChart('smart-regional-content-chart', regions.map(r => r.governorate),
    regions.map(r => r.avg_anomaly_score), { title: _t('Regional average anomaly score') });
}