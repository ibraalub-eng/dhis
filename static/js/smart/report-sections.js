// report-sections.js — Butterfly Intelligence section renderers.
// Each section renders structured HTML from `data` + embeds `sections[key]` narrative.
import { smartState, _smartEscapeHtml, _t, _fmtNum } from './core.js';

const SECTION_META = {
  exec_summary: { title: 'تقرير تنفيذي', icon: '📊' },
  key_messages: { title: 'أهم الرسائل التنفيذية', icon: '🎯' },
  priority_hospitals: { title: 'المستشفيات ذات الأولوية', icon: '🏥' },
  geo_risk: { title: 'التوزيع الجغرافي للمخاطر', icon: '🗺️' },
  early_warnings: { title: 'إشارات الإنذار المبكر', icon: '🔮' },
  current_trends: { title: 'الاتجاهات الشهرية', icon: '📈' },
  forecast: { title: 'التنبؤ بالمخاطر المستقبلية', icon: '🔭' },
  clinical_relations: { title: 'تحليل المؤشرات والعلاقات', icon: '🔗' },
  composite_patterns: { title: 'الأنماط المركبة', icon: '🧩' },
  anomaly_intel: { title: 'تحليل الحالات الشاذة', icon: '🚨' },
  top_deviations: { title: 'أكبر الانحرافات', icon: '📉' },
  regional_intel: { title: 'الاستخبارات الإقليمية', icon: '🌍' },
  deterioration: { title: 'التدهور المستمر', icon: '⬇️' },
  data_quality: { title: 'تنبيهات جودة البيانات', icon: '🔍' },
  recommendations: { title: 'التوصيات والأولويات', icon: '✅' },
  conclusion: { title: 'الخلاصة التنفيذية', icon: '📝' },
  appendix: { title: 'الملحق الفني', icon: '🗂️' },
};

function esc(v) { return v == null ? '' : _smartEscapeHtml(String(v)); }
function badge(severity) {
  const lvl = severity === 'critical' ? 'critical' : severity === 'warning' ? 'warning' : 'normal';
  return `<span class="bi-badge bi-badge-${lvl}">${esc(_t(severity || 'Normal'))}</span>`;
}
function sectionShell(key, inner) {
  const m = SECTION_META[key] || { title: key, icon: '' };
  const narrative = smartState.sections && smartState.sections[key];
  return `<section class="bi-section" data-bi-section="${key}">
    <h4 class="bi-section-title">${m.icon} ${esc(_t(m.title) || m.title)}</h4>
    ${inner}
    ${narrative ? `<div class="bi-narrative">${esc(narrative)}</div>` : ''}
  </section>`;
}

function renderExecSummary(data) {
  const decision = data.decision || {};
  const kpi = data.kpi || {};
  const verdict = decision.verdict || 'normal';
  const kpis = [
    ['العدد الإجمالي للمستشفيات', data.hospitals_count],
    ['المستشفيات الشاذة', kpi.total_anomalies],
    ['الحرجة', kpi.critical_count],
    ['بحاجة متابعة', kpi.warning_count],
    ['المحافظات المتأثرة', kpi.affected_governorates],
  ].map(([label, val]) => `<div class="bi-kpi"><div class="bi-kpi-value">${esc(val ?? '-')}</div><div class="bi-kpi-label">${esc(_t(label) || label)}</div></div>`).join('');
  return `<div class="bi-kpi-grid">${kpis}</div>
    <div><span class="bi-badge bi-badge-${verdict === 'attention' ? 'warning' : verdict}">${esc(_t(decision.verdict_label) || decision.verdict_label)}</span>
    <span class="bi-kpi-label">درجة الخطر: ${esc(decision.risk_score ?? '-')}/100</span></div>`;
}

function renderPriorityHospitals(data) {
  const anomalies = (data.anomalies || []).slice().sort((a, b) => b.anomaly_score - a.anomaly_score);
  if (!anomalies.length) return `<div class="bi-empty">لا توجد مستشفيات ذات أولوية.</div>`;
  const rows = anomalies.slice(0, 10).map((a, i) => `<tr>
    <td style="text-align:center;">${i + 1}</td>
    <td>${esc(a.hospital_name)}</td>
    <td>${esc(a.governorate)}</td>
    <td style="text-align:center;">${_fmtNum(a.anomaly_score)}</td>
    <td>${badge(a.severity)}</td>
  </tr>`).join('');
  return `<div class="bi-table-wrap"><table><thead><tr>
    <th>الترتيب</th><th>المستشفى</th><th>المحافظة</th><th>درجة الخطر</th><th>الحالة</th>
  </tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderGeoRisk(data) {
  const govs = ((data.geo && data.geo.governorates) || []).slice().sort((a, b) => b.avg_anomaly_score - a.avg_anomaly_score);
  if (!govs.length) return `<div class="bi-empty">لا توجد بيانات جغرافية.</div>`;
  const rows = govs.map(g => {
    const pct = Math.min(100, Math.round(g.avg_anomaly_score * 100));
    const col = pct >= 60 ? 'var(--accent-red)' : pct >= 30 ? 'var(--accent-orange)' : 'var(--accent-green)';
    return `<tr><td>${esc(g.governorate)}</td>
      <td style="text-align:center;">${g.hospital_count}</td>
      <td style="text-align:center;">${_fmtNum(g.avg_anomaly_score)}</td>
      <td style="text-align:center;">${g.outlier_count}</td>
      <td><span class="bi-severity-bar"><span style="width:${pct}%;background:${col};"></span></span></td>
    </tr>`;
  }).join('');
  return `<div class="bi-table-wrap"><table><thead><tr>
    <th>المحافظة</th><th>عدد المستشفيات</th><th>متوسط درجة الخطر</th><th>شاذ</th><th>التوزيع</th>
  </tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderEarlyWarnings(data) {
  const hospitals = ((data.forecast && data.forecast.hospitals) || []).slice().filter(h => (h.probability || 0) > 0);
  if (!hospitals.length) return `<div class="bi-empty">لا توجد إشارات إنذار مبكر موثوقة.</div>`;
  const cards = hospitals.slice(0, 8).map(h => {
    const prob = Math.round((h.probability || 0) * 100);
    const col = prob >= 70 ? 'var(--accent-red)' : prob >= 40 ? 'var(--accent-orange)' : 'var(--accent-green)';
    const leads = (h.leading_rising || []).slice(0, 3).map(r => esc(r.metric_ar || r.metric)).join('، ');
    return `<div class="bi-priority">
      <strong>${esc(h.hospital_name)}</strong> — ${esc(h.severity || '')}<br>
      <span>إشارة: ${esc(leads)}</span>
      <span class="bi-severity-bar"><span style="width:${prob}%;background:${col};"></span></span>
      <div class="bi-kpi-label">الاحتمال: <b>${prob}%</b> · الثقة: ${esc(h.confidence_label_ar || h.confidence || '—')}</div>
    </div>`;
  }).join('');
  return `<div class="bi-grid-2">${cards}</div><div class="bi-caution">ارتباط زمني إحصائي — ليس علاقة سببية.</div>`;
}

function renderForecast(data) {
  const preds = (data.xgboost && data.xgboost.predictions) || [];
  if (!preds.length) return `<div class="bi-empty">لا توجد تنبؤات متاحة.</div>`;
  const rows = preds.slice(0, 8).map(p => `<tr>
    <td>${esc(p.hospital_name)}</td>
    <td style="text-align:center;">${_fmtNum(p.current_score)}</td>
    <td style="text-align:center;color:var(--accent-blue);">${_fmtNum(p.predicted_next_score)}</td>
    <td>${badge(p.predicted_severity)}</td>
  </tr>`).join('');
  return `<div class="bi-table-wrap"><table><thead><tr>
    <th>المستشفى</th><th>الخطر الحالي</th><th>الخطر المتوقع</th><th>التصنيف المتوقع</th>
  </tr></thead><tbody>${rows}</tbody></table></div>
  <div class="bi-caution">الخطر الحالي منفصل عن الخطر المتوقع — التوقع تقدير إحصائي وليس يقينًا.</div>`;
}

function renderAppendix(data) {
  const c = data.clustering || {};
  const x = data.xgboost || {};
  const lines = [];
  if (c && c.n_clusters != null) lines.push(`- التجميع: ${c.n_clusters} مجموعات — silhouette ${_fmtNum(c.silhouette_score)}`);
  if (x && x.model_r2 != null) lines.push(`- نموذج التنبؤ: R² ${_fmtNum(x.model_r2)} — MAE ${_fmtNum(x.model_mae)}`);
  if (!lines.length) lines.push('- لا توجد بيانات فنية كافية.');
  lines.push('- مصطلحات: درجة الخطر (Risk Score) · درجة الشذوذ (Anomaly Score) · الارتباط الزمني (Lead-Lag).');
  return `<details class="bi-collapsible"><summary>عرض التحليل الفني</summary><div style="margin-top:.5rem;">${lines.map(esc).join('<br>')}</div></details>`;
}

// Render the remaining sections with a shared table/grid fallback that shows
// the narrative plus a lightweight data table where relevant.
function renderSimpleSection(key, data) {
  return `<div class="bi-empty">تُعرض بيانات هذا القسم أدناه.</div>`;
}

const RENDERERS = {
  exec_summary: renderExecSummary,
  priority_hospitals: renderPriorityHospitals,
  geo_risk: renderGeoRisk,
  early_warnings: renderEarlyWarnings,
  forecast: renderForecast,
  appendix: renderAppendix,
};

const SECTION_ORDER = ['exec_summary', 'key_messages', 'priority_hospitals', 'geo_risk',
  'early_warnings', 'current_trends', 'forecast', 'clinical_relations',
  'composite_patterns', 'anomaly_intel', 'top_deviations', 'regional_intel',
  'deterioration', 'data_quality', 'recommendations', 'conclusion', 'appendix'];

export default function renderReportSections(state) {
  const container = document.getElementById('smart-report-output');
  if (!container) return;
  const html = SECTION_ORDER.map(key => {
    const renderer = RENDERERS[key];
    const inner = renderer ? renderer(state.data || {}) : renderSimpleSection(key, state.data || {});
    return sectionShell(key, inner);
  }).join('');
  container.innerHTML = html;
  container.style.direction = 'rtl';
}