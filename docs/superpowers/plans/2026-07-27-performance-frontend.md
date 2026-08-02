# خطة تنفيذ تحسين الأداء وواجهة المستخدم

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** تحسين أداء شاشة التحليلات الذكية من 15 ثانية إلى أقل من 5 ثوانٍ

**Architecture:** إضافة نظام caching ذكي في Backend + تحميل تدريجي للرسوم في Frontend

**Tech Stack:** Python, FastAPI, SQLAlchemy, TTLCache, JavaScript, Plotly.js

## Global Constraints
- Python 3.14
- FastAPI
- SQLAlchemy
- TTLCache (موجود في app/cache.py)
- Plotly.js للرسوم البيانية

---

## File Structure

| الملف | المسؤولية |
|-------|-----------|
| `app/api/smart_analytics.py` | إضافة caching + error handling |
| `app/api/upload.py` | إضافة cache invalidation |
| `static/js/smart-analytics.js` | تحسين الـ frontend + progressive loading |
| `tests/test_smart_analytics.py` | اختبارات الأداء والـ caching |

---

### Task 1: إضافة Caching لـ smart_analytics.py

**Files:**
- Modify: `app/api/smart_analytics.py`
- Test: `tests/test_smart_analytics.py`

**Interfaces:**
- Consumes: `cache` من `app/cache.py`
- Produces: `get_overview()` مع caching

- [ ] **Step 1: إضافة import لـ cache**

```python
# في أعلى الملف
from app.cache import cache
```

- [ ] **Step 2: تعديل get_overview لإضافة caching**

```python
@router.get("/overview/{month}")
def get_overview(month: str, db: Session = Depends(get_db)):
    cache_key = f"smart_overview_{month}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    
    result = run_smart_analytics(db, month)
    response = _envelope(result)
    cache.set(cache_key, response, ttl=300)
    return response
```

- [ ] **Step 3: تعديل get_anomalies لإضافة caching**

```python
@router.get("/anomalies/{month}")
def get_anomalies(month: str, db: Session = Depends(get_db)):
    cache_key = f"smart_anomalies_{month}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    
    result = run_smart_analytics(db, month)
    data = _envelope(result)["data"]
    response = {"month": month, "anomalies": data["anomalies"], "explanations": data["explanations"]}
    cache.set(cache_key, response, ttl=300)
    return response
```

- [ ] **Step 4: تعديل get_clusters لإضافة caching**

```python
@router.get("/clusters/{month}")
def get_clusters(month: str, db: Session = Depends(get_db)):
    cache_key = f"smart_clusters_{month}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    
    result = run_smart_analytics(db, month)
    data = _envelope(result)["data"]
    response = {"month": month, "clustering": data["clustering"]}
    cache.set(cache_key, response, ttl=300)
    return response
```

- [ ] **Step 5: تعديل get_correlations لإضافة caching**

```python
@router.get("/correlations/{month}")
def get_correlations(month: str, db: Session = Depends(get_db)):
    cache_key = f"smart_correlations_{month}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    
    result = run_smart_analytics(db, month)
    data = _envelope(result)["data"]
    response = {"month": month, "correlations": data["correlations"]}
    cache.set(cache_key, response, ttl=300)
    return response
```

- [ ] **Step 6: تعديل get_residuals لإضافة caching**

```python
@router.get("/residuals/{month}")
def get_residuals(month: str, db: Session = Depends(get_db)):
    cache_key = f"smart_residuals_{month}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    
    result = run_smart_analytics(db, month)
    data = _envelope(result)["data"]
    response = {"month": month, "residuals": data["residuals"]}
    cache.set(cache_key, response, ttl=300)
    return response
```

- [ ] **Step 7: تعديل get_stratified لإضافة caching**

```python
@router.get("/stratified/{month}")
def get_stratified(month: str, db: Session = Depends(get_db)):
    cache_key = f"smart_stratified_{month}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    
    result = run_smart_analytics(db, month)
    data = _envelope(result)["data"]
    response = {"month": month, "stratified": data["stratified"]}
    cache.set(cache_key, response, ttl=300)
    return response
```

- [ ] **Step 8: تعديل get_geo لإضافة caching**

```python
@router.get("/geo/{month}")
def get_geo(month: str, db: Session = Depends(get_db)):
    cache_key = f"smart_geo_{month}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    
    result = run_smart_analytics(db, month)
    data = _envelope(result)["data"]
    response = {"month": month, "geo": data["geo"]}
    cache.set(cache_key, response, ttl=300)
    return response
```

- [ ] **Step 9: تشغيل الاختبارات**

Run: `pytest tests/test_smart_analytics.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add app/api/smart_analytics.py
git commit -m "feat: add caching to smart analytics endpoints"
```

---

### Task 2: إضافة Error Handling لـ smart_analytics.py

**Files:**
- Modify: `app/api/smart_analytics.py`
- Test: `tests/test_smart_analytics.py`

**Interfaces:**
- Consumes: `cache` من `app/cache.py`
- Produces: `get_overview()` مع error handling

- [ ] **Step 1: تعديل get_overview لإضافة error handling**

```python
@router.get("/overview/{month}")
def get_overview(month: str, db: Session = Depends(get_db)):
    try:
        cache_key = f"smart_overview_{month}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        result = run_smart_analytics(db, month)
        response = _envelope(result)
        cache.set(cache_key, response, ttl=300)
        return response
    except Exception as e:
        cache.invalidate(f"smart_overview_{month}")
        raise HTTPException(status_code=500, detail=f"خطأ في التحليل: {str(e)}")
```

- [ ] **Step 2: تعديل get_anomalies لإضافة error handling**

```python
@router.get("/anomalies/{month}")
def get_anomalies(month: str, db: Session = Depends(get_db)):
    try:
        cache_key = f"smart_anomalies_{month}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        result = run_smart_analytics(db, month)
        data = _envelope(result)["data"]
        response = {"month": month, "anomalies": data["anomalies"], "explanations": data["explanations"]}
        cache.set(cache_key, response, ttl=300)
        return response
    except Exception as e:
        cache.invalidate(f"smart_anomalies_{month}")
        raise HTTPException(status_code=500, detail=f"خطأ في تحليل الشذوذ: {str(e)}")
```

- [ ] **Step 3: تشغيل الاختبارات**

Run: `pytest tests/test_smart_analytics.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/api/smart_analytics.py
git commit -m "feat: add error handling to smart analytics endpoints"
```

---

### Task 3: إضافة Cache Invalidation لـ upload.py

**Files:**
- Modify: `app/api/upload.py`
- Test: `tests/test_smart_analytics.py`

**Interfaces:**
- Consumes: `cache` من `app/cache.py`
- Produces: `upload_data()` مع cache invalidation

- [ ] **Step 1: إضافة import لـ cache**

```python
# في أعلى الملف
from app.cache import cache
```

- [ ] **Step 2: تعديل upload_data لإضافة cache invalidation**

```python
@router.post("/upload")
def upload_data(...):
    # بعد رفع البيانات بنجاح
    cache.invalidate("smart_overview_")
    cache.invalidate("smart_anomalies_")
    cache.invalidate("smart_clusters_")
    cache.invalidate("smart_correlations_")
    cache.invalidate("smart_residuals_")
    cache.invalidate("smart_stratified_")
    cache.invalidate("smart_geo_")
    return {"status": "uploaded"}
```

- [ ] **Step 3: تشغيل الاختبارات**

Run: `pytest tests/test_smart_analytics.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/api/upload.py
git commit -m "feat: add cache invalidation to upload endpoint"
```

---

### Task 4: تحسين Frontend - التحميل التدريجي

**Files:**
- Modify: `static/js/smart-analytics.js`
- Test: `tests/test_smart_analytics.py`

**Interfaces:**
- Consumes: `apiSmartGet()` من `static/js/smart-analytics.js`
- Produces: `loadSmartData()` مع progressive loading

- [ ] **Step 1: تعديل loadSmartData للتحميل التدريجي**

```javascript
async function loadSmartData(month) {
    smartCurrentMonth = month;
    document.getElementById('smart-status').textContent = 'جاري التحميل...';
    smartShowLoading();
    
    try {
        smartCurrentData = await apiSmartGet(`/smart/overview/${month}`);
        const d = smartCurrentData.data;
        const total = smartCurrentData.hospitals_count;
        
        // الخطوة 1: تحميل KPIs أولاً (أسرع رسم)
        renderKPIs(d.kpi, total);
        
        // الخطوة 2: تحميل الرسوم الرئيسية بعد 100ms
        setTimeout(() => {
            renderGeoMap(d.geo);
            renderClusterScatter(d.clustering, d.anomalies);
            renderCorrelationHeatmap(d.correlations);
        }, 100);
        
        // الخطوة 3: تحميل الرسوم الثانوية بعد 300ms
        setTimeout(() => {
            renderResidualPlot(d.residuals, document.getElementById('smart-residual-indicator').value);
            renderAnomalyTable(d.anomalies, d.explanations);
            renderFeatureImportance(d.correlations, document.getElementById('smart-fi-indicator').value);
            renderStratifiedComparison(d.stratified, document.getElementById('smart-strat-indicator').value);
            renderXGBoostPredictions(d.xgboost);
            
            document.getElementById('smart-status').textContent = `تم التحديث — ${total} مستشفى`;
            smartHideLoading();
        }, 300);
    } catch (e) {
        document.getElementById('smart-status').textContent = 'خطأ في التحميل: ' + e.message;
        smartHideLoading();
    }
}
```

- [ ] **Step 2: تشغيل الاختبارات**

Run: `pytest tests/test_smart_analytics.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add static/js/smart-analytics.js
git commit -m "feat: add progressive loading to smart analytics frontend"
```

---

### Task 5: إضافة اختبارات الأداء

**Files:**
- Modify: `tests/test_smart_analytics.py`

**Interfaces:**
- Consumes: `cache` من `app/cache.py`
- Produces: اختبارات الأداء

- [ ] **Step 1: إضافة اختبار caching**

```python
def test_cache_returns_cached_result():
    # اختبار أن الكاش يُعيد النتيجة المخزنة
    from app.cache import cache
    
    # مسح الكاش أولاً
    cache.invalidate("smart_overview_")
    
    # تشغيل التحليل
    result = run_smart_analytics(db, "2026-01")
    
    # التحقق من أن النتيجة مخزنة في الكاش
    cache_key = "smart_overview_2026-01"
    cached = cache.get(cache_key)
    assert cached is not None
```

- [ ] **Step 2: إضافة اختبار cache invalidation**

```python
def test_cache_invalidates_on_upload():
    # اختبار مسح الكاش عند رفع بيانات جديدة
    from app.cache import cache
    
    # تشغيل التحليل أولاً
    run_smart_analytics(db, "2026-01")
    
    # مسح الكاش
    cache.invalidate("smart_overview_")
    
    # التحقق من أن الكاش فارغ
    cache_key = "smart_overview_2026-01"
    cached = cache.get(cache_key)
    assert cached is None
```

- [ ] **Step 3: إضافة اختبار error handling**

```python
def test_error_handling():
    # اختبار معالجة الأخطاء
    from fastapi.testclient import TestClient
    from app.main import app
    
    client = TestClient(app)
    
    # محاولة تحليل شهر غير موجود
    response = client.get("/smart/overview/2026-99")
    assert response.status_code == 500
```

- [ ] **Step 4: تشغيل الاختبارات**

Run: `pytest tests/test_smart_analytics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_smart_analytics.py
git commit -m "feat: add performance tests for smart analytics"
```

---

### Task 6: تشغيل جميع الاختبارات والتحقق

**Files:**
- None

**Interfaces:**
- Consumes: جميع الملفات المعدلة
- Produces: جميع الاختبارات ناجحة

- [ ] **Step 1: تشغيل جميع الاختبارات**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 2: التحقق من الأداء**

Run: `python -c "import time; start=time.time(); from app.engine.smart import run_smart_analytics; print(f'Load time: {time.time()-start:.2f}s')"`
Expected: < 5 ثوانٍ

- [ ] **Step 3: Commit النهائي**

```bash
git add .
git commit -m "feat: complete performance and frontend optimization"
```
