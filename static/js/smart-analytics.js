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
  nd: 'الوفيات新生儿',
  sb: 'الولادات الميتة',
  preterm: 'الولادات السابقة لأوانها',
  lbw: 'نقص وزن الولادة',
  total_births: 'إجمالي المواليد',
  high_risk: 'حالات الخطر العالي',
  adolescent: 'الحالات المراهقة',
  governorate: 'المحافظة',
  hospital_type: 'نوع المستشفى',
};

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

async function apiSmartGet(path) {
  const base = document.getElementById('apiBase')?.value || '';
  const res = await fetch(base + path);
  return res.json();
}

window.initSmartAnalytics = async function() {
  const monthsRes = await apiSmartGet('/analysis/months');
  const months = monthsRes?.months || monthsRes || [];
  const monthSelect = document.getElementById('smart-month-select');
  monthSelect.innerHTML = '';
  months.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.month || m; opt.textContent = m.month || m;
    monthSelect.appendChild(opt);
  });
  monthSelect.addEventListener('change', () => {
    loadSmartData(monthSelect.value);
    updateHospitalList();
  });

  document.getElementById('smart-refresh').addEventListener('click', () => {
    loadSmartData(monthSelect.value);
    updateHospitalList();
  });
  document.getElementById('smart-close-drilldown').addEventListener('click', () => {
    document.getElementById('smart-drilldown-panel').style.display = 'none';
  });
  document.getElementById('smart-close-hospital').addEventListener('click', () => {
    document.getElementById('smart-hospital-panel').style.display = 'none';
    document.getElementById('smart-hospital-select').value = '';
  });
  document.getElementById('smart-hospital-select').addEventListener('change', (e) => {
    const hospitalId = e.target.value;
    if (hospitalId) {
      loadHospitalAnalysis(parseInt(hospitalId), monthSelect.value);
    } else {
      document.getElementById('smart-hospital-panel').style.display = 'none';
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
  if (months.length > 0) {
    const lastMonth = months[months.length - 1];
    monthSelect.value = lastMonth.month || lastMonth;
    loadSmartData(monthSelect.value);
    updateHospitalList();
  }
};

async function updateHospitalList() {
  const month = document.getElementById('smart-month-select').value;
  if (!month) return;
  try {
    const data = await apiSmartGet(`/smart/overview/${month}`);
    const select = document.getElementById('smart-hospital-select');
    const current = select.value;
    select.innerHTML = '<option value="">-- جميع المستشفيات --</option>';
    const anomalies = data.data?.anomalies || [];
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
  } catch (e) {
    console.error('Failed to load hospital list:', e);
  }
}

async function loadSmartData(month) {
  smartCurrentMonth = month;
  document.getElementById('smart-status').textContent = 'جاري التحميل...';
  try {
    smartCurrentData = await apiSmartGet(`/smart/overview/${month}`);
    const d = smartCurrentData.data;
    const total = smartCurrentData.hospitals_count;
    renderKPIs(d.kpi, total);
    renderGeoMap(d.geo);
    renderClusterScatter(d.clustering, d.anomalies);
    renderCorrelationHeatmap(d.correlations);
    renderResidualPlot(d.residuals, document.getElementById('smart-residual-indicator').value);
    renderAnomalyTable(d.anomalies, d.explanations);
    renderFeatureImportance(d.correlations, document.getElementById('smart-fi-indicator').value);
    renderStratifiedComparison(d.stratified, document.getElementById('smart-strat-indicator').value);
    document.getElementById('smart-status').textContent = `تم التحديث — ${total} مستشفى`;
    document.getElementById('smart-disclaimer').textContent = `النتائج مبنية على بيانات ${total} مستشفى فقط. يجب تفسيرها كمؤشرات أولية وليست قرارات نهائية. لا تتوفر تنبؤات زمنية في هذه المرحلة.`;
  } catch (e) {
    document.getElementById('smart-status').textContent = 'خطأ في التحميل: ' + e.message;
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
  const statusIcon = kpi.month_status === 'critical' ? '\u274C' : kpi.month_status === 'attention_needed' ? '\u26A0\uFE0F' : '\u2705';
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
      <div style="font-size:0.65rem;color:#3b82f6;margin-top:0.4rem;">\u2139\uFE0F اضغط للتفاصيل</div>
    </div>

    <div class="card" style="${cardStyle}border-top:3px solid #3b82f6;" ${hoverJs} onclick="window._smartKPIGovernorates()">
      <div style="font-size:2.2rem;font-weight:700;color:#3b82f6;">${kpi.affected_governorates}<span style="font-size:0.9rem;font-weight:400;color:#999;">/${hospitalsCount > 0 ? Math.min(hospitalsCount, 5) : 5}</span></div>
      <div style="font-size:0.8rem;color:#444;font-weight:600;margin:0.3rem 0;">محافظات بها انحرافات</div>
      <div style="font-size:0.7rem;color:#888;line-height:1.4;">تحتوي على مستشفيات تنبيه أو حرج</div>
      <div style="font-size:0.68rem;color:#aaa;margin-top:0.3rem;">المحافظات: غزة، خان يونس، الشمال، الوسطى، رفح</div>
      <div style="font-size:0.65rem;color:#3b82f6;margin-top:0.4rem;">\u2139\uFE0F اضغط للتفاصيل</div>
    </div>

    <div class="card" style="${cardStyle}border-top:3px solid #8b5cf6;" ${hoverJs} onclick="window._smartKPIFactors()">
      <div style="font-size:1rem;font-weight:700;color:#8b5cf6;word-break:break-word;line-height:1.4;">${smartTranslateFeature(kpi.top_contributing_factor) || 'غير محدد'}</div>
      <div style="font-size:0.8rem;color:#444;font-weight:600;margin:0.3rem 0;">العامل الأكثر تأثيراً</div>
      <div style="font-size:0.7rem;color:#888;line-height:1.4;">أبرز العوامل المسببة للشذوذ</div>
      <div style="font-size:0.68rem;color:#aaa;margin-top:0.3rem;">يُحدَّد من تحليل SHAP للعوامل المؤثرة</div>
      <div style="font-size:0.65rem;color:#3b82f6;margin-top:0.4rem;">\u2139\uFE0F اضغط للتفاصيل</div>
    </div>

    <div class="card" style="${cardStyle}border-left:4px solid ${statusColor};" ${hoverJs} onclick="window._smartKPIStatus()">
      <div style="font-size:1.4rem;font-weight:700;">${statusIcon} ${statusText}</div>
      <div style="font-size:0.8rem;color:#444;font-weight:600;margin:0.3rem 0;">حالة الشهر</div>
      <div style="font-size:0.7rem;color:#888;line-height:1.4;">${hospitalsCount} مستشفى مُحلَّل — ${normalCount} طبيعي، ${kpi.warning_count} تنبيه، ${kpi.critical_count} حرج</div>
      <div style="font-size:0.68rem;color:#aaa;margin-top:0.3rem;">يتم تجميع النتائج من 7 محركات تحليل ذكي</div>
      <div style="font-size:0.65rem;color:#3b82f6;margin-top:0.4rem;">\u2139\uFE0F اضغط للتفاصيل</div>
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
        <strong>\u0643\u064A\u0641 \u062A\u0645 \u062A\u062D\u062F\u064A\u062F \u0647\u0630\u0647 \u0627\u0644\u0642\u0627\u0626\u0645\u0629؟</strong><br>
        كُل مستشفى يمر بـ <strong>4 محركات</strong>: Isolation Forest (35%)، LOF (30%)، Mahalanobis (20%)، والبواقي (15%).<br>
        النتيجة المُوحَّدة (0\u20131) تُقارن مع <strong>العتبات</strong>: أقل من 0.3 طبيعي، 0.3\u20130.6 تنبيه، أعلى 0.6 حرج.<br>
        <strong>الإدخالات:</strong> 10 مؤشرات سريرية + نوع المستشفى + المحافظة.<br>
        <strong>الإخراج:</strong> الدرجة النهائية + تصنيف الحالة + تفصيل دروس كل محرك.
      </div>
    </div>
    <h4 style="color:#1a237e;margin-bottom:0.5rem;">\u0642\u0627\u0626\u0645\u0629 \u0627\u0644\u0645\u0633\u062A\u0634\u0641\u064A\u0627\u062A (${sorted.length}/${total})</h4>
    <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
      <thead><tr style="background:#f1f5f9;border-bottom:2px solid #e2e8f0;">
        <th style="padding:0.4rem 0.6rem;text-align:center;width:30px;">#</th>
        <th style="padding:0.4rem 0.6rem;text-align:right;">\u0627\u0644\u0645\u0633\u062A\u0634\u0641\u0649</th>
        <th style="padding:0.4rem 0.6rem;text-align:center;">\u0627\u0644\u0645\u062D\u0627\u0641\u0638\u0629</th>
        <th style="padding:0.4rem 0.6rem;text-align:center;">\u0627\u0644\u062F\u0631\u062C\u0629</th>
        <th style="padding:0.4rem 0.6rem;text-align:center;">\u0627\u0644\u062D\u0627\u0644\u0629</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div style="margin-top:1rem;display:flex;gap:1rem;font-size:0.75rem;color:#666;">
      <span><span style="display:inline-block;width:10px;height:10px;background:${SMART_COLORS.normal};border-radius:50%;vertical-align:middle;"></span> طبيعي (&lt;0.3)</span>
      <span><span style="display:inline-block;width:10px;height:10px;background:${SMART_COLORS.warning};border-radius:50%;vertical-align:middle;"></span> تنبيه (0.3\u20130.6)</span>
      <span><span style="display:inline-block;width:10px;height:10px;background:${SMART_COLORS.critical};border-radius:50%;vertical-align:middle;"></span> حرج (&gt;0.6)</span>
    </div>
  `;
  openSmartModal('\u{1F50D} تفاصيل الحالات الشاذة', body);
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
      <td style="padding:0.5rem 0.6rem;text-align:right;font-weight:600;">\u0645\u062D\u0627\u0641\u0638\u0629 ${name}</td>
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
        <strong>\u0643\u064A\u0641 \u062A\u0645 \u062A\u062D\u062F\u064A\u062F \u0627\u0644\u0645\u062D\u0627\u0641\u0638\u0629؟</strong><br>
        تُحسب المحافظة ك<strong>"متأثرة"</strong> إذا تحتوي على مستشفى واحد على الأقل بحالة تنبيه أو حرج.<br>
        <strong>الإدخالات:</strong> تصنيف كل مستشفى حسب المحافظة + درجة الشذوذ.<br>
        <strong>الإخراج:</strong> عدد المستشفيات في كل محافظة + عدد الحرج/تنبيه/طبيعي + شريط مقارن.
      </div>
    </div>
    <h4 style="color:#1a237e;margin-bottom:0.5rem;">\u062A\u0641\u0635\u064A\u0644 \u0627\u0644\u0645\u062D\u0627\u0641\u0638\u0627\u062A</h4>
    <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
      <thead><tr style="background:#f1f5f9;border-bottom:2px solid #e2e8f0;">
        <th style="padding:0.5rem 0.6rem;text-align:right;">\u0627\u0644\u0645\u062D\u0627\u0641\u0638\u0629</th>
        <th style="padding:0.5rem 0.6rem;text-align:center;">\u0627\u0644\u0645\u0633\u062A\u0634\u0641\u064A\u0627\u062A</th>
        <th style="padding:0.5rem 0.6rem;text-align:center;">\u062D\u0631\u062C</th>
        <th style="padding:0.5rem 0.6rem;text-align:center;">\u062A\u0646\u0628\u064A\u0647</th>
        <th style="padding:0.5rem 0.6rem;text-align:center;">\u0637\u0628\u064A\u0639\u064A</th>
        <th style="padding:0.5rem 0.6rem;text-align:center;">\u0627\u0644\u062A\u0623\u062B\u064A\u0631</th>
      </tr></thead>
      <tbody>${govRows}</tbody>
    </table>
  `;
  openSmartModal('\u{1F4CD} تفاصيل المحافظات', body);
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
    const dirColor = avgShap > 0 ? SMART_COLORS.shap_positive : SMART_COLORS.shap_negative;
    const dirText = avgShap > 0 ? 'يُزيّد' : 'يُقلّص';
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
        <strong>\u0645\u0627 \u0647\u0648 SHAP؟</strong><br>
        SHAP (SHapley Additive exPlanations) يحسب <strong>مساهمة كل ميزة</strong> في نتيجة المستشفى مقارنة بالمتوسط.<br>
        <strong>القيمة الموجبة (+):</strong> تُزيّد من درجة الشذوذ (تساهم في ارتفاعها).<br>
        <strong>القيمة السالبة (\u2013):</strong> تُقلّص من درجة الشذوذ (تساعد في خفضها).<br>
        <strong>الإدخالات:</strong> قيم الميزات الـ 10 + التصنيف + النموذج المُدرَّب.<br>
        <strong>الإخراج:</strong> مساهمة كل ميزة + تفسير نصي عربي.
      </div>
    </div>
    <h4 style="color:#1a237e;margin-bottom:0.5rem;">\u0627\u0644\u0639\u0648\u0627\u0645\u0644 \u0627\u0644\u0645\u0633\u0624\u0648\u0644\u0629 \u0644\u0644\u0634\u0630\u0648\u0630</h4>
    <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
      <thead><tr style="background:#f1f5f9;border-bottom:2px solid #e2e8f0;">
        <th style="padding:0.4rem 0.6rem;text-align:center;width:30px;">#</th>
        <th style="padding:0.4rem 0.6rem;text-align:right;">\u0627\u0644\u0639\u0627\u0645\u0644</th>
        <th style="padding:0.4rem 0.6rem;text-align:center;">\u0645\u062A\u0648\u0633\u0637 SHAP</th>
        <th style="padding:0.4rem 0.6rem;text-align:center;">\u0627\u0644\u0627\u062A\u062C\u0627\u0647</th>
        <th style="padding:0.4rem 0.6rem;text-align:center;">\u0627\u0644\u062A\u0631\u062F\u062F</th>
        <th style="padding:0.4rem 0.6rem;text-align:right;">\u0627\u0644\u0645\u0633\u062A\u0634\u0641\u064A\u0627\u062A \u0627\u0644\u0645\u062A\u0623\u0636\u0639\u0629</th>
      </tr></thead>
      <tbody>${factorRows}</tbody>
    </table>
  `;
  openSmartModal('\u{1F50D} تفاصيل العوامل المؤثرة', body);
};

window._smartKPIStatus = function() {
  if (!smartCurrentData || !smartCurrentData.data) return;
  const kpi = smartCurrentData.data.kpi || {};
  const total = smartCurrentData.hospitals_count || 20;
  const normalCount = total - (kpi.critical_count || 0) - (kpi.warning_count || 0);

  const body = `
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:1rem;margin-bottom:1rem;">
      <div style="font-size:0.82rem;color:#374151;line-height:1.7;">
        <strong>\u0643\u064A\u0641 \u062A\u0645 \u062A\u062D\u062F\u064A\u062F \u062D\u0627\u0644\u0629 \u0627\u0644\u0634\u0647\u0631؟</strong><br>
        تُجمَّع نتائج <strong>7 محركات تحليل ذكي</strong>: كشف الشذوذ، التجميع، الارتباط، البواقي، المقارنة الطبقية، SHAP، والخريطة.<br>
        <strong>الحالة النهائية</strong> تعتمد على أسوأ حالة بين المستشفيات:<br>
        \u2022 <strong>\u274C يحتاج تدخل عاجل:</strong> يوجد مستشفى واحد على الأقل بدرجة حرج (&gt;0.6)<br>
        \u2022 <strong>\u26A0\uFE0F يحتاج مراقبة:</strong> أعلى حالة تنبيه (0.3\u20130.6) ولا حرج<br>
        \u2022 <strong>\u2705 طبيعي:</strong> جميع المستشفيات ضمن الطبيعي (&lt;0.3)<br>
        <strong>الإدخالات:</strong> درجات الشذوذ لجميع المستشفيات.<br>
        <strong>الإخراج:</strong> تصنيف الحالة العامة + عدد المستشفيات في كل فئة.
      </div>
    </div>
    <h4 style="color:#1a237e;margin-bottom:0.8rem;">\u062A\u0642\u0633\u064A\u0645 \u0627\u0644\u062D\u0627\u0644\u0629</h4>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;margin-bottom:1rem;">
      <div style="background:#f0fdf4;border:2px solid ${SMART_COLORS.normal};border-radius:8px;padding:1rem;text-align:center;">
        <div style="font-size:2rem;font-weight:700;color:${SMART_COLORS.normal};">${normalCount}</div>
        <div style="font-size:0.85rem;color:#444;font-weight:600;">\u0637\u0628\u064A\u0639\u064A</div>
        <div style="font-size:0.72rem;color:#888;">\u062F\u0631\u062C\u0629 &lt;0.3</div>
        <div style="font-size:0.7rem;color:#aaa;margin-top:0.3rem;">${total > 0 ? Math.round(normalCount / total * 100) : 0}% \u0645\u0646 \u0627\u0644\u0645\u0633\u062A\u0634\u0641\u064A\u0627\u062A</div>
      </div>
      <div style="background:#fffbeb;border:2px solid ${SMART_COLORS.warning};border-radius:8px;padding:1rem;text-align:center;">
        <div style="font-size:2rem;font-weight:700;color:${SMART_COLORS.warning};">${kpi.warning_count || 0}</div>
        <div style="font-size:0.85rem;color:#444;font-weight:600;">\u062A\u0646\u0628\u064A\u0647</div>
        <div style="font-size:0.72rem;color:#888;">\u062F\u0631\u062C\u0629 0.3\u20130.6</div>
        <div style="font-size:0.7rem;color:#aaa;margin-top:0.3rem;">${total > 0 ? Math.round((kpi.warning_count || 0) / total * 100) : 0}% \u0645\u0646 \u0627\u0644\u0645\u0633\u062A\u0634\u0641\u064A\u0627\u062A</div>
      </div>
      <div style="background:#fef2f2;border:2px solid ${SMART_COLORS.critical};border-radius:8px;padding:1rem;text-align:center;">
        <div style="font-size:2rem;font-weight:700;color:${SMART_COLORS.critical};">${kpi.critical_count || 0}</div>
        <div style="font-size:0.85rem;color:#444;font-weight:600;">\u062D\u0631\u062C</div>
        <div style="font-size:0.72rem;color:#888;">\u062F\u0631\u062C\u0629 &gt;0.6</div>
        <div style="font-size:0.7rem;color:#aaa;margin-top:0.3rem;">${total > 0 ? Math.round((kpi.critical_count || 0) / total * 100) : 0}% \u0645\u0646 \u0627\u0644\u0645\u0633\u062A\u0634\u0641\u064A\u0627\u062A</div>
      </div>
    </div>
    <div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:8px;padding:1rem;margin-top:1rem;">
      <div style="font-size:0.82rem;color:#374151;line-height:1.7;">
        <strong>\u0627\u0644\u0639\u062A\u0628\u0627\u062A:</strong><br>
        \u2022 <span style="color:${SMART_COLORS.normal};font-weight:700;">\u0623\u0642\u0644 \u0645\u0646 0.3:</span> \u0627\u0644\u0628\u064A\u0627\u0646\u0627\u062A \u062A\u0643\u0648\u0646 \u0623\u0642\u0631\u0628 \u0645\u0646 \u0627\u0644\u0645\u062A\u0648\u0633\u0637\u0642\u0629 \u0641\u064A \u0641\u0636\u0627\u0621 \u0627\u0644\u0645\u0633\u062A\u0634\u0641\u064A\u0627\u062A \u0627\u0644\u0645\u062C\u0627\u0648\u064A\u0629<br>
        \u2022 <span style="color:${SMART_COLORS.warning};font-weight:700;">0.3\u20130.6:</span> \u064A\u062C\u0628 \u0645\u0631\u0627\u0642\u0628\u0629 \u0623\u0642\u0631\u0628 \u0645\u0646 \u0627\u0644\u0645\u0633\u062A\u0634\u0641\u0649<br>
        \u2022 <span style="color:${SMART_COLORS.critical};font-weight:700;">\u0623\u0643\u062B\u0631 \u0645\u0646 0.6:</span> \u064A\u062D\u062A\u0627\u062C \u062A\u062F\u062E\u0644 \u0639\u0627\u062C\u0644
      </div>
    </div>
  `;
  openSmartModal('\u{1F4CA} تفاصيل حالة الشهر', body);
};

function renderGeoMap(geo) {
  if (!geo || !geo.governorates || geo.governorates.length === 0) {
    document.getElementById('smart-geo-text').textContent = 'لا توجد بيانات جغرافية متاحة.';
    return;
  }
  const GOV_COORDS = {
    'شمال غزة': {lat: 31.55, lon: 34.45},
    'غزة': {lat: 31.50, lon: 34.47},
    'محافظة غزة': {lat: 31.50, lon: 34.47},
    'دير البلح': {lat: 31.42, lon: 34.35},
    'الوسطى': {lat: 31.42, lon: 34.35},
    'محافظة الوسطى': {lat: 31.42, lon: 34.35},
    'خانيونس': {lat: 31.34, lon: 34.30},
    'خان يونس': {lat: 31.34, lon: 34.30},
    'محافظة خان يونس': {lat: 31.34, lon: 34.30},
    'رفح': {lat: 31.28, lon: 34.24},
  };
  const govs = geo.governorates;
  const lats = govs.map(g => (GOV_COORDS[g.governorate] || {lat: 31.4}).lat);
  const lons = govs.map(g => (GOV_COORDS[g.governorate] || {lon: 34.4}).lon);
  const sizes = govs.map(g => 20 + g.hospital_count * 5 + g.avg_anomaly_score * 30);
  const colors = govs.map(g => g.avg_anomaly_score > 0.6 ? SMART_COLORS.critical : g.avg_anomaly_score > 0.3 ? SMART_COLORS.warning : SMART_COLORS.normal);
  const data = [{
    type: 'scattergeo',
    lat: lats,
    lon: lons,
    mode: 'markers+text',
    marker: { size: sizes, color: colors, opacity: 0.8, line: { width: 2, color: '#fff' } },
    text: govs.map(g => g.governorate),
    textposition: 'top center',
    textfont: { size: 11, color: '#333', family: 'Arial' },
    hovertext: govs.map(g => `<b>${g.governorate}</b><br>المستشفيات: ${g.hospital_count}<br>متوسط الشذوذ: ${g.avg_anomaly_score.toFixed(2)}<br>حالات شاذة: ${g.outlier_count}`),
    hoverinfo: 'text',
  }];
  Plotly.newPlot('smart-geo-map', data, {
    geo: {
      scope: 'asia',
      center: {lat: 31.4, lon: 34.35},
      projection: {scale: 5000},
      showland: true, landcolor: '#f0f0f0',
      showocean: true, oceancolor: '#dbeafe',
      showcountries: true, countrycolor: '#ccc',
      showcoastlines: true, coastlinecolor: '#999',
      subunitcolor: '#aaa',
    },
    margin: {t: 10, b: 10, l: 10, r: 10},
    showlegend: false,
  });
  const affected = govs.filter(g => g.avg_anomaly_score > 0.3).length;
  document.getElementById('smart-geo-text').textContent = `${affected} من ${govs.length} محافظات تظهر انحرافات.`;
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
  const arabicLabels = indicators.map(i => smartTranslateFeature(i));
  const z = indicators.map(ind_a => indicators.map(ind_b => correlations.matrix[ind_a]?.[ind_b] || 0));
  const data = [{ type: 'heatmap', z: z, x: arabicLabels, y: arabicLabels, colorscale: [[0, SMART_COLORS.corr_negative], [0.5, SMART_COLORS.corr_zero], [1, SMART_COLORS.corr_positive]], zmin: -1, zmax: 1, showscale: true, colorbar: {title: {text: 'r', font: {size: 12}}} }];
  Plotly.newPlot('smart-correlation-heatmap', data, { margin: {t: 20, b: 100, l: 100, r: 20}, xaxis: {tickangle: -45}, yaxis: {automargin: true} });
  const strong = correlations.strong_correlations?.[0];
  document.getElementById('smart-corr-text').textContent = strong ? `أقوى علاقة: ${smartTranslateFeature(strong.indicator_a)} ↔ ${smartTranslateFeature(strong.indicator_b)} (r=${strong.pearson_r.toFixed(2)})` : 'لم يتم اكتشاف علاقات قوية.';
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

  let html = `<table style="width:100%;border-collapse:collapse;font-size:0.8rem;direction:rtl;">
    <thead>
      <tr style="background:#1a237e;color:white;">
        <th style="padding:0.6rem;text-align:right;border-radius:0 0 8px 0;">#</th>
        <th style="padding:0.6rem;text-align:right;">المستشفى</th>
        <th style="padding:0.6rem;text-align:center;">المحافظة</th>
        <th style="padding:0.6rem;text-align:center;">النوع</th>
        <th style="padding:0.6rem;text-align:center;">الدرجة</th>
        <th style="padding:0.6rem;text-align:center;">الحالة</th>
        <th style="padding:0.6rem;text-align:center;border-radius:0 0 0 8px;">إجراء</th>
      </tr>
    </thead>
    <tbody>`;

  sorted.forEach((a, idx) => {
    const sevColor = a.severity === 'critical' ? SMART_COLORS.critical : a.severity === 'warning' ? SMART_COLORS.warning : SMART_COLORS.normal;
    const sevBg = a.severity === 'critical' ? '#fef2f2' : a.severity === 'warning' ? '#fffbeb' : '#f0fdf4';
    const sevText = a.severity === 'critical' ? 'حرج' : a.severity === 'warning' ? 'تنبيه' : 'طبيعي';
    const topFactor = expMap[a.hospital_name]?.top_factors?.[0]?.arabic_label || '-';
    const hid = parseInt(a.hospital_id, 10);
    html += `<tr style="border-bottom:1px solid #e5e7eb;background:${idx % 2 === 0 ? '#fff' : '#f9fafb'};">
      <td style="padding:0.5rem;text-align:center;color:#999;">${idx + 1}</td>
      <td style="padding:0.5rem;text-align:right;font-weight:600;white-space:nowrap;">${a.hospital_name}</td>
      <td style="padding:0.5rem;text-align:center;font-size:0.75rem;white-space:nowrap;">${a.governorate || '-'}</td>
      <td style="padding:0.5rem;text-align:center;font-size:0.75rem;white-space:nowrap;">${a.hospital_type || '-'}</td>
      <td style="padding:0.5rem;text-align:center;"><span style="display:inline-block;background:${sevBg};color:${sevColor};padding:0.15rem 0.5rem;border-radius:12px;font-weight:700;font-size:0.8rem;">${a.anomaly_score.toFixed(2)}</span></td>
      <td style="padding:0.5rem;text-align:center;"><span style="display:inline-block;background:${sevBg};color:${sevColor};padding:0.15rem 0.5rem;border-radius:12px;font-weight:600;font-size:0.75rem;">${sevText}</span></td>
      <td style="padding:0.5rem;text-align:center;"><button class="btn btn-sm btn-outline" style="font-size:0.75rem;padding:0.2rem 0.5rem;" onclick="window.smartDrilldown(${hid})">تفاصيل</button></td>
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
  const data = [{
    type: 'bar', orientation: 'h',
    y: features.map(f => smartTranslateFeature(f.feature_name)),
    x: features.map(f => f.importance),
    marker: { color: features.map((f, i) => `rgba(26,35,126,${1 - i * 0.1})`) },
    text: features.map(f => f.importance.toFixed(3)),
    textposition: 'outside',
  }];
  Plotly.newPlot('smart-feature-importance', data, {
    xaxis: {title: 'الأهمية النسبية'},
    yaxis: {autorange: 'reversed', automargin: true},
    margin: {t: 10, b: 40, l: 140, r: 40}
  });
  document.getElementById('smart-fi-text').textContent = `أهم عامل يؤثر على ${smartTranslateFeature(targetIndicator)}: ${smartTranslateFeature(features[0]?.feature_name)}`;
}

function renderStratifiedComparison(stratified, indicator) {
  if (!stratified || stratified.length === 0) { Plotly.purge('smart-stratified-chart'); return; }
  const filtered = stratified.filter(s => s.indicator === indicator);
  if (filtered.length === 0) { Plotly.purge('smart-stratified-chart'); document.getElementById('smart-strat-text').textContent = 'لا توجد بيانات طبقية لهذا المؤشر.'; return; }
  const sorted = [...filtered].sort((a, b) => Math.abs(b.deviation_pct) - Math.abs(a.deviation_pct)).slice(0, 15);
  const barColors = sorted.map(s => Math.abs(s.deviation_pct) > 30 ? SMART_COLORS.critical : Math.abs(s.deviation_pct) > 15 ? SMART_COLORS.warning : SMART_COLORS.normal);
  const data = [
    { type: 'bar', name: 'القيمة الفعلية', x: sorted.map(s => s.hospital_name), y: sorted.map(s => s.hospital_value), marker: { color: barColors } },
    { type: 'bar', name: 'متوسط النظير', x: sorted.map(s => s.hospital_name), y: sorted.map(s => s.peer_group_mean), marker: { color: '#d1d5db' } },
  ];
  Plotly.newPlot('smart-stratified-chart', data, { barmode: 'group', xaxis: {tickangle: -45}, yaxis: {title: 'القيمة'}, margin: {t: 20, b: 100, l: 60, r: 20} });
  const significant = filtered.filter(s => s.deviation_pct > 15 || s.deviation_pct < -15).length;
  document.getElementById('smart-strat-text').textContent = `${significant} من ${filtered.length} مستشفى يختلف بشكل ملحوظ عن مجموعته النظيرة.`;
}

window.smartDrilldown = async function(hospitalId) {
  if (!smartCurrentData || !smartCurrentData.data) return;
  const d = smartCurrentData.data;
  const anomaly = d.anomalies?.find(a => parseInt(a.hospital_id, 10) === hospitalId);
  const explanation = d.explanations?.find(e => parseInt(e.hospital_id, 10) === hospitalId);

  if (!anomaly) return;

  document.getElementById('smart-drilldown-name').textContent = anomaly.hospital_name || '';
  document.getElementById('smart-drilldown-panel').style.display = 'block';
  document.getElementById('smart-drilldown-panel').scrollIntoView({behavior: 'smooth'});

  if (explanation?.top_factors && explanation.top_factors.length > 0) {
    const factors = explanation.top_factors;
    const wfData = [{
      type: 'waterfall', orientation: 'v',
      x: factors.map(f => smartTranslateFeature(f.arabic_label)),
      y: factors.map(f => f.shap_value),
      connector: {line: {color: '#ccc'}},
      decreasing: {marker: {color: SMART_COLORS.shap_negative}},
      increasing: {marker: {color: SMART_COLORS.shap_positive}},
      text: factors.map(f => f.shap_value > 0 ? '+' + f.shap_value.toFixed(3) : f.shap_value.toFixed(3)),
      textposition: 'outside',
    }];
    Plotly.newPlot('smart-shap-waterfall', wfData, { margin: {t: 20, b: 80, l: 60, r: 20}, yaxis: {title: 'قيمة SHAP'} });
  } else {
    Plotly.purge('smart-shap-waterfall');
  }
  document.getElementById('smart-drilldown-text').textContent = explanation?.text_explanation || 'لا توجد تفسيرات متاحة.';

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

async function loadHospitalAnalysis(hospitalId, currentMonth) {
  const panel = document.getElementById('smart-hospital-panel');
  panel.style.display = 'block';
  document.getElementById('smart-hospital-name').textContent = 'جاري التحميل...';

  try {
    const drilldown = await apiSmartGet(`/smart/drilldown/${hospitalId}/${currentMonth}`);
    document.getElementById('smart-hospital-name').textContent = drilldown.hospital_name || '';

    const anomaly = drilldown.anomaly;
    const explanation = drilldown.explanation;

    const kpiHtml = `
      <div class="card" style="text-align:center;padding:0.8rem;border-radius:8px;border-top:3px solid ${anomaly ? (anomaly.severity === 'critical' ? SMART_COLORS.critical : anomaly.severity === 'warning' ? SMART_COLORS.warning : SMART_COLORS.normal) : '#ccc'};">
        <div style="font-size:1.8rem;font-weight:700;color:${anomaly ? (anomaly.severity === 'critical' ? SMART_COLORS.critical : anomaly.severity === 'warning' ? SMART_COLORS.warning : SMART_COLORS.normal) : '#666'};">${anomaly ? anomaly.anomaly_score.toFixed(2) : '-'}</div>
        <div style="font-size:0.75rem;color:#444;font-weight:600;">درجة الشذوذ</div>
        <div style="font-size:0.65rem;color:#888;margin-top:0.2rem;">${anomaly ? (anomaly.severity === 'critical' ? 'تتجاوز 0.6 - يحتاج تدخل' : anomaly.severity === 'warning' ? 'بين 0.3 و 0.6 - يحتاج مراقبة' : 'أقل من 0.3 - ضمن الطبيعي') : ''}</div>
      </div>
      <div class="card" style="text-align:center;padding:0.8rem;border-radius:8px;">
        <div style="font-size:1rem;font-weight:600;">${anomaly ? (anomaly.severity === 'critical' ? '\u274C حرج' : anomaly.severity === 'warning' ? '\u26A0\uFE0F تنبيه' : '\u2705 طبيعي') : '-'}</div>
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
        <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;">\u062A\u0641\u0633\u064A\u0631 SHAP</div>
      </div>
      <div class="card" style="text-align:center;padding:0.8rem;border-radius:8px;">
        <div style="font-size:0.75rem;color:#666;line-height:1.5;">
          ${anomaly ? Object.entries(anomaly.method_scores || {}).map(([k, v]) => {
            const labels = {isolation_forest: 'IF', lof: 'LOF', mahalanobis: 'Mahal', residual: 'Resid'};
            return `<span style="display:inline-block;margin:0.1rem;padding:0.1rem 0.3rem;background:#f3f4f6;border-radius:3px;font-size:0.65rem;">${labels[k] || k}: ${v.toFixed(2)}</span>`;
          }).join(' ') : ''}
        </div>
        <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;">\u062F\u0631\u0648\u0633 \u0627\u0644\u062E\u0635\u0627\u0626\u0635</div>
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
  } catch (e) {
    document.getElementById('smart-hospital-name').textContent = 'خطأ في التحميل';
    console.error('Hospital analysis error:', e);
  }
}
