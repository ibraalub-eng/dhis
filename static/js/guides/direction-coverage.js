// ── Guide: Direction Coverage ────────────────────────────────────────────────
import { p, list, steps, table } from '../guide-kit.js';

export default {
    key: 'direction-coverage',
    tab: 'direction-coverage',
    icon: '🧭',
    title: { en: 'Direction Coverage', ar: 'تغطية الاتجاه' },
    menu: { en: 'Analysis › Direction Coverage (Data section in the default layout)', ar: 'التحليل › تغطية الاتجاه (قسم البيانات في التخطيط الافتراضي)' },
    permission: 'settings.read',
    shot: 'direction-coverage.png',
    shotAlt: {
        en: 'Direction Coverage screen with the three summary cards and the review table',
        ar: 'شاشة تغطية الاتجاه مع بطاقات الملخص الثلاث وجدول المراجعة',
    },
    shotLegend: [
        { en: 'Refresh and Apply selected', ar: 'تحديث وتطبيق المحدد' },
        { en: 'Summary cards: families, active alerts, suggestions', ar: 'بطاقات الملخص: العائلات والتنبيهات النشطة والاقتراحات' },
        { en: 'Rescan banner after applying', ar: 'شريط إعادة الفحص بعد التطبيق' },
        { en: 'Search and the filter selector', ar: 'البحث ومحدّد التصفية' },
        { en: 'Select all with a suggestion', ar: 'تحديد كل ما له اقتراح' },
        { en: 'Table: code, name, active alerts, direction, why suggested', ar: 'الجدول: الكود والاسم والتنبيهات النشطة والاتجاه وسبب الاقتراح' },
    ],
    nextSteps: [
        {
            tab: 'quality-alerts',
            label: { en: 'Re-scan Quality Alerts', ar: 'أعد فحص تنبيهات الجودة' },
            why: {
                en: 'Stored alerts keep the old interpretation until they are re-scanned.',
                ar: 'تحتفظ التنبيهات المخزّنة بالتفسير القديم حتى إعادة فحصها.',
            },
        },
        {
            tab: 'indicators',
            label: { en: 'Read the indicator definition', ar: 'اقرأ تعريف المؤشر' },
            why: {
                en: 'The code link opens the indicator behind the direction.',
                ar: 'يفتح رابط الكود المؤشر الكامن وراء الاتجاه.',
            },
        },
    ],
    sections: {
        overview: [
            p(
                'Direction Coverage lists the indicator families and data elements that still carry no clinical direction — that is, the system cannot tell whether a higher or a lower value is better for them. It also shows the direction the server proposes and the evidence behind it, so a reviewer can confirm it in one batch.',
                'تسرد تغطية الاتجاه عائلات المؤشرات وعناصر البيانات التي لا تحمل اتجاهًا سريريًا بعد، أي أن النظام لا يستطيع تحديد ما إذا كانت القيمة الأعلى أو الأدنى أفضل لها. وتعرض أيضًا الاتجاه الذي يقترحه الخادم والدليل وراءه، ليؤكده المراجع دفعة واحدة.',
            ),
            list(
                ['Why it exists: Quality Alerts can label a deviation as good or bad only when the indicator carries a direction; without one the deviation is reported without a verdict.', 'لماذا وُجدت: تستطيع تنبيهات الجودة وصف الانحراف بأنه جيد أو سيئ فقط عندما يحمل المؤشر اتجاهًا، وبدونه يُبلَّغ عن الانحراف دون حكم.'],
                ['Who uses it: clinical reviewers and administrators with settings.read; applying directions needs settings.write.', 'من يستخدمها: المراجعون السريريون والمديرون بصلاحية settings.read، وتطبيق الاتجاهات يحتاج settings.write.'],
                ['When: before relying on Quality Alerts for interpretation, and whenever a new indicator family is introduced without a direction.', 'متى: قبل الاعتماد على تنبيهات الجودة في التفسير، وكلما أُدخلت عائلة مؤشرات جديدة بلا اتجاه.'],
            ),
        ],
        layout: [
            table(
                [['Area', 'المنطقة'], ['What it contains', 'ما تحتويه']],
                [
                    [['Header', 'الترويسة'], ['Refresh and Apply selected, with the number of selected rows in brackets.', 'تحديث وتطبيق المحدد، وعدد الصفوف المحددة بين قوسين.']],
                    [['Summary cards', 'بطاقات الملخص'], ['Families without direction, active alerts affected, and families that already have a suggested direction.', 'العائلات بلا اتجاه، والتنبيهات النشطة المتأثرة، والعائلات التي لها اقتراح.']],
                    [['Rescan banner', 'شريط إعادة الفحص'], ['Appears after applying, warning that stored alerts keep the old interpretation until a Quality Alerts scan.', 'يظهر بعد التطبيق وينبّه إلى أن التنبيهات المخزّنة تحتفظ بالتفسير القديم حتى فحص تنبيهات الجودة.']],
                    [['Filter bar', 'شريط التصفية'], ['Search over code, name and group; filter All items / With active alerts / With a suggestion; Select all with a suggestion; visible count.', 'بحث في الكود والاسم والمجموعة، وتصفية: كل العناصر / ذات تنبيهات نشطة / ذات اقتراح، وتحديد كل ما له اقتراح، وعدّاد الظاهر.']],
                    [['Table', 'الجدول'], ['Checkbox, code (opens the indicator definition in a new tab), name with unit and group, active alerts, direction to apply, and why it was suggested.', 'مربع تحديد، والكود يفتح تعريف المؤشر في تبويب جديد، والاسم مع الوحدة والمجموعة، والتنبيهات النشطة، والاتجاه المراد تطبيقه، وسبب الاقتراح.']],
                ],
            ),
        ],
        usage: [
            steps(
                ['Open Data › Direction Coverage (in this database it sits under Analysis).', 'افتح البيانات › تغطية الاتجاه (وهي في قاعدة البيانات الحالية تحت التحليل).'],
                ['Read the three cards to size the work: how many families lack a direction and how many active alerts depend on them.', 'اقرأ البطاقات الثلاث لتقدير حجم العمل: كم عائلة بلا اتجاه وكم تنبيهًا نشطًا يعتمد عليها.'],
                ['Filter to “With active alerts” to review the items with the highest impact first.', 'صفِّ على «ذات تنبيهات نشطة» لمراجعة الأعلى أثرًا أولًا.'],
                ['For each row, accept the proposed direction in the selector or choose the other one. Choosing a direction ticks the row automatically.', 'لكل صف اقبل الاتجاه المقترح في القائمة أو اختر الآخر. واختيار اتجاه يحدّد الصف تلقائيًا.'],
                ['Press Apply selected. A confirmation lists the families and their directions before anything is written.', 'اضغط «تطبيق المحدد»، وتعرض نافذة التأكيد العائلات واتجاهاتها قبل كتابة أي شيء.'],
                ['After applying, use Rescan all months in the banner so Quality Alerts reinterprets stored alerts with the new directions.', 'بعد التطبيق استخدم «إعادة فحص كل الأشهر» في الشريط ليعيد تنبيهات الجودة تفسير التنبيهات المخزّنة بالاتجاهات الجديدة.'],
            ),
        ],
        fields: [
            table(
                [['Field', 'الحقل'], ['Meaning', 'المعنى'], ['Required?', 'مطلوب؟'], ['Values and effect', 'القيم والأثر']],
                [
                    [['Code', 'الكود'], ['Indicator or data-element code.', 'كود المؤشر أو عنصر البيانات.'], ['—', '—'], ['The link opens its definition on the Indicators screen in a new tab.', 'يفتح الرابط تعريفه في شاشة المؤشرات بتبويب جديد.']],
                    [['Active alerts', 'التنبيهات النشطة'], ['How many active Quality Alerts are currently interpreted without a direction for this item.', 'عدد تنبيهات الجودة النشطة التي تُفسَّر حاليًا بلا اتجاه لهذا العنصر.'], ['—', '—'], ['The higher the number, the more interpretation is at stake.', 'كلما زاد العدد زادت أهمية التفسير.']],
                    [['Direction to apply', 'الاتجاه المراد تطبيقه'], ['The clinical meaning to store.', 'المعنى السريري المراد تخزينه.'], ['Yes for each selected row', 'نعم لكل صف محدد'], ['Higher is better or Lower is better; the suggestion is preselected when one exists.', 'الأعلى أفضل أو الأدنى أفضل، ويُختار الاقتراح مسبقًا عند وجوده.']],
                    [['Suggested because', 'سبب الاقتراح'], ['The evidence behind the proposal.', 'الدليل وراء الاقتراح.'], ['—', '—'], ['Clinical guideline, or the element’s role as the numerator of a directed rate; blank when there is no evidence.', 'دليل سريري أو دور العنصر كبسط لمعدل موجّه، ويبقى فارغًا عند غياب الدليل.']],
                ],
            ),
        ],
        actions: [
            table(
                [['Action', 'الإجراء'], ['What it does', 'ما يفعله'], ['Writes data?', 'يعدّل البيانات؟'], ['When to use / prerequisites', 'متى يُستخدم / المتطلبات']],
                [
                    [['Refresh', 'تحديث'], ['Reloads the coverage list and the cards.', 'يعيد تحميل قائمة التغطية والبطاقات.'], ['No', 'لا'], ['After another reviewer applies directions.', 'بعد أن يطبّق مراجع آخر اتجاهات.']],
                    [['Apply selected', 'تطبيق المحدد'], ['Writes the chosen direction for every selected row after a confirmation listing them.', 'يكتب الاتجاه المختار لكل صف محدد بعد تأكيد يسردها.'], ['Yes — configuration', 'نعم — إعدادات'], ['settings.write; every selected row must have a direction, otherwise nothing is written.', 'يتطلب settings.write، ويجب أن يكون لكل صف محدد اتجاه وإلا لا يُكتب شيء.']],
                    [['Rescan all months', 'إعادة فحص كل الأشهر'], ['Runs a full Quality Alerts scan so stored alerts are reinterpreted.', 'يشغّل فحصًا كاملًا لتنبيهات الجودة لإعادة تفسير التنبيهات المخزّنة.'], ['Yes — alerts', 'نعم — التنبيهات'], ['quality_alerts.write; offered in the banner after applying.', 'يتطلب quality_alerts.write، ويُعرض في الشريط بعد التطبيق.']],
                    [['Select all with a suggestion', 'تحديد كل ما له اقتراح'], ['Ticks every visible row that already has a proposed direction.', 'يحدّد كل صف ظاهر له اتجاه مقترح.'], ['No', 'لا'], ['Bulk review when the proposals are trustworthy.', 'مراجعة جماعية عندما تكون الاقتراحات موثوقة.']],
                ],
            ),
        ],
        results: [
            p(
                'The screen never invents a clinical meaning: rows without evidence have an empty proposal, and the reviewer must choose. Applying writes the direction only; it changes no stored values and no stored alert text.',
                'لا تبتكر الشاشة معنى سريريًا: الصفوف بلا دليل تبقى بلا اقتراح وعلى المراجع أن يختار. التطبيق يكتب الاتجاه فقط، ولا يغيّر أي قيمة مخزّنة ولا نص تنبيه مخزّن.',
            ),
            list(
                ['“Active alerts affected” counts alerts whose interpretation depends on the missing direction; after a rescan the number drops for the applied items.', 'يعدّ «التنبيهات النشطة المتأثرة» التنبيهات التي يعتمد تفسيرها على الاتجاه الناقص، وينخفض العدد بعد إعادة الفحص للعناصر المطبّقة.'],
                ['A direction that was already recorded is skipped, so re-applying is harmless and reports nothing to change.', 'يُتخطّى الاتجاه المسجّل سابقًا، فإعادة التطبيق غير ضارة وتُبلغ أنه لا شيء لتغييره.'],
                ['Until the rescan runs, Quality Alerts keep the old interpretation: the banner states this explicitly and must not be ignored.', 'إلى أن تُنفَّذ إعادة الفحص تحتفظ تنبيهات الجودة بالتفسير القديم، ويصرّح الشريط بذلك ولا يجوز تجاهله.'],
            ),
        ],
        examples: [
            p(
                'The reviewer filters to “With active alerts”, sees a family of maternal-death indicators with a guideline-based proposal “Lower is better”, presses Select all with a suggestion, then Apply selected. The toast reports the applied count, the banner appears, and Rescan all months is pressed so the stored alerts are reinterpreted.',
                'يصفّي المراجع على «ذات تنبيهات نشطة» فيرى عائلة مؤشرات وفيات الأمومة مع اقتراح مبني على دليل «الأدنى أفضل»، ثم يضغط «تحديد كل ما له اقتراح» ثم «تطبيق المحدد». يبلغ التنبيه بعدد المطبَّق ويظهر الشريط، فيضغط «إعادة فحص كل الأشهر» لإعادة تفسير التنبيهات المخزّنة.',
            ),
        ],
        problems: [
            table(
                [['Problem', 'المشكلة'], ['Cause', 'السبب'], ['Resolution', 'الحل']],
                [
                    [['“Select at least one row to apply”', '«حدّد صفًا واحدًا على الأقل للتطبيق»'], ['No row is ticked.', 'لا يوجد صف محدد.'], ['Tick rows, or choose a direction (which ticks the row).', 'حدّد صفوفًا أو اختر اتجاهًا (فيُحدَّد الصف).']],
                    [['“Choose a direction for the selected rows…”', '«اختر اتجاهًا للصفوف المحددة…»'], ['A selected row has an empty direction, often a row with no suggestion.', 'صف محدد بلا اتجاه، وغالبًا صف بلا اقتراح.'], ['Choose a direction for it or clear its selection; the message names up to five codes.', 'اختر له اتجاهًا أو أزل تحديده، وتذكر الرسالة حتى خمسة أكواد.']],
                    [['Apply has no effect on alerts', 'التطبيق لا يؤثر في التنبيهات'], ['Directions were written but the rescan did not run.', 'كُتبت الاتجاهات لكن لم تُنفَّذ إعادة الفحص.'], ['Press Rescan all months in the banner (needs quality_alerts.write).', 'اضغط «إعادة فحص كل الأشهر» في الشريط (يتطلب quality_alerts.write).']],
                    [['Rows have no suggestion', 'صفوف بلا اقتراح'], ['No clinical evidence exists for that element.', 'لا يوجد دليل سريري لذلك العنصر.'], ['Decide clinically and choose the direction manually; the screen will not guess.', 'قرّر سريريًا واختر الاتجاه يدويًا، فالشاشة لا تخمّن.']],
                ],
            ),
        ],
        related: [
            table(
                [['Screen', 'الشاشة'], ['Relationship', 'العلاقة']],
                [
                    [['Indicators', 'المؤشرات'], ['Where the code link opens the definition and its benchmark directions.', 'حيث يفتح رابط الكود التعريف واتجاهات مرجعه.']],
                    [['Quality Alerts', 'تنبيهات الجودة'], ['Consumes the direction to label a deviation as good or bad; needs a rescan after applying.', 'يستهلك الاتجاه لوصف الانحراف جيدًا أو سيئًا، ويحتاج إعادة فحص بعد التطبيق.']],
                    [['Outlier Diagnostics', 'تشخيص الشذوذ'], ['Shows the deviation itself; its interpretation also depends on direction.', 'يعرض الانحراف نفسه، ويعتمد تفسيره أيضًا على الاتجاه.']],
                    [['Data Tree', 'شجرة البيانات'], ['Where the underlying values can be inspected.', 'حيث يمكن فحص القيم الأساسية.']],
                ],
            ),
        ],
    },
};
