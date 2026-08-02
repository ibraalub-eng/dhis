# التقرير الذكي الشامل - التحليلات المقارنة المتقدمة

## التاريخ: 2026-07-27

## المشكلة
- لا يوجد تقرير شامل يجمع بين جميع تحليلات النظام
- لا توجد توصيات إجرائية بالعربية
- صعوبة فهم النتائج للمستخدمين غير المتخصصين

## الحل المقترح
إنشاء تقرير ذكي شامل يتضمن جميع تحليلات النظام مع توصيات إجرائية بالعربية باستخدام Google Gemini API

## المكونات

### 1. محرك التقرير الشامل
```python
# الملفات الجديدة:
app/engine/comparative/__init__.py
app/engine/comparative/report_generator.py
```

**المسؤوليات:**
- جمع جميع بيانات التحليلات من `run_smart_analytics()`
- بناء Prompt شامل يتضمن جميع التحليلات
- استدعاء Google Gemini API
- معالجة الاستجابة وإرجاع التقرير

### 2. API Endpoint
```python
# الملف الجديد:
app/api/comparative.py

# Endpoint:
GET /comparative/comprehensive-report/{month}
```

**المعلمات:**
- `month`: الشهر المطلوب (YYYY-MM)

**الاستجابة:**
```json
{
    "month": "2026-01",
    "report": "التقرير النصي بالعربية",
    "data": {
        "kpi": {...},
        "anomalies": [...],
        "clustering": {...},
        "correlations": {...},
        "residuals": [...],
        "stratified": [...],
        "explanations": [...],
        "geo": {...},
        "xgboost": {...}
    }
}
```

### 3. واجهة المستخدم
```html
<!-- الملف الجديد: static/tabs/comparative.html -->
```

**المكونات:**
- اختيار الشهر
- زر "توليد التقرير الذكي"
- منطقة عرض التقرير
- شريط تحميل أثناء التوليد

## هيكل التقرير

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
11. **التوصيات الإجرائية** - ماذا يجب فعله

## معايير النجاح
- التقرير يتضمن جميع التحليلات المذكورة أعلاه
- التقرير بالعربية الفصحى
- التوصيات إجرائية وواضحة
- وقت التوليد < 30 ثانية
- معالجة أخطاء ذكية

## معالجة الأخطاء
```python
@router.get("/comprehensive-report/{month}")
def get_comprehensive_report(month: str, db: Session = Depends(get_db)):
    try:
        # 1. جمع جميع البيانات
        analytics = run_smart_analytics(db, month)
        
        # 2. بناء الـ Prompt
        prompt = build_comprehensive_prompt(analytics, {})
        
        # 3. استدعاء Google Gemini
        report_text = call_gemini_api(prompt)
        
        if not report_text:
            raise HTTPException(status_code=503, detail="Gemini API غير متاح")
        
        # 4. إرجاع التقرير
        return {
            "month": month,
            "report": report_text,
            "data": analytics
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ في توليد التقرير: {str(e)}")
```

## الاختبارات المطلوبة
```python
def test_comprehensive_report_returns_data():
    """اختبار أن التقرير يُعيد بيانات"""
    pass

def test_comprehensive_report_in_arabic():
    """اختبار أن التقرير بالعربية"""
    pass

def test_comprehensive_report_includes_all_sections():
    """اختبار أن التقرير يتضمن جميع الأقسام"""
    pass
```

## الملفات المعدلة
1. `app/engine/comparative/__init__.py` - جديد
2. `app/engine/comparative/report_generator.py` - جديد
3. `app/api/comparative.py` - جديد
4. `static/tabs/comparative.html` - جديد
5. `static/js/comparative.js` - جديد
6. `tests/test_comparative.py` - جديد
