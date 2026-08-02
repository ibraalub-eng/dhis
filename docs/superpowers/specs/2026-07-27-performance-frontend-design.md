# تحسين الأداء وواجهة المستخدم - التحليلات الذكية

## التاريخ: 2026-07-27

## المشكلة
- شاشة التحليلات الذكية تستغرق 5-15 ثانية للتحميل
- أخطاء 500 و 422 تظهر أحياناً
- الرسوم البيانية تظهر ببطء

## الحلول المقترحة

### الحل 1: نظام Caching ذكي
- تخزين نتائج `run_smart_analytics()` في الذاكرة
- TTL = 5 دقائق
- Smart Invalidation عند رفع بيانات جديدة عبر `upload` endpoint
- مسح الكاش لكل городе عند رفع بيانات جديدة

### الحل 2: تحسين الواجهة الأمامية
- تحميل تدريجي للرسوم البيانية
- تحميل KPIs أولاً (أسرع رسم)
- تحميل الرسوم الرئيسية (Geo, Clustering, Correlation) بعد 100ms
- تحميل الرسوم الثانوية (Residual, Anomaly Table, Feature Importance, Stratified, XGBoost) بعد 300ms
- إظهار loading indicator أثناء التحميل

### الحل 3: معالجة أخطاء ذكية
- Try/Catch في جميع endpoints
- Cache invalidation عند الخطأ
- رسائل خطأ واضحة بالعربية
- logging للأخطاء في server

## المكونات

### Backend (Python/FastAPI)

#### 1. إضافة Caching لـ smart_analytics.py
```python
from app.cache import cache

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

#### 2. Cache Invalidation عند رفع بيانات جديدة
```python
# في upload endpoint
@router.post("/upload")
def upload_data(...):
    # بعد رفع البيانات بنجاح
    cache.invalidate("smart_overview_")
    return {"status": "uploaded"}
```

#### 3. Error Handling
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

### Frontend (JavaScript)

#### 1. التحميل التدريجي للرسوم
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

#### 2. إظهار/إخفاء Loading Indicator
```javascript
function smartShowLoading() {
    const el = document.getElementById('smart-loading-overlay');
    if (el) { el.style.display = 'flex'; }
}

function smartHideLoading() {
    const el = document.getElementById('smart-loading-overlay');
    if (el) { el.style.display = 'none'; }
}
```

## معايير النجاح
- وقت التحميل: < 5 ثوانٍ (بدون caching كان 15 ثانية)
- لا أخطاء 500 أو 422
- الرسوم البيانية تظهر تدريجياً
- KPIs تظهر فوراً (< 1 ثانية)

## الاختبارات المطلوبة

### Unit Tests
```python
def test_cache_returns_cached_result():
    # اختبار أن الكاش يُعيد النتيجة المخزنة
    pass

def test_cache_invalidates_on_upload():
    # اختبار مسح الكاش عند رفع بيانات جديدة
    pass

def test_error_handling():
    # اختبار معالجة الأخطاء
    pass
```

### Performance Tests
```python
def test_load_time_with_cache():
    # اختبار أن وقت التحميل < 5 ثوانٍ مع الكاش
    pass

def test_load_time_without_cache():
    # اختبار أن وقت التحميل < 15 ثانية بدون كاش
    pass
```

## الملفات المعدلة
1. `app/api/smart_analytics.py` - إضافة caching + error handling
2. `app/api/upload.py` - إضافة cache invalidation
3. `static/js/smart-analytics.js` - تحسين الـ frontend + progressive loading
4. `tests/test_smart_analytics.py` - اختبارات الأداء والـ caching
