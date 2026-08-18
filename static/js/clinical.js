        import { API, apiGet } from './api.js';
        import { __ } from './i18n.js';
        import { esc } from './tree.js';
        import { renderClinical } from './validation.js';

        // ── Unified analysis (Analyze + Generate AI Reports merged — same engine, one button) ──
        // نطاق محدد (مستشفى+شهر) = عرض تفصيلي واحد · نطاق واسع = بطاقات مجمّعة مرتّبة بالمخاطر
        let _reportData = null;

        export function runAnalysis() {
            const monthSel = document.getElementById('clinicalMonthSelect');
            const hSel = document.getElementById('clinicalHospitalSelect');
            if (!monthSel || !hSel) return;

            // نطاق التحليل من الخيارات الفعلية للقوائم (ترمّز النطاق الصحيح تلقائياً)
            const selectedMonth = monthSel.value;
            const selectedHospital = hSel && hSel.value ? hSel.value : '';
            const months = selectedMonth ? [selectedMonth] : Array.from(monthSel.options).map(o => o.value).filter(Boolean);
            const hospitals = selectedHospital ? [selectedHospital] : Array.from(hSel.options).map(o => o.value).filter(Boolean);
            const pairs = [];
            for (const m of months) for (const h of hospitals) pairs.push([h, m]);

            // نطاق محدد (مستشفى + شهر واحد) → التحليل التفصيلي مباشرة (نفس مخرجات الدفعة لكن بعرض «قرار أولاً»)
            if (pairs.length === 1 && selectedHospital && selectedMonth) {
                _reportData = null;
                if (typeof window.loadClinical === 'function') window.loadClinical();
                return;
            }

            // نطاق واسع → توليد دفعة (مستشفى × شهر) مع شريط تقدم ونتائج جزئية
            const btn = document.getElementById('clinicalRunBtn');
            const status = document.getElementById('reportStatus');
            const container = document.getElementById('clinicalResults');
            const spinner = document.getElementById('reportLoading');
            const progWrap = document.getElementById('reportProgressWrap');
            const progBar = document.getElementById('reportProgressBar');
            const progText = document.getElementById('reportProgressText');
            const progPct = document.getElementById('reportProgressPct');

            btn.disabled = true;
            btn.textContent = __('Generating...');
            status.textContent = __('Generating report, please wait...') + ' (' + pairs.length + ' ' + __('items') + ')';
            // شريط التقدم والحالة يظهران في بطاقة الفلاتر بجانب الزر — لا مؤشر داخل النتائج
            container.innerHTML = '';
            spinner.classList.remove('hidden');
            if (progWrap) progWrap.style.display = 'block';
            if (progBar) progBar.style.width = '0%';
            if (progText) progText.textContent = '0 / ' + pairs.length;
            if (progPct) progPct.textContent = '0%';

            // توليد تدريجي لكل (مستشفى، شهر) مع تزامن محدود — تقدم حقيقي ونتائج جزئية،
            // وكل زوج مُكتمل يُخزَّن مؤقتاً في الخادم فيعود التكرار فورياً.
            const merged = { reports: [], errors: [], months: [...new Set(months)], hospitals: [], total: 0 };
            const seen = new Set();
            let done = 0;
            const CONCURRENCY = 4;

            async function worker(pair) {
                const [hid, m] = pair;
                const params = [];
                if (m) params.push('month=' + encodeURIComponent(m));
                if (hid) params.push('hospital_id=' + encodeURIComponent(hid));
                let url = API() + '/analysis/generate-report';
                if (params.length) url += '?' + params.join('&');
                try {
                    const res = await fetch(url, { method: 'POST' });
                    const data = await res.json();
                    (data.reports || []).forEach(r => {
                        const key = r.hospital + '|' + r.month;
                        if (!seen.has(key)) { seen.add(key); merged.reports.push(r); }
                    });
                    (data.errors || []).forEach(e => merged.errors.push(e));
                    (data.hospitals || []).forEach(n => { if (!merged.hospitals.includes(n)) merged.hospitals.push(n); });
                } catch (e) {
                    merged.errors.push(hid + '/' + m + ': ' + (e && e.message || e));
                }
            }

            async function run() {
                let idx = 0;
                async function next() {
                    while (idx < pairs.length) {
                        const pair = pairs[idx++];
                        await worker(pair);
                        done++;
                        const pct = Math.round(done / pairs.length * 100);
                        if (progBar) progBar.style.width = pct + '%';
                        if (progText) progText.textContent = done + ' / ' + pairs.length;
                        if (progPct) progPct.textContent = pct + '%';
                        // عرض جزئي للنتائج أثناء التوليد
                        if (done === pairs.length || done % 3 === 0) {
                            merged.total = merged.reports.length;
                            renderReport(merged);
                        }
                    }
                }
                await Promise.all(Array.from({ length: Math.min(CONCURRENCY, pairs.length) }, next));
                btn.disabled = false;
                btn.textContent = __('Run Analysis');
                spinner.classList.add('hidden');
                if (progWrap) progWrap.style.display = 'none';
                merged.total = merged.reports.length;
                if (merged.errors.length) {
                    status.textContent = 'Completed with ' + merged.errors.length + ' errors';
                } else {
                    status.textContent = 'Generated ' + merged.total + ' reports';
                }
                renderReport(merged);
                // تمرير أخير لموضع النتائج ليرى المستخدم المخرجات النهائية
                // (فوري لا smooth — بعض الـ webviews لا تشغّل إطارات الحركة فيعلق التمرير الناعم)
                const finalResults = document.getElementById('clinicalResults');
                if (finalResults) finalResults.scrollIntoView({ block: 'start' });
            }

            run();
        }

        function renderReport(data) {
            _reportData = data;
            const container = document.getElementById('clinicalResults');
            if (!data.reports || !data.reports.length) {
                container.innerHTML = '<p style="color:#888;text-align:center;padding:2rem;">' + __('No data found for the selected criteria.') + '</p>';
                return;
            }
            applyReportFilter();
        }

        // يفتح نافذة منبثقة تعرض التحليل التفصيلي لنفس (المستشفى، الشهر) من البطاقة المجمّعة
        export function openBatchDetail(linkEl) {
            const hosp = linkEl.getAttribute('data-hosp');
            const month = linkEl.getAttribute('data-month');
            const hSel = document.getElementById('clinicalHospitalSelect');
            const titleEl = document.getElementById('modalTitle');
            const bodyEl = document.getElementById('modalBody');
            if (!hSel || !hosp || !month || !titleEl || !bodyEl) return;
            let hid = null;
            Array.from(hSel.options).forEach(o => { if (o.text === hosp) hid = o.value; });
            if (!hid) return;

            titleEl.textContent = hosp + ' — ' + month;
            bodyEl.innerHTML = '<div style="text-align:center;padding:2.5rem;color:#888;"><span class="spinner spinner-lg"></span><br><span style="font-size:0.85rem;">' + __('Loading hospital details...') + '</span></div>';
            document.getElementById('detailModal').classList.add('show');

            fetch(API() + '/clinical/' + hid + '?month=' + encodeURIComponent(month))
                .then(r => r.json())
                .then(analysis => {
                    renderClinical(analysis, bodyEl);
                })
                .catch(err => {
                    bodyEl.innerHTML = '<p style="color:#c62828;padding:1.5rem;">' + __('Failed to load details') + ': ' + err.message + '</p>';
                });
        }

        function _riskGroupHeader(lvl, count) {
            const labels = { critical: __('Critical'), high: __('High'), moderate: __('Moderate'), low: __('Low'), '': __('Other') };
            const colors = { critical: '#b71c1c', high: '#c62828', moderate: '#e65100', low: '#2e7d32', '': '#888' };
            const icons = { critical: '&#128308;', high: '&#128992;', moderate: '&#128993;', low: '&#128994;', '': '&#9899;' };
            const key = labels[lvl] !== undefined ? lvl : '';
            return '<div style="display:flex;align-items:center;gap:0.5rem;margin:1rem 0 0.4rem 0;padding:0.45rem 0.7rem;background:' + colors[key] + '11;border-left:4px solid ' + colors[key] + ';border-radius:4px;">' +
                '<span style="font-size:0.85rem;">' + icons[key] + '</span>' +
                '<strong style="font-size:0.85rem;color:' + colors[key] + ';">' + labels[key] + ' (' + count + ')</strong>' +
                '</div>';
        }

        function _riskColor(level) {
            if (!level) return '#888';
            const l = level.toLowerCase();
            if (l === 'critical') return '#b71c1c';
            if (l === 'high') return '#c62828';
            if (l === 'moderate') return '#e65100';
            if (l === 'low') return '#2e7d32';
            return '#888';
        }

        function _scoreBadge(score) {
            if (!score) return '';
            const g = score === 'Good' || score === 'جيد';
            const m = score === 'Needs Improvement' || score === __('Needs Improvement');
            const c = g ? '#2e7d32' : m ? '#e65100' : '#c62828';
            return '<span style="display:inline-block;font-size:0.72rem;font-weight:600;color:#fff;background:' + c + ';padding:0.1rem 0.5rem;border-radius:10px;">' + esc(score) + '</span>';
        }

        function _pill(label, value, color) {
            return '<span style="display:inline-flex;align-items:center;gap:0.2rem;font-size:0.7rem;background:' + color + '11;border:1px solid ' + color + '44;border-radius:4px;padding:0.1rem 0.45rem;"><strong style="color:' + color + ';">' + esc(value) + '</strong><span style="color:' + color + '88;">' + esc(label) + '</span></span>';
        }

        // يُستدعى عند تغيير المستشفى/الشهر في شريط الفلاتر الموحّد لإعادة تصفية النتائج المجمّعة
        export function applyReportFilter() {
            const data = _reportData;
            const container = document.getElementById('clinicalResults');
            if (!data || !data.reports) return;

            const hSel = document.getElementById('clinicalHospitalSelect');
            const mSel = document.getElementById('clinicalMonthSelect');
            // قيمة select هي معرّف المستشفى — نأخذ الاسم من نص الخيار للتصفية على r.hospital
            const selectedOpt = hSel && hSel.value ? hSel.options[hSel.selectedIndex] : null;
            const selectedHospital = selectedOpt ? selectedOpt.text : '';
            const selectedMonth = mSel ? mSel.value : '';

            let filtered = data.reports;
            if (selectedHospital) {
                filtered = filtered.filter(r => r.hospital === selectedHospital);
            }
            if (selectedMonth) {
                filtered = filtered.filter(r => r.month === selectedMonth);
            }

            if (!filtered.length) {
                container.innerHTML = '<p style="color:#888;text-align:center;padding:2rem;">' + __('No reports match the selected filter.') + '</p>';
                return;
            }

            const monthsInFilter = [...new Set(filtered.map(r => r.month))].sort();
            const hospInFilter = [...new Set(filtered.map(r => r.hospital))].sort();

            // ── ملخص الأزمة: قرار أولاً — عدّ المستشفيات حسب مستوى الخطر + أسماء الحرجة ──
            const riskGroups = { critical: [], high: [], moderate: [], low: [] };
            const riskOrder = ['critical', 'high', 'moderate', 'low'];
            const riskColors = { critical: '#b71c1c', high: '#c62828', moderate: '#e65100', low: '#2e7d32' };
            const riskLabels = { critical: __('Critical'), high: __('High'), moderate: __('Moderate'), low: __('Low') };
            filtered.forEach(r => {
                const lvl = ((r.risk_profile || {}).overall_risk_level || '').toLowerCase();
                const group = riskGroups[lvl] !== undefined ? riskGroups[lvl] : null;
                if (group && !group.includes(r.hospital)) group.push(r.hospital);
            });

            // شريط الأزمة: خلفية وحدود أوضح مع حدّ جانبي أحمر بارز — أول ما يُرى
            let html = '<div style="margin:0.8rem 0 0.5rem 0;padding:0.7rem 0.9rem;background:#fff0f0;border:1px solid #e57373;border-left:4px solid #b71c1c;border-radius:6px;display:flex;flex-wrap:wrap;gap:0.5rem;align-items:center;font-size:0.8rem;">';
            html += '<strong style="color:#b71c1c;font-size:0.85rem;">' + __('Hospitals by risk') + ':</strong>';
            riskOrder.forEach(lvl => {
                const n = riskGroups[lvl].length;
                if (n > 0) {
                    html += '<span style="display:inline-flex;align-items:center;gap:0.25rem;background:' + riskColors[lvl] + '11;border:1px solid ' + riskColors[lvl] + '44;border-radius:12px;padding:0.1rem 0.6rem;">';
                    html += '<strong style="color:' + riskColors[lvl] + ';">' + n + '</strong>';
                    html += '<span style="color:' + riskColors[lvl] + '88;font-size:0.72rem;">' + riskLabels[lvl] + '</span>';
                    html += '</span>';
                }
            });
            const crisisHospitals = riskGroups.critical.length ? riskGroups.critical : (riskGroups.high.length ? riskGroups.high : []);
            if (crisisHospitals.length) {
                const isCritical = riskGroups.critical.length > 0;
                html += '<span style="width:100%;font-size:0.78rem;color:#b71c1c;">&#9888; <strong>' + (isCritical ? __('Critical hospitals') : __('High-risk hospitals')) + ':</strong> ' + esc(crisisHospitals.join(' · ')) + '</span>';
            }
            html += '</div>';

            html += '<div style="margin:0.5rem 0 0.8rem 0;padding:0.6rem 0.8rem;background:#f5f5f5;border-radius:6px;display:flex;gap:1rem;flex-wrap:wrap;font-size:0.82rem;">';
            // العدد فقط بدل قائمة الأسماء — الأسماء في شريط الأزمة ورؤوس البطاقات
            html += '<span><strong>' + __('Hospitals') + ':</strong> ' + hospInFilter.length + '</span>';
            html += '<span><strong>' + __('Months') + ':</strong> ' + monthsInFilter.join(', ') + '</span>';
            html += '<span><strong>' + __('Showing') + ':</strong> ' + filtered.length + ' / ' + data.reports.length + '</span>';
            if (data.errors && data.errors.length) {
                html += '<span style="color:#c62828;"><strong>' + __('Errors') + ':</strong> ' + data.errors.join('; ') + '</span>';
            }
            html += '</div>';

            const byHospital = {};
            filtered.forEach(r => {
                if (!byHospital[r.hospital]) byHospital[r.hospital] = [];
                byHospital[r.hospital].push(r);
            });

            // ترتيب المستشفيات بدرجة الخطر: الحرجة أولاً ثم العالية ثم المتوسطة فالمنخفضة،
            // مع الترتيب الأبجدي كاحتياط للتعادل (الأسوأ عبر تقارير المستشفى)
            const riskRank = { critical: 0, high: 1, moderate: 2, low: 3 };
            const hospitalRiskRank = {};
            const hospitalWorstLevel = {};
            Object.keys(byHospital).forEach(hospital => {
                let worst = 4; // مستوى غير معروف
                let worstLvl = '';
                byHospital[hospital].forEach(r => {
                    const lvl = ((r.risk_profile || {}).overall_risk_level || '').toLowerCase();
                    const rank = riskRank[lvl] !== undefined ? riskRank[lvl] : 4;
                    if (rank < worst) { worst = rank; worstLvl = lvl; }
                });
                hospitalRiskRank[hospital] = worst;
                hospitalWorstLevel[hospital] = worstLvl;
            });
            const riskBadgeColors = { critical: '#b71c1c', high: '#c62828', moderate: '#e65100', low: '#2e7d32' };
            const riskBadgeLabels = { critical: __('Critical'), high: __('High'), moderate: __('Moderate'), low: __('Low') };

            // فواصل مجموعات الخطر بين البطاقات: الحرجة → العالية → المتوسطة → المنخفضة → الأخرى
            const sortedHospitals = Object.keys(byHospital)
                .sort((a, b) => hospitalRiskRank[a] - hospitalRiskRank[b] || a.localeCompare(b));
            let currentRank = -1;
            sortedHospitals.forEach(hospital => {
                const rank = hospitalRiskRank[hospital];
                if (rank !== currentRank) {
                    currentRank = rank;
                    const groupLvl = hospitalWorstLevel[hospital] || '';
                    const groupCount = sortedHospitals.filter(h => hospitalRiskRank[h] === rank).length;
                    html += _riskGroupHeader(groupLvl, groupCount);
                }
                const reports = byHospital[hospital];
                const worstLvl = hospitalWorstLevel[hospital] || '';
                const badgeColor = riskBadgeColors[worstLvl] || '#888';
                const badgeLabel = riskBadgeLabels[worstLvl] || '';
                html += '<div class="card" style="margin-bottom:0.8rem;padding:0.6rem 0.8rem;">';
                html += '<h3 style="margin:0 0 0.5rem 0;color:#1a237e;font-size:0.95rem;display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">' + esc(hospital);
                if (badgeLabel) {
                    html += '<span style="font-size:0.66rem;font-weight:700;color:#fff;background:' + badgeColor + ';border-radius:10px;padding:0.1rem 0.55rem;">' + badgeLabel + '</span>';
                }
                html += '<span style="font-weight:400;font-size:0.78rem;color:#888;">(' + reports.length + ')</span></h3>';

                reports.sort((a, b) => a.month.localeCompare(b.month)).forEach(r => {
                    const s = r.summary || {};
                    const score = s.overall_assessment || '';
                    const rp = r.risk_profile || {};
                    const mp = r.morbidity_profile || {};
                    const recs = r.recommendations || [];
                    const cls = r.classifications || [];

                    const deliveries = rp.total_deliveries || mp.total_deliveries || 0;
                    const csRate = cls.find(c => c.indicator_code === 'rate_cs');
                    const mmrRate = cls.find(c => c.indicator_code === 'rate_mmr');
                    const smmRate = cls.find(c => c.indicator_code === 'rate_smm');
                    const nmrRate = cls.find(c => c.indicator_code === 'rate_nmr');

                    html += '<div style="margin:0.4rem 0;padding:0.6rem 0.7rem;background:#fafafa;border-left:3px solid ' + _riskColor(rp.overall_risk_level) + ';border-radius:4px;">';

                    // ── Header row: month + score + risk + deliveries ──
                    html += '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.3rem;margin-bottom:0.3rem;">';
                    html += '<div style="display:flex;align-items:center;gap:0.5rem;">';
                    html += '<strong style="font-size:0.85rem;">' + r.month + '</strong>';
                    html += _scoreBadge(score);
                    html += '</div>';
                    html += '<span style="display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap;">';
                    html += '<span style="font-size:0.72rem;color:#888;">Deliveries: ' + deliveries + '</span>';
                    if (cls.length) html += '<span style="font-size:0.72rem;color:#888;">' + cls.length + ' indicators</span>';
                    html += '<a href="#" data-hosp="' + esc(r.hospital) + '" data-month="' + r.month + '" onclick="openBatchDetail(this);return false;" style="font-size:0.7rem;color:#1565c0;text-decoration:underline;white-space:nowrap;">' + __('Open Details') + '</a>';
                    html += '</span>';
                    html += '</div>';

                    // ── Key indicator pills ──
                    let pills = '';
                    if (csRate) pills += _pill('CS Rate', (csRate.value != null ? Number(csRate.value).toFixed(1) : '--') + csRate.unit.replace('%',''), csRate.color);
                    if (mmrRate) pills += _pill('MMR', (mmrRate.value != null ? Number(mmrRate.value).toFixed(0) : '--'), mmrRate.color);
                    if (smmRate) pills += _pill('SMM Rate', (smmRate.value != null ? Number(smmRate.value).toFixed(1) : '--') + '%', smmRate.color);
                    if (nmrRate) pills += _pill('NMR', (nmrRate.value != null ? Number(nmrRate.value).toFixed(1) : '--'), nmrRate.color);
                    html += '<div style="display:flex;gap:0.3rem;flex-wrap:wrap;margin-bottom:0.3rem;">' + pills + '</div>';

                    // ── Key findings ──
                    if (s.key_findings && s.key_findings.length) {
                        html += '<div style="margin:0.2rem 0;">';
                        s.key_findings.forEach(f => {
                            html += '<div style="font-size:0.74rem;color:#555;padding:0.05rem 0;padding-left:0.6rem;">▸ ' + esc(f) + '</div>';
                        });
                        html += '</div>';
                    }

                    // ── Risk profile metrics (critical/high only) ──
                    if (rp.metrics && rp.metrics.length) {
                        const bad = rp.metrics.filter(m => m.severity === 'critical' || m.severity === 'high');
                        if (bad.length) {
                            html += '<details style="margin:0.3rem 0;font-size:0.74rem;">';
                            html += '<summary style="cursor:pointer;color:' + _riskColor('critical') + ';font-weight:600;font-size:0.76rem;">Risk Metrics (' + bad.length + ' critical/high)</summary>';
                            bad.forEach(m => {
                                const sevColor = _riskColor(m.severity);
                                html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:0.1rem 0.6rem;background:' + sevColor + '08;border-left:2px solid ' + sevColor + ';margin:0.15rem 0;border-radius:2px;">';
                                html += '<span style="color:#333;">' + esc(m.metric_name) + ': <strong>' + (m.value != null ? Number(m.value).toFixed(1) : '--') + m.unit + '</strong></span>';
                                html += '<span style="font-size:0.7rem;color:' + sevColor + ';font-weight:600;">' + m.severity + '</span>';
                                html += '</div>';
                            });
                            html += '</details>';
                        }
                    }

                    // ── Morbidity profile key data ──
                    if (mp.maternal_deaths > 0 || mp.mortality_preventability_signals?.length) {
                        html += '<div style="margin:0.2rem 0;padding:0.2rem 0.5rem;background:#b71c1c08;border-left:2px solid #b71c1c;border-radius:2px;font-size:0.74rem;">';
                        if (mp.maternal_deaths > 0) {
                            html += '<div style="font-weight:600;color:#b71c1c;">Maternal Deaths: ' + mp.maternal_deaths + '</div>';
                        }
                        if (mp.mortality_preventability_signals?.length) {
                            mp.mortality_preventability_signals.forEach(sig => {
                                html += '<div style="color:#555;padding:0.05rem 0;">⚠ ' + esc(sig) + '</div>';
                            });
                        }
                        html += '</div>';
                    }

                    // ── Recommendations ──
                    if (recs.length) {
                        html += '<details style="margin:0.3rem 0;font-size:0.74rem;">';
                        html += '<summary style="cursor:pointer;color:#1a237e;font-weight:600;font-size:0.76rem;">Recommendations (' + recs.length + ')</summary>';
                        recs.forEach(rec => {
                            const pColor = _riskColor(rec.priority);
                            html += '<div style="margin:0.2rem 0;padding:0.3rem 0.5rem;background:' + pColor + '06;border-left:2px solid ' + pColor + ';border-radius:2px;">';
                            html += '<div style="display:flex;justify-content:space-between;align-items:center;gap:0.3rem;">';
                            html += '<strong style="font-size:0.74rem;color:#333;">' + esc(rec.title) + '</strong>';
                            html += '<span style="font-size:0.65rem;font-weight:600;color:' + pColor + ';text-transform:uppercase;">' + rec.priority + '</span>';
                            html += '</div>';
                            if (rec.description) {
                                html += '<div style="font-size:0.72rem;color:#555;margin:0.1rem 0;">' + esc(rec.description) + '</div>';
                            }
                            if (rec.action_items?.length) {
                                html += '<div style="font-size:0.7rem;color:#666;padding:0.1rem 0;">Actions: ' + esc(rec.action_items.join('; ')) + '</div>';
                            }
                            if (rec.data_reliable === false) {
                                html += '<span style="font-size:0.65rem;color:#c62828;">⚠ Data may be unreliable</span>';
                            }
                            html += '</div>';
                        });
                        html += '</details>';
                    }

                    // ── Overview / risk assessment text ──
                    if (s.risk_assessment || s.morbidity_assessment) {
                        html += '<details style="margin:0.3rem 0;font-size:0.74rem;">';
                        html += '<summary style="cursor:pointer;color:#1a237e;font-weight:600;font-size:0.76rem;">Assessments</summary>';
                        if (s.overview) html += '<div style="font-size:0.74rem;color:#555;margin:0.15rem 0;padding:0.2rem 0.5rem;background:#e8eaf608;border-radius:2px;">' + esc(s.overview) + '</div>';
                        if (s.risk_assessment) html += '<div style="font-size:0.74rem;color:#555;margin:0.15rem 0;padding:0.2rem 0.5rem;background:#fff3e008;border-left:2px solid #e65100;border-radius:2px;">' + esc(s.risk_assessment) + '</div>';
                        if (s.morbidity_assessment) html += '<div style="font-size:0.74rem;color:#555;margin:0.15rem 0;padding:0.2rem 0.5rem;background:#fce4ec08;border-left:2px solid #c62828;border-radius:2px;">' + esc(s.morbidity_assessment) + '</div>';
                        html += '</details>';
                    }

                    // ── All classification details ──
                    if (cls.length) {
                        html += '<details style="margin:0.3rem 0;font-size:0.74rem;">';
                        html += '<summary style="cursor:pointer;color:#555;font-size:0.74rem;">All Classifications (' + cls.length + ' indicators)</summary>';
                        cls.forEach(c => {
                            html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:0.1rem 0.5rem;border-bottom:1px solid #eee;">';
                            html += '<span style="color:#333;">' + esc(c.rate_name) + '</span>';
                            html += '<span><span style="color:' + c.color + ';font-weight:600;">' + (c.value != null ? Number(c.value).toFixed(1) : '--') + '</span> <span style="font-size:0.7rem;color:' + c.color + ';">' + esc(c.label) + '</span></span>';
                            html += '</div>';
                        });
                        html += '</details>';
                    }

                    html += '</div>';
                });
                html += '</div>';
            });

            container.innerHTML = html;
        }

        export function showRuleFailureDetail(ruleCode, hospital, month) {
            fetch(API() + '/analysis/rule-failures?rule_code=' + encodeURIComponent(ruleCode) + '&month=' + encodeURIComponent(month))
                .then(r => r.json())
                .then(resp => {
                    const data = resp.data || resp;
                    let inner = '';
                    if (!data.length) {
                        inner = '<p style="color:#888;">No rule failure details found.</p>';
                    } else {
                        inner = '<table style="font-size:0.8rem;"><thead><tr><th>Rule</th><th>Description</th><th>Severity</th><th>Type</th><th>Details</th></tr></thead><tbody>';
                        data.forEach(d => {
                            const sevColor = d.severity === 'CRITICAL' ? '#b71c1c' : d.severity === 'HIGH' ? '#c62828' : d.severity === __('MEDIUM') ? '#e65100' : '#2e7d32';
                            inner += '<tr><td>' + d.rule_code + '</td><td>' + d.rule_description + '</td><td><span style="color:' + sevColor + ';">' + d.severity + '</span></td><td>' + (d.rule_type || '') + '</td><td style="font-size:0.75rem;">' + (d.details || '') + '</td></tr>';
                        });
                        inner += '</tbody></table>';
                    }
                    document.getElementById('modalTitle').textContent = 'Rule Failure: ' + ruleCode;
                    document.getElementById('modalBody').innerHTML = inner;
                    document.getElementById('detailModal').classList.add('show');
                })
                .catch(err => {
                    document.getElementById('modalTitle').textContent = 'Error';
                    document.getElementById('modalBody').innerHTML = '<p style="color:red;">' + err.message + '</p>';
                    document.getElementById('detailModal').classList.add('show');
                });
        }

        export function showModal(html) {
            document.getElementById('modalTitle').innerHTML = 'AI Report Detail';
            document.getElementById('modalBody').innerHTML = html;
            document.getElementById('detailModal').classList.add('show');
        }
        export function closeModal() { document.getElementById('detailModal').classList.remove('show'); }
        document.getElementById('detailModal').addEventListener('click', function(e) { if (e.target === this) closeModal(); });
        document.getElementById('ruleEditModal').addEventListener('click', function(e) { if (e.target === this) closeRuleModal(); });
        document.addEventListener('keydown', function(e) { if (e.key === 'Escape') { closeModal(); closeRuleModal(); } });

