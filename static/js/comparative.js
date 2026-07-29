let comparativeCurrentMonth = null;
let comparativeCurrentData = null;
let comparisonChart = null;
let reportLang = 'ar';

const langMap = {
    'ar': {
        title: 'التحليل المقارن المتقدم',
        labelMonth: 'الشهر:',
        labelComparison: 'طريقة المقارنة:',
        labelHospital: 'المستشفى:',
        btnGenerate: 'توليد التقرير الذكي الشامل',
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
        kpiConfidence: 'نسبة الثقة',
        kpiQuality: 'جودة البيانات',
    },
    'en': {
        title: 'Advanced Comparative Analysis',
        labelMonth: 'Month:',
        labelComparison: 'Comparison Type:',
        labelHospital: 'Hospital:',
        btnGenerate: 'Generate Smart Report',
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
        kpiConfidence: 'Confidence Score',
        kpiQuality: 'Data Quality',
    }
};

function toggleReportLang() {
    reportLang = reportLang === 'ar' ? 'en' : 'ar';
    document.getElementById('report-lang-toggle').textContent = reportLang === 'ar' ? '🇬🇧 English' : '🇸🇦 العربية';
    applyReportLang(reportLang);
    if (comparativeCurrentMonth) {
        generateComprehensiveReport(comparativeCurrentMonth);
    }
}

function applyReportLang(lang) {
    const t = langMap[lang];
    if (!t) return;

    document.getElementById('comparative-title').textContent = t.title;
    document.getElementById('label-month').textContent = t.labelMonth;
    document.getElementById('label-comparison').textContent = t.labelComparison;
    document.getElementById('label-hospital').textContent = t.labelHospital;
    document.getElementById('btn-generate').textContent = t.btnGenerate;
    document.getElementById('loading-text').textContent = t.loadingText;
    document.getElementById('section-executive').textContent = t.sectionExecutive;
    document.getElementById('section-indicators').textContent = t.sectionIndicators;
    document.getElementById('section-anomalies').textContent = t.sectionAnomalies;
    document.getElementById('section-clustering').textContent = t.sectionClustering;
    document.getElementById('section-stratified').textContent = t.sectionStratified;
    document.getElementById('section-recommendations').textContent = t.sectionRecommendations;
    document.getElementById('chart-title').textContent = t.chartTitle;
    document.getElementById('peer-title').textContent = t.peerTitle;
    document.getElementById('peer-rank').textContent = t.peerRank;
    document.getElementById('peer-hospital').textContent = t.peerHospital;
    document.getElementById('peer-percentile').textContent = t.peerPercentile;
    document.getElementById('peer-assessment').textContent = t.peerAssessment;
    document.getElementById('kpi-label-total').textContent = t.kpiTotal;
    document.getElementById('kpi-label-anomalies').textContent = t.kpiAnomalies;
    document.getElementById('kpi-label-confidence').textContent = t.kpiConfidence;
    document.getElementById('kpi-label-quality').textContent = t.kpiQuality;

    // Set report text direction based on language
    const reportDiv = document.getElementById('report-executive-summary');
    if (reportDiv) {
        reportDiv.style.direction = lang === 'ar' ? 'rtl' : 'ltr';
        reportDiv.style.textAlign = lang === 'ar' ? 'right' : 'left';
    }
}

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

  // Load hospitals list
  try {
    const hospitalsRes = await apiComparativeGet('/hospitals');
    const hospitals = hospitalsRes?.hospitals || hospitalsRes || [];
    const hospitalSelect = document.getElementById('hospital-select');
    hospitalSelect.innerHTML = '<option value="">جميع المستشفيات</option>';
    hospitals.forEach(h => {
      const opt = document.createElement('option');
      opt.value = h.id;
      opt.textContent = h.name;
      hospitalSelect.appendChild(opt);
    });
  } catch (e) {
    console.error('خطأ في تحميل المستشفيات:', e);
  }

  document.getElementById('btn-generate').addEventListener('click', () => {
    const month = monthSelect.value;
    const hospitalId = document.getElementById('hospital-select').value;
    const comparisonType = document.getElementById('comparison-type').value;
    generateComprehensiveReport(month);
    generateAdvancedComparison(month, hospitalId, comparisonType);
  });

  if (months.length > 0) {
    const lastMonth = months[months.length - 1];
    monthSelect.value = lastMonth.month || lastMonth;
  }
};

function toggleSection(header) {
  header.classList.toggle('open');
  const body = header.nextElementSibling;
  body.classList.toggle('open');
}

function showAlert(message, type = 'info') {
  let container = document.getElementById('alert-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'alert-container';
    container.className = 'alert-container';
    document.body.appendChild(container);
  }

  const alert = document.createElement('div');
  alert.className = `alert-item ${type}`;
  alert.innerHTML = `
    <span>${message}</span>
    <span class="close-btn" onclick="this.parentElement.remove()">✕</span>
  `;

  container.appendChild(alert);

  setTimeout(() => {
    if (alert.parentElement) {
      alert.remove();
    }
  }, 5000);
}

function updateKPIDashboard(data) {
  const dashboard = document.getElementById('kpi-dashboard');
  if (!dashboard || !data) {
    if (dashboard) dashboard.style.display = 'none';
    return;
  }

  document.getElementById('kpi-total-hospitals').textContent = data.total_hospitals || '-';
  document.getElementById('kpi-anomalies').textContent = data.anomaly_count || '0';
  document.getElementById('kpi-confidence').textContent = data.confidence_score || '-';
  document.getElementById('kpi-quality').textContent = data.quality_score || '-';
  dashboard.style.display = 'grid';

  if (data.anomaly_count > 0) {
    showAlert(reportLang === 'ar' ? `يوجد ${data.anomaly_count} مستشفى بحاجة للانتباه` : `${data.anomaly_count} hospitals need attention`, 'warning');
  }
  if (data.critical_anomalies > 0) {
    showAlert(reportLang === 'ar' ? `يوجد ${data.critical_anomalies} حالة حرجة!` : `${data.critical_anomalies} critical cases!`, 'danger');
  }
}

function parseReportSections(reportText) {
  const sections = {};
  const sectionNames = {
    'الملخص التنفيذي': 'report-executive-summary',
    'تحليل المؤشرات': 'report-indicators',
    'تحليل الشذوذ': 'report-anomalies',
    'التجميع': 'report-clustering',
    'الارتباطات': 'report-clustering',
    'المقارنة الطبقية': 'report-stratified',
    'التوصيات': 'report-recommendations',
  };

  let currentSection = 'report-executive-summary';
  const lines = reportText.split('\n');

  lines.forEach(line => {
    const trimmed = line.trim();
    for (const [name, id] of Object.entries(sectionNames)) {
      if (trimmed.includes(name)) {
        currentSection = id;
        return;
      }
    }

    if (!sections[currentSection]) {
      sections[currentSection] = [];
    }
    sections[currentSection].push(line);
  });

  return sections;
}

function renderReportSections(reportText) {
  const sections = parseReportSections(reportText);

  for (const [id, lines] of Object.entries(sections)) {
    const element = document.getElementById(id);
    if (element) {
      element.textContent = lines.join('\n');
    }
  }

  document.getElementById('comparative-report-output').style.display = 'block';
}

async function generateComprehensiveReport(month) {
  comparativeCurrentMonth = month;
  compShowLoading();
  document.getElementById('comparative-status').textContent = reportLang === 'ar' ? 'جاري توليد التقرير...' : 'Generating report...';
  document.getElementById('comparative-placeholder').style.display = 'none';
  document.getElementById('comparative-report-output').style.display = 'none';

  try {
    const result = await apiComparativeGet(`/comparative/comprehensive-report/${month}?lang=${reportLang}`);
    comparativeCurrentData = result;

    renderReportSections(result.report);

    if (result.data) {
      updateKPIDashboard(result.data.kpi);
    }

    showAlert(reportLang === 'ar' ? 'تم توليد التقرير بنجاح' : 'Report generated successfully', 'success');
    document.getElementById('comparative-status').textContent = reportLang === 'ar' ? 'تم التحديث بنجاح' : 'Updated successfully';
  } catch (e) {
    document.getElementById('comparative-report-output').style.display = 'block';
    showAlert((reportLang === 'ar' ? 'خطأ في توليد التقرير: ' : 'Error generating report: ') + e.message, 'danger');
    document.getElementById('comparative-status').textContent = (reportLang === 'ar' ? 'خطأ في التحميل: ' : 'Load error: ') + e.message;
  } finally {
    compHideLoading();
  }
}

async function generateAdvancedComparison(month, hospitalId, comparisonType) {
  document.getElementById('comparison-chart-container').style.display = 'none';
  document.getElementById('peer-comparison-container').style.display = 'none';

  try {
    let url = `/comparative/advanced-comparison/${month}`;
    const params = new URLSearchParams();
    if (hospitalId) params.append('hospital_id', hospitalId);
    if (comparisonType) params.append('comparison_type', comparisonType);
    if (params.toString()) url += '?' + params.toString();

    const result = await apiComparativeGet(url);

    // Render chart
    if (result.chart_config && result.chart_config.data && result.chart_config.data.labels && result.chart_config.data.labels.length > 0) {
      renderComparisonChart(result.chart_config);
      document.getElementById('chart-filter-badge').textContent = comparisonType === 'all' ? 'جميع المستشفيات' : comparisonType === 'governorate' ? 'نفس المحافظة' : 'نفس النوع';
      document.getElementById('comparison-chart-container').style.display = 'block';
    }

    // Render peer comparison table
    if (result.comparison_data && result.comparison_data.peer_comparison && result.comparison_data.peer_comparison.length > 0) {
      renderPeerComparisonTable(result.comparison_data.peer_comparison);
      document.getElementById('peer-filter-badge').textContent = comparisonType === 'all' ? 'جميع المستشفيات' : comparisonType === 'governorate' ? 'نفس المحافظة' : 'نفس النوع';
      document.getElementById('peer-comparison-container').style.display = 'block';
    }
  } catch (e) {
    console.error('خطأ في المقارنة المتقدمة:', e);
  }
}

function renderComparisonChart(chartConfig) {
  const ctx = document.getElementById('comparison-chart').getContext('2d');

  if (comparisonChart) {
    comparisonChart.destroy();
  }

  comparisonChart = new Chart(ctx, {
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
        legend: {
          position: 'bottom'
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          title: {
            display: true,
            text: 'إجمالي الحالات'
          }
        },
        x: {
          title: {
            display: true,
            text: 'الشهر'
          }
        }
      }
    }
  });
}

function renderPeerComparisonTable(peerComparison) {
  const tbody = document.querySelector('#peer-comparison-table tbody');
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
