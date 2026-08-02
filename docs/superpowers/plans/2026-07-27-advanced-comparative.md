# خطة تنفيذ التحليلات المقارنة المتقدمة

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** تحسين التقرير الذكي الشامل بإضافة قسم المقارنة المتقدمة

**Architecture:** إضافة محرك مقارنة متقدمة يستخدم البيانات التاريخية والتنبؤات

**Tech Stack:** Python, FastAPI, SQLAlchemy, Plotly.js

## Global Constraints
- Python 3.14
- FastAPI
- SQLAlchemy
- Google Gemini API
- Arabic language output
- Plotly.js للرسوم البيانية

---

## File Structure

| الملف | المسؤولية |
|-------|-----------|
| `app/engine/comparative/advanced_comparison.py` | محرك المقارنة المتقدمة |
| `app/engine/comparative/__init__.py` | تعديل لتصدير الدوال الجديدة |
| `app/api/comparative.py` | تعديل لإضافة Endpoint جديد |
| `static/tabs/comparative.html` | تعديل لإضافة واجهة المقارنة |
| `static/js/comparative.js` | تعديل لإضافة منطق الواجهة |
| `tests/test_comparative.py` | تعديل لإضافة اختبارات جديدة |

---

### Task 1: إنشاء محرك المقارنة المتقدمة

**Files:**
- Create: `app/engine/comparative/advanced_comparison.py`
- Modify: `app/engine/comparative/__init__.py`
- Test: `tests/test_comparative.py`

**Interfaces:**
- Consumes: `run_smart_analytics()` من `app/engine/smart/__init__.py`
- Produces: `perform_advanced_comparison()`

- [ ] **Step 1: إنشاء advanced_comparison.py**

```python
# app/engine/comparative/advanced_comparison.py
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from app.engine.smart import run_smart_analytics
import numpy as np


@dataclass
class TrendData:
    """بيانات الاتجاه لمستشفى"""
    hospital_id: str
    hospital_name: str
    months: List[str] = field(default_factory=list)
    values: Dict[str, List[float]] = field(default_factory=dict)


@dataclass
class PeerComparison:
    """مقارنة الأقران"""
    hospital_id: str
    hospital_name: str
    percentile: float
    rank: int
    total_hospitals: int
    comparison_label: str


@dataclass
class AdvancedComparisonResult:
    """نتيجة المقارنة المتقدمة"""
    month: str
    trends: List[TrendData] = field(default_factory=list)
    peer_comparisons: List[PeerComparison] = field(default_factory=list)
    predictions: Dict[str, Any] = field(default_factory=dict)
    chart_config: Dict[str, Any] = field(default_factory=dict)


def get_historical_data(session: Session, current_month: str, hospital_id: Optional[str] = None) -> Dict[str, Any]:
    """جلب البيانات التاريخية للمقارنة"""
    from datetime import datetime, timedelta
    
    # تحويل الشهر الحالي إلى تاريخ
    current_date = datetime.strptime(current_month, "%Y-%m")
    
    # جلب آخر 6 أشهر
    months = []
    for i in range(6):
        month_date = current_date - timedelta(days=30 * i)
        months.append(month_date.strftime("%Y-%m"))
    
    months.reverse()
    
    # جمع البيانات لكل شهر
    historical_data = {}
    for month in months:
        try:
            analytics = run_smart_analytics(session, month)
            historical_data[month] = {
                "kpi": analytics.kpi.__dict__ if analytics.kpi else {},
                "anomalies": [a.__dict__ for a in analytics.anomalies] if analytics.anomalies else [],
                "predictions": analytics.xgboost_predictions.__dict__ if analytics.xgboost_predictions else {}
            }
        except Exception:
            historical_data[month] = None
    
    return historical_data


def perform_advanced_comparison(
    session: Session,
    month: str,
    hospital_id: Optional[str] = None,
    comparison_type: str = "all"
) -> AdvancedComparisonResult:
    """إجراء مقارنة متقدمة"""
    
    # 1. جمع البيانات التاريخية
    historical_data = get_historical_data(session, month, hospital_id)
    
    # 2. تحليل الاتجاهات
    trends = analyze_trends(historical_data, hospital_id)
    
    # 3. مقارنة الأقران
    peer_comparisons = compare_peers(session, month, comparison_type)
    
    # 4. التنبؤات (من البيانات الحالية)
    current_analytics = run_smart_analytics(session, month)
    predictions = current_analytics.xgboost_predictions.__dict__ if current_analytics.xgboost_predictions else {}
    
    # 5. تكوين الرسم البياني
    chart_config = generate_comparison_chart(trends, peer_comparisons)
    
    return AdvancedComparisonResult(
        month=month,
        trends=trends,
        peer_comparisons=peer_comparisons,
        predictions=predictions,
        chart_config=chart_config
    )


def analyze_trends(historical_data: Dict[str, Any], hospital_id: Optional[str] = None) -> List[TrendData]:
    """تحليل الاتجاهات عبر الأشهر"""
    trends = []
    
    if not historical_data:
        return trends
    
    # استخراج المستشفيات
    hospitals = set()
    for month_data in historical_data.values():
        if month_data and "anomalies" in month_data:
            for anomaly in month_data["anomalies"]:
                hospitals.add(anomaly.get("hospital_id"))
    
    # إذا تم تحديد مستشفى معين
    if hospital_id:
        hospitals = {hospital_id}
    
    # إنشاء بيانات الاتجاه لكل مستشفى
    for hosp_id in hospitals:
        trend = TrendData(hospital_id=hosp_id, hospital_name=hosp_id)
        
        for month in sorted(historical_data.keys()):
            month_data = historical_data[month]
            if month_data and "kpi" in month_data:
                trend.months.append(month)
                # استخدام إجمالي الحالات كقيمة اتجاه
                value = month_data["kpi"].get("total_cases", 0)
                if "total_cases" not in trend.values:
                    trend.values["total_cases"] = []
                trend.values["total_cases"].append(value)
        
        if trend.months:
            trends.append(trend)
    
    return trends


def compare_peers(session: Session, month: str, comparison_type: str) -> List[PeerComparison]:
    """مقارنة المستشفيات ببعضها"""
    from app.models import Hospital, IndicatorValue, Indicator, Governorate
    
    # جلب المستشفيات
    hospitals = session.query(Hospital).all()
    
    if len(hospitals) < 2:
        return []
    
    # جلب بيانات الشهر المحدد
    month_data = {}
    for hospital in hospitals:
        values = session.query(IndicatorValue).filter(
            IndicatorValue.hospital_id == hospital.id,
            IndicatorValue.month == month
        ).all()
        
        if values:
            total_cases = sum(v.value for v in values if v.value)
            month_data[hospital.id] = {
                "hospital_name": hospital.name,
                "total_cases": total_cases
            }
    
    if not month_data:
        return []
    
    # ترتيب المستشفيات حسب إجمالي الحالات
    sorted_hospitals = sorted(month_data.items(), key=lambda x: x[1]["total_cases"], reverse=True)
    
    # إنشاء المقارنات
    comparisons = []
    total = len(sorted_hospitals)
    
    for rank, (hosp_id, data) in enumerate(sorted_hospitals, 1):
        percentile = (rank / total) * 100
        
        if percentile <= 25:
            label = "متفوق"
        elif percentile <= 50:
            label = "متوسط"
        elif percentile <= 75:
            label = "يحتاج تحسين"
        else:
            label = "حرج"
        
        comparisons.append(PeerComparison(
            hospital_id=hosp_id,
            hospital_name=data["hospital_name"],
            percentile=percentile,
            rank=rank,
            total_hospitals=total,
            comparison_label=label
        ))
    
    return comparisons


def generate_comparison_chart(trends: List[TrendData], peer_comparisons: List[PeerComparison]) -> Dict[str, Any]:
    """تكوين الرسم البياني للمقارنة"""
    
    # إعداد بيانات الرسم البياني
    chart_data = {
        "type": "line",
        "data": {
            "labels": [],
            "datasets": []
        },
        "options": {
            "responsive": True,
            "plugins": {
                "title": {
                    "display": True,
                    "text": "مقارنة أداء المستشفيات عبر الأشهر"
                },
                "legend": {
                    "position": "bottom"
                }
            },
            "scales": {
                "y": {
                    "beginAtZero": True,
                    "title": {
                        "display": True,
                        "text": "إجمالي الحالات"
                    }
                },
                "x": {
                    "title": {
                        "display": True,
                        "text": "الشهر"
                    }
                }
            }
        }
    }
    
    # إضافة بيانات الاتجاهات
    if trends:
        # استخدام أشهر أول ترند كتسميات
        first_trend = trends[0]
        chart_data["data"]["labels"] = first_trend.months
        
        # إضافة ترند لكل مستشفى
        for trend in trends[:5]:  # أول 5 مستشفيات
            dataset = {
                "label": trend.hospital_name,
                "data": trend.values.get("total_cases", []),
                "borderColor": f"rgb({hash(trend.hospital_id) % 256}, {hash(trend.hospital_id + '1') % 256}, {hash(trend.hospital_id + '2') % 256})",
                "tension": 0.1
            }
            chart_data["data"]["datasets"].append(dataset)
    
    return chart_data
```

- [ ] **Step 2: تعديل __init__.py**

```python
# app/engine/comparative/__init__.py
from app.engine.comparative.report_generator import generate_comprehensive_report
from app.engine.comparative.advanced_comparison import perform_advanced_comparison

__all__ = ["generate_comprehensive_report", "perform_advanced_comparison"]
```

- [ ] **Step 3: إنشاء اختبار أساسي**

```python
# tests/test_comparative.py
import pytest
from app.engine.comparative import perform_advanced_comparison


def test_perform_advanced_comparison_returns_data(db_session):
    """اختبار أن المقارنة تُعيد بيانات"""
    result = perform_advanced_comparison(db_session, "2026-06")
    assert "month" in result
    assert "trends" in result
    assert "peer_comparisons" in result
    assert "predictions" in result
    assert "chart_config" in result
    assert result["month"] == "2026-06"
```

- [ ] **Step 4: تشغيل الاختبارات**

Run: `pytest tests/test_comparative.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/engine/comparative/ tests/test_comparative.py
git commit -m "feat: add advanced comparison engine"
```

---

### Task 2: إضافة API Endpoint للمقارنة المتقدمة

**Files:**
- Modify: `app/api/comparative.py`
- Test: `tests/test_comparative.py`

**Interfaces:**
- Consumes: `perform_advanced_comparison()` من `app/engine/comparative`
- Produces: `GET /comparative/advanced-comparison/{month}`

- [ ] **Step 1: إضافة Endpoint الجديد**

```python
# app/api/comparative.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.engine.comparative import generate_comprehensive_report, perform_advanced_comparison

router = APIRouter(prefix="/comparative", tags=["Comparative Analysis"])


@router.get("/comprehensive-report/{month}")
def get_comprehensive_report(month: str, db: Session = Depends(get_db)):
    """توليد تقرير ذكي شامل"""
    try:
        result = generate_comprehensive_report(db, month)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ في توليد التقرير: {str(e)}")


@router.get("/advanced-comparison/{month}")
def get_advanced_comparison(
    month: str,
    hospital_id: str = Query(None, description="معرف المستشفى (اختياري)"),
    comparison_type: str = Query("all", description="نوع المقارنة (all/governorate/type)"),
    db: Session = Depends(get_db)
):
    """مقارنة متقدمة للمستشفيات"""
    try:
        result = perform_advanced_comparison(db, month, hospital_id, comparison_type)
        return {
            "month": result.month,
            "comparison_data": {
                "trends": [{"hospital_id": t.hospital_id, "hospital_name": t.hospital_name, "months": t.months, "values": t.values} for t in result.trends],
                "peer_comparison": [{"hospital_id": p.hospital_id, "hospital_name": p.hospital_name, "percentile": p.percentile, "rank": p.rank, "total_hospitals": p.total_hospitals, "comparison_label": p.comparison_label} for p in result.peer_comparisons],
                "predictions": result.predictions
            },
            "chart_config": result.chart_config
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ في المقارنة: {str(e)}")
```

- [ ] **Step 2: إنشاء اختبار Endpoint**

```python
# tests/test_comparative.py
from fastapi.testclient import TestClient
from app.main import app


def test_advanced_comparison_endpoint(client):
    """اختبار endpoint المقارنة المتقدمة"""
    response = client.get("/comparative/advanced-comparison/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "month" in data
    assert "comparison_data" in data
    assert "chart_config" in data
```

- [ ] **Step 3: تشغيل الاختبارات**

Run: `pytest tests/test_comparative.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/api/comparative.py tests/test_comparative.py
git commit -m "feat: add advanced comparison API endpoint"
```

---

### Task 3: تحديث واجهة المستخدم

**Files:**
- Modify: `static/tabs/comparative.html`
- Modify: `static/js/comparative.js`

**Interfaces:**
- Consumes: `GET /comparative/advanced-comparison/{month}`
- Produces: واجهة مستخدم للمقارنة المتقدمة

- [ ] **Step 1: تعديل comparative.html**

```html
<!-- static/tabs/comparative.html -->
<div id="comparative-tab" class="tab-content" style="display:none;">
    <div class="container-fluid">
        <h2>التحليل المقارن المتقدم</h2>
        
        <!-- اختيار الشهر وطريقة المقارنة -->
        <div class="row mb-3">
            <div class="col-md-3">
                <label>الشهر:</label>
                <select id="comparative-month" class="form-control">
                </select>
            </div>
            <div class="col-md-3">
                <label>طريقة المقارنة:</label>
                <select id="comparison-type" class="form-control">
                    <option value="all">جميع المستشفيات</option>
                    <option value="governorate">نفس المحافظة</option>
                    <option value="type">نفس النوع</option>
                </select>
            </div>
            <div class="col-md-3">
                <label>المستشفى:</label>
                <select id="hospital-select" class="form-control">
                    <option value="">جميع المستشفيات</option>
                </select>
            </div>
            <div class="col-md-3">
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
        
        <!-- الرسم البياني للمقارنة -->
        <div id="comparison-chart-container" class="card mt-4" style="display:none;">
            <div class="card-body">
                <h5>مقارنة أداء المستشفيات عبر الأشهر</h5>
                <canvas id="comparison-chart"></canvas>
            </div>
        </div>
        
        <!-- جدول مقارنة الأقران -->
        <div id="peer-comparison-container" class="card mt-4" style="display:none;">
            <div class="card-body">
                <h5>مقارنة المستشفيات ببعضها</h5>
                <table id="peer-comparison-table" class="table table-striped">
                    <thead>
                        <tr>
                            <th>الترتيب</th>
                            <th>المستشفى</th>
                            <th>النسبة المئوية</th>
                            <th>التقييم</th>
                        </tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>
        </div>
    </div>
</div>
```

- [ ] **Step 2: تعديل comparative.js**

```javascript
// static/js/comparative.js

let comparativeCurrentMonth = null;
let comparisonChart = null;

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
    
    // تحميل قائمة المستشفيات
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
    
    // زر التوليد
    document.getElementById('comparative-generate').addEventListener('click', () => {
        generateComprehensiveReport(monthSelect.value);
        generateAdvancedComparison(monthSelect.value, hospitalSelect.value, document.getElementById('comparison-type').value);
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

async function generateAdvancedComparison(month, hospitalId, comparisonType) {
    document.getElementById('comparative-loading').style.display = 'block';
    document.getElementById('comparison-chart-container').style.display = 'none';
    document.getElementById('peer-comparison-container').style.display = 'none';
    
    try {
        let url = `/comparative/advanced-comparison/${month}`;
        const params = new URLSearchParams();
        if (hospitalId) params.append('hospital_id', hospitalId);
        if (comparisonType) params.append('comparison_type', comparisonType);
        if (params.toString()) url += '?' + params.toString();
        
        const result = await apiComparativeGet(url);
        
        // عرض الرسم البياني
        if (result.chart_config && result.chart_config.data && result.chart_config.data.labels.length > 0) {
            renderComparisonChart(result.chart_config);
            document.getElementById('comparison-chart-container').style.display = 'block';
        }
        
        // عرض جدول مقارنة الأقران
        if (result.comparison_data && result.comparison_data.peer_comparison && result.comparison_data.peer_comparison.length > 0) {
            renderPeerComparisonTable(result.comparison_data.peer_comparison);
            document.getElementById('peer-comparison-container').style.display = 'block';
        }
    } catch (e) {
        console.error('خطأ في المقارنة:', e);
    } finally {
        document.getElementById('comparative-loading').style.display = 'none';
    }
}

function renderComparisonChart(chartConfig) {
    const ctx = document.getElementById('comparison-chart').getContext('2d');
    
    if (comparisonChart) {
        comparisonChart.destroy();
    }
    
    comparisonChart = new Chart(ctx, {
        type: 'line',
        data: chartConfig.data,
        options: chartConfig.options
    });
}

function renderPeerComparisonTable(peerComparison) {
    const tbody = document.querySelector('#peer-comparison-table tbody');
    tbody.innerHTML = '';
    
    peerComparison.forEach(peer => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${peer.rank}</td>
            <td>${peer.hospital_name}</td>
            <td>${peer.percentile.toFixed(1)}%</td>
            <td>${peer.comparison_label}</td>
        `;
        tbody.appendChild(row);
    });
}
```

- [ ] **Step 3: إضافة Chart.js إلى الصفحة الرئيسية**

```html
<!-- في static/index.html، أضف Chart.js -->
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
```

- [ ] **Step 4: Commit**

```bash
git add static/tabs/comparative.html static/js/comparative.js static/index.html
git commit -m "feat: update UI for advanced comparison"
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


def test_advanced_comparison_returns_data(client):
    """اختبار أن المقارنة تُعيد بيانات"""
    response = client.get("/comparative/advanced-comparison/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "month" in data
    assert "comparison_data" in data
    assert "chart_config" in data


def test_advanced_comparison_includes_trends(client):
    """اختبار أن المقارنة تتضمن الاتجاهات"""
    response = client.get("/comparative/advanced-comparison/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "trends" in data["comparison_data"]


def test_advanced_comparison_includes_predictions(client):
    """اختبار أن المقارنة تتضمن التنبؤات"""
    response = client.get("/comparative/advanced-comparison/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "predictions" in data["comparison_data"]


def test_advanced_comparison_chart_config(client):
    """اختبار تكوين الرسم البياني"""
    response = client.get("/comparative/advanced-comparison/2026-06")
    assert response.status_code == 200
    data = response.json()
    assert "chart_config" in data
    assert "type" in data["chart_config"]
    assert "data" in data["chart_config"]
    assert "options" in data["chart_config"]


def test_advanced_comparison_with_hospital_id(client):
    """اختبار المقارنة مع معرف مستشفى محدد"""
    response = client.get("/comparative/advanced-comparison/2026-06?hospital_id=1")
    assert response.status_code == 200
    data = response.json()
    assert "month" in data


def test_advanced_comparison_with_comparison_type(client):
    """اختبار المقارنة مع نوع مقارنة محدد"""
    response = client.get("/comparative/advanced-comparison/2026-06?comparison_type=governorate")
    assert response.status_code == 200
    data = response.json()
    assert "month" in data
```

- [ ] **Step 2: تشغيل الاختبارات**

Run: `pytest tests/test_comparative.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_comparative.py
git commit -m "test: add advanced comparison tests"
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

Run: `python -c "import time; start=time.time(); from app.engine.comparative import perform_advanced_comparison; print(f'Load time: {time.time()-start:.2f}s')"`
Expected: < 30 ثانية

- [ ] **Step 3: Commit النهائي**

```bash
git add .
git commit -m "feat: complete advanced comparative analysis"
```
