// hospital.js — hospital-scope mode: trend, forecast, drilldown, root cause.
import { smartState, apiSmartGet, setSmartLoader, showSmartSectionError,
         showSmartSectionEmpty, _smartEscapeHtml, _t, _fmtNum, _riskBadge, smartTranslateFeature } from './core.js';
import { renderPlot, makeLineChart, renderWaterfall } from './charts.js';

/** Read theme-aware colors from CSS variables at render time. */
function getThemeColors() {
  const cs = getComputedStyle(document.documentElement);
  return {
    green: cs.getPropertyValue('--accent-green').trim() || '#4ADE80',
    orange: cs.getPropertyValue('--accent-orange').trim() || '#FB923C',
    red: cs.getPropertyValue('--accent-red').trim() || '#F87171',
    blue: cs.getPropertyValue('--accent-blue').trim() || '#4F8CFF',
    purple: cs.getPropertyValue('--accent-purple').trim() || '#A78BFA',
    teal: cs.getPropertyValue('--accent-teal').trim() || '#2DD4BF',
    textPrimary: cs.getPropertyValue('--text-primary').trim() || '#E8EAED',
    textMuted: cs.getPropertyValue('--text-muted').trim() || '#5C6370',
    bgSurface: cs.getPropertyValue('--bg-surface').trim() || '#1A1D27',
    bgElevated: cs.getPropertyValue('--bg-elevated').trim() || '#252A36',
    borderDefault: cs.getPropertyValue('--border-default').trim() || '#2A2E3B',
  };
}

export function initHospitalSelect(hospitals) {
  const select = document.getElementById('smart-hospital-context-select');
  const monthlySelect = document.getElementById('smart-hospital-select');
  if (select) {
    select.innerHTML = '<option value="">-- ' + _t('Select Hospital') + ' --</option>' +
      hospitals.map(h => `<option value="${h.id}">${_smartEscapeHtml(h.name)}</option>`).join('');
  }
  if (monthlySelect && monthlySelect.options.length === 1) {
    monthlySelect.innerHTML = '<option value="">-- ' + _t('All Hospitals') + ' --</option>' +
      hospitals.map(h => `<option value="${h.id}">${_smartEscapeHtml(h.name)}</option>`).join('');
  }
}

export async function loadHospitalMode(hospitalId, months) {
  const panel = document.getElementById('smart-hospital-panel');
  if (!panel) return;
  setSmartLoader('hospital', true);
  try {
    const trend = await apiSmartGet(`/smart/trend/${hospitalId}`);
    if (!trend.hospital_name) { showSmartSectionEmpty('hospital', _t('No data for this hospital')); return; }

    const drill = await apiSmartGet(`/smart/drilldown/${hospitalId}/all`);
    if (drill.empty && !drill.anomaly) {
      showSmartSectionEmpty('hospital', drill.message || _t('No data'));
      return;
    }

    renderHospitalProfile(drill, trend);
    renderConfidenceGauge(drill, trend);
    renderHospitalGauges(drill);
    renderTrend(trend);
    renderHospitalIndicators(drill.indicators || []);
    renderHospitalPeers(drill.peer_comparison || {}, drill.anomaly);
    renderHospitalLagTimeline(drill.lag_analysis || {}, drill.indicators || []);
    const forecast = drill.forecast || {};
    renderHospitalForecast(forecast);
    renderHospitalFactors(drill.anomaly, drill.explanation);
  } catch (e) {
    showSmartSectionError('hospital', e.message);
  } finally {
    setSmartLoader('hospital', false);
  }
}

function computeTrendDirection(trendData) {
  const points = trendData.trend || [];
  if (points.length < 2) return { overall: 'stable', recent: 'stable', overallDelta: 0, recentDelta: 0 };
  const scores = points.map(p => p.anomaly_score);

  // Overall: compare first half avg vs second half avg
  const mid = Math.floor(scores.length / 2);
  const firstHalf = scores.slice(0, mid || 1);
  const secondHalf = scores.slice(mid);
  const avgFirst = firstHalf.reduce((s, v) => s + v, 0) / firstHalf.length;
  const avgSecond = secondHalf.reduce((s, v) => s + v, 0) / secondHalf.length;
  const overallDelta = avgSecond - avgFirst;
  let overall = 'stable';
  if (overallDelta > 0.05) overall = 'declining';
  else if (overallDelta < -0.05) overall = 'improving';

  // Recent: last 2-3 months direction
  const recent = scores.slice(-Math.min(3, scores.length));
  let recentDelta = 0;
  let recentDir = 'stable';
  if (recent.length >= 2) {
    recentDelta = recent[recent.length - 1] - recent[0];
    if (recentDelta > 0.03) recentDir = 'declining';
    else if (recentDelta < -0.03) recentDir = 'improving';
  }

  return { overall, recent: recentDir, overallDelta, recentDelta };
}

function trendArrow(dir, size) {
  const s = size || '1rem';
  if (dir === 'improving') return `<span style="color:var(--accent-green);font-size:${s};font-weight:800;">↗</span>`;
  if (dir === 'declining') return `<span style="color:var(--accent-red);font-size:${s};font-weight:800;">↘</span>`;
  return `<span style="color:var(--text-muted);font-size:${s};">→</span>`;
}

function trendLabel(dir) {
  if (dir === 'improving') return `<span style="color:var(--accent-green);font-weight:600;">${_t('Improving')}</span>`;
  if (dir === 'declining') return `<span style="color:var(--accent-red);font-weight:600;">${_t('Declining')}</span>`;
  return `<span style="color:var(--text-muted);">${_t('Stable')}</span>`;
}

function renderHospitalProfile(drill, trend) {
  const el = document.getElementById('smart-hospital-profile');
  if (!el) return;
  const meta = drill.metadata || {};
  const score = drill.anomaly?.anomaly_score;
  const severity = drill.anomaly?.severity || 'normal';
  const sevColor = severity === 'critical' ? 'var(--accent-red)' : severity === 'warning' ? 'var(--accent-orange)' : 'var(--accent-green)';

  // Compute trend
  const td = computeTrendDirection(trend || {});
  const overallColor = td.overall === 'improving' ? 'var(--accent-green)' : td.overall === 'declining' ? 'var(--accent-red)' : 'var(--text-muted)';
  const recentColor = td.recent === 'improving' ? 'var(--accent-green)' : td.recent === 'declining' ? 'var(--accent-red)' : 'var(--text-muted)';

  el.style.display = 'block';
  el.innerHTML = `
    <div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap;">
      <div style="font-size:1.1rem;font-weight:700;color:var(--text-primary);">${_smartEscapeHtml(drill.hospital_name)}</div>
      <span style="padding:2px 10px;border-radius:12px;font-size:0.75rem;font-weight:600;color:#fff;background:${sevColor};">${_t(severity)}</span>
      ${score != null ? `<span style="font-size:0.8rem;color:var(--text-muted);">Score: ${_fmtNum(score, 3)}</span>` : ''}
    </div>
    <div style="display:flex;gap:1rem;flex-wrap:wrap;margin-top:0.5rem;font-size:0.8rem;color:var(--text-secondary);">
      ${meta.governorate ? `<span>📍 ${_smartEscapeHtml(meta.governorate)}</span>` : ''}
      ${meta.hospital_type ? `<span>🏥 ${_smartEscapeHtml(meta.hospital_type)}</span>` : ''}
      ${meta.facility_ownership ? `<span>🏢 ${_smartEscapeHtml(meta.facility_ownership)}</span>` : ''}
      ${meta.facility_type ? `<span>🏗️ ${_smartEscapeHtml(meta.facility_type)}</span>` : ''}
      ${meta.organisation_unit_id ? `<span style="color:var(--text-muted);">ID: ${meta.organisation_unit_id}</span>` : ''}
    </div>
    <!-- Trend arrows -->
    <div style="display:flex;gap:1.5rem;flex-wrap:wrap;margin-top:0.6rem;padding:0.5rem 0.7rem;background:var(--bg-surface);border-radius:8px;border:1px solid var(--border-default);">
      <div style="display:flex;align-items:center;gap:0.4rem;">
        ${trendArrow(td.overall, '1.2rem')}
        <div>
          <div style="font-size:0.68rem;color:var(--text-muted);line-height:1;">${_t('Overall Trend')}</div>
          <div style="font-size:0.82rem;line-height:1.2;">${trendLabel(td.overall)}</div>
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:0.4rem;">
        ${trendArrow(td.recent, '1.2rem')}
        <div>
          <div style="font-size:0.68rem;color:var(--text-muted);line-height:1;">${_t('Recent (3 mo)')}</div>
          <div style="font-size:0.82rem;line-height:1.2;">${trendLabel(td.recent)}</div>
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:0.4rem;">
        <div style="font-size:0.8rem;">${td.overallDelta >= 0 ? '📈' : '📉'}</div>
        <div>
          <div style="font-size:0.68rem;color:var(--text-muted);line-height:1;">${_t('Score Change')}</div>
          <div style="font-size:0.82rem;line-height:1.2;color:${overallColor};">${td.overallDelta >= 0 ? '+' : ''}${_fmtNum(td.overallDelta, 3)}</div>
        </div>
      </div>
    </div>
  `;
}

function renderHospitalGauges(drill) {
  const el = document.getElementById('smart-hospital-gauges');
  if (!el) return;
  const q = drill.quality || {};
  const c = drill.confidence;
  if (!q.score && c == null) { el.style.display = 'none'; return; }
  el.style.display = 'grid';
  const tc = getThemeColors();
  const items = [];
  if (q.score != null) items.push({ label: _t('Quality'), value: q.score, max: 100, color: tc.blue });
  if (c != null) items.push({ label: _t('Confidence'), value: c, max: 100, color: tc.teal });
  if (q.completeness != null) items.push({ label: _t('Completeness'), value: q.completeness, max: 100, color: tc.green });
  if (q.consistency != null) items.push({ label: _t('Consistency'), value: q.consistency, max: 100, color: tc.orange });
  if (q.rule_compliance != null) items.push({ label: _t('Rule Compliance'), value: q.rule_compliance, max: 100, color: tc.purple });
  el.innerHTML = items.map(it => {
    const pct = Math.min(100, Math.max(0, it.value));
    const barColor = pct >= 80 ? tc.green : pct >= 60 ? tc.orange : tc.red;
    return `<div style="background:var(--bg-surface);border-radius:8px;padding:0.6rem 0.8rem;border:1px solid var(--border-default);">
      <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:0.2rem;">${it.label}</div>
      <div style="font-size:1.1rem;font-weight:700;color:var(--text-primary);">${_fmtNum(it.value, 1)}%</div>
      <div style="height:4px;background:var(--bg-elevated);border-radius:2px;margin-top:0.3rem;overflow:hidden;">
        <div style="height:100%;width:${pct}%;background:${barColor};border-radius:2px;transition:width 0.5s ease;"></div>
      </div>
    </div>`;
  }).join('');
}

function renderConfidenceGauge(drill, trend) {
  const el = document.getElementById('smart-hospital-confidence-gauge');
  if (!el) return;

  // Compute composite confidence from multiple signals
  const q = drill.quality || {};
  const conf = drill.confidence;
  const months = (trend.trend || []).length;
  const anomalies = trend.trend || [];
  const indicators = drill.indicators || [];
  const peerAvg = drill.peer_comparison?.peer_avg_anomaly;
  const myScore = drill.anomaly?.anomaly_score;

  // Factor 1: data completeness (0–30)
  const completeness = q.completeness != null ? (q.completeness / 100) * 30 : 0;
  // Factor 2: months of data (0–25), capped at 6 months = max
  const monthScore = Math.min(25, (months / 6) * 25);
  // Factor 3: has confidence score (0–20)
  const confScore = conf != null ? (conf / 100) * 20 : 0;
  // Factor 4: indicator count sufficiency (0–15)
  const indicatorScore = Math.min(15, (indicators.length / 10) * 15);
  // Factor 5: peer comparison available (0–10)
  const peerScore = peerAvg != null && myScore != null ? 10 : 0;
  // Factor 6: consistency across months (0–10)
  let consistencyScore = 0;
  if (anomalies.length >= 2) {
    const stdDev = Math.sqrt(anomalies.reduce((s, a) => s + Math.pow(a.anomaly_score - (anomalies.reduce((s2, a2) => s2 + a2.anomaly_score, 0) / anomalies.length), 2), 0) / anomalies.length);
    consistencyScore = stdDev < 0.15 ? 10 : stdDev < 0.25 ? 6 : 3;
  }

  const total = Math.round(completeness + monthScore + confScore + indicatorScore + peerScore + consistencyScore);
  const clamped = Math.max(0, Math.min(100, total));

  // Classify
  const tc = getThemeColors();
  let level, label, color, arcColor;
  if (clamped >= 70) {
    level = 'high'; label = _t('High Confidence'); color = tc.green; arcColor = tc.green;
  } else if (clamped >= 40) {
    level = 'medium'; label = _t('Medium Confidence'); color = tc.orange; arcColor = tc.orange;
  } else {
    level = 'low'; label = _t('Low Confidence'); color = tc.red; arcColor = tc.red;
  }

  // SVG semicircular gauge
  const w = 160, h = 100, cx = w / 2, cy = h - 10, r = 65;
  // Arc from 180° (left) to 0° (right) — 180 degrees
  const needleAngle = 180 - (clamped / 100) * 180; // degrees from positive x-axis
  const needleRad = (needleAngle * Math.PI) / 180;
  const nx = cx + r * Math.cos(needleRad);
  const ny = cy - r * Math.sin(needleRad);

  // Colored arc segments (3 zones: red → orange → green)
  function arcPath(startDeg, endDeg) {
    const s = (startDeg * Math.PI) / 180;
    const e = (endDeg * Math.PI) / 180;
    const sx = cx + r * Math.cos(s);
    const sy = cy - r * Math.sin(s);
    const ex = cx + r * Math.cos(e);
    const ey = cy - r * Math.sin(e);
    const largeArc = endDeg - startDeg > 180 ? 1 : 0;
    return `M ${sx} ${sy} A ${r} ${r} 0 ${largeArc} 0 ${ex} ${ey}`;
  }

  // Draw the 3 colored zones
  const zoneW = 60; // degrees per zone
  const zones = [
    { start: 180, end: 120, color: tc.red, label: _t('Low') },
    { start: 120, end: 60,  color: tc.orange, label: _t('Medium') },
    { start: 60,  end: 0,   color: tc.green, label: _t('High') },
  ];

  el.style.display = 'block';
  el.innerHTML = `
    <div style="display:flex;flex-direction:column;align-items:center;">
      <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
        <!-- Zone arcs -->
        ${zones.map(z => `<path d="${arcPath(z.start, z.end)}" fill="none" stroke="${z.color}" stroke-width="12" stroke-linecap="round" opacity="0.25"/>`).join('')}
        <!-- Active filled arc from left to needle position -->
        <path d="${arcPath(180, needleAngle)}" fill="none" stroke="${arcColor}" stroke-width="12" stroke-linecap="round"/>
        <!-- Needle -->
        <line x1="${cx}" y1="${cy}" x2="${nx}" y2="${ny}" stroke="var(--text-primary)" stroke-width="2.5" stroke-linecap="round"/>
        <circle cx="${cx}" cy="${cy}" r="5" fill="var(--text-primary)"/>
        <circle cx="${nx}" cy="${ny}" r="3" fill="${arcColor}"/>
        <!-- Zone labels -->
        ${zones.map(z => {
          const mid = ((z.start + z.end) / 2 * Math.PI) / 180;
          const lx = cx + (r + 14) * Math.cos(mid);
          const ly = cy - (r + 14) * Math.sin(mid);
          return `<text x="${lx}" y="${ly}" text-anchor="middle" font-size="8" fill="var(--text-muted)" dominant-baseline="middle">${z.label}</text>`;
        }).join('')}
      </svg>
      <div style="text-align:center;margin-top:-0.3rem;">
        <div style="font-size:1.4rem;font-weight:800;color:${color};">${clamped}%</div>
        <div style="font-size:0.78rem;font-weight:600;color:${color};">${label}</div>
      </div>
    </div>
  `;
}

export function renderTrend(trend) {
  const tc = getThemeColors();
  const months = trend.trend.map(t => t.month);
  const scores = trend.trend.map(t => t.anomaly_score);
  const colors = trend.trend.map(t => t.severity === 'critical' ? tc.red : t.severity === 'warning' ? tc.orange : tc.green);
  renderPlot('smart-hospital-trend', [{
    x: months, y: scores, type: 'scatter', mode: 'lines+markers',
    line: { color: tc.purple, width: 2.5 }, marker: { color: colors, size: 8 },
    text: trend.trend.map(t => _t(t.severity)),
  }], { title: { text: _t('Anomaly score over time'), font: { color: tc.textPrimary, size: 13 } }, yaxis: { range: [0, 1] }, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)' });
}

export function renderHospitalForecast(forecast) {
  const c = document.getElementById('smart-hospital-forecast');
  if (!c) return;
  const forecasts = forecast.forecasts || forecast.forecast || [];
  if (!forecasts.length) { c.innerHTML = `<div class="smart-empty-state">${_t('No forecast available')}</div>`; return; }
  c.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
    <th>${_t('Month')}</th><th>${_t('Predicted score')}</th><th>${_t('Range')}</th></tr></thead><tbody>` +
    forecasts.map(f => `<tr><td>${_smartEscapeHtml(f.month)}</td>
      <td>${_fmtNum(f.prediction, 3)}</td>
      <td style="font-size:0.75rem;">${_fmtNum(f.lower, 3)} – ${_fmtNum(f.upper, 3)}</td></tr>`).join('') +
    `</tbody></table></div>`;
}

function renderHospitalIndicators(indicators) {
  const c = document.getElementById('smart-hospital-indicators');
  if (!c || !indicators.length) { if (c) c.innerHTML = ''; return; }
  c.innerHTML = `<div style="font-size:0.85rem;font-weight:600;color:var(--text-primary);margin-bottom:0.4rem;">📊 ${_t('Clinical Indicators')}</div>
  <div class="smart-table-wrap"><table><thead><tr>
    <th>${_t('Indicator')}</th><th>${_t('Value')}</th><th>${_t('Peer Avg')}</th><th>${_t('vs Peers')}</th></tr></thead><tbody>` +
    indicators.map(ind => {
      const val = ind.value != null ? _fmtNum(ind.value, 3) : '—';
      const peer = ind.peer_avg != null ? _fmtNum(ind.peer_avg, 3) : '—';
      let diff = '';
      if (ind.value != null && ind.peer_avg != null) {
        const d = ind.value - ind.peer_avg;
        const pct = ind.peer_avg !== 0 ? ((d / ind.peer_avg) * 100).toFixed(1) : '—';
        const color = d > 0 ? 'var(--accent-red)' : d < 0 ? 'var(--accent-green)' : 'var(--text-muted)';
        const arrow = d > 0 ? '↑' : d < 0 ? '↓' : '→';
        diff = `<span style="color:${color};font-weight:600;">${arrow} ${pct}%</span>`;
      }
      return `<tr><td>${_smartEscapeHtml(ind.indicator_name)}</td><td>${val}</td><td>${peer}</td><td>${diff}</td></tr>`;
    }).join('') +
    `</tbody></table></div>`;
}

function renderHospitalPeers(peers, anomaly) {
  const c = document.getElementById('smart-hospital-peers');
  if (!c) return;
  if (!peers.peer_count) { c.innerHTML = ''; return; }
  const tc = getThemeColors();
  const myScore = anomaly?.anomaly_score ?? null;
  const peerAvg = peers.peer_avg_anomaly;
  let barHtml = '';
  if (myScore != null && peerAvg != null) {
    const maxW = 300;
    const myW = Math.round(myScore * maxW);
    const peerW = Math.round(peerAvg * maxW);
    barHtml = `<div style="margin-top:0.5rem;">
      <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.3rem;">
        <span style="font-size:0.72rem;color:var(--text-muted);width:80px;">${_t('This Hospital')}</span>
        <div style="height:14px;background:var(--bg-elevated);border-radius:3px;flex:1;max-width:${maxW}px;">
          <div style="height:100%;width:${myW}px;background:${tc.blue};border-radius:3px;transition:width 0.5s;"></div>
        </div>
        <span style="font-size:0.75rem;font-weight:600;">${_fmtNum(myScore, 3)}</span>
      </div>
      <div style="display:flex;align-items:center;gap:0.5rem;">
        <span style="font-size:0.72rem;color:var(--text-muted);width:80px;">${_t('Peer Average')}</span>
        <div style="height:14px;background:var(--bg-elevated);border-radius:3px;flex:1;max-width:${maxW}px;">
          <div style="height:100%;width:${peerW}px;background:${tc.orange};border-radius:3px;transition:width 0.5s;"></div>
        </div>
        <span style="font-size:0.75rem;font-weight:600;">${_fmtNum(peerAvg, 3)}</span>
      </div>
    </div>`;
  }
  c.innerHTML = `<div style="font-size:0.85rem;font-weight:600;color:var(--text-primary);margin-bottom:0.3rem;">👥 ${_t('Peer Comparison')}</div>
    <div style="font-size:0.78rem;color:var(--text-secondary);margin-bottom:0.3rem;">${peers.peer_count} ${_t('peers in same group')}</div>
    ${barHtml}`;
}

function renderHospitalLagTimeline(lagData, indicators) {
  const c = document.getElementById('smart-hospital-lag');
  if (!c) return;
  const lags = lagData.lags || lagData.all_lags || [];
  if (!lags.length) { c.innerHTML = ''; return; }

  // Build node list from indicators involved in lags
  const nodeMap = new Map();
  lags.forEach(f => {
    const aKey = f.indicator_a || f.indicator_a_ar || '';
    const bKey = f.indicator_b || f.indicator_b_ar || '';
    if (aKey && !nodeMap.has(aKey)) nodeMap.set(aKey, {
      label: f.indicator_a_ar || f.indicator_a || aKey,
      code: aKey,
    });
    if (bKey && !nodeMap.has(bKey)) nodeMap.set(bKey, {
      label: f.indicator_b_ar || f.indicator_b || bKey,
      code: bKey,
    });
  });
  const nodes = Array.from(nodeMap.values());
  if (!nodes.length) { c.innerHTML = ''; return; }

  // Layout: arrange nodes horizontally with spacing
  const svgW = Math.max(500, nodes.length * 110);
  const svgH = 200;
  const nodeY = svgH / 2 + 10;
  const nodeSpacing = svgW / (nodes.length + 1);
  const nodePositions = {};
  nodes.forEach((n, i) => {
    nodePositions[n.code] = { x: nodeSpacing * (i + 1), y: nodeY };
  });

  // Draw SVG: nodes + lag arrows
  const tc = getThemeColors();
  const textPrimary = tc.textPrimary;
  const bgSurface = tc.bgSurface;
  const borderDef = tc.borderDefault;

  function shortenName(name, maxLen) {
    if (name.length <= maxLen) return name;
    return name.substring(0, maxLen - 2) + '…';
  }

  // Arrow paths
  const arrowsHtml = lags.map((f, idx) => {
    const aPos = nodePositions[f.indicator_a];
    const bPos = nodePositions[f.indicator_b];
    if (!aPos || !bPos) return '';
    const isPos = f.direction === 'positive';
    const arrowColor = isPos ? tc.blue : tc.red;
    const strength = f.strength || 'weak';
    const strokeW = strength === 'strong' ? 3 : strength === 'moderate' ? 2 : 1.5;
    const dashArr = strength === 'weak' ? '6,4' : 'none';
    const r = f.lag_pearson || f.correlation || 0;
    // Curved path between nodes
    const x1 = aPos.x + 35, y1 = aPos.y;
    const x2 = bPos.x - 35, y2 = bPos.y;
    const midX = (x1 + x2) / 2;
    const curveY = y1 - 20 - (idx % 3) * 15; // stagger curves
    const path = `M ${x1} ${y1} Q ${midX} ${curveY} ${x2} ${y2}`;
    // Arrowhead
    const angle = Math.atan2(y2 - curveY, x2 - midX);
    const ahLen = 8;
    const ahx = x2 - ahLen * Math.cos(angle - 0.3);
    const ahy = y2 - ahLen * Math.sin(angle - 0.3);
    const ahx2 = x2 - ahLen * Math.cos(angle + 0.3);
    const ahy2 = y2 - ahLen * Math.sin(angle + 0.3);
    // Label
    const labelX = midX;
    const labelY = curveY - 6;
    const confBadge = f.confidence === 'high' ? '🟢' : f.confidence === 'medium' ? '🟡' : '🔴';
    const lagText = `${f.lag}m`;
    return `
      <path d="${path}" fill="none" stroke="${arrowColor}" stroke-width="${strokeW}" stroke-dasharray="${dashArr}" opacity="0.8"/>
      <polygon points="${x2},${y2} ${ahx},${ahy} ${ahx2},${ahy2}" fill="${arrowColor}" opacity="0.8"/>
      <rect x="${labelX - 30}" y="${labelY - 10}" width="60" height="18" rx="9" fill="${bgSurface}" stroke="${borderDef}" stroke-width="1"/>
      <text x="${labelX}" y="${labelY + 3}" text-anchor="middle" font-size="9" font-weight="600" fill="${arrowColor}">
        r=${_fmtNum(r, 2)} · ${lagText} ${confBadge}
      </text>
    `;
  }).join('');

  // Store lags data globally for modal access
  window._currentLagData = lags;

  // Nodes
  const nodesHtml = nodes.map(n => {
    const pos = nodePositions[n.code];
    const isLeader = lags.some(f => f.indicator_a === n.code);
    const isFollower = lags.some(f => f.indicator_b === n.code);
    const borderColor = isLeader ? tc.blue : isFollower ? tc.red : borderDef;
    const bgColor = isLeader ? 'rgba(79,140,255,0.08)' : isFollower ? 'rgba(248,113,113,0.08)' : bgSurface;
    const escapedCode = n.code.replace(/'/g, "\\'").replace(/"/g, '&quot;');
    const escapedLabel = n.label.replace(/'/g, "\\'").replace(/"/g, '&quot;');
    return `
      <g onclick="window.showLagDetailModal('${escapedCode}', '${escapedLabel}')" style="cursor:pointer;">
        <rect x="${pos.x - 35}" y="${pos.y - 18}" width="70" height="36" rx="8" fill="${bgColor}" stroke="${borderColor}" stroke-width="1.5"/>
        <text x="${pos.x}" y="${pos.y + 1}" text-anchor="middle" font-size="8" font-weight="600" fill="${textPrimary}" style="pointer-events:none;">
          ${shortenName(n.label, 10)}
        </text>
      </g>
    `;
  }).join('');

  // Legend
  const legendHtml = `
    <div style="display:flex;gap:1rem;flex-wrap:wrap;margin-top:0.5rem;font-size:0.72rem;color:var(--text-muted);">
      <span>🔵 → ${_t('Positive lag')}</span>
      <span>🔴 → ${_t('Negative lag')}</span>
      <span>── ${_t('Strong (r≥0.6)')}</span>
      <span>╌╌ ${_t('Weak (r<0.4)')}</span>
      <span>🟢 ${_t('High confidence')}</span>
      <span>🟡 ${_t('Medium')}</span>
      <span>🔴 ${_t('Low')}</span>
    </div>
  `;

  // Add lag modal container if not exists
  let lagModal = document.getElementById('lag-detail-modal');
  if (!lagModal) {
    lagModal = document.createElement('div');
    lagModal.id = 'lag-detail-modal';
    lagModal.className = 'modal-overlay';
    lagModal.style.cssText = 'display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.45);z-index:1100;align-items:center;justify-content:center;';
    document.body.appendChild(lagModal);
  }

  c.innerHTML = `
    <div style="font-size:0.85rem;font-weight:600;color:var(--text-primary);margin-bottom:0.4rem;">⏱️ ${_t('Lag Relationships Timeline')}</div>
    <div style="overflow-x:auto;padding:0.5rem 0;">
      <svg width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}" style="display:block;">
        <line x1="20" y1="${svgH - 15}" x2="${svgW - 20}" y2="${svgH - 15}" stroke="${borderDef}" stroke-width="1"/>
        <text x="${svgW / 2}" y="${svgH - 3}" text-anchor="middle" font-size="8" fill="var(--text-muted)">
          ${_t('Leading')} ← ${_t('time')} → ${_t('Lagging')}
        </text>
        ${arrowsHtml}
        ${nodesHtml}
      </svg>
    </div>
    ${legendHtml}
    <div style="margin-top:0.4rem;font-size:0.72rem;color:var(--text-muted);font-style:italic;">
      ${_t('Click any indicator node to view detailed lag analysis.')}<br/>
      ${_t('Arrows show indicator A leading indicator B by the indicated lag. Thickness = correlation strength.')}
    </div>
  `;
}

window.showLagDetailModal = function(indicatorCode, indicatorLabel) {
  const lags = window._currentLagData || [];
  if (!lags.length) return;

  // Find all relationships involving this indicator
  const outgoing = lags.filter(f => f.indicator_a === indicatorCode);
  const incoming = lags.filter(f => f.indicator_b === indicatorCode);
  const total = outgoing.length + incoming.length;
  if (!total) return;

  const tc = getThemeColors();

  function renderRelationship(f, type) {
    const isPos = f.direction === 'positive';
    const r = f.lag_pearson || f.correlation || 0;
    const absR = Math.abs(r);
    const strengthColor = absR >= 0.6 ? tc.green : absR >= 0.4 ? tc.orange : tc.red;
    const confColor = f.confidence === 'high' ? tc.green : f.confidence === 'medium' ? tc.orange : tc.red;
    const confLabel = f.confidence === 'high' ? _t('High') : f.confidence === 'medium' ? _t('Medium') : _t('Low');
    const dirIcon = isPos ? '📈' : '📉';
    const dirColor = isPos ? tc.green : tc.red;
    const otherName = type === 'outgoing' ? (f.indicator_b_ar || f.indicator_b) : (f.indicator_a_ar || f.indicator_a);
    const otherCode = type === 'outgoing' ? f.indicator_b : f.indicator_a;
    const arrowDir = type === 'outgoing' ? '→' : '←';
    const strengthLabel = absR >= 0.6 ? _t('Strong') : absR >= 0.4 ? _t('Moderate') : _t('Weak');

    return `
      <div style="background:${tc.bgElevated};border:1px solid ${tc.borderDefault};border-radius:8px;padding:0.7rem 0.8rem;margin-bottom:0.5rem;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.4rem;">
          <div style="display:flex;align-items:center;gap:0.5rem;">
            <span style="font-size:1rem;">${type === 'outgoing' ? '📤' : '📥'}</span>
            <span style="font-size:0.78rem;font-weight:600;color:${tc.textPrimary};">${_smartEscapeHtml(otherName)}</span>
          </div>
          <span style="font-size:0.75rem;color:${tc.textMuted};">${_smartEscapeHtml(otherCode)}</span>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:0.5rem;">
          <span style="font-size:0.72rem;background:${tc.bgInput};padding:0.2rem 0.5rem;border-radius:4px;color:${dirColor};font-weight:600;">
            ${dirIcon} ${arrowDir} ${isPos ? _t('Positive') : _t('Negative')}
          </span>
          <span style="font-size:0.72rem;background:${tc.bgInput};padding:0.2rem 0.5rem;border-radius:4px;color:${strengthColor};font-weight:600;">
            r=${_fmtNum(r, 2)} · ${strengthLabel}
          </span>
          <span style="font-size:0.72rem;background:${tc.bgInput};padding:0.2rem 0.5rem;border-radius:4px;color:${tc.accentBlue};font-weight:600;">
            ⏱ ${f.lag} ${_t('months')}
          </span>
          <span style="font-size:0.72rem;background:${tc.bgInput};padding:0.2rem 0.5rem;border-radius:4px;color:${confColor};font-weight:600;">
            🎯 ${confLabel} ${_t('confidence')}
          </span>
        </div>
      </div>
    `;
  }

  const outgoingHtml = outgoing.length ? `
    <div style="margin-top:0.6rem;">
      <div style="font-size:0.78rem;font-weight:600;color:${tc.blue};margin-bottom:0.4rem;">📤 ${_t('Leads (causes changes in)')}</div>
      ${outgoing.map(f => renderRelationship(f, 'outgoing')).join('')}
    </div>
  ` : '';

  const incomingHtml = incoming.length ? `
    <div style="margin-top:0.6rem;">
      <div style="font-size:0.78rem;font-weight:600;color:${tc.red};margin-bottom:0.4rem;">📥 ${_t('Lagged by (affected by)')}</div>
      ${incoming.map(f => renderRelationship(f, 'incoming')).join('')}
    </div>
  ` : '';

  // Summary stats
  const avgAbsR = total > 0 ? outgoing.concat(incoming).reduce((s, f) => s + Math.abs(f.lag_pearson || f.correlation || 0), 0) / total : 0;
  const avgLag = total > 0 ? outgoing.concat(incoming).reduce((s, f) => s + (f.lag || 0), 0) / total : 0;
  const highConf = outgoing.concat(incoming).filter(f => f.confidence === 'high').length;

  const modal = document.getElementById('lag-detail-modal');
  modal.innerHTML = `
    <div style="background:${tc.bgSurface};border-radius:12px;padding:1.2rem;max-width:520px;width:92%;max-height:80vh;overflow-y:auto;box-shadow:0 8px 32px rgba(0,0,0,0.25);">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.8rem;">
        <div style="display:flex;align-items:center;gap:0.5rem;">
          <span style="font-size:1.1rem;">⏱️</span>
          <span style="font-size:0.95rem;font-weight:700;color:${tc.textPrimary};">${_smartEscapeHtml(indicatorLabel)}</span>
        </div>
        <button onclick="document.getElementById('lag-detail-modal').style.display='none'" style="background:none;border:none;font-size:1.2rem;cursor:pointer;color:${tc.textMuted};padding:0.2rem;">✕</button>
      </div>
      <div style="font-size:0.75rem;color:${tc.textMuted};margin-bottom:0.8rem;">${_smartEscapeHtml(indicatorCode)}</div>

      <div style="display:flex;gap:0.6rem;margin-bottom:0.8rem;flex-wrap:wrap;">
        <div style="background:${tc.bgInput};border-radius:6px;padding:0.4rem 0.7rem;text-align:center;min-width:80px;">
          <div style="font-size:0.65rem;color:${tc.textMuted};">${_t('Relationships')}</div>
          <div style="font-size:1.1rem;font-weight:700;color:${tc.textPrimary};">${total}</div>
        </div>
        <div style="background:${tc.bgInput};border-radius:6px;padding:0.4rem 0.7rem;text-align:center;min-width:80px;">
          <div style="font-size:0.65rem;color:${tc.textMuted};">${_t('Avg |r|')}</div>
          <div style="font-size:1.1rem;font-weight:700;color:${tc.textPrimary};">${_fmtNum(avgAbsR, 2)}</div>
        </div>
        <div style="background:${tc.bgInput};border-radius:6px;padding:0.4rem 0.7rem;text-align:center;min-width:80px;">
          <div style="font-size:0.65rem;color:${tc.textMuted};">${_t('Avg Lag')}</div>
          <div style="font-size:1.1rem;font-weight:700;color:${tc.textPrimary};">${_fmtNum(avgLag, 1)}m</div>
        </div>
        <div style="background:${tc.bgInput};border-radius:6px;padding:0.4rem 0.7rem;text-align:center;min-width:80px;">
          <div style="font-size:0.65rem;color:${tc.textMuted};">${_t('High Conf.')}</div>
          <div style="font-size:1.1rem;font-weight:700;color:${highConf > 0 ? tc.green : tc.textMuted};">${highConf}/${total}</div>
        </div>
      </div>

      ${outgoingHtml}
      ${incomingHtml}

      <div style="margin-top:0.8rem;padding-top:0.5rem;border-top:1px solid ${tc.borderDefault};font-size:0.7rem;color:${tc.textMuted};font-style:italic;">
        ${_t('Granger causality and FDR-corrected. Click arrow labels on the timeline for correlation details.')}
      </div>
    </div>
  `;
  modal.style.display = 'flex';

  // Close on backdrop click
  modal.onclick = function(e) {
    if (e.target === modal) modal.style.display = 'none';
  };
};

export function renderHospitalFactors(anomaly, explanation, containerId) {
  const c = document.getElementById(containerId || 'smart-hospital-factors');
  if (!c) return;
  const factors = explanation?.top_factors || [];
  c.innerHTML = `<div class="smart-table-wrap"><table><thead><tr>
    <th>${_t('Factor')}</th><th>${_t('Value')}</th><th>${_t('SHAP')}</th></tr></thead><tbody>` +
    factors.map(f => `<tr><td>${_smartEscapeHtml(smartTranslateFeature(f.feature))}</td>
      <td>${_fmtNum(f.value, 3)}</td><td>${_fmtNum(f.shap_value, 3)}</td></tr>`).join('') +
    `</tbody></table></div>`;
  if (factors.length) renderWaterfall('smart-shap-waterfall', factors);
}

export function openDrilldown(hospitalId) {
  const month = smartState.month || '';
  const modal = document.getElementById('smart-drilldown-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  // Show loading state immediately
  const nameEl = document.getElementById('smart-drilldown-name');
  const textEl = document.getElementById('smart-drilldown-text');
  const factorsEl = document.getElementById('smart-drilldown-factors');
  const trendEl = document.getElementById('smart-trend-line');
  if (nameEl) nameEl.textContent = hospitalId;
  if (textEl) textEl.innerHTML = '<div style="text-align:center;padding:1.5rem;"><div class="spinner spinner-lg" style="margin:0 auto 0.5rem;display:block;"></div><span style="color:var(--accent-blue);">' + (_t('Loading analysis...') || 'Loading analysis...') + '</span></div>';
  if (factorsEl) factorsEl.innerHTML = '';
  if (trendEl) trendEl.innerHTML = '';
  apiSmartGet(`/smart/drilldown/${hospitalId}/${month}`).then(d => {
    if (d.empty || !d.anomaly) {
      document.getElementById('smart-drilldown-name').textContent = d.hospital_name || hospitalId;
      document.getElementById('smart-drilldown-text').textContent = d.message || _t('No data');
      return;
    }
    document.getElementById('smart-drilldown-name').textContent = d.hospital_name;
    document.getElementById('smart-drilldown-text').textContent = d.explanation?.text_ar || d.explanation?.text || '';
    const residuals = d.residuals || [];
    const _tc = getThemeColors();
    if (residuals.length) renderPlot('smart-trend-line', [{
      x: residuals.map(r => r.month), y: residuals.map(r => r.residual),
      type: 'bar', marker: { color: residuals.map(r => r.residual > 0 ? _tc.red : _tc.blue) },
    }], { title: { text: _t('Monthly residuals'), font: { color: _tc.textPrimary, size: 13 } }, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)' });
    renderHospitalFactors(d.anomaly, d.explanation, 'smart-drilldown-factors');
  }).catch(e => {
    document.getElementById('smart-drilldown-text').textContent = e.message;
  });
}

export function goRootCause(hospitalId, month) {
  // Root-cause navigation: switch to hospital mode and load the hospital.
  const btn = document.querySelector('.smart-mode-btn[data-smart-mode="hospital"]');
  if (btn) btn.click();
  const select = document.getElementById('smart-hospital-context-select');
  if (select && select.querySelector(`option[value="${hospitalId}"]`)) {
    select.value = String(hospitalId);
    select.dispatchEvent(new Event('change'));
  }
}

// Exposed for inline onclick attributes (kept for backward compatibility).
window.smartDrilldown = openDrilldown;
window.smartGoRootCause = goRootCause;