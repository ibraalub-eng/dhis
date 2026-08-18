        import { _tabInited, switchTab } from './main.js';

        // ── Translation System (EN ↔ AR) ─────────────────────────
        export let currentLang = localStorage.getItem('lang') || 'ar';

        export const translations = {
            // General UI
            'Dashboard': 'لوحة القيادة',
            'Quality Reports': 'تقارير الجودة',
            'Trend Analysis': 'تحليل الاتجاهات',
            'Hospital Comparison': 'مقارنة المستشفيات',
            'Clinical Intelligence': 'التحليل السريري',
            'AI Reports': 'تقارير الذكاء الاصطناعي',
            'Outliers': 'القيم الشاذة',
            'Alerts': 'التنبيهات',
            'Rule Failures': 'إخفاقات القواعد',
            'Indicator Tree': 'شجرة المؤشرات',
            'Rules Manager': 'إدارة القواعد',
            'Root Cause': 'تحليل الأسباب الجذرية',
            'Settings': 'الإعدادات',
            'Hospital:': 'المستشفى:',
            'Month:': 'الشهر:',
            'Year:': 'السنة:',
            'All Hospitals': 'كل المستشفيات',
            'All Months': 'كل الأشهر',
            'All Years': 'كل السنوات',
            'All Indicators': 'كل المؤشرات',
            'All': 'الكل',
            'Latest': 'الأحدث',
            'Loading...': 'جاري التحميل...',
            'Loading hospital details...': 'جاري تحميل تفاصيل المستشفى...',
            'Select Hospital': 'اختر المستشفى',
            'Select Month': 'اختر الشهر',
            'Select a hospital': 'اختر مستشفى',
            'Select a month': 'اختر شهر',
            'Run Analysis': 'تشغيل التحليل',
            'Analyze': 'تحليل',
            'Load Trends': 'عرض الاتجاهات',
            'Compare Hospitals': 'مقارنة المستشفيات',
            'Generate Report': 'توليد التقرير',
            'Generate AI Reports': 'توليد تقارير الذكاء الاصطناعي',
            'Generating AI reports': 'توليد تقارير الذكاء الاصطناعي',
            'Generating...': 'جاري التوليد...',
            'Generating report, please wait...': 'جاري توليد التقرير، الرجاء الانتظار...',
            'Select a hospital and month for detailed analysis.': 'اختر مستشفى وشهراً محددين للتحليل التفصيلي.',
            'for all hospitals and all months': 'لكل المستشفيات وكل الأشهر',
            'for all hospitals': 'لكل المستشفيات',
            'for all months of the selected hospital': 'لكل أشهر المستشفى المحدد',
            'May take several minutes on first run; results are cached.': 'قد يستغرق عدة دقائق عند التشغيل الأول؛ النتائج تُخزَّن مؤقتاً.',
            'items': 'عناصر',
            'Open Details': 'فتح التفصيل',
            'Other': 'أخرى',
            'Failed to load details': 'فشل تحميل التفاصيل',
            'Select a hospital and month for detailed analysis, or click Generate AI Reports for a batch.': 'اختر مستشفى وشهراً محددين للتحليل التفصيلي، أو انقر «توليد تقارير الذكاء الاصطناعي» لتوليد دفعة تقارير.',
            'Analyze = detailed classification for one hospital/month · Generate AI Reports = batch AI narrative reports for the selected scope (empty = all).': '«تحليل» = تصنيف تفصيلي لمستشفى/شهر محدد · «توليد تقارير الذكاء الاصطناعي» = تقارير سردية مجمّعة للنطاق المحدد (فارغ = الكل).',
            'Hospitals': 'المستشفيات',
            'Reports': 'التقارير',
            'Avg Quality Score': 'متوسط درجة الجودة',
            'Active Alerts': 'التنبيهات النشطة',
            'Quality Score Trend': 'اتجاه درجة الجودة',
            'Year-over-Year Comparison': 'مقارنة سنة بسنة',
            'Confidence Distribution': 'توزيع الثقة',
            'Quality Components': 'مكونات الجودة',
            'Hospital Comparison': 'مقارنة المستشفيات',
            'Quality Score Heatmap': 'خريطة حرارية لدرجة الجودة',
            'Hospital × Month — darker = higher quality': 'مستشفى × شهر — الأغمق = جودة أعلى',
            'Filter by Month:': 'تصفية بالشهر:',
            'Summary:': 'الملخص:',
            'Quality Score:': 'درجة الجودة:',
            'Confidence:': 'الثقة:',
            'Critical Issues:': 'المشكلات الحرجة:',
            'Priority Actions': 'الإجراءات العاجلة',
            'AI': 'ذ.م',
            'AI Recommendations': 'توصيات الذكاء الاصطناعي',
            'No AI recommendations available': 'لا توجد توصيات ذكاء اصطناعي متاحة',
            'Configure AI provider in Settings → AI Provider tab': 'تكوين مزود الذكاء الاصطناعي في الإعدادات → تبويب AI Provider',
            'Actions:': 'الإجراءات:',
            'Affected:': 'المتأثر:',
            'Rule Failures': 'إخفاقات القواعد',
            'Quality Drivers': 'محركات الجودة',
            'Confidence Gaps': 'فجوات الثقة',
            'Anomaly Patterns': 'أنماط الشذوذ',
            'Failure rate:': 'نسبة الفشل:',
            'Cause:': 'السبب:',
            'Impact:': 'التأثير:',
            'Signal:': 'الإشارة:',
            'pts': 'نقطة',
            'Recurring': 'متكرر',
            'View Full Details': 'عرض التفاصيل الكاملة',
            'Risk:': 'المخاطر:',
            'Assessment:': 'التقييم:',
            'No urgent actions needed.': 'لا توجد إجراءات عاجلة مطلوبة.',
            'No rule failures found.': 'لم يتم العثور على إخفاقات للقواعد.',
            'No data available.': 'لا توجد بيانات متاحة.',
            'No confidence gaps found.': 'لم يتم العثور على فجوات ثقة.',
            'No anomaly patterns found.': 'لم يتم العثور على أنماط شذوذ.',
            'Error:': 'خطأ:',
            'Save All Settings': 'حفظ كل الإعدادات',
            'Reload': 'إعادة تحميل',
            'Re-analyze All': 'إعادة تحليل الكل',
            'Refresh': 'تحديث',
            'Upload Excel File': 'رفع ملف إكسل',
            'Drag & drop or click to browse': 'اسحب وأفلت أو انقر للتصفح',
            '.xlsx, .xls, .csv | Multi-file supported': 'يدعم ملفات متعددة',
            'Preview Before Import': 'معاينة قبل الاستيراد',
            'Confirm & Import': 'تأكيد واستيراد',
            'Cancel': 'إلغاء',
            'Previously Uploaded Files': 'الملفات المرفوعة سابقاً',
            'Loading saved files...': 'جاري تحميل الملفات المحفوظة...',
            'Analyze Selected': 'تحليل المحدد',
            'Delete Selected': 'حذف المحدد',
            'issues': 'مشكلات',
            'outliers': 'شواذ',
            'Read more': 'اقرأ المزيد',

            // Trend Analysis
            'How data quality changes over time': 'كيف تتغير جودة البيانات مع الوقت',
            'Select Hospital:': 'اختر المستشفى:',
            'Select a hospital and click Load Trends.': 'اختر مستشفى ثم انقر "عرض الاتجاهات".',
            'Historical Trend Analysis': 'تحليل الاتجاهات التاريخية',
            'Detects gradual drift, consecutive trends, and significant changes across months.': 'يكشف الانجراف التدريجي والاتجاهات المتتالية والتغييرات الهامة عبر الأشهر.',
            'Indicator': 'المؤشر',
            'Direction': 'الاتجاه',
            'Severity': 'الشدة',
            'Slope %/mo': 'الانحدار %/شهر',
            'CV %': 'معامل الاختلاف %',
            'Last vs Mean': 'آخر قيمة vs المتوسط',
            'Consecutive': 'متتالي',
            'Findings': 'النتائج',
            'Rates Analyzed': 'المعدلات المحللة',
            'Increasing': 'متزايد',
            'Decreasing': 'متناقص',
            'Critical': 'حرج',
            'Attention': 'انتباه',
            'critical': 'حرجة',
            'high-priority recommendations': 'توصيات عالية الأولوية',
            'Critical issues — act first': 'مشاكل حرجة — عالجها أولاً',
            'Trend Outliers': 'القيم الشاذة في الاتجاه',
            'Significant': 'هام',
            'Current Score': 'الدرجة الحالية',
            'Trend': 'الاتجاه',
            'Average': 'المتوسط',
            'Best': 'الأفضل',
            'Worst': 'الأسوأ',
            'HIGH': 'عالٍ',
            'LOW': 'منخفض',
            'vs Last Month': 'مقارنة بالشهر الماضي',
            'Hover over data points for details': 'حرك الماوس فوق النقاط للتفاصيل',

            // Hospital Comparison
            'Cross-Hospital Comparison': 'مقارنة بين المستشفيات',
            'Compare indicators across hospitals for a given month. Identifies significantly above/below average hospitals.': 'مقارنة المؤشرات بين المستشفيات لشهر معين. يحدد المستشفيات الأعلى أو الأدنى من المتوسط.',
            'Select Month:': 'اختر الشهر:',
            'Indicator:': 'المؤشر:',
            'Hospital': 'المستشفى',
            'Value': 'القيمة',
            'Benchmark': 'المعيار',
            'Deviation %': 'الانحراف %',
            'Percentile': 'النسبة المئوية',
            'Assessment': 'التقييم',

            // Clinical Intelligence
            'Clinical Intelligence': 'التحليل السريري',
            'Evidence-based clinical classification, risk analysis, morbidity-mortality correlation, and recommendations driven by WHO/FIGO standards.': 'تصنيف سريري قائم على الأدلة، تحليل المخاطر، ارتباط المراضة والوفيات، وتوصيات وفق معايير WHO/FIGO.',
            'Key Findings': 'النتائج الرئيسية',
            'Clinical Indicators': 'المؤشرات السريرية',
            'Clinical Classifications': 'التصنيفات السريرية',
            'Risk Profile': 'ملف المخاطر',
            'Morbidity-Mortality Assessment': 'تقييم المراضة والوفيات',
            'Recommendations': 'التوصيات',
            'Narrative': 'الوصف',
            'Metric': 'المقياس',
            'Interpretation': 'التفسير',
            'Priority Verification': 'التحقق ذو الأولوية',
            'Level': 'المستوى',
            'MISSING': 'مفقود',

            // Validation table
            'Status:': 'الحالة:',
            'Severity:': 'الشدة:',
            'Type:': 'النوع:',
            'Rule': 'القاعدة',
            'Description': 'الوصف',
            'Status': 'الحالة',
            'Details': 'التفاصيل',
            'Validation Results': 'نتائج التحقق',
            'Anomaly Detection': 'كشف الشذوذ',
            'Rate': 'المعدل',
            'Z-Score': 'درجة Z',
            'Outlier': 'شاذ',
            'Outlier:': 'الشاذ:',
            'Outliers': 'شواذ',
            'Normal': 'طبيعي',
            'YES': 'نعم',
            'No': 'لا',
            'No matching results': 'لا توجد نتائج مطابقة',
            'No data found for the selected criteria.': 'لا توجد بيانات للمعايير المحددة.',

            // Outliers Tab
            'Outlier Analysis': 'تحليل القيم الشاذة',
            'Statistical outliers detected across hospitals and months via Z-score analysis.': 'القيم الشاذة إحصائياً المكتشفة عبر المستشفيات والأشهر باستخدام تحليل درجة Z.',
            'Total Outliers': 'إجمالي الشواذ',
            'Months': 'الأشهر',
            'Avg |Z|': 'متوسط |Z|',
            'No outliers found.': 'لم يتم العثور على شواذ.',

            // Alerts Tab
            'Smart Alert Dashboard': 'لوحة التنبيهات الذكية',
            'Real-time severity overview': 'نظرة عامة فورية على الشدة',
            'All Alerts': 'كل التنبيهات',
            'CRITICAL': 'حرج',
            'HIGH': 'عالي',
            'MEDIUM': 'متوسط',
            'LOW': 'منخفض',
            'Total Alerts': 'إجمالي التنبيهات',
            'Hospitals with Most Critical+High Alerts': 'المستشفيات الأكثر في التنبيهات الحرجة+العالية',
            'Recent Critical Alerts': 'أحدث التنبيهات الحرجة',
            'No critical alerts': 'لا توجد تنبيهات حرجة',
            'No alerts match the current filters.': 'لا توجد تنبيهات تطابق عوامل التصفية الحالية.',

            // Rule Failures Tab
            'Data quality rule violations across hospitals and months.': 'انتهاكات قواعد جودة البيانات عبر المستشفيات والأشهر.',
            'Total Failures': 'إجمالي الإخفاقات',
            'Top Severity': 'أعلى شدة',
            'Unique Rules': 'القواعد الفريدة',
            'No rule failures found.': 'لم يتم العثور على إخفاقات للقواعد.',

            // Indicator Tree
            'Indicator Tree': 'شجرة المؤشرات',
            'Browse indicators hierarchically with values for a selected hospital and month.': 'تصفح المؤشرات هرمياً مع القيم لمستشفى وشهر محددين.',
            'Source:': 'المصدر:',
            'Hardcoded Tree': 'شجرة ثابتة',
            'From DB': 'من قاعدة البيانات',
            'Load Tree': 'تحميل الشجرة',
            'Save Config': 'حفظ الإعدادات',
            'Expand All': 'توسيع الكل',
            'Collapse All': 'طي الكل',
            'branch': 'فرع',
            'Upload data first, then select a hospital and month.': 'ارفع البيانات أولاً، ثم اختر مستشفى وشهر.',
            'No data for heatmap': 'لا توجد بيانات للخريطة الحرارية',
            'View results in Dashboard tab.': 'عرض النتائج في تبويب Dashboard.',
            'Preview ready': 'المعاينة جاهزة',
            'records from': 'سجل من',
            'hospitals across': 'مستشفى عبر',
            'months': 'أشهر',
            'Preview failed': 'فشلت المعاينة',
            'Select a hospital and month': 'اختر مستشفى وشهر',
            'Saving...': 'جاري الحفظ...',
            'Saved!': 'تم الحفظ!',
            'Re-analyze': 'إعادة تحليل',
            'Show less': 'عرض أقل',
            'Executive Summary': 'الملخص التنفيذي',
            'AI Assessment': 'تقييم الذكاء الاصطناعي',

            // Rules Manager
            'Rules Manager': 'إدارة القواعد',
            '60 validation rules — drag to reorder, toggle to enable/disable for analytics control': '60 قاعدة تحقق — اسحب لإعادة الترتيب، بدّل للتمكين/التعطيل للتحكم في التحليل',
            '+ Add Rule': '+ إضافة قاعدة',
            'Code': 'الرمز',
            'Name': 'الاسم',
            'Category': 'الفئة',
            'Expression': 'التعبير',
            'Enabled': 'مفعل',
            'Actions': 'الإجراءات',
            'Edit': 'تعديل',
            'Del': 'حذف',
            'Drag to reorder rules. Disabled rules are skipped during analysis.': 'اسحب لإعادة ترتيب القواعد. القواعد المعطلة يتم تخطيها أثناء التحليل.',
            'Expression Types Reference': 'مرجع أنواع التعبيرات',
            'Click to expand': 'انقر للتوسيع',
            'Click to collapse': 'انقر للطي',
            'Logic': 'المنطق',
            'Required Params': 'المعلمات المطلوبة',
            'Example': 'مثال',
            'Example Params Templates:': 'نماذج المعاملات:',
            'No expression selected': 'لم يتم اختيار تعبير',
            'New Rule': 'قاعدة جديدة',
            'Edit Rule': 'تعديل القاعدة',
            'Rule Type': 'نوع القاعدة',
            'Expression Type': 'نوع التعبير',
            'Params (JSON)': 'المعاملات (JSON)',
            'Code and Name are required.': 'الرمز والاسم مطلوبان.',
            'Save Rule': 'حفظ القاعدة',
            'Delete rule ... This cannot be undone.': 'حذف القاعدة... لا يمكن التراجع عن هذا.',

            // Settings tabs
            'System Settings': 'إعدادات النظام',
            'Quality Score': 'درجة الجودة',
            'Confidence Score': 'درجة الثقة',
            'Thresholds': 'الحدود',
            'Rules': 'القواعد',
            'Clinical': 'السريرية',
            'Risk Profile': 'ملف المخاطر',
            'Trends': 'الاتجاهات',
            'Rate Benchmarks': 'معايير المعدلات',
            'Quality Score Formula Weights': 'أوزان معادلة درجة الجودة',
            'Confidence Signal Weights': 'أوزان إشارات الثقة',
            'Confidence Level Cutoffs': 'حدود مستويات الثقة',
            'Global Z-Score Threshold': 'حد درجة Z العام',
            'Rule Thresholds': 'حدود القواعد',
            'Clinical Indicator Thresholds': 'حدود المؤشرات السريرية',
            'Risk Profile Thresholds': 'حدود ملف المخاطر',
            'Trend Analysis Thresholds': 'حدود تحليل الاتجاهات',
            'Finding Generation': 'توليد النتائج',
            'Rate Benchmarks (Anomaly Detection)': 'معايير المعدلات (كشف الشذوذ)',
            'Save All Settings': 'حفظ كل الإعدادات',

            // Upload
            'Smart Data Entry': 'إدخال البيانات الذكي',
            'Reading file': 'جاري قراءة الملف',
            'Reading file:': 'جاري قراءة الملف:',
            'Processing file...': 'جاري معالجة الملف...',
            'Analysis complete.': 'اكتمل التحليل.',
            'Import failed:': 'فشل الاستيراد:',
            'No saved files found.': 'لم يتم العثور على ملفات محفوظة.',
            'Select at least one file.': 'اختر ملفاً واحداً على الأقل.',
            'Delete ... file(s) from disk? (data in DB will NOT be removed)': 'حذف الملف(ات) من القرص؟ (البيانات في قاعدة البيانات لن تُحذف)',
            'Analyzing ... saved file(s)...': 'جاري تحليل الملف(ات) المحفوظة...',
            'Analysis complete.': 'اكتمل التحليل.',
            'Deleted.': 'تم الحذف.',
            'Delete failed:': 'فشل الحذف:',

            // AI Reports
            'AI Comprehensive Reports': 'تقارير شاملة بالذكاء الاصطناعي',
            'Generate comprehensive reports with AI-powered recommendations for all hospitals.': 'توليد تقارير شاملة بتوصيات مدعومة بالذكاء الاصطناعي لجميع المستشفيات.',
            'Select a specific month or generate for all available months.': 'اختر شهراً محدداً أو توليد لكل الأشهر المتاحة.',
            'Hospitals:': 'المستشفيات:',
            'Months:': 'الأشهر:',
            'Showing:': 'عرض:',
            'Errors:': 'الأخطاء:',
            'Reports:': 'التقارير:',
            'more': 'المزيد',
            'more recommendations': 'المزيد من التوصيات',
            'Completed with errors': 'اكتمل مع أخطاء',
            'Generated reports': 'تم توليد التقارير',
            'Failed to generate report:': 'فشل توليد التقرير:',

            // Root Cause AI
            'AI recommendations not available (configure AI provider in Settings).': 'توصيات الذكاء الاصطناعي غير متاحة (قم بتكوين مزود الذكاء الاصطناعي في الإعدادات).',
            'Root Cause Analysis': 'تحليل الأسباب الجذرية',

            // General status/error
            'No reports match the selected filter.': 'لا توجد تقارير تطابق الفلتر المحدد.',
            'No reports for selected month.': 'لا توجد تقارير للشهر المحدد.',
            'Could not load clinical details for': 'تعذر تحميل التفاصيل السريرية لـ',
            'No clinical data available for': 'لا توجد بيانات سريرية متاحة لـ',
            'No clinical data available. Upload files first.': 'لا توجد بيانات سريرية. ارفع الملفات أولاً.',
            'No data for this hospital/month': 'لا توجد بيانات سريرية لهذا المستشفى/الشهر',
            'Failed to load alerts:': 'فشل تحميل التنبيهات:',
            'Report Coverage': 'تغطية التقارير',
            'High Confidence': 'ثقة عالية',
            'Completeness': 'الاكتمال',
            'Consistency': 'الاتساق',
            'Rule Compliance': 'الامتثال للقواعد',
            'Score': 'الدرجة',
            'target': 'الهدف',
            'Good': 'جيد',
            'Needs Improvement': 'يحتاج تحسيناً',
            'Poor': 'ضعيف',
            'Moderate': 'متوسط',
            'High': 'عالٍ',
            'Low': 'منخفض',
            'Hospitals by risk': 'المستشفيات حسب مستوى الخطر',
            'Critical hospitals': 'المستشفيات الحرجة',
            'High-risk hospitals': 'مستشفيات عالية الخطورة',
            'Data Quality Score': 'درجة جودة البيانات',
            'Overall Confidence': 'الثقة الإجمالية',
            'No data found for the selected criteria.': 'لا توجد بيانات للمعايير المحددة.',
        };

        export function __(text) {
            if (currentLang === 'ar' && translations[text]) return translations[text];
            return text;
        }

        // Build reverse map on first call
        let _rev = null;
        function _getRev() {
            if (!_rev) {
                _rev = {};
                for (const [k, v] of Object.entries(translations)) {
                    _rev[v] = k;
                }
            }
            return _rev;
        }

        export function translateDOM(root) {
            if (!root) root = document.body;
            const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
            const nodesToReplace = [];
            while (walker.nextNode()) {
                const node = walker.currentNode;
                const text = node.textContent.trim();
                if (!text) continue;
                const parent = node.parentElement;
                if (!parent) continue;
                const tag = parent.tagName;
                if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'CANVAS') continue;
                if (parent.tagName === 'INPUT' || parent.tagName === 'SELECT' || parent.tagName === 'TEXTAREA') continue;
                if (/^[\d\s,.%+\-/]+$/.test(text)) continue;
                if (currentLang === 'ar') {
                    if (translations[text]) nodesToReplace.push(node);
                } else {
                    const rev = _getRev();
                    if (rev[text]) nodesToReplace.push({node, key: rev[text]});
                }
            }
            for (const item of nodesToReplace) {
                if (currentLang === 'ar') {
                    item.textContent = translations[item.textContent.trim()] || item.textContent;
                } else {
                    item.node.textContent = item.key;
                }
            }
        }

        export function applyLang(fromToggle) {
            // حافظ على window.currentLang متزامناً مع متغير الوحدة (لقطة app.js لا تتحدث تلقائياً)
            window.currentLang = currentLang;
            const isAr = currentLang === 'ar';
            document.documentElement.lang = isAr ? 'ar' : 'en';
            document.documentElement.dir = isAr ? 'rtl' : 'ltr';
            document.body.classList.toggle('rtl', isAr);
            document.getElementById('langToggle').textContent = isAr ? 'English' : 'العربية';
            localStorage.setItem('lang', currentLang);
            // Translate all data-i18n elements (safely - preserve child elements)
            document.querySelectorAll('[data-i18n]').forEach(el => {
                const trans = __(el.getAttribute('data-i18n'));
                // If element has child elements, only replace the first text node
                if (el.children.length > 0) {
                    const childNodes = el.childNodes;
                    for (let i = 0; i < childNodes.length; i++) {
                        if (childNodes[i].nodeType === Node.TEXT_NODE && childNodes[i].textContent.trim()) {
                            childNodes[i].textContent = trans;
                            break;
                        }
                    }
                } else {
                    el.textContent = trans;
                }
            });
            // Walk DOM for any remaining translatable text nodes
            translateDOM();
        }

        export function toggleLang() {
            currentLang = currentLang === 'ar' ? 'en' : 'ar';
            applyLang();
            const activeTab = document.querySelector('.tab.active');
            if (activeTab) {
                const name = activeTab.getAttribute('data-tab');
                _tabInited.delete(name);
                switchTab(name);
            }
        }

        // Apply lang immediately
        applyLang();

        // Tab switching
