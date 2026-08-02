# التحليلات المقارنة المتقدمة - التصميم

## التاريخ: 2026-07-27

## المشكلة
- لا توجد مقارنة متقدمة للمستشفيات عبر الأشهر
- لا يوجد تنبؤ بالأداء المستقبلي
- صعوبة مقارنة أداء مستشفى بمستشفيات مشابهة

## الحل المقترح
تحسين التقرير الذكي الشامل بإضافة قسم المقارنة المتقدمة

## المكونات

### 1. محرك المقارنة المتقدمة
```python
# الملفات الجديدة:
app/engine/comparative/advanced_comparison.py
```

**المسؤوليات:**
- مقارنة المستشفيات عبر الأشهر (رسم بياني خطي)
- مقارنة المستشفيات ببعضها (حسب المحافظة أو النوع)
- استخدام XGBoost للتنبؤ بالأداء المستقبلي
- دعم جميع المؤشرات السريرية (10 مؤشرات)
- إعطاء المستخدم حرية اختيار طريقة المقارنة

### 2. API Endpoint
```python
# الملف المعدل:
app/api/comparative.py

# Endpoint الجديد:
GET /comparative/advanced-comparison/{month}
```

**المعلمات:**
- `month`: الشهر المطلوب (YYYY-MM)
- `hospital_id`: معرف المستشفى (اختياري)
- `comparison_type`: نوع المقارنة (all/governorate/type)

**الاستجابة:**
```json
{
    "month": "2026-01",
    "comparison_data": {
        "trends": [...],
        "peer_comparison": {...},
        "predictions": {...}
    },
    "chart_config": {
        "type": "line",
        "data": {...},
        "options": {...}
    }
}
```

### 3. واجهة المستخدم
```html
<!-- الملف المعدل: static/tabs/comparative.html -->
```

**المكونات الجديدة:**
- قائمة منسدلة لاختيار نوع المقارنة
- رسم بياني خطي لمقارنة المستشفيات عبر الأشهر
- جدول مقارنة بسيط
- شريط تحميل أثناء التوليد

## هيكل التقرير المحسّن

1. **الملخص التنفيذي** - حالة النظام العامة
2. **تحليل المؤشرات** - جميع المؤشرات السريرية
3. **تحليل الشذوذ** - المستشفيات غير الطبيعية
4. **التجميع** - تقسيم المستشفيات لمجموعات
5. **الارتباطات** - العلاقات بين المؤشرات
6. **البواقي** - الانحراف عن التوقعات
7. **المقارنة الطبقية** - مقارنة كل مستشفى بنظيره
8. **شرح SHAP** - العوامل المسؤولة عن الشذوذ
9. **الخريطة الجغرافية** - التوزيع الجغرافي
10. **التنبؤات** - توقعات XGBoost
11. **المقارنة المتقدمة** - جديد!
    - مقارنة عبر الأشهر
    - مقارنة بمستشفيات مشابهة
    - تنبؤات مستقبلية
12. **التوصيات الإجرائية** - ماذا يجب فعله

## معايير النجاح
- التقرير يتضمن قسم المقارنة المتقدمة
- الرسم البياني الخطي يعمل بشكل صحيح
- التنبؤات دقيقة
- المقارنة تدعم جميع المؤشرات
- المستخدم يختار طريقة المقارنة بحرية
- وقت التوليد < 30 ثانية
- معالجة أخطاء ذكية

## معالجة الأخطاء
```python
@router.get("/advanced-comparison/{month}")
def get_advanced_comparison(
    month: str,
    hospital_id: str = None,
    comparison_type: str = "all",
    db: Session = Depends(get_db)
):
    try:
        # 1. جمع البيانات التاريخية
        historical_data = get_historical_data(db, month, hospital_id)
        
        # 2. إجراء المقارنة
        comparison = perform_advanced_comparison(historical_data, comparison_type)
        
        # 3. التنبؤ بالأداء المستقبلي
        predictions = predict_future_performance(historical_data)
        
        # 4. إرجاع البيانات مع تكوين الرسم البياني
        return {
            "month": month,
            "comparison_data": {
                "trends": comparison.trends,
                "peer_comparison": comparison.peer_comparison,
                "predictions": predictions
            },
            "chart_config": generate_chart_config(comparison, predictions)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ في المقارنة: {str(e)}")
```

## الاختبارات المطلوبة
```python
def test_advanced_comparison_returns_data():
    """اختبار أن المقارنة تُعيد بيانات"""
    pass

def test_advanced_comparison_includes_trends():
    """اختبار أن المقارنة تتضمن الاتجاهات"""
    pass

def test_advanced_comparison_includes_predictions():
    """اختبار أن المقارنة تتضمن التنبؤات"""
    pass

def test_advanced_comparison_chart_config():
    """اختبار تكوين الرسم البياني"""
    pass
```

## الملفات المعدلة
1. `app/engine/comparative/advanced_comparison.py` - جديد
2. `app/engine/comparative/__init__.py` - تعديل
3. `app/api/comparative.py` - تعديل
4. `static/tabs/comparative.html` - تعديل
5. `static/js/comparative.js` - تعديل
6. `tests/test_comparative.py` - تعديل
