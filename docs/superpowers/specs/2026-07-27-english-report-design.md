# دعم اللغة الإنجليزية في التقرير الذكي الشامل

## التاريخ: 2026-07-27

## المشكلة
- التقرير الذكي الشامل يدعم العربية فقط
- لا يمكن للمستخدمين الناطقين بالإنجليزية استخدام التقرير

## الحل المقترح
إضافة دعم كامل للإنجليزية للتقرير الذكي الشامل (محتوى + واجهة)

## المكونات

### 1. تعديل محرك التقرير
```python
# app/engine/comparative/report_generator.py
def build_comprehensive_prompt(analytics, lang: str = "ar") -> str:
    if lang == "en":
        return _build_english_prompt(analytics)
    return _build_arabic_prompt(analytics)
```

### 2. تعديل API
```python
# app/api/comparative.py
@router.get("/comprehensive-report/{month}")
def get_comprehensive_report(month: str, lang: str = "ar", ...):
    result = generate_comprehensive_report(db, month, lang)
```

### 3. زر تبديل اللغة في الواجهة
```html
<button onclick="toggleReportLang()">🇸🇦 العربية / 🇬🇧 English</button>
```

## الملفات المعدلة
1. `app/engine/comparative/report_generator.py` - إضافة prompt إنجليزي
2. `app/api/comparative.py` - إضافة معامل lang
3. `static/tabs/comparative.html` - إضافة زر التبديل وعناوين ثنائية اللغة
4. `static/js/comparative.js` - إضافة منطق التبديل
5. `tests/test_comparative.py` - اختبارات للإنجليزية

## معايير النجاح
- التقرير يظهر بالإنجليزية عند اختيار English
- جميع أقسام التقرير (11 قسم) مترجمة
- عناوين الأقسام في الواجهة متغيرة حسب اللغة
- زر التبديل يعمل بدون إعادة تحميل الصفحة
- جميع الاختبارات ناجحة
