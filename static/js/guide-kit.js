// ── Shared building blocks for the Data-section user guides ──────────────────
// Every screen guide is a plain object built from these helpers, so all six
// guides share one template (A–I) and one renderer. Bilingual text is always a
// {en, ar} pair; the renderer picks by the current UI language and falls back
// to English when a translation is missing.

export const t = (en, ar) => ({ en, ar });

export const p = (en, ar) => ({ type: 'p', text: t(en, ar) });

export const list = (...items) => ({
    type: 'list',
    items: items.map(([en, ar]) => t(en, ar)),
});

export const steps = (...items) => ({
    type: 'steps',
    items: items.map(([en, ar]) => t(en, ar)),
});

export const table = (headers, rows) => ({
    type: 'table',
    headers: headers.map(([en, ar]) => t(en, ar)),
    rows: rows.map(row => row.map(([en, ar]) => t(en, ar))),
});

// The nine sections every guide must carry, in order (the task's A–I).
export const SECTION_ORDER = [
    'overview', 'layout', 'usage', 'fields', 'actions',
    'results', 'examples', 'problems', 'related',
];

export const SECTION_TITLES = {
    overview: t('A. Screen overview', 'أ. نظرة عامة على الشاشة'),
    layout: t('B. Screen layout', 'ب. تخطيط الشاشة'),
    usage: t('C. How to use the screen', 'ج. طريقة استخدام الشاشة'),
    fields: t('D. Important fields', 'د. شرح الحقول المهمة'),
    actions: t('E. Actions and buttons', 'هـ. الأزرار والإجراءات'),
    results: t('F. Understanding results', 'و. فهم النتائج'),
    examples: t('G. Practical examples', 'ز. أمثلة عملية'),
    problems: t('H. Common problems', 'ح. المشكلات الشائعة'),
    related: t('I. Related screens', 'ط. الشاشات المرتبطة'),
};

export const GUIDE_META = {
    hubTitle: t('Data section user guides', 'أدلة مستخدم قسم البيانات'),
    hubSubtitle: t(
        'One guide per screen. Each guide explains the layout, the fields, every action, how to read the results, and what to check next.',
        'دليل مستقل لكل شاشة: يشرح التخطيط والحقول وكل إجراء وكيف تُقرأ النتائج وما الخطوة التالية.',
    ),
    backToIndex: t('All Data guides', 'كل أدلة البيانات'),
    previous: t('Previous', 'السابق'),
    next: t('Next', 'التالي'),
    openScreen: t('Open this screen', 'افتح هذه الشاشة'),
    backToData: t('Back to the Data section', 'العودة إلى قسم البيانات'),
    searchPlaceholder: t('Search a screen or a topic…', 'ابحث عن شاشة أو موضوع…'),
    searchHint: t(
        'Search matches the screen name, its purpose, and every heading and table inside its guide.',
        'يشمل البحث اسم الشاشة وغرضها وكل عنوان وجدول داخل دليلها.',
    ),
    noResults: t('No screen matches that search.', 'لا توجد شاشة تطابق هذا البحث.'),
    guideCount: t('documented screen(s)', 'شاشة موثّقة'),
    permission: t('Permission', 'الصلاحية'),
    menu: t('Menu location', 'موقع القائمة'),
    onThisPage: t('Inside this guide', 'داخل هذا الدليل'),
    screenshot: t('Screen as it appears in the system', 'الشاشة كما تظهر في النظام'),
    legend: t('Numbered reference', 'المرجع المرقّم'),
    screenshotsNote: t(
        'Screenshots are captured from the running system; numbers refer to the reference list below.',
        'الصور مأخوذة من النظام قيد التشغيل، والأرقام تشير إلى القائمة المرجعية أدناه.',
    ),
    screenshotMissing: t(
        'A screenshot for this screen is not available yet.',
        'لا تتوفر صورة لهذه الشاشة بعد.',
    ),
    verified: t(
        'This guide documents only features present in the application at the time of writing.',
        'يوثّق هذا الدليل الميزات الموجودة فعليًا في التطبيق وقت كتابته فقط.',
    ),
};

export const DATA_SECTION_NOTE = {
    en: 'Data section',
    ar: 'قسم البيانات',
};
