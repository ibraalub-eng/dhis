# تخزين التقرير الذكي الشامل (مرة واحدة شهرياً)

## التاريخ: 2026-08-01

## المشكلة
- التقرير الذكي الشامل يتم توليده من الذكاء الاصطناعي عند كل طلب دون أي تخزين
- استهلاك كوتة Gemini (المجانية) يتم بسرعة بسبب إعادة التوليد المتكررة (429 RESOURCE_EXHAUSTED)
- المستخدم يفتح التقرير مرة واحدة في الشهر (البيانات شهرية) — يجب توليده مرة واحدة وتخزينه وإعادة استخدامه

## الحل المقترح
تخزين التقرير في قاعدة البيانات (جدول `analysis_cache` الموجود) بمفتاح `comparative_report:{month}:{lang}`. عند الطلب: فحص التخزين أولاً → إذا وُجد نعيده فوراً (بدون تحليلات وبدون استدعاء AI) → إذا لم يوجد نولّده. يتم حذف السجل المخزن عند تغيير البيانات عبر الرفع.

**يتم تخزين التقارير المولّدة بالذكاء الاصطناعي فقط.** التقرير المحلي (fallback عند فشل AI) يُعرض ولا يُخزَّن — فيُعاد تجربة AI في الطلب التالي تلقائياً بعد استعادة الكوتة.

## المكونات

### 1. وحدة جديدة `app/engine/comparative/report_cache.py`
```python
REPORT_CACHE_PREFIX = "comparative_report:"

def get_stored_report(session, month: str, lang: str) -> dict | None:
    # يقرأ من جدول analysis_cache بمفتاح comparative_report:{month}:{lang}

def store_report(session, month: str, lang: str, result: dict) -> None:
    # يحفظ result JSON في جدول analysis_cache (بدون expires_at = دائم)
    # يُستخدم json.dumps(result, default=str) لمعالجة أنواع numpy غير القابلة للـ JSON

def invalidate_report_cache(session, month: str | None = None) -> None:
    # يحذف صفوف شهر محدد أو كل الصفوف إذا كان month = None
```
- يستخدم نموذج `AnalysisCache` الموجود (لا هجرة قاعدة بيانات)
- `expires_at` يُترك NULL (لا انتهاء صلاحية) — الحذف يتم عبر الرفع

### 2. تعديل `app/engine/comparative/report_generator.py`
```python
def generate_comprehensive_report(session, month: str, lang: str = "ar", use_cache: bool = True) -> dict:
    if use_cache:
        cached = get_stored_report(session, month, lang)
        if cached:
            return cached
    analytics = run_smart_analytics(session, month)
    prompt = build_comprehensive_prompt(analytics, lang)
    report_text = None
    try:
        report_text = _call_api(prompt)
    except Exception:
        logger.error("...", exc_info=True)
    if report_text:
        result = {..., "report_source": "ai", ...}
        store_report(session, month, lang, result)
        return result
    result = {..., "report_source": "local", ...}  # fallback محلي
    return result  # لا يُخزَّن
```

### 3. تعديل `app/api/comparative.py`
```python
@router.get("/comprehensive-report/{month}")
def get_comprehensive_report(
    month: str,
    lang: str = Query("ar"),
    force: bool = Query(False, description="إعادة توليد التقرير وتجاوز التخزين"),
    db: Session = Depends(get_db),
):
    result = generate_comprehensive_report(db, month, lang, use_cache=not force)
```

### 4. تعديل `app/api/upload.py` (إبطال التخزين عند تغيير البيانات)
- `save_manual_entry`: بعد الحفظ → `invalidate_report_cache(db, month)` (الشهر المتأثر فقط)
- `/upload/` (رفع Excel): بعد المعالجة → `invalidate_report_cache(db)` (كل الأشهر)
- `/upload/analyze`: بعد المعالجة → `invalidate_report_cache(db)` (كل الأشهر)

## تدفق البيانات
```
طلب → use_cache? 
  → إصابة التخزين: إرجاع التقرير المخزن (فوري)
  → عدم وجود: تحليلات → AI 
      → نجاح AI: تخزين + إرجاع (report_source=ai)
      → فشل AI: fallback محلي إرجاع فقط (report_source=local)
```

## معالجة الحالات الطرفية
- طلبان متزامنان أوليان لنفس الشهر → كلاهما يولّد (نادر وغير ضار، أحدهما يخزن)
- الاستجابة المخزنة تتضمن كامل `data` (لقطة التحليلات) — فتكون الإصابات فورية
- إبطال التخزين عند الرفع يغطي مسارات الرفع الثلاثة

## الاختبارات
- إصابة التخزين: AI يُستدعى مرة واحدة عبر استدعائين لنفس الشهر/اللغة
- فصل اللغة: تخزين ar و en بشكل منفصل
- عدم تخزين الـ fallback المحلي: عند فشل AI يُعاد الاستدعاء في الطلب التالي
- الإبطال: بعد `save_manual_entry` يُمسح التخزين ويُعاد التوليد
- معامل `force`: يتجاوز التخزين ويولّد من جديد
- جميع الاختبارات الحالية (76) تبقى ناجحة (قاعدة بيانات معزولة لكل اختبار)

## الملفات
1. `app/engine/comparative/report_cache.py` — جديد (دوال get/store/invalidate)
2. `app/engine/comparative/report_generator.py` — دمج التخزين
3. `app/api/comparative.py` — معامل force
4. `app/api/upload.py` — إبطال التخزين عند الرفع
5. `tests/test_comparative.py` — اختبارات التخزين

## معايير النجاح
- أول طلب لشهر يولّد التقرير ويخزنه، والطلبات التالية تعود من التخزين دون استدعاء AI
- عدد استدعاءات AI = مرة واحدة شهرياً لكل (شهر، لغة) ضمن الكوتة
- عند رفع بيانات جديدة يُعاد توليد تقرير الشهر المتأثر
- التقرير المحلي عند فشل AI لا يُخزَّن ويُعاد تجربة AI لاحقاً
- جميع الاختبارات ناجحة
