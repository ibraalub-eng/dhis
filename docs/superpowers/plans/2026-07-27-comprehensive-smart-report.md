# خطة تنفيذ التقرير الذكي الشامل

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** إنشاء تقرير ذكي شامل يتضمن جميع تحليلات النظام مع توصيات إجرائية بالعربية

**Architecture:** محرك تقرير جديد يستخدم Google Gemini API لتوليد تقرير شامل بالعربية

**Tech Stack:** Python, FastAPI, Google Gemini API, SQLAlchemy

## Global Constraints
- Python 3.14
- FastAPI
- SQLAlchemy
- Google Gemini API (موجود في app/plugins/ai/providers.py)
- Arabic language output

---

## File Structure

| الملف | المسؤولية |
|-------|-----------|
| `app/engine/comparative/__init__.py` | تهيئة المحرك |
| `app/engine/comparative/report_generator.py` | توليد التقرير الشامل |
| `app/api/comparative.py` | API Endpoint |
| `static/tabs/comparative.html` | واجهة المستخدم |
| `static/js/comparative.js` | منطق الواجهة |
| `tests/test_comparative.py` | الاختبارات |

---

### Task 1: إنشاء محرك التقرير الشامل

**Files:**
- Create: `app/engine/comparative/__init__.py`
- Create: `app/engine/comparative/report_generator.py`
- Test: `tests/test_comparative.py`

**Interfaces:**
- Consumes: `run_smart_analytics()` من `app/engine/smart/__init__.py`
- Consumes: `call_gemini_api()` من `app/plugins/ai/providers.py`
- Produces: `generate_comprehensive_report()`

- [ ] **Step 1: إنشاء __init__.py**

```python
# app/engine/comparative/__init__.py
from app.engine.comparative.report_generator import generate_comprehensive_report

__all__ = ["generate_comprehensive_report"]
```

- [ ] **Step 2: إنشاء report_generator.py**

```python
# app/engine/comparative/report_generator.py
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.engine.smart import run_smart_analytics
from app.plugins.ai.providers import _call_gemini_api


def build_comprehensive_prompt(analytics_data: Dict[str, Any]) -> str:
    """بناء Prompt شامل يتضمن جميع التحليلات"""
    
    kpi = analytics_data.get("kpi", {})
    anomalies = analytics_data.get("anomalies", [])
    clustering = analytics_data.get("clustering", {})
    correlations = analytics_data.get("correlations", {})
    residuals = analytics_data.get("residuals", [])
    stratified = analytics_data.get("stratified", [])
    explanations = analytics_data.get("explanations", [])
    geo = analytics_data.get("geo", {})
    xgboost = analytics_data.get("xgboost", {})
    
    # تحليل الشذوذ
    critical_count = sum(1 for a in anomalies if a.get("severity") == "critical")
    warning_count = sum(1 for a in anomalies if a.get("severity") == "warning")
    
    # تحليل الارتباطات
    strong_correlations = correlations.get("strong_correlations", [])
    
    prompt = f"""
    أنت خبير في تحليل بيانات الصحة في قطاع غزة.
    
    قم بإنشاء تقرير ذكي شامل بالعربية يتضمن:
    
    === الملخص التنفيذي ===
    - حالة النظام: {kpi.get("month_status", "غير محدد")}
    - عدد المستشفيات الشاذة: {kpi.get("total_anomalies", 0)}
    - عدد المستشفيات الحرجة: {critical_count}
    - عدد المستشفيات بحاجة لتنبيه: {warning_count}
    - العامل الأكثر تأثيراً: {kpi.get("top_contributing_factor", "غير محدد")}
    
    === تحليل المؤشرات ===
    تحليل جميع المؤشرات السريرية:
    - معدل القيصارية (cs_rate)
    - المضاعفات الخطيرة (smm_total)
    - الوفيات الأمومية (mat_deaths)
    - وفيات المولودين (nd)
    - الولادات الميتة (sb)
    - الولادات السابقة لأوانها (preterm)
    - نقص وزن الولادة (lbw)
    - إجمالي المواليد (total_births)
    - حالات الخطر العالي (high_risk)
    - الحالات المراهقة (adolescent)
    
    === تحليل الشذوذ ===
    المستشفيات غير الطبيعية:
    {anomalies[:10]}  # أول 10 مستشفيات
    
    === التجميع ===
    تقسيم المستشفيات لمجموعات:
    - عدد المجموعات: {clustering.get("n_clusters", 0)}
    - جودة التجميع: {clustering.get("silhouette_score", 0):.2f}
    
    === الارتباطات ===
    العلاقات بين المؤشرات:
    {strong_correlations[:5]}  # أول 5 علاقات قوية
    
    === البواقي ===
    الانحراف عن التوقعات:
    {residuals[:10]}  # أول 10 مستشفيات
    
    === المقارنة الطبقية ===
    مقارنة كل مستشفى بنظيره:
    {stratified[:10]}  # أول 10 مستشفيات
    
    === شرح SHAP ===
    العوامل المسؤولة عن الشذوذ:
    {explanations[:5]}  # أول 5 مستشفيات
    
    === الخريطة الجغرافية ===
    التوزيع الجغرافي:
    {geo}
    
    === التنبؤات ===
    توقعات XGBoost:
    {xgboost}
    
    التقرير يجب أن يكون:
    - بالعربية الفصحى
    - سهل الفهم
    - يتضمن أرقام وأحصائيات
    - يتضمن توصيات إجرائية واضحة
    - يغطي جميع الجوانب أعلاه
    """
    return prompt


def generate_comprehensive_report(session: Session, month: str) -> Dict[str, Any]:
    """توليد تقرير ذكي شامل"""
    
    # 1. جمع جميع البيانات
    analytics = run_smart_analytics(session, month)
    
    # 2. بناء الـ Prompt
    prompt = build_comprehensive_prompt(analytics.__dict__)
    
    # 3. استدعاء Google Gemini
    report_text = _call_gemini_api(prompt)
    
    # 4. إرجاع التقرير
    return {
        "month": month,
        "report": report_text or "خطأ في توليد التقرير",
        "data": {
            "kpi": analytics.kpi.__dict__ if analytics.kpi else {},
            "anomalies": [a.__dict__ for a in analytics.anomalies] if analytics.anomalies else [],
            "clustering": analytics.clustering.__dict__ if analytics.clustering else {},
            "correlations": analytics.correlations.__dict__ if analytics.correlations else {},
            "residuals": [r.__dict__ for r in analytics.residuals] if analytics.residuals else [],
            "stratified": [s.__dict__ for s in analytics.stratified] if analytics.stratified else [],
            "explanations": [e.__dict__ for e in analytics.explanations] if analytics.explanations else [],
            "geo": analytics.geo.__dict__ if analytics.geo else {},
            "xgboost": analytics.xgboost_predictions.__dict__ if analytics.xgboost_predictions else {},
        }
    }
```

- [ ] **Step 3: إنشاء اختبار أساسي**

```python
# tests/test_comparative.py
import pytest
from app.engine.comparative import generate_comprehensive_report


def test_generate_comprehensive_report_returns_data(db_session):
    """اختبار أن التقرير يُعيد بيانات"""
    result = generate_comprehensive_report(db_session, "2026-06")
    assert "month" in result
    assert "report" in result
    assert "data" in result
    assert result["month"] == "2026-06"
```

- [ ] **Step 4: تشغيل الاختبارات**

Run: `pytest tests/test_comparative.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/comparative/ tests/test_comparative.py
git commit -m "feat: add comprehensive report generator"
```

---

### Task 2: إنشاء API Endpoint

**Files:**
- Create: `app/api/comparative.py`
- Modify: `app/api/__init__.py`
- Test: `tests/test_comparative.py`

**Interfaces:**
- Consumes: `generate_comprehensive_report()` من `app/engine/comparative`
- Produces: `GET /comparative/comprehensive-report/{month}`

- [ ] **Step 1: إنشاء comparative.py**

```python
# app/api/comparative.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.engine.comparative import generate_comprehensive_report

router = APIRouter(prefix="/comparative", tags=["Comparative Analysis"])


@router.get("/comprehensive-report/{month}")
def get_comprehensive_report(month: str, db: Session = Depends(get_db)):
    """توليد تقرير ذكي شامل"""
    try:
        result = generate_comprehensive_report(db, month)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ في توليد التقرير: {str(e)}")
```

- [ ] **Step 2: تعديل __init__.py لتسجيل الـ router**

```python
# في app/api/__init__.py
from app.api.comparative import router as comparative_router

# إضافة الـ router إلى القائمة
routers = [
    ...,
    comparative_router,
]
```

- [ ] **Step 3: إنشاء اختبار API**

```python
# tests/test_comparative.py
from fastapi.testclient import TestClient
from app.main import app


def test_comprehensive_report_endpoint(client):
    """اختبار endpoint التقرير الشامل"""
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "month" in data
    assert "report" in data
    assert "data" in data
```

- [ ] **Step 4: تشغيل الاختبارات**

Run: `pytest tests/test_comparative.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/comparative.py app/api/__init__.py tests/test_comparative.py
git commit -m "feat: add comprehensive report API endpoint"
```

---

### Task 3: إنشاء واجهة المستخدم

**Files:**
- Create: `static/tabs/comparative.html`
- Create: `static/js/comparative.js`

**Interfaces:**
- Consumes: `GET /comparative/comprehensive-report/{month}`
- Produces: واجهة مستخدم للتقرير الشامل

- [ ] **Step 1: إنشاء comparative.html**

```html
<!-- static/tabs/comparative.html -->
<div id="comparative-tab" class="tab-content" style="display:none;">
    <div class="container-fluid">
        <h2>التقرير الذكي الشامل</h2>
        
        <!-- اختيار الشهر -->
        <div class="row mb-3">
            <div class="col-md-4">
                <label>الشهر:</label>
                <select id="comparative-month" class="form-control">
                </select>
            </div>
            <div class="col-md-4">
                <label>&nbsp;</label>
                <button id="comparative-generate" class="btn btn-primary btn-block">
                    توليد التقرير الذكي
                </button>
            </div>
        </div>
        
        <!-- شريط التحميل -->
        <div id="comparative-loading" style="display:none;" class="text-center my-4">
            <div class="spinner-border text-primary" role="status">
                <span class="sr-only">جاري التحميل...</span>
            </div>
            <p>جاري توليد التقرير الذكي...</p>
        </div>
        
        <!-- منطقة عرض التقرير -->
        <div id="comparative-report-output" class="card mt-4">
            <div class="card-body">
                <div id="comparative-report-text" style="white-space: pre-wrap; direction: rtl; text-align: right;">
                    اختر الشهر واضغط "توليد التقرير الذكي" للبدء.
                </div>
            </div>
        </div>
    </div>
</div>
```

- [ ] **Step 2: إنشاء comparative.js**

```javascript
// static/js/comparative.js

let comparativeCurrentMonth = null;

async function apiComparativeGet(path) {
    const base = document.getElementById('apiBase')?.value || '';
    const res = await fetch(base + path);
    return res.json();
}

window.initComparative = async function() {
    // تحميل قائمة الأشهر
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
    
    // زر التوليد
    document.getElementById('comparative-generate').addEventListener('click', () => {
        generateComprehensiveReport(monthSelect.value);
    });
};

async function generateComprehensiveReport(month) {
    comparativeCurrentMonth = month;
    document.getElementById('comparative-loading').style.display = 'block';
    document.getElementById('comparative-report-output').style.display = 'none';
    
    try {
        const result = await apiComparativeGet(`/comparative/comprehensive-report/${month}`);
        
        // عرض التقرير
        document.getElementById('comparative-report-text').textContent = result.report;
        document.getElementById('comparative-report-output').style.display = 'block';
    } catch (e) {
        document.getElementById('comparative-report-text').textContent = 'خطأ في توليد التقرير: ' + e.message;
        document.getElementById('comparative-report-output').style.display = 'block';
    } finally {
        document.getElementById('comparative-loading').style.display = 'none';
    }
}
```

- [ ] **Step 3: إضافة التبويب إلى الصفحة الرئيسية**

```html
<!-- في static/index.html، أضف التبويب -->
<li class="nav-item">
    <a class="nav-link" data-toggle="tab" href="#comparative">التحليل المقارن</a>
</li>
```

- [ ] **Step 4: Commit**

```bash
git add static/tabs/comparative.html static/js/comparative.js static/index.html
git commit -m "feat: add comparative analysis UI"
```

---

### Task 4: إضافة اختبارات شاملة

**Files:**
- Modify: `tests/test_comparative.py`

**Interfaces:**
- Consumes: جميع الملفات المعدلة
- Produces: اختبارات شاملة

- [ ] **Step 1: إضافة اختبارات شاملة**

```python
# tests/test_comparative.py
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_comprehensive_report_returns_data(client):
    """اختبار أن التقرير يُعيد بيانات"""
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "month" in data
    assert "report" in data
    assert "data" in data


def test_comprehensive_report_includes_all_sections(client):
    """اختبار أن التقرير يتضمن جميع الأقسام"""
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    data = response.json()
    
    # التحقق من وجود جميع الأقسام في البيانات
    assert "kpi" in data["data"]
    assert "anomalies" in data["data"]
    assert "clustering" in data["data"]
    assert "correlations" in data["data"]
    assert "residuals" in data["data"]
    assert "stratified" in data["data"]
    assert "explanations" in data["data"]
    assert "geo" in data["data"]
    assert "xgboost" in data["data"]


@patch("app.engine.comparative.report_generator._call_gemini_api")
def test_comprehensive_report_uses_gemini(mock_gemini, client):
    """اختبار أن التقرير يستخدم Gemini API"""
    mock_gemini.return_value = "تقرير تجريبي بالعربية"
    
    response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    assert mock_gemini.called


def test_comprehensive_report_error_handling(client):
    """اختبار معالجة الأخطاء"""
    response = client.get("/comparative/comprehensive-report/2026-99")
    assert response.status_code == 500
```

- [ ] **Step 2: تشغيل الاختبارات**

Run: `pytest tests/test_comparative.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_comparative.py
git commit -m "test: add comprehensive report tests"
```

---

### Task 5: تشغيل جميع الاختبارات والتحقق

**Files:**
- None

**Interfaces:**
- Consumes: جميع الملفات المعدلة
- Produces: جميع الاختبارات ناجحة

- [ ] **Step 1: تشغيل جميع الاختبارات**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 2: التحقق من الأداء**

Run: `python -c "import time; start=time.time(); from app.engine.comparative import generate_comprehensive_report; print(f'Load time: {time.time()-start:.2f}s')"`
Expected: < 30 ثانية

- [ ] **Step 3: Commit النهائي**

```bash
git add .
git commit -m "feat: complete comprehensive smart report system"
```
