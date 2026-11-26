// ── Guide: Validation Rules ──────────────────────────────────────────────────
import { p, list, steps, table } from '../guide-kit.js';

export default {
    key: 'rules-manager',
    tab: 'rules-manager',
    icon: '📋',
    title: { en: 'Validation Rules', ar: 'قواعد التحقق' },
    menu: { en: 'Data › Validation Rules', ar: 'البيانات › قواعد التحقق' },
    permission: 'rules.read',
    shot: 'validation-rules.png',
    shotAlt: {
        en: 'Validation Rules screen with filters, the rules table and the expression reference',
        ar: 'شاشة قواعد التحقق مع المرشّحات وجدول القواعد ومرجع أنواع المعادلات',
    },
    shotLegend: [
        { en: 'Rule count, Add Rule, Export, Import, Save, Refresh', ar: 'عدد القواعد وإضافة قاعدة وتصدير واستيراد وحفظ وتحديث' },
        { en: 'Category / Type / Severity / Status filters', ar: 'مرشّحات الفئة والنوع والخطورة والحالة' },
        { en: 'Search and bulk Enable all / Disable all', ar: 'البحث والتفعيل أو التعطيل الجماعي للصفوف المصفّاة' },
        { en: 'Rules table with sortable Code, Severity and Affected Hospitals', ar: 'جدول القواعد مع أعمدة كود وخطورة ومستشفيات متأثرة قابلة للفرز' },
        { en: 'Enabled column and per-row actions', ar: 'عمود التفعيل وإجراءات كل صف' },
        { en: 'Expression Types Reference card', ar: 'بطاقة مرجع أنواع المعادلات' },
    ],
    nextSteps: [
        {
            tab: 'alerts',
            label: { en: 'See the failures these rules produce', ar: 'شاهد الإخفاقات التي تنتجها هذه القواعد' },
            why: {
                en: 'Validation Result lists every failed rule per hospital and month.',
                ar: 'تسرد نتيجة التحقق كل قاعدة فاشلة لكل مستشفى وشهر.',
            },
        },
        {
            tab: 'quality',
            label: { en: 'Check the compliance effect', ar: 'راجع أثر الالتزام' },
            why: {
                en: 'Rule compliance is a component of the Quality Score.',
                ar: 'الالتزام بالقواعد مكوّن من مكوّنات درجة الجودة.',
            },
        },
    ],
    sections: {
        overview: [
            p(
                'Validation Rules is the rule catalog and its control panel. Each rule states a logical check over reported values (for example a total must be at least the sum of its parts), and the analysis runs the enabled rules for every hospital-month.',
                'شاشة قواعد التحقق هي كتالوج القواعد ولوحة التحكم بها. تفرض كل قاعدة فحصًا منطقيًا على القيم المبلَّغ عنها (مثل أن يكون الإجمالي على الأقل مجموع أجزائه)، ويشغّل التحليل القواعد المفعّلة لكل مستشفى وشهر.',
            ),
            list(
                ['Why it exists: data-quality defects must be caught the same way every month, not by ad-hoc spreadsheet review.', 'لماذا وُجدت: يجب كشف عيوب جودة البيانات بالطريقة نفسها كل شهر لا بمراجعة جدول عشوائية.'],
                ['Who uses it: quality officers and administrators; viewing needs rules.read, and every write needs rules.write.', 'من يستخدمها: مسؤولو الجودة والمديرون، والاطلاع يحتاج rules.read وكل كتابة تحتاج rules.write.'],
                ['When: when a new consistency rule is agreed, when a rule is noisy and must be paused, or when the rule set is exported/imported between environments.', 'متى: عند اعتماد قاعدة اتساق جديدة، أو إيقاف قاعدة مزعجة مؤقتًا، أو تصدير/استيراد مجموعة القواعد بين البيئات.'],
            ),
        ],
        layout: [
            table(
                [['Area', 'المنطقة'], ['What it contains', 'ما تحتويه']],
                [
                    [['Header', 'الترويسة'], ['Rule count, Add Rule, Export, Import, Save (when there are pending changes), Refresh.', 'عدد القواعد وإضافة قاعدة وتصدير واستيراد وحفظ عند وجود تغييرات معلّقة وتحديث.']],
                    [['Filters', 'المرشّحات'], ['Category, Type, Severity and Status selectors, plus a filtered-count label and bulk Enable all / Disable all.', 'مرشّحات الفئة والنوع والخطورة والحالة مع عدّاد للصفوف المصفّاة وزرّي التفعيل والتعطيل الجماعي.']],
                    [['Search', 'البحث'], ['Searches code, name, description and category; the ✕ button clears it. The box is reset every time the screen opens.', 'يبحث في الكود والاسم والوصف والفئة، وزر ✕ يفرّغه، ويُفرَّغ الحقل آليًا كلما فُتحت الشاشة.']],
                    [['Table', 'الجدول'], ['Code, Name, Type, Severity, Category, Expression, Affected Hospitals, Enabled, Actions; Code, Severity and Affected Hospitals are sortable.', 'الكود والاسم والنوع والخطورة والفئة والمعادلة والمستشفيات المتأثرة والتفعيل والإجراءات، والأعمدة كود وخطورة ومستشفيات متأثرة قابلة للفرز.']],
                    [['Expression reference', 'مرجع المعادلات'], ['Collapsible table of every expression type with its logic, required parameters and an example.', 'جدول قابل للطي بكل أنواع المعادلات ومنطقها ومعاملاتها المطلوبة ومثال عليها.']],
                    [['Rule drawer', 'لوحة القاعدة'], ['Full details of a clicked rule: expression, parameters, affected hospitals and its history.', 'تفاصيل القاعدة المنقورة: المعادلة والمعاملات والمستشفيات المتأثرة وسجلها.']],
                ],
            ),
        ],
        usage: [
            steps(
                ['Open Data › Validation Rules. The catalog loads sorted by code.', 'افتح البيانات › قواعد التحقق ليُحمَّل الكتالوج مرتّبًا بالكود.'],
                ['Narrow with the category, type, severity or status filters, or type in the search box.', 'ضيّق النتائج بمرشّحات الفئة أو النوع أو الخطورة أو الحالة، أو اكتب في مربع البحث.'],
                ['Click a rule row to open the drawer and read its expression, parameters, affected hospitals and history.', 'انقر صف قاعدة لتفتح اللوحة وتقرأ معادلتها ومعاملاتها والمستشفيات المتأثرة وسجلها.'],
                ['To add one, press Add Rule, fill the code, name, type, severity, category and expression type, then enter the parameters the expression requires (the reference card lists them).', 'لإضافة قاعدة اضغط «إضافة قاعدة» واملأ الكود والاسم والنوع والخطورة والفئة ونوع المعادلة ثم أدخل المعاملات التي تتطلبها (يسردها مرجع المعادلات).'],
                ['Validate / test the rule against a hospital before saving; the editor warns about possible conflicts with existing rules.', 'تحقق من القاعدة أو اختبرها على مستشفى قبل الحفظ، وينبّه المحرّر إلى تعارضات محتملة مع قواعد قائمة.'],
                ['Enable or disable a rule from its row, or in bulk for the currently filtered rows, then press Save if the change is pending.', 'فعّل القاعدة أو عطّلها من صفّها أو دفعة واحدة للصفوف المصفّاة حاليًا ثم اضغط «حفظ» إن كان التغيير معلّقًا.'],
                ['Use Export to keep a JSON copy, and Import to load a rule set. Refresh reloads the catalog and its impact counts.', 'استخدم «تصدير» لحفظ نسخة JSON و«استيراد» لتحميل مجموعة قواعد، ويعيد «تحديث» تحميل الكتالوج وأعداد الأثر.'],
            ),
        ],
        fields: [
            table(
                [['Field', 'الحقل'], ['Meaning', 'المعنى'], ['Required?', 'مطلوب؟'], ['Values and effect', 'القيم والأثر']],
                [
                    [['Code', 'الكود'], ['Stable identifier of the rule.', 'معرّف ثابت للقاعدة.'], ['Yes', 'نعم'], ['Short text; used by history and exports.', 'نص قصير يستخدمه السجل والتصدير.']],
                    [['Name', 'الاسم'], ['What the rule checks, in words.', 'ما تفحصه القاعدة بالكلمات.'], ['Yes', 'نعم'], ['Free text shown in the table and on Validation Result.', 'نص حر يظهر في الجدول وفي نتيجة التحقق.']],
                    [['Type', 'النوع'], ['Rule family.', 'عائلة القاعدة.'], ['Yes', 'نعم'], ['Logic, Clinical or Data Quality.', 'Logic أو Clinical أو Data Quality.']],
                    [['Severity', 'الخطورة'], ['How serious a failure is.', 'مدى خطورة الإخفاق.'], ['Yes', 'نعم'], ['Critical, High, Medium or Low; drives alert ranking.', 'Critical أو High أو Medium أو Low، ويوجّه ترتيب التنبيهات.']],
                    [['Category', 'الفئة'], ['Grouping used by the filter.', 'التجميع المستخدم في المرشّح.'], ['Yes', 'نعم'], ['BASIC_LOGIC, CLINICAL_CONSISTENCY, CLINICAL_LOGIC, PLAUSIBILITY or TREND_DATA_QUALITY.', 'BASIC_LOGIC أو CLINICAL_CONSISTENCY أو CLINICAL_LOGIC أو PLAUSIBILITY أو TREND_DATA_QUALITY.']],
                    [['Expression type + parameters', 'نوع المعادلة والمعاملات'], ['The actual check and the codes it compares.', 'الفحص الفعلي والأكواد التي يقارنها.'], ['Yes', 'نعم'], ['One of the reference types (ge, gt, eq, le, lt, month_over, month_under, neg_check, decimal_check, missing, all_zero, formula and their variants) with its required parameters.', 'أحد أنواع المرجع (ge وgt وeq وle وlt وmonth_over وmonth_under وneg_check وdecimal_check وmissing وall_zero وformula ومشتقاتها) مع معاملاتها المطلوبة.']],
                    [['Enabled', 'مفعّلة'], ['Whether the analysis runs the rule.', 'هل يشغّل التحليل القاعدة.'], ['Yes', 'نعم'], ['Disabled rules are skipped during analysis and are excluded from failures.', 'تُتجاهل القواعد المعطّلة أثناء التحليل وتُستبعد من الإخفاقات.']],
                ],
            ),
        ],
        actions: [
            table(
                [['Action', 'الإجراء'], ['What it does', 'ما يفعله'], ['Writes data?', 'يعدّل البيانات؟'], ['When to use / prerequisites', 'متى يُستخدم / المتطلبات']],
                [
                    [['+ Add Rule', 'إضافة قاعدة'], ['Opens the rule editor for a new rule.', 'يفتح محرّر القاعدة لقاعدة جديدة.'], ['Yes — on save', 'نعم — عند الحفظ'], ['rules.write.', 'يتطلب rules.write.']],
                    [['Row click', 'النقر على الصف'], ['Opens the drawer with details and history.', 'يفتح اللوحة بالتفاصيل والسجل.'], ['No', 'لا'], ['rules.read.', 'يتطلب rules.read.']],
                    [['Edit / Delete', 'تعديل / حذف'], ['Changes or removes the rule.', 'يغيّر القاعدة أو يحذفها.'], ['Yes', 'نعم'], ['rules.write; deletion is permanent.', 'يتطلب rules.write، والحذف دائم.']],
                    [['Test rule', 'اختبار القاعدة'], ['Evaluates the rule against a chosen hospital to see the outcome before enabling it.', 'يقيّم القاعدة على مستشفى مختار لرؤية النتيجة قبل تفعيلها.'], ['No', 'لا'], ['Before saving a new or changed rule.', 'قبل حفظ قاعدة جديدة أو معدّلة.']],
                    [['Enable all / Disable all', 'تفعيل الكل / تعطيل الكل'], ['Toggles every rule that matches the current filters.', 'يبدّل كل قاعدة تطابق المرشّحات الحالية.'], ['Yes — bulk', 'نعم — جماعي'], ['rules.write; review the filtered count first.', 'يتطلب rules.write، وراجع عدّاد الصفوف المصفّاة أولًا.']],
                    [['Export / Import', 'تصدير / استيراد'], ['Writes or reads the rule set as JSON.', 'يكتب مجموعة القواعد بصيغة JSON أو يقرأها.'], ['Import: yes', 'الاستيراد: نعم'], ['rules.write for Import; Export is a download.', 'يتطلب rules.write للاستيراد، والتصدير تنزيل.']],
                    [['Refresh', 'تحديث'], ['Reloads rules and impact counts.', 'يعيد تحميل القواعد وأعداد الأثر.'], ['No', 'لا'], ['After another administrator edits rules.', 'بعد أن يعدّل مسؤول آخر القواعد.']],
                ],
            ),
        ],
        results: [
            p(
                '“Affected Hospitals” counts the hospitals the rule currently concerns, so a rule with a large number is either broadly relevant or too permissive. The rule itself does not produce a score here: failures appear on Validation Result, and rule compliance feeds the Quality Score.',
                'يعدّ عمود «المستشفيات المتأثرة» المستشفيات التي تخصّها القاعدة حاليًا، فالقاعدة ذات العدد الكبير إمّا واسعة الصلة أو متساهلة. القاعدة لا تنتج درجة هنا: تظهر الإخفاقات في نتيجة التحقق، ويُغذّي الالتزام بالقواعد درجة الجودة.',
            ),
            list(
                ['A disabled rule is skipped in analysis, so its failures disappear from new runs but stored results of past months are not rewritten automatically.', 'تُتجاهل القاعدة المعطّلة في التحليل فتختفي إخفاقاتها من التشغيلات الجديدة، لكن نتائج الشهور السابقة لا تُعاد كتابتها تلقائيًا.'],
                ['History in the drawer shows what changed on the rule and when, which is how a sudden change in failures is explained.', 'يعرض سجل اللوحة ما تغيّر في القاعدة ومتى، وبذلك يُفسَّر التغيّر المفاجئ في الإخفاقات.'],
                ['Severity does not change the check; it changes how a failure is ranked and escalated on the alert screens.', 'الخطورة لا تغيّر الفحص بل ترتيب الإخفاق وتصعيده في شاشات التنبيه.'],
            ),
        ],
        examples: [
            p(
                'Deliveries must not be less than the sum of normal and caesarean deliveries. Create a rule with category BASIC_LOGIC, type Logic, severity High, expression ge with parent 2 and children 3 and 4. Test it on one hospital, save it, and the next analysed month lists a failure for every hospital where the total is smaller than its parts.',
                'لا يجوز أن تقل الولادات عن مجموع الطبيعية والقيصرية. أنشئ قاعدة بفئة BASIC_LOGIC ونوع Logic وخطورة High ومعادلة ge بأب 2 وأبناء 3 و4. اختبرها على مستشفى ثم احفظها، فيسرد الشهر المحلَّل التالي إخفاقًا لكل مستشفى إجماليه أصغر من أجزائه.',
            ),
            p(
                'A new rule turns out noisy: filter by its category, disable it from its row, press Save, then re-analyse the affected month if its failures should disappear from that month’s stored results.',
                'تظهر قاعدة جديدة مزعجة: صفِّ حسب فئتها وعطّلها من صفّها واضغط «حفظ» ثم أعد تحليل الشهر المتأثر إن أردت اختفاء إخفاقاتها من نتائجه المخزّنة.',
            ),
        ],
        problems: [
            table(
                [['Problem', 'المشكلة'], ['Cause', 'السبب'], ['Resolution', 'الحل']],
                [
                    [['“Possible conflicts” on save', '«تعارضات محتملة» عند الحفظ'], ['The rule overlaps an existing check that would always fail with it.', 'تتقاطع القاعدة مع فحص قائم بحيث يفشل دائمًا معها.'], ['Read the warning; save anyway only if the overlap is intended.', 'اقرأ التحذير ولا تحفظ إلا إذا كان التقاطع مقصودًا.']],
                    [['A rule never fails', 'قاعدة لا تفشل أبدًا'], ['Its expression or parameters are wrong, or it is disabled.', 'معادلتها أو معاملاتها خاطئة أو أنها معطّلة.'], ['Test it on a hospital known to violate it and check the Enabled column.', 'اختبرها على مستشفى معروف بمخالفتها وتحقق من عمود التفعيل.']],
                    [['Import rejects the file', 'الاستيراد يرفض الملف'], ['The JSON is not an exported rule set or contains invalid expressions.', 'ملف JSON ليس مجموعة قواعد مصدّرة أو يحتوي معادلات غير صحيحة.'], ['Import only a file produced by Export, or fix the reported entry.', 'استورد فقط ملفًا أنتجه «تصدير» أو صحّح العنصر المذكور.']],
                    [['Changes vanished', 'اختفاء التغييرات'], ['Toggles were made but Save was not pressed before leaving.', 'أُجريت التبديلات دون ضغط «حفظ» قبل المغادرة.'], ['Redo the change and press Save; the Save button appears only with pending changes.', 'أعد التغيير واضغط «حفظ»، ويظهر الزر عند وجود تغييرات معلّقة فقط.']],
                ],
            ),
        ],
        related: [
            table(
                [['Screen', 'الشاشة'], ['Relationship', 'العلاقة']],
                [
                    [['Validation Result', 'نتيجة التحقق'], ['Lists the failures of these rules.', 'يسرد إخفاقات هذه القواعد.']],
                    [['Quality Reports', 'تقارير الجودة'], ['Rule compliance is one component of the score.', 'الالتزام بالقواعد أحد مكوّنات الدرجة.']],
                    [['Data Tree', 'شجرة البيانات'], ['Where the values a rule compares can be inspected.', 'حيث يمكن فحص القيم التي تقارنها القاعدة.']],
                    [['Indicators', 'المؤشرات'], ['Derived indicators are valid references inside rule expressions.', 'المؤشرات المشتقة مراجع صالحة داخل معادلات القواعد.']],
                ],
            ),
        ],
    },
};
