// ── Guide: Indicators ────────────────────────────────────────────────────────
import { p, list, steps, table } from '../guide-kit.js';

export default {
    key: 'indicators',
    tab: 'indicators',
    icon: '📐',
    title: { en: 'Indicators', ar: 'المؤشرات' },
    menu: { en: 'Data › Indicators', ar: 'البيانات › المؤشرات' },
    permission: 'settings.read',
    shot: 'indicators.png',
    shotAlt: {
        en: 'Indicators catalog with search and filters, the table, and the detail drawer',
        ar: 'كتالوج المؤشرات مع البحث والتصفية والجدول ولوحة التفاصيل',
    },
    shotLegend: [
        { en: 'Recompute latest and New Indicator', ar: 'إعادة حساب الأحدث ومؤشر جديد' },
        { en: 'Search and the category / type / status filters', ar: 'البحث ومرشّحات الفئة والنوع والحالة' },
        { en: 'Catalog table with formula and per-row actions', ar: 'جدول الكتالوج مع المعادلة وإجراءات لكل صف' },
        { en: 'Detail drawer: definition and preview', ar: 'لوحة التفاصيل: التعريف والمعاينة' },
        { en: 'Stored results and version history', ar: 'النتائج المخزّنة وسجل الإصدارات' },
        { en: 'Indicator builder modal', ar: 'نافذة إنشاء المؤشر' },
    ],
    nextSteps: [
        {
            tab: 'direction-coverage',
            label: { en: 'Fill missing directions', ar: 'أكمل الاتجاهات الناقصة' },
            why: {
                en: 'An indicator without a clinical direction cannot be interpreted in Quality Alerts.',
                ar: 'المؤشر بلا اتجاه سريري لا يمكن تفسيره في تنبيهات الجودة.',
            },
        },
        {
            tab: 'quality-completeness',
            label: { en: 'See the score effect', ar: 'شاهد أثر الدرجة' },
            why: {
                en: 'Derived indicators feed the quality components and the completeness denominator.',
                ar: 'تُغذي المؤشرات المشتقة مكوّنات الجودة ومقام الاكتمال.',
            },
        },
    ],
    sections: {
        overview: [
            p(
                'The Indicators screen is the catalog of everything the analysis can read: raw data elements coming from uploaded files, and derived indicators computed from them with a stored formula. It is where a new derived indicator is created and where an existing definition, its stored results and its version history are inspected.',
                'شاشة المؤشرات هي كتالوج كل ما يمكن للتحليل قراءته: عناصر البيانات الأولية القادمة من الملفات المرفوعة، والمؤشرات المشتقة المحسوبة منها بمعادلة مخزّنة. وهي مكان إنشاء مؤشر مشتق جديد وفحص تعريف قائم ونتائجه المخزّنة وسجل إصداراته.',
            ),
            list(
                ['Why it exists: SRMNH rates (for example caesarean rate) are ratios of reported counts, and the system must compute them consistently instead of trusting a spreadsheet formula.', 'لماذا وُجدت: معدلات SRMNH (كالقصرية مثلًا) نسب بين أعداد مبلَّغ عنها، ويجب أن يحسبها النظام باتساق بدل الاعتماد على معادلة في الجدول.'],
                ['Who uses it: administrators and analysts with settings.read; creating, editing, deleting and recomputing need settings.write.', 'من يستخدمها: المديرون والمحللون بصلاحية settings.read، أما الإنشاء والتعديل والحذف وإعادة الحساب فتحتاج settings.write.'],
                ['When: when a new rate is needed, when a definition must be corrected, or when a questionable value has to be traced back to its formula and data.', 'متى: عند الحاجة إلى معدل جديد، أو تصحيح تعريف، أو تتبّع قيمة مشكوك فيها إلى معادلتها وبياناتها.'],
            ),
        ],
        layout: [
            table(
                [['Area', 'المنطقة'], ['What it contains', 'ما تحتويه']],
                [
                    [['Header', 'الترويسة'], ['Recompute latest (settings.write) and New Indicator (settings.write).', 'إعادة حساب الأحدث (settings.write) ومؤشر جديد (settings.write).']],
                    [['Toolbar', 'شريط الأدوات'], ['Search across name, id, category and formula; category, type and status filters; a visible-count label.', 'بحث في الاسم والمعرّف والفئة والمعادلة، ومرشّحات الفئة والنوع والحالة، وعدّاد للعناصر الظاهرة.']],
                    [['Table', 'الجدول'], ['One row per indicator: status, name, category, type, unit, formula, actions.', 'صف لكل مؤشر: الحالة والاسم والفئة والنوع والوحدة والمعادلة والإجراءات.']],
                    [['Detail drawer', 'لوحة التفاصيل'], ['Definition, preview against real data, data references, stored results and version history.', 'التعريف، ومعاينة على بيانات حقيقية، ومراجع البيانات، والنتائج المخزّنة، وسجل الإصدارات.']],
                    [['Builder modal', 'نافذة الإنشاء'], ['Name, result type, multiplier, unit, numerator/denominator or expression, benchmark directions and validation messages.', 'الاسم ونوع النتيجة والمعامل والوحدة والبسط والمقام أو المعادلة واتجاهات المرجع ورسائل التحقق.']],
                ],
            ),
        ],
        usage: [
            steps(
                ['Open Data › Indicators. The catalog loads with every category.', 'افتح البيانات › المؤشرات ليُحمَّل الكتالوج بكل الفئات.'],
                ['Filter by name or id, or by category, type and active status. The count label shows how many rows match.', 'صفِّ حسب الاسم أو المعرّف أو الفئة أو النوع أو حالة التفعيل، ويظهر عدّاد الصفوف المطابقة.'],
                ['Click a row to open the drawer: the definition and its formula, then preview it against a chosen hospital and month.', 'انقر صفًا لتفتح اللوحة: التعريف والمعادلة، ثم عاينه على مستشفى وشهر مختارين.'],
                ['For a managed indicator, the drawer also lists its data references, stored monthly results and version history.', 'للمؤشر المُدار تعرض اللوحة أيضًا مراجع بياناته ونتائجه الشهرية المخزّنة وسجل إصداراته.'],
                ['To add one, press New Indicator, name it, choose the result type, then drag data elements into Numerator and Denominator (or switch to Expression and write {code} arithmetic).', 'لإضافة مؤشر اضغط «مؤشر جديد» وسمّه واختر نوع النتيجة ثم اسحب عناصر البيانات إلى البسط والمقام (أو اختر «معادلة» واكتب حسابًا بأكواد {code}).'],
                ['Press Validate to check the draft, then Save. The new indicator appears in the catalog and is computed from the stored values.', 'اضغط «تحقق» لفحص المسودة ثم «حفظ». يظهر المؤشر الجديد في الكتالوج ويُحسب من القيم المخزّنة.'],
                ['After changing a definition, press Recompute latest to refresh the newest data month, and follow the instruction to re-analyse older months if needed.', 'بعد تغيير تعريف اضغط «إعادة حساب الأحدث» لتحديث أحدث شهر، واتبع الإرشاد لإعادة تحليل الشهور الأقدم إن لزم.'],
            ),
        ],
        fields: [
            table(
                [['Field', 'الحقل'], ['Meaning', 'المعنى'], ['Required?', 'مطلوب؟'], ['Values and effect', 'القيم والأثر']],
                [
                    [['Name', 'الاسم'], ['Display name; the identifier is generated from it.', 'اسم العرض، ويُولَّد المعرّف منه.'], ['Yes', 'نعم'], ['Free text; the ID field is derived automatically and cannot be edited.', 'نص حر، ويُشتق حقل المعرّف تلقائيًا ولا يمكن تعديله.']],
                    [['Result type', 'نوع النتيجة'], ['How the result should be read.', 'كيف تُقرأ النتيجة.'], ['Yes', 'نعم'], ['Percentage, Rate, Ratio or Count; it labels the value, the multiplier converts it.', 'نسبة مئوية أو معدل أو نسبة أو عدد، وتسمّي القيمة ويحوّلها المعامل.']],
                    [['Multiplier / Unit', 'المعامل / الوحدة'], ['Scaling and label of the result.', 'مقياس النتيجة وتسميتها.'], ['No', 'لا'], ['Default multiplier 100 (percentage), unit such as %.', 'المعامل الافتراضي 100 (نسبة مئوية) والوحدة مثل %.']],
                    [['Numerator / Denominator', 'البسط / المقام'], ['The data elements combined into the value.', 'عناصر البيانات المجمّعة في القيمة.'], ['Yes for ratio', 'نعم للنسبة'], ['Only data elements are offered; aggregation is Sum, Average, Min or Max and the operator is ÷ + − ×.', 'تُعرض عناصر البيانات فقط، والجمع هو Sum أو Average أو Min أو Max والمعامل ÷ + − ×.']],
                    [['Expression', 'المعادلة'], ['Alternative to numerator/denominator.', 'بديل عن البسط والمقام.'], ['Yes for expression', 'نعم للمعادلة'], ['{code} references with + − * / and parentheses; the preview line shows the evaluated formula.', 'مراجع {code} مع + − * / والأقواس، ويعرض سطر المعاينة المعادلة المُقيَّمة.']],
                    [['Global / Local direction', 'الاتجاه العام / المحلي'], ['Clinical meaning used when interpreting deviation.', 'المعنى السريري المستخدم في تفسير الانحراف.'], ['No', 'لا'], ['None, Higher is better, Lower is better, or Target range with a value or min/max bounds.', 'بلا اتجاه، أو الأعلى أفضل، أو الأدنى أفضل، أو نطاق مستهدف بقيمة أو حدّي أدنى وأعلى.']],
                    [['Status', 'الحالة'], ['Whether the indicator participates in analysis.', 'هل يشارك المؤشر في التحليل.'], ['—', '—'], ['Active/Inactive; inactive indicators stop being computed and validated.', 'مفعّل/معطّل، ويتوقف المؤشر المعطّل عن الحساب والتحقق.']],
                ],
            ),
        ],
        actions: [
            table(
                [['Action', 'الإجراء'], ['What it does', 'ما يفعله'], ['Writes data?', 'يعدّل البيانات؟'], ['When to use / prerequisites', 'متى يُستخدم / المتطلبات']],
                [
                    [['New Indicator', 'مؤشر جديد'], ['Opens the builder for a derived indicator.', 'يفتح منشئ مؤشر مشتق.'], ['Yes — on Save', 'نعم — عند الحفظ'], ['settings.write.', 'يتطلب settings.write.']],
                    [['Validate', 'تحقق'], ['Checks the draft and lists problems without saving.', 'يفحص المسودة ويسرد المشكلات دون حفظ.'], ['No', 'لا'], ['Before Save, especially for expressions.', 'قبل الحفظ وخصوصًا مع المعادلات.']],
                    [['Save', 'حفظ'], ['Creates or updates the indicator definition and bumps its version.', 'ينشئ تعريف المؤشر أو يحدّثه ويرفع إصداره.'], ['Yes — definition', 'نعم — التعريف'], ['settings.write; requires a name and a complete formula.', 'يتطلب settings.write واسمًا ومعادلة مكتملة.']],
                    [['Edit / Delete', 'تعديل / حذف'], ['Changes the definition, or deletes the managed indicator.', 'يغيّر التعريف أو يحذف المؤشر المُدار.'], ['Yes', 'نعم'], ['settings.write; check data references before deleting.', 'يتطلب settings.write، وراجع مراجع البيانات قبل الحذف.']],
                    [['Activate / Deactivate', 'تفعيل / تعطيل'], ['Toggles whether the indicator takes part in analysis.', 'يبدّل مشاركة المؤشر في التحليل.'], ['Yes — configuration', 'نعم — إعدادات'], ['settings.write; takes effect on the next analysis of a month.', 'يتطلب settings.write، ويسري عند التحليل التالي للشهر.']],
                    [['Recompute latest', 'إعادة حساب الأحدث'], ['Recomputes stored results for the latest data month.', 'يعيد حساب النتائج المخزّنة لأحدث شهر بيانات.'], ['Yes — results', 'نعم — النتائج'], ['settings.write; use after a formula change.', 'يتطلب settings.write، ويُستخدم بعد تغيير معادلة.']],
                    [['Run preview', 'تشغيل المعاينة'], ['Evaluates the indicator against a chosen hospital and month without storing it.', 'يقيّم المؤشر على مستشفى وشهر مختارين دون تخزين.'], ['No', 'لا'], ['Before saving, to confirm the formula on real data.', 'قبل الحفظ للتأكد من المعادلة على بيانات حقيقية.']],
                ],
            ),
        ],
        results: [
            p(
                'A derived indicator is not uploadable data: it is computed from the stored data elements whenever the month is analysed. Its stored results table therefore lists what the last analysis wrote, with a status and a version per row.',
                'المؤشر المشتق ليس بيانات قابلة للرفع، بل يُحسب من عناصر البيانات المخزّنة عند تحليل الشهر. لذلك يسرد جدول نتائجه المخزّنة ما كتبه آخر تحليل، مع حالة وإصدار لكل صف.',
            ),
            list(
                ['The formula column is the definition the system evaluates; if a value looks wrong, compare it with Data Tree values for the same month.', 'عمود المعادلة هو التعريف الذي يقيّمه النظام، وإذا بدت القيمة خاطئة فقارنها بقيم شجرة البيانات للشهر نفسه.'],
                ['Version history records each change to the definition with the actor and time, so “why did this value change?” is answerable.', 'يسجّل سجل الإصدارات كل تغيير في التعريف مع المنفّذ والوقت، فتُجاب مسألة «لماذا تغيّرت هذه القيمة؟».'],
                ['Direction fields do not change the stored value; they change how a deviation from the benchmark is interpreted by alerts.', 'حقول الاتجاه لا تغيّر القيمة المخزّنة، بل تغيّر تفسير الانحراف عن المرجع في التنبيهات.'],
                ['Recomputing one month does not rewrite older months; their results keep the definition used when they were analysed.', 'إعادة حساب شهر لا تعيد كتابة الشهور الأقدم، فنتائجها تحتفظ بالتعريف المستخدم عند تحليلها.'],
            ),
        ],
        examples: [
            p(
                'A caesarean rate is needed: New Indicator › name “C-Section Rate” › result type Percentage with multiplier 100 › numerator “Caesarean Sections” › denominator “Total Deliveries” › global direction Lower is better with the agreed benchmark. Validate, preview on one hospital-month, then Save.',
                'يراد معدل قيصريات: «مؤشر جديد» › الاسم «معدل القيصريات» › نوع النتيجة نسبة مئوية بمعامل 100 › البسط «Caesarean Sections» › المقام «Total Deliveries» › الاتجاه العام «الأدنى أفضل» مع المرجع المتفق عليه. ثم «تحقق» ومعاينة على مستشفى/شهر ثم «حفظ».',
            ),
            p(
                'A formula change is needed after a reporting-form update: edit the definition, save, press Recompute latest, then re-analyse the affected older months so their stored values follow the new definition.',
                'يلزم تغيير معادلة بعد تحديث نموذج التقرير: عدّل التعريف واحفظ واضغط «إعادة حساب الأحدث» ثم أعد تحليل الشهور الأقدم المتأثرة لتتبع قيمها التعريف الجديد.',
            ),
        ],
        problems: [
            table(
                [['Problem', 'المشكلة'], ['Cause', 'السبب'], ['Resolution', 'الحل']],
                [
                    [['Validate reports a missing or invalid formula', '«تحقق» يبلّغ عن معادلة ناقصة أو غير صحيحة'], ['No numerator/denominator, or an expression with unknown {code}.', 'لا بسط أو مقام، أو معادلة تحتوي {code} غير معروف.'], ['Complete both zones or reference existing codes only; the formula preview must show a value.', 'أكمل المنطقتين أو استخدم أكوادًا موجودة فقط، ويجب أن يعرض سطر المعاينة قيمة.']],
                    [['Save is unavailable', 'زر الحفظ غير متاح'], ['settings.write is missing, or the draft failed validation.', 'صلاحية settings.write غير متاحة أو فشلت المسودة في التحقق.'], ['Review the validation messages; ask an administrator for the permission.', 'راجع رسائل التحقق واطلب الصلاحية من المسؤول.']],
                    [['A derived value is empty for a month', 'قيمة مشتقة فارغة لشهر'], ['One of the referenced data elements is missing or null for that hospital-month.', 'أحد عناصر البيانات المرجعية ناقص أو فارغ لذلك المستشفى/الشهر.'], ['Check Data Tree for the referenced codes and fix the upload.', 'راجع شجرة البيانات للأكواد المرجعية وصحّح الرفع.']],
                    [['The value did not change after editing the formula', 'لم تتغير القيمة بعد تعديل المعادلة'], ['The month was not re-analysed.', 'لم يُعَد تحليل الشهر.'], ['Press Recompute latest, or re-analyse that month from Upload Data.', 'اضغط «إعادة حساب الأحدث» أو أعد تحليل الشهر من رفع البيانات.']],
                ],
            ),
        ],
        related: [
            table(
                [['Screen', 'الشاشة'], ['Relationship', 'العلاقة']],
                [
                    [['Data Tree', 'شجرة البيانات'], ['Source values the derived indicator is computed from.', 'القيم المصدر التي يُحسب منها المؤشر المشتق.']],
                    [['Direction Coverage', 'تغطية الاتجاه'], ['Lists indicators still missing a clinical direction and proposes one.', 'يسرد المؤشرات التي ينقصها اتجاه سريري ويقترحه.']],
                    [['Validation Rules', 'قواعد التحقق'], ['Rules that compare indicator values and totals.', 'قواعد تقارن قيم المؤشرات والإجماليات.']],
                    [['Smart Analytics', 'التحليلات الذكية'], ['Uses the stored indicator history for forecasting and risk views.', 'يستخدم تاريخ المؤشرات المخزّن للتنبؤ وعرض المخاطر.']],
                ],
            ),
        ],
    },
};
