// ── Guide: Upload Data ───────────────────────────────────────────────────────
import { p, list, steps, table } from '../guide-kit.js';

export default {
    key: 'upload',
    tab: 'upload',
    icon: '📤',
    title: { en: 'Upload Data', ar: 'رفع البيانات' },
    menu: { en: 'Data › Upload Data', ar: 'البيانات › رفع البيانات' },
    permission: 'data.upload',
    shot: 'upload-data.png',
    shotAlt: {
        en: 'Upload Data screen with the four-step bar, drop zone and saved files card',
        ar: 'شاشة رفع البيانات مع شريط الخطوات الأربع ومنطقة الإفلات وبطاقة الملفات المحفوظة',
    },
    shotLegend: [
        { en: 'Step bar (Upload → Preview → Analyze → Results)', ar: 'شريط الخطوات (رفع ← معاينة ← تحليل ← نتائج)' },
        { en: 'Drop zone / file picker', ar: 'منطقة الإفلات أو اختيار الملفات' },
        { en: 'Preview table and Confirm/Cancel buttons', ar: 'جدول المعاينة وزرّا التأكيد والإلغاء' },
        { en: 'Progress bar and month analysis chips', ar: 'شريط التقدم وشرائح حالة تحليل الشهور' },
        { en: 'Previously uploaded files card', ar: 'بطاقة الملفات المرفوعة سابقًا' },
        { en: 'Results section after import', ar: 'قسم النتائج بعد الاستيراد' },
    ],
    nextSteps: [
        {
            tab: 'indicator-tree',
            label: { en: 'Check the imported values', ar: 'تحقّق من القيم المستوردة' },
            why: {
                en: 'Data Tree shows the stored values per hospital and month exactly as the analysis reads them.',
                ar: 'تُظهر شجرة البيانات القيم المخزّنة لكل مستشفى وشهر كما يقرأها التحليل تمامًا.',
            },
        },
        {
            tab: 'alerts',
            label: { en: 'Review validation results', ar: 'راجع نتائج التحقق' },
            why: {
                en: 'Rules run during the analysis; failures are listed on Validation Result.',
                ar: 'تُشغَّل القواعد أثناء التحليل وتظهر إخفاقاتها في شاشة نتيجة التحقق.',
            },
        },
        {
            tab: 'quality',
            label: { en: 'Open the quality reports', ar: 'افتح تقارير الجودة' },
            why: {
                en: 'A month gets a quality score once its background analysis finishes.',
                ar: 'يحصل الشهر على درجة جودة بعد انتهاء تحليله في الخلفية.',
            },
        },
    ],
    sections: {
        overview: [
            p(
                'Upload Data is the only entry point for monthly SRMNH indicator values. It reads an Excel or CSV file, shows what the file will store before anything is written, imports the values, and starts the background analysis that produces validation results, quality scores and alerts.',
                'رفع البيانات هو المدخل الوحيد لقيم مؤشرات SRMNH الشهرية. يقرأ ملف Excel أو CSV، ويعرض ما سيُخزَّن قبل كتابة أي شيء، ثم يستورد القيم ويبدأ التحليل الخلفي الذي ينتج نتائج التحقق ودرجات الجودة والتنبيهات.',
            ),
            list(
                ['Why it exists: hospitals report in spreadsheets, and the system needs one controlled, previewed import instead of manual data entry.', 'لماذا وُجدت: ترفع المستشفيات بياناتها في جداول، ويحتاج النظام استيرادًا واحدًا خاضعًا للمعاينة بدل الإدخال اليدوي.'],
                ['Who uses it: data officers and administrators who hold the data.upload permission.', 'من يستخدمها: مسؤولو البيانات والمديرون ممن يملكون صلاحية data.upload.'],
                ['When: at the end of each reporting month, or when a hospital corrects or re-sends its file.', 'متى: في نهاية كل شهر تقرير، أو عند تصحيح ملف مستشفى أو إعادة إرساله.'],
            ),
        ],
        layout: [
            table(
                [['Area', 'المنطقة'], ['What it contains', 'ما تحتويه']],
                [
                    [['Step bar', 'شريط الخطوات'], ['Four steps: Upload, Preview, Analyze, Results.', 'أربع خطوات: الرفع، المعاينة، التحليل، النتائج.']],
                    [['Drop zone', 'منطقة الإفلات'], ['Drag-and-drop area and a click-to-browse file input; multiple files are accepted.', 'منطقة سحب وإفلات وزر لاختيار الملفات، وتقبل عدة ملفات.']],
                    [['Preview area', 'منطقة المعاينة'], ['Table of the parsed rows and the Confirm & Import / Cancel buttons.', 'جدول بالصفوف المقروءة وزرّا تأكيد واستيراد وإلغاء.']],
                    [['Status and progress', 'الحالة والتقدم'], ['Status line, progress bar, and the month analysis chips.', 'سطر الحالة وشريط التقدم وشرائح حالة تحليل الشهور.']],
                    [['Previously uploaded files', 'الملفات المرفوعة سابقًا'], ['One row per saved file with its own update/analyze/delete/download actions; hidden for users without data.upload.', 'صف لكل ملف محفوظ مع إجراءات التحديث والتحليل والحذف والتنزيل، ويُخفى لمن لا يملك data.upload.']],
                    [['Results', 'النتائج'], ['Summary of hospitals, months and imported rows, plus follow-up links after the analysis.', 'ملخص المستشفيات والشهور والصفوف المستوردة مع روابط المتابعة بعد التحليل.']],
                ],
            ),
        ],
        usage: [
            steps(
                ['Open Data › Upload Data from the sidebar.', 'افتح البيانات › رفع البيانات من القائمة الجانبية.'],
                ['Drag the file onto the drop zone or click it to choose a file. Accepted types: .xlsx, .xls, .csv, .xlsm, .xlsb; maximum 20 MB per file.', 'اسحب الملف إلى منطقة الإفلات أو انقر لاختياره. الأنواع المقبولة: .xlsx و.xls و.csv و.xlsm و.xlsb، وبحد أقصى 20 ميجابايت للملف.'],
                ['Read the preview table. It is read-only: it shows the rows the server will import. If the columns do not match, cancel and fix the file.', 'اقرأ جدول المعاينة. الجدول للقراءة فقط ويعرض الصفوف التي سيستوردها الخادم. إن لم تكن الأعمدة مطابقة فألغِ العملية وصحّح الملف.'],
                ['Press Confirm & Import. The step bar moves to Analyze and a progress bar appears.', 'اضغط تأكيد واستيراد. ينتقل شريط الخطوات إلى التحليل ويظهر شريط التقدم.'],
                ['Watch the month chips under the progress bar: each month shows whether its analysis is queued, running, complete or failed, with the finished hospital count.', 'راقب شرائح الشهور أسفل شريط التقدم: يظهر لكل شهر ما إذا كان تحليله في الانتظار أو جاريًا أو مكتملًا أو فاشلًا، مع عدد المستشفيات المنتهية.'],
                ['Read the results section when the run finishes, then follow the links to validation results and quality reports.', 'اقرأ قسم النتائج عند انتهاء التشغيل ثم تابع الروابط إلى نتائج التحقق وتقارير الجودة.'],
                ['To re-import or correct a file later, use its row in Previously Uploaded Files (Update, Analyze, Delete, Download).', 'لإعادة استيراد ملف أو تصحيحه لاحقًا استخدم صفّه في الملفات المرفوعة سابقًا (تحديث، تحليل، حذف، تنزيل).'],
            ),
        ],
        fields: [
            table(
                [['Field', 'الحقل'], ['Meaning', 'المعنى'], ['Required?', 'مطلوب؟'], ['Values and effect', 'القيم والأثر']],
                [
                    [['File', 'الملف'], ['The SRMNH spreadsheet to import.', 'جدول SRMNH المراد استيراده.'], ['Yes', 'نعم'], ['.xlsx/.xls/.csv/.xlsm/.xlsb, ≤ 20 MB; anything else is rejected before upload.', 'xlsx/xls/csv/xlsm/xlsb وبحد 20 ميجابايت، ويرفض ما سواها قبل الرفع.']],
                    [['Preview table', 'جدول المعاينة'], ['Parsed rows of the chosen file.', 'الصفوف المقروءة من الملف المختار.'], ['—', '—'], ['Read-only; it is the last check before writing.', 'للقراءة فقط، وهي آخر تحقق قبل الكتابة.']],
                    [['Month chip', 'شريحة الشهر'], ['Analysis state of one uploaded month.', 'حالة تحليل شهر مرفوع.'], ['—', '—'], ['Queued / Analyzing (with %) / Complete / Failed, plus analyzed-of-total hospitals.', 'في الانتظار / جاري التحليل مع النسبة / مكتمل / فاشل، مع عدد المستشفيات المنتهية من الإجمالي.']],
                    [['Saved file row', 'صف الملف المحفوظ'], ['A file already imported and stored.', 'ملف سبق استيراده وحفظه.'], ['—', '—'], ['Shows its months and row count; actions operate on that file only.', 'يعرض شهوره وعدد صفوفه، وتعمل الإجراءات على ذلك الملف وحده.']],
                ],
            ),
        ],
        actions: [
            table(
                [['Action', 'الإجراء'], ['What it does', 'ما يفعله'], ['Writes data?', 'يعدّل البيانات؟'], ['When to use / prerequisites', 'متى يُستخدم / المتطلبات']],
                [
                    [['Confirm & Import', 'تأكيد واستيراد'], ['Imports the previewed file and starts the background analysis.', 'يستورد الملف المعروض ويبدأ التحليل الخلفي.'], ['Yes', 'نعم'], ['After checking the preview; requires data.upload.', 'بعد التحقق من المعاينة، ويتطلب data.upload.']],
                    [['Cancel', 'إلغاء'], ['Closes the preview without importing.', 'يغلق المعاينة دون استيراد.'], ['No', 'لا'], ['When the preview shows the wrong file or columns.', 'عندما تُظهر المعاينة ملفًا أو أعمدة خاطئة.']],
                    [['Refresh (saved files)', 'تحديث (الملفات المحفوظة)'], ['Reloads the saved-file list.', 'يعيد تحميل قائمة الملفات المحفوظة.'], ['No', 'لا'], ['After another user uploaded a file.', 'بعد أن يرفع مستخدم آخر ملفًا.']],
                    [['Analyze Selected / per-file Analyze', 'تحليل المحدد / تحليل ملف'], ['Re-runs the analysis of the selected saved file(s) without re-importing.', 'يعيد تحليل الملفات المحددة دون إعادة استيراد.'], ['Writes analysis results', 'يكتب نتائج التحليل'], ['When a month is stuck or after changing rules/indicators.', 'عند تعليق شهر أو بعد تغيير قواعد أو مؤشرات.']],
                    [['Update (per file)', 'تحديث (لكل ملف)'], ['Replaces the stored file with a newly chosen one and re-imports it.', 'يستبدل الملف المخزّن بملف جديد ويعيد استيراده.'], ['Yes', 'نعم'], ['When a hospital corrects its report.', 'عندما تصحّح مستشفى تقريرها.']],
                    [['Delete (per file)', 'حذف (لكل ملف)'], ['Deletes the file and its imported records after a confirmation dialog.', 'يحذف الملف وسجلاته المستوردة بعد تأكيد.'], ['Yes — irreversible', 'نعم — غير قابل للتراجع'], ['Only for files uploaded by mistake; the dialog states the deletion is permanent.', 'للملفات المرفوعة بالخطأ فقط، ويوضّح التأكيد أن الحذف دائم.']],
                    [['Download (per file)', 'تنزيل (لكل ملف)'], ['Downloads the stored copy of the file.', 'ينزّل نسخة الملف المخزّنة.'], ['No', 'لا'], ['To check what was actually imported.', 'للتحقق مما استُورد فعليًا.']],
                ],
            ),
        ],
        results: [
            p(
                'The results section summarises how many hospitals, months and rows the import touched. The month chips are the authoritative progress: they are computed from the same analysis eligibility the rest of the system uses, so a hospital-month that is disabled, or has no enabled indicator values, is not counted as unfinished.',
                'يلخّص قسم النتائج عدد المستشفيات والشهور والصفوف التي طالها الاستيراد. شرائح الشهور هي المرجع في التقدّم، وتُحسب من أهلية التحليل نفسها المستخدمة في بقية النظام، لذا لا يُحتسب زوج مستشفى/شهر معطّل أو بلا قيم مفعّلة على أنه غير منتهٍ.',
            ),
            list(
                ['Complete with a count such as 18/18 means every eligible hospital-month of that month produced a stored result.', 'تعني «مكتمل» مع عدّ مثل 18/18 أن كل زوج مؤهّل في الشهر أنتج نتيجة مخزّنة.'],
                ['Complete 0/0 means nothing in that month is analysable (all pairs disabled or without enabled values); it is not an error.', 'تعني «مكتمل 0/0» أنه لا شيء في الشهر قابل للتحليل (كل الأزواج معطّلة أو بلا قيم مفعّلة)، وليست خطأ.'],
                ['Failed names how many hospitals could not be analysed; hover the chip to read the message.', 'تذكر «فاشل» عدد المستشفيات التي تعذّر تحليلها، ومرّر المؤشر على الشريحة لقراءة الرسالة.'],
                ['The upload screen does not compute scores itself: the quality score, validation results and alerts appear on their own screens after the analysis finishes.', 'شاشة الرفع لا تحسب الدرجات بنفسها، بل تظهر درجة الجودة ونتائج التحقق والتنبيهات في شاشاتها بعد انتهاء التحليل.'],
            ),
        ],
        examples: [
            p(
                'A data officer uploads the October 2026 file for 18 hospitals. The preview lists the parsed rows; after Confirm & Import the chip reads “2026-10 Analyzing 40%” and then “✓ 2026-10 Complete 18/18”. Opening Quality Reports shows the new month for all hospitals, and Validation Result lists the rule failures found in it.',
                'يرفع مسؤول البيانات ملف تشرين الأول 2026 لـ18 مستشفى. تعرض المعاينة الصفوف المقروءة، وبعد التأكيد تظهر الشريحة «2026-10 جاري التحليل 40%» ثم «✓ 2026-10 مكتمل 18/18». تفتح تقارير الجودة فيظهر الشهر الجديد لكل المستشفيات، وتعرض نتيجة التحقق إخفاقات القواعد فيه.',
            ),
            p(
                'A hospital re-sends a corrected file: the officer opens the file row, presses Update, chooses the new file, and the preview/import flow repeats for that file only. Other files are untouched.',
                'تعيد مستشفى إرسال ملف مصحّح: يفتح المسؤول صف الملف ويضغط تحديث ويختار الملف الجديد، فتتكرر المعاينة والاستيراد لذلك الملف فقط دون المساس بالملفات الأخرى.',
            ),
        ],
        problems: [
            table(
                [['Problem', 'المشكلة'], ['Cause', 'السبب'], ['Resolution', 'الحل']],
                [
                    [['“Unsupported file type”', '«نوع ملف غير مدعوم»'], ['The extension is outside the five accepted ones.', 'الامتداد خارج الأنواع الخمسة المقبولة.'], ['Save as .xlsx or .csv and retry.', 'احفظ الملف بصيغة xlsx أو csv وأعد المحاولة.']],
                    [['“exceeds the 20 MB limit”', '«يتجاوز حد 20 ميجابايت»'], ['The file is too large.', 'حجم الملف كبير.'], ['Remove unused sheets/columns or split the file by month.', 'احذف الأوراق أو الأعمدة غير المستخدمة أو قسّم الملف حسب الشهر.']],
                    [['Preview fails or columns are not recognised', 'فشل المعاينة أو أعمدة غير معروفة'], ['Headers or month format differ from the SRMNH template.', 'ترويسات الأعمدة أو صيغة الشهر مخالفة لقالب SRMNH.'], ['Compare with a previously imported file (Download) and correct the headers/month (YYYY-MM).', 'قارن بملف سبق استيراده (تنزيل) وصحّح الترويسات والشهر بصيغة YYYY-MM.']],
                    [['A month stays Queued', 'شهر يبقى في الانتظار'], ['Its analysis task did not run to completion (service restart or a failed task).', 'لم تكتمل مهمة تحليله (إعادة تشغيل الخدمة أو مهمة فاشلة).'], ['Run Analyze on the saved file; if it stays queued, contact an administrator.', 'شغّل «تحليل» على الملف المحفوظ، وإن بقي في الانتظار فتواصل مع المسؤول.']],
                    [['Wrong file imported', 'استيراد ملف خاطئ'], ['Confirmed by mistake.', 'تأكيد بالخطأ.'], ['Delete that file (permanent) and import the correct one; there is no undo.', 'احذف ذلك الملف (حذف دائم) واستورد الصحيح، فلا يوجد تراجع.']],
                ],
            ),
        ],
        related: [
            table(
                [['Screen', 'الشاشة'], ['Relationship', 'العلاقة']],
                [
                    [['Data Tree', 'شجرة البيانات'], ['Shows the stored values per hospital/month, including the values this import wrote.', 'يعرض القيم المخزّنة لكل مستشفى/شهر بما فيها ما كتبه هذا الاستيراد.']],
                    [['Indicators', 'المؤشرات'], ['A new column in the file can create a new data element; derived indicators are computed from these values.', 'يمكن لعمود جديد في الملف إنشاء عنصر بيانات جديد، وتُحسب المؤشرات المشتقة من هذه القيم.']],
                    [['Validation Result', 'نتيجة التحقق'], ['List of rule failures found in the imported data.', 'قائمة إخفاقات القواعد في البيانات المستوردة.']],
                    [['Quality Reports', 'تقارير الجودة'], ['Per-hospital monthly score produced by the analysis this screen starts.', 'درجة شهرية لكل مستشفى ينتجها التحليل الذي تبدأه هذه الشاشة.']],
                ],
            ),
        ],
    },
};
