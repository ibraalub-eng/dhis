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
  const govs = geo.governorates || [];
  if (!govs.length) { mapDiv.innerHTML = `<div class="smart-empty-state">${_t('No geographic data')}</div>`; return; }
  renderGazaMap('smart-geo-map', govs);
}

function renderGazaMap(containerId, govs) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const DEFAULT_COLOR = '#5C6370';
  const govMap = {};
  govs.forEach(g => { govMap[g.governorate] = g; });

  function getColor(score) {
    if (score == null) return DEFAULT_COLOR;
    if (score >= 0.6) return '#F87171';
    if (score >= 0.3) return '#FB923C';
    return '#4ADE80';
  }

  const regions = [
    { name: 'شمال غزة', path: 'M60,10 L140,10 L145,80 L55,80 Z', labelY: 45 },
    { name: 'غزة',      path: 'M55,85 L145,85 L150,160 L50,160 Z', labelY: 122 },
    { name: 'دير البلح', path: 'M50,165 L150,165 L145,245 L55,245 Z', labelY: 205 },
    { name: 'خانيونس',  path: 'M55,250 L145,250 L140,330 L60,330 Z', labelY: 290 },
    { name: 'رفح',      path: 'M60,335 L140,335 L135,395 L65,395 Z', labelY: 365 },
  ];

  let svgContent = `<svg viewBox="0 0 200 400" width="100%" style="max-width:200px;height:auto;" role="img" aria-label="${_t('Gaza governorates map')}">`;

  regions.forEach(r => {
    const data = govMap[r.name];
    const score = data ? data.avg_anomaly_score : null;
    const color = getColor(score);
    const label = r.name;
    const hospitals = data ? data.hospital_count : 0;
    const outlierCount = data ? data.outlier_count : 0;
    const tooltip = `${label}\n${_t('Score')}: ${score != null ? score.toFixed(3) : _t('N/A')}\n${_t('Hospitals')}: ${hospitals}\n${_t('Outliers')}: ${outlierCount}`;

    svgContent += `<g class="gaza-gov" style="cursor:pointer;" data-governorate="${label}">
      <path d="${r.path}" fill="${color}" stroke="var(--border-default, #333)" stroke-width="1.5" opacity="0.88">
        <title>${tooltip}</title>
      </path>
      <text x="100" y="${r.labelY}" text-anchor="middle" fill="var(--text-primary, #fff)" font-size="11" font-weight="600" style="pointer-events:none;">${label}</text>
      <text x="100" y="${r.labelY + 15}" text-anchor="middle" fill="var(--text-secondary, #aaa)" font-size="9" style="pointer-events:none;">${score != null ? score.toFixed(3) : '—'}</text>
    </g>`;
  });

  svgContent += '</svg>';
  container.innerHTML = svgContent;

  container.querySelectorAll('.gaza-gov').forEach(g => {
    g.addEventListener('mouseenter', () => {
      g.querySelector('path').style.opacity = '1';
      g.querySelector('path').style.filter = 'brightness(1.15)';
    });
    g.addEventListener('mouseleave', () => {
      g.querySelector('path').style.opacity = '0.88';
      g.querySelector('path').style.filter = '';
    });
    g.addEventListener('click', () => {
      const govName = g.getAttribute('data-governorate');
      const event = new CustomEvent('gaza-gov-click', { detail: { governorate: govName } });
      container.dispatchEvent(event);
    });
  });
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
}export function renderRegionalAnalysis(geo) {
  const c = document.getElementById('smart-regional-content');
  if (!c) return;
  const govs = geo.governorates || [];
  if (!govs.length) { c.innerHTML = ''; return; }
  c.innerHTML = '<div id="smart-regional-content-chart" style="height:240px;"></div>';
  makeBarChart('smart-regional-content-chart', govs.map(g => g.governorate),
    govs.map(g => g.avg_anomaly_score),
    { title: _t('Regional average anomaly score'),
      colors: govs.map(g => g.avg_anomaly_score >= 0.6 ? '#ef4444' : g.avg_anomaly_score >= 0.3 ? '#f59e0b' : '#22c55e') });
}