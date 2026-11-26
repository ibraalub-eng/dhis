// ── Guide: Data Tree ─────────────────────────────────────────────────────────
import { p, list, steps, table } from '../guide-kit.js';

export default {
    key: 'indicator-tree',
    tab: 'indicator-tree',
    icon: '🌳',
    title: { en: 'Data Tree', ar: 'شجرة البيانات' },
    menu: { en: 'Data › Data Tree', ar: 'البيانات › شجرة البيانات' },
    permission: 'settings.read',
    shot: 'data-tree.png',
    shotAlt: {
        en: 'Data Tree screen with hospital and month selectors and the indicator hierarchy',
        ar: 'شاشة شجرة البيانات مع محدّدَي المستشفى والشهر وتدرّج المؤشرات',
    },
    shotLegend: [
        { en: 'Hospital selector (includes Default for all hospitals)', ar: 'محدّد المستشفى (يشمل «افتراضي» لكل المستشفيات)' },
        { en: 'Month selector (includes All Months)', ar: 'محدّد الشهر (يشمل «كل الأشهر»)' },
        { en: 'Load Tree and Save Config buttons', ar: 'زرّا تحميل الشجرة وحفظ الإعداد' },
        { en: 'Expand / Collapse and the bulk tools', ar: 'توسيع/طي الشجرة والأدوات الجماعية' },
        { en: 'Tree: codes, names, values and requirement types', ar: 'الشجرة: الأكواد والأسماء والقيم ونوع المتطلب' },
        { en: 'Undo banner after removing data', ar: 'شريط التراجع بعد حذف البيانات' },
    ],
    nextSteps: [
        {
            tab: 'indicators',
            label: { en: 'Inspect the indicator definition', ar: 'افحص تعريف المؤشر' },
            why: {
                en: 'The Indicators screen explains how a derived value shown here is computed.',
                ar: 'تشرح شاشة المؤشرات كيف تُحسب القيمة المشتقة المعروضة هنا.',
            },
        },
        {
            tab: 'quality-completeness',
            label: { en: 'See the completeness effect', ar: 'شاهد أثر الاكتمال' },
            why: {
                en: 'Changing a requirement type changes the completeness denominator.',
                ar: 'تغيير نوع المتطلب يغيّر مقام الاكتمال.',
            },
        },
    ],
    sections: {
        overview: [
            p(
                'Data Tree is the read-and-inspect view of the stored indicator values: one hierarchy per hospital and month, showing the code, name, stored value and requirement type of every data element and derived indicator.',
                'شجرة البيانات هي عرض القراءة والفحص للقيم المخزّنة: تدرّج واحد لكل مستشفى وشهر يعرض الكود والاسم والقيمة المخزّنة ونوع المتطلب لكل عنصر بيانات ومؤشر مشتق.',
            ),
            list(
                ['Why it exists: the analysis reads the same values, so questions such as “did this value arrive?” or “why is this counted as missing?” are answered here, at the source.', 'لماذا وُجدت: يقرأ التحليل هذه القيم نفسها، فأسئلة مثل «هل وصلت هذه القيمة؟» أو «لماذا تُحتسب ناقصة؟» تُجاب هنا من المصدر.'],
                ['Who uses it: data officers, analysts and administrators with settings.read; two tools need settings.write and data.manage respectively.', 'من يستخدمها: مسؤولو البيانات والمحللون والمديرون ممن يملكون settings.read، وأداتان تحتاجان settings.write وdata.manage.'],
                ['When: after an upload to verify values, and when a hospital disputes a missing value or a completeness figure.', 'متى: بعد الرفع للتحقق من القيم، وعندما تعترض مستشفى على قيمة ناقصة أو رقم اكتمال.'],
            ),
        ],
        layout: [
            table(
                [['Area', 'المنطقة'], ['What it contains', 'ما تحتويه']],
                [
                    [['Filter bar', 'شريط التصفية'], ['Hospital selector (including Default for all hospitals), month selector (including All Months), Load Tree, and Save Config when there are unsaved changes.', 'محدّد المستشفى (بما فيه «افتراضي» لكل المستشفيات) ومحدّد الشهر (بما فيه «كل الأشهر») وزر تحميل الشجرة وزر حفظ الإعداد عند وجود تغييرات غير محفوظة.']],
                    [['Tree toolbar', 'شريط أدوات الشجرة'], ['Expand All, Collapse All, Remove Data (data.manage), Never-Reported and Optional Detector (settings.write).', 'توسيع الكل وطي الكل وحذف البيانات (data.manage) وأداة غير المُبلَّغ عنها وكاشف الاختيارية (settings.write).']],
                    [['Notices', 'الإشعارات'], ['Undo banner after a removal, and the auto-disable-null notice when that policy is on.', 'شريط التراجع بعد الحذف، وإشعار التعطيل التلقائي للقيم الفارغة عند تفعيل تلك السياسة.']],
                    [['Tree panel', 'لوحة الشجرة'], ['Scrollable hierarchy with values; each node carries its requirement state.', 'تدرّج قابل للتمرير مع القيم، ولكل عقدة حالتها في المتطلب.']],
                    [['Summary line', 'سطر الملخص'], ['Indicator count and load state for the selected hospital/month.', 'عدد المؤشرات وحالة التحميل للمستشفى والشهر المختارين.']],
                ],
            ),
        ],
        usage: [
            steps(
                ['Open Data › Data Tree.', 'افتح البيانات › شجرة البيانات.'],
                ['Choose a hospital — or Default to read the shared default configuration — and a month, or All Months for the aggregated view.', 'اختر مستشفى — أو «افتراضي» لقراءة الإعداد الافتراضي المشترك — وشهرًا، أو «كل الأشهر» للعرض المجمّع.'],
                ['Press Load Tree. The summary line reports how many indicators were loaded.', 'اضغط تحميل الشجرة، ويذكر سطر الملخص عدد المؤشرات المحمّلة.'],
                ['Expand or collapse nodes; the requirement chip on a node shows whether the element is Required or Optional for that hospital/month.', 'وسّع العقد أو اطوِها، وتُظهر شارة المتطلب على العقدة ما إذا كان العنصر مطلوبًا أو اختياريًا لذلك المستشفى والشهر.'],
                ['If you changed a requirement type, press Save Config. Saving a hospital-specific configuration offers a Re-analyze button so the scores reflect the new definition.', 'إن غيّرت نوع المتطلب فاضغط حفظ الإعداد. حفظ إعداد خاص بمستشفى يعرض زر «إعادة التحليل» لتحديث الدرجات وفق التعريف الجديد.'],
                ['To delete a month’s data, select one hospital (or Default) and one specific month, press Remove Data, confirm, and use Undo while the banner is visible if needed.', 'لحذف بيانات شهر اختر مستشفى واحدًا (أو «افتراضي») وشهرًا محددًا، واضغط حذف البيانات وأكّد، واستخدم «تراجع» أثناء ظهور الشريط إن لزم.'],
            ),
        ],
        fields: [
            table(
                [['Field', 'الحقل'], ['Meaning', 'المعنى'], ['Required?', 'مطلوب؟'], ['Values and effect', 'القيم والأثر']],
                [
                    [['Hospital', 'المستشفى'], ['Whose stored values to show.', 'قيم من تُعرض.'], ['Yes', 'نعم'], ['Any active or inactive hospital, or Default; Default reads the shared default tree configuration rather than one hospital.', 'أي مستشفى نشط أو غير نشط أو «افتراضي»، ويقرأ الافتراضي إعداد الشجرة المشترك لا مستشفى بعينه.']],
                    [['Month', 'الشهر'], ['Which reporting month to show.', 'شهر التقرير المعروض.'], ['Yes', 'نعم'], ['YYYY-MM, or All Months; removal is refused for All Months.', 'بصيغة YYYY-MM أو «كل الأشهر»، ويُرفض الحذف عند اختيار «كل الأشهر».']],
                    [['Requirement type', 'نوع المتطلب'], ['Whether a data element counts as required for the hospital-month.', 'هل يُحتسب عنصر البيانات مطلوبًا للمستشفى والشهر.'], ['—', '—'], ['Required or Optional; Optional keeps the value visible but removes it from the completeness denominator.', 'مطلوب أو اختياري، والاختياري يبقي القيمة ظاهرة لكنه يستبعدها من مقام الاكتمال.']],
                    [['Value', 'القيمة'], ['The stored number the analysis will use.', 'الرقم المخزّن الذي سيستخدمه التحليل.'], ['—', '—'], ['Empty means no stored value for that pair; whether that is “missing” depends on the requirement type and the auto-disable policy.', 'الفراغ يعني عدم وجود قيمة لذلك الزوج، وكونها «ناقصة» يعتمد على نوع المتطلب وسياسة التعطيل التلقائي.']],
                ],
            ),
        ],
        actions: [
            table(
                [['Action', 'الإجراء'], ['What it does', 'ما يفعله'], ['Writes data?', 'يعدّل البيانات؟'], ['When to use / prerequisites', 'متى يُستخدم / المتطلبات']],
                [
                    [['Load Tree', 'تحميل الشجرة'], ['Loads the hierarchy and stored values for the chosen hospital/month.', 'يحمّل التدرّج والقيم المخزّنة للمستشفى والشهر.'], ['No', 'لا'], ['After changing either selector.', 'بعد تغيير أي محدّد.']],
                    [['Expand All / Collapse All', 'توسيع الكل / طي الكل'], ['Opens or closes every node.', 'يفتح أو يغلق كل العقد.'], ['No', 'لا'], ['Navigation only.', 'للتنقل فقط.']],
                    [['Save Config', 'حفظ الإعداد'], ['Stores the requirement-type changes for the chosen hospital and month (or for the default tree).', 'يحفظ تغييرات نوع المتطلب للمستشفى والشهر المختارين (أو للشجرة الافتراضية).'], ['Yes — configuration', 'نعم — إعدادات'], ['Appears when something changed; needs settings.write.', 'يظهر عند وجود تغيير، ويحتاج settings.write.']],
                    [['Re-analyze', 'إعادة التحليل'], ['Recomputes the saved hospital configuration into its stored results.', 'يعيد حساب إعداد المستشفى المحفوظ داخل نتائجه المخزّنة.'], ['Yes — analysis results', 'نعم — نتائج التحليل'], ['Shown after saving a hospital-specific config.', 'يظهر بعد حفظ إعداد خاص بمستشفى.']],
                    [['Remove Data', 'حذف البيانات'], ['Deletes the indicator values of one hospital and one month, then re-runs analysis; a snapshot allows Undo.', 'يحذف قيم مؤشرات مستشفى وشهر واحد ثم يعيد التحليل، وتتيح لقطة تراجعًا.'], ['Yes — destructive', 'نعم — إجراء خطِر'], ['data.manage; one hospital and one specific month; not All Months.', 'يتطلب data.manage ومستشفى واحدًا وشهرًا محددًا، لا «كل الأشهر».']],
                    [['Never-Reported', 'غير المُبلَّغ عنها'], ['Previews every indicator no hospital ever reported and disables them in one confirmed batch.', 'يعاين كل مؤشر لم يبلّغ عنه أي مستشفى ثم يعطّله دفعة واحدة بعد تأكيد.'], ['Yes — configuration', 'نعم — إعدادات'], ['settings.write; useful after a new form adds unused elements.', 'يتطلب settings.write، ومفيد بعد إضافة عناصر غير مستخدمة إلى النموذج.']],
                    [['Optional Detector', 'كاشف الاختيارية'], ['Finds data elements no hospital ever reported a value for and proposes marking them Optional.', 'يجد عناصر بيانات لم يبلّغ عنها أي مستشفى بقيمة ويقترح جعلها اختيارية.'], ['Yes — configuration', 'نعم — إعدادات'], ['settings.write; Optional stays visible but leaves the completeness denominator.', 'يتطلب settings.write، ويبقى الاختياري ظاهرًا لكنه يخرج من مقام الاكتمال.']],
                ],
            ),
        ],
        results: [
            p(
                'The tree is not a calculation screen: it shows the stored inputs the analysis will read. A blank value is not automatically “missing” — it is missing only when the element is Required for that hospital-month and the auto-disable policy does not exclude it.',
                'الشجرة ليست شاشة حساب، بل تعرض المدخلات المخزّنة التي سيقرأها التحليل. القيمة الفارغة ليست «ناقصة» تلقائيًا، بل تكون ناقصة فقط إذا كان العنصر مطلوبًا لذلك المستشفى والشهر ولم تستبعده سياسة التعطيل التلقائي.',
            ),
            list(
                ['Requirement changes affect the completeness denominator, and therefore the Quality Score, only after the configuration is saved and the month is re-analysed.', 'تؤثر تغييرات المتطلب في مقام الاكتمال وبالتالي درجة الجودة بعد حفظ الإعداد وإعادة تحليل الشهر فقط.'],
                ['Removing a month’s data leaves the other months untouched; the undo snapshot is valid while its banner is shown.', 'حذف بيانات شهر لا يمس بقية الشهور، ولقطة التراجع صالحة ما دام شريطها ظاهرًا.'],
                ['Never-Reported and Optional Detector change configuration for all hospitals, not only the one selected in the filter.', 'تغيّر أداتا «غير المُبلَّغ عنها» و«كاشف الاختيارية» الإعداد لكل المستشفيات لا للمستشفى المختار في التصفية فقط.'],
            ),
        ],
        examples: [
            p(
                'A hospital reports 300 deliveries but the dashboard flags the month as incomplete. Data Tree for that hospital/month shows code 2 = 300 while the sub-elements (2.a, 2.b) are empty: the derived total exists, the elements do not. If those sub-elements are never reported by any hospital, Optional Detector proposes marking them Optional; otherwise the hospital must supply them.',
                'تبلّغ مستشفى عن 300 ولادة لكن لوحة القيادة تُعلّم الشهر كناقص. تُظهر شجرة البيانات لذلك المستشفى/الشهر الكود 2 = 300 بينما العناصر الفرعية (2.a و2.b) فارغة: الإجمالي المشتق موجود والعناصر غير موجودة. إن لم يبلّغ أي مستشفى عن هذه العناصر فسيقترح «كاشف الاختيارية» جعلها اختيارية، وإلا وجب على المستشفى تزويدها.',
            ),
            p(
                'A hospital uploaded a file for the wrong month: the officer selects that hospital and month, presses Remove Data, confirms, then presses Undo in the banner to restore the values if the removal was a mistake, or re-uploads the correct file.',
                'رفعت مستشفى ملفًا لشهر خاطئ: يختار المسؤول ذلك المستشفى والشهر ويضغط حذف البيانات ويؤكد، ثم يضغط «تراجع» في الشريط لاستعادة القيم إن كان الحذف خطأً، أو يعيد رفع الملف الصحيح.',
            ),
        ],
        problems: [
            table(
                [['Problem', 'المشكلة'], ['Cause', 'السبب'], ['Resolution', 'الحل']],
                [
                    [['Save Config is not visible', 'زر حفظ الإعداد غير ظاهر'], ['Nothing changed yet, or settings.write is missing.', 'لا يوجد تغيير بعد، أو صلاحية settings.write غير متاحة.'], ['Change a requirement type; ask an administrator for the permission.', 'غيّر نوع متطلب، واطلب الصلاحية من المسؤول.']],
                    [['Remove Data is disabled', 'زر حذف البيانات معطّل'], ['No hospital, no month, or All Months is selected; or data.manage is missing.', 'لم يُحدَّد مستشفى أو شهر أو اختير «كل الأشهر»، أو صلاحية data.manage غير متاحة.'], ['Select one hospital and one specific month.', 'اختر مستشفى واحدًا وشهرًا محددًا.']],
                    [['Values stay blank after an upload', 'بقاء القيم فارغة بعد الرفع'], ['The column header or month did not match, so nothing was written for that element.', 'لم يتطابق ترويسة العمود أو الشهر فلم تُكتب قيمة لذلك العنصر.'], ['Check the saved file in Upload Data and re-import a corrected file.', 'راجع الملف المحفوظ في رفع البيانات وأعد استيراد ملف مصحّح.']],
                    [['Undo banner disappeared', 'اختفاء شريط التراجع'], ['The banner was dismissed or the page was reloaded.', 'أُغلق الشريط أو أُعيد تحميل الصفحة.'], ['The removal stands; restore by re-uploading the file.', 'يبقى الحذف قائمًا، وتُستعاد القيم بإعادة رفع الملف.']],
                ],
            ),
        ],
        related: [
            table(
                [['Screen', 'الشاشة'], ['Relationship', 'العلاقة']],
                [
                    [['Upload Data', 'رفع البيانات'], ['Where the values inspected here come from.', 'مصدر القيم التي تُفحص هنا.']],
                    [['Data Group', 'مجموعة البيانات'], ['Bulk enable/disable of indicator families, which changes what the tree shows as disabled.', 'تفعيل أو تعطيل عائلات مؤشرات دفعة واحدة، وهو ما يغيّر ما تُظهره الشجرة كمعطّل.']],
                    [['Indicators', 'المؤشرات'], ['Definitions and formulas behind the derived values.', 'التعريفات والمعادلات وراء القيم المشتقة.']],
                    [['Completeness', 'الاكتمال'], ['Shows the effect of requirement types on the completeness score.', 'يعرض أثر أنواع المتطلبات على درجة الاكتمال.']],
                ],
            ),
        ],
    },
};
