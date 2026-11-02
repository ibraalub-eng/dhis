/**
 * Dynamic Explain prose — structured message templates (EN / AR).
 *
 * The backend composes its explanations in English (app/engine/audit/explain.py,
 * layered classification, Quality Alerts cross-check). Translating those
 * strings word by word in the browser would be fragile and could silently
 * change an analytical meaning, so each STABLE sentence shape is registered
 * here as a message: a key, a regex that binds its parameters, and one
 * rendering per language. Everything else falls through untouched.
 *
 * Rules of the registry:
 *   - a matcher binds PARAMETERS only; it never rewrites words in place;
 *   - parameters holding analytical identifiers (bands, types, reason codes)
 *     are rendered through the caller's label function, so they use the same
 *     vocabulary as the rest of the popup;
 *   - numbers, percentages, units, hospital and indicator names are copied
 *     verbatim — the template only decides where they sit in the sentence;
 *   - an unregistered sentence is never translated: it is returned unchanged
 *     and only the machine identifiers it carries are made readable by the
 *     caller's optional ``humanize`` hook;
 *   - a composed paragraph is split into sentences and each sentence into its
 *     '; '-separated clauses, so one unregistered clause can neither leave the
 *     rest of the paragraph in English nor leak a raw code into it.
 *
 * Presentation only: no payload field is read differently, no value is
 * recomputed, and the renderer never invents a parameter the backend did not
 * send.
 */

const MESSAGES = {
    // ── detection layer names ────────────────────────────────────────────
    'layer.name.raw': ['Raw value', 'القيمة الخام'],
    'layer.name.rate': ['Rate', 'المعدل'],
    'layer.name.historical': ['Historical baseline', 'الأساس التاريخي'],
    'layer.name.volume': ['Patient volume', 'حجم المرضى'],
    'layer.name.peer': ['Peer comparison', 'المقارنة مع النظير'],

    // ── layered outlier: headline ────────────────────────────────────────
    'layered.what.change': [
        '{name} {value} vs {previous} previous ({change}) — {type} ({level} level)',
        '{name}: {value} مقابل {previous} في القياس السابق ({change}) — {type} ({level})',
    ],
    'layered.what.plain': [
        '{name} — {type} ({level} level)',
        '{name} — {type} ({level})',
    ],

    // ── layered outlier: why ─────────────────────────────────────────────
    'layered.why.rule': [
        'Rule {rule} of the layered rule table fired → {type}.',
        'انطبقت القاعدة {rule} من جدول قواعد الطبقات ← {type}.',
    ],
    'layered.why.stale': [
        'The stored classification no longer matches the current history (recomputed: {type}) — recalculate this month.',
        'لم يعد التصنيف المخزَّن مطابقاً للتاريخ الحالي (أُعيد حسابه: {type}) — أعد حساب هذا الشهر.',
    ],
    'layered.why.stored': [
        'Stored interpretation: {text}',
        'التفسير المخزَّن: {text}',
    ],
    'layered.stale.policy': [
        'Under the current classification policy this row recomputes to {type} {level} (stored: {stype} {slevel}) — recalculate this month.',
        'بموجب سياسة التصنيف الحالية يُعاد حساب هذا الصف إلى {type} {level} (المخزَّن: {stype} {slevel}) — أعد حساب هذا الشهر.',
    ],

    // ── layered outlier: layer details ───────────────────────────────────
    'layered.layer.raw': [
        "this month's analysis value vs its own recent distribution",
        'قيمة هذا الشهر التحليلية مقابل توزيعها الحديث',
    ],
    'layered.layer.rate': [
        'rate vs its own recent distribution',
        'المعدل مقابل توزيعه الحديث',
    ],
    'layered.layer.rate.count': [
        'count indicators have no separate rate layer',
        'المؤشرات العددية ليس لها طبقة معدل منفصلة',
    ],
    'layered.layer.history': [
        '{valid} valid prior months against a {min}-observation minimum',
        '{valid} شهراً سابقاً صالحاً مقابل حد أدنى مقداره {min} مشاهدة',
    ],
    'layered.layer.volume': [
        'denominator change guards against volume-driven spikes',
        'يقي تغيّر المقام من الارتفاعات الناتجة عن حجم البيانات',
    ],
    'layered.layer.volume.count': [
        'count indicators have no denominator layer',
        'المؤشرات العددية ليس لها طبقة مقام',
    ],
    'layered.layer.peer': [
        'every hospital reporting the indicator this month (≥ 2 others), self excluded',
        'كل مستشفى أبلغ عن المؤشر هذا الشهر (≥ 2 آخران على الأقل) باستثناء المستشفى نفسه',
    ],
    'layered.layer.peer.thin': [
        'Fewer than {min} peer hospitals cannot measure a spread, so no z-score is produced for this comparison',
        'أقل من {min} مستشفى نظير لا يكفي لقياس التباين، لذا لا تُحتسب درجة z لهذه المقارنة',
    ],

    // ── layered outlier: layer values ────────────────────────────────────
    'layered.value.none': ['not computable', 'غير قابل للحساب'],
    'layered.value.change': [
        '{value} (previous {previous}, {change})',
        '{value} (سابقاً {previous}، {change})',
    ],
    'layered.value.count': [
        'not applicable (count indicator)',
        'لا ينطبق (مؤشر عددي)',
    ],
    'layered.value.denominator': [
        'not computable (denominator missing or zero)',
        'غير قابل للحساب (المقام مفقود أو صفر)',
    ],
    'layered.value.insufficient': ['insufficient history', 'التاريخ غير كافٍ'],
    'layered.value.history.change': [
        '{change} vs baseline mean {mean}',
        '{change} مقابل متوسط الأساس {mean}',
    ],
    'layered.value.peer': [
        '{mean} across {peer} peer hospitals',
        '{mean} عبر {peer} مستشفى نظير',
    ],
    'layered.value.peer.none': [
        'not computable (fewer than 2 hospitals reported it)',
        'غير قابل للحساب (أقل من 2 مستشفى أبلغ عنه)',
    ],

    // ── layered outlier: reproduction ────────────────────────────────────
    'layered.reproduce.ok': [
        'Stored layer scores and the current history reproduce the stored classification.',
        'درجات الطبقات المخزَّنة والتاريخ الحالي يعيدان إنتاج التصنيف المخزَّن.',
    ],
    'layered.reproduce.stale': [
        'Re-running the rule table over the stored scores with the CURRENT history gives a different result — the history changed since this row was written; recalculate this month.',
        'إعادة تشغيل جدول القواعد على الدرجات المخزَّنة بالتاريخ الحالي تعطي نتيجة مختلفة — تغيّر التاريخ منذ كتابة هذا الصف؛ أعد حساب هذا الشهر.',
    ],
    'layered.chain.layers': [
        'raw → rate/volume → historical → peer (recorded method: {method})',
        'خام → معدل/حجم → تاريخي → نظير (الطريقة المسجّلة: {method})',
    ],
    'layered.chain.classification': [
        'Rule {rule}: {type} at {level}, route {route}',
        'القاعدة {rule}: {type} عند {level}، المسار {route}',
    ],

    // ── anomaly ──────────────────────────────────────────────────────────
    'anomaly.what.outlier': [
        '{rate} is an outlier: value {value} vs benchmark {benchmark} (z={z})',
        '{rate} قيمة شاذة: القيمة {value} مقابل المرجع {benchmark} (z={z})',
    ],
    'anomaly.what.normal': [
        '{rate} is within normal range: value {value} vs benchmark {benchmark} (z={z})',
        '{rate} ضمن النطاق الطبيعي: القيمة {value} مقابل المرجع {benchmark} (z={z})',
    ],
    'anomaly.why.exceeds': [
        '|z| = {z} exceeds the {threshold} threshold → flagged as outlier (rate {direction} the benchmark)',
        '|z| = {z} يتجاوز الحد {threshold} ← صُنِّف كقيمة شاذة (المعدل {direction} المرجع)',
    ],
    'anomaly.why.pipeline': [
        'Flagged by the anomaly detection pipeline (trend/regression rule) with z={z}, threshold {threshold}',
        'صُنِّف بواسطة محرك كشف الشذوذ (قاعدة الاتجاه/الانحدار) عند z={z} والحد {threshold}',
    ],
    'anomaly.why.within': [
        '|z| = {z} is within the {threshold} threshold → not an outlier',
        '|z| = {z} ضمن الحد {threshold} ← ليس قيمة شاذة',
    ],
    'anomaly.chain.validation': [
        'Zero-denominator and range checks run before rate computation',
        'تُنفَّذ فحوص المقام الصفري والنطاق قبل حساب المعدل',
    ],
    'anomaly.chain.finding': [
        'Anomaly row #{id} (outlier={flag})',
        'صف الشذوذ رقم #{id} (شاذ={flag})',
    ],
    'anomaly.reproduce.missing': [
        'Raw numerator/denominator missing — rate cannot be reproduced from stored values',
        'البسط أو المقام الخام مفقود — لا يمكن إعادة إنتاج المعدل من القيم المخزَّنة',
    ],
    'anomaly.reproduce.ok': [
        'Benchmark recomputed and matches the current data.',
        'أُعيد حساب المرجع وهو مطابق للبيانات الحالية.',
    ],
    'anomaly.reproduce.stale': [
        'Benchmark could not be reproduced from the current data.',
        'تعذّرت إعادة إنتاج المرجع من البيانات الحالية.',
    ],

    // ── data-problem messages ────────────────────────────────────────────
    'problem.missing': [
        'Indicator {code} ({name}) has no value for this month',
        'المؤشر {code} ({name}) لا قيمة له في هذا الشهر',
    ],
    'problem.missing.noname': [
        'Indicator {code} has no value for this month',
        'المؤشر {code} لا قيمة له في هذا الشهر',
    ],
    'problem.negative': [
        'Indicator {code} ({name}) has a negative value ({value})',
        'المؤشر {code} ({name}) له قيمة سالبة ({value})',
    ],
    'problem.negative.noname': [
        'Indicator {code} has a negative value ({value})',
        'المؤشر {code} له قيمة سالبة ({value})',
    ],
    'problem.duplicate': [
        "Indicator {code} ({name}) = {value} from '{source}' appears {n} times (uploaded more than once)",
        "المؤشر {code} ({name}) = {value} من '{source}' يتكرر {n} مرات (رُفع أكثر من مرة)",
    ],
    'problem.duplicate.noname': [
        "Indicator {code} = {value} from '{source}' appears {n} times (uploaded more than once)",
        "المؤشر {code} = {value} من '{source}' يتكرر {n} مرات (رُفع أكثر من مرة)",
    ],
    'problem.thin_peers': [
        'Only {n} peer hospital(s) — the benchmark is statistically fragile',
        '{n} مستشفى نظير فقط — المرجع هش إحصائياً',
    ],
    'problem.stale_benchmark': [
        'The stored benchmark ({benchmark}, z={z}) no longer matches the uploaded data: recomputing {rate} over the same population gives {recomputed} (z={recomputedZ}). The anomaly row is out of date with the current values or indicator configuration — recalculate this month.',
        'لم يعد المرجع المخزَّن ({benchmark}، z={z}) مطابقاً للبيانات المرفوعة: إعادة حساب {rate} على السكان أنفسهم تعطي {recomputed} (z={recomputedZ}). صف الشذوذ لم يعد مواكباً للقيم أو لإعدادات المؤشر الحالية — أعد حساب هذا الشهر.',
    ],

    // ── quality score ────────────────────────────────────────────────────
    'score.what.mix': [
        'Data quality score {score} for {month} — weighted mix of rule compliance, completeness, consistency and outlier score',
        'درجة جودة البيانات {score} لشهر {month} — مزيج مرجّح من الالتزام بالقواعد والاكتمال والاتساق ودرجة الشذوذ',
    ],
    'score.what.outlier': [
        'Outlier score {score} for {month} — 100 minus the penalty from {n} indicator(s) at High/Very high',
        'درجة الشذوذ {score} لشهر {month} — 100 ناقص العقوبة الناتجة عن {n} مؤشراً عند المستوى المرتفع أو المرتفع جدًا',
    ],
    'score.what.ghost': [
        'This month has a score row but no raw data behind it (never analyzed or data was removed). The score is a placeholder, not a performance result.',
        'لهذا الشهر صف درجة دون بيانات خام خلفه (لم يُحلَّل قط أو أُزيلت بياناته). الدرجة عنصر نائب وليست نتيجة أداء.',
    ],
    // Time Periods row: the same stored score, but the backend REPLACES the
    // quality-score headline with the month-over-month change the column shows
    // (explain_time_period_point). Numbers, month and the previous month are
    // the backend's own tokens — only their position in the sentence changes.
    'score.what.period': [
        'Quality score {score} for {month} ({change} vs {previous})',
        'درجة الجودة {score} لشهر {month} ({change} مقابل {previous})',
    ],
    'score.what.period.none': [
        'Quality score {score} for {month} (no earlier analyzed month to compare)',
        'درجة الجودة {score} لشهر {month} (لا يوجد شهر مُحلَّل سابق للمقارنة)',
    ],
    'score.why.below': [
        '{n} component(s) below target; weakest: {component} ({value}% vs {target}% target).',
        '{n} مكوّن دون الهدف؛ الأضعف: {component} ({value}% مقابل هدف {target}%).',
    ],
    'score.why.rules': [
        '{n} validation rule(s) failed ({codes}{more}) → rule compliance {compliance}%',
        'فشلت {n} قاعدة تحقق ({codes}{more}) ← الالتزام بالقواعد {compliance}%',
    ],
    'score.why.no_rules': [
        'No validation rule failed this month',
        'لم تفشل أي قاعدة تحقق هذا الشهر',
    ],
    'score.why.all_with_rules': [
        'All components meet their targets ({sentence})',
        'كل المكوّنات تحقق أهدافها ({sentence})',
    ],
    'score.why.all': [
        'All components meet their targets — the score reflects good data quality',
        'كل المكوّنات تحقق أهدافها — الدرجة تعكس جودة بيانات سليمة',
    ],
    'score.why.problems': [
        '{n} raw-data problem(s) detected;',
        'رُصدت {n} مشكلة في البيانات الخام؛',
    ],
    'score.why.outlier_drivers': [
        'Outlier score {score}% = 100 - {penalty} penalty, from {n} indicator(s) at High/Very high: {list}{more}',
        'درجة الشذوذ {score}% = 100 - عقوبة {penalty}، ناتجة عن {n} مؤشراً عند المستوى المرتفع أو المرتفع جدًا: {list}{more}',
    ],
    'score.why.outlier_none': [
        'No indicator reached High or Very high this month — outlier score {score}% (penalty {penalty}).',
        'لم يبلغ أي مؤشر المستوى المرتفع أو المرتفع جدًا هذا الشهر — درجة الشذوذ {score}% (العقوبة {penalty}).',
    ],
    'score.why.outlier_none.tail': [
        'Missing cells are counted under completeness, not here',
        'تُحتسب الخلايا المفقودة ضمن الاكتمال لا هنا',
    ],
    'score.why.more': ['+{n} more', '+{n} أخرى'],

    // ── Quality Alerts cross-check ───────────────────────────────────────
    'cc.no_alert': [
        'No active Quality Alert is stored for this formula and month, so there is no second verdict to compare with.',
        'لا يوجد تنبيه جودة نشط مخزَّن لهذه المعادلة وهذا الشهر، لذا لا حكم ثانٍ للمقارنة معه.',
    ],
    'cc.no_alert.tail': [
        'Re-scan the month if an alert was expected.',
        'أعد فحص الشهر إذا كان التنبيه متوقعاً.',
    ],
    'cc.stratified': [
        'Quality Alerts reports {severity} under "{label}" (n={peers}), a narrower stratified comparison.',
        'تنبيهات الجودة تُبلغ {severity} ضمن "{label}" (العدد {peers})، وهي مقارنة طبقية أضيق.',
    ],
    'cc.stratified.diag': [
        'Outlier Diagnostics classifies this row {type} at {level} against the single all-hospital detection baseline (peer score {peerScore} / {peerLevel}), and {history}',
        'تشخيص القيم الشاذة يصنّف هذا الصف {type} عند {level} مقابل خط الأساس الوحيد لجميع المستشفيات (درجة النظير {peerScore} / {peerLevel})، و{history}',
    ],
    'cc.history.not_assessable': [
        "the hospital's own history is not assessable.",
        'تاريخ المستشفى نفسه غير قابل للتقييم.',
    ],
    'cc.history.not_assessed': [
        "the hospital's own history could not be assessed either.",
        'وتعذّر تقييم تاريخ المستشفى نفسه أيضاً.',
    ],
    'cc.history.within': [
        'its own history stayed within its band.',
        'وبقي تاريخه ضمن نطاقه.',
    ],
    'cc.history_more_severe': [
        'The stored history-perspective alert is more severe than this diagnostic row although both use the same history baseline; recalculate the month before relying on either.',
        'تنبيه منظور التاريخ المخزَّن أشد من صف التشخيص هذا رغم أن كليهما يستخدم خط الأساس التاريخي نفسه؛ أعد حساب الشهر قبل الاعتماد على أي منهما.',
    ],
    'cc.severity_more_severe': [
        'The stored alert ({severity}, "{label}") is more severe than this diagnostic row ({level}) under the same detection baseline, so the two stored results disagree.',
        'التنبيه المخزَّن ({severity}، "{label}") أشد من صف التشخيص هذا ({level}) على خط الأساس نفسه، لذا تختلف النتيجتان المخزَّنتان.',
    ],
    'cc.recalc': [
        'Recalculate this month to reconcile them.',
        'أعد حساب هذا الشهر للتوفيق بينهما.',
    ],
    'cc.agree': [
        'Quality Alerts and Outlier Diagnostics agree: the most severe stored alert ({severity}, "{label}") is consistent with this diagnostic level ({level}).',
        'تنبيهات الجودة وتشخيص القيم الشاذة متفقان: أشد تنبيه مخزَّن ({severity}، "{label}") متسق مع مستوى التشخيص هذا ({level}).',
    ],
    'cc.closed_note': [
        'The matching Quality Alert was closed by a reviewer (Resolved / skipped as False Positive), so it no longer raises on the Quality Alerts screen; closing records the investigation decision and changes neither detection result.',
        'أُغلق تنبيه الجودة المطابق بواسطة مراجع (مُعالَج / تم تجاوزه كإيجابية كاذبة)، لذا لم يعد يظهر على شاشة تنبيهات الجودة؛ الإغلاق يسجل قرار التحقيق ولا يغيّر أي نتيجة كشف.',
    ],
    'cc.policy_band': [
        'The stored alert was written {stored}, but the approved cap policy assigns it {severity} ("{label}"): {reasons}.',
        'كُتب التنبيه المخزَّن عند {stored}، لكن سياسة السقف المعتمدة تمنحه {severity} ("{label}"): {reasons}.',
    ],
    'cc.policy_band.tail': [
        'Quality Alerts shows that policy band while Outlier Diagnostics classifies the peer layer without the cap ({type} at {level}).',
        'تعرض تنبيهات الجودة نطاق السياسة هذا بينما يصنّف تشخيص القيم الشاذة طبقة النظير دون السقف ({type} عند {level}).',
    ],
    'cc.policy_band.stored': [
        'The stored row keeps {stored} until the month is re-scanned.',
        'يحتفظ الصف المخزَّن بـ {stored} حتى يُعاد فحص الشهر.',
    ],
    'cc.reason.dispersion': [
        'every hospital in that comparison reported the same value, so the deviation has no measurable scale',
        'كل المستشفيات في تلك المقارنة أبلغت القيمة نفسها، لذا لا مقياس قابلاً للقياس للانحراف',
    ],
    'cc.reason.thin': [
        'the comparison group holds {peers} other hospital(s) and measuring a spread needs at least {min}, so its z-score is not a measurement',
        'مجموعة المقارنة تضم {peers} مستشفى آخر وقياس التباين يحتاج {min} على الأقل، لذا فدرجة z ليست قياساً',
    ],
    'cc.reason.window': [
        "the hospital's own history window does not support the top band (the same window's dispersion-aware band is {band})",
        'نافذة تاريخ المستشفى نفسه لا تدعم المستوى الأعلى (النطاق الواعي بالتباين للنافذة نفسها هو {band})',
    ],
    'cc.older_policy': [
        'The stored alert ({severity}, "{label}") is consistent with the stored diagnostic row, but that row was written under an older classification policy.',
        'التنبيه المخزَّن ({severity}، "{label}") متسق مع صف التشخيص المخزَّن، لكن ذلك الصف كُتب بموجب سياسة تصنيف أقدم.',
    ],

    // ── rule explanations ────────────────────────────────────────────────
    'score.why.problems.clause': [
        '{n} raw-data problem(s) detected',
        'رُصدت {n} مشكلة في البيانات الخام',
    ],
    'score.why.below.n': [
        '{n} component(s) below target',
        '{n} مكوّن دون الهدف',
    ],
    'score.why.weakest': [
        'weakest: {component} ({value}% vs {target}% target)',
        'الأضعف: {component} ({value}% مقابل هدف {target}%)',
    ],

    // ── read-only formula line ───────────────────────────────────────────
    // Only the EXPLANATORY connector is translated: the indicator's own name,
    // its code and every operator stay exactly as the backend wrote them, so a
    // reader can still recognise the stored formula. Mathematical shapes
    // (proportions) are deliberately unregistered and stay verbatim.
    'how.formula.count': [
        '{name} = count of indicator {code}',
        '{name} = عدد المؤشر {code}',
    ],

    // ── row headlines: Compare (comparison_row) and Trend Analysis ───────
    // ``label`` is the comparison engine's closed label set (normal / above
    // average / significantly …), ``direction`` and ``severity`` are the trend
    // engine's words; all three travel through the shared label function, so a
    // known word is translated and an unknown one stays readable instead of
    // being guessed. Rate name, hospital, month and every number stay verbatim.
    'comparison.what': [
        '{rate} for {hospital} in {month}: {value} vs peer benchmark {benchmark} ({label})',
        '{rate} للمستشفى {hospital} في {month}: {value} مقابل المعيار المرجعي {benchmark} ({label})',
    ],
    'trend.what': [
        '{rate} trend for {hospital}: {direction} ({severity}), slope {slope}%/mo over {months} months',
        '{rate} — اتجاه المستشفى {hospital}: {direction} ({severity})، الانحدار {slope}%/شهر على مدى {months} أشهر',
    ],

    // Trend row's `why`: "slope -3.60%/mo → direction 'decreasing' (stable band
    // ±5.0%); severity 'low'; 2 consecutive decreasing months; last vs mean
    // -17.9%; CV 14.5%". Two shapes, because the consecutive clause is
    // OPTIONAL in the backend. Every number, sign, unit and percentage is the
    // backend's own token copied into its slot; only the wording moves.
    // `direction`, `severity` and `dir` are the trend engine's closed
    // vocabulary and render through the shared label function, so an unknown
    // word is preserved verbatim instead of being guessed.
    'trend.why.consecutive': [
        'slope {slope}%/mo → direction \'{direction}\' (stable band ±{band}%); severity \'{severity}\'; {consecutive} consecutive {dir} months; last vs mean {lastMean}%; CV {cv}%',
        'الانحدار {slope}%/شهر ← الاتجاه "{direction}" (نطاق الاستقرار ±{band}%)؛ الشدة "{severity}"؛ {consecutive} أشهر متتالية {dir}؛ الأخير مقابل المتوسط {lastMean}%؛ معامل التباين {cv}%',
    ],
    'trend.why': [
        'slope {slope}%/mo → direction \'{direction}\' (stable band ±{band}%); severity \'{severity}\'; last vs mean {lastMean}%; CV {cv}%',
        'الانحدار {slope}%/شهر ← الاتجاه "{direction}" (نطاق الاستقرار ±{band}%)؛ الشدة "{severity}"؛ الأخير مقابل المتوسط {lastMean}%؛ معامل التباين {cv}%',
    ],

    // ── layered-outlier interpretation: lead ─────────────────────────────
    // The backend composes "{lead}. {tail}; {tail}; {tail}." — the lead and
    // every tail are separate registered shapes, so an unknown tail can never
    // drag the rest of the explanation back into English.
    'interp.lead.none': [
        'No layer exceeded its threshold',
        'لم يتجاوز أي مستوى حدّه',
    ],
    'interp.lead.historical': [
        "Deviation from this hospital's own recent baseline",
        'انحراف عن خط الأساس الحديث لهذا المستشفى',
    ],
    'interp.lead.rate': [
        'Rate deviates from its recent pattern',
        'المعدل ينحرف عن نمطه الحديث',
    ],
    'interp.lead.raw': [
        'Raw value deviates from its recent pattern',
        'القيمة الخام تنحرف عن نمطها الحديث',
    ],
    'interp.lead.insufficient': [
        'Not enough history: needs at least {min} prior months - this month is not assessable against its own baseline, so it is not a confirmed normal result',
        'التاريخ غير كافٍ: يلزم {min} شهراً سابقاً على الأقل — لا يمكن تقييم هذا الشهر مقابل خط أساسه، لذا فهو ليس نتيجة طبيعية مؤكدة',
    ],
    'interp.lead.peer_only': [
        "Not enough history: needs at least {min} prior months, but the peer comparison is significant - a peer deviation is confirmed while the hospital's own baseline is not assessable",
        'التاريخ غير كافٍ: يلزم {min} شهراً سابقاً على الأقل، لكن المقارنة مع النظير دالّة — يتأكد انحراف عن النظراء بينما لا يمكن تقييم خط أساس المستشفى نفسه',
    ],
    'interp.lead.data_entry': [
        'All layers spike together while the denominator is stable - consistent with a data-entry error; verify source values before acting',
        'كل الطبقات ترتفع معاً بينما المقام مستقر — متسق مع خطأ في إدخال البيانات؛ تحقق من القيم المصدرية قبل التصرف',
    ],
    'interp.lead.clinical': [
        'Rate and history are both high with a stable denominator - consistent with a genuine clinical change; investigate clinically',
        'المعدل والتاريخ مرتفعان مع مقام مستقر — متسق مع تغيّر سريري حقيقي؛ يُستقصى سريرياً',
    ],
    'interp.lead.volume': [
        'The jump tracks a denominator (activity-volume) shift - volume-driven, not a per-case change',
        'الارتفاع يتتبع تغيّراً في المقام (حجم النشاط) — مدفوع بالحجم وليس تغيّراً لكل حالة',
    ],
    'interp.lead.peer_both': [
        'Differs from peers and from its own recent history; both deviations are stated below',
        'يختلف عن النظراء وعن تاريخه الحديث؛ وكلاهما مذكور أدناه',
    ],
    'interp.lead.peer': [
        'Consistently differs from peers; review case mix, referral pattern, and indicator definition',
        'يختلف باستمرار عن النظراء؛ راجع مزيج الحالات ونمط الإحالة وتعريف المؤشر',
    ],

    // ── layered-outlier interpretation: tails ────────────────────────────
    'interp.tail.change': [
        '{name} {value} vs {previous} ({change} vs previous month)',
        '{name} {value} مقابل {previous} ({change} مقابل الشهر السابق)',
    ],
    'interp.tail.history.above': [
        '{change} above baseline mean {mean}',
        '{change} أعلى من متوسط الأساس {mean}',
    ],
    'interp.tail.history.below': [
        '{change} below baseline mean {mean}',
        '{change} أدنى من متوسط الأساس {mean}',
    ],
    'interp.tail.rate': [
        'rate {rate}{unit}',
        'المعدل {rate}{unit}',
    ],
    'interp.tail.denominator.change': [
        'denominator {denominator} ({change} vs previous)',
        'المقام {denominator} ({change} مقابل السابق)',
    ],
    'interp.tail.denominator': [
        'denominator {denominator}',
        'المقام {denominator}',
    ],
    'interp.tail.peer_average': [
        'peer average {mean} across {count} hospitals',
        'متوسط النظراء {mean} عبر {count} مستشفى',
    ],
    'interp.tail.peer_unavailable': [
        'peer comparison unavailable - no independent peer evidence either way',
        'المقارنة مع النظير غير متاحة — لا دليل نظير مستقل في أي من الاتجاهين',
    ],
    'interp.tail.peer_no_deviation': [
        'peer comparison {level}{score} - no peer deviation',
        'المقارنة مع النظير {level}{score} — لا انحراف عن النظراء',
    ],
    'interp.tail.peer_below_high': [
        'peer comparison {level}{score} is below the HIGH threshold - not enough to classify without history',
        'المقارنة مع النظير {level}{score} دون حد المرتفع — لا يكفي للتصنيف دون التاريخ',
    ],
    'interp.tail.peer_plain': [
        'peer comparison {level}{score}',
        'المقارنة مع النظير {level}{score}',
    ],
    'interp.tail.peer_also': [
        'peer comparison also {level}',
        'المقارنة مع النظير أيضاً {level}',
    ],
    'interp.tail.peer_not_shared': [
        'peer comparison {level} - peers do not share this deviation',
        'المقارنة مع النظير {level} — لا يشارك النظراء هذا الانحراف',
    ],
    'interp.tail.own_history': [
        'own history {level} - no deviation from its own baseline',
        'التاريخ الخاص {level} — لا انحراف عن خط أساسه',
    ],
    'interp.tail.own_history.missing': [
        'own history not assessable - the peer comparison is the evidence',
        'التاريخ الخاص غير قابل للتقييم — المقارنة مع النظير هي الدليل',
    ],
    'interp.tail.denominator_missing': [
        'denominator missing or zero - rate layers not computable',
        'المقام مفقود أو صفر — طبقات المعدل غير قابلة للحساب',
    ],
    'interp.tail.small_denominator': [
        'small denominator ({denominator} < {min}) - confidence lowered, level capped at {cap}',
        'مقام صغير ({denominator} < {min}) — الثقة مخفّضة والمستوى مسقَّف عند {cap}',
    ],
    'interp.tail.zero_spread': [
        '{labels} has no spread (all values identical) - the deviation cannot be graded, so the level is capped at {cap}',
        '{labels} بلا تباين (كل القيم متطابقة) — لا يمكن تقدير الانحراف، لذا يُسقَّف المستوى عند {cap}',
    ],
    'interp.tail.pct_change_capped': [
        "{labels}: the percentage change is not graded on its own - it is clamped to the level the same window's z-score supports, because a relative change ignores how much the series normally varies",
        '{labels}: لا تُقدَّر النسبة المئوية للتغيّر بمفردها — بل تُقيَّد بالمستوى الذي تدعمه درجة z للنافذة نفسها، لأن التغيّر النسبي يتجاهل مقدار تباين السلسلة عادةً',
    ],
    'interp.tail.thin_peer': [
        '{labels} has fewer than {min} peer hospitals - too few to measure a spread, so the level is capped at {cap} and no z-score is produced for it',
        '{labels} لديها أقل من {min} مستشفى نظير — عدد أقل من قياس التباين، لذا يُسقَّف المستوى عند {cap} ولا تُحتسب درجة z لها',
    ],
    'interp.tail.thin_peer.tail': [
        'the deviation itself is still reported',
        'ويبقى الانحراف نفسه مُبلَّغاً عنه',
    ],
    // The layer-name vocabulary the interpretation quotes when it names the
    // comparison whose spread is degenerate (``_LAYER_LABELS``).
    'interp.layer.raw_value': ['raw-value comparison', 'مقارنة القيمة الخام'],
    'interp.layer.rate': ['rate comparison', 'مقارنة المعدل'],
    'interp.layer.own_history': ['own-history baseline', 'خط الأساس التاريخي'],
    'interp.layer.denominator_shift': ['denominator shift', 'تغيّر المقام'],
    'interp.layer.peer': ['peer comparison', 'المقارنة مع النظير'],

    'rule.what.failed': [
        'Rule {code} FAILED: {description}',
        'القاعدة {code} فشلت: {description}',
    ],
    'rule.what.passed': [
        'Rule {code} passed: {description}',
        'القاعدة {code} نُجحت: {description}',
    ],
};

/* Matcher table. Ordered: the more specific shape first. Each entry binds
 * parameters from a STABLE sentence shape; ``codes`` lists parameters that
 * are analytical identifiers (rendered through the caller's label function). */
const RULES = [
    ['layer.name.raw', /^Raw value$/],
    ['layer.name.rate', /^Rate$/],
    ['layer.name.historical', /^Historical baseline$/],
    ['layer.name.volume', /^Patient volume$/],
    ['layer.name.peer', /^Peer comparison$/],

    ['layered.what.change', /^(?<name>.+?) (?<value>-?[\d.,]+) vs (?<previous>-?[\d.,]+) previous \((?<change>[+\-\u2212]?[\d.,]+%)\) — (?<type>[A-Z_]+) \((?<level>[A-Z_]+) level\)\.?$/, ['type', 'level']],
    ['layered.what.plain', /^(?<name>.+?) — (?<type>[A-Z_]+) \((?<level>[A-Z_]+) level\)\.?$/, ['type', 'level']],
    ['layered.why.rule', /^Rule (?<rule>\d+) of the layered rule table fired → (?<type>[A-Z_]+)\.$/, ['type']],
    ['layered.why.stale', /^The stored classification no longer matches the current history \(recomputed: (?<type>[A-Z_]+)\) — recalculate this month\.$/, ['type']],
    ['layered.why.stored', /^Stored interpretation: (?<text>.+)$/],
    ['layered.stale.policy', /^Under the current classification policy this row recomputes to (?<type>[A-Z_]+) (?<level>[A-Z_]+) \(stored: (?<stype>[A-Z_]+) (?<slevel>[A-Z_]+)\) — recalculate this month\.$/, ['type', 'level', 'stype', 'slevel']],

    ['layered.layer.raw', /^this month's analysis value vs its own recent distribution$/],
    ['layered.layer.rate', /^rate vs its own recent distribution$/],
    ['layered.layer.rate.count', /^count indicators have no separate rate layer$/],
    ['layered.layer.history', /^(?<valid>\d+) valid prior months against a (?<min>\d+)-observation minimum$/],
    ['layered.layer.volume', /^denominator change guards against volume-driven spikes$/],
    ['layered.layer.volume.count', /^count indicators have no denominator layer$/],
    ['layered.layer.peer', /^every hospital reporting the indicator this month \(≥ 2 others\), self excluded$/],
    ['layered.layer.peer.thin', /^Fewer than (?<min>\d+) peer hospitals cannot measure a spread, so no z-score is produced for this comparison$/],

    ['layered.value.none', /^not computable$/],
    ['layered.value.change', /^(?<value>[\d.,]+) \(previous (?<previous>[\d.,]+), (?<change>[+\-\u2212]?[\d.,]+%)\)$/],
    ['layered.value.count', /^not applicable \(count indicator\)$/],
    ['layered.value.denominator', /^not computable \(denominator missing or zero\)$/],
    ['layered.value.insufficient', /^insufficient history$/],
    ['layered.value.history.change', /^(?<change>[+\-\u2212]?[\d.,]+%) vs baseline mean (?<mean>[\d.,]+)$/],
    ['layered.value.peer', /^(?<mean>[\d.,]+) across (?<peer>\d+) peer hospitals$/],
    ['layered.value.peer.none', /^not computable \(fewer than 2 hospitals reported it\)$/],

    ['layered.reproduce.ok', /^Stored layer scores and the current history reproduce the stored classification\.$/],
    ['layered.reproduce.stale', /^Re-running the rule table over the stored scores with the CURRENT history gives a different result — the history changed since this row was written; recalculate this month\.$/],
    ['layered.chain.layers', /^raw → rate\/volume → historical → peer \(recorded method: (?<method>\w+)\)$/],
    ['layered.chain.classification', /^Rule (?<rule>\d+|—): (?<type>[A-Z_]+) at (?<level>[A-Z_]+), route (?<route>\w+)$/, ['type', 'level']],

    ['anomaly.what.outlier', /^(?<rate>.+?) is an outlier: value (?<value>-?[\d.,]+) vs benchmark (?<benchmark>-?[\d.,]+) \(z=(?<z>[-\d.]+)\)$/],
    ['anomaly.what.normal', /^(?<rate>.+?) is within normal range: value (?<value>-?[\d.,]+) vs benchmark (?<benchmark>-?[\d.,]+) \(z=(?<z>[-\d.]+)\)$/],
    ['anomaly.why.exceeds', /^\|z\| = (?<z>[\d.]+) exceeds the (?<threshold>[\d.]+) threshold → flagged as outlier \(rate (?<direction>above|below) the benchmark\)$/],
    ['anomaly.why.pipeline', /^Flagged by the anomaly detection pipeline \(trend\/regression rule\) with z=(?<z>[-\d.]+), threshold (?<threshold>[\d.]+)$/],
    ['anomaly.why.within', /^\|z\| = (?<z>[\d.]+) is within the (?<threshold>[\d.]+) threshold → not an outlier$/],
    ['anomaly.chain.validation', /^Zero-denominator and range checks run before rate computation$/],
    ['anomaly.chain.finding', /^Anomaly row #(?<id>\d+) \(outlier=(?<flag>True|False)\)$/],
    ['anomaly.reproduce.missing', /^Raw numerator\/denominator missing — rate cannot be reproduced from stored values$/],
    ['anomaly.reproduce.ok', /^Benchmark recomputed and matches the current data\.$/],
    ['anomaly.reproduce.stale', /^Benchmark could not be reproduced from the current data\.$/],

    ['problem.stale_benchmark', /^The stored benchmark \((?<benchmark>[-\d.]+), z=(?<z>[-\d.]+)\) no longer matches the uploaded data: recomputing (?<rate>.+?) over the same population gives (?<recomputed>[-\d.]+) \(z=(?<recomputedZ>[-\d.]+)\)\. The anomaly row is out of date with the current values or indicator configuration — recalculate this month\.$/],
    ['problem.missing', /^Indicator (?<code>[^ ]+) \((?<name>.+)\) has no value for this month$/],
    ['problem.missing.noname', /^Indicator (?<code>[^ ]+) has no value for this month$/],
    ['problem.negative', /^Indicator (?<code>[^ ]+) \((?<name>.+)\) has a negative value \((?<value>-?[\d.,]+)\)$/],
    ['problem.negative.noname', /^Indicator (?<code>[^ ]+) has a negative value \((?<value>-?[\d.,]+)\)$/],
    ['problem.duplicate', /^Indicator (?<code>[^ ]+) \((?<name>.+)\) = (?<value>-?[\d.,]+) from '(?<source>.*)' appears (?<n>\d+) times \(uploaded more than once\)$/],
    ['problem.duplicate.noname', /^Indicator (?<code>[^ ]+) = (?<value>-?[\d.,]+) from '(?<source>.*)' appears (?<n>\d+) times \(uploaded more than once\)$/],
    ['problem.thin_peers', /^Only (?<n>\d+) peer hospital\(s\) — the benchmark is statistically fragile$/],

    ['score.what.mix', /^Data quality score (?<score>[-\d.]+) for (?<month>[\d-]+) — weighted mix of rule compliance, completeness, consistency and outlier score$/],
    ['score.what.outlier', /^Outlier score (?<score>[-\d.]+) for (?<month>[\d-]+) — 100 minus the penalty from (?<n>\d+) indicator\(s\) at HIGH\/VERY_HIGH$/],
    ['score.what.ghost', /^This month has a score row but no raw data behind it \(never analyzed or data was removed\)\. The score is a placeholder, not a performance result\.$/],
    ['score.what.period.none', /^Quality score (?<score>[-\d.]+) for (?<month>[\d-]+) \(no earlier analyzed month to compare\)$/],
    ['score.what.period', /^Quality score (?<score>[-\d.]+) for (?<month>[\d-]+) \((?<change>[+\-\u2212][\d.]+) vs (?<previous>[\d-]+)\)$/],
    ['score.why.below', /^(?<n>\d+) component\(s\) below target; weakest: (?<component>.+?) \((?<value>[-\d.]+)% vs (?<target>[-\d.]+)% target\)\.$/],
    ['score.why.rules', /^(?<n>\d+) validation rule\(s\) failed \((?<codes>[^)]*?)(?<more>, …)?\) → rule compliance (?<compliance>[-\d.]+)%$/],
    ['score.why.no_rules', /^No validation rule failed this month$/],
    ['score.why.all_with_rules', /^All components meet their targets \((?<sentence>.+)\)$/],
    ['score.why.all', /^All components meet their targets — the score reflects good data quality$/],
    ['score.why.problems', /^(?<n>\d+) raw-data problem\(s\) detected;$/],
    // ``list`` is a comma-separated run of "<code> (<BAND>)" items: nested, so
    // each item keeps its indicator code while the band becomes words.
    ['score.why.outlier_drivers', /^Outlier score (?<score>[-\d.]+)% = 100 - (?<penalty>[-\d.]+) penalty, from (?<n>\d+) indicator\(s\) at HIGH\/VERY_HIGH: (?<list>.+?)(?<more> \+?\d+ more)?$/, [], ['list']],
    ['score.why.outlier_none', /^No indicator reached HIGH or VERY_HIGH this month — outlier score (?<score>[-\d.]+)% \(penalty (?<penalty>[-\d.]+)\)\.$/],
    ['score.why.outlier_none.tail', /^Missing cells are counted under completeness, not here$/],
    ['score.why.more', /^\+(?<n>\d+) more$/],

    ['cc.no_alert', /^No active Quality Alert is stored for this formula and month, so there is no second verdict to compare with\.$/],
    ['cc.no_alert.tail', /^Re-scan the month if an alert was expected\.$/],
    // ``label`` is the perspective name ("Ownership peers"); it travels through
    // the shared label function like every other stored identifier, so an
    // Arabic sentence never carries an English perspective name. The ``history``
    // clause is a sentence of its own and is localized as one (cc.history.*).
    ['cc.stratified', /^Quality Alerts reports (?<severity>[A-Z_]+) under "(?<label>[^"]+)" \(n=(?<peers>\d+)\), a narrower stratified comparison\.$/, ['severity', 'label']],
    ['cc.stratified.diag', /^Outlier Diagnostics classifies this row (?<type>[A-Z_]+) at (?<level>[A-Z_]+) against the single all-hospital detection baseline \(peer score (?<peerScore>.+?) \/ (?<peerLevel>[^)]+)\), and (?<history>.+)$/, ['type', 'level', 'peerLevel'], ['history']],
    ['cc.history.not_assessable', /^the hospital's own history is not assessable\.$/],
    ['cc.history.not_assessed', /^the hospital's own history could not be assessed either\.$/],
    ['cc.history.within', /^its own history stayed within its band\.$/],
    ['cc.history_more_severe', /^The stored history-perspective alert is more severe than this diagnostic row although both use the same history baseline; recalculate the month before relying on either\.$/],
    ['cc.severity_more_severe', /^The stored alert \((?<severity>[A-Z_]+), "(?<label>[^"]+)"\) is more severe than this diagnostic row \((?<level>[A-Z_]+)\) under the same detection baseline, so the two stored results disagree\.$/, ['severity', 'level', 'label']],
    ['cc.recalc', /^Recalculate this month to reconcile them\.$/],
    ['cc.agree', /^Quality Alerts and Outlier Diagnostics agree: the most severe stored alert \((?<severity>[A-Z_]+), "(?<label>[^"]+)"\) is consistent with this diagnostic level \((?<level>[A-Z_]+)\)\.$/, ['severity', 'level', 'label']],
    ['cc.closed_note', /^The matching Quality Alert was closed by a reviewer \(Resolved \/ skipped as False Positive\), so it no longer raises on the Quality Alerts screen; closing records the investigation decision and changes neither detection result\.$/],
    ['cc.policy_band', /^The stored alert was written (?<stored>[A-Z_]+), but the approved cap policy assigns it (?<severity>[A-Z_]+) \("(?<label>[^"]+)"\): (?<reasons>.+)\.$/, ['stored', 'severity', 'label'], ['reasons']],
    ['cc.policy_band.tail', /^Quality Alerts shows that policy band while Outlier Diagnostics classifies the peer layer without the cap \((?<type>[A-Z_]+) at (?<level>[A-Z_]+)\)\.$/, ['type', 'level']],
    ['cc.policy_band.stored', /^The stored row keeps (?<stored>[A-Z_]+) until the month is re-scanned\.$/, ['stored']],
    ['cc.reason.dispersion', /^every hospital in that comparison reported the same value, so the deviation has no measurable scale$/],
    ['cc.reason.thin', /^the comparison group holds (?<peers>\d+) other hospital\(s\) and measuring a spread needs at least (?<min>\d+), so its z-score is not a measurement$/],
    ['cc.reason.window', /^the hospital's own history window does not support the top band \(the same window's dispersion-aware band is (?<band>[A-Z_]+|below VERY_HIGH)\)$/, ['band']],
    ['cc.older_policy', /^The stored alert \((?<severity>[A-Z_]+), "(?<label>[^"]+)"\) is consistent with the stored diagnostic row, but that row was written under an older classification policy\.$/, ['severity', 'label']],

    // Composed interpretation: the lead and each '; '-separated tail are
    // matched independently, so a new tail shape only leaves itself in English.
    ['interp.lead.none', /^No layer exceeded its threshold\.?$/],
    ['interp.lead.historical', /^Deviation from this hospital's own recent baseline\.?$/],
    ['interp.lead.rate', /^Rate deviates from its recent pattern\.?$/],
    ['interp.lead.raw', /^Raw value deviates from its recent pattern\.?$/],
    ['interp.lead.insufficient', /^Not enough history: needs at least (?<min>\d+) prior months - this month is not assessable against its own baseline, so it is not a confirmed normal result\.?$/],
    ['interp.lead.peer_only', /^Not enough history: needs at least (?<min>\d+) prior months, but the peer comparison is significant - a peer deviation is confirmed while the hospital's own baseline is not assessable\.?$/],
    ['interp.lead.data_entry', /^All layers spike together while the denominator is stable - consistent with a data-entry error; verify source values before acting\.?$/],
    ['interp.lead.clinical', /^Rate and history are both high with a stable denominator - consistent with a genuine clinical change; investigate clinically\.?$/],
    ['interp.lead.volume', /^The jump tracks a denominator \(activity-volume\) shift - volume-driven, not a per-case change\.?$/],
    ['interp.lead.peer_both', /^Differs from peers and from its own recent history; both deviations are stated below\.?$/],
    ['interp.lead.peer', /^Consistently differs from peers; review case mix, referral pattern, and indicator definition\.?$/],

    // The ``name`` / ``labels`` parameters may never cross a sentence boundary
    // (". "): a lazy ".+?" let a WHOLE paragraph match one tail shape, which
    // swallowed the lead sentence as a prefix and left it in English.
    ['interp.tail.change', /^(?<name>(?:(?!\.\s)[^;])+?) (?<value>-?[\d.,]+) vs (?<previous>-?[\d.,]+) \((?<change>[+\-\u2212]?[\d.,]+%) vs previous month\)$/],
    ['interp.tail.history.above', /^(?<change>[+\-\u2212]?[\d.,]+%) above baseline mean (?<mean>[\d.,]+)$/],
    ['interp.tail.history.below', /^(?<change>[+\-\u2212]?[\d.,]+%) below baseline mean (?<mean>[\d.,]+)$/],
    ['interp.tail.rate', /^rate (?<rate>[\d.]+)(?<unit>%)?$/],
    ['interp.tail.denominator.change', /^denominator (?<denominator>[\d.,]+) \((?<change>[+\-\u2212]?[\d.,]+%) vs previous\)$/],
    ['interp.tail.denominator', /^denominator (?<denominator>[\d.,]+)$/],
    ['interp.tail.peer_average', /^peer average (?<mean>[\d.,]+) across (?<count>\d+) hospitals$/],
    ['interp.tail.peer_unavailable', /^peer comparison unavailable - no independent peer evidence either way$/],
    ['interp.tail.peer_no_deviation', /^peer comparison (?<level>[A-Z_]+)(?<score> \(score [\d.]+\))? - no peer deviation$/, ['level']],
    ['interp.tail.peer_below_high', /^peer comparison (?<level>[A-Z_]+)(?<score> \(score [\d.]+\))? is below the HIGH threshold - not enough to classify without history$/, ['level']],
    ['interp.tail.peer_plain', /^peer comparison (?<level>[A-Z_]+)(?<score> \(score [\d.]+\))?$/, ['level']],
    ['interp.tail.peer_also', /^peer comparison also (?<level>[A-Z_]+)$/, ['level']],
    ['interp.tail.peer_not_shared', /^peer comparison (?<level>[A-Z_]+) - peers do not share this deviation$/, ['level']],
    ['interp.tail.own_history', /^own history (?<level>[A-Z_]+) - no deviation from its own baseline$/, ['level']],
    ['interp.tail.own_history.missing', /^own history not assessable - the peer comparison is the evidence$/],
    ['interp.tail.denominator_missing', /^denominator missing or zero - rate layers not computable$/],
    ['interp.tail.small_denominator', /^small denominator \((?<denominator>[\d.,]+) < (?<min>[\d.,]+)\) - confidence lowered, level capped at (?<cap>[A-Z_]+)$/, ['cap']],
    ['interp.tail.zero_spread', /^(?<labels>(?:(?!\.\s)[^;])+?) has no spread \(all values identical\) - the deviation cannot be graded, so the level is capped at (?<cap>[A-Z_]+)$/, ['cap'], ['labels']],
    ['interp.tail.pct_change_capped', /^(?<labels>(?:(?!\.\s)[^;])+?): the percentage change is not graded on its own - it is clamped to the level the same window's z-score supports, because a relative change ignores how much the series normally varies$/, [], ['labels']],
    ['interp.tail.thin_peer', /^(?<labels>(?:(?!\.\s)[^;])+?) has fewer than (?<min>\d+) peer hospitals - too few to measure a spread, so the level is capped at (?<cap>[A-Z_]+) and no z-score is produced for it$/, ['cap'], ['labels']],
    ['interp.tail.thin_peer.tail', /^the deviation itself is still reported$/],

    ['interp.layer.raw_value', /^raw-value comparison$/],
    ['interp.layer.rate', /^rate comparison$/],
    ['interp.layer.own_history', /^own-history baseline$/],
    ['interp.layer.denominator_shift', /^denominator shift$/],
    ['interp.layer.peer', /^peer comparison$/],

    // Composite quality-score paragraph: the backend joins the clauses with
    // '; ', so each clause is registered on its own as well as in full.
    ['score.why.problems.clause', /^(?<n>\d+) raw-data problem\(s\) detected$/],
    ['score.why.below.n', /^(?<n>\d+) component\(s\) below target$/],
    ['score.why.weakest', /^weakest: (?<component>(?:(?!\.\s)[^;])+?) \((?<value>[-\d.]+)% vs (?<target>[-\d.]+)% target\)$/, ['component']],

    ['how.formula.count', /^(?<name>.+?) = count of indicator (?<code>\S+)$/],

    // Row headlines. Anchored at both ends: a longer sentence that merely
    // CONTAINS the shape ("… (normal) and more text") is not this row's
    // headline and must keep the backend's wording.
    ['comparison.what', /^(?<rate>.+?) for (?<hospital>.+?) in (?<month>[\d-]+): (?<value>[+\-\u2212]?[\d.,]+) vs peer benchmark (?<benchmark>[+\-\u2212]?[\d.,]+) \((?<label>[^)]+)\)$/, ['label']],
    ['trend.what', /^(?<rate>.+?) trend for (?<hospital>.+?): (?<direction>increasing|decreasing|stable) \((?<severity>[a-z_]+)\), slope (?<slope>[+\-\u2212]?[\d.]+)%\/mo over (?<months>\d+) months$/, ['direction', 'severity']],

    // The trend row's ``why``. Anchored at both ends, and the longer shape
    // (with the optional consecutive clause) is tried first.
    ['trend.why.consecutive', /^slope (?<slope>[+\-\u2212]?[\d.]+)%\/mo \u2192 direction '(?<direction>[^']+)' \(stable band \u00b1(?<band>[\d.]+)%\); severity '(?<severity>[^']+)'; (?<consecutive>\d+) consecutive (?<dir>[^']+) months; last vs mean (?<lastMean>[+\-\u2212]?[\d.]+)%; CV (?<cv>[\d.]+)%$/, ['direction', 'severity', 'dir']],
    ['trend.why', /^slope (?<slope>[+\-\u2212]?[\d.]+)%\/mo \u2192 direction '(?<direction>[^']+)' \(stable band \u00b1(?<band>[\d.]+)%\); severity '(?<severity>[^']+)'; last vs mean (?<lastMean>[+\-\u2212]?[\d.]+)%; CV (?<cv>[\d.]+)%$/, ['direction', 'severity']],

    ['rule.what.failed', /^Rule (?<code>\S+) FAILED: (?<description>.+)$/],
    ['rule.what.passed', /^Rule (?<code>\S+) passed: (?<description>.+)$/],
];

function _humanize(code) {
    const words = String(code).replace(/_/g, ' ').toLowerCase();
    return /^[A-Z0-9_]+$/.test(String(code))
        ? words.charAt(0).toUpperCase() + words.slice(1)
        : words;
}

/**
 * An unregistered LIST ITEM, e.g. ``2.l (VERY_HIGH)`` from the outlier-score
 * driver list. The item itself is not a sentence shape, but the band it names
 * is a machine identifier: it takes its localized label in Arabic and readable
 * words in English. Indicator codes and numbers are left exactly as they are.
 */
const BAND_WORDS = {
    VERY_HIGH: 'Very high',
    HIGH: 'High',
    MODERATE: 'Moderate',
    LOW: 'Low',
    NONE: 'None',
};

function _plain(piece, lang, label) {
    const named = function (code) {
        if (lang === 'ar' && label) {
            const localized = label(code);
            if (localized && localized !== code) return localized;
        }
        return BAND_WORDS[code] || _humanize(code);
    };
    return String(piece)
        .replace(/\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b/g, named)
        // A band listed on its own ("2.l (VERY_HIGH), 17 (HIGH)") has no
        // underscore, so the identifier pattern above cannot see it.
        .replace(/\b(?:VERY_HIGH|HIGH|MODERATE|LOW|NONE)\b/g, named);
}

function _fill(template, values, codeNames, label, nested, lang) {
    return String(template).replace(/\{(\w+)\}/g, function (match, name) {
        if (!Object.prototype.hasOwnProperty.call(values, name)) return match;
        const raw = values[name];
        if (raw === undefined || raw === null) return '';
        const text = String(raw);
        if (codeNames.indexOf(name) !== -1) {
            return label ? label(text) : _humanize(text);
        }
        if (nested.indexOf(name) !== -1) {
            // A list is composed by the backend with '; ' (clauses) or ', '
            // (the names of the layers whose spread is degenerate). Each piece
            // is itself a registered shape, so it is localized on its own; an
            // unregistered piece stays verbatim.
            return text.split('; ').map(function (piece) {
                const loc = localizeSentence(piece, lang, label);
                if (loc !== null) return loc;
                return piece.split(', ').map(function (item) {
                    const inner = localizeSentence(item, lang, label);
                    return inner === null ? _plain(item, lang, label) : inner;
                }).join(', ');
            }).join('; ');
        }
        return text;
    });
}

/** Split a backend paragraph into its sentences so each one is localizable on
 * its own. The backend composes prose by concatenation ("<rule sentence>
 * <interpretation> <cross-check>"), so template matching must never require
 * the whole paragraph to match one shape. */
function _sentences(text) {
    return String(text).split(/(?<=[.!?])\s+(?=[A-Z0-9(\u0600-\u06FF])/);
}

/**
 * Localize one backend sentence.
 *
 * @param {string} text   one sentence (or a whole short string)
 * @param {string} lang   'en' | 'ar'
 * @param {function} [label] code → localized label (shared with the popup)
 * @returns {string|null} the localized sentence, or null when no registered
 *                        template matches — the caller then keeps the original
 *                        text instead of guessing.
 */
export function localizeSentence(text, lang, label) {
    const raw = String(text == null ? '' : text).trim();
    if (!raw) return null;
    const index = lang === 'ar' ? 1 : 0;
    const direct = _matchRules(raw, lang, index, label);
    if (direct !== null) return _withStop(direct, raw);
    // A sentence that ENDS the paragraph carries the backend's full stop, while
    // the registered shape describes the sentence without it. The stop is
    // matched off and put back, so a localizable last sentence is never left in
    // English just because of its punctuation (and no stop is ever lost).
    if (/\.$/.test(raw)) {
        const body = _matchRules(raw.replace(/\.\s*$/, ''), lang, index, label);
        if (body !== null) return _withStop(body, raw);
    }
    return null;
}

/** Keep the backend's sentence-final full stop, whatever the shape matched. */
function _withStop(rendered, raw) {
    return /\.$/.test(raw) && !/\.$/.test(String(rendered))
        ? rendered + '.' : rendered;
}

/** First registered shape that renders this text, in one language. */
function _matchRules(raw, lang, index, label) {
    for (let i = 0; i < RULES.length; i += 1) {
        const [key, re, codes, nested] = RULES[i];
        const match = re.exec(raw);
        if (!match) continue;
        // A phrase template has no parameters at all, so ``groups`` is
        // undefined; it still renders the registered sentence.
        const values = match.groups ? Object.assign({}, match.groups) : {};
        return _fill(MESSAGES[key][index], values, codes || [], label,
            nested || [], lang);
    }
    return null;
}

/**
 * Localize ONE sentence by its '; '-separated clauses.
 *
 * The backend composes the interpretation as "{lead}. {tail}; {tail}." and the
 * quality-score reason as "{n} problem(s); {n} component(s) below target;
 * weakest: …". Each clause is a registered shape of its own, so a matched one
 * is never held back by an unmatched neighbour. A trailing full stop is kept
 * exactly where the backend put it.
 *
 * @returns {string|null} null when no clause matched (the caller then keeps the
 *                        sentence verbatim).
 */
function _localizeClauses(text, lang, label) {
    const raw = String(text);
    const trailing = /\.\s*$/.test(raw);
    const body = trailing ? raw.replace(/\.\s*$/, '') : raw;
    if (body.indexOf('; ') === -1) return null;
    const pieces = body.split('; ');
    let matched = 0;
    const rendered = pieces.map(function (piece) {
        const bare = piece.replace(/\.\s*$/, '');
        const localized = localizeSentence(bare, lang, label);
        if (localized === null) return bare;
        matched += 1;
        return localized;
    });
    if (!matched) return null;
    // The Arabic semicolon, so a localized paragraph does not mix scripts.
    return rendered.join(lang === 'ar' ? '\u061b ' : '; ') + (trailing ? '.' : '');
}

/**
 * Localize a composed backend paragraph, sentence by sentence and clause by
 * clause. Nothing is ever translated beyond a registered shape: an unmatched
 * sentence keeps the backend's own wording, and only the machine identifiers
 * it carries are made readable by ``humanize`` (when the caller supplies one).
 *
 * @param {string} text
 * @param {string} lang 'en' | 'ar'
 * @param {function} [label]    code → localized label
 * @param {function} [humanize] unmatched sentence → readable text (codes only)
 * @returns {string|null} null when NOTHING was recognized, so the caller can
 *                        keep the original text verbatim.
 */
export function localizeProse(text, lang, label, humanize) {
    if (text === null || text === undefined) return null;
    const raw = String(text);
    if (!raw.trim()) return null;
    // A registered multi-sentence message matches as a whole first; the
    // sentence split below is only for paragraphs composed of independent
    // backend sentences.
    const whole = localizeSentence(raw, lang, label);
    if (whole !== null) return whole;
    const parts = _sentences(raw);
    let matched = 0;
    const rendered = parts.map(function (part) {
        const localized = localizeSentence(part, lang, label);
        if (localized !== null) { matched += 1; return localized; }
        const clauses = _localizeClauses(part, lang, label);
        if (clauses !== null) { matched += 1; return clauses; }
        // Unregistered wording is returned unchanged - never a guessed
        // translation - but a machine code it carries must not survive into
        // the rendered prose.
        return humanize ? humanize(part) : part;
    });
    if (!matched) return null;
    return rendered.join(' ');
}

/** True when at least one registered template renders this text. */
export function hasTemplate(text, lang) {
    return localizeProse(text, lang || 'en', null) !== null;
}

export const __templates = { MESSAGES: MESSAGES, RULES: RULES };
