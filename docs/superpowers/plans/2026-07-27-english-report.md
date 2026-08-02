# خطة تنفيذ دعم اللغة الإنجليزية في التقرير الذكي

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** إضافة دعم كامل للغة الإنجليزية للتقرير الذكي الشامل (محتوى + واجهة)

**Architecture:** تعديل محرك التقرير لقبول معامل lang، إضافة زر تبديل لغة في الواجهة

**Tech Stack:** Python, FastAPI, JavaScript, HTML/CSS

## Global Constraints
- Python 3.14
- FastAPI
- Google Gemini API
- Arabic + English support
- زر تبديل داخل التقرير (دون إعادة تحميل)

---

## File Structure

| الملف | المسؤولية |
|-------|-----------|
| `app/engine/comparative/report_generator.py` | إضافة _build_english_prompt + معامل lang |
| `app/api/comparative.py` | إضافة معامل lang=ar/en |
| `static/tabs/comparative.html` | إضافة زر تبديل لغة + عناوين ثنائية |
| `static/js/comparative.js` | إضافة reportLang + toggleReportLang |
| `tests/test_comparative.py` | اختبارات التقرير بالإنجليزية |

---

### Task 1: دعم الإنجليزية في محرك التقرير و API

**Files:**
- Modify: `app/engine/comparative/report_generator.py`
- Modify: `app/api/comparative.py`
- Test: `tests/test_comparative.py`

- [ ] **Step 1: تعديل report_generator.py - إضافة دعم اللغة**

```python
def build_comprehensive_prompt(analytics, lang: str = "ar") -> str:
    """بناء Prompt شامل حسب اللغة"""
    if lang == "en":
        return _build_english_prompt(analytics)
    return _build_arabic_prompt(analytics)


def _build_arabic_prompt(analytics) -> str:
    """Prompt عربي - موجود حالياً"""
    # ... الكود الحالي ...


def _build_english_prompt(analytics) -> str:
    """Build comprehensive prompt in English"""
    kpi = analytics.kpi
    anomalies = analytics.anomalies or []
    clustering = analytics.clustering
    correlations = analytics.correlations
    residuals = analytics.residuals or []
    stratified = analytics.stratified or []
    explanations = analytics.explanations or []
    geo = analytics.geo
    xgboost = analytics.xgboost_predictions

    critical_count = sum(1 for a in anomalies if a.severity == "critical")
    warning_count = sum(1 for a in anomalies if a.severity == "warning")
    strong_correlations = correlations.strong_correlations if correlations else []

    anomaly_details = []
    for a in anomalies[:10]:
        anomaly_details.append({
            "hospital": a.hospital_name,
            "score": a.anomaly_score,
            "severity": a.severity,
            "governorate": a.governorate,
        })

    residual_details = []
    for r in residuals[:10]:
        residual_details.append({
            "hospital": r.hospital_name,
            "indicator": r.indicator,
            "actual": round(r.actual_value, 2),
            "predicted": round(r.predicted_value, 2),
            "z_score": round(r.residual_z_score, 2),
        })

    stratified_details = []
    for s in stratified[:10]:
        stratified_details.append({
            "hospital": s.hospital_name,
            "indicator": s.indicator,
            "value": round(s.hospital_value, 2),
            "peer_mean": round(s.peer_group_mean, 2),
            "deviation_pct": round(s.deviation_pct, 2),
        })

    explanation_details = []
    for e in explanations[:5]:
        top_factors = []
        for f in e.top_factors[:3]:
            top_factors.append({
                "feature": f.feature,
                "shap_value": round(f.shap_value, 4),
                "direction": f.direction,
            })
        explanation_details.append({
            "hospital": e.hospital_name,
            "severity": e.severity,
            "top_factors": top_factors,
        })

    geo_details = {}
    if geo and geo.governorates:
        for g in geo.governorates:
            geo_details[g.governorate] = {
                "hospital_count": g.hospital_count,
                "avg_anomaly_score": round(g.avg_anomaly_score, 3),
                "outlier_count": g.outlier_count,
            }

    xgboost_details = {}
    if xgboost:
        xgboost_details = {
            "model_r2": round(xgboost.model_r2, 3),
            "model_mae": round(xgboost.model_mae, 3),
            "hospitals_trained": xgboost.hospitals_trained,
        }

    prompt = f"""
    You are a health data analysis expert for Gaza Strip hospitals.

    Generate a comprehensive smart report in English covering:

    === Executive Summary ===
    - System status: {kpi.month_status if kpi else "N/A"}
    - Anomalous hospitals: {kpi.total_anomalies if kpi else 0}
    - Critical hospitals: {critical_count}
    - Hospitals needing attention: {warning_count}
    - Top contributing factor: {kpi.top_contributing_factor if kpi else "N/A"}

    === Indicator Analysis ===
    All clinical indicators:
    - Caesarean rate (cs_rate)
    - Severe maternal morbidity (smm_total)
    - Maternal deaths (mat_deaths)
    - Neonatal deaths (nd)
    - Stillbirths (sb)
    - Preterm births (preterm)
    - Low birth weight (lbw)
    - Total births (total_births)
    - High risk cases (high_risk)
    - Adolescent cases (adolescent)

    === Anomaly Analysis ===
    Abnormal hospitals:
    {anomaly_details}

    === Clustering ===
    Hospital groups:
    - Number of clusters: {clustering.n_clusters if clustering else 0}
    - Clustering quality: {clustering.silhouette_score if clustering else 0:.2f}

    === Correlations ===
    Indicator relationships:
    {strong_correlations[:5]}

    === Residuals ===
    Deviation from predictions:
    {residual_details}

    === Stratified Comparison ===
    Hospital vs peer comparison:
    {stratified_details}

    === SHAP Explanations ===
    Factors responsible for anomalies:
    {explanation_details}

    === Geographic Map ===
    Geographic distribution:
    {geo_details}

    === Predictions ===
    XGBoost forecasts:
    {xgboost_details}

    The report MUST:
    - Be in English
    - Be easy to understand
    - Include numbers and statistics
    - Include actionable recommendations
    - Cover all sections above
    """
    return prompt


def generate_comprehensive_report(session: Session, month: str, lang: str = "ar") -> Dict[str, Any]:
    """توليد تقرير ذكي شامل حسب اللغة"""
    analytics = run_smart_analytics(session, month)
    prompt = build_comprehensive_prompt(analytics, lang)
    report_text = _call_gemini_api(prompt)

    # باقي الكود كما هو ...
```

- [ ] **Step 2: تعديل API - إضافة معامل lang**

```python
# app/api/comparative.py
@router.get("/comprehensive-report/{month}")
def get_comprehensive_report(
    month: str,
    lang: str = Query("ar", description="لغة التقرير (ar/en)"),
    db: Session = Depends(get_db)
):
    """توليد تقرير ذكي شامل"""
    try:
        result = generate_comprehensive_report(db, month, lang)
        return result
    except Exception as e:
        error_msg = f"Error generating report: {str(e)}" if lang == "en" else f"خطأ في توليد التقرير: {str(e)}"
        raise HTTPException(status_code=500, detail=error_msg)
```

- [ ] **Step 3: إضافة اختبارات للإنجليزية**

```python
# tests/test_comparative.py
def test_build_english_prompt_returns_string(db_session):
    """اختبار أن prompt الإنجليزية يُعيد نص"""
    analytics = run_smart_analytics(db_session, "2026-06")
    prompt = build_comprehensive_prompt(analytics, "en")
    assert isinstance(prompt, str)
    assert len(prompt) > 100
    assert "Executive Summary" in prompt


def test_generate_comprehensive_report_english(db_session):
    """اختبار توليد تقرير بالإنجليزية"""
    result = generate_comprehensive_report(db_session, "2026-06", lang="en")
    assert "month" in result
    assert "report" in result
    assert "data" in result


def test_comprehensive_report_endpoint_english(client):
    """اختبار endpoint بالإنجليزية"""
    response = client.get("/comparative/comprehensive-report/2026-06?lang=en")
    assert response.status_code == 200
    data = response.json()
    assert "month" in data
```

- [ ] **Step 4: تشغيل الاختبارات**

Run: `pytest tests/test_comparative.py -v --tb=short`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/comparative/report_generator.py app/api/comparative.py tests/test_comparative.py
git commit -m "feat: add English language support to report generator and API"
```

---

### Task 2: دعم الإنجليزية في الواجهة

**Files:**
- Modify: `static/tabs/comparative.html`
- Modify: `static/js/comparative.js`

- [ ] **Step 1: إضافة زر تبديل اللغة وعناوين ثنائية في HTML**

```html
<!-- static/tabs/comparative.html -->
<div id="comparative-tab" class="tab-content" style="display:none;">
    <div class="container-fluid">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <h2 id="comparative-title">التحليل المقارن المتقدم</h2>
            <button id="report-lang-toggle" class="btn btn-sm btn-outline" onclick="toggleReportLang()">
                🇬🇧 English
            </button>
        </div>
        
        <!-- KPI Dashboard -->
        <div id="kpi-dashboard" class="kpi-grid" style="display:none;">
            <div class="kpi-card">
                <div class="icon">🏥</div>
                <div class="value" id="kpi-total-hospitals">-</div>
                <div class="label" id="kpi-label-total">إجمالي المستشفيات</div>
            </div>
            <div class="kpi-card danger">
                <div class="icon">⚠️</div>
                <div class="value" id="kpi-anomalies">-</div>
                <div class="label" id="kpi-label-anomalies">مستشفيات شاذة</div>
            </div>
            <div class="kpi-card warning">
                <div class="icon">📊</div>
                <div class="value" id="kpi-confidence">-</div>
                <div class="label" id="kpi-label-confidence">نسبة الثقة</div>
            </div>
            <div class="kpi-card success">
                <div class="icon">✅</div>
                <div class="value" id="kpi-quality">-</div>
                <div class="label" id="kpi-label-quality">جودة البيانات</div>
            </div>
        </div>
        
        <!-- اختيار الشهر وطريقة المقارنة -->
        <div class="row mb-3">
            <div class="col-md-3">
                <label id="label-month">الشهر:</label>
                <select id="comparative-month" class="form-control"></select>
            </div>
            <div class="col-md-3">
                <label id="label-comparison">طريقة المقارنة:</label>
                <select id="comparison-type" class="form-control">
                    <option value="all">جميع المستشفيات</option>
                    <option value="governorate">نفس المحافظة</option>
                    <option value="type">نفس النوع</option>
                </select>
            </div>
            <div class="col-md-3">
                <label id="label-hospital">المستشفى:</label>
                <select id="hospital-select" class="form-control">
                    <option value="">جميع المستشفيات</option>
                </select>
            </div>
            <div class="col-md-3">
                <label>&nbsp;</label>
                <button id="comparative-generate" class="btn btn-primary btn-block" id="btn-generate">
                    توليد التقرير الذكي
                </button>
            </div>
        </div>
        
        <!-- التحميل -->
        <div id="comparative-loading" style="display:none;" class="text-center my-4">
            <div class="spinner-border text-primary" role="status">
                <span class="sr-only">جاري التحميل...</span>
            </div>
            <p id="loading-text">جاري توليد التقرير الذكي...</p>
        </div>
        
        <!-- التقرير بأقسام قابلة للطي -->
        <div id="comparative-report-output" style="display:none;">
            <!-- الملخص التنفيذي -->
            <div class="collapsible-section">
                <div class="collapsible-header open" onclick="toggleSection(this)">
                    <span id="section-executive">📋 الملخص التنفيذي</span>
                    <span class="arrow">▼</span>
                </div>
                <div class="collapsible-body open">
                    <div id="report-executive-summary" style="white-space: pre-wrap; direction: rtl; text-align: right;"></div>
                </div>
            </div>
            <!-- تحليل المؤشرات -->
            <div class="collapsible-section">
                <div class="collapsible-header" onclick="toggleSection(this)">
                    <span id="section-indicators">📊 تحليل المؤشرات</span>
                    <span class="arrow">▼</span>
                </div>
                <div class="collapsible-body">
                    <div id="report-indicators"></div>
                </div>
            </div>
            <!-- تحليل الشذوذ -->
            <div class="collapsible-section">
                <div class="collapsible-header" onclick="toggleSection(this)">
                    <span id="section-anomalies">🔍 تحليل الشذوذ</span>
                    <span class="arrow">▼</span>
                </div>
                <div class="collapsible-body">
                    <div id="report-anomalies"></div>
                </div>
            </div>
            <!-- التجميع والارتباطات -->
            <div class="collapsible-section">
                <div class="collapsible-header" onclick="toggleSection(this)">
                    <span id="section-clustering">🔗 التجميع والارتباطات</span>
                    <span class="arrow">▼</span>
                </div>
                <div class="collapsible-body">
                    <div id="report-clustering"></div>
                </div>
            </div>
            <!-- المقارنة الطبقية -->
            <div class="collapsible-section">
                <div class="collapsible-header" onclick="toggleSection(this)">
                    <span id="section-stratified">📈 المقارنة الطبقية</span>
                    <span class="arrow">▼</span>
                </div>
                <div class="collapsible-body">
                    <div id="report-stratified"></div>
                </div>
            </div>
            <!-- التوصيات -->
            <div class="collapsible-section">
                <div class="collapsible-header" onclick="toggleSection(this)">
                    <span id="section-recommendations">💡 التوصيات الإجرائية</span>
                    <span class="arrow">▼</span>
                </div>
                <div class="collapsible-body">
                    <div id="report-recommendations"></div>
                </div>
            </div>
        </div>
        
        <!-- الرسم البياني -->
        <div id="comparison-chart-container" class="card mt-4" style="display:none;">
            <div class="card-body">
                <h5 id="chart-title">مقارنة أداء المستشفيات عبر الأشهر</h5>
                <canvas id="comparison-chart"></canvas>
            </div>
        </div>
        
        <!-- جدول مقارنة الأقران -->
        <div id="peer-comparison-container" class="card mt-4" style="display:none;">
            <div class="card-body">
                <h5 id="peer-title">مقارنة المستشفيات ببعضها</h5>
                <table id="peer-comparison-table" class="table table-striped">
                    <thead>
                        <tr>
                            <th id="peer-rank">الترتيب</th>
                            <th id="peer-hospital">المستشفى</th>
                            <th id="peer-percentile">النسبة المئوية</th>
                            <th id="peer-assessment">التقييم</th>
                        </tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>
        </div>
    </div>
</div>
```

- [ ] **Step 2: إضافة منطق التبديل في JS**

```javascript
// static/js/comparative.js

let reportLang = 'ar';

const langMap = {
    'ar': {
        title: 'التحليل المقارن المتقدم',
        labelMonth: 'الشهر:',
        labelComparison: 'طريقة المقارنة:',
        labelHospital: 'المستشفى:',
        btnGenerate: 'توليد التقرير الذكي',
        loadingText: 'جاري توليد التقرير الذكي...',
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
    // إعادة توليد التقرير إذا كان موجوداً
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
}

async function generateComprehensiveReport(month) {
    comparativeCurrentMonth = month;
    document.getElementById('comparative-loading').style.display = 'block';
    document.getElementById('comparative-report-output').style.display = 'none';
    
    try {
        const result = await apiComparativeGet(`/comparative/comprehensive-report/${month}?lang=${reportLang}`);
        renderReportSections(result.report);
        if (result.data) {
            updateKPIDashboard(result.data.kpi);
        }
        showAlert(
            reportLang === 'ar' ? 'تم توليد التقرير بنجاح' : 'Report generated successfully',
            'success'
        );
    } catch (e) {
        showAlert(
            (reportLang === 'ar' ? 'خطأ في توليد التقرير: ' : 'Error generating report: ') + e.message,
            'danger'
        );
    } finally {
        document.getElementById('comparative-loading').style.display = 'none';
    }
}
```

- [ ] **Step 3: تشغيل الاختبارات**

Run: `pytest tests/test_comparative.py -v --tb=short`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add static/tabs/comparative.html static/js/comparative.js
git commit -m "feat: add English language toggle to report UI"
```

---

### Task 3: تشغيل جميع الاختبارات والتحقق

- [ ] **Step 1: تشغيل اختبارات المقارنة كاملة**

Run: `python -m pytest tests/test_comparative.py -v --tb=short`
Expected: PASS (جميع الاختبارات)

- [ ] **Step 2: Commit النهائي**

```bash
git add .
git commit -m "feat: complete English language support for smart report"
```
