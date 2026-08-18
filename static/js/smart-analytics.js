const SMART_COLORS = {
  normal: '#22c55e', warning: '#f59e0b', critical: '#ef4444',
  clusters: ['#3b82f6', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#06b6d4', '#84cc16'],
  noise: '#6b7280', shap_positive: '#ef4444', shap_negative: '#3b82f6',
  corr_negative: '#3b82f6', corr_zero: '#ffffff', corr_positive: '#ef4444',
};

const SMART_ARABIC = {
  cs_rate: 'معدل القيصارية',
  smm_total: 'المضاعفات الخطيرة',
  mat_deaths: 'الوفيات الأمومية',
  nd: 'وفيات المولودين',
  sb: 'الولادات الميتة',
  preterm: 'الولادات السابقة لأوانها',
  lbw: 'نقص وزن الولادة',
  total_births: 'إجمالي المواليد',
  high_risk: 'حالات الخطر العالي',
  adolescent: 'الحالات المراهقة',
  governorate: 'المحافظة',
  hospital_type: 'نوع المستشفى',
  cs_per_birth: 'نسبة القيصارية لكل ولادة',
  smm_per_1000: 'المضاعفات لكل 1000 ولادة',
  mat_mortality_rate: 'معدل الوفيات الأمومية',
  stillbirth_rate: 'معدل الولادات الميتة',
  preterm_rate: 'معدل الولادات المبكرة',
  lbw_rate: 'معدل نقص الوزن',
  high_risk_rate: 'نسبة الخطر العالي',
  adolescent_rate: 'نسبة الحالات المراهقة',
  cs_x_highrisk: 'قيصارية × خطر عالي',
  preterm_x_lbw: 'ولادة مبكرة × نقص وزن',
  smm_x_matdeaths: 'مضاعفات × وفيات أمومية',
  nd_x_sb: 'وفيات جديدة × ولادات ميتة',
  cs_rate_delta: 'تغير معدل القيصارية',
  smm_delta: 'تغير المضاعفات',
  mat_deaths_delta: 'تغير الوفيات الأمومية',
  total_births_delta: 'تغير المواليد',
};

// ميزات زمنية إضافية (اختيار أفضل مجموعة عبر walk-forward): قيم الشهر السابق
// وشهرين سابقين للمعدلات الحساسة، والتغيّر الشهري لكل المؤشرات الأساسية.
['cs_rate', 'smm_total', 'mat_deaths', 'total_births', 'nd', 'sb'].forEach(k => {
  SMART_ARABIC['lag1_' + k] = (SMART_ARABIC[k] || k) + ' (قيمة الشهر السابق)';
  SMART_ARABIC['lag2_' + k] = (SMART_ARABIC[k] || k) + ' (قيمة شهرين سابقين)';
});
['cs_rate', 'smm_total', 'mat_deaths', 'nd', 'sb', 'preterm', 'lbw', 'total_births', 'high_risk', 'adolescent'].forEach(k => {
  SMART_ARABIC['delta_' + k] = 'التغيّر الشهري في ' + (SMART_ARABIC[k] || k);
});

function smartTranslateFeature(name) {
  if (!name) return '-';
  if (SMART_ARABIC[name]) return SMART_ARABIC[name];
  if (name.startsWith('governorate_')) {
    const val = name.substring('governorate_'.length);
    return val.startsWith('محافظة') ? val : 'محافظة ' + val;
  }
  if (name.startsWith('hospital_type_')) {
    const val = name.substring('hospital_type_'.length);
    return val.startsWith('نوع') ? val : 'نوع: ' + val;
  }
  return name;
}

let smartCurrentMonth = null;
let smartCurrentData = null;
let smartMonthChartsRendered = false;

async function apiSmartGet(path) {
  const base = document.getElementById('apiBase')?.value || '';
  const res = await fetch(base + path);
  return res.json();
}

window.smartGoRootCause = function(hospitalId, month) {
  if (typeof window.goRootCause === 'function') {
    window.goRootCause(hospitalId, month);
  } else {
    console.error('goRootCause not loaded');
  }
};

window.initSmartAnalytics = async function() {
  const monthSelect = document.getElementById('smart-month-select');
  if (!monthSelect) return; // التبويب لم يُحمَّل
  const monthsRes = await apiSmartGet('/analysis/months');
  const months = monthsRes?.months || monthsRes || [];
  monthSelect.innerHTML = '';
  months.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.month || m; opt.textContent = m.month || m;
    monthSelect.appendChild(opt);
  });
  monthSelect.addEventListener('change', () => {
    const reportSection = document.getElementById('smart-report-section');
    if (reportSection) reportSection.style.display = 'none';
    loadSmartData(monthSelect.value);
    // لوحة المستشفى تعتمد على الشهر + المستشفى — حدّثها للشهر الجديد إذا كانت ظاهرة
    const hospitalId = document.getElementById('smart-hospital-select').value;
    if (hospitalId) loadHospitalAnalysis(parseInt(hospitalId), monthSelect.value);
  });

  document.getElementById('smart-refresh').addEventListener('click', () => {
    loadSmartData(monthSelect.value);
    const hospitalId = document.getElementById('smart-hospital-select').value;
    if (hospitalId) loadHospitalAnalysis(parseInt(hospitalId), monthSelect.value);
  });
  document.getElementById('smart-close-hospital').addEventListener('click', () => {
    document.getElementById('smart-hospital-panel').style.display = 'none';
    document.getElementById('smart-hospital-select').value = '';
  });
  document.getElementById('smart-hospital-all-months').addEventListener('click', () => {
    const hospitalId = document.getElementById('smart-hospital-select').value;
    if (hospitalId) loadHospitalAnalysis(parseInt(hospitalId), 'all');
  });
  document.getElementById('smart-hospital-select').addEventListener('change', (e) => {
    const hospitalId = e.target.value;
    if (hospitalId) {
      loadHospitalAnalysis(parseInt(hospitalId), monthSelect.value);
    } else {
      document.getElementById('smart-hospital-panel').style.display = 'none';
    }
    // إذا كان التقرير ظاهراً حدّث المقارنة النظيرة للمستشفى المحدد
    const reportOutput = document.getElementById('smart-report-output');
    if (monthSelect.value && reportOutput && reportOutput.style.display !== 'none') {
      smartGenerateAdvancedComparison(monthSelect.value, hospitalId, document.getElementById('smart-comparison-type')?.value || 'all');
    }
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
  document.getElementById('smart-drilldown-modal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) e.target.style.display = 'none';
  });
  document.getElementById('smart-comparison-type').addEventListener('change', () => {
    const month = monthSelect.value;
    const hospitalId = document.getElementById('smart-hospital-select').value;
    const comparisonType = document.getElementById('smart-comparison-type').value;
    if (month && document.getElementById('smart-report-output').style.display !== 'none') {
      smartGenerateAdvancedComparison(month, hospitalId, comparisonType);
    }
  });

  // رسم كسول: تُرسم تحليلات الشهر عند فتح قسمها المطوي فقط (تفادي رسوم خارج الشاشة)
  const monthSections = document.getElementById('smart-month-sections');
  if (monthSections) {
    monthSections.addEventListener('toggle', () => {
      if (monthSections.open && smartCurrentData) renderMonthCharts();
    });
  }
  // التحليل العام (كل الأشهر) يُحمَّل مرة واحدة عند أول فتح لقسمه
  const globalSections = document.getElementById('smart-global-sections');
  if (globalSections) {
    globalSections.addEventListener('toggle', () => {
      if (globalSections.open) loadAnomalyTimeline();
    });
  }

  if (months.length > 0) {
    const lastMonth = months[months.length - 1];
    monthSelect.value = lastMonth.month || lastMonth;
    loadSmartData(monthSelect.value);
  }
};

async function updateHospitalList() {
  const month = document.getElementById('smart-month-select').value;
  if (!month) return;
  let anomalies = null;
  // استخدم البيانات المحمّلة أصلاً (بدون طلب شبكة مكرر) إن كانت للشهر نفسه
  if (smartCurrentData && smartCurrentMonth === month) {
    anomalies = smartCurrentData.data?.anomalies || [];
  } else {
    try {
      const data = await apiSmartGet(`/smart/overview/${month}`);
      anomalies = data.data?.anomalies || [];
    } catch (e) {
      console.error('Failed to load hospital list:', e);
      return;
    }
  }
  const select = document.getElementById('smart-hospital-select');
  const current = select.value;
  select.innerHTML = '<option value="">-- جميع المستشفيات --</option>';
  const sorted = [...anomalies].sort((a, b) => {
    const order = {critical: 0, warning: 1, normal: 2};
    return (order[a.severity] || 2) - (order[b.severity] || 2);
  });
  sorted.forEach(a => {
    const opt = document.createElement('option');
    opt.value = a.hospital_id;
    const icon = a.severity === 'critical' ? '🔴' : a.severity === 'warning' ? '🟡' : '🟢';
    opt.textContent = `${icon} ${a.hospital_name} (${a.anomaly_score.toFixed(2)})`;
    select.appendChild(opt);
  });
  if (current) select.value = current;
}

function smartShowLoading() {
  const el = document.getElementById('smart-loading-overlay');
  if (el) { el.style.display = 'flex'; }
}
function smartHideLoading() {
  const el = document.getElementById('smart-loading-overlay');
  if (el) { el.style.display = 'none'; }
}

// لوحة القرار: قائمة المستشفيات الحرجة (إجراء فوري أعلى الصفحة)
function renderCriticalList(anomalies) {
  const container = document.getElementById('smart-critical-list');
  const countEl = document.getElementById('smart-critical-count');
  const textEl = document.getElementById('smart-critical-text');
  if (!container) return;
  const critical = (anomalies || []).filter(a => a.severity === 'critical');
  const warnings = (anomalies || []).filter(a => a.severity === 'warning');
  if (countEl) countEl.textContent = `${critical.length} حرج · ${warnings.length} تنبيه`;
  if (critical.length === 0) {
    container.innerHTML = `<div style="display:flex;align-items:center;gap:0.5rem;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:0.8rem 1rem;color:#15803d;font-size:0.85rem;font-weight:600;">
      ✅ لا توجد مستشفيات حرجة هذا الشهر — جميع المستشفيات ضمن حد التنبيه أو أدناه.
    </div>`;
    if (textEl) textEl.textContent = `هناك ${warnings.length} مستشفى في حالة تنبيه (0.3–0.6) — افتح جدول الشذوذ للمتابعة.`;
    return;
  }
  container.innerHTML = critical.map(h => {
    const hid = parseInt(h.hospital_id, 10);
    const month = smartCurrentMonth || '';
    return `<div style="border:1px solid #fecaca;border-radius:10px;padding:0.7rem 0.85rem;background:#fef2f2;">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:0.4rem;margin-bottom:0.4rem;">
        <div style="font-size:0.82rem;font-weight:700;color:#991b1b;line-height:1.4;">${_smartEscapeHtml(h.hospital_name)}</div>
        <span style="flex-shrink:0;font-size:0.62rem;background:#dc2626;color:#fff;padding:2px 8px;border-radius:10px;font-weight:700;">${h.anomaly_score.toFixed(3)}</span>
      </div>
      <div style="font-size:0.7rem;color:#6b7280;margin-bottom:0.5rem;">${_smartEscapeHtml(h.governorate || '')}${h.hospital_type ? ' · ' + _smartEscapeHtml(h.hospital_type) : ''}</div>
      <div style="display:flex;gap:0.4rem;justify-content:flex-end;">
        <button class="btn btn-sm btn-outline" style="font-size:0.66rem;padding:0.18rem 0.45rem;" onclick="window.smartDrilldown(${hid})">📊 تفاصيل</button>
        <button class="btn btn-sm" style="font-size:0.66rem;padding:0.18rem 0.45rem;background:#dc2626;color:#fff;border:none;border-radius:4px;cursor:pointer;" onclick="window.smartGoRootCause(${hid}, '${month}')" title="فتح تحليل السبب الجذري لهذا المستشفى والشهر">🔍 السبب الجذري</button>
      </div>
    </div>`;
  }).join('');
  if (textEl) textEl.textContent = 'المستشفيات الحرجة (درجة > 0.6) تحتاج تدخلاً عاجلاً. انقر «تفاصيل» لعرض عوامل الشذوذ أو «السبب الجذري» لتحليل أعمق.';
}

// فتح قسم تحليلات الشهر والتمرير لقسم محدد (من لوحة القرار)
window.smartOpenMonthSections = function(targetId) {
  const details = document.getElementById('smart-month-sections');
  if (details && !details.open) details.open = true;
  if (targetId) {
    setTimeout(() => {
      const el = document.getElementById(targetId);
      if (el) el.scrollIntoView({behavior: 'smooth', block: 'start'});
    }, 80);
  }
};

// كل الرسوم المرتبطة بالشهر — تُستدعى مرة واحدة عند فتح القسم المطوي
function renderMonthCharts() {
  if (!smartCurrentData) return;
  if (smartMonthChartsRendered) return;
  smartMonthChartsRendered = true;
  const d = smartCurrentData.data;
  const total = smartCurrentData.hospitals_count;

  renderGeoMap(d.geo);
  renderClusterScatter(d.clustering, d.anomalies);
  renderClusterProfiles(d.clustering?.profiles);
  renderCorrelationHeatmap(d.correlations);
  renderCompositePatterns(d.patterns);
  renderSeverityDonut(d.kpi, total);
  renderScoreHistogram(d.anomalies);
  renderPredictedScatter(d.xgboost);
  renderResidualPlot(d.residuals, document.getElementById('smart-residual-indicator').value);
  renderAnomalyTable(d.anomalies, d.explanations);
  renderHealthyHospitals(d.healthy_hospitals);
  renderFeatureImportance(d.correlations, document.getElementById('smart-fi-indicator').value);
  renderStratifiedComparison(d.stratified, document.getElementById('smart-strat-indicator').value);
  renderXGBoostPredictions(d.xgboost);
  renderLagAnalysis(d.lag_analysis);
  loadGovernorateAnalysis(smartCurrentMonth);
  loadRegionalAnalysis(smartCurrentMonth);
}

async function loadSmartData(month) {
  smartCurrentMonth = month;
  document.getElementById('smart-status').textContent = 'جاري التحميل...';
  smartShowLoading();
  try {
    smartCurrentData = await apiSmartGet(`/smart/overview/${month}`);
    const d = smartCurrentData.data;
    const total = smartCurrentData.hospitals_count;

    // ── لوحة القرار (تُرسم فوراً — قرار أولاً) ──
    const decisionMonth = document.getElementById('smart-decision-month');
    if (decisionMonth) decisionMonth.textContent = month;
    renderKPIs(d.kpi, total);
    renderCriticalList(d.anomalies);
    renderEarlyWarnings(d.early_warnings);

    // تحديث قائمة المستشفيات من البيانات المحمّلة (بدون طلب مكرر)
    updateHospitalList();

    // ── تحليلات الشهر: تُرسم عند فتح القسم المطوي فقط ──
    smartMonthChartsRendered = false;
    const monthSections = document.getElementById('smart-month-sections');
    if (monthSections && monthSections.open) renderMonthCharts();

    document.getElementById('smart-status').textContent = `تم التحديث — ${total} مستشفى`;
    document.getElementById('smart-disclaimer').textContent = `النتائج مبنية على بيانات ${total} مستشفى فقط. يجب تفسيرها كمؤشرات أولية وليست قرارات نهائية. لا تتوفر تنبؤات زمنية في هذه المرحلة.`;
    if (!smartReportGenerating) smartHideLoading();
  } catch (e) {
    document.getElementById('smart-status').textContent = 'خطأ في التحميل: ' + e.message;
    smartHideLoading();
  }
}

function openSmartModal(title, bodyHtml) {
  const modal = document.getElementById('smart-kpi-modal');
  document.getElementById('smart-kpi-modal-title').textContent = title;
  document.getElementById('smart-kpi-modal-body').innerHTML = bodyHtml;
  modal.style.display = 'flex';
  modal.onclick = function(e) { if (e.target === modal) modal.style.display = 'none'; };
}

function renderKPIs(kpi, hospitalsCount) {
  const c = document.getElementById('smart-kpi-container');
  const statusColor = kpi.month_status === 'critical' ? SMART_COLORS.critical : kpi.month_status === 'attention_needed' ? SMART_COLORS.warning : SMART_COLORS.normal;
  const statusText = kpi.month_status === 'critical' ? 'يحتاج تدخل عاجل' : kpi.month_status === 'attention_needed' ? 'يحتاج مراقبة مستمرة' : 'ضمن النطاق الطبيعي';
  const statusIcon = kpi.month_status === 'critical' ? '❌' : kpi.month_status === 'attention_needed' ? '⚠️' : '✅';
  const criticalPct = hospitalsCount > 0 ? Math.round(kpi.critical_count / hospitalsCount * 100) : 0;
  const warningPct = hospitalsCount > 0 ? Math.round(kpi.warning_count / hospitalsCount * 100) : 0;
  const normalCount = hospitalsCount - kpi.critical_count - kpi.warning_count;

  const cardStyle = 'text-align:center;padding:1rem;border-radius:8px;cursor:pointer;transition:transform 0.15s,box-shadow 0.15s;';
  const hoverJs = 'onmouseenter="this.style.transform=\'translateY(-3px)\';this.style.boxShadow=\'0 6px 20px rgba(0,0,0,0.12)\'" onmouseleave="this.style.transform=\'none\';this.style.boxShadow=\'none\'"';

  c.innerHTML = `
    <div class="card" style="${cardStyle}border-top:3px solid ${kpi.total_anomalies > 0 ? SMART_COLORS.critical : SMART_COLORS.normal};" ${hoverJs} onclick="window._smartKPIAnomalies()">
      <div style="font-size:2.2rem;font-weight:700;color:${kpi.total_anomalies > 0 ? SMART_COLORS.critical : SMART_COLORS.normal};">${kpi.total_anomalies}<span style="font-size:0.9rem;font-weight:400;color:#999;">/${hospitalsCount}</span></div>
      <div style="font-size:0.8rem;color:#444;font-weight:600;margin:0.3rem 0;">مستشفى بنتائج شاذة</div>
      <div style="font-size:0.7rem;color:#888;line-height:1.4;">${kpi.critical_count} حرج (${criticalPct}%) + ${kpi.warning_count} تنبيه (${warningPct}%)</div>
      <div style="font-size:0.68rem;color:#aaa;margin-top:0.3rem;">يتجاوز المعدل المتوقع بناءً على 10 مؤشرات سريرية</div>
      <div style="font-size:0.65rem;color:#3b82f6;margin-top:0.4rem;">ℹ️ اضغط للتفاصيل</div>
    </div>

    <div class="card" style="${cardStyle}border-top:3px solid #3b82f6;" ${hoverJs} onclick="window._smartKPIGovernorates()">
      <div style="font-size:2.2rem;font-weight:700;color:#3b82f6;">${kpi.affected_governorates}<span style="font-size:0.9rem;font-weight:400;color:#999;">/${hospitalsCount > 0 ? Math.min(hospitalsCount, 5) : 5}</span></div>
      <div style="font-size:0.8rem;color:#444;font-weight:600;margin:0.3rem 0;">محافظات بها انحرافات</div>
      <div style="font-size:0.7rem;color:#888;line-height:1.4;">تحتوي على مستشفيات تنبيه أو حرج</div>
      <div style="font-size:0.68rem;color:#aaa;margin-top:0.3rem;">المحافظات: غزة، خان يونس، الشمال، الوسطى، رفح</div>
      <div style="font-size:0.65rem;color:#3b82f6;margin-top:0.4rem;">ℹ️ اضغط للتفاصيل</div>
    </div>

    <div class="card" style="${cardStyle}border-top:3px solid #8b5cf6;" ${hoverJs} onclick="window._smartKPIFactors()">
      <div style="font-size:1rem;font-weight:700;color:#8b5cf6;word-break:break-word;line-height:1.4;">${smartTranslateFeature(kpi.top_contributing_factor) || 'غير محدد'}</div>
      <div style="font-size:0.8rem;color:#444;font-weight:600;margin:0.3rem 0;">العامل الأكثر تأثيراً</div>
      <div style="font-size:0.7rem;color:#888;line-height:1.4;">أبرز العوامل المسببة للشذوذ</div>
      <div style="font-size:0.68rem;color:#aaa;margin-top:0.3rem;">يُحدَّد من تحليل SHAP للعوامل المؤثرة</div>
      <div style="font-size:0.65rem;color:#3b82f6;margin-top:0.4rem;">ℹ️ اضغط للتفاصيل</div>
    </div>

    <div class="card" style="${cardStyle}border-left:4px solid ${statusColor};" ${hoverJs} onclick="window._smartKPIStatus()">
      <div style="font-size:1.4rem;font-weight:700;">${statusIcon} ${statusText}</div>
      <div style="font-size:0.8rem;color:#444;font-weight:600;margin:0.3rem 0;">حالة الشهر</div>
      <div style="font-size:0.7rem;color:#888;line-height:1.4;">${hospitalsCount} مستشفى مُحلَّل — ${normalCount} طبيعي، ${kpi.warning_count} تنبيه، ${kpi.critical_count} حرج</div>
      <div style="font-size:0.68rem;color:#aaa;margin-top:0.3rem;">يتم تجميع النتائج من 7 محركات تحليل ذكي</div>
      <div style="font-size:0.65rem;color:#3b82f6;margin-top:0.4rem;">ℹ️ اضغط للتفاصيل</div>
    </div>
  `;
}

window._smartKPIAnomalies = function() {
  if (!smartCurrentData || !smartCurrentData.data) return;
  const anomalies = smartCurrentData.data.anomalies || [];
  const total = smartCurrentData.hospitals_count || anomalies.length;
  const sorted = [...anomalies].sort((a, b) => b.anomaly_score - a.anomaly_score);

  let rows = sorted.map((a, i) => {
    const sevColor = a.severity === 'critical' ? SMART_COLORS.critical : a.severity === 'warning' ? SMART_COLORS.warning : SMART_COLORS.normal;
    const sevBg = a.severity === 'critical' ? '#fef2f2' : a.severity === 'warning' ? '#fffbeb' : '#f0fdf4';
    const sevText = a.severity === 'critical' ? 'حرج' : a.severity === 'warning' ? 'تنبيه' : 'طبيعي';
    return `<tr style="border-bottom:1px solid #f0f0f0;">
      <td style="padding:0.4rem 0.6rem;text-align:center;color:#999;font-size:0.8rem;">${i + 1}</td>
      <td style="padding:0.4rem 0.6rem;text-align:right;font-weight:600;font-size:0.82rem;">${a.hospital_name}</td>
      <td style="padding:0.4rem 0.6rem;text-align:center;font-size:0.75rem;">${a.governorate || '-'}</td>
      <td style="padding:0.4rem 0.6rem;text-align:center;"><span style="display:inline-block;background:${sevBg};color:${sevColor};padding:0.15rem 0.5rem;border-radius:12px;font-weight:700;font-size:0.78rem;">${a.anomaly_score.toFixed(3)}</span></td>
      <td style="padding:0.4rem 0.6rem;text-align:center;"><span style="display:inline-block;background:${sevBg};color:${sevColor};padding:0.15rem 0.5rem;border-radius:12px;font-weight:600;font-size:0.75rem;">${sevText}</span></td>
    </tr>`;
  }).join('');

  const body = `
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:1rem;margin-bottom:1rem;">
      <div style="font-size:0.82rem;color:#374151;line-height:1.7;">
        <strong>كيف تم تحديد هذه القائمة؟</strong><br>
        كُل مستشفى يمر بـ <strong>4 محركات</strong>: Isolation Forest (35%)، LOF (30%)، Mahalanobis (20%)، والبواقي (15%).<br>
        النتيجة المُوحَّدة (0–1) تُقارن مع <strong>العتبات</strong>: أقل من 0.3 طبيعي، 0.3–0.6 تنبيه، أعلى 0.6 حرج.<br>
        <strong>الإدخالات:</strong> 10 مؤشرات سريرية + نوع المستشفى + المحافظة.<br>
        <strong>الإخراج:</strong> الدرجة النهائية + تصنيف الحالة + تفصيل دروس كل محرك.
      </div>
    </div>
    <h4 style="color:#1a237e;margin-bottom:0.5rem;">قائمة المستشفيات (${sorted.length}/${total})</h4>
    <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
      <thead><tr style="background:#f1f5f9;border-bottom:2px solid #e2e8f0;">
        <th style="padding:0.4rem 0.6rem;text-align:center;width:30px;">#</th>
        <th style="padding:0.4rem 0.6rem;text-align:right;">المستشفى</th>
        <th style="padding:0.4rem 0.6rem;text-align:center;">المحافظة</th>
        <th style="padding:0.4rem 0.6rem;text-align:center;">الدرجة</th>
        <th style="padding:0.4rem 0.6rem;text-align:center;">الحالة</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div style="margin-top:1rem;display:flex;gap:1rem;font-size:0.75rem;color:#666;">
      <span><span style="display:inline-block;width:10px;height:10px;background:${SMART_COLORS.normal};border-radius:50%;vertical-align:middle;"></span> طبيعي (&lt;0.3)</span>
      <span><span style="display:inline-block;width:10px;height:10px;background:${SMART_COLORS.warning};border-radius:50%;vertical-align:middle;"></span> تنبيه (0.3–0.6)</span>
      <span><span style="display:inline-block;width:10px;height:10px;background:${SMART_COLORS.critical};border-radius:50%;vertical-align:middle;"></span> حرج (&gt;0.6)</span>
    </div>
  `;
  openSmartModal('🔍 تفاصيل الحالات الشاذة', body);
};

window._smartKPIGovernorates = function() {
  if (!smartCurrentData || !smartCurrentData.data) return;
  const anomalies = smartCurrentData.data.anomalies || [];
  const geo = smartCurrentData.data.geo_aggregation || {};

  const govMap = {};
  anomalies.forEach(a => {
    const g = a.governorate || 'غير محدد';
    if (!govMap[g]) govMap[g] = { critical: 0, warning: 0, normal: 0, hospitals: [] };
    govMap[g][a.severity] = (govMap[g][a.severity] || 0) + 1;
    govMap[g].hospitals.push(a);
  });

  const govEntries = Object.entries(govMap).sort((a, b) => (b[1].critical + b[1].warning) - (a[1].critical + a[1].warning));

  let govRows = govEntries.map(([name, data]) => {
    const total = data.critical + data.warning + data.normal;
    const affected = data.critical + data.warning;
    const barColor = data.critical > 0 ? SMART_COLORS.critical : data.warning > 0 ? SMART_COLORS.warning : SMART_COLORS.normal;
    const barPct = total > 0 ? Math.round(affected / total * 100) : 0;
    return `<tr style="border-bottom:1px solid #f0f0f0;">
      <td style="padding:0.5rem 0.6rem;text-align:right;font-weight:600;">محافظة ${name}</td>
      <td style="padding:0.5rem 0.6rem;text-align:center;">${total}</td>
      <td style="padding:0.5rem 0.6rem;text-align:center;color:${SMART_COLORS.critical};font-weight:600;">${data.critical}</td>
      <td style="padding:0.5rem 0.6rem;text-align:center;color:${SMART_COLORS.warning};font-weight:600;">${data.warning}</td>
      <td style="padding:0.5rem 0.6rem;text-align:center;color:${SMART_COLORS.normal};font-weight:600;">${data.normal}</td>
      <td style="padding:0.5rem 0.6rem;text-align:center;width:120px;">
        <div style="background:#e5e7eb;border-radius:4px;height:12px;overflow:hidden;">
          <div style="background:${barColor};width:${barPct}%;height:100%;border-radius:4px;"></div>
        </div>
        <div style="font-size:0.65rem;color:#888;margin-top:2px;">${barPct}% متأثر</div>
      </td>
    </tr>`;
  }).join('');

  const body = `
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:1rem;margin-bottom:1rem;">
      <div style="font-size:0.82rem;color:#374151;line-height:1.7;">
        <strong>كيف تم تحديد المحافظة؟</strong><br>
        تُحسب المحافظة ك<strong>"متأثرة"</strong> إذا تحتوي على مستشفى واحد على الأقل بحالة تنبيه أو حرج.<br>
        <strong>الإدخالات:</strong> تصنيف كل مستشفى حسب المحافظة + درجة الشذوذ.<br>
        <strong>الإخراج:</strong> عدد المستشفيات في كل محافظة + عدد الحرج/تنبيه/طبيعي + شريط مقارن.
      </div>
    </div>
    <h4 style="color:#1a237e;margin-bottom:0.5rem;">تفصيل المحافظات</h4>
    <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
      <thead><tr style="background:#f1f5f9;border-bottom:2px solid #e2e8f0;">
        <th style="padding:0.5rem 0.6rem;text-align:right;">المحافظة</th>
        <th style="padding:0.5rem 0.6rem;text-align:center;">المستشفيات</th>
        <th style="padding:0.5rem 0.6rem;text-align:center;">حرج</th>
        <th style="padding:0.5rem 0.6rem;text-align:center;">تنبيه</th>
        <th style="padding:0.5rem 0.6rem;text-align:center;">طبيعي</th>
        <th style="padding:0.5rem 0.6rem;text-align:center;">التأثير</th>
      </tr></thead>
      <tbody>${govRows}</tbody>
    </table>
  `;
  openSmartModal('📍 تفاصيل المحافظات', body);
};

window._smartKPIFactors = function() {
  if (!smartCurrentData || !smartCurrentData.data) return;
  const explanations = smartCurrentData.data.explanations || [];

  const factorCounts = {};
  explanations.forEach(exp => {
    if (exp.top_factors) {
      exp.top_factors.forEach(f => {
        const key = f.arabic_label;
        if (!factorCounts[key]) factorCounts[key] = { count: 0, total_shap: 0, hospitals: [] };
        factorCounts[key].count++;
        factorCounts[key].total_shap += f.shap_value;
        factorCounts[key].hospitals.push(exp.hospital_name);
      });
    }
  });

  const sorted = Object.entries(factorCounts).sort((a, b) => b[1].count - a[1].count);

  let factorRows = sorted.map(([name, data], i) => {
    const avgShap = data.total_shap / data.count;
    // الإسهام السالب في decision_function = يزيد الشذوذ => أحمر و«يُزيّد»
    const isDriver = avgShap < 0;
    const dirColor = isDriver ? SMART_COLORS.shap_positive : SMART_COLORS.shap_negative;
    const dirText = isDriver ? 'يُزيّد الشذوذ' : 'يُقلّص الشذوذ';
    return `<tr style="border-bottom:1px solid #f0f0f0;">
      <td style="padding:0.4rem 0.6rem;text-align:center;color:#999;font-size:0.8rem;">${i + 1}</td>
      <td style="padding:0.4rem 0.6rem;text-align:right;font-weight:600;font-size:0.82rem;">${smartTranslateFeature(name)}</td>
      <td style="padding:0.4rem 0.6rem;text-align:center;font-weight:700;color:${dirColor};">${avgShap > 0 ? '+' : ''}${avgShap.toFixed(4)}</td>
      <td style="padding:0.4rem 0.6rem;text-align:center;"><span style="color:${dirColor};font-weight:600;">${dirText}</span></td>
      <td style="padding:0.4rem 0.6rem;text-align:center;">${data.count}</td>
      <td style="padding:0.4rem 0.6rem;text-align:right;font-size:0.72rem;color:#666;">${data.hospitals.slice(0, 3).join(', ')}${data.hospitals.length > 3 ? ` +${data.hospitals.length - 3}` : ''}</td>
    </tr>`;
  }).join('');

  const body = `
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:1rem;margin-bottom:1rem;">
      <div style="font-size:0.82rem;color:#374151;line-height:1.7;">
        <strong>ما هو SHAP؟</strong><br>
        SHAP (SHapley Additive exPlanations) يحسب <strong>مساهمة كل ميزة</strong> في مخرَج نموذج IsolationForest (حيث الدرجة الأقل = أكثر شذوذاً).<br>
        <strong>القيمة السالبة (–):</strong> تُزيّد من درجة الشذوذ — العامل المسؤول عن ارتفاعها (تظهر بالأحمر).<br>
        <strong>القيمة الموجبة (+):</strong> تُقلّص من درجة الشذوذ (تساعد في خفضها).<br>
        <strong>الإدخالات:</strong> قيم الميزات الـ 10 + التصنيف + النموذج المُدرَّب.<br>
        <strong>الإخراج:</strong> مساهمة كل ميزة + تفسير نصي عربي.
      </div>
    </div>
    <h4 style="color:#1a237e;margin-bottom:0.5rem;">العوامل المسؤولة للشذوذ</h4>
    <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
      <thead><tr style="background:#f1f5f9;border-bottom:2px solid #e2e8f0;">
        <th style="padding:0.4rem 0.6rem;text-align:center;width:30px;">#</th>
        <th style="padding:0.4rem 0.6rem;text-align:right;">العامل</th>
        <th style="padding:0.4rem 0.6rem;text-align:center;">متوسط SHAP</th>
        <th style="padding:0.4rem 0.6rem;text-align:center;">الاتجاه</th>
        <th style="padding:0.4rem 0.6rem;text-align:center;">التردد</th>
        <th style="padding:0.4rem 0.6rem;text-align:right;">المستشفيات المتأضعة</th>
      </tr></thead>
      <tbody>${factorRows}</tbody>
    </table>
  `;
  openSmartModal('🔍 تفاصيل العوامل المؤثرة', body);
};

window._smartKPIStatus = function() {
  if (!smartCurrentData || !smartCurrentData.data) return;
  const kpi = smartCurrentData.data.kpi || {};
  const total = smartCurrentData.hospitals_count || 20;
  const normalCount = total - (kpi.critical_count || 0) - (kpi.warning_count || 0);

  const body = `
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:1rem;margin-bottom:1rem;">
      <div style="font-size:0.82rem;color:#374151;line-height:1.7;">
        <strong>كيف تم تحديد حالة الشهر؟</strong><br>
        تُجمَّع نتائج <strong>7 محركات تحليل ذكي</strong>: كشف الشذوذ، التجميع، الارتباط، البواقي، المقارنة الطبقية، SHAP، والخريطة.<br>
        <strong>الحالة النهائية</strong> تعتمد على أسوأ حالة بين المستشفيات:<br>
        • <strong>❌ يحتاج تدخل عاجل:</strong> يوجد مستشفى واحد على الأقل بدرجة حرج (&gt;0.6)<br>
        • <strong>⚠️ يحتاج مراقبة:</strong> أعلى حالة تنبيه (0.3–0.6) ولا حرج<br>
        • <strong>✅ طبيعي:</strong> جميع المستشفيات ضمن الطبيعي (&lt;0.3)<br>
        <strong>الإدخالات:</strong> درجات الشذوذ لجميع المستشفيات.<br>
        <strong>الإخراج:</strong> تصنيف الحالة العامة + عدد المستشفيات في كل فئة.
      </div>
    </div>
    <h4 style="color:#1a237e;margin-bottom:0.8rem;">تقسيم الحالة</h4>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;margin-bottom:1rem;">
      <div style="background:#f0fdf4;border:2px solid ${SMART_COLORS.normal};border-radius:8px;padding:1rem;text-align:center;">
        <div style="font-size:2rem;font-weight:700;color:${SMART_COLORS.normal};">${normalCount}</div>
        <div style="font-size:0.85rem;color:#444;font-weight:600;">طبيعي</div>
        <div style="font-size:0.72rem;color:#888;">درجة &lt;0.3</div>
        <div style="font-size:0.7rem;color:#aaa;margin-top:0.3rem;">${total > 0 ? Math.round(normalCount / total * 100) : 0}% من المستشفيات</div>
      </div>
      <div style="background:#fffbeb;border:2px solid ${SMART_COLORS.warning};border-radius:8px;padding:1rem;text-align:center;">
        <div style="font-size:2rem;font-weight:700;color:${SMART_COLORS.warning};">${kpi.warning_count || 0}</div>
        <div style="font-size:0.85rem;color:#444;font-weight:600;">تنبيه</div>
        <div style="font-size:0.72rem;color:#888;">درجة 0.3–0.6</div>
        <div style="font-size:0.7rem;color:#aaa;margin-top:0.3rem;">${total > 0 ? Math.round((kpi.warning_count || 0) / total * 100) : 0}% من المستشفيات</div>
      </div>
      <div style="background:#fef2f2;border:2px solid ${SMART_COLORS.critical};border-radius:8px;padding:1rem;text-align:center;">
        <div style="font-size:2rem;font-weight:700;color:${SMART_COLORS.critical};">${kpi.critical_count || 0}</div>
        <div style="font-size:0.85rem;color:#444;font-weight:600;">حرج</div>
        <div style="font-size:0.72rem;color:#888;">درجة &gt;0.6</div>
        <div style="font-size:0.7rem;color:#aaa;margin-top:0.3rem;">${total > 0 ? Math.round((kpi.critical_count || 0) / total * 100) : 0}% من المستشفيات</div>
      </div>
    </div>
    <div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:8px;padding:1rem;margin-top:1rem;">
      <div style="font-size:0.82rem;color:#374151;line-height:1.7;">
        <strong>العتبات:</strong><br>
        • <span style="color:${SMART_COLORS.normal};font-weight:700;">أقل من 0.3:</span> البيانات تكون أقرب من المتوسطقة في فضاء المستشفيات المجاوية<br>
        • <span style="color:${SMART_COLORS.warning};font-weight:700;">0.3–0.6:</span> يجب مراقبة أقرب من المستشفى<br>
        • <span style="color:${SMART_COLORS.critical};font-weight:700;">أكثر من 0.6:</span> يحتاج تدخل عاجل
      </div>
    </div>
  `;
  openSmartModal('📊 تفاصيل حالة الشهر', body);
};

const SMART_GOV_ALIASES = {
  'شمال غزة': ['شمال غزة', 'نورث غزة', 'north gaza', 'northgaza'],
  'غزة': ['غزة', 'gaza'],
  'دير البلح': ['دير البلح', 'ديرالبلح', 'deir al balah', 'deiralbalah'],
  'خانيونس': ['خانيونس', 'خان يونس', 'خانيونس', 'khan yunis', 'khanyounis'],
  'رفح': ['رفح', 'rafah'],
};
const _smartNormGov = s => String(s || '').toLowerCase().replace(/[\s_\-\u200f\u200e]/g, '');
function _smartMatchGov(name) {
  const n = _smartNormGov(name);
  for (const [canon, aliases] of Object.entries(SMART_GOV_ALIASES)) {
    if (aliases.some(a => _smartNormGov(a) === n)) return canon;
  }
  return null;
}
function renderGeoMap(geo) {
  if (!geo || !geo.governorates || geo.governorates.length === 0) {
    document.getElementById('smart-geo-text').textContent = 'لا توجد بيانات جغرافية متاحة.';
    return;
  }
  const govs = geo.governorates;
  const affected = govs.filter(g => g.avg_anomaly_score > 0.3).length;
  // Choropleth حقيقي بحدود geoBoundaries (CC BY 4.0)؛ إن فشل التحميل (بدون
  // إنترنت) نعود للرسم الفقاعي بالإحداثيات الثابتة.
  fetch('/static/geo/gaza_governorates.geojson')
    .then(r => r.ok ? r.json() : Promise.reject(new Error('geojson unavailable')))
    .then(gj => {
      const byCanon = {};
      (gj.features || []).forEach((f, i) => {
        if (f.id === undefined) f.id = i;
        const canon = _smartMatchGov(f.properties.name_ar || f.properties.shapeName || '');
        if (canon) byCanon[canon] = f.id;
      });
      const ids = [];
      const z = [];
      const texts = [];
      for (const g of govs) {
        const canon = _smartMatchGov(g.governorate);
        const fid = canon ? byCanon[canon] : undefined;
        if (fid === undefined) continue;
        ids.push(fid);
        z.push(g.avg_anomaly_score || 0);
        texts.push(`<b>${g.governorate}</b><br>المستشفيات: ${g.hospital_count}<br>متوسط الشذوذ: ${(g.avg_anomaly_score || 0).toFixed(2)}<br>حالات شاذة: ${g.outlier_count}`);
      }
      const traces = [];
      if (ids.length > 0) {
        traces.push({
          type: 'choropleth', geojson: gj, locations: ids, z: z,
          colorscale: [[0, '#d1fae5'], [0.5, '#fde68a'], [1, '#dc2626']],
          zmin: 0, zmax: 1,
          marker: {line: {color: '#ffffff', width: 1}},
          text: texts, hovertemplate: '%{text}<extra></extra>',
          colorbar: {title: {text: 'متوسط الشذوذ', font: {size: 9}}, thickness: 10, len: 0.7},
        });
      }
      // فقاعات عدد المستشفيات (في مركز كل محافظة)
      const pts = [];
      for (const g of govs) {
        const canon = _smartMatchGov(g.governorate);
        const feat = (gj.features || []).find(f => canon && _smartMatchGov(f.properties.name_ar || f.properties.shapeName || '') === canon);
        if (feat && feat.geometry && feat.geometry.type === 'Polygon') {
          const coords = feat.geometry.coordinates[0];
          const cx = coords.reduce((s, c) => s + c[0], 0) / coords.length;
          const cy = coords.reduce((s, c) => s + c[1], 0) / coords.length;
          pts.push({lon: cx, lat: cy, size: 20 + g.hospital_count * 7 + (g.avg_anomaly_score || 0) * 30,
                    color: g.avg_anomaly_score > 0.6 ? '#dc2626' : g.avg_anomaly_score > 0.3 ? '#f59e0b' : '#059669',
                    label: `${g.governorate}<br>(${g.hospital_count})`,
                    text: `<b>${g.governorate}</b><br>المستشفيات: ${g.hospital_count}<br>متوسط الشذوذ: ${(g.avg_anomaly_score || 0).toFixed(2)}<br>حالات شاذة: ${g.outlier_count}`});
        }
      }
      if (pts.length > 0) {
        traces.push({
          type: 'scattergeo', mode: 'markers+text',
          lon: pts.map(p => p.lon), lat: pts.map(p => p.lat),
          marker: {size: pts.map(p => p.size), color: pts.map(p => p.color), opacity: 0.85, line: {width: 2, color: '#fff'}},
          text: pts.map(p => p.label),
          textposition: 'top center',
          textfont: {size: 10, color: '#1a237e', family: 'Arial', weight: 700},
          hovertext: pts.map(p => p.text), hoverinfo: 'text',
        });
      }
      Plotly.newPlot('smart-geo-map', traces, {
        geo: {fitbounds: 'locations', showland: false, showframe: false,
              showcoastlines: false, projection: {type: 'mercator'},
              bgcolor: '#dbeafe'},
        margin: {t: 30, b: 20, l: 20, r: 20},
        showlegend: false, paper_bgcolor: 'white',
        annotations: [{
          text: 'خريطة قطاع غزة — حدود geoBoundaries (CC BY 4.0)',
          xref: 'paper', yref: 'paper', x: 0.5, y: 1.06,
          showarrow: false, font: {size: 11, color: '#1a237e', family: 'Arial'},
        }],
      });
      document.getElementById('smart-geo-text').textContent =
        `${affected} من ${govs.length} محافظات تظهر انحرافات (تلوين حسب متوسط درجة الشذوذ).`;
    })
    .catch(() => {
      // ── احتياطي: رسم فقاعي بمواقع ثابتة ──
      const GOV_COORDS = {
        'شمال غزة': {lat: 31.55, lon: 34.45}, 'غزة': {lat: 31.50, lon: 34.47},
        'دير البلح': {lat: 31.42, lon: 34.35}, 'خانيونس': {lat: 31.34, lon: 34.30},
        'رفح': {lat: 31.28, lon: 34.24},
      };
      const lats = govs.map(g => (GOV_COORDS[_smartMatchGov(g.governorate)] || {lat: 31.4}).lat);
      const lons = govs.map(g => (GOV_COORDS[_smartMatchGov(g.governorate)] || {lon: 34.4}).lon);
      const sizes = govs.map(g => 25 + g.hospital_count * 6 + (g.avg_anomaly_score || 0) * 40);
      const colors = govs.map(g => g.avg_anomaly_score > 0.6 ? SMART_COLORS.critical : g.avg_anomaly_score > 0.3 ? SMART_COLORS.warning : SMART_COLORS.normal);
      const texts = govs.map(g => `<b>${g.governorate}</b><br>المستشفيات: ${g.hospital_count}<br>متوسط الشذوذ: ${(g.avg_anomaly_score || 0).toFixed(2)}<br>حالات شاذة: ${g.outlier_count}`);
      const labels = govs.map(g => `${g.governorate}<br>(${g.hospital_count})`);
      Plotly.newPlot('smart-geo-map', [{
        type: 'scatter', mode: 'markers+text', x: lons, y: lats,
        marker: {size: sizes, color: colors, opacity: 0.85, line: {width: 2, color: '#fff'}},
        text: labels, textposition: 'top center',
        textfont: {size: 11, color: '#1a237e', family: 'Arial', weight: 700},
        hovertext: texts, hoverinfo: 'text',
      }], {
        xaxis: {title: 'الطول', range: [34.18, 34.52], showgrid: false, zeroline: false, showticklabels: false},
        yaxis: {title: 'العرض', range: [31.22, 31.62], showgrid: false, zeroline: false, showticklabels: false, scaleanchor: 'x', scaleratio: 1},
        margin: {t: 20, b: 30, l: 20, r: 20}, showlegend: false,
        plot_bgcolor: '#dbeafe', paper_bgcolor: 'white',
      });
      document.getElementById('smart-geo-text').textContent =
        `${affected} من ${govs.length} محافظات تظهر انحرافات (رسم فقاعي — الحدود غير متاحة حالياً).`;
    });
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

function _smartEscapeHtml(s) {
  if (!s) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderHealthyHospitals(healthy) {
  const container = document.getElementById('smart-healthy-hospitals');
  const textEl = document.getElementById('smart-healthy-text');
  if (!container) return;
  if (!healthy || healthy.length === 0) {
    container.innerHTML = '<div style="font-size:0.8rem;color:#888;padding:0.6rem;">لا توجد مستشفيات سليمة كافية لهذا الشهر لعرض نماذج.</div>';
    if (textEl) textEl.textContent = '';
    return;
  }
  container.innerHTML = healthy.map(h => {
    const hid = parseInt(h.hospital_id, 10);
    const month = smartCurrentMonth || '';
    const qualityPct = (h.quality_score || 0);
    const confPct = (h.confidence || 0);
    const qColor = qualityPct >= 90 ? '#16a34a' : qualityPct >= 70 ? '#ca8a04' : '#dc2626';
    const cColor = confPct >= 80 ? '#0891b2' : confPct >= 60 ? '#ca8a04' : '#dc2626';
    const chip = (label, val, color, unit) => `
      <div style="text-align:center;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:0.45rem 0.2rem;">
        <div style="font-size:1.05rem;font-weight:700;color:${color};">${val.toFixed ? val.toFixed(1) : val}${unit || ''}</div>
        <div style="font-size:0.65rem;color:#888;margin-top:0.15rem;">${label}</div>
      </div>`;
    return `<div style="border:1px solid #bbf7d0;border-radius:10px;padding:0.8rem;background:linear-gradient(135deg,#f0fdf4,#f8fafc);">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:0.4rem;margin-bottom:0.5rem;">
        <div style="font-size:0.82rem;font-weight:700;color:#14532d;line-height:1.4;">${_smartEscapeHtml(h.hospital_name)}</div>
        <span style="flex-shrink:0;font-size:0.62rem;background:#16a34a;color:#fff;padding:2px 8px;border-radius:10px;font-weight:700;" title="الدرجة المركّبة (50% جودة + 30% ثقة + 20% انخفاض الشذوذ)">${(h.composite_score || 0).toFixed(0)}</span>
      </div>
      <div style="font-size:0.7rem;color:#6b7280;margin-bottom:0.6rem;">${_smartEscapeHtml(h.governorate || '')}${h.hospital_type ? ' · ' + _smartEscapeHtml(h.hospital_type) : ''} · شذوذ ${(h.anomaly_score || 0).toFixed(3)}</div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.4rem;margin-bottom:0.6rem;">
        ${chip('الجودة', qualityPct, qColor, '%')}
        ${chip('الثقة', confPct, cColor, '%')}
        ${chip('الاكتمال', h.completeness || 0, '#6d28d9', '%')}
      </div>
      <div style="display:flex;gap:0.4rem;justify-content:flex-end;">
        <button class="btn btn-sm btn-outline" style="font-size:0.66rem;padding:0.18rem 0.45rem;" onclick="window.smartDrilldown(${hid})">📊 تفاصيل</button>
        <button class="btn btn-sm" style="font-size:0.66rem;padding:0.18rem 0.45rem;background:#15803d;color:#fff;border:none;border-radius:4px;cursor:pointer;" onclick="window.smartGoRootCause(${hid}, '${month}')" title="فتح تحليل السبب الجذري لهذا المستشفى والشهر">🔍 السبب الجذري</button>
      </div>
    </div>`;
  }).join('');
  if (textEl) textEl.textContent = 'مرتبة حسب درجة مركّبة = 50% جودة البيانات + 30% ثقة + 20% انخفاض الشذوذ. تُعرض أفضل 5 مستشفيات سليمة فقط.';
}

function renderEarlyWarnings(ew) {
  const section = document.getElementById('smart-early-warning-section');
  if (!section) return;
  const warnings = (ew && ew.warnings) || [];
  if (warnings.length === 0) {
    section.style.display = 'none';
    return;
  }
  section.style.display = 'block';
  document.getElementById('smart-early-warning-summary').textContent = ew.summary_ar || '';
  const sevStyle = {
    critical: ['حرج', '#dc2626', '#fef2f2'],
    warning: ['تحذير', '#c2410c', '#fff7ed'],
    info: ['متابعة', '#b45309', '#fffbeb'],
  };
  const confStyle = {high: ['عالية', '#15803d', '#f0fdf4'], medium: ['متوسطة', '#b45309', '#fffbeb'], low: ['منخفضة', '#dc2626', '#fef2f2']};
  document.getElementById('smart-early-warnings').innerHTML = warnings.map((w, i) => {
    const s = sevStyle[w.severity] || sevStyle.info;
    const c = confStyle[w.confidence] || confStyle.low;
    const probW = Math.round((w.probability || 0) * 100);
    const probColor = probW >= 60 ? '#dc2626' : probW >= 40 ? '#c2410c' : '#b45309';
    const chips = (w.contributing || []).map(r => {
      const wTxt = (r.weight !== undefined && r.weight !== 1.0) ? ` · وزن ${r.weight}` : '';
      const leadTxt = r.leads ? ` — يقود ${r.leads}` : '';
      return `<span title="${_smartEscapeHtml(r.metric_ar)}${leadTxt}: ${_fmtNum(r.current, 1)} مقابل ${_fmtNum(r.previous, 1)} قبل شهر" style="display:inline-block;background:#fee2e2;color:#b91c1c;padding:0.12rem 0.45rem;border-radius:8px;font-size:0.66rem;font-weight:600;margin:0.12rem 0.12rem 0 0;">
        ↑ ${_smartEscapeHtml(r.metric_ar)} ${r.delta_pct !== null && r.delta_pct !== undefined ? '+' + r.delta_pct + '%' : ''}${wTxt}
      </span>`;
    }).join('');
    return `<div style="border:1px solid ${s[2] === '#fef2f2' ? '#fecaca' : '#fed7aa'};border-radius:10px;padding:0.8rem;background:${s[2]};">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:0.4rem;margin-bottom:0.45rem;">
        <div style="font-size:0.82rem;font-weight:700;color:#7c2d12;line-height:1.4;">${_smartEscapeHtml(w.hospital_name)}</div>
        <div style="display:flex;gap:0.3rem;flex-shrink:0;">
          ${w.discovered_leads ? '<span style="font-size:0.6rem;background:#7c3aed;color:#fff;padding:2px 8px;border-radius:10px;font-weight:700;" title="قائمة القيادة مبنية من علاقات متأخرة مكتشفة (FDR + غرانجر) موزونة بقوة العلاقة واتساق المستشفيات">🧭 قيادة مكتشفة</span>' : '<span style="font-size:0.6rem;background:#6b7280;color:#fff;padding:2px 8px;border-radius:10px;font-weight:700;" title="بيانات غير كافية لاكتشاف العلاقات — استُخدمت القائمة الافتراضية بوزن 1 لكل مؤشر">📋 قيادة افتراضية</span>'}
          <span style="flex-shrink:0;font-size:0.62rem;background:${s[1]};color:#fff;padding:2px 8px;border-radius:10px;font-weight:700;">${s[0]}</span>
        </div>
      </div>
      <div style="font-size:0.7rem;color:#6b7280;margin-bottom:0.5rem;">${_smartEscapeHtml(w.governorate || '')} · ${w.rising_count} مؤشر(ات) قيادية صاعدة${w.score !== undefined ? ` · وزن ${w.score}` : ''}${w.outcome_rising ? ' · وفيات المواليد ترتفع' : ''}</div>
      <div style="font-size:0.68rem;color:#57534e;margin-bottom:0.5rem;">
        احتمال تدهور تقديري: <span style="font-weight:800;color:${probColor};">${probW}%</span>
        <div style="background:#fecaca;border-radius:4px;height:7px;margin-top:0.25rem;"><div style="background:${probColor};height:7px;border-radius:4px;width:${probW}%;"></div></div>
      </div>
      <div style="margin-bottom:0.5rem;">${chips}</div>
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span style="font-size:0.62rem;background:${c[2]};color:${c[1]};padding:2px 8px;border-radius:10px;font-weight:700;" title="من اكتمال بيانات المستشفى — الثقة المنخفضة تعني إشارة غير موثوقة">ثقة ${c[0]}</span>
        <button class="btn btn-sm" style="font-size:0.66rem;padding:0.18rem 0.45rem;background:#9a3412;color:#fff;border:none;border-radius:4px;cursor:pointer;" onclick="window.smartGoRootCause(${parseInt(w.hospital_id, 10) || 0}, '${w.month}')" title="فتح تحليل السبب الجذري لهذا المستشفى والشهر">🔍 السبب الجذري</button>
      </div>
    </div>`;
  }).join('');
  document.getElementById('smart-early-warning-note').textContent =
    'الارتفاع = ≥10% شهرياً (أو ≥2 نقطة مئوية للمعدلات النسبية) مقابل الشهر السابق. قائمة القيادة تُبنى من العلاقات المتأخرة المكتشفة (FDR + غرانجر) ويُوزن كل مؤشر بقوة علاقته واتساقها (الوزن 1 = أقوى قائد). الاحتمال تقدير تحفظي من قوة الإشارة لا احتمال حقيقي — إشارة للتحقيق لا تشخيص.';
}

// مصفوفة القيادة الزمنية: الصف (القيادي) ← العمود (النتيجة)، بقوة ارتباط جزئي
// (غرانجر-لايك) لأفضل إزاحة 1–3 أشهر، مع علامة ✱ للعلاقات التي اجتازت FDR.
function renderLagMatrix(lag) {
  const el = document.getElementById('smart-lag-matrix');
  if (!el) return;
  const m = lag && lag.matrix;
  if (!m || !m.metrics || m.metrics.length === 0) {
    el.innerHTML = '';
    return;
  }
  const labels = m.names_ar || m.metrics;
  const z = m.values.map(row => row.map(v => (v === null || v === undefined) ? 0 : v));
  const text = m.values.map((row, i) => row.map((v, j) => {
    if (i === j || v === null || v === undefined) return '';
    const sig = (m.significant && m.significant[i][j]) ? ' ✱' : '';
    const lg = (m.lags && m.lags[i][j]) ? ' →' + m.lags[i][j] + 'م' : '';
    return v.toFixed(2) + sig + lg;
  }));
  const trace = {
    type: 'heatmap', z: z, x: labels, y: labels,
    colorscale: [[0, '#1e3a8a'], [0.5, '#faf5ff'], [1, '#7c3aed']],
    zmid: 0, zmin: -1, zmax: 1,
    text: text, texttemplate: '%{text}',
    hovertemplate: '%{y} ← %{x}<br>r = %{z:.2f}<extra></extra>',
    colorbar: {title: {text: 'r', font: {size: 12}}},
  };
  const layout = {
    margin: {t: 20, b: 130, l: 150, r: 20},
    xaxis: {tickangle: -45, tickfont: {size: 10}},
    yaxis: {automargin: true, tickfont: {size: 10}},
  };
  Plotly.newPlot(el, [trace], layout);
}

function renderLagAnalysis(lag) {
  const container = document.getElementById('smart-lag-list');
  const noteEl = document.getElementById('smart-lag-note');
  if (!container) return;
  renderLagMatrix(lag);
  const lags = (lag && lag.lags) || [];
  if (lags.length === 0) {
    container.innerHTML = '<p style="color:#999;font-size:0.8rem;">' + (lag && lag.note_ar ? _smartEscapeHtml(lag.note_ar) : 'لا توجد علاقات متأخرة قوية (يلزم شهران وعدة مستشفيات).') + '</p>';
    if (noteEl) noteEl.textContent = '';
    return;
  }
  const strengthStyle = {strong: ['قوية', '#7c3aed', '#f5f3ff'], moderate: ['متوسطة', '#6d28d9', '#f3e8ff'], weak: ['ضعيفة', '#a855f7', '#faf5ff']};
  const confStyle = {high: ['عالية', '#15803d', '#f0fdf4'], medium: ['متوسطة', '#b45309', '#fffbeb'], low: ['منخفضة', '#dc2626', '#fef2f2']};
  const lagWord = {1: 'شهر واحد', 2: 'شهرين', 3: '3 أشهر'};
  container.innerHTML = lags.map((l, i) => {
    const st = strengthStyle[l.strength] || strengthStyle.weak;
    const cf = confStyle[l.confidence] || confStyle.low;
    const arrow = l.direction === 'positive' ? '↑' : '↓';
    const rColor = l.lag_pearson >= 0 ? '#7c3aed' : '#2563eb';
    const contemp = l.contemporaneous_pearson !== null && l.contemporaneous_pearson !== undefined
      ? `الآني ${l.contemporaneous_pearson > 0 ? '+' : ''}${l.contemporaneous_pearson.toFixed(2)}`
      : 'الآني —';
    const granger = (l.granger_pearson !== null && l.granger_pearson !== undefined)
      ? `بعد التحكم بماضي النتيجة: r = ${l.granger_pearson > 0 ? '+' : ''}${l.granger_pearson.toFixed(2)}`
      : 'لا يمكن فصل القيادة عن استمرارية المؤشر (بيانات شبه حتمية)';
    const consPct = (l.consistency !== null && l.consistency !== undefined) ? Math.round(l.consistency * 100) : null;
    const lagLabel = lagWord[l.lag] || (l.lag + ' أشهر');
    return `<div style="border:1px solid #ddd6fe;border-radius:10px;padding:0.75rem 0.85rem;background:${i % 2 === 0 ? '#faf5ff' : '#fff'};">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:0.4rem;margin-bottom:0.4rem;">
        <div style="font-size:0.8rem;font-weight:700;color:#4c1d95;line-height:1.4;">
          ${_smartEscapeHtml(l.indicator_a_ar)} <span style="color:#a855f7;">t</span>
          <span style="color:#7c3aed;">→</span>
          ${_smartEscapeHtml(l.indicator_b_ar)} <span style="color:#a855f7;">t+${l.lag}</span>
        </div>
        <span style="flex-shrink:0;font-size:0.6rem;background:#6d28d9;color:#fff;padding:2px 8px;border-radius:10px;font-weight:700;">${lagLabel}</span>
      </div>
      <div style="font-size:1.05rem;font-weight:800;color:${rColor};">${arrow} r = ${l.lag_pearson.toFixed(2)}</div>
      <div style="font-size:0.7rem;color:#6b7280;margin:0.3rem 0;line-height:1.6;">
        p = ${l.p_value < 0.001 ? '<0.001' : l.p_value.toFixed(3)} · n = ${l.n} عينة · ${contemp}${l.small_sample ? ' · <span style="color:#c2410c;">⚠ عينة صغيرة</span>' : ''}
      </div>
      <div style="font-size:0.7rem;color:#5b21b6;background:#ede9fe;border-radius:6px;padding:0.35rem 0.5rem;margin-bottom:0.5rem;line-height:1.5;" title="ارتباط غرانجر-لايك corr(A_t, B_{t+L} | B_t): هل تبقى العلاقة بعد إزالة أثر قيمة B السابقة؟">🧪 ${granger}</div>
      <div style="font-size:0.72rem;color:#374151;background:#fefce8;border:1px solid #fde68a;border-radius:6px;padding:0.4rem 0.5rem;margin-bottom:0.5rem;line-height:1.6;">🔮 ${_smartEscapeHtml(l.prediction_ar || l.summary_ar)}</div>
      <div style="display:flex;gap:0.35rem;flex-wrap:wrap;align-items:center;">
        <span style="font-size:0.62rem;background:${st[2]};color:${st[1]};padding:2px 8px;border-radius:10px;font-weight:700;">${st[0]}</span>
        <span style="font-size:0.62rem;background:${cf[2]};color:${cf[1]};padding:2px 8px;border-radius:10px;font-weight:700;" title="من حجم العينة والدلالة والاتساق">ثقة ${cf[0]}</span>
        ${l.is_lead ? '<span style="font-size:0.62rem;background:#7c3aed;color:#fff;padding:2px 8px;border-radius:10px;font-weight:700;" title="|ارتباط التأخر| يتجاوز |الارتباط الآني| — العلاقة تسبق زمنياً">رائدة ⭐</span>' : ''}
        ${l.granger_pass ? '<span style="font-size:0.62rem;background:#16a34a;color:#fff;padding:2px 8px;border-radius:10px;font-weight:700;" title="العلاقة تبقى بعد التحكم بماضي المؤشر الناتج">غرانجر ✓</span>' : '<span style="font-size:0.62rem;background:#d97706;color:#fff;padding:2px 8px;border-radius:10px;font-weight:700;" title="قد تعكس استمرارية المؤشر الناتج لا قيادة حقيقية">لا انفصال عن الماضي</span>'}
        ${consPct !== null ? `<span style="font-size:0.62rem;background:#e0e7ff;color:#3730a3;padding:2px 8px;border-radius:10px;font-weight:700;" title="نسبة المستشفيات التي يتوافق ارتباطها الداخلي مع الاتجاه الكلي">اتساق ${consPct}%</span>` : ''}
        ${l.jackknife_stable ? '<span style="font-size:0.62rem;background:#dcfce7;color:#166534;padding:2px 8px;border-radius:10px;font-weight:700;" title="العلاقة لا تنقلب عند استبعاد أي مستشفى">مستقر ✓</span>' : ''}
      </div>
    </div>`;
  }).join('');
  if (noteEl) noteEl.textContent = (lag && lag.note_ar) || '';
}

function renderCompositePatterns(patterns) {
  const container = document.getElementById('smart-composite-patterns');
  const textEl = document.getElementById('smart-patterns-text');
  if (!container) return;
  if (!patterns || patterns.length === 0) {
    container.innerHTML = '<div style="font-size:0.8rem;color:#888;padding:0.6rem;">لا توجد أنماط مركبة واضحة لهذا الشهر — المؤشرات لا تتكرر معاً في توليفات أعلى من المتوقع.</div>';
    if (textEl) textEl.textContent = '';
    return;
  }
  container.innerHTML = patterns.map(p => {
    const chips = (p.indicators || []).map((ind, i) => {
      const up = (p.statuses || [])[i] !== 'lowered';
      const col = up ? '#b91c1c' : '#1565c0';
      const bg = up ? '#fef2f2' : '#e3f2fd';
      const arrow = up ? '↑' : '↓';
      const label = smartTranslateFeature(ind);
      return `<span style="display:inline-block;background:${bg};color:${col};padding:0.2rem 0.5rem;border-radius:6px;font-size:0.72rem;font-weight:600;margin:0.1rem 0.15rem;">${arrow} ${label}</span>`;
    }).join('');
    const supportPct = Math.round((p.support || 0) * 100);
    const hospNames = (p.hospitals || []);
    const hospChips = hospNames.length
      ? `<div style="margin-top:0.45rem;padding-top:0.4rem;border-top:1px dashed #99f6e4;font-size:0.7rem;color:#0f766e;">&#127968; في: ${hospNames.slice(0, 3).map(n => `<span style="display:inline-block;background:#ccfbf1;padding:0.1rem 0.4rem;border-radius:5px;margin:0.1rem 0.15rem;">${_smartEscapeHtml(n)}</span>`).join('')}${hospNames.length > 3 ? ` <span style="color:#888;">+${hospNames.length - 3} أخرى</span>` : ''}</div>`
      : '';
    return `<div style="border:1px solid #99f6e4;border-radius:10px;padding:0.8rem;background:linear-gradient(135deg,#f0fdfa,#f8fafc);">
      <div style="font-size:0.8rem;color:#134e4a;font-weight:700;margin-bottom:0.4rem;">${_smartEscapeHtml(p.summary_ar || '')}</div>
      <div style="margin-bottom:0.5rem;">${chips}</div>
      <div style="display:flex;gap:0.8rem;font-size:0.72rem;color:#666;flex-wrap:wrap;">
        <span title="نسبة المستشفيات الحاملة للنمط">&#127968; <strong>${p.hospitals_count}</strong> مستشفى</span>
        <span title="الدعم: نسبة المستشفيات التي تظهر فيها التوليفة">الدعم <strong>${supportPct}%</strong></span>
        <span title="قوة التجاوز عن التواجد المستقل — أعلى من 1 تعني ارتباطاً حقيقياً">Lift <strong>${(p.lift || 0).toFixed(2)}</strong></span>
      </div>${hospChips}
    </div>`;
  }).join('');
  if (textEl) textEl.textContent = 'مرتبة حسب قوة الارتباط (Lift) ثم الدعم. يُحسب النمط من المؤشرات المرتفعة (أعلى من الشريحة 75% أو العتبة السريرية) والمنخفضة (أدنى من الشريحة 25%).';
}

function renderClusterProfiles(profiles) {
  const container = document.getElementById('smart-cluster-profiles');
  if (!container) return;
  if (!profiles || profiles.length === 0) { container.innerHTML = ''; return; }
  const cards = profiles.map(p => {
    const chips = (p.distinguishing_features || []).map(d => {
      const up = d.deviation_pct > 0;
      const col = up ? '#c62828' : '#1565c0';
      const arrow = up ? '↑' : '↓';
      return `<span style="display:inline-block;background:${up ? '#fef2f2' : '#e3f2fd'};color:${col};padding:0.15rem 0.45rem;border-radius:6px;font-size:0.7rem;font-weight:600;margin:0.1rem 0.15rem;" title="المتوسط ${d.cluster_mean ?? ''} مقابل ${d.overall_mean ?? ''}">${arrow} ${smartTranslateFeature(d.feature)} ${Math.abs(d.deviation_pct || 0).toFixed(0)}%</span>`;
    }).join('');
    return `<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:0.6rem 0.8rem;margin-bottom:0.5rem;">
      <div style="font-weight:700;color:#1a237e;font-size:0.8rem;">عنقود ${p.cluster_id} <span style="color:#6b7280;font-weight:400;">(${p.size} مستشفى)</span></div>
      <div style="font-size:0.72rem;color:#374151;margin:0.25rem 0;line-height:1.6;">${_smartEscapeHtml(p.summary_ar || '')}</div>
      <div>${chips}</div>
    </div>`;
  }).join('');
  container.innerHTML = `<div style="font-size:0.78rem;color:#333;font-weight:600;margin-bottom:0.4rem;">🗂️ ملفات تعريف المجموعات</div>${cards}`;
}

function renderCorrelationHeatmap(correlations) {
  if (!correlations || !correlations.matrix || Object.keys(correlations.matrix).length === 0) {
    document.getElementById('smart-corr-text').textContent = 'لا توجد بيانات ارتباط متاحة.';
    return;
  }
  const indicators = correlations.indicators || [];
  const arabicLabels = indicators.map(i => smartTranslateFeature(i));
  const z = indicators.map(ind_a => indicators.map(ind_b => correlations.matrix[ind_a]?.[ind_b] || 0));
  const data = [{ type: 'heatmap', z: z, x: arabicLabels, y: arabicLabels, colorscale: [[0, SMART_COLORS.corr_negative], [0.5, SMART_COLORS.corr_zero], [1, SMART_COLORS.corr_positive]], zmin: -1, zmax: 1, showscale: true, colorbar: {title: {text: 'r', font: {size: 12}}} }];
  Plotly.newPlot('smart-correlation-heatmap', data, { margin: {t: 20, b: 100, l: 100, r: 20}, xaxis: {tickangle: -45}, yaxis: {automargin: true} });
  const strong = correlations.strong_correlations?.[0];
  let corrText = 'لم يتم اكتشاف علاقات قوية.';
  if (strong) {
    const a = strong.indicator_a ? smartTranslateFeature(strong.indicator_a) : '';
    const b = strong.indicator_b ? smartTranslateFeature(strong.indicator_b) : '';
    if (a || b) {
      const r = strong.pearson_r;
      const pair = a && b ? `${a} ↔ ${b}` : (a || b);
      corrText = (typeof r === 'number' && isFinite(r))
        ? `أقوى علاقة: ${pair} (r=${r.toFixed(2)})`
        : `أقوى علاقة: ${pair}`;
    } else {
      corrText = 'توجد علاقات قوية ملحوظة بين المؤشرات.';
    }
  }
  document.getElementById('smart-corr-text').textContent = corrText;
}

function renderResidualPlot(residuals, indicator) {
  if (!residuals || residuals.length === 0) { Plotly.purge('smart-residual-plot'); document.getElementById('smart-residual-text').textContent = 'لا توجد بيانات متاحة.'; return; }
  const filtered = residuals.filter(r => r.indicator === indicator);
  if (filtered.length === 0) { Plotly.purge('smart-residual-plot'); document.getElementById('smart-residual-text').textContent = `لا توجد بيانات لمؤشر ${smartTranslateFeature(indicator)}.`; return; }
  const colors = filtered.map(r => Math.abs(r.residual_z_score) > 2 ? SMART_COLORS.critical : Math.abs(r.residual_z_score) > 1.5 ? SMART_COLORS.warning : SMART_COLORS.normal);
  const data = [{ type: 'scatter', mode: 'markers', x: filtered.map(r => r.predicted_value), y: filtered.map(r => r.residual), marker: { size: 10, color: colors }, text: filtered.map(r => `${r.hospital_name}<br>فعلي: ${r.actual_value.toFixed(1)}<br>متوقع: ${r.predicted_value.toFixed(1)}<br>بواقي: ${r.residual.toFixed(1)}`), hoverinfo: 'text' }];
  const shapes = [
    { type: 'line', x0: 0, x1: 1, y0: 0, y1: 0, xref: 'paper', line: { color: '#999', width: 1, dash: 'dash' } },
  ];
  Plotly.newPlot('smart-residual-plot', data, { shapes, xaxis: {title: 'القيمة المتوقعة'}, yaxis: {title: 'البواقي (فعلي - متوقع)'}, margin: {t: 20, b: 40, l: 60, r: 20} });
  const outliers = filtered.filter(r => r.is_anomaly).length;
  document.getElementById('smart-residual-text').textContent = `${outliers} من ${filtered.length} مستشفي يظهر انحرافاً حقيقياً بعد استبعاد تأثير الموقع والنوع.`;
}

function renderAnomalyTable(anomalies, explanations) {
  if (!anomalies || anomalies.length === 0) { document.getElementById('smart-anomaly-table').innerHTML = '<p>لا توجد بيانات شذوذ.</p>'; return; }
  const expMap = {}; explanations?.forEach(e => { expMap[e.hospital_name] = e; });
  const sorted = [...anomalies].sort((a, b) => b.anomaly_score - a.anomaly_score);

  let html = `<table style="width:100%;border-collapse:collapse;font-size:0.78rem;direction:rtl;">
    <thead>
      <tr style="background:#1a237e;color:white;">
        <th style="padding:0.4rem 0.5rem;text-align:center;border-radius:0 0 8px 0;width:28px;">#</th>
        <th style="padding:0.4rem 0.5rem;text-align:right;white-space:nowrap;">المستشفى</th>
        <th style="padding:0.4rem 0.5rem;text-align:center;white-space:nowrap;">المحافظة</th>
        <th style="padding:0.4rem 0.5rem;text-align:center;white-space:nowrap;">النوع</th>
        <th style="padding:0.4rem 0.5rem;text-align:center;width:50px;">الدرجة</th>
        <th style="padding:0.4rem 0.5rem;text-align:center;width:55px;">الحالة</th>
        <th style="padding:0.4rem 0.5rem;text-align:center;white-space:nowrap;">العامل الأبرز</th>
        <th style="padding:0.4rem 0.5rem;text-align:center;white-space:nowrap;">التفسير</th>
        <th style="padding:0.4rem 0.5rem;text-align:center;border-radius:0 0 0 8px;width:140px;">إجراء</th>
      </tr>
    </thead>
    <tbody>`;

  sorted.forEach((a, idx) => {
    const sevColor = a.severity === 'critical' ? SMART_COLORS.critical : a.severity === 'warning' ? SMART_COLORS.warning : SMART_COLORS.normal;
    const sevBg = a.severity === 'critical' ? '#fef2f2' : a.severity === 'warning' ? '#fffbeb' : '#f0fdf4';
    const sevText = a.severity === 'critical' ? 'حرج' : a.severity === 'warning' ? 'تنبيه' : 'طبيعي';
    const topFactors = expMap[a.hospital_name]?.top_factors || [];
    const factorBadges = topFactors.slice(0, 3).map(f => {
      // SHAP يفسّر مخرَج IsolationForest (decision_function): الإسهام السالب = يزيد الشذوذ
      const isDriver = (f.direction || (f.shap_value < 0 ? 'increases_anomaly' : 'decreases_anomaly')) === 'increases_anomaly';
      const fColor = isDriver ? SMART_COLORS.shap_positive : SMART_COLORS.shap_negative;
      const fBg = isDriver ? '#fef2f2' : '#eff6ff';
      const arrow = isDriver ? '↑' : '↓';
      return `<span style="display:inline-block;background:${fBg};color:${fColor};padding:0.15rem 0.4rem;border-radius:6px;font-size:0.65rem;font-weight:600;margin:0.1rem 0;" title="${smartTranslateFeature(f.arabic_label)}: ${f.shap_value > 0 ? '+' : ''}${f.shap_value.toFixed(4)}">${arrow} ${smartTranslateFeature(f.arabic_label)}</span>`;
    }).join(' ');
    const hid = parseInt(a.hospital_id, 10);
    const sentence = expMap[a.hospital_name]?.text_explanation || '';
    const month = smartCurrentMonth || '';
    html += `<tr style="border-bottom:1px solid #e5e7eb;background:${idx % 2 === 0 ? '#fff' : '#f9fafb'};">
      <td style="padding:0.4rem 0.45rem;text-align:center;color:#999;width:28px;">${idx + 1}</td>
      <td style="padding:0.4rem 0.45rem;text-align:right;font-weight:600;line-height:1.35;min-width:110px;max-width:170px;word-break:break-word;">${a.hospital_name}</td>
      <td style="padding:0.4rem 0.45rem;text-align:center;font-size:0.72rem;white-space:nowrap;">${a.governorate || '-'}</td>
      <td style="padding:0.4rem 0.45rem;text-align:center;font-size:0.72rem;white-space:nowrap;">${a.hospital_type || '-'}</td>
      <td style="padding:0.4rem 0.45rem;text-align:center;width:50px;"><span style="display:inline-block;background:${sevBg};color:${sevColor};padding:0.18rem 0.45rem;border-radius:12px;font-weight:700;font-size:0.8rem;">${a.anomaly_score.toFixed(2)}</span></td>
      <td style="padding:0.4rem 0.45rem;text-align:center;width:55px;"><span style="display:inline-block;background:${sevBg};color:${sevColor};padding:0.18rem 0.45rem;border-radius:12px;font-weight:600;font-size:0.73rem;">${sevText}</span></td>
      <td style="padding:0.4rem 0.45rem;text-align:center;max-width:180px;line-height:1.5;">${factorBadges || '<span style="color:#ccc;">-</span>'}</td>
      <td style="padding:0.4rem 0.45rem;text-align:right;min-width:180px;max-width:280px;line-height:1.6;">${sentence
        ? `<div style="display:flex;align-items:flex-start;gap:0.35rem;">
            <span title="جملة مُولّدة آلياً: تُختار أهم العوامل المؤثرة عبر تحليل SHAP، ثم تُقارن قيمة المستشفى الفعلية بمتوسط مجموعة النظير (نفس المحافظة والنوع)." style="flex-shrink:0;margin-top:0.15rem;background:linear-gradient(135deg,#1a237e,#3949ab);color:#fff;font-size:0.55rem;font-weight:700;padding:2px 6px;border-radius:4px;cursor:help;letter-spacing:0.5px;">AI</span>
            <a href="javascript:void(0)" onclick="window.smartGoRootCause(${hid}, '${month}')" title="اضغط لفتح تحليل السبب الجذري" style="color:#1a237e;text-decoration:none;border-bottom:1px dashed #a5b4fc;font-weight:500;">💬 ${_smartEscapeHtml(sentence)}</a>
          </div>
          <a href="javascript:void(0)" onclick="window.smartDrilldown(${hid})" title="عرض قيم العوامل الفعلية مقابل متوسط النظير" style="font-size:0.66rem;color:#4338ca;text-decoration:underline dotted;margin-top:0.2rem;display:inline-block;">📊 بيانات العوامل الفعلية</a>`
        : '<span style="color:#ccc;">-</span>'}</td>
      <td style="padding:0.4rem 0.45rem;text-align:center;width:140px;white-space:nowrap;"><button class="btn btn-sm btn-outline" style="font-size:0.72rem;padding:0.18rem 0.45rem;" onclick="window.smartDrilldown(${hid})">تفاصيل</button> <button class="btn btn-sm" style="font-size:0.68rem;padding:0.18rem 0.45rem;background:#c62828;color:#fff;border:none;border-radius:4px;cursor:pointer;" onclick="window.smartGoRootCause(${hid}, '${month}')" title="فتح تحليل السبب الجذري لهذا المستشفى والشهر">🔍 السبب الجذري</button></td>
    </tr>`;
  });
  html += '</tbody></table>';
  document.getElementById('smart-anomaly-table').innerHTML = html;
  const critical = anomalies.filter(a => a.severity === 'critical').length;
  const warnings = anomalies.filter(a => a.severity === 'warning').length;
  document.getElementById('smart-table-text').textContent = `إجمالي: ${anomalies.length} مستشفى — ${critical} حرج، ${warnings} تنبيه، ${anomalies.length - critical - warnings} طبيعي.`;
}

function renderFeatureImportance(correlations, targetIndicator) {
  if (!correlations || !correlations.feature_importance) { Plotly.purge('smart-feature-importance'); return; }
  const fi = correlations.feature_importance.find(f => f.target_indicator === targetIndicator);
  if (!fi || fi.features.length === 0) { Plotly.purge('smart-feature-importance'); document.getElementById('smart-fi-text').textContent = 'لا توجد أهمية عوامل متاحة لهذا المؤشر.'; return; }
  const features = fi.features.slice(0, 8);
  const maxImp = Math.max(...features.map(f => f.importance), 0.001);
  const barColors = features.map((f, i) => {
    const ratio = f.importance / maxImp;
    if (ratio > 0.7) return '#1a237e';
    if (ratio > 0.4) return '#3949ab';
    if (ratio > 0.2) return '#5c6bc0';
    return '#9fa8da';
  });
  const data = [{
    type: 'bar', orientation: 'h',
    y: features.map(f => smartTranslateFeature(f.feature_name)),
    x: features.map(f => f.importance),
    marker: { color: barColors, line: { width: 0 } },
    text: features.map(f => f.importance.toFixed(3)),
    textposition: 'outside',
    cliponaxis: false,
    textfont: { size: 11, color: '#1a237e' },
    hovertemplate: '%{y}: %{x:.4f}<extra></extra>',
  }];
  Plotly.newPlot('smart-feature-importance', data, {
    xaxis: {title: 'الأهمية النسبية', gridcolor: '#f0f0f0', zeroline: false},
    yaxis: {autorange: 'reversed', automargin: true, tickfont: {size: 10}},
    margin: {t: 15, b: 50, l: 130, r: 45},
    plot_bgcolor: 'white',
    paper_bgcolor: 'white',
    height: 280,
  });
  document.getElementById('smart-fi-text').textContent = `أهم عامل يؤثر على ${smartTranslateFeature(targetIndicator)}: ${smartTranslateFeature(features[0]?.feature_name)}`;
}

function renderStratifiedComparison(stratified, indicator) {
  if (!stratified || stratified.length === 0) { Plotly.purge('smart-stratified-chart'); return; }
  const filtered = stratified.filter(s => s.indicator === indicator);
  if (filtered.length === 0) { Plotly.purge('smart-stratified-chart'); document.getElementById('smart-strat-text').textContent = 'لا توجد بيانات طبقية لهذا المؤشر.'; return; }
  const sorted = [...filtered].sort((a, b) => Math.abs(b.deviation_pct) - Math.abs(a.deviation_pct)).slice(0, 15);
  const barColors = sorted.map(s => Math.abs(s.deviation_pct) > 30 ? SMART_COLORS.critical : Math.abs(s.deviation_pct) > 15 ? SMART_COLORS.warning : SMART_COLORS.normal);
  const xLabels = sorted.map(s => s.hospital_name.length > 22 ? s.hospital_name.substring(0, 20) + '…' : s.hospital_name);
  const tooltips = sorted.map(s => `${s.hospital_name}<br>المحافظة: ${s.governorate || '-'}<br>النوع: ${s.hospital_type || '-'}<br>القيمة: ${s.hospital_value.toFixed(2)}<br>متوسط النظير: ${s.peer_group_mean.toFixed(2)}<br>الانحراف: ${s.deviation_pct.toFixed(1)}%`);
  // تسميات قيم ظاهرة فوق كل عمود (تتضمن القيم الصفرية) — نفس إصلاح بطاقة المستشفى
  const data = [
    { type: 'bar', name: 'القيمة الفعلية', x: xLabels, y: sorted.map(s => s.hospital_value), marker: { color: barColors }, customdata: tooltips, hovertemplate: '%{customdata}<extra></extra>', text: sorted.map(s => s.hospital_value.toFixed(1)), textposition: 'outside', cliponaxis: false, textfont: { size: 9, color: '#1a237e' } },
    { type: 'bar', name: 'متوسط النظير', x: xLabels, y: sorted.map(s => s.peer_group_mean), marker: { color: '#d1d5db' }, customdata: tooltips, hovertemplate: '%{customdata}<extra></extra>', text: sorted.map(s => s.peer_group_mean.toFixed(1)), textposition: 'outside', cliponaxis: false, textfont: { size: 9, color: '#6b7280' } },
  ];
  Plotly.newPlot('smart-stratified-chart', data, { barmode: 'group', xaxis: {tickangle: -45, tickfont: {size: 10}}, yaxis: {title: 'القيمة', rangemode: 'tozero'}, margin: {t: 20, b: 110, l: 60, r: 20}, legend: {orientation: 'h', y: 1.12}, plot_bgcolor: 'white', paper_bgcolor: 'white' });
  const significant = filtered.filter(s => s.deviation_pct > 15 || s.deviation_pct < -15).length;
  const govCounts = {};
  filtered.forEach(s => { const g = s.governorate || '-'; govCounts[g] = (govCounts[g] || 0) + 1; });
  const govSummary = Object.entries(govCounts).map(([g, c]) => `${g}: ${c}`).join(' | ');
  document.getElementById('smart-strat-text').textContent = `${significant} من ${filtered.length} مستشفى يختلف بشكل ملحوظ — ${govSummary}`;
}

function renderWalkForward(xgb) {
  const badge = document.getElementById('smart-xgb-walkforward-badge');
  const chartEl = document.getElementById('smart-xgb-walkforward-chart');
  const tableEl = document.getElementById('smart-xgb-walkforward-table');
  if (!badge || !chartEl || !tableEl) return;
  const folds = xgb.walk_forward || [];
  if (folds.length === 0) {
    badge.textContent = 'لا توجد طيات كافية';
    Plotly.purge(chartEl);
    tableEl.innerHTML = '<p style="color:#999;font-size:0.78rem;">يلزم شهران على الأقل ببيانات مُعلَّمة لبناء طية تحقق واحدة.</p>';
    return;
  }
  const meanR2 = folds.reduce((s, f) => s + f.r2, 0) / folds.length;
  const meanMae = folds.reduce((s, f) => s + f.mae, 0) / folds.length;
  badge.textContent = `${folds.length} طية | متوسط R²=${meanR2.toFixed(3)} | متوسط MAE=${meanMae.toFixed(3)}`;

  Plotly.newPlot(chartEl, [{
    type: 'bar',
    x: folds.map(f => `← ${f.train_through}`),
    y: folds.map(f => f.r2),
    marker: {color: folds.map(f => f.r2 >= 0 ? '#f97316' : '#ef4444')},
    text: folds.map(f => f.r2.toFixed(3)),
    textposition: 'outside',
    cliponaxis: false,
    hovertemplate: 'التدريب حتى %{x}<br>R²: %{y:.3f}<extra></extra>',
  }], {
    margin: {t: 25, b: 45, l: 45, r: 15},
    xaxis: {title: {text: 'طية (التدريب حتى)', font: {size: 9}}, tickfont: {size: 9}},
    yaxis: {title: {text: 'R² للشهر التالي', font: {size: 9}}, gridcolor: '#f0f0f0', zeroline: true, zerolinecolor: '#888'},
    plot_bgcolor: 'white', paper_bgcolor: 'white', height: 220,
  });

  tableEl.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:0.74rem;direction:rtl;">
    <thead><tr style="background:#7c2d12;color:white;">
      <th style="padding:0.4rem;text-align:center;border-radius:0 0 6px 0;">التدريب حتى</th>
      <th style="padding:0.4rem;text-align:center;">الشهر التالي</th>
      <th style="padding:0.4rem;text-align:center;">عينات</th>
      <th style="padding:0.4rem;text-align:center;">R²</th>
      <th style="padding:0.4rem;text-align:center;border-radius:0 0 0 6px;">MAE</th>
    </tr></thead><tbody>
    ${folds.map((f, i) => {
      const r2Color = f.r2 >= 0 ? '#16a34a' : '#dc2626';
      return `<tr style="border-bottom:1px solid #e5e7eb;background:${i % 2 === 0 ? '#fff' : '#fff7ed'};">
        <td style="padding:0.4rem;text-align:center;">${f.train_through}</td>
        <td style="padding:0.4rem;text-align:center;font-weight:700;">${f.validate_month}</td>
        <td style="padding:0.4rem;text-align:center;font-size:0.68rem;color:#888;">${f.n_train} ← ${f.n_test}</td>
        <td style="padding:0.4rem;text-align:center;font-weight:800;color:${r2Color};">${f.r2.toFixed(3)}</td>
        <td style="padding:0.4rem;text-align:center;">${f.mae.toFixed(3)}</td>
      </tr>`;
    }).join('')}
    </tbody></table>`;
}

function renderXGBoostPredictions(xgb) {
  const section = document.getElementById('smart-xgboost-section');
  if (!xgb || !xgb.predictions || xgb.predictions.length === 0) {
    section.style.display = 'none';
    return;
  }
  section.style.display = 'block';

  const trainedAt = xgb.trained_at ? new Date(xgb.trained_at).toLocaleString('ar') : null;
  const persistLabel = trainedAt
    ? (xgb.retrained ? `🔄 أُعيد تدريبه ${trainedAt}` : `💾 محمَّل من القرص (دُرِّب ${trainedAt})`)
    : '';
  document.getElementById('smart-xgb-model-badge').textContent = `R²=${xgb.model_r2.toFixed(3)} | MAE=${xgb.model_mae.toFixed(3)}`;
  const variantEl = document.getElementById('smart-xgb-variant-badge');
  if (variantEl) {
    const variantNames = {
      baseline: ['الميزات الأساسية', 'الميزات المصدرية + المشتقة + الفروق الأربعة الأساسية'],
      lag_rates: ['معدلات الأشهر السابقة', 'قيم الشهر السابق وشهرين سابقين للمعدلات الحساسة (مع الأساسية)'],
      full_deltas: ['الفروق الشهرية الكاملة', 'التغيّر الشهري لكل المؤشرات الأساسية (مع الأساسية)'],
      combined: ['المجمعة', 'تأخرات الشهرين السابقين + الفروق الشهرية الكاملة (مع الأساسية)'],
    };
    const v = variantNames[xgb.feature_variant] || [xgb.feature_variant, ''];
    variantEl.textContent = `🧬 ${v[0]}`;
    variantEl.title = `مجموعة الميزات المختارة عبر متوسط R² في التحقق الزمني walk-forward: ${v[1]}`;
  }
  document.getElementById('smart-xgb-note').textContent = (persistLabel ? persistLabel + ' — ' : '') + (xgb.accuracy_note || '');

  // التحقق الزمني Walk-Forward: R²/MAE لكل شهر تالٍ
  renderWalkForward(xgb);

  if (xgb.global_feature_importance && xgb.global_feature_importance.length > 0) {
    const fi = xgb.global_feature_importance.slice(0, 8);
    const fiData = [{
      type: 'bar', orientation: 'h',
      y: fi.map(f => smartTranslateFeature(f.feature)),
      x: fi.map(f => f.mean_abs_shap),
      marker: { color: fi.map((_, i) => i < 3 ? '#f97316' : '#fb923c') },
      text: fi.map(f => f.mean_abs_shap.toFixed(4)),
      textposition: 'outside',
      cliponaxis: false,
    }];
    Plotly.newPlot('smart-xgb-global-fi', fiData, {
      margin: {t: 10, b: 40, l: 130, r: 30},
      xaxis: {title: 'متوسط |SHAP|'},
      yaxis: {autorange: 'reversed', automargin: true, tickfont: {size: 10}},
      plot_bgcolor: 'white',
      paper_bgcolor: 'white',
      height: 260,
    });
  }

  const preds = xgb.predictions;
  // قابلية الثقة بالتنبؤ: متوسط R² في التحقق الزمني walk-forward (نفس القيمة
  // لكل المستشفيات لأنها سمة موثوقية النموذج لا سمة المستشفى).
  const wfFolds = xgb.walk_forward || [];
  const wfMeanR2 = wfFolds.length ? wfFolds.reduce((s, f) => s + f.r2, 0) / wfFolds.length : null;
  const wfBadge = (r2) => {
    if (r2 === null) {
      return '<span style="display:inline-block;padding:0.15rem 0.5rem;border-radius:8px;font-size:0.68rem;font-weight:600;background:#f1f5f9;color:#64748b;">لا يوجد تحقق</span>';
    }
    const level = r2 >= 0.5
      ? ['عالية', '#15803d', '#f0fdf4']
      : r2 >= 0.2
        ? ['متوسطة', '#b45309', '#fffbeb']
        : r2 >= 0
          ? ['منخفضة', '#c2410c', '#fff7ed']
          : ['أدنى من التخمين', '#dc2626', '#fef2f2'];
    const foldsNote = wfFolds.length ? ` عبر ${wfFolds.length} طية` : '';
    return `<span title="متوسط R² في التحقق الزمني walk-forward (التنبؤ بالشهر التالي خارج العينة): ${r2.toFixed(3)}${foldsNote}" style="display:inline-block;padding:0.15rem 0.5rem;border-radius:8px;font-size:0.68rem;font-weight:700;background:${level[2]};color:${level[1]};cursor:help;">${level[0]} ${r2.toFixed(2)}</span>`;
  };
  let rows = preds.map((p, i) => {
    const sevColor = p.predicted_severity === 'critical' ? SMART_COLORS.critical : p.predicted_severity === 'warning' ? SMART_COLORS.warning : SMART_COLORS.normal;
    const changeIcon = p.risk_change === 'increasing' ? '↑' : p.risk_change === 'decreasing' ? '↓' : '→';
    const changeColor = p.risk_change === 'increasing' ? SMART_COLORS.critical : p.risk_change === 'decreasing' ? SMART_COLORS.normal : '#999';
    const changeText = p.risk_change === 'increasing' ? 'يزداد' : p.risk_change === 'decreasing' ? 'يقل' : 'مستقر';
    const drivers = (p.top_drivers || []).slice(0, 2).map(d => {
      const dc = d.shap_value > 0 ? SMART_COLORS.shap_positive : SMART_COLORS.shap_negative;
      const arrow = d.shap_value > 0 ? '↑' : '↓';
      return `<span style="font-size:0.6rem;color:${dc};">${arrow}${smartTranslateFeature(d.feature)}</span>`;
    }).join(' ');
    return `<tr style="border-bottom:1px solid #f0f0f0;background:${i % 2 === 0 ? '#fff' : '#f9fafb'};">
      <td style="padding:0.45rem 0.5rem;text-align:center;color:#999;font-size:0.75rem;width:30px;">${i + 1}</td>
      <td style="padding:0.45rem 0.5rem;text-align:right;font-weight:600;font-size:0.78rem;line-height:1.35;min-width:100px;max-width:160px;word-break:break-word;">${p.hospital_name}</td>
      <td style="padding:0.45rem 0.5rem;text-align:center;font-size:0.75rem;">${p.current_score.toFixed(2)}</td>
      <td style="padding:0.45rem 0.5rem;text-align:center;font-weight:700;color:${sevColor};font-size:0.8rem;">${p.predicted_next_score.toFixed(2)}</td>
      <td style="padding:0.45rem 0.5rem;text-align:center;color:${changeColor};font-weight:700;font-size:0.85rem;width:35px;">${changeIcon}</td>
      <td style="padding:0.45rem 0.5rem;text-align:center;"><span style="display:inline-block;padding:0.15rem 0.5rem;border-radius:8px;font-size:0.68rem;font-weight:600;background:${sevColor}20;color:${sevColor};">${p.predicted_severity === 'critical' ? 'حرج' : p.predicted_severity === 'warning' ? 'تنبيه' : 'طبيعي'}</span></td>
      <td style="padding:0.45rem 0.5rem;text-align:center;">${wfBadge(wfMeanR2)}</td>
      <td style="padding:0.45rem 0.5rem;text-align:center;font-size:0.68rem;color:#888;">${Math.round(p.confidence * 100)}%</td>
      <td style="padding:0.45rem 0.5rem;text-align:center;font-size:0.65rem;line-height:1.5;">${drivers || '-'}</td>
    </tr>`;
  }).join('');

  const html = `<table style="width:100%;border-collapse:collapse;font-size:0.78rem;direction:rtl;">
    <thead><tr style="background:#1a237e;color:white;">
      <th style="padding:0.5rem;text-align:center;border-radius:0 0 6px 0;">#</th>
      <th style="padding:0.5rem;text-align:right;">المستشفى</th>
      <th style="padding:0.5rem;text-align:center;">الحالة الحالية</th>
      <th style="padding:0.5rem;text-align:center;">التنبؤ</th>
      <th style="padding:0.5rem;text-align:center;">الاتجاه</th>
      <th style="padding:0.5rem;text-align:center;">المحتمل</th>
      <th style="padding:0.5rem;text-align:center;" title="متوسط R² في التحقق الزمني walk-forward — قابلية الثقة بالتنبؤ (نفسها لكل المستشفيات لأنها سمة النموذج)">قابلية التنبؤ</th>
      <th style="padding:0.5rem;text-align:center;">الثقة</th>
      <th style="padding:0.5rem;text-align:center;border-radius:0 0 0 6px;">العوامل</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
  document.getElementById('smart-xgb-predictions-table').innerHTML = html;
}

async function loadGovernorateAnalysis(month) {
  const section = document.getElementById('smart-gov-section');
  try {
    const data = await apiSmartGet(`/smart/governorate-analysis/${month}`);
    if (!data || !data.governorate_profiles || data.governorate_profiles.length === 0) {
      section.style.display = 'none';
      return;
    }
    section.style.display = 'block';
    renderGovernorateAnalysis(data);
  } catch (e) {
    section.style.display = 'none';
  }
}

function renderGovernorateAnalysis(data) {
  const profiles = data.governorate_profiles || [];
  const crossCorrs = data.cross_governorate_correlations || [];
  const xgbInsights = data.xgboost_insights || {};

  const govCount = profiles.length;
  const hospCount = profiles.reduce((s, p) => s + p.hospital_count, 0);
  document.getElementById('smart-gov-badge').textContent = `${govCount} محافظة | ${hospCount} مستشفى`;
  document.getElementById('smart-gov-note').textContent = `تحليل XGBoost يقيس تأثير كل محافظة على المؤشرات السريرية. كلما ارتفع التأثير، زادت الحاجة لتدخل في تلك المحافظة.`;

  if (xgbInsights && Object.keys(xgbInsights).length > 0) {
    const indicators = Object.keys(xgbInsights);
    const traces = [];
    const govNames = new Set();
    indicators.forEach(ind => {
      const impact = xgbInsights[ind]?.governorate_impact || [];
      impact.forEach(g => govNames.add(g.governorate));
    });
    const allGovs = [...govNames];

    indicators.forEach(ind => {
      const impact = xgbInsights[ind]?.governorate_impact || [];
      const impactMap = {};
      impact.forEach(g => { impactMap[g.governorate] = g.impact; });
      traces.push({
        type: 'bar',
        name: smartTranslateFeature(ind),
        x: allGovs,
        y: allGovs.map(g => impactMap[g] || 0),
        // تسمية القيمة ظاهرة فوق العمود حتى تظهر الأصفار بوضوح بدل اختفاء العمود
        text: allGovs.map(g => (impactMap[g] || 0).toFixed(2)),
        textposition: 'outside',
        cliponaxis: false,
        textfont: { size: 8.5 },
      });
    });

    Plotly.newPlot('smart-gov-impact-chart', traces, {
      barmode: 'group',
      xaxis: {tickangle: -45, tickfont: {size: 10}},
      yaxis: {title: 'متوسط |SHAP| للتأثير', gridcolor: '#f0f0f0'},
      margin: {t: 15, b: 90, l: 60, r: 20},
      legend: {orientation: 'h', y: 1.15, font: {size: 9}},
      plot_bgcolor: 'white', paper_bgcolor: 'white', height: 300,
    });
  }

  const heatmapData = data.indicator_governorate_heatmap || {};
  const indicators = Object.keys(heatmapData).filter(k => FEATURE_KEYS.includes(k));
  const govNames = new Set();
  indicators.forEach(ind => { Object.keys(heatmapData[ind] || {}).forEach(g => govNames.add(g)); });
  const allGovs = [...govNames];

  if (indicators.length > 0 && allGovs.length > 0) {
    const zValues = indicators.map(ind => allGovs.map(g => heatmapData[ind]?.[g] || 0));
    const trace = {
      type: 'heatmap',
      z: zValues,
      x: allGovs,
      y: indicators.map(i => smartTranslateFeature(i)),
      colorscale: [
        [0, '#eff6ff'],
        [0.25, '#93c5fd'],
        [0.5, '#fbbf24'],
        [0.75, '#f97316'],
        [1, '#ef4444'],
      ],
      text: zValues.map(row => row.map(v => v.toFixed(2))),
      texttemplate: '%{text}',
      textfont: {size: 9},
      hovertemplate: '%{y} في %{x}<br>المتوسط: %{z:.3f}<extra></extra>',
    };
    Plotly.newPlot('smart-gov-heatmap', [trace], {
      margin: {t: 10, b: 80, l: 120, r: 20},
      xaxis: {tickangle: -45, tickfont: {size: 10}},
      yaxis: {tickfont: {size: 9}, autorange: 'reversed'},
      plot_bgcolor: 'white', paper_bgcolor: 'white', height: 300,
    });
  }

  if (crossCorrs.length > 0) {
    let html = `<table style="width:100%;border-collapse:collapse;font-size:0.78rem;direction:rtl;">
      <thead><tr style="background:#7c3aed;color:white;">
        <th style="padding:0.5rem;text-align:center;border-radius:0 0 6px 0;">المؤشر أ</th>
        <th style="padding:0.5rem;text-align:center;">المؤشر ب</th>
        <th style="padding:0.5rem;text-align:center;">الارتباط</th>
        <th style="padding:0.5rem;text-align:center;">القوة</th>
        <th style="padding:0.5rem;text-align:center;">الاتجاه</th>
        <th style="padding:0.5rem;text-align:center;border-radius:0 0 0 6px;">المحصّلات</th>
      </tr></thead><tbody>`;
    crossCorrs.slice(0, 10).forEach((c, i) => {
      const rColor = c.correlation > 0 ? '#ef4444' : '#3b82f6';
      const strengthLabel = c.strength === 'strong' ? 'قوي' : 'متوسط';
      const dirLabel = c.direction === 'positive' ? 'إيجابي' : 'سلبي';
      html += `<tr style="border-bottom:1px solid #e5e7eb;background:${i % 2 === 0 ? '#fff' : '#faf5ff'};">
        <td style="padding:0.5rem;text-align:center;font-weight:600;">${smartTranslateFeature(c.indicator_a)}</td>
        <td style="padding:0.5rem;text-align:center;font-weight:600;">${smartTranslateFeature(c.indicator_b)}</td>
        <td style="padding:0.5rem;text-align:center;font-weight:700;color:${rColor};">${c.correlation > 0 ? '+' : ''}${c.correlation.toFixed(3)}</td>
        <td style="padding:0.5rem;text-align:center;"><span style="padding:0.15rem 0.5rem;border-radius:10px;font-size:0.7rem;font-weight:600;background:${c.strength === 'strong' ? '#fef2f2' : '#fffbeb'};color:${c.strength === 'strong' ? '#ef4444' : '#f59e0b'};">${strengthLabel}</span></td>
        <td style="padding:0.5rem;text-align:center;color:${rColor};font-weight:600;">${dirLabel} ${c.correlation > 0 ? '↑' : '↓'}</td>
        <td style="padding:0.5rem;text-align:center;font-size:0.7rem;color:#888;">${c.governorate_count} محافظة</td>
      </tr>`;
    });
    html += '</tbody></table>';
    document.getElementById('smart-gov-cross-table').innerHTML = html;
  } else {
    document.getElementById('smart-gov-cross-table').innerHTML = '<p style="color:#999;font-size:0.82rem;">لا توجد ارتباطات قوية بين المحافظات.</p>';
  }
}

async function loadRegionalAnalysis(month) {
  const section = document.getElementById('smart-regional-section');
  if (!section) return;
  try {
    const data = await apiSmartGet(`/regional/overview/${month}`);
    if (!data || !data.governorates || data.governorates.length === 0) {
      section.style.display = 'none';
      return;
    }
    section.style.display = 'block';
    renderRegionalAnalysis(data);
  } catch (e) {
    section.style.display = 'none';
  }
}

function _fmtNum(v, digits) {
  if (v === null || v === undefined) return '-';
  const n = Number(v);
  if (!isFinite(n)) return '-';
  return digits !== undefined ? n.toFixed(digits) : n.toLocaleString();
}

function _riskBadge(label, level) {
  const colors = {high: ['#ef4444', '#fef2f2'], medium: ['#f59e0b', '#fffbeb'], low: ['#16a34a', '#f0fdf4']};
  const c = colors[level] || colors.low;
  return `<span style="display:inline-block;padding:0.15rem 0.6rem;border-radius:10px;font-size:0.7rem;font-weight:700;background:${c[1]};color:${c[0]};">${label}</span>`;
}

function renderRegionalAnalysis(data) {
  const govs = data.governorates || [];
  const mortality = data.mortality || [];
  const risks = data.risk_scores || [];
  const trends = data.trends || [];
  const oe = data.observed_expected || {};
  const bvm = data.births_vs_mortality || {};
  const benchmarks = data.benchmarks || {};

  const hospCount = govs.reduce((s, g) => s + (g.hospital_count || 0), 0);
  document.getElementById('smart-regional-badge').textContent = `${govs.length} محافظة | ${hospCount} مستشفى`;

  // ── KPIs ──
  const totalBirths = govs.reduce((s, g) => s + (g.births || 0), 0);
  const totalMatDeaths = govs.reduce((s, g) => s + (g.mat_deaths || 0), 0);
  const totalNd = govs.reduce((s, g) => s + (g.nd || 0), 0);
  const totalSb = govs.reduce((s, g) => s + (g.sb || 0), 0);
  const regionalNmr = totalNd / totalBirths * 1000;
  const regionalMmr = totalMatDeaths / totalBirths * 100000;
  const regionalSb = totalSb / totalBirths * 1000;
  const highRiskGovs = risks.filter(r => r.level === 'high').length;
  const kpiCards = [
    {label: 'إجمالي المواليد', value: totalBirths.toLocaleString(), color: '#0f766e'},
    {label: 'وفيات المواليد', value: totalNd.toLocaleString(), color: '#dc2626'},
    {label: 'الوفيات الأمومية', value: totalMatDeaths.toLocaleString(), color: '#dc2626'},
    {label: 'معدل وفيات المواليد (لكل 1000)', value: regionalNmr.toFixed(1), color: '#0f766e'},
    {label: 'نسبة الوفيات الأمومية (100 ألف)', value: regionalMmr.toFixed(1), color: '#0f766e'},
    {label: 'معدل الولادات الميتة (1000)', value: regionalSb.toFixed(1), color: '#0f766e'},
    {label: 'محافظات عالية الخطر', value: highRiskGovs, color: highRiskGovs > 0 ? '#dc2626' : '#16a34a'},
  ];
  document.getElementById('smart-regional-kpis').innerHTML = kpiCards.map(k => `
    <div style="background:#f0fdfa;border:1px solid #99f6e4;border-radius:8px;padding:0.7rem;text-align:center;">
      <div style="font-size:1.15rem;font-weight:800;color:${k.color};">${k.value}</div>
      <div style="font-size:0.68rem;color:#134e4a;margin-top:0.2rem;">${k.label}</div>
    </div>`).join('');

  // ── Mortality bar chart vs benchmark ──
  const mr = mortality.map(m => ({
    gov: m.governorate, rate: m.rate, bench: m.benchmark, dev: m.deviation_pct, risk: m.risk,
  }));
  if (mr.length > 0) {
    const traceBars = {
      type: 'bar', name: 'معدل المحافظة',
      x: mr.map(x => x.gov), y: mr.map(x => x.rate),
      marker: {color: mr.map(x => x.risk === 'high' ? '#ef4444' : x.risk === 'medium' ? '#f59e0b' : '#10b981')},
      text: mr.map(x => _fmtNum(x.rate, 1)), textposition: 'outside', cliponaxis: false,
      hovertemplate: '%{x}<br>المعدل: %{y:.2f} (لكل 1000)<extra></extra>',
    };
    const benchVal = mr[0].bench;
    const traces = [traceBars];
    const mbm = data.mortality_benchmarks || {};
    const xVals = mr.map(x => x.gov);
    if (benchVal !== null && benchVal !== undefined) {
      traces.push({
        type: 'scatter', mode: 'lines', name: 'معيار الإقليم (المتوسط)',
        x: xVals, y: mr.map(() => benchVal),
        line: {color: '#1a237e', dash: 'dash', width: 2},
      });
    }
    if (mbm.target !== null && mbm.target !== undefined) {
      traces.push({
        type: 'scatter', mode: 'lines', name: mbm.target_label_ar || 'الهدف المرجعي',
        x: xVals, y: mr.map(() => mbm.target),
        line: {color: '#16a34a', dash: 'dot', width: 2},
      });
    }
    if (mbm.historical_baseline !== null && mbm.historical_baseline !== undefined) {
      traces.push({
        type: 'scatter', mode: 'lines', name: mbm.historical_baseline_label_ar || 'الأساس التاريخي',
        x: xVals, y: mr.map(() => mbm.historical_baseline),
        line: {color: '#6b7280', dash: 'longdash', width: 1.5},
      });
    }
    Plotly.newPlot('smart-regional-mortality-chart', traces, {
      margin: {t: 20, b: 70, l: 50, r: 20},
      xaxis: {tickangle: -30, tickfont: {size: 10}},
      yaxis: {title: {text: 'لكل 1000 ولادة', font: {size: 10}}, gridcolor: '#f0f0f0'},
      legend: {orientation: 'h', y: 1.15, font: {size: 10}},
      plot_bgcolor: 'white', paper_bgcolor: 'white', height: 300,
      showlegend: true,
    });
  }

  // ── Births vs mortality scatter ──
  const points = bvm.points || [];
  if (points.length > 0) {
    const bvmTraces = [{
      type: 'scatter', mode: 'markers',
      x: points.map(p => p.births), y: points.map(p => p.nmr),
      text: points.map(p => p.governorate), hoverinfo: 'text+x+y',
      marker: {size: 13, color: '#0d9488', line: {color: 'white', width: 1}},
      name: 'المحافظات',
    }];
    const reg = bvm.regression;
    if (reg && points.length > 1) {
      const xMin = Math.min(...points.map(p => p.births));
      const xMax = Math.max(...points.map(p => p.births));
      bvmTraces.push({
        type: 'scatter', mode: 'lines', name: 'خط الانحدار',
        x: [xMin, xMax], y: [reg.intercept + reg.slope * xMin, reg.intercept + reg.slope * xMax],
        line: {color: '#ef4444', dash: 'dot', width: 2},
      });
    }
    Plotly.newPlot('smart-regional-bvm-chart', bvmTraces, {
      margin: {t: 20, b: 50, l: 60, r: 20},
      xaxis: {title: {text: 'حجم الولادات', font: {size: 10}}, gridcolor: '#f0f0f0'},
      yaxis: {title: {text: 'معدل وفيات المواليد (1000)', font: {size: 10}}, gridcolor: '#f0f0f0'},
      legend: {orientation: 'h', y: 1.15, font: {size: 10}},
      plot_bgcolor: 'white', paper_bgcolor: 'white', height: 300,
    });
    const cr = bvm.corr_rate;
    const cRaw = bvm.corr_raw;
    let note = bvm.note_ar || '';
    if (cr) note += ` ارتباط المعدل بالحجم: ${cr.pearson > 0 ? '+' : ''}${cr.pearson.toFixed(2)} (p=${cr.pearson_p || cr.p_value}); `;
    if (cRaw) note += ` ارتباط العدد الخام: ${cRaw.pearson > 0 ? '+' : ''}${cRaw.pearson.toFixed(2)}.`;
    document.getElementById('smart-regional-bvm-note').textContent = note;
  } else {
    document.getElementById('smart-regional-bvm-note').textContent = bvm.note_ar || 'لا توجد بيانات كافية.';
    Plotly.purge('smart-regional-bvm-chart');
  }

  // ── Mortality table ──
  if (mortality.length > 0) {
    document.getElementById('smart-regional-mortality-table').innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:0.78rem;direction:rtl;">
      <thead><tr style="background:#0f766e;color:white;">
        <th style="padding:0.5rem;text-align:right;border-radius:0 0 6px 0;">المحافظة</th>
        <th style="padding:0.5rem;text-align:center;">الوفيات الملاحظة</th>
        <th style="padding:0.5rem;text-align:center;">المواليد</th>
        <th style="padding:0.5rem;text-align:center;">المعدل /1000</th>
        <th style="padding:0.5rem;text-align:center;">معيار الإقليم</th>
        <th style="padding:0.5rem;text-align:center;">الانحراف</th>
        <th style="padding:0.5rem;text-align:center;">مستوى الخطر</th>
        <th style="padding:0.5rem;text-align:center;border-radius:0 0 0 6px;">ملاحظة</th>
      </tr></thead><tbody>
      ${mortality.map((m, i) => {
        const devColor = m.deviation_pct > 0 ? '#dc2626' : '#16a34a';
        return `<tr style="border-bottom:1px solid #e5e7eb;background:${i % 2 === 0 ? '#fff' : '#f0fdfa'};">
          <td style="padding:0.5rem;text-align:right;font-weight:600;">${m.governorate}</td>
          <td style="padding:0.5rem;text-align:center;">${_fmtNum(m.observed_deaths)}</td>
          <td style="padding:0.5rem;text-align:center;">${_fmtNum(m.births)}</td>
          <td style="padding:0.5rem;text-align:center;font-weight:700;">${_fmtNum(m.rate, 2)}</td>
          <td style="padding:0.5rem;text-align:center;">${_fmtNum(m.benchmark, 2)}</td>
          <td style="padding:0.5rem;text-align:center;font-weight:700;color:${devColor};">${m.deviation_pct !== null && m.deviation_pct !== undefined ? (m.deviation_pct > 0 ? '+' : '') + m.deviation_pct + '%' : '-'}</td>
          <td style="padding:0.5rem;text-align:center;">${_riskBadge(m.risk_label_ar, m.risk)}</td>
          <td style="padding:0.5rem;text-align:center;font-size:0.68rem;color:#b45309;">${m.small_sample ? '⚠ عينة صغيرة' : ''}</td>
        </tr>`;
      }).join('')}
      </tbody></table>`;
  }

  // ── O/E table ──
  const oeResults = oe.results || [];
  if (oeResults.length > 0) {
    document.getElementById('smart-regional-oe-table').innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:0.78rem;direction:rtl;">
      <thead><tr style="background:#134e4a;color:white;">
        <th style="padding:0.5rem;text-align:right;border-radius:0 0 6px 0;">المحافظة</th>
        <th style="padding:0.5rem;text-align:center;">الملاحظة</th>
        <th style="padding:0.5rem;text-align:center;">المتوقعة</th>
        <th style="padding:0.5rem;text-align:center;">O/E</th>
        <th style="padding:0.5rem;text-align:center;border-radius:0 0 0 6px;">التفسير</th>
      </tr></thead><tbody>
      ${oeResults.map((r, i) => {
        const oeVal = r.oe_ratio;
        const color = oeVal !== null && oeVal > 1.2 ? '#dc2626' : oeVal !== null && oeVal > 1.0 ? '#f59e0b' : '#16a34a';
        const interp = oeVal === null ? '-' : oeVal > 1.2 ? `أعلى من المتوقع بـ ${((oeVal - 1) * 100).toFixed(0)}%` : oeVal > 1.0 ? 'أعلى قليلاً من المتوقع' : 'عند المتوقع أو أقل';
        return `<tr style="border-bottom:1px solid #e5e7eb;background:${i % 2 === 0 ? '#fff' : '#f0fdfa'};">
          <td style="padding:0.5rem;text-align:right;font-weight:600;">${r.governorate}</td>
          <td style="padding:0.5rem;text-align:center;">${_fmtNum(r.observed)}</td>
          <td style="padding:0.5rem;text-align:center;">${_fmtNum(r.expected, 1)}</td>
          <td style="padding:0.5rem;text-align:center;font-weight:800;color:${color};">${oeVal !== null ? oeVal.toFixed(2) : '-'}</td>
          <td style="padding:0.5rem;text-align:center;font-size:0.7rem;color:#555;">${interp}${r.small_sample ? ' <span style="color:#b45309;">⚠ عينة صغيرة</span>' : ''}</td>
        </tr>`;
      }).join('')}
      </tbody></table>`;
    document.getElementById('smart-regional-oe-note').textContent = `${oe.note_ar || ''} (نموذج: ${oe.model})`;
  }

  // ── Risk bars ──
  if (risks.length > 0) {
    const sorted = [...risks].sort((a, b) => a.risk_score - b.risk_score);
    const colors = {high: '#ef4444', medium: '#f59e0b', low: '#16a34a'};
    Plotly.newPlot('smart-regional-risk-chart', [{
      type: 'bar', orientation: 'h',
      y: sorted.map(r => r.governorate), x: sorted.map(r => r.risk_score),
      marker: {color: sorted.map(r => colors[r.level] || '#16a34a')},
      text: sorted.map(r => `${r.risk_score} — ${r.confidence_label_ar}`), textposition: 'outside', cliponaxis: false,
      hovertemplate: '%{y}<br>درجة الخطر: %{x}<br>الثقة: %{text}<extra></extra>',
    }], {
      margin: {t: 10, b: 40, l: 110, r: 30},
      xaxis: {range: [0, 100], title: {text: 'درجة الخطر (0-100)', font: {size: 10}}, gridcolor: '#f0f0f0'},
      yaxis: {autorange: 'reversed', tickfont: {size: 11}},
      plot_bgcolor: 'white', paper_bgcolor: 'white', height: 280,
    });
    const lowConf = risks.filter(r => r.confidence === 'low');
    let riskNote = 'درجة مركّبة من انحراف الوفيات ومعدلات الخطر والاتجاهات، مع عقوبة ضعف الاكتمال.';
    if (lowConf.length > 0) riskNote += ' ⚠ ' + lowConf.length + ' محافظة بثقة منخفضة — استنتاجاتها غير موثوقة.';
    document.getElementById('smart-regional-risk-note').textContent = riskNote;
  }

  // ── Regional anomalies ──
  const anomalies = data.anomalies || [];
  const anomTable = document.getElementById('smart-regional-anomalies-table');
  const anomNote = document.getElementById('smart-regional-anomalies-note');
  if (anomTable) {
    if (anomalies.length > 0) {
      anomTable.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:0.78rem;direction:rtl;">
        <thead><tr style="background:#b91c1c;color:white;">
          <th style="padding:0.5rem;text-align:center;border-radius:0 0 6px 0;">المحافظة</th>
          <th style="padding:0.5rem;text-align:right;">المؤشر</th>
          <th style="padding:0.5rem;text-align:center;">النوع</th>
          <th style="padding:0.5rem;text-align:center;">القيمة</th>
          <th style="padding:0.5rem;text-align:center;">المعيار</th>
          <th style="padding:0.5rem;text-align:center;">الانحراف %</th>
          <th style="padding:0.5rem;text-align:center;">z</th>
          <th style="padding:0.5rem;text-align:center;border-radius:0 0 0 6px;">الشدة</th>
        </tr></thead><tbody>
        ${anomalies.map((a, i) => {
          const sev = a.severity === 'critical'
            ? '<span style="color:#dc2626;font-weight:800;">حرج</span>'
            : '<span style="color:#f59e0b;font-weight:800;">تحذير</span>';
          const typeLabel = a.type === 'cross_sectional' ? 'مقابل النظيرات' : 'مقابل تاريخها';
          const devColor = a.deviation_pct > 0 ? '#dc2626' : '#16a34a';
          return `<tr style="border-bottom:1px solid #e5e7eb;background:${i % 2 === 0 ? '#fff' : '#fef2f2'};">
            <td style="padding:0.5rem;text-align:center;font-weight:600;">${a.governorate}</td>
            <td style="padding:0.5rem;text-align:right;">${a.metric_ar}${a.small_sample ? ' <span title="عينة صغيرة" style="color:#f59e0b;">⚠</span>' : ''}</td>
            <td style="padding:0.5rem;text-align:center;font-size:0.72rem;color:#6b7280;">${typeLabel}</td>
            <td style="padding:0.5rem;text-align:center;font-weight:700;">${_fmtNum(a.observed, 1)}</td>
            <td style="padding:0.5rem;text-align:center;">${_fmtNum(a.benchmark, 1)}</td>
            <td style="padding:0.5rem;text-align:center;font-weight:700;color:${devColor};">${a.deviation_pct > 0 ? '+' : ''}${a.deviation_pct}%</td>
            <td style="padding:0.5rem;text-align:center;">${_fmtNum(a.z_score, 1)}</td>
            <td style="padding:0.5rem;text-align:center;">${sev}</td>
          </tr>`;
        }).join('')}
        </tbody></table>`;
      anomNote.textContent = 'الشذوذ العرضي: |z| ≥ 2 مقابل معيار الإقليم. التاريخي: |z| ≥ 2 مقابل متوسط أشهر المحافظة السابقة (يلزم 3 أشهر). العينات الصغيرة تخفّض الشدة.';
    } else {
      anomTable.innerHTML = '<p style="color:#999;font-size:0.8rem;">لا توجد شذوذ إقليمية (|z| ≥ 2) في هذا الشهر.</p>';
      anomNote.textContent = '';
    }
  }

  // ── Risk factor explanations (SHAP-style) ──
  const explains = data.risk_explanations || [];
  const explainEl = document.getElementById('smart-regional-explain');
  const explainNote = document.getElementById('smart-regional-explain-note');
  if (explainEl) {
    if (explains.length > 0) {
      explainEl.innerHTML = explains.map(e => {
        const lvl = _riskBadge(e.level_label_ar || e.level, e.level);
        const factors = (e.factors || []).map(f => {
          const barW = Math.min(100, (f.contribution / 35) * 100);
          const tooltip = `${f.arabic_label}: ${_fmtNum(f.observed, 1)} مقابل ${_fmtNum(f.benchmark, 1)} (انحراف ${f.deviation_pct > 0 ? '+' : ''}${f.deviation_pct}%)`;
          return `<div style="margin-bottom:0.45rem;" title="${tooltip}">
            <div style="display:flex;justify-content:space-between;font-size:0.7rem;margin-bottom:0.15rem;">
              <span style="color:#374151;font-weight:600;">${f.arabic_label}</span>
              <span style="color:#b91c1c;font-weight:800;">+${f.contribution} نقطة</span>
            </div>
            <div style="background:#fee2e2;border-radius:4px;height:8px;">
              <div style="background:${f.feature === 'quality' ? '#f59e0b' : '#dc2626'};height:8px;border-radius:4px;width:${barW}%;"></div>
            </div>
          </div>`;
        }).join('');
        return `<div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;padding:0.7rem 0.8rem;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;">
            <span style="font-weight:700;font-size:0.82rem;color:#7c2d12;">${e.governorate}</span>
            ${lvl}
          </div>
          ${factors || '<span style="font-size:0.72rem;color:#999;">لا عوامل دافعة مرتفعة (الدرجة منخفضة).</span>'}
        </div>`;
      }).join('');
      explainNote.textContent = 'تفكيك درجة الخطر إلى مساهماتها الفعلية (نقاط في الدرجة، بلا نموذج إضافي على بيانات صغيرة). التمرير على كل عامل يعرض بياناته الفعلية مقابل المعيار. الارتباط لا يعني سببّية.';
    } else {
      explainEl.innerHTML = '<p style="color:#999;font-size:0.8rem;">لا توجد درجات خطر لحساب تفكيكها.</p>';
      explainNote.textContent = '';
    }
  }

  // ── Ranking table ──
  if (govs.length > 0) {
    document.getElementById('smart-regional-ranking-table').innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:0.78rem;direction:rtl;">
      <thead><tr style="background:#0d9488;color:white;">
        <th style="padding:0.5rem;text-align:center;border-radius:0 0 6px 0;">#</th>
        <th style="padding:0.5rem;text-align:right;">المحافظة</th>
        <th style="padding:0.5rem;text-align:center;">المستشفيات</th>
        <th style="padding:0.5rem;text-align:center;">المواليد</th>
        <th style="padding:0.5rem;text-align:center;">وفيات المواليد /1000</th>
        <th style="padding:0.5rem;text-align:center;">مئوي</th>
        <th style="padding:0.5rem;text-align:center;">الانحراف %</th>
        <th style="padding:0.5rem;text-align:center;">MMR</th>
        <th style="padding:0.5rem;text-align:center;">ولادات ميتة /1000</th>
        <th style="padding:0.5rem;text-align:center;">قيصرية %</th>
        <th style="padding:0.5rem;text-align:center;border-radius:0 0 0 6px;">الخطر</th>
      </tr></thead><tbody>
      ${[...govs].sort((a, b) => (b.rates.nmr.value || 0) - (a.rates.nmr.value || 0)).map((g, i) => {
        const nmr = g.rates.nmr || {};
        const risk = risks.find(r => r.governorate === g.governorate);
        const devColor = nmr.deviation_pct > 0 ? '#dc2626' : '#16a34a';
        return `<tr style="border-bottom:1px solid #e5e7eb;background:${i % 2 === 0 ? '#fff' : '#f0fdfa'};">
          <td style="padding:0.5rem;text-align:center;color:#888;">${i + 1}</td>
          <td style="padding:0.5rem;text-align:right;font-weight:600;">${g.governorate}</td>
          <td style="padding:0.5rem;text-align:center;">${g.hospital_count}</td>
          <td style="padding:0.5rem;text-align:center;">${_fmtNum(g.births)}</td>
          <td style="padding:0.5rem;text-align:center;font-weight:700;">${_fmtNum(nmr.value, 2)}</td>
          <td style="padding:0.5rem;text-align:center;">${_fmtNum(nmr.percentile, 0)}%</td>
          <td style="padding:0.5rem;text-align:center;font-weight:700;color:${devColor};">${nmr.deviation_pct !== null && nmr.deviation_pct !== undefined ? (nmr.deviation_pct > 0 ? '+' : '') + nmr.deviation_pct + '%' : '-'}</td>
          <td style="padding:0.5rem;text-align:center;">${_fmtNum(g.rates.mmr.value, 1)}</td>
          <td style="padding:0.5rem;text-align:center;">${_fmtNum(g.rates.stillbirth_rate.value, 1)}</td>
          <td style="padding:0.5rem;text-align:center;">${_fmtNum(g.rates.cs_rate.value, 1)}</td>
          <td style="padding:0.5rem;text-align:center;">${risk ? _riskBadge(risk.level_label_ar, risk.level) : '-'}</td>
        </tr>`;
      }).join('')}
      </tbody></table>`;
  }

  // ── Trends ──
  if (trends.length > 0) {
    document.getElementById('smart-regional-trends').innerHTML = trends.map(t => {
      const isBad = t.direction === 'worsening' || t.direction === 'spike';
      const border = isBad ? '#fca5a5' : '#86efac';
      const bg = isBad ? '#fef2f2' : '#f0fdf4';
      const icon = t.direction === 'worsening' ? '&#128200;&#65039;' : t.direction === 'improving' ? '&#128200;&#65039;' : '&#9889;&#65039;';
      const trendColor = t.direction === 'worsening' ? '#dc2626' : t.direction === 'improving' ? '#16a34a' : '#f59e0b';
      return `<div style="background:${bg};border:1px solid ${border};border-radius:8px;padding:0.7rem 0.8rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.3rem;">
          <span style="font-weight:700;font-size:0.8rem;color:#134e4a;">${t.governorate} — ${t.metric_ar}</span>
          <span style="font-size:0.68rem;font-weight:700;color:${trendColor};">${t.direction === 'worsening' ? 'تدهور' : t.direction === 'improving' ? 'تحسّن' : 'طفرة'}</span>
        </div>
        <div style="font-size:0.76rem;color:#374151;line-height:1.5;">${t.summary_ar || ''}</div>
      </div>`;
    }).join('');
    document.getElementById('smart-regional-trends-note').textContent = 'الاتجاهات تُكشف بانحدار خطي (R² ≥ 0.5 وميل ≥ 3% شهرياً) أو بانحراف |z| ≥ 2 لآخر شهر — لا يُعلَّم التقلّب العشوائي اتجاهاً.';
  } else {
    document.getElementById('smart-regional-trends').innerHTML = '<p style="color:#999;font-size:0.8rem;">لا توجد اتجاهات إقليمية واضحة (يلزم 3 أشهر على الأقل).</p>';
    document.getElementById('smart-regional-trends-note').textContent = '';
  }
}

window.smartDrilldown = async function(hospitalId) {
  if (!smartCurrentData || !smartCurrentData.data) return;
  const d = smartCurrentData.data;
  const anomaly = d.anomalies?.find(a => parseInt(a.hospital_id, 10) === hospitalId);
  const explanation = d.explanations?.find(e => parseInt(e.hospital_id, 10) === hospitalId);

  if (!anomaly) return;

  document.getElementById('smart-drilldown-name').textContent = anomaly.hospital_name || '';
  document.getElementById('smart-drilldown-modal').style.display = 'flex';
  document.getElementById('smart-drilldown-modal').scrollIntoView({behavior: 'smooth'});

  if (explanation?.top_factors && explanation.top_factors.length > 0) {
    const factors = explanation.top_factors;
    const wfData = [{
      type: 'waterfall', orientation: 'v',
      x: factors.map(f => smartTranslateFeature(f.arabic_label)),
      y: factors.map(f => f.shap_value),
      connector: {line: {color: '#ccc'}},
      // الإسهام السالب يزيد الشذوذ => يظهر بالأحمر (العامل المسؤول)، الموجب بالأزرق
      decreasing: {marker: {color: SMART_COLORS.shap_positive}},
      increasing: {marker: {color: SMART_COLORS.shap_negative}},
      text: factors.map(f => f.shap_value > 0 ? '+' + f.shap_value.toFixed(3) : f.shap_value.toFixed(3)),
      textposition: 'outside',
    }];
    Plotly.newPlot('smart-shap-waterfall', wfData, { margin: {t: 20, b: 80, l: 60, r: 20}, yaxis: {title: 'قيمة SHAP'} });
  } else {
    Plotly.purge('smart-shap-waterfall');
  }
  document.getElementById('smart-drilldown-text').textContent = explanation?.text_explanation || 'لا توجد تفسيرات متاحة.';

  // جدول قيم العوامل الفعلية مقابل متوسط النظير (من التحليل الطبقي)
  renderDrilldownFactorTable(d, hospitalId, explanation);

  try {
    const trendRes = await apiSmartGet(`/smart/trend/${hospitalId}`);
    if (trendRes?.trend?.length > 0) {
      const trend = trendRes.trend;
      const tColors = trend.map(t => t.severity === 'critical' ? SMART_COLORS.critical : t.severity === 'warning' ? SMART_COLORS.warning : SMART_COLORS.normal);
      Plotly.newPlot('smart-trend-line', [{ type: 'scatter', mode: 'lines+markers', x: trend.map(t => t.month), y: trend.map(t => t.anomaly_score), marker: { size: 10, color: tColors }, line: { color: '#1a237e', width: 2 }, text: trend.map(t => `${t.month}<br>الدرجة: ${t.anomaly_score.toFixed(2)}<br>الحالة: ${t.severity === 'critical' ? 'حرج' : t.severity === 'warning' ? 'تنبيه' : 'طبيعي'}`), hoverinfo: 'text' }], { shapes: [
        { type: 'rect', x0: 0, x1: 1, y0: 0, y1: 0.3, xref: 'paper', fillcolor: SMART_COLORS.normal, opacity: 0.1 },
        { type: 'rect', x0: 0, x1: 1, y0: 0.3, y1: 0.6, xref: 'paper', fillcolor: SMART_COLORS.warning, opacity: 0.1 },
        { type: 'rect', x0: 0, x1: 1, y0: 0.6, y1: 1, xref: 'paper', fillcolor: SMART_COLORS.critical, opacity: 0.1 },
      ], xaxis: {title: 'الشهر'}, yaxis: {title: 'درجة الشذوذ', range: [0, 1]}, margin: {t: 20, b: 40, l: 50, r: 20} });
    } else {
      Plotly.purge('smart-trend-line');
    }
  } catch (e) {
    Plotly.purge('smart-trend-line');
  }
};

function renderDrilldownFactorTable(d, hospitalId, explanation) {
  const container = document.getElementById('smart-drilldown-factors');
  if (!container) return;
  const factors = explanation?.top_factors || [];
  if (factors.length === 0) {
    container.innerHTML = '<p style="color:#999;font-size:0.78rem;">لا توجد عوامل SHAP متاحة.</p>';
    return;
  }
  const strat = (d.stratified || []).filter(s => parseInt(s.hospital_id, 10) === hospitalId);
  if (strat.length === 0) {
    container.innerHTML = '<p style="color:#999;font-size:0.78rem;">لا توجد بيانات مقارنة طبقية لهذا المستشفى في الشهر الحالي.</p>';
    return;
  }
  const stratMap = {};
  strat.forEach(s => { stratMap[s.indicator] = s; });

  const rows = factors.map((f, i) => {
    const s = stratMap[f.feature];
    const fmt = (v, ind) => (ind === 'cs_rate' ? `${v.toFixed(1)}%` : v.toFixed(1));
    const dev = s ? s.deviation_pct : null;
    const devColor = dev === null ? '#999' : Math.abs(dev) > 30 ? SMART_COLORS.critical : Math.abs(dev) > 15 ? SMART_COLORS.warning : SMART_COLORS.normal;
    const devText = dev === null ? '-' : (dev > 0 ? '+' : '') + dev.toFixed(1) + '%';
    const sh = f.shap_value;
    // الإسهام السالب = العامل المسؤول (يزيد الشذوذ) => أحمر، الموجب أزرق
    const isDriver = (f.direction || (sh < 0 ? 'increases_anomaly' : 'decreases_anomaly')) === 'increases_anomaly';
    const shColor = isDriver ? SMART_COLORS.shap_positive : SMART_COLORS.shap_negative;
    return `<tr style="border-bottom:1px solid #f0f0f0;background:${i % 2 === 0 ? '#fff' : '#f9fafb'};">
      <td style="padding:0.4rem 0.5rem;text-align:center;color:#999;width:30px;">${i + 1}</td>
      <td style="padding:0.4rem 0.5rem;text-align:right;font-weight:600;font-size:0.78rem;">${smartTranslateFeature(f.arabic_label)}</td>
      <td style="padding:0.4rem 0.5rem;text-align:center;"><span style="font-weight:700;color:${shColor};font-size:0.78rem;">${sh > 0 ? '+' : ''}${sh.toFixed(3)}</span></td>
      <td style="padding:0.4rem 0.5rem;text-align:center;font-size:0.78rem;font-weight:600;">${s ? fmt(s.hospital_value, s.indicator) : '-'}</td>
      <td style="padding:0.4rem 0.5rem;text-align:center;font-size:0.78rem;color:#555;">${s ? fmt(s.peer_group_mean, s.indicator) : '-'}</td>
      <td style="padding:0.4rem 0.5rem;text-align:center;"><span style="display:inline-block;background:${devColor}18;color:${devColor};padding:0.1rem 0.4rem;border-radius:8px;font-weight:700;font-size:0.72rem;">${devText}</span></td>
    </tr>`;
  }).join('');

  container.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:0.75rem;direction:rtl;">
    <thead><tr style="background:#f1f5f9;border-bottom:2px solid #e2e8f0;">
      <th style="padding:0.45rem 0.5rem;text-align:center;width:30px;">#</th>
      <th style="padding:0.45rem 0.5rem;text-align:right;">العامل</th>
      <th style="padding:0.45rem 0.5rem;text-align:center;">SHAP</th>
      <th style="padding:0.45rem 0.5rem;text-align:center;">القيمة الفعلية</th>
      <th style="padding:0.45rem 0.5rem;text-align:center;">متوسط النظير</th>
      <th style="padding:0.45rem 0.5rem;text-align:center;">الانحراف</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

// توقعات الشهر القادم لمستشفى محدد: المؤشرات القيادية الصاعدة بأوزانها
// + النتائج المتوقعة التي تسبقها + زر ربط بتحليل السبب الجذري
function renderHospitalForecast(forecast, hospitalId, month) {
  const container = document.getElementById('smart-hospital-forecast');
  if (!container) return;
  if (!forecast || !forecast.leading_rising || !forecast.leading_rising.length) {
    container.innerHTML = '';
    return;
  }

  const severityColor = forecast.severity === 'critical' ? SMART_COLORS.critical
    : forecast.severity === 'warning' ? SMART_COLORS.warning : '#16a34a';
  const severityLabel = forecast.severity === 'critical' ? 'حرج'
    : forecast.severity === 'warning' ? 'تحذير' : 'متابعة';
  const leadsBadge = forecast.discovered_leads
    ? '<span style="font-size:0.6rem;background:#7c3aed;color:#fff;padding:2px 8px;border-radius:10px;font-weight:700;" title="الأوزان مبنية من علاقات متأخرة مكتشفة (FDR + غرانجر)">🧭 قيادة مكتشفة</span>'
    : '<span style="font-size:0.6rem;background:#6b7280;color:#fff;padding:2px 8px;border-radius:10px;font-weight:700;" title="بيانات غير كافية — أوزان افتراضية 1 لكل مؤشر">📋 قيادة افتراضية</span>';

  const rows = forecast.leading_rising.map(r => {
    const delta = r.delta_pct !== null && r.delta_pct !== undefined
      ? `+${r.delta_pct.toFixed(1)}%` : '';
    const outcomes = (r.leads_to && r.leads_to.length)
      ? r.leads_to.map(o =>
          `<span style="display:inline-block;margin:0.15rem 0;padding:0.15rem 0.5rem;background:#f5f3ff;border:1px solid #ddd6fe;border-radius:5px;font-size:0.72rem;color:#5b21b6;">
             يُتوقع <b>${o.outcome_ar}</b> بعد ${o.lag_word}${o.granger_pearson ? ` (قوة ${Math.abs(o.granger_pearson).toFixed(2)})` : ''}
           </span>`).join(' ')
      : '<span style="font-size:0.72rem;color:#9ca3af;">لا توجد نتيجة موثوقة مرتبطة بهذا المؤشر</span>';
    return `
      <div style="background:#fff;border:1px solid #e5e7eb;border-right:4px solid #7c3aed;border-radius:8px;padding:0.7rem 0.9rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:0.5rem;flex-wrap:wrap;">
          <div style="font-weight:700;color:#1a237e;font-size:0.85rem;">▲ ${r.metric_ar}</div>
          <div style="display:flex;gap:0.4rem;align-items:center;">
            <span style="font-size:0.72rem;font-weight:600;color:#dc2626;">${delta}</span>
            <span style="font-size:0.65rem;background:#f3f4f6;color:#555;padding:2px 8px;border-radius:10px;">وزن ${r.weight}</span>
          </div>
        </div>
        <div style="font-size:0.72rem;color:#666;margin-top:0.3rem;">
          ${r.previous !== null && r.previous !== undefined ? `القيمة: ${r.previous} ← ${r.current}` : ''}
        </div>
        <div style="margin-top:0.4rem;display:flex;flex-wrap:wrap;gap:0.35rem;">${outcomes}</div>
      </div>`;
  }).join('');

  container.innerHTML = `
    <div style="border:2px solid ${severityColor};border-radius:10px;background:${forecast.severity === 'none' ? '#f9fafb' : '#fff7f7'};">
      <div style="display:flex;justify-content:space-between;align-items:center;padding:0.7rem 1rem;border-bottom:1px solid #f3e8e8;flex-wrap:wrap;gap:0.4rem;">
        <div style="font-weight:700;color:#333;font-size:0.9rem;">🔮 توقعات الشهر القادم</div>
        <div style="display:flex;gap:0.4rem;align-items:center;">${leadsBadge}
          <span style="font-size:0.7rem;font-weight:700;color:#fff;background:${severityColor};padding:2px 10px;border-radius:12px;">${severityLabel} · ${(forecast.probability * 100).toFixed(0)}%</span>
        </div>
      </div>
      <div style="padding:0.8rem 1rem;display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:0.6rem;">${rows}</div>
      <div style="padding:0.5rem 1rem 0.8rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;">
        <span style="font-size:0.72rem;color:#6b7280;">${forecast.note_ar || ''} — ثقة ${forecast.confidence_label_ar || ''}</span>
        <button onclick="window.smartGoRootCause(${hospitalId}, '${month}')" class="btn btn-sm" style="font-size:0.75rem;padding:0.3rem 0.8rem;background:#1a237e;color:#fff;border:none;border-radius:6px;cursor:pointer;">🔍 تحليل السبب الجذري</button>
      </div>
    </div>`;
}

async function loadHospitalAnalysis(hospitalId, currentMonth) {
  const panel = document.getElementById('smart-hospital-panel');
  panel.style.display = 'block';
  document.getElementById('smart-hospital-name').textContent = 'جاري التحميل...';

  try {
    const drilldown = await apiSmartGet(`/smart/drilldown/${hospitalId}/${currentMonth}`);
    document.getElementById('smart-hospital-name').textContent = drilldown.hospital_name || '';

    renderHospitalForecast(drilldown.forecast, hospitalId, currentMonth);

    const anomaly = drilldown.anomaly;
    const explanation = drilldown.explanation;

    if (drilldown.all_months && drilldown.anomalies && drilldown.anomalies.length > 0) {
      const allAnomalies = drilldown.anomalies;
      const allExplanations = drilldown.explanations || [];

      const avgScore = allAnomalies.reduce((s, a) => s + a.anomaly_score, 0) / allAnomalies.length;
      const critCount = allAnomalies.filter(a => a.severity === 'critical').length;
      const warnCount = allAnomalies.filter(a => a.severity === 'warning').length;
      const normCount = allAnomalies.filter(a => a.severity === 'normal').length;

      const latestAnomaly = allAnomalies[allAnomalies.length - 1];
      const latestExplanation = allExplanations[allExplanations.length - 1];

      const kpiHtml = `
        <div class="card" style="text-align:center;padding:0.8rem;border-radius:8px;border-top:3px solid ${SMART_COLORS.warning};">
          <div style="font-size:1.8rem;font-weight:700;color:#1a237e;">${avgScore.toFixed(2)}</div>
          <div style="font-size:0.75rem;color:#444;font-weight:600;">متوسط الدرجات</div>
          <div style="font-size:0.65rem;color:#888;margin-top:0.2rem;">${allAnomalies.length} شهر مسجل</div>
        </div>
        <div class="card" style="text-align:center;padding:0.8rem;border-radius:8px;border-top:3px solid ${critCount > 0 ? SMART_COLORS.critical : SMART_COLORS.normal};">
          <div style="font-size:1.3rem;font-weight:700;color:${SMART_COLORS.critical};">${critCount}</div>
          <div style="font-size:0.75rem;color:#444;font-weight:600;">أشهر حرجة</div>
          <div style="font-size:0.65rem;color:#888;margin-top:0.2rem;">${warnCount} تنبيه | ${normCount} طبيعي</div>
        </div>
        <div class="card" style="text-align:center;padding:0.8rem;border-radius:8px;">
          <div style="font-size:0.85rem;font-weight:600;">${latestAnomaly.severity === 'critical' ? '❌ حرج' : latestAnomaly.severity === 'warning' ? '⚠️ تنبيه' : '✅ طبيعي'}</div>
          <div style="font-size:0.75rem;color:#666;">آخر شهر (${latestAnomaly.month})</div>
        </div>
        <div class="card" style="text-align:center;padding:0.8rem;border-radius:8px;">
          <div style="font-size:0.85rem;font-weight:600;color:#8b5cf6;">${latestExplanation?.top_factors?.[0] ? smartTranslateFeature(latestExplanation.top_factors[0].arabic_label) : '-'}</div>
          <div style="font-size:0.75rem;color:#666;">آخر عامل أساسي</div>
        </div>
        <div class="card" style="text-align:center;padding:0.8rem;border-radius:8px;">
          <div style="font-size:0.85rem;font-weight:600;color:#333;">${smartTranslateFeature('governorate_' + latestAnomaly.governorate)}</div>
          <div style="font-size:0.75rem;color:#666;">المحافظة</div>
        </div>
        <div class="card" style="text-align:center;padding:0.8rem;border-radius:8px;">
          <div style="font-size:0.78rem;color:#444;line-height:1.5;">${latestExplanation?.text_explanation || 'لا توجد تفسيرات'}</div>
          <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;">آخر تفسير SHAP</div>
        </div>
      `;
      document.getElementById('smart-hospital-kpis').innerHTML = kpiHtml;

      const tColors = allAnomalies.map(a => a.severity === 'critical' ? SMART_COLORS.critical : a.severity === 'warning' ? SMART_COLORS.warning : SMART_COLORS.normal);
      const traces = [{
        type: 'scatter', mode: 'lines+markers',
        x: allAnomalies.map(a => a.month),
        y: allAnomalies.map(a => a.anomaly_score),
        marker: { size: 10, color: tColors, line: { width: 2, color: '#fff' } },
        line: { color: '#1a237e', width: 2 },
        text: allAnomalies.map(a => `${a.month}<br>الدرجة: ${a.anomaly_score.toFixed(2)}<br>الحالة: ${a.severity === 'critical' ? 'حرج' : a.severity === 'warning' ? 'تنبيه' : 'طبيعي'}`),
        hoverinfo: 'text',
        name: 'درجة الشذوذ',
      }];
      const shapes = [
        { type: 'rect', x0: 0, x1: 1, y0: 0, y1: 0.3, xref: 'paper', fillcolor: SMART_COLORS.normal, opacity: 0.08 },
        { type: 'rect', x0: 0, x1: 1, y0: 0.3, y1: 0.6, xref: 'paper', fillcolor: SMART_COLORS.warning, opacity: 0.08 },
        { type: 'rect', x0: 0, x1: 1, y0: 0.6, y1: 1, xref: 'paper', fillcolor: SMART_COLORS.critical, opacity: 0.08 },
        { type: 'line', x0: 0, x1: 1, y0: 0.3, y1: 0.3, xref: 'paper', line: { color: SMART_COLORS.warning, width: 1, dash: 'dash' } },
        { type: 'line', x0: 0, x1: 1, y0: 0.6, y1: 0.6, xref: 'paper', line: { color: SMART_COLORS.critical, width: 1, dash: 'dash' } },
      ];
      Plotly.newPlot('smart-hospital-trend', traces, {
        shapes,
        xaxis: {title: 'الشهر', tickangle: -45},
        yaxis: {title: 'درجة الشذوذ', range: [0, 1]},
        margin: {t: 20, b: 60, l: 50, r: 20},
        legend: {orientation: 'h', y: 1.1},
        plot_bgcolor: 'white', paper_bgcolor: 'white',
      });
      document.getElementById('smart-hospital-trend-text').textContent =
        `ملخص ${allAnomalies.length} شهر: ${critCount} حرج، ${warnCount} تنبيه، ${normCount} طبيعي. المتوسط: ${avgScore.toFixed(2)}`;
    } else {
      const kpiHtml = `
        <div class="card" style="text-align:center;padding:0.8rem;border-radius:8px;border-top:3px solid ${anomaly ? (anomaly.severity === 'critical' ? SMART_COLORS.critical : anomaly.severity === 'warning' ? SMART_COLORS.warning : SMART_COLORS.normal) : '#ccc'};">
          <div style="font-size:1.8rem;font-weight:700;color:${anomaly ? (anomaly.severity === 'critical' ? SMART_COLORS.critical : anomaly.severity === 'warning' ? SMART_COLORS.warning : SMART_COLORS.normal) : '#666'};">${anomaly ? anomaly.anomaly_score.toFixed(2) : '-'}</div>
          <div style="font-size:0.75rem;color:#444;font-weight:600;">درجة الشذوذ</div>
          <div style="font-size:0.65rem;color:#888;margin-top:0.2rem;">${anomaly ? (anomaly.severity === 'critical' ? 'تتجاوز 0.6 - يحتاج تدخل' : anomaly.severity === 'warning' ? 'بين 0.3 و 0.6 - يحتاج مراقبة' : 'أقل من 0.3 - ضمن الطبيعي') : ''}</div>
        </div>
        <div class="card" style="text-align:center;padding:0.8rem;border-radius:8px;">
          <div style="font-size:1rem;font-weight:600;">${anomaly ? (anomaly.severity === 'critical' ? '❌ حرج' : anomaly.severity === 'warning' ? '⚠️ تنبيه' : '✅ طبيعي') : '-'}</div>
          <div style="font-size:0.75rem;color:#666;">الحالة</div>
        </div>
        <div class="card" style="text-align:center;padding:0.8rem;border-radius:8px;">
          <div style="font-size:0.85rem;font-weight:600;word-break:break-word;">${anomaly ? smartTranslateFeature('governorate_' + anomaly.governorate) : '-'}</div>
          <div style="font-size:0.75rem;color:#666;">المحافظة</div>
        </div>
        <div class="card" style="text-align:center;padding:0.8rem;border-radius:8px;">
          <div style="font-size:0.85rem;font-weight:600;color:#8b5cf6;">${explanation?.top_factors?.[0] ? smartTranslateFeature(explanation.top_factors[0].arabic_label) : '-'}</div>
          <div style="font-size:0.75rem;color:#666;">العامل الأساسي للشذوذ</div>
          <div style="font-size:0.65rem;color:#888;margin-top:0.2rem;">${explanation?.top_factors?.[0] ? (explanation.top_factors[0].shap_value > 0 ? 'يُزيّد من الدرجة' : 'يُقلّص من الدرجة') : ''}</div>
        </div>
        <div class="card" style="text-align:center;padding:0.8rem;border-radius:8px;">
          <div style="font-size:0.8rem;color:#444;line-height:1.5;">${explanation?.text_explanation || 'لا توجد تفسيرات'}</div>
          <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;">تفسير SHAP</div>
        </div>
        <div class="card" style="text-align:center;padding:0.8rem;border-radius:8px;">
          <div style="font-size:0.75rem;color:#666;line-height:1.5;">
            ${anomaly ? Object.entries(anomaly.method_scores || {}).map(([k, v]) => {
              const labels = {isolation_forest: 'IF', lof: 'LOF', mahalanobis: 'Mahal', residual: 'Resid'};
              return `<span style="display:inline-block;margin:0.1rem;padding:0.1rem 0.3rem;background:#f3f4f6;border-radius:3px;font-size:0.65rem;">${labels[k] || k}: ${v.toFixed(2)}</span>`;
            }).join(' ') : ''}
          </div>
          <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;">دروس الخصائص</div>
        </div>
      `;
      document.getElementById('smart-hospital-kpis').innerHTML = kpiHtml;

      const trendRes = await apiSmartGet(`/smart/trend/${hospitalId}`);
      if (trendRes?.trend?.length > 0) {
        const trend = trendRes.trend;
        const tColors = trend.map(t => t.severity === 'critical' ? SMART_COLORS.critical : t.severity === 'warning' ? SMART_COLORS.warning : SMART_COLORS.normal);

        const traces = [
          {
            type: 'scatter', mode: 'lines+markers',
            x: trend.map(t => t.month),
            y: trend.map(t => t.anomaly_score),
            marker: { size: 12, color: tColors, line: { width: 2, color: '#fff' } },
            line: { color: '#1a237e', width: 2 },
            text: trend.map(t => `${t.month}<br>الدرجة: ${t.anomaly_score.toFixed(2)}<br>الحالة: ${t.severity === 'critical' ? 'حرج' : t.severity === 'warning' ? 'تنبيه' : 'طبيعي'}`),
            hoverinfo: 'text',
            name: 'درجة الشذوذ',
          }
        ];
        const shapes = [
          { type: 'rect', x0: 0, x1: 1, y0: 0, y1: 0.3, xref: 'paper', fillcolor: SMART_COLORS.normal, opacity: 0.08 },
          { type: 'rect', x0: 0, x1: 1, y0: 0.3, y1: 0.6, xref: 'paper', fillcolor: SMART_COLORS.warning, opacity: 0.08 },
          { type: 'rect', x0: 0, x1: 1, y0: 0.6, y1: 1, xref: 'paper', fillcolor: SMART_COLORS.critical, opacity: 0.08 },
          { type: 'line', x0: 0, x1: 1, y0: 0.3, y1: 0.3, xref: 'paper', line: { color: SMART_COLORS.warning, width: 1, dash: 'dash' } },
          { type: 'line', x0: 0, x1: 1, y0: 0.6, y1: 0.6, xref: 'paper', line: { color: SMART_COLORS.critical, width: 1, dash: 'dash' } },
        ];
        Plotly.newPlot('smart-hospital-trend', traces, {
          shapes,
          xaxis: {title: 'الشهر', tickangle: -45},
          yaxis: {title: 'درجة الشذوذ', range: [0, 1]},
          margin: {t: 20, b: 60, l: 50, r: 20},
          legend: {orientation: 'h', y: 1.1},
        });

        const critMonths = trend.filter(t => t.severity === 'critical').length;
        const warnMonths = trend.filter(t => t.severity === 'warning').length;
        const normalMonths = trend.filter(t => t.severity === 'normal').length;
        document.getElementById('smart-hospital-trend-text').textContent =
          `ملخص ${trend.length} شهر: ${critMonths} حرج، ${warnMonths} تنبيه، ${normalMonths} طبيعي.`;
      } else {
        Plotly.purge('smart-hospital-trend');
        document.getElementById('smart-hospital-trend-text').textContent = 'لا توجد بيانات اتجاه متاحة.';
      }
    }
  } catch (e) {
    document.getElementById('smart-hospital-name').textContent = 'خطأ في التحميل';
    console.error('Hospital analysis error:', e);
  }
}

async function smartExportData() {
  const scope = document.getElementById('smart-export-scope')?.value || 'current';
  const month = scope === 'all' ? 'all' : (smartCurrentMonth || document.getElementById('smart-month-select')?.value || '');
  const base = document.getElementById('apiBase')?.value || '';
  const url = `${base}/export/full-data?month=${encodeURIComponent(month)}&lang=${smartReportLang}`;
  document.getElementById('smart-status').textContent = 'جاري تصدير البيانات...';
  smartShowLoading();
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `health_export_${month}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
    document.getElementById('smart-status').textContent = 'تم تصدير البيانات بنجاح';
  } catch (e) {
    document.getElementById('smart-status').textContent = 'خطأ في التصدير: ' + e.message;
  } finally {
    smartHideLoading();
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  التقرير الشامل — مدمج من تبويب comparative
// ═══════════════════════════════════════════════════════════════════════

let smartReportLang = 'ar';
let smartComparisonChart = null;
let smartReportGenerating = false;
let smartTimelineLoaded = false;

const smartReportLangMap = {
  ar: {
    title: '📋 التقرير الشامل الذكي',
    labelComparison: 'طريقة المقارنة',
    btnGenerate: '🤖 توليد التقرير الشامل',
    loadingText: 'جاري توليد التقرير الذكي الشامل...',
    sectionExecutive: '📋 الملخص التنفيذي',
    sectionIndicators: '📊 تحليل المؤشرات',
    sectionAnomalies: '🔍 تحليل الشذوذ',
    sectionClustering: '🔗 التجميع والارتباطات',
    sectionStratified: '📈 المقارنة الطبقية',
    sectionRecommendations: '💡 التوصيات الإجرائية',
    chartTitle: 'مقارنة أداء المستشفيات عبر الأشهر',
    peerTitle: 'مقارنة المستشفيات ببعضها',
    peerRank: 'الترتيب',
    peerHospital: 'المستشفى',
    peerPercentile: 'النسبة المئوية',
    peerAssessment: 'التقييم',
    kpiTotal: 'إجمالي المستشفيات',
    kpiAnomalies: 'مستشفيات شاذة',
    kpiMonthStatus: 'حالة الشهر',
    kpiTopFactor: 'العامل الأكثر تأثيراً',
  },
  en: {
    title: '📋 Smart Comprehensive Report',
    labelComparison: 'Comparison Type:',
    btnGenerate: '🤖 Generate Smart Report',
    loadingText: 'Generating smart report...',
    sectionExecutive: '📋 Executive Summary',
    sectionIndicators: '📊 Indicator Analysis',
    sectionAnomalies: '🔍 Anomaly Analysis',
    sectionClustering: '🔗 Clustering & Correlations',
    sectionStratified: '📈 Stratified Comparison',
    sectionRecommendations: '💡 Recommendations',
    chartTitle: 'Hospital Performance Comparison Over Time',
    peerTitle: 'Hospital Peer Comparison',
    peerRank: 'Rank',
    peerHospital: 'Hospital',
    peerPercentile: 'Percentile',
    peerAssessment: 'Assessment',
    kpiTotal: 'Total Hospitals',
    kpiAnomalies: 'Anomalous Hospitals',
    kpiMonthStatus: 'Month Status',
    kpiTopFactor: 'Top Contributing Factor',
  }
};

const smartReportStatusMap = {
  ar: { normal: 'طبيعي', attention_needed: 'يحتاج انتباه', critical: 'حرج' },
  en: { normal: 'Normal', attention_needed: 'Needs Attention', critical: 'Critical' }
};

function smartToggleReportLang() {
  smartReportLang = smartReportLang === 'ar' ? 'en' : 'ar';
  document.getElementById('smart-report-lang-toggle').textContent = smartReportLang === 'ar' ? '🇬🇧 English' : '🇸🇦 العربية';
  smartApplyReportLang(smartReportLang);
  const month = document.getElementById('smart-month-select')?.value;
  if (month && document.getElementById('smart-report-output').style.display !== 'none') {
    smartGenerateComprehensiveReport(month);
  }
}

function smartApplyReportLang(lang) {
  const t = smartReportLangMap[lang];
  if (!t) return;

  document.getElementById('smart-report-title').textContent = t.title;
  document.getElementById('smart-label-comparison').textContent = t.labelComparison;
  document.getElementById('smart-report-generate').textContent = t.btnGenerate;
  document.getElementById('smart-section-executive').textContent = t.sectionExecutive;
  document.getElementById('smart-section-indicators').textContent = t.sectionIndicators;
  document.getElementById('smart-section-anomalies').textContent = t.sectionAnomalies;
  document.getElementById('smart-section-clustering').textContent = t.sectionClustering;
  document.getElementById('smart-section-stratified').textContent = t.sectionStratified;
  document.getElementById('smart-section-recommendations').textContent = t.sectionRecommendations;
  document.getElementById('smart-chart-title').textContent = t.chartTitle;
  document.getElementById('smart-peer-title').textContent = t.peerTitle;
  document.getElementById('smart-peer-rank').textContent = t.peerRank;
  document.getElementById('smart-peer-hospital').textContent = t.peerHospital;
  document.getElementById('smart-peer-percentile').textContent = t.peerPercentile;
  document.getElementById('smart-peer-assessment').textContent = t.peerAssessment;
  document.getElementById('smart-kpi-label-total').textContent = t.kpiTotal;
  document.getElementById('smart-kpi-label-anomalies').textContent = t.kpiAnomalies;
  document.getElementById('smart-kpi-label-month-status').textContent = t.kpiMonthStatus;
  document.getElementById('smart-kpi-label-top-factor').textContent = t.kpiTopFactor;

  ['smart-report-executive-summary', 'smart-report-indicators', 'smart-report-anomalies', 'smart-report-clustering', 'smart-report-stratified', 'smart-report-recommendations'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.style.direction = lang === 'ar' ? 'rtl' : 'ltr';
      el.style.textAlign = lang === 'ar' ? 'right' : 'left';
    }
  });
}

function smartReportShowLoading() {
  const el = document.getElementById('smart-report-status');
  if (el) el.textContent = smartReportLang === 'ar' ? 'جاري توليد التقرير...' : 'Generating report...';
  smartShowLoading();
  smartReportGenerating = true;
}

function smartReportHideLoading() {
  smartReportGenerating = false;
  smartHideLoading();
}

async function smartGenerateComprehensiveReport(month) {
  const selectedMonth = month || document.getElementById('smart-month-select')?.value;
  if (!selectedMonth) return;

  document.getElementById('smart-report-section').style.display = 'block';
  document.getElementById('smart-report-output').style.display = 'none';
  document.getElementById('smart-comparison-chart-container').style.display = 'none';
  document.getElementById('smart-peer-comparison-container').style.display = 'none';
  smartReportShowLoading();

  try {
    const result = await apiSmartGet(`/comparative/comprehensive-report/${selectedMonth}?lang=${smartReportLang}`);
    document.getElementById('smart-report-badge').textContent = result.report_source === 'ai' ? '🤖 ذكاء اصطناعي' : '📊 محلي';
    smartRenderReportSections(result.report);
    if (result.data) {
      smartUpdateReportKPIs(result.data);
      smartRenderDecisionBoard(result.data.decision);
    }

    const hospitalId = document.getElementById('smart-hospital-select')?.value || '';
    const comparisonType = document.getElementById('smart-comparison-type')?.value || 'all';
    await smartGenerateAdvancedComparison(selectedMonth, hospitalId, comparisonType);
    const statusEl = document.getElementById('smart-report-status');
    if (statusEl) statusEl.textContent = smartReportLang === 'ar' ? 'تم توليد التقرير بنجاح' : 'Report generated successfully';
  } catch (e) {
    smartReportError((smartReportLang === 'ar' ? 'خطأ في توليد التقرير: ' : 'Error generating report: ') + e.message);
  } finally {
    smartReportHideLoading();
  }
}

function smartReportError(message) {
  const el = document.getElementById('smart-report-status');
  if (el) el.textContent = message;
  smartShowAlert(message, 'danger');
}

function smartUpdateReportKPIs(data) {
  const dashboard = document.getElementById('smart-report-kpi-dashboard');
  if (!dashboard || !data) return;

  const kpi = data.kpi || {};
  document.getElementById('smart-kpi-total-hospitals').textContent = data.hospitals_count != null ? data.hospitals_count : '-';
  document.getElementById('smart-kpi-anomalies').textContent = kpi.total_anomalies != null ? kpi.total_anomalies : '0';

  const statusKey = kpi.month_status || 'normal';
  const statusEl = document.getElementById('smart-kpi-month-status');
  statusEl.textContent = (smartReportStatusMap[smartReportLang] && smartReportStatusMap[smartReportLang][statusKey]) || statusKey;
  statusEl.className = 'value status-' + statusKey;

  document.getElementById('smart-kpi-top-factor').textContent = kpi.top_contributing_factor || '-';
  dashboard.style.display = 'grid';
}

function smartRenderDecisionBoard(decision) {
  const board = document.getElementById('smart-decision-board');
  if (!board || !decision) return;

  const verdictMap = {
    critical: { label: decision.verdict_label || 'حرج', bg: '#c62828' },
    attention: { label: decision.verdict_label || 'يتطلب انتباهاً', bg: '#e65100' },
    normal: { label: decision.verdict_label || 'مستقر', bg: '#2e7d32' },
  };
  const v = verdictMap[decision.verdict] || verdictMap.normal;
  const verdictEl = document.getElementById('smart-decision-verdict');
  verdictEl.textContent = v.label;
  verdictEl.style.background = v.bg;
  document.getElementById('smart-decision-risk').textContent = 'مؤشر الخطر: ' + (decision.risk_score != null ? decision.risk_score : '-') + '/100';

  // نقاط التركيز الجغرافية
  const hotspotsEl = document.getElementById('smart-decision-hotspots');
  hotspotsEl.innerHTML = (decision.hotspots && decision.hotspots.length)
    ? decision.hotspots.map(h => {
        const col = h.risk_pct >= 50 ? '#c62828' : h.risk_pct >= 25 ? '#e65100' : '#2e7d32';
        return '<div style="margin-bottom:0.3rem;">' +
          '<div style="display:flex;justify-content:space-between;font-size:0.75rem;">' +
            '<span style="font-weight:600;">' + esc(h.governorate) + '</span>' +
            '<span style="color:' + col + ';font-weight:700;">' + h.outliers + ' شاذ · ' + h.risk_pct + '%</span>' +
          '</div>' +
          '<div style="height:4px;background:#e2e8f0;border-radius:2px;overflow:hidden;">' +
            '<div style="width:' + Math.min(100, h.risk_pct) + '%;height:100%;background:' + col + ';"></div>' +
          '</div>' +
        '</div>';
      }).join('')
    : '<div style="color:#94a3b8;font-size:0.75rem;">لا توجد محافظات شاذة هذا الشهر.</div>';

  // الاتجاه الشهري
  const trendEl = document.getElementById('smart-decision-trend');
  const tdir = decision.trend_direction;
  const tArrow = tdir === 'worsening' ? '&#9660;' : tdir === 'improving' ? '&#9650;' : '&#8212;';
  const tCol = tdir === 'worsening' ? '#c62828' : tdir === 'improving' ? '#2e7d32' : '#64748b';
  trendEl.innerHTML = '<span style="font-weight:600;color:' + tCol + ';">' + tArrow + ' ' + esc(decision.trend_summary || '') + '</span>' +
    (decision.trend_changes && decision.trend_changes.length
      ? '<div style="margin-top:0.3rem;">' + decision.trend_changes.map(c => {
          const arrow = c[1] === 'up' ? '▲' : '▼';
          const col = c[1] === 'up' ? '#2e7d32' : '#c62828';
          return '<div style="font-size:0.72rem;color:#555;"><span style="color:' + col + ';">' + arrow + '</span> ' + esc(c[0]) + ': ' + (c[2] > 0 ? '+' : '') + c[2] + '</div>';
        }).join('') + '</div>'
      : '');

  // قائمة المتابعة
  const watchEl = document.getElementById('smart-decision-watchlist');
  watchEl.innerHTML = (decision.watchlist && decision.watchlist.length)
    ? decision.watchlist.map(w => {
        const col = w.severity === 'critical' ? '#c62828' : w.severity === 'warning' ? '#e65100' : '#f9a825';
        return '<div style="display:flex;align-items:center;gap:0.35rem;padding:0.25rem 0;border-bottom:1px dashed #e2e8f0;">' +
          '<span style="width:8px;height:8px;border-radius:50%;background:' + col + ';flex-shrink:0;"></span>' +
          '<span style="font-weight:600;font-size:0.78rem;">' + esc(w.hospital) + '</span>' +
          '<span style="font-size:0.68rem;color:#888;">' + esc(w.governorate) + ' · ' + w.score + '</span>' +
        '</div>';
      }).join('')
    : '<div style="color:#94a3b8;font-size:0.75rem;">لا توجد مستشفيات تحتاج متابعة.</div>';

  // إجراءات الأولوية
  const prioEl = document.getElementById('smart-decision-priorities');
  const prioColors = { critical: '#c62828', high: '#e65100', medium: '#f9a825', low: '#388e3c' };
  prioEl.innerHTML = (decision.priorities && decision.priorities.length)
    ? decision.priorities.map((p, i) => {
        const col = prioColors[p.priority] || '#888';
        return '<div style="display:flex;align-items:center;gap:0.5rem;padding:0.35rem 0.4rem;margin-bottom:0.3rem;background:' + col + '0a;border-radius:6px;border-left:3px solid ' + col + ';">' +
          '<span style="font-size:0.7rem;font-weight:700;color:' + col + ';min-width:1.1rem;">' + (i + 1) + '</span>' +
          '<span style="flex:1;">' +
            '<span style="font-weight:600;font-size:0.78rem;">' + esc(p.action) + '</span>' +
            '<span style="font-size:0.7rem;color:#666;display:block;">&#8592; ' + esc(p.target) + '</span>' +
          '</span>' +
          '<span style="font-size:0.68rem;font-weight:700;color:' + col + ';">أثر ' + Math.round(p.impact || 0) + '%</span>' +
        '</div>';
      }).join('')
    : '<div style="color:#94a3b8;font-size:0.75rem;">لا توجد إجراءات عاجلة.</div>';

  board.style.display = 'block';
}

function smartParseReportSections(reportText) {
  const sections = {};
  const sectionNames = {
    'قرارات تنفيذية': 'smart-report-executive-summary',
    'Executive Decisions': 'smart-report-executive-summary',
    'توقعات الشهر القادم': 'smart-report-executive-summary',
    'Next-Month Forecast': 'smart-report-executive-summary',
    'الملخص التنفيذي': 'smart-report-executive-summary',
    'Executive Summary': 'smart-report-executive-summary',
    'تحليل المؤشرات': 'smart-report-indicators',
    'Indicator Analysis': 'smart-report-indicators',
    'بيانات المؤشرات الفعلية': 'smart-report-indicators',
    'Actual Indicator Statistics': 'smart-report-indicators',
    'الاتجاهات الشهرية': 'smart-report-indicators',
    'Monthly Trends': 'smart-report-indicators',
    'الأنماط المركبة للمؤشرات': 'smart-report-clustering',
    'Composite Indicator Patterns': 'smart-report-clustering',
    'تحليل الشذوذ': 'smart-report-anomalies',
    'Anomaly Analysis': 'smart-report-anomalies',
    'التجميع': 'smart-report-clustering',
    'Clustering': 'smart-report-clustering',
    'الارتباطات': 'smart-report-clustering',
    'Correlations': 'smart-report-clustering',
    'المقارنة الطبقية': 'smart-report-stratified',
    'Stratified Comparison': 'smart-report-stratified',
    'التوصيات': 'smart-report-recommendations',
    'Recommendations': 'smart-report-recommendations',
    'البواقي': 'smart-report-executive-summary',
    'Residuals': 'smart-report-executive-summary',
    'شرح SHAP': 'smart-report-executive-summary',
    'SHAP Explanations': 'smart-report-executive-summary',
    'الخريطة الجغرافية': 'smart-report-executive-summary',
    'Geographic Map': 'smart-report-executive-summary',
    'التنبؤات': 'smart-report-executive-summary',
    'Predictions': 'smart-report-executive-summary',
  };

  let currentSection = 'smart-report-executive-summary';
  const lines = reportText.split('\n');

  lines.forEach(line => {
    const trimmed = line.trim();
    for (const [name, id] of Object.entries(sectionNames)) {
      if (trimmed.includes(name)) {
        currentSection = id;
        return;
      }
    }
    if (!sections[currentSection]) sections[currentSection] = [];
    sections[currentSection].push(line);
  });

  if (Object.keys(sections).length === 0) {
    sections['smart-report-executive-summary'] = lines;
  }

  return sections;
}

function _smartEscapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function _smartRenderReportLine(line) {
  const t = String(line || '').trim();
  if (!t) return '<div class="report-line report-line-empty"></div>';

  if (t.startsWith('- ') || t.startsWith('• ')) {
    let content = t.replace(/^[-•]\s*/, '');
    const segments = content.split('|').map(s => s.trim()).filter(Boolean);
    if (segments.length > 1) {
      const chips = segments.map(seg => {
        const idx = seg.indexOf(': ');
        if (idx > 0) {
          const key = seg.slice(0, idx);
          const val = seg.slice(idx + 2);
          return `<span class="report-chip"><span class="report-chip-key">${_smartEscapeHtml(key)}</span>: ${_smartEscapeHtml(val)}</span>`;
        }
        return `<span class="report-chip">${_smartEscapeHtml(seg)}</span>`;
      });
      return `<div class="report-line report-bullet">${chips.join('')}</div>`;
    }
    const idx = content.indexOf(': ');
    if (idx > 0) {
      const key = content.slice(0, idx);
      const val = content.slice(idx + 2);
      return `<div class="report-line report-bullet"><span class="report-key">${_smartEscapeHtml(key)}</span><span class="report-sep">: </span><span class="report-value">${_smartEscapeHtml(val)}</span></div>`;
    }
    return `<div class="report-line report-bullet">${_smartEscapeHtml(content)}</div>`;
  }

  return `<div class="report-line report-text">${_smartEscapeHtml(t)}</div>`;
}

function smartRenderReportSections(reportText) {
  ['smart-report-executive-summary', 'smart-report-indicators', 'smart-report-anomalies', 'smart-report-clustering', 'smart-report-stratified', 'smart-report-recommendations'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = '';
  });

  if (!reportText) {
    document.getElementById('smart-report-output').style.display = 'block';
    const el = document.getElementById('smart-report-executive-summary');
    if (el) el.textContent = smartReportLang === 'ar' ? 'لم يتم توليد محتوى التقرير.' : 'No report content was generated.';
    return;
  }

  const sections = smartParseReportSections(reportText);
  for (const [id, lines] of Object.entries(sections)) {
    const element = document.getElementById(id);
    if (element) element.innerHTML = lines.map(_smartRenderReportLine).join('');
  }

  document.getElementById('smart-report-output').style.display = 'block';
}

async function smartGenerateAdvancedComparison(month, hospitalId, comparisonType) {
  try {
    let url = `/comparative/advanced-comparison/${month}`;
    const params = new URLSearchParams();
    if (hospitalId) params.append('hospital_id', hospitalId);
    if (comparisonType) params.append('comparison_type', comparisonType);
    if (params.toString()) url += '?' + params.toString();

    const result = await apiSmartGet(url);

    if (result.chart_config && result.chart_config.data && result.chart_config.data.labels && result.chart_config.data.labels.length > 0) {
      smartRenderComparisonChart(result.chart_config);
      document.getElementById('smart-chart-filter-badge').textContent = comparisonType === 'all' ? 'جميع المستشفيات' : comparisonType === 'governorate' ? 'نفس المحافظة' : 'نفس النوع';
      document.getElementById('smart-comparison-chart-container').style.display = 'block';
    }

    if (result.comparison_data && result.comparison_data.peer_comparison && result.comparison_data.peer_comparison.length > 0) {
      smartRenderPeerComparisonTable(result.comparison_data.peer_comparison);
      document.getElementById('smart-peer-filter-badge').textContent = comparisonType === 'all' ? 'جميع المستشفيات' : comparisonType === 'governorate' ? 'نفس المحافظة' : 'نفس النوع';
      document.getElementById('smart-peer-comparison-container').style.display = 'block';
    }
  } catch (e) {
    console.error('خطأ في المقارنة المتقدمة:', e);
  }
}

function smartRenderComparisonChart(chartConfig) {
  const ctx = document.getElementById('smart-comparison-chart').getContext('2d');

  if (smartComparisonChart) {
    smartComparisonChart.destroy();
  }

  smartComparisonChart = new Chart(ctx, {
    type: chartConfig.type || 'line',
    data: chartConfig.data,
    options: chartConfig.options || {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        title: {
          display: true,
          text: 'مقارنة أداء المستشفيات عبر الأشهر'
        },
        legend: { position: 'bottom' }
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: 'إجمالي الحالات' }
        },
        x: { title: { display: true, text: 'الشهر' } }
      }
    }
  });
}

function smartRenderPeerComparisonTable(peerComparison) {
  const tbody = document.querySelector('#smart-peer-comparison-table tbody');
  tbody.innerHTML = '';

  const labelColors = {
    'متفوق': { bg: '#dcfce7', color: '#166534' },
    'متوسط': { bg: '#eef2ff', color: '#4338ca' },
    'يحتاج تحسين': { bg: '#fef3c7', color: '#92400e' },
    'حرج': { bg: '#fee2e2', color: '#991b1b' }
  };

  peerComparison.forEach(peer => {
    const row = document.createElement('tr');
    row.style.borderBottom = '1px solid #e5e7eb';
    const lbl = labelColors[peer.comparison_label] || { bg: '#f3f4f6', color: '#374151' };
    row.innerHTML = `
      <td style="padding:0.55rem 0.8rem;font-weight:600;color:#1a237e;">${peer.rank}</td>
      <td style="padding:0.55rem 0.8rem;font-weight:500;">${peer.hospital_name}</td>
      <td style="padding:0.55rem 0.8rem;">${peer.percentile.toFixed(1)}%</td>
      <td style="padding:0.55rem 0.8rem;">
        <span style="display:inline-block;padding:0.15rem 0.6rem;border-radius:10px;font-size:0.78rem;font-weight:600;background:${lbl.bg};color:${lbl.color};">${peer.comparison_label}</span>
      </td>
    `;
    tbody.appendChild(row);
  });
}

function toggleSection(header) {
  header.classList.toggle('open');
  const body = header.nextElementSibling;
  body.classList.toggle('open');
}

function smartShowAlert(message, type = 'info') {
  let container = document.getElementById('alert-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'alert-container';
    container.className = 'alert-container';
    document.body.appendChild(container);
  }
  const alert = document.createElement('div');
  alert.className = `alert-item ${type}`;
  alert.innerHTML = `<span>${message}</span><span class="close-btn" onclick="this.parentElement.remove()">✕</span>`;
  container.appendChild(alert);
  setTimeout(() => {
    if (alert.parentElement) alert.remove();
  }, 5000);
}

// ═══════════════════════════════════════════════════════════════════════
//  رسوم تفاعلية جديدة
// ═══════════════════════════════════════════════════════════════════════

function renderSeverityDonut(kpi, hospitalsCount) {
  const normal = Math.max(0, hospitalsCount - (kpi.critical_count || 0) - (kpi.warning_count || 0));
  const data = [{
    type: 'pie', hole: 0.55,
    labels: ['طبيعي', 'تنبيه', 'حرج'],
    values: [normal, kpi.warning_count || 0, kpi.critical_count || 0],
    marker: { colors: [SMART_COLORS.normal, SMART_COLORS.warning, SMART_COLORS.critical], line: { color: '#fff', width: 2 } },
    textinfo: 'label+value',
    hovertemplate: '%{label}: %{value} مستشفى (%{percent})<extra></extra>',
  }];
  Plotly.newPlot('smart-severity-donut', data, {
    margin: { t: 20, b: 30, l: 20, r: 20 },
    showlegend: false,
    paper_bgcolor: 'white',
    height: 300,
  }).then(gd => {
    gd.on('plotly_click', () => {
      if (window._smartKPIAnomalies) window._smartKPIAnomalies();
    });
  }).catch(() => {});
}

function renderScoreHistogram(anomalies) {
  const el = document.getElementById('smart-score-histogram');
  if (!el) return;
  if (!anomalies || anomalies.length === 0) {
    Plotly.purge('smart-score-histogram');
    return;
  }
  const scores = anomalies.map(a => a.anomaly_score);
  const data = [{
    type: 'histogram',
    x: scores,
    nbinsx: 14,
    marker: { color: '#4338ca', line: { color: '#312e81', width: 1 } },
    hovertemplate: 'الدرجة %{x:.2f}<br>المستشفيات: %{y}<extra></extra>',
  }];
  Plotly.newPlot('smart-score-histogram', data, {
    margin: { t: 20, b: 40, l: 50, r: 20 },
    xaxis: { title: 'درجة الشذوذ', range: [0, 1] },
    yaxis: { title: 'عدد المستشفيات' },
    bargap: 0.05,
    shapes: [
      { type: 'line', x0: 0.3, x1: 0.3, y0: 0, y1: 1, xref: 'x', yref: 'paper', line: { color: SMART_COLORS.warning, width: 2, dash: 'dash' } },
      { type: 'line', x0: 0.6, x1: 0.6, y0: 0, y1: 1, xref: 'x', yref: 'paper', line: { color: SMART_COLORS.critical, width: 2, dash: 'dash' } },
    ],
    paper_bgcolor: 'white',
    height: 300,
  });
}

function renderPredictedScatter(xgb) {
  const el = document.getElementById('smart-predicted-scatter');
  if (!el) return;
  if (!xgb || !xgb.predictions || xgb.predictions.length === 0) {
    Plotly.purge('smart-predicted-scatter');
    return;
  }
  const preds = xgb.predictions;
  const data = [{
    type: 'scatter', mode: 'markers',
    x: preds.map(p => p.current_score),
    y: preds.map(p => p.predicted_next_score),
    marker: {
      size: preds.map(p => 10 + p.confidence * 14),
      color: preds.map(p => p.predicted_severity === 'critical' ? SMART_COLORS.critical : p.predicted_severity === 'warning' ? SMART_COLORS.warning : SMART_COLORS.normal),
      line: { color: '#fff', width: 1 },
    },
    text: preds.map(p => `${p.hospital_name}<br>الحالي: ${p.current_score.toFixed(2)}<br>المتوقع: ${p.predicted_next_score.toFixed(2)}<br>الاتجاه: ${p.risk_change === 'increasing' ? '⬆ يزداد' : p.risk_change === 'decreasing' ? '⬇ يقل' : '➡ مستقر'}<br>الثقة: ${Math.round(p.confidence * 100)}%`),
    hovertemplate: '%{text}<extra></extra>',
  }];
  const shapes = [
    { type: 'line', x0: 0, x1: 1, y0: 0, y1: 1, xref: 'x', yref: 'y', line: { color: '#999', width: 1.5, dash: 'dot' } },
    { type: 'line', x0: 0.3, x1: 0.3, y0: 0, y1: 1, xref: 'x', yref: 'y', line: { color: SMART_COLORS.warning, width: 1, dash: 'dash' } },
    { type: 'line', x0: 0.6, x1: 0.6, y0: 0, y1: 1, xref: 'x', yref: 'y', line: { color: SMART_COLORS.critical, width: 1, dash: 'dash' } },
    { type: 'line', x0: 0, x1: 1, y0: 0.3, y1: 0.3, xref: 'x', yref: 'y', line: { color: SMART_COLORS.warning, width: 1, dash: 'dash' } },
    { type: 'line', x0: 0, x1: 1, y0: 0.6, y1: 0.6, xref: 'x', yref: 'y', line: { color: SMART_COLORS.critical, width: 1, dash: 'dash' } },
  ];
  Plotly.newPlot('smart-predicted-scatter', data, {
    margin: { t: 20, b: 40, l: 50, r: 20 },
    xaxis: { title: 'درجة الشذوذ الحالية', range: [0, 1] },
    yaxis: { title: 'الدرجة المتوقعة', range: [0, 1] },
    showlegend: false,
    paper_bgcolor: 'white',
    height: 300,
  });
}

async function loadAnomalyTimeline() {
  const el = document.getElementById('smart-timeline-chart');
  if (!el) return;
  if (smartTimelineLoaded) return;
  try {
    const data = await apiSmartGet('/smart/anomaly-timeline');
    if (!data || !data.months || data.months.length === 0 || !data.hospitals || data.hospitals.length === 0) {
      document.getElementById('smart-timeline-badge').textContent = '';
      document.getElementById('smart-timeline-text').textContent = 'لا توجد بيانات كافية عبر الأشهر لعرض الرسم المتحرك.';
      Plotly.purge('smart-timeline-chart');
      return;
    }
    smartTimelineLoaded = true;
    renderAnomalyTimeline(data);
  } catch (e) {
    document.getElementById('smart-timeline-text').textContent = 'تعذر تحميل الخط الزمني: ' + e.message;
    Plotly.purge('smart-timeline-chart');
  }
}

function renderAnomalyTimeline(data) {
  const months = data.months || [];
  const hospitals = data.hospitals || [];
  if (months.length === 0 || hospitals.length === 0) return;

  document.getElementById('smart-timeline-badge').textContent = `${months.length} شهر | ${hospitals.length} مستشفى`;

  const hospitalNames = hospitals.map(h => h.hospital_name);

  // أعمدة لكل شهر: المحور السيني المستشفيات، الصادي درجة الشذوذ، اللون حسب الحالة
  const makeMonthTrace = (m) => {
    const y = hospitals.map(h => (h.scores && h.scores[m] != null ? h.scores[m] : null));
    const colors = hospitals.map(h => {
      const sev = h.severities && h.severities[m];
      return sev === 'critical' ? SMART_COLORS.critical : sev === 'warning' ? SMART_COLORS.warning : SMART_COLORS.normal;
    });
    const text = hospitals.map(h => {
      const sev = h.severities && h.severities[m];
      const sevText = sev === 'critical' ? 'حرج' : sev === 'warning' ? 'تنبيه' : 'طبيعي';
      const score = h.scores && h.scores[m] != null ? h.scores[m].toFixed(3) : 'لا توجد بيانات';
      return `${h.hospital_name}<br>الشهر: ${m}<br>الدرجة: ${score}<br>الحالة: ${sevText}`;
    });
    return {
      type: 'bar',
      x: hospitalNames,
      y: y,
      marker: { color: colors, line: { width: 1, color: '#fff' } },
      text: text,
      hovertemplate: '%{text}<extra></extra>',
    };
  };

  const frames = months.map(m => ({ name: m, data: [makeMonthTrace(m)] }));

  const slidersSteps = months.map(m => ({
    label: m,
    method: 'animate',
    args: [[m], { mode: 'immediate', frame: { duration: 400, redraw: true }, transition: { duration: 150 } }],
  }));

  const layout = {
    title: { text: 'تطور درجات الشذوذ عبر الأشهر', font: { size: 13, color: '#1a237e' } },
    xaxis: {
      title: 'المستشفى',
      tickangle: -45,
      tickfont: { size: 9 },
      categoryorder: 'array',
      categoryarray: hospitalNames,
    },
    yaxis: { title: 'درجة الشذوذ', range: [0, 1] },
    shapes: [
      { type: 'line', x0: -0.5, x1: hospitals.length - 0.5, y0: 0.3, y1: 0.3, xref: 'x', yref: 'y', line: { color: SMART_COLORS.warning, width: 1.5, dash: 'dash' } },
      { type: 'line', x0: -0.5, x1: hospitals.length - 0.5, y0: 0.6, y1: 0.6, xref: 'x', yref: 'y', line: { color: SMART_COLORS.critical, width: 1.5, dash: 'dash' } },
    ],
    updatemenus: [{
      type: 'buttons',
      showactive: false,
      x: 0.02, y: 1.15, xanchor: 'left', yanchor: 'top',
      buttons: [
        { label: '▶ تشغيل', method: 'animate', args: [null, { mode: 'next', frame: { duration: 500, redraw: true }, transition: { duration: 200 } }] },
        { label: '⏸ إيقاف', method: 'animate', args: [[null], { mode: 'immediate', transition: { duration: 0 } }] },
      ],
    }],
    sliders: [{
      active: 0,
      steps: slidersSteps,
      pad: { t: 40 },
      currentvalue: { prefix: 'الشهر: ', font: { size: 12, color: '#1a237e' } },
    }],
    margin: { t: 60, b: 100, l: 50, r: 20 },
    height: 460,
    paper_bgcolor: 'white',
    plot_bgcolor: 'white',
    hovermode: 'closest',
  };

  // الإطار الابتدائي = أول شهر بما يطابق slider active: 0 (النمط القياسي للتشغيل التالي)
  Plotly.newPlot('smart-timeline-chart', [makeMonthTrace(months[0])], layout).then(gd => {
    Plotly.addFrames(gd, frames);
  });

  // نص ملخص
  const firstMonth = months[0];
  const lastMonth = months[months.length - 1];
  const critical = hospitals.filter(h => h.severities && h.severities[lastMonth] === 'critical').length;
  const warning = hospitals.filter(h => h.severities && h.severities[lastMonth] === 'warning').length;
  document.getElementById('smart-timeline-text').textContent =
    `من ${firstMonth} إلى ${lastMonth}: ${critical} حرج و${warning} تنبيه في آخر شهر من ${hospitals.length} مستشفى.`;
}
