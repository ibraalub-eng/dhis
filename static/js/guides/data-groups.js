// ── Guide: Data Group ────────────────────────────────────────────────────────
import { p, list, steps, table } from '../guide-kit.js';

export default {
    key: 'indicator-groups',
    tab: 'indicator-groups',
    icon: '🗂️',
    title: { en: 'Data Group', ar: 'مجموعة البيانات' },
    menu: { en: 'Data › Data Group', ar: 'البيانات › مجموعة البيانات' },
    permission: 'settings.read',
    shot: 'data-groups.png',
    shotAlt: {
        en: 'Data Group screen with group cards, state badges and per-group actions',
        ar: 'شاشة مجموعة البيانات مع بطاقات المجموعات وشارات الحالة وإجراءات كل مجموعة',
    },
    shotLegend: [
        { en: 'Refresh and New Group buttons', ar: 'زرّا التحديث وإنشاء مجموعة' },
        { en: 'Group card: name, description and range', ar: 'بطاقة المجموعة: الاسم والوصف ونطاق الشهور' },
        { en: 'Scope, state, member count badges', ar: 'شارات النطاق والحالة وعدد الأعضاء' },
        { en: 'Enable/Disable All and Impact (dry run)', ar: 'تفعيل/تعطيل الكل و«الأثر» (تشغيل تجريبي)' },
        { en: 'Members, Edit and Delete', ar: 'الأعضاء والتعديل والحذف' },
        { en: 'Group editor modal with the indicator picker', ar: 'نافذة تحرير المجموعة مع منتقي المؤشرات' },
    ],
    nextSteps: [
        {
            tab: 'indicator-tree',
            label: { en: 'Verify the result in the tree', ar: 'تحقّق من النتيجة في الشجرة' },
            why: {
                en: 'A group toggle writes indicator configuration; Data Tree shows the affected elements as enabled or disabled.',
                ar: 'يكتب تبديل المجموعة إعدادات مؤشرات، وتُظهر شجرة البيانات العناصر المتأثرة كمفعّلة أو معطّلة.',
            },
        },
        {
            tab: 'quality-completeness',
            label: { en: 'Check completeness afterwards', ar: 'راجع الاكتمال بعد ذلك' },
            why: {
                en: 'Disabled indicators leave the completeness calculation, so the score changes after the month is re-analysed.',
                ar: 'تخرج المؤشرات المعطّلة من حساب الاكتمال، فتتغير الدرجة بعد إعادة تحليل الشهر.',
            },
        },
    ],
    sections: {
        overview: [
            p(
                'Data Group is a macro tool: it stores a named set of indicators with a hospital scope and a month range, then applies Enable or Disable to all its members in one operation by writing the same indicator configuration rows the Data Tree edits individually.',
                'مجموعة البيانات أداة إجراءات جماعية: تحفظ مجموعة مسمّاة من المؤشرات مع نطاق مستشفى ونطاق شهور، ثم تطبّق التفعيل أو التعطيل على كل أعضائها في عملية واحدة بكتابة صفوف إعدادات المؤشرات نفسها التي تعدّلها شجرة البيانات فردًا فردًا.',
            ),
            list(
                ['Why it exists: SRMNH forms carry families that are switched on or off together (for example a whole optional block), and doing that by hand for every hospital and month is error-prone.', 'لماذا وُجدت: تحتوي نماذج SRMNH على عائلات تُفعَّل أو تُعطَّل معًا (كتلة اختيارية كاملة مثلًا)، وفعل ذلك يدويًا لكل مستشفى وشهر عرضة للخطأ.'],
                ['Who uses it: administrators and data managers with settings.write; the list itself is readable with settings.read.', 'من يستخدمها: المديرون ومسؤولو البيانات ممن يملكون settings.write، وقائمة المجموعات قابلة للقراءة بصلاحية settings.read.'],
                ['When: when a reporting form changes, when a family of indicators is retired, or when a large group of indicators must be excluded from scoring for a period.', 'متى: عند تغيّر نموذج التقرير، أو إيقاف عائلة مؤشرات، أو استبعاد مجموعة كبيرة من المؤشرات من التقييم لفترة.'],
            ),
        ],
        layout: [
            table(
                [['Area', 'المنطقة'], ['What it contains', 'ما تحتويه']],
                [
                    [['Header', 'الترويسة'], ['Refresh and New Group; New Group is hidden without settings.write.', 'تحديث وإنشاء مجموعة، ويُخفى إنشاء مجموعة بدون settings.write.']],
                    [['Notice strip', 'شريط الإشعار'], ['Explains what the next toggle will cover, for example when no month range is set.', 'يوضّح ما سيغطيه التبديل التالي، مثلًا عند عدم تحديد نطاق شهور.']],
                    [['Group card', 'بطاقة المجموعة'], ['Name and id, description, scope badge (all hospitals or one hospital), state badge, month range, member count, and the action buttons.', 'الاسم والمعرّف والوصف وشارة النطاق (كل المستشفيات أو مستشفى واحد) وشارة الحالة ونطاق الشهور وعدد الأعضاء وأزرار الإجراءات.']],
                    [['Empty state', 'الحالة الفارغة'], ['Shown when no group exists, with a shortcut to create the first one.', 'تظهر عند عدم وجود مجموعات، مع اختصار لإنشاء الأولى.']],
                    [['Group editor modal', 'نافذة تحرير المجموعة'], ['Name, description, scope, hospital, month range, and the indicator picker with search and bulk selection.', 'الاسم والوصف والنطاق والمستشفى ونطاق الشهور ومنتقي المؤشرات مع البحث والتحديد الجماعي.']],
                    [['Members modal', 'نافذة الأعضاء'], ['Current members with remove/move controls, plus a picker to add more.', 'الأعضاء الحاليون مع أزرار الإزالة والنقل، ومنتقي لإضافة المزيد.']],
                    [['Impact preview modal', 'نافذة معاينة الأثر'], ['Dry run of what Enable/Disable All would change, without writing anything.', 'تشغيل تجريبي لما سيغيّره التفعيل/التعطيل الكلي دون كتابة أي شيء.']],
                ],
            ),
        ],
        usage: [
            steps(
                ['Open Data › Data Group. Existing groups are listed as cards.', 'افتح البيانات › مجموعة البيانات، وتظهر المجموعات كبطاقات.'],
                ['To create one, press New Group: enter a name (required), an optional description, the scope, and optionally a month range.', 'لإنشاء مجموعة اضغط «مجموعة جديدة» وأدخل اسمًا (مطلوبًا) ووصفًا اختياريًا والنطاق ونطاق شهور اختياريًا.'],
                ['Pick the members from the indicator tree in the modal. Search narrows the tree; Select visible and Clear work on the filtered set.', 'اختر الأعضاء من شجرة المؤشرات داخل النافذة. يضيّق البحث الشجرة، ويعمل «تحديد الظاهر» و«تفريغ» على المجموعة المصفّاة.'],
                ['Press Save Group. The card shows the member count and the resulting state.', 'اضغط «حفظ المجموعة»، وتُظهر البطاقة عدد الأعضاء والحالة الناتجة.'],
                ['Before toggling, press Impact to see a dry run: which indicators, hospitals and months would change, and how many rows would be written.', 'قبل التبديل اضغط «الأثر» لترى تشغيلًا تجريبيًا: أي مؤشرات ومستشفيات وشهور ستتغير وكم صفًا سيُكتب.'],
                ['Press Enable All or Disable All — the label is always the action that flips the current state. The card and the toast report the result.', 'اضغط «تفعيل الكل» أو «تعطيل الكل»، ويكون الزر دائمًا هو الإجراء الذي يعكس الحالة الحالية، وتُبلغ البطاقة والتنبيه بالنتيجة.'],
                ['To fine-tune later, use Members (add, remove, reorder) or Edit (name, description, scope, range).', 'للضبط لاحقًا استخدم «الأعضاء» (إضافة وإزالة وترتيب) أو «تعديل» (الاسم والوصف والنطاق والمدى).'],
            ),
        ],
        fields: [
            table(
                [['Field', 'الحقل'], ['Meaning', 'المعنى'], ['Required?', 'مطلوب؟'], ['Values and effect', 'القيم والأثر']],
                [
                    [['Name', 'الاسم'], ['The label shown on the card.', 'التسمية الظاهرة على البطاقة.'], ['Yes', 'نعم'], ['Free text; used only for identification.', 'نص حر للتعريف فقط.']],
                    [['Description', 'الوصف'], ['What the group is for.', 'الغرض من المجموعة.'], ['No', 'لا'], ['Free text shown under the name.', 'نص حر يظهر تحت الاسم.']],
                    [['Scope', 'النطاق'], ['Which hospitals the toggle applies to.', 'المستشفيات التي يسري عليها التبديل.'], ['Yes', 'نعم'], ['All hospitals, or a single hospital chosen from the selector.', 'كل المستشفيات أو مستشفى واحد يُختار من القائمة.']],
                    [['Month From / Month To', 'من شهر / إلى شهر'], ['Limits the toggle to a month range.', 'يحصر التبديل في نطاق شهور.'], ['No', 'لا'], ['Empty means every known month; Clear removes both ends. From must not be after To.', 'الفراغ يعني كل الشهور المعروفة، و«تفريغ» يزيل الطرفين، ولا يجوز أن يكون البداية بعد النهاية.']],
                    [['Members', 'الأعضاء'], ['The indicators the group toggles.', 'المؤشرات التي تبدّلها المجموعة.'], ['Yes (at least one)', 'نعم (واحد على الأقل)'], ['Selected from the indicator tree; a group with zero members refuses to toggle.', 'تُختار من شجرة المؤشرات، وترفض المجموعة الفارغة التبديل.']],
                ],
            ),
        ],
        actions: [
            table(
                [['Action', 'الإجراء'], ['What it does', 'ما يفعله'], ['Writes data?', 'يعدّل البيانات؟'], ['When to use / prerequisites', 'متى يُستخدم / المتطلبات']],
                [
                    [['Enable All / Disable All', 'تفعيل الكل / تعطيل الكل'], ['Writes the indicator configuration for every member across the scope and range.', 'يكتب إعداد المؤشرات لكل عضو عبر النطاق والمدى.'], ['Yes — configuration', 'نعم — إعدادات'], ['settings.write; at least one member; run Impact first when the range is wide.', 'يتطلب settings.write وعضوًا واحدًا على الأقل، وشغّل «الأثر» أولًا إن كان المدى واسعًا.']],
                    [['Impact', 'الأثر'], ['Dry run: what the toggle would change, and how many configuration rows.', 'تشغيل تجريبي لما سيغيّره التبديل وعدد صفوف الإعدادات.'], ['No', 'لا'], ['Before any bulk toggle, especially with no month range.', 'قبل أي تبديل جماعي، خصوصًا بلا نطاق شهور.']],
                    [['Members', 'الأعضاء'], ['Opens the member list; add, remove or reorder indicators.', 'يفتح قائمة الأعضاء لإضافة المؤشرات أو إزالتها أو ترتيبها.'], ['Yes — group definition', 'نعم — تعريف المجموعة'], ['settings.write for changes.', 'يتطلب settings.write للتغييرات.']],
                    [['Edit / Delete', 'تعديل / حذف'], ['Updates the group definition, or deletes the group itself.', 'يحدّث تعريف المجموعة أو يحذف المجموعة نفسها.'], ['Yes — group definition', 'نعم — تعريف المجموعة'], ['Delete removes the group only; configuration it already wrote stays as it is.', 'الحذف يزيل المجموعة فقط، ويبقى الإعداد الذي كتبته كما هو.']],
                    [['Refresh', 'تحديث'], ['Reloads groups from the server.', 'يعيد تحميل المجموعات من الخادم.'], ['No', 'لا'], ['After another administrator changed a group.', 'بعد أن يغيّر مسؤول آخر مجموعة.']],
                ],
            ),
        ],
        results: [
            p(
                'A group is a macro, not a live filter: the system never consults groups when it reads data. What matters afterwards is the indicator configuration the toggle wrote — the same rows the Data Tree edits — and the badges on the card reflect it.',
                'المجموعة إجراء جماعي وليست مرشّحًا حيًّا: لا يرجع النظام إلى المجموعات عند قراءة البيانات. المهم بعد التنفيذ هو إعداد المؤشرات الذي كتبه التبديل — وهي الصفوف نفسها التي تعدّلها شجرة البيانات — وتعكسها الشارات على البطاقة.',
            ),
            list(
                ['The state badge (Enabled/Disabled) describes the group’s last operation, not a guarantee that every member has the same state in every month.', 'تصف شارة الحالة (مفعّلة/معطّلة) آخر عملية على المجموعة، ولا تضمن أن كل عضو في الحالة نفسها في كل شهر.'],
                ['Disabling indicators removes them from validation and from the completeness denominator; that effect appears in the scores of the months actually covered.', 'تعطيل المؤشرات يستبعدها من التحقق ومن مقام الاكتمال، ويظهر الأثر في درجات الشهور المشمولة فعليًا.'],
                ['A group does not re-run analysis by itself; months that were already analysed keep their stored results until they are re-analysed.', 'المجموعة لا تعيد التحليل بنفسها، وتحتفظ الشهور المحلَّلة سابقًا بنتائجها المخزّنة حتى يُعاد تحليلها.'],
            ),
        ],
        examples: [
            p(
                'A new form removes the optional NICU block. The administrator creates “NICU block” with all hospitals, no month range, picks its indicators, runs Impact to see the number of rows and months, then presses Disable All. Data Tree now shows those elements disabled, and the next month’s completeness excludes them.',
                'يحذف نموذج جديد كتلة الحاضنة الاختيارية. ينشئ المسؤول مجموعة «كتلة الحاضنة» لكل المستشفيات بلا نطاق شهور ويختار مؤشراتها ويشغّل «الأثر» ليرى عدد الصفوف والشهور ثم يضغط «تعطيل الكل». تُظهر شجرة البيانات تلك العناصر معطّلة، ويستبعدها اكتمال الشهر التالي.',
            ),
            p(
                'For one hospital that does not provide a service, the administrator creates the same family with scope “Single hospital” and that hospital only, so the exclusion does not affect the network.',
                'لمستشفى واحد لا يقدّم خدمة معينة ينشئ المسؤول العائلة نفسها بنطاق «مستشفى واحد» لتلك المستشفى فقط، فلا يؤثر الاستبعاد على الشبكة.',
            ),
        ],
        problems: [
            table(
                [['Problem', 'المشكلة'], ['Cause', 'السبب'], ['Resolution', 'الحل']],
                [
                    [['“Group has no members”', '«المجموعة بلا أعضاء»'], ['The group was saved without selecting indicators.', 'حُفظت المجموعة دون اختيار مؤشرات.'], ['Open Members (or Edit) and add indicators, then toggle.', 'افتح الأعضاء أو التعديل وأضف مؤشرات ثم بدّل.']],
                    [['The toggle changed more months than intended', 'غيّر التبديل شهورًا أكثر من المقصود'], ['No month range was set, so it applied to every known month.', 'لم يُحدَّد نطاق شهور فطُبِّق على كل الشهور المعروفة.'], ['Set From/To in Edit, or fix the affected months in Data Tree; use Impact before toggling.', 'حدّد «من/إلى» في التعديل أو صحّح الشهور المتأثرة في شجرة البيانات، واستخدم «الأثر» قبل التبديل.']],
                    [['Buttons are missing or disabled', 'أزرار مفقودة أو معطّلة'], ['settings.write is not granted to the account.', 'الصلاحية settings.write غير ممنوحة للحساب.'], ['Ask an administrator; the list stays readable with settings.read.', 'اطلبها من المسؤول، وتبقى القائمة مقروءة بصلاحية settings.read.']],
                    [['Scores did not change after a toggle', 'لم تتغير الدرجات بعد التبديل'], ['Existing months were not re-analysed.', 'لم يُعَد تحليل الشهور الموجودة.'], ['Re-analyze the affected month (Upload Data › Analyze on the saved file) or ask an administrator.', 'أعد تحليل الشهر المتأثر من رفع البيانات › تحليل على الملف المحفوظ أو اطلب ذلك من المسؤول.']],
                ],
            ),
        ],
        related: [
            table(
                [['Screen', 'الشاشة'], ['Relationship', 'العلاقة']],
                [
                    [['Data Tree', 'شجرة البيانات'], ['Per-hospital, per-month view of the configuration a group writes.', 'عرض الإعداد الذي تكتبه المجموعة لكل مستشفى وشهر.']],
                    [['Indicators', 'المؤشرات'], ['Catalog and definitions of the members.', 'كتالوج الأعضاء وتعريفاتها.']],
                    [['Validation Rules', 'قواعد التحقق'], ['Disabled indicators stop being validated, so rule impact shrinks.', 'تتوقف المؤشرات المعطّلة عن التحقق فيتراجع أثر القواعد.']],
                    [['Completeness', 'الاكتمال'], ['The component that reacts most directly to disabling indicators.', 'المكوّن الأكثر تأثرًا بتعطيل المؤشرات.']],
                ],
            ),
        ],
    },
};
