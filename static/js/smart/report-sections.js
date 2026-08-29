// report-sections.js — Butterfly Intelligence section renderers.
// Each section renders structured HTML from `data` + embeds `sections[key]` narrative.
import { smartState, _smartEscapeHtml, _t, _fmtNum, smartTranslateFeature } from './core.js';

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

function renderCurrentTrends(data) {
  const trends = ((data.regional && data.regional.trends) || []).filter(t => t.metric_ar);
  const dirs = trends.filter(t => t.direction === 'worsening' || t.direction === 'improving');
  const spikes = trends.filter(t => t.direction === 'spike');
  if (!dirs.length && !spikes.length) return `<div class="bi-empty">لا توجد سلاسل شهرية كافية لحساب الاتجاهات.</div>`;
  const cards = dirs.slice(0, 6).map(t => {
    const worse = t.direction === 'worsening';
    return `<div class="bi-priority">
      <strong>${esc(t.governorate)}</strong> — ${esc(t.metric_ar)}
      <span class="bi-badge ${worse ? 'bi-badge-critical' : 'bi-badge-normal'}">${worse ? 'تدهور' : 'تحسّن'} ${esc(t.slope_pct != null ? Math.abs(t.slope_pct).toFixed(1) + '%/شهر' : '')}</span><br>
      <span class="bi-kpi-label">R² = ${esc(t.r2 != null ? t.r2.toFixed(2) : '—')} · ميل ${worse ? '⬆' : '⬇'} (الانخفاض أفضل)</span>
    </div>`;
  }).join('');
  const spikeRows = spikes.slice(0, 5).map(t => `<tr>
    <td>${esc(t.governorate)}</td><td>${esc(t.metric_ar)}</td><td>${esc(t.last_value)}</td><td>${esc(t.prior_mean)}</td><td>${esc(t.spike_z)}</td>
  </tr>`).join('');
  const spikeBlock = spikeRows ? `<div class="bi-table-wrap"><table><thead><tr><th>المحافظة</th><th>المؤشر</th><th>آخر قيمة</th><th>متوسط سابق</th><th>z</th></tr></thead><tbody>${spikeRows}</tbody></table></div>` : '';
  return `<div class="bi-grid-2">${cards}</div>${spikeBlock}`;
}

function renderClinicalRelations(data) {
  const corrs = ((data.correlations && data.correlations.strong_correlations) || []).slice(0, 8);
  if (!corrs.length) return `<div class="bi-empty">لا توجد علاقات قوية بين المؤشرات.</div>`;
  const cards = corrs.map(c => {
    const r = c.pearson_r || 0;
    const col = Math.abs(r) >= 0.7 ? 'var(--accent-red)' : 'var(--accent-orange)';
    return `<div class="bi-priority" style="border-left-color:${col};">
      <strong>${esc(smartTranslateFeature(c.indicator_a))} ↔ ${esc(smartTranslateFeature(c.indicator_b))}</strong><br>
      <span>r = <b>${_fmtNum(r)}</b> · ${esc(c.strength || '')}</span>
    </div>`;
  }).join('');
  return `<div class="bi-grid-2">${cards}</div>
    <div class="bi-caution">الارتباط الإحصائي لا يثبت السببية — قد تكون الوشائج نتيجة عوامل مشتركة أو عشوائية.</div>`;
}

function renderCompositePatterns(data) {
  const patterns = (data.patterns || []).slice(0, 5);
  if (!patterns.length) return `<div class="bi-empty">لا توجد أنماط مركبة متكررة.</div>`;
  const cards = patterns.map(p => `
    <div class="bi-priority">
      <strong>${esc((p.arabic_names || []).join('، '))}</strong><br>
      <span class="bi-kpi-label">${esc(p.hospitals_count || 0)} مستشفى · الدعم ${_fmtNum((p.support || 0) * 100)}%</span><br>
      <span class="bi-badge bi-badge-warning" title="Lift مقدار تجاوز تكرار النمط عن التكرار المتوقع المستقل">Lift ${esc(p.lift != null ? p.lift.toFixed(2) : '—')}</span>
      ${esc(p.summary_ar ? ' · ' + p.summary_ar : '')}
    </div>`).join('');
  return `<div class="bi-grid-2">${cards}</div>`;
}

function renderAnomalyIntel(data) {
  const anomalies = (data.anomalies || []).slice(0, 6);
  if (!anomalies.length) return `<div class="bi-empty">لا توجد حالات شاذة.</div>`;
  const cards = anomalies.map(a => {
    const expl = (data.explanations || []).find(e => e.hospital_name === a.hospital_name);
    const factors = (expl && expl.top_factors || []).slice(0, 3).map(f => {
      const dir = f.direction === 'low' ? '▼' : '▲';
      return `<span class="bi-kpi-label">${esc(f.arabic_label || f.feature)} ${dir} ${_fmtNum(f.shap_value)}</span>`;
    }).join('<br>');
    return `<div class="bi-priority">
      <strong>${esc(a.hospital_name)}</strong> — ${esc(a.governorate || '')}<br>
      <div class="bi-kpi-label">درجة الشذوذ (Anomaly Score): <b>${_fmtNum(a.anomaly_score)}</b> ${badge(a.severity)}</div>
      <div style="margin-top:.4rem;">${esc(_t('انحراف المؤشر المفسِّر (Indicator Deviation):'))}</div>
      ${factors || `<div class="bi-empty">لا توجد عوامل تفسير متاحة.</div>`}
    </div>`;
  }).join('');
  return `<div class="bi-grid-2">${cards}</div>
    <div class="bi-caution">درجة الشذوذ الإحصائية منفصلة عن انحراف المؤشرات — لا تُخلط بينهما عند اتخاذ القرار.</div>`;
}

function renderTopDeviations(data) {
  const rowsData = (data.stratified || []).slice().sort((a, b) => Math.abs(b.deviation_pct || 0) - Math.abs(a.deviation_pct || 0)).slice(0, 5);
  if (!rowsData.length) return `<div class="bi-empty">لا توجد انحرافات كبيرة عن المستشفيات المماثلة.</div>`;
  const rows = rowsData.map(r => `<tr>
    <td>${esc(r.hospital_name)}</td>
    <td>${esc(smartTranslateFeature(r.indicator))}</td>
    <td style="text-align:center;">${_fmtNum(r.hospital_value)}</td>
    <td style="text-align:center;">${_fmtNum(r.peer_group_mean)}</td>
    <td style="text-align:center;color:${r.deviation_pct >= 0 ? 'var(--accent-red)' : 'var(--accent-green)'};">${r.deviation_pct >= 0 ? '+' : ''}${_fmtNum(r.deviation_pct)}%</td>
  </tr>`).join('');
  return `<div class="bi-table-wrap"><table><thead><tr>
    <th>المستشفى</th><th>المؤشر</th><th>القيمة</th><th>متوسط النظير</th><th>الانحراف</th>
  </tr></thead><tbody>${rows}</tbody></table></div>
  <div class="bi-caution">الانحراف عن النظير لا يُثبت خطأً إكلينيكياً — يجب التحقق من البيانات قبل الاعتماد.</div>`;
}

function renderRegionalIntel(data) {
  const govs = ((data.regional && data.regional.governorates) || []).map(g => {
    const r = (g.rates && g.rates.nmr) || {};
    return { name: g.governorate, births: g.births, nmr: r.value, risk: (data.regional.mortality || []).find(m => m.governorate === g.governorate) };
  });
  if (!govs.length) return `<div class="bi-empty">لا توجد بيانات إقليمية كافية.</div>`;
  const rows = govs.map(g => {
    const mr = g.risk;
    const lvl = mr ? mr.risk : 'low';
    const col = lvl === 'high' ? 'var(--accent-red)' : lvl === 'medium' ? 'var(--accent-orange)' : 'var(--accent-green)';
    return `<tr>
      <td>${esc(g.name)}</td>
      <td style="text-align:center;">${esc(g.births ?? '-')}</td>
      <td style="text-align:center;">${g.nmr != null ? _fmtNum(g.nmr) : '—'}</td>
      <td style="text-align:center;">${mr && mr.rate != null ? _fmtNum(mr.rate) : '—'}</td>
      <td style="text-align:center;color:${col};">${esc(mr ? (mr.risk_label_ar || mr.risk) : '—')}</td>
    </tr>`;
  }).join('');
  return `<div class="bi-table-wrap"><table><thead><tr>
    <th>المحافظة</th><th>المواليد</th><th>معدل وفيات حديثي الولادة</th><th>معدل الوفيات</th><th>مستوى الخطر</th>
  </tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderDeterioration(data) {
  const trends = ((data.regional && data.regional.trends) || []).filter(t => t.direction === 'worsening').slice(0, 5);
  if (!trends.length) return `<div class="bi-empty">لا توجد سلاسل تاريخية كافية لتقدير التدهور المستمر.</div>`;
  const rows = trends.map(t => `<tr>
    <td>${esc(t.governorate)}</td>
    <td>${esc(t.metric_ar)}</td>
    <td style="text-align:center;">${esc(Math.abs(t.slope_pct).toFixed(1))}%</td>
    <td style="text-align:center;">${esc(t.r2.toFixed(2))}</td>
    <td style="text-align:center;color:var(--accent-red);">⬆ تدهور</td>
  </tr>`).join('');
  return `<div class="bi-table-wrap"><table><thead><tr>
    <th>المحافظة</th><th>المؤشر</th><th>الميل الشهري %</th><th>R²</th><th>الاتجاه</th>
  </tr></thead><tbody>${rows}</tbody></table></div>
  <div class="bi-caution">التدهور المستمر قياس اتجاه زمني إحصائي — لا يفترض علاقة سببية مباشرة.</div>`;
}

function renderDataQuality(data) {
  const mortality = ((data.regional && data.regional.mortality) || []).filter(m => m.small_sample);
  if (!mortality.length) return `<div class="bi-empty">لا توجد تنبيهات جودة بيانات كبرى.</div>`;
  const cards = mortality.slice(0, 6).map(m => `
    <div class="bi-priority">
      <strong>${esc(m.governorate)}</strong><br>
      <span class="bi-kpi-label">${esc(m.births || 0)} مولود — حجم عينة صغير، تُفسَّر النتائج بحذر.</span>
    </div>`).join('');
  return `<div class="bi-grid-2">${cards}</div>
    <div class="bi-caution">العينات الصغيرة قد تُضخّم الانحرافات — لا تُعتمد النتائج كقرار نهائي دون بيانات أكبر.</div>`;
}

function renderRecommendations(data) {
  const prios = (data.decision && data.decision.priorities) || [];
  if (!prios.length) return `<div class="bi-empty">لا توجد أولويات إلزامية هذا الشهر.</div>`;
  const prioIcons = { critical: '🔴', high: '🟠', medium: '🟡', low: '🔵' };
  const rows = prios.slice(0, 5).map(p => `<tr>
    <td style="text-align:center;">${prioIcons[p.priority] || '⚪'}</td>
    <td>${esc(p.action)}</td>
    <td>${esc(p.target)}</td>
    <td>${badge(p.priority)}</td>
    <td style="text-align:center;">${Math.round((p.impact || 0) * 100)}%</td>
  </tr>`).join('');
  return `<div class="bi-table-wrap"><table><thead><tr>
    <th>الأولوية</th><th>الإجراء</th><th>الهدف</th><th>المستوى</th><th>الأثر</th>
  </tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderConclusion(data) {
  const decision = data.decision || {};
  const prio = (decision.priorities || [])[0];
  const verdict = decision.verdict === 'critical' ? 'وضع حرج يتطلب تدخلاً فورياً' :
    decision.verdict === 'attention' ? 'وضع يستدعي متابعة ومراجعة' : 'استقرار نسبي هذا الشهر';
  return `<div class="bi-priority">
    <strong>الوضع الحالي:</strong> ${esc(verdict)} (درجة الخطر ${esc(decision.risk_score ?? '-')}/100).
  </div>
  <div class="bi-priority">
    <strong>الخطر المستقبلي:</strong> يُرصد في قسم التنبؤ — تقدير إحصائي منفصل عن الوضع الحالي وليس يقيناً.
  </div>
  <div class="bi-priority">
    <strong>الإجراء الموصى به:</strong> ${prio ? esc(prio.action) + ' ← ' + esc(prio.target) : 'مراجعة بيانات المستشفيات ذات الأولوية وتحديث السجلات.'}
  </div>`;
}

// Render the remaining sections with a shared table/grid fallback that shows
// the narrative plus a lightweight data table where relevant.
function renderSimpleSection(key, data) {
  return `<div class="bi-empty">تُعرض بيانات هذا القسم أدناه.</div>`;
}

const RENDERERS = {
  exec_summary: renderExecSummary,
  current_trends: renderCurrentTrends,
  priority_hospitals: renderPriorityHospitals,
  geo_risk: renderGeoRisk,
  early_warnings: renderEarlyWarnings,
  clinical_relations: renderClinicalRelations,
  composite_patterns: renderCompositePatterns,
  anomaly_intel: renderAnomalyIntel,
  top_deviations: renderTopDeviations,
  regional_intel: renderRegionalIntel,
  deterioration: renderDeterioration,
  data_quality: renderDataQuality,
  forecast: renderForecast,
  recommendations: renderRecommendations,
  conclusion: renderConclusion,
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