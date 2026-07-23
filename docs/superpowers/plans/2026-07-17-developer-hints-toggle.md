# Developer Hints Toggle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a checkbox in Settings → Control to show/hide Source code references below each setting, and expand all hints with Calculation + Purpose + Source sections.

**Architecture:** localStorage toggle + global `window._showDevHints` + CSS class `.dev-hint` on Source elements. Calculation and Purpose always visible; only Source toggles.

**Tech Stack:** vanilla JS, HTML inline, localStorage

## Global Constraints

- No backend API changes — pure frontend
- localStorage key: `dev_hints_enabled`
- Class name for togglable elements: `.dev-hint`
- Default state: enabled (`true`)

---

### Task 1: Checkbox + JS Logic + Hint Expansion (Quality, Confidence, Thresholds, Rules)

**Files:**
- Modify: `static/tabs/settings.html`
- Modify: `static/js/settings.js`

**Interfaces:**
- Consumes: existing `settings.html` structure, existing `settings.js` functions (`loadControlSettings`, `showSettingsTab`, `loadAllSettings`)
- Produces: `window._showDevHints`, `window.initDevHints()`, `window.toggleDevHints(bool)`, `applyDevHintsVisibility()`

- [ ] **Step 1: Add checkbox in Control tab (`settings.html`)**

Insert after Structured Logging div (line 696), before Analysis Months div (line 697):

```html
                        <div style="background:#fafafa;padding:0.8rem;border-radius:6px;max-width:700px;margin-top:0.8rem;">
                            <label style="display:flex;align-items:flex-start;gap:0.6rem;cursor:pointer;">
                                <input type="checkbox" id="cfg_dev_hints" onchange="toggleDevHints(this.checked)" style="margin-top:0.2rem;width:18px;height:18px;">
                                <div>
                                    <strong>Show Developer Hints</strong><br>
                                    <span style="font-size:0.8rem;color:#666;">When enabled, displays source code file references and function names below each setting control. Disable before production deployment to hide internal implementation details.</span>
                                </div>
                            </label>
                        </div>
```

- [ ] **Step 2: Add JS functions at end of `settings.js`**

```javascript
        export function initDevHints() {
            const enabled = localStorage.getItem('dev_hints_enabled') !== 'false';
            window._showDevHints = enabled;
            const cb = document.getElementById('cfg_dev_hints');
            if (cb) cb.checked = enabled;
            applyDevHintsVisibility();
        }

        export function toggleDevHints(show) {
            window._showDevHints = show;
            localStorage.setItem('dev_hints_enabled', show ? 'true' : 'false');
            applyDevHintsVisibility();
        }

        function applyDevHintsVisibility() {
            document.querySelectorAll('.dev-hint').forEach(function(el) {
                el.style.display = window._showDevHints ? '' : 'none';
            });
        }
```

- [ ] **Step 3: Hook `initDevHints()` into existing functions**

In `loadControlSettings()` (line 1233), add `initDevHints();` at the end, before the closing `}`.

In `showSettingsTab('control')` — the `showSettingsTab` function already calls `loadControlSettings()` when name === 'control', so the hook in `loadControlSettings` covers it.

Also add to `loadAllSettings()` (line 716) — add `initDevHints();` at the end.

- [ ] **Step 4: Expand hints in Quality Score section**

Replace lines 65-66 (blue info box):
```html
                        <div style="background:#f0f4ff;padding:0.6rem;border-radius:6px;margin-bottom:0.8rem;font-size:0.78rem;color:#555;">
                            <strong>Outlier Multiplier:</strong> Multiplies the outlier ratio before capping at 1.0. At multiplier 2.0, 50% outliers = max penalty.<br>
                            <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/scoring.py:91-97</code> &rarr; <code>min(1.0, ratio * multiplier)</code></span><br>
                            <strong>Severity Weights:</strong> Used in consistency calculation. HIGH=3 means one HIGH failure = three LOW failures.<br>
                            <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/scoring.py:70-84</code> &rarr; <code>_calc_consistency()</code></span>
                        </div>
```

Replace hint texts for each Quality slider (lines 31, 39, 47, 55, 75, 83, 91, 99):

Line 31 (Rule Compliance):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> passed_rules / total_rules. 60 rules checked, 58 passed → 96.7%.<br>
                                    <strong>Purpose:</strong> Controls how much the rule compliance rate influences the final quality score.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/scoring.py:51-56</code> &rarr; <code>_calc_rule_compliance()</code></span>
                                </div>
```

Line 39 (Completeness):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> filled_indicators / active_indicators. 45 of 50 filled → 90%.<br>
                                    <strong>Purpose:</strong> Controls how much data completeness influences the final quality score. Missing values = lower score.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/scoring.py:59-63</code> &rarr; <code>_calc_completeness()</code></span>
                                </div>
```

Line 47 (Consistency):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> 1 - (weighted_failures / weighted_total). HIGH failures weighted by severity_high (3), LOW by severity_low (1).<br>
                                    <strong>Purpose:</strong> Controls how much rule failure severity (weighted by severity) influences the quality score.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/scoring.py:66-84</code> &rarr; <code>_calc_consistency()</code></span>
                                </div>
```

Line 55 (Outlier Penalty):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> (1 - outlier_penalty) × W4. Penalty = min(1.0, outlier_ratio × outlier_multiplier).<br>
                                    <strong>Purpose:</strong> Controls how much statistical outliers (anomalies) reduce the final quality score.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/scoring.py:24-29</code> &rarr; formula <code>raw_score = ... + (1.0 - outlier_penalty) × w_op</code></span>
                                </div>
```

Line 75 (Outlier Multiplier):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> min(1.0, (outlier_count / total_anomalies) × multiplier). At 2.0, 50% outliers = 100% penalty.<br>
                                    <strong>Purpose:</strong> Amplifies or dampens the outlier penalty. Higher values = fewer outliers needed to max the penalty.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/scoring.py:87-97</code> &rarr; <code>_calc_outlier_penalty()</code></span>
                                </div>
```

Line 83 (Severity HIGH):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> In consistency formula: 1 - (Σ fail_weight × severity_importance / Σ total_weight). HIGH=3 means ×3 impact.<br>
                                    <strong>Purpose:</strong> Sets relative importance of HIGH severity rule failures vs MEDIUM and LOW.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/scoring.py:70-74</code> &rarr; <code>severity_weights</code></span>
                                </div>
```

Line 91 (Severity MEDIUM):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> Same as HIGH above, but with MEDIUM weight. Default 2 = twice the impact of LOW.<br>
                                    <strong>Purpose:</strong> Sets relative importance of MEDIUM severity rule failures in consistency score.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/scoring.py:70-74</code> &rarr; <code>severity_weights</code></span>
                                </div>
```

Line 99 (Severity LOW):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> Baseline weight = 1. All severities are relative to LOW.<br>
                                    <strong>Purpose:</strong> Baseline severity weight. Set HIGH higher to make critical rules dominate the consistency score.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/scoring.py:70-74</code> &rarr; <code>severity_weights</code></span>
                                </div>
```

- [ ] **Step 5: Expand hints in Confidence Score section**

Replace line 109 (blue box):
```html
                        <div style="background:#f0f4ff;padding:0.8rem;border-radius:6px;margin-bottom:1rem;font-size:0.8rem;color:#333;line-height:1.6;">
                            <strong>Formula:</strong> confidence = sum(signal_score × signal_weight) × 100<br>
                            <strong>Appears in:</strong> Detail Modal (Priority Verification table, by_level badges)<br>
                            <span class="dev-hint"><strong>Source:</strong> <code>app/engine/confidence/confidence.py:468</code> &rarr; called from <code>app/engine/pipeline.py:145</code></span><br>
                            <strong>Must sum to 1.0</strong> &mdash; enforced on save.
                        </div>
```

Replace each Confidence hint (lines 120, 128, 136, 144, 152):

Line 120 (Rule Compliance):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> Rules referencing this specific indicator only. Pass/total of relevant rules (e.g. R003 for Age 25-29).<br>
                                    <strong>Purpose:</strong> How much indicator-specific rule compliance contributes to overall confidence score.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/confidence/confidence.py</code> &rarr; signal computation</span>
                                </div>
```

Line 128 (Historical):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> Z-score of current value vs this hospital's own historical values for the same indicator.<br>
                                    <strong>Purpose:</strong> Flags values that deviate from the hospital's normal historical pattern.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/confidence/confidence.py</code> &rarr; historical signal</span>
                                </div>
```

Line 136 (Cross-Hospital):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> Z-score of this hospital's value vs all other hospitals' values for the same indicator.<br>
                                    <strong>Purpose:</strong> Flags values that are outliers compared to peer hospitals.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/confidence/confidence.py</code> &rarr; cross-hospital signal</span>
                                </div>
```

Line 144 (Trend):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> Linear regression projection error. How far actual values deviate from the expected trend line.<br>
                                    <strong>Purpose:</strong> Detects values that break an established upward/downward trend.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/confidence/confidence.py</code> &rarr; trend signal</span>
                                </div>
```

Line 152 (Completeness):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> Are all child/sub-indicators present? For "Total Deliveries", checks sub-codes 2.a, 2.b, etc.<br>
                                    <strong>Purpose:</strong> Flags missing sub-components that could make the indicator unreliable.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/confidence/confidence.py</code> &rarr; completeness signal</span>
                                </div>
```

- [ ] **Step 6: Expand hints in Thresholds section**

Replace line 166 (blue box):
```html
                        <div style="background:#f0f4ff;padding:0.8rem;border-radius:6px;margin-bottom:1rem;font-size:0.8rem;color:#333;line-height:1.6;">
                            <strong>Appears in:</strong> Detail Modal (badge colors, by_level counts, Priority Verification table)<br>
                            <span class="dev-hint"><strong>Source:</strong> <code>app/engine/confidence/confidence.py:349-355</code> &rarr; <code>_compute_level()</code></span>
                        </div>
```

Replace lines 176, 184, 192 (hint texts for HIGH/MEDIUM/LOW):

Line 176 (HIGH >=):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> score ≥ this value → HIGH level. Default 80 = green badge.<br>
                                    <strong>Purpose:</strong> Cutoff for HIGH confidence level. Indicators at or above this score are considered reliable.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/confidence/confidence.py:349-355</code> &rarr; <code>_compute_level()</code></span>
                                </div>
```

Line 184 (MEDIUM >=):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> MEDIUM ≤ score < HIGH cutoff → MEDIUM level. Orange badge.<br>
                                    <strong>Purpose:</strong> Cutoff for MEDIUM confidence level. Indicators between MEDIUM and HIGH need attention.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/confidence/confidence.py:349-355</code> &rarr; <code>_compute_level()</code></span>
                                </div>
```

Line 192 (LOW >=):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> LOW ≤ score < MEDIUM cutoff → LOW level. Light red badge.<br>
                                    <strong>Purpose:</strong> Cutoff for LOW confidence level. Below this → CRITICAL (dark red).<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/confidence/confidence.py:349-355</code> &rarr; <code>_compute_level()</code></span>
                                </div>
```

Replace line 198 (Z-Score blue box):
```html
                        <div style="background:#f0f4ff;padding:0.6rem;border-radius:6px;margin-bottom:0.8rem;font-size:0.78rem;color:#555;">
                            <strong>Controls:</strong> Outlier detection sensitivity. Lower = more values flagged as outliers.<br>
                            <span class="dev-hint"><strong>Source:</strong> <code>app/config_utils.py:10</code> &rarr; referenced by <code>app/engine/anomaly/zscore.py:62,105</code>, <code>app/engine/anomaly/trends.py:241</code>, <code>app/engine/confidence/confidence.py</code></span>
                        </div>
```

Line 208 (Z-Score Threshold slider):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> |z-score| > threshold → flagged as outlier. z = (value - mean) / std_dev.<br>
                                    <strong>Purpose:</strong> Controls how many standard deviations from the mean a value must be to be flagged anomalous.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/zscore.py:62,105</code> &rarr; <code>is_outlier = abs(z) > z_thresh</code></span>
                                </div>
```

- [ ] **Step 7: Expand hints in Rules section**

Each Rules hint currently follows pattern `rules.py:LINE → FUNCTION. DESCRIPTION`.

Replace all 8 rule hints (lines 227, 235, 243, 251, 259, 267, 275):

Line 227 (Equality Tolerance):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> |a - b| ≤ tolerance → PASS. 187 vs 186.99 passes at tolerance 0.01.<br>
                                    <strong>Purpose:</strong> Controls floating-point precision for equality checks between reported and derived values.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/rules.py:92</code> &rarr; <code>_eq()</code></span>
                                </div>
```

Line 235 (C-Section Rate):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> (C-Sections / Total Deliveries) × 100 > threshold → FAIL.<br>
                                    <strong>Purpose:</strong> Rule R041. Flags implausibly high C-section rates that may indicate data error.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/rules.py:273</code> &rarr; <code>R041</code></span>
                                </div>
```

Line 243 (NVD Rate):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> NVD / Total Deliveries × 100 < threshold → FAIL.<br>
                                    <strong>Purpose:</strong> Rule R042. Flags implausibly low normal vaginal delivery rates.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/rules.py:274</code> &rarr; <code>R042</code></span>
                                </div>
```

Line 251 (Month Over):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> current_month > previous_month × factor → FAIL. 200 > 100 × 1.5 = FAIL at 1.5.<br>
                                    <strong>Purpose:</strong> Rules R051,R053. Flags sudden spikes (> factor×) in any indicator vs previous month.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/rules.py:288</code> &rarr; <code>R051,R053</code></span>
                                </div>
```

Line 259 (Month Under):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> current_month < previous_month × factor → FAIL. 30 < 100 × 0.5 = FAIL at 0.5.<br>
                                    <strong>Purpose:</strong> Rule R052. Flags sudden drops (< factor×) in any indicator vs previous month.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/rules.py:289</code> &rarr; <code>R052</code></span>
                                </div>
```

Line 267 (Maternal Over):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> maternal_deaths > previous_month × factor → CRITICAL FAIL.<br>
                                    <strong>Purpose:</strong> Rule R054. Critical-level flag when maternal deaths spike > factor× vs previous month.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/rules.py:291</code> &rarr; <code>R054</code></span>
                                </div>
```

Line 275 (Neonatal Over):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
                                    <strong>Calculation:</strong> neonatal_deaths > previous_month × factor → CRITICAL FAIL.<br>
                                    <strong>Purpose:</strong> Rule R055. Critical-level flag when neonatal deaths spike > factor× vs previous month.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/rules.py:292</code> &rarr; <code>R055</code></span>
                                </div>
```

- [ ] **Step 8: Verify**

1. Load Settings → Control tab — see "Show Developer Hints" checkbox, default checked.
2. Uncheck — all `.dev-hint` elements disappear (Source references hidden).
3. Check — all `.dev-hint` elements reappear.
4. Refresh page — state persists from localStorage.
5. Navigate to Quality Score tab — Calculation + Purpose visible, Source controlled by checkbox.
6. Repeat for all 10 sections.

---

### Task 2: Expand Hints for Clinical, Risk, Trends, Rate Benchmarks

**Files:**
- Modify: `static/tabs/settings.html` (remaining sections)

- [ ] **Step 1: Expand hints in Clinical section**

Replace line 284 (blue box):
```html
                        <div style="background:#f0f4ff;padding:0.8rem;border-radius:6px;margin-bottom:1rem;font-size:0.8rem;color:#333;line-height:1.6;">
                            <strong>Appears in:</strong> Clinical Assessment section of Detail Modal<br>
                            <span class="dev-hint"><strong>Source:</strong> <code>app/engine/clinical/clinical_thresholds.py</code> &rarr; rate classification (Elevated / High / Critical)</span>
                        </div>
```

Replace line 373 (bottom note):
```html
                            <div style="font-size:0.75rem;color:#666;padding:0.4rem;">
                                Higher values in the "Elevated/High/Critical" columns mean thresholds are less strict (i.e. require more extreme rates to flag).<br>
                                <span class="dev-hint"><strong>Calculation:</strong> rate ≤ Elevated → Normal, rate ≤ High → Elevated, rate ≤ Critical → High, rate > Critical → Critical.<br>
                                <strong>Source:</strong> <code>app/engine/clinical/clinical_thresholds.py</code> &rarr; threshold comparison</span>
                            </div>
```

- [ ] **Step 2: Expand hints in Risk Profile section**

Replace line 381 (blue box):
```html
                        <div style="background:#f0f4ff;padding:0.8rem;border-radius:6px;margin-bottom:1rem;font-size:0.8rem;color:#333;line-height:1.6;">
                            <strong>Appears in:</strong> Risk Profile section of Detail Modal<br>
                            <span class="dev-hint"><strong>Source:</strong> <code>app/engine/clinical/clinical_risk.py</code> &rarr; risk classification (Moderate / High / Critical)</span>
                        </div>
```

Replace hint lines 391, 399:

Line 391 (Peer Multiplier High):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> hospital_value > peer_avg × multiplier → HIGH risk.<br>
                                    <strong>Purpose:</strong> Sets how much above peer average a value must be to flag HIGH risk.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/clinical/clinical_risk.py</code> &rarr; peer comparison logic</span>
                                </div>
```

Line 399 (Peer Multiplier Critical):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> hospital_value > peer_avg × multiplier → CRITICAL risk.<br>
                                    <strong>Purpose:</strong> Sets how much above peer average a value must be to flag CRITICAL risk.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/clinical/clinical_risk.py</code> &rarr; peer comparison logic</span>
                                </div>
```

- [ ] **Step 3: Expand hints in Trends section**

Replace line 431 (blue box):
```html
                        <div style="background:#f0f4ff;padding:0.8rem;border-radius:6px;margin-bottom:1rem;font-size:0.8rem;color:#333;line-height:1.6;">
                            <strong>Appears in:</strong> Trend Chart, flags, recommendations<br>
                            <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/trends.py</code> &rarr; slope classification, severity, finding generation</span>
                        </div>
```

Replace all Trends hints (lines 441, 449, 457, 465, 473, 483, 491, 499, 507, 515):

Line 441 (Slope Stable):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> |slope| ≤ this value → STABLE. e.g. 1.5% means "no significant change".<br>
                                    <strong>Purpose:</strong> Threshold below which a trend slope is considered flat/stable.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/trends.py</code> &rarr; slope classification</span>
                                </div>
```

Line 449 (Slope Low):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> slope above Stable but below this → LOW severity trend.<br>
                                    <strong>Purpose:</strong> Lower bound for LOW severity trend classification.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/trends.py</code> &rarr; severity classification</span>
                                </div>
```

Line 457 (Slope Moderate):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> slope above Low but below this → MODERATE severity trend.<br>
                                    <strong>Purpose:</strong> Lower bound for MODERATE severity trend classification.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/trends.py</code> &rarr; severity classification</span>
                                </div>
```

Line 465 (Slope High):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> slope above this → HIGH severity trend.<br>
                                    <strong>Purpose:</strong> Threshold above which a trend is classified as HIGH severity.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/trends.py</code> &rarr; severity classification</span>
                                </div>
```

Line 473 (R-Squared):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> R² < threshold → trend not meaningful. R² measures how well data fits the linear regression.<br>
                                    <strong>Purpose:</strong> Minimum R² required to consider a linear trend as statistically meaningful.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/trends.py</code> &rarr; trend significance check</span>
                                </div>
```

Line 483 (Finding Slope):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> absolute slope ≥ this value → trigger a trend finding.<br>
                                    <strong>Purpose:</strong> Minimum slope magnitude to generate a trend finding/recommendation.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/trends.py</code> &rarr; finding generation</span>
                                </div>
```

Line 491 (Finding Consecutive):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> N consecutive months in same direction (up/down) → trigger finding.<br>
                                    <strong>Purpose:</strong> Number of consecutive directional months needed to generate a finding.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/trends.py</code> &rarr; finding generation</span>
                                </div>
```

Line 499 (Finding Deviation):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> |actual - expected| / expected × 100 ≥ this % → trigger finding.<br>
                                    <strong>Purpose:</strong> Minimum percentage deviation from expected value to trigger a finding.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/trends.py</code> &rarr; finding generation</span>
                                </div>
```

Line 507 (Finding CV):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> CV = (std_dev / mean) × 100. CV ≥ this → trigger finding.<br>
                                    <strong>Purpose:</strong> Minimum coefficient of variation (volatility) to trigger a finding.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/trends.py</code> &rarr; finding generation</span>
                                </div>
```

Line 515 (Finding R-Squared):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> R² ≥ this value → generate trend finding (need good fit).<br>
                                    <strong>Purpose:</strong> Minimum R² for a trend to generate a finding — ensures the trend line fits well.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/trends.py</code> &rarr; finding generation</span>
                                </div>
```

- [ ] **Step 4: Expand hints in Rate Benchmarks section**

Replace line 524 (blue box):
```html
                        <div style="background:#f0f4ff;padding:0.8rem;border-radius:6px;margin-bottom:1rem;font-size:0.8rem;color:#333;line-height:1.6;">
                            <strong>Appears in:</strong> Anomaly Detection section of Detail Modal, outlier flagging<br>
                            <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/zscore.py</code> &rarr; z-score calculation using expected rates per indicator</span>
                        </div>
```

Replace each Rate Benchmark hint (lines 534, 542, 550, 558, 566, 574, 582):

Line 534 (C-Section):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> z = (actual_rate - benchmark) / std_dev. |z| > z_threshold → outlier.<br>
                                    <strong>Purpose:</strong> Expected proportion of C-sections among all deliveries. Used as benchmark for z-score.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/zscore.py</code> &rarr; expected rate for C-Section indicator</span>
                                </div>
```

Line 542 (MMR):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> z = (actual_mmr - benchmark) / std_dev. |z| > z_threshold → outlier.<br>
                                    <strong>Purpose:</strong> Expected maternal deaths per 100,000 live births. Used as benchmark for z-score.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/zscore.py</code> &rarr; expected rate for MMR indicator</span>
                                </div>
```

Line 550 (NMR):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> Same z-score logic. Expected neonatal deaths per 1,000 live births.<br>
                                    <strong>Purpose:</strong> Expected NMR rate used as benchmark for z-score outlier detection.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/zscore.py</code> &rarr; expected rate for NMR indicator</span>
                                </div>
```

Line 558 (Preterm):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> Same z-score logic. Expected % of preterm births among all deliveries.<br>
                                    <strong>Purpose:</strong> Expected preterm birth rate used as benchmark for z-score outlier detection.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/zscore.py</code> &rarr; expected rate for Preterm indicator</span>
                                </div>
```

Line 566 (SMM):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> Same z-score logic. Expected severe maternal morbidity rate.<br>
                                    <strong>Purpose:</strong> Expected SMM rate used as benchmark for z-score outlier detection.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/zscore.py</code> &rarr; expected rate for SMM indicator</span>
                                </div>
```

Line 574 (Stillbirth):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> Same z-score logic. Expected stillbirths per 1,000 births.<br>
                                    <strong>Purpose:</strong> Expected stillbirth rate used as benchmark for z-score outlier detection.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/zscore.py</code> &rarr; expected rate for Stillbirth indicator</span>
                                </div>
```

Line 582 (NICU):
```html
                                <div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:205px;">
                                    <strong>Calculation:</strong> Same z-score logic. Expected % of NICU admissions among all deliveries.<br>
                                    <strong>Purpose:</strong> Expected NICU admission rate used as benchmark for z-score outlier detection.<br>
                                    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/anomaly/zscore.py</code> &rarr; expected rate for NICU indicator</span>
                                </div>
```

- [ ] **Step 5: Verify**

1. Load each settings section — all hints show Calculation + Purpose + Source.
2. Toggle "Show Developer Hints" off — Source lines disappear, Calculation + Purpose remain.
3. Toggle on — Source lines reappear.
4. Refresh — state preserved.
