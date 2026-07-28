let comparativeCurrentMonth = null;
let comparativeCurrentData = null;

async function apiComparativeGet(path) {
  const base = document.getElementById('apiBase')?.value || '';
  const res = await fetch(base + path);
  return res.json();
}

function compShowLoading() {
  const el = document.getElementById('comparative-loading-overlay');
  if (el) { el.style.display = 'flex'; }
}

function compHideLoading() {
  const el = document.getElementById('comparative-loading-overlay');
  if (el) { el.style.display = 'none'; }
}

window.initComparative = async function() {
  const monthsRes = await apiComparativeGet('/analysis/months');
  const months = monthsRes?.months || monthsRes || [];
  const monthSelect = document.getElementById('comparative-month');
  monthSelect.innerHTML = '';
  months.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.month || m;
    opt.textContent = m.month || m;
    monthSelect.appendChild(opt);
  });

  document.getElementById('comparative-generate').addEventListener('click', () => {
    generateComprehensiveReport(monthSelect.value);
  });

  if (months.length > 0) {
    const lastMonth = months[months.length - 1];
    monthSelect.value = lastMonth.month || lastMonth;
  }
};

async function generateComprehensiveReport(month) {
  comparativeCurrentMonth = month;
  compShowLoading();
  document.getElementById('comparative-status').textContent = 'جاري توليد التقرير...';
  document.getElementById('comparative-placeholder').style.display = 'none';
  document.getElementById('comparative-report-output').style.display = 'none';
  document.getElementById('comparative-data-section').style.display = 'none';

  try {
    const result = await apiComparativeGet(`/comparative/comprehensive-report/${month}`);
    comparativeCurrentData = result;

    document.getElementById('comparative-report-text').textContent = result.report;
    document.getElementById('comparative-report-month-badge').textContent = `الشهر: ${result.month}`;
    document.getElementById('comparative-report-output').style.display = 'block';

    if (result.data) {
      renderComparativeDataCards(result.data);
      document.getElementById('comparative-data-section').style.display = 'block';
    }

    document.getElementById('comparative-status').textContent = 'تم التحديث بنجاح';
  } catch (e) {
    document.getElementById('comparative-report-text').textContent = 'خطأ في توليد التقرير: ' + e.message;
    document.getElementById('comparative-report-output').style.display = 'block';
    document.getElementById('comparative-status').textContent = 'خطأ في التحميل: ' + e.message;
  } finally {
    compHideLoading();
  }
}

function renderComparativeDataCards(data) {
  const container = document.getElementById('comparative-data-cards');
  const kpi = data.kpi || {};
  const anomalies = data.anomalies || [];
  const clustering = data.clustering || {};

  const criticalCount = anomalies.filter(a => a.severity === 'critical').length;
  const warningCount = anomalies.filter(a => a.severity === 'warning').length;
  const clustersCount = clustering.n_clusters || 0;
  const silhouette = clustering.silhouette_score || 0;

  const cardStyle = 'text-align:center;padding:1rem;border-radius:8px;';
  const hoverJs = 'onmouseenter="this.style.transform=\'translateY(-3px)\';this.style.boxShadow=\'0 6px 20px rgba(0,0,0,0.12)\'" onmouseleave="this.style.transform=\'none\';this.style.boxShadow=\'none\'"';

  container.innerHTML = `
    <div class="card" style="${cardStyle}border-top:3px solid ${criticalCount > 0 ? '#ef4444' : '#22c55e'};" ${hoverJs}>
      <div style="font-size:2rem;font-weight:700;color:${criticalCount > 0 ? '#ef4444' : '#22c55e'};">${kpi.total_anomalies || anomalies.length}</div>
      <div style="font-size:0.8rem;color:#444;font-weight:600;margin:0.3rem 0;">مستشفى شاذ</div>
      <div style="font-size:0.7rem;color:#888;">${criticalCount} حرج + ${warningCount} تنبيه</div>
    </div>

    <div class="card" style="${cardStyle}border-top:3px solid #3b82f6;" ${hoverJs}>
      <div style="font-size:2rem;font-weight:700;color:#3b82f6;">${kpi.affected_governorates || 0}</div>
      <div style="font-size:0.8rem;color:#444;font-weight:600;margin:0.3rem 0;">محافظات متأثرة</div>
      <div style="font-size:0.7rem;color:#888;">تحتوي على انحرافات</div>
    </div>

    <div class="card" style="${cardStyle}border-top:3px solid #8b5cf6;" ${hoverJs}>
      <div style="font-size:2rem;font-weight:700;color:#8b5cf6;">${clustersCount}</div>
      <div style="font-size:0.8rem;color:#444;font-weight:600;margin:0.3rem 0;">مجموعات تجميع</div>
      <div style="font-size:0.7rem;color:#888;">الجودة: ${silhouette.toFixed(2)}</div>
    </div>

    <div class="card" style="${cardStyle}border-top:3px solid #f97316;" ${hoverJs}>
      <div style="font-size:1rem;font-weight:700;color:#f97316;word-break:break-word;line-height:1.4;">${kpi.top_contributing_factor || 'غير محدد'}</div>
      <div style="font-size:0.8rem;color:#444;font-weight:600;margin:0.3rem 0;">العامل الأكثر تأثيراً</div>
      <div style="font-size:0.7rem;color:#888;">من تحليل SHAP</div>
    </div>
  `;
}
