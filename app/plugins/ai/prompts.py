from typing import List, Dict, Optional

from app.plugins.ai.providers import AI_MAX_RECOMMENDATIONS


def _build_prompt(
    values: Dict[str, float],
    classifications: List,
    risk_profile,
    morbidity_profile,
    quality_score: Optional[float],
) -> str:
    lines = []
    lines.append("You are a maternal health expert analyzing a hospital's monthly data.")
    lines.append("Generate actionable recommendations based on the following analysis.")
    lines.append("")

    ind_list = "\n".join([f"  {k}: {v}" for k, v in sorted(values.items()) if v is not None])
    lines.append(f"## Indicator Values\n{ind_list}\n")

    if classifications:
        lines.append("## Classifications")
        for c in classifications:
            lines.append(f"  {c.indicator_code} ({c.rate_name}): {c.value}{c.unit} \u2192 {c.classification}")
        lines.append("")

    if risk_profile:
        lines.append(f"## Risk Profile\n  Overall: {risk_profile.overall_risk_level}")
        for m in getattr(risk_profile, "metrics", []):
            lines.append(f"  {m.metric_name}: {m.value}{m.unit} ({m.interpretation}) [{m.severity}]")
        lines.append("")

    if morbidity_profile:
        lines.append(f"## Morbidity Profile\n  SMM: {morbidity_profile.total_smm}, Deaths: {morbidity_profile.maternal_deaths}")
        for signal in getattr(morbidity_profile, "mortality_preventability_signals", []):
            lines.append(f"  Preventability signal: {signal}")
        lines.append("")

    if quality_score is not None:
        lines.append(f"## Data Quality Score\n  {quality_score:.1f}/100\n")

    lines.append("""Return a JSON array of recommendation objects only (no markdown, no explanation).
Each object has these fields:
- category: str (e.g. "C-Section Management", "Maternal Mortality", "Data Quality")
- priority: str (one of "critical", "high", "medium", "low")
- title: str (short, max 80 chars)
- description: str (1-2 sentences explaining the issue)
- rationale: str (medical/public health rationale, 1-2 sentences)
- action_items: list[str] (3-6 specific actionable steps)
- indicators_monitored: list[str] (indicator codes that triggered this)

Analyze the numbers carefully:
- Check if rates exceed WHO thresholds (C-section >15%, SMM >2%, etc.)
- Look for data quality issues (missing values, zeros, inconsistencies)
- Consider risk profile severity
- Prioritize life-threatening conditions first

Return between 1 and """ + str(AI_MAX_RECOMMENDATIONS) + """ recommendations in order of priority.""")
    return "\n".join(lines)


def _build_executive_summary_prompt(
    hospital: str,
    month: str,
    values: Dict[str, float],
    quality_score: float,
    completeness: float,
    consistency: float,
    rule_compliance: float,
    outlier_penalty: float,
    rule_results: List,
    anomaly_results: List,
    trend_data: Dict,
    all_hospital_data: Dict,
    classifications: List = None,
    risk_profile=None,
    morbidity_profile=None,
) -> str:
    lines = []
    lines.append(f"You are a senior data quality analyst reviewing the monthly report for {hospital} ({month}).")
    lines.append("Write a concise executive narrative summary of the hospital's data quality status.")
    lines.append("Do NOT list individual recommendations. Write a flowing analytical report.")
    lines.append("")
    lines.append("## Quality Scores")
    lines.append(f"  Overall: {quality_score}/100")
    lines.append(f"  Completeness: {completeness}%")
    lines.append(f"  Consistency: {consistency}%")
    lines.append(f"  Rule Compliance: {rule_compliance}%")
    lines.append(f"  Outlier Penalty: {outlier_penalty}%")
    lines.append("")

    if rule_results:
        failed = [r for r in rule_results if getattr(r, 'status', None) and r.status.name == "FAIL"]
        passed = [r for r in rule_results if getattr(r, 'status', None) and r.status.name == "PASS"]
        lines.append("## Rule Engine Results")
        lines.append(f"  Total rules: {len(rule_results)}")
        lines.append(f"  Passed: {len(passed)}, Failed: {len(failed)}")
        for f in failed[:5]:
            desc = getattr(f, 'description', '') or getattr(f, 'details', '')
            code = getattr(f, 'rule_code', '')
            lines.append(f"  - {code}: {desc[:100]}")
        lines.append("")

    if anomaly_results:
        outliers = [a for a in anomaly_results if getattr(a, 'is_outlier', False)]
        if outliers:
            lines.append("## Outlier Detection")
            lines.append(f"  {len(outliers)} outlier(s) detected:")
            for o in outliers[:5]:
                name = getattr(o, 'rate_name', '') or getattr(o, 'indicator', '')
                z = getattr(o, 'z_score', '')
                lines.append(f"  - {name} (z={z})")
            lines.append("")

    if classifications:
        elevated = [c for c in classifications if getattr(c, 'classification', '') in ('high', 'critical')]
        if elevated:
            lines.append("## Clinical Threshold Analysis")
            lines.append(f"  {len(elevated)} indicator(s) at elevated clinical risk:")
            for c in elevated[:5]:
                lines.append(f"  - {getattr(c, 'rate_name', '') or getattr(c, 'indicator_code', '')}: {getattr(c, 'value', '')} ({getattr(c, 'classification', '')})")
            lines.append("")

    if risk_profile:
        rl = getattr(risk_profile, 'overall_risk_level', '')
        kf = getattr(risk_profile, 'key_findings', [])
        lines.append("## Risk Profile")
        if rl:
            lines.append(f"  Overall Risk Level: {rl}")
        if kf:
            for f in kf[:3]:
                lines.append(f"  - {f}")
        metrics = getattr(risk_profile, 'metrics', [])
        at_risk = [m for m in metrics if getattr(m, 'severity', '') in ('high', 'critical')]
        if at_risk:
            lines.append("  Elevated Risk Metrics:")
            for m in at_risk[:3]:
                lines.append(f"    - {getattr(m, 'metric_name', '')}: {getattr(m, 'severity', '')}")
        lines.append("")

    if morbidity_profile:
        smm = getattr(morbidity_profile, 'total_smm', 0)
        deaths = getattr(morbidity_profile, 'maternal_deaths', 0)
        kf = getattr(morbidity_profile, 'key_findings', [])
        lines.append("## Maternal Morbidity Profile")
        if smm is not None:
            lines.append(f"  Total SMM Events: {smm}")
        if deaths:
            lines.append(f"  Maternal Deaths: {deaths}")
        if kf:
            for f in kf[:3]:
                lines.append(f"  - {f}")
        lines.append("")

    if values:
        non_null = {k: v for k, v in values.items() if v is not None}
        if non_null:
            important = [(k, v) for k, v in sorted(non_null.items())][:10]
            if important:
                lines.append("## Key Indicator Values")
                for k, v in important:
                    lines.append(f"  {k}: {v}")
        lines.append("")

    if trend_data:
        lines.append("## Trend Analysis")
        for indicator, points in list(trend_data.items())[:5]:
            direction = "improving" if points.get("slope", 0) > 0 else "declining" if points.get("slope", 0) < 0 else "stable"
            lines.append(f"  {indicator}: {direction} (slope={points.get('slope', 0):.2f})")
        lines.append("")

    if all_hospital_data and len(all_hospital_data) > 1:
        lines.append("## Cross-Hospital Benchmarking")
        lines.append(f"  Compared to {len(all_hospital_data) - 1} other hospital(s)")
        lines.append("")

    lines.append("""Write a narrative executive summary covering:
1. Overall data quality status assessment
2. Most significant findings from the rule analysis
3. Patterns, trends, and relationships detected across indicators
4. Impact on data reliability and decision-making
5. Highest-priority actions for improvement
6. Overall assessment of data maturity and reporting performance

Write in clear, professional English. Keep it to 3-5 paragraphs. Do NOT use bullet points or numbered lists.
The summary should read like an executive analytical report written for hospital management — concise, insightful, and actionable.""")
    return "\n".join(lines)


def _build_root_cause_prompt(report_data: dict) -> str:
    lines = []
    lines.append("You are a maternal health data quality expert. Analyze the Root Cause Analysis report below and provide actionable recommendations.")
    lines.append("Focus on data quality improvements, confidence gaps, and operational fixes for the specific hospital.")
    lines.append("")
    lines.append(f"Hospital: {report_data.get('hospital', 'Unknown')}")
    lines.append(f"Month: {report_data.get('month', 'Unknown')}")
    lines.append(f"Overall Quality Score: {report_data.get('overall_quality_score', 'N/A')}")
    lines.append(f"Overall Confidence: {report_data.get('overall_confidence', 'N/A')}")
    lines.append(f"Critical Issues Count: {report_data.get('critical_issues_count', 0)}")
    lines.append("")
    if report_data.get("top_rule_failures"):
        lines.append("## Top Rule Failures")
        for f in report_data["top_rule_failures"][:5]:
            lines.append(f"  {f.get('rule_code','')} ({f.get('severity','')}): {f.get('description','')}")
            lines.append(f"    Failure rate: {f.get('failure_rate','')}% | Cause: {f.get('primary_cause','')}")
        lines.append("")
    if report_data.get("quality_drivers"):
        lines.append("## Quality Drivers")
        for d in report_data["quality_drivers"]:
            lines.append(f"  {d.get('component','')}: {d.get('value','')}% ({d.get('status','')}) | Impact: {d.get('impact','')} pts")
        lines.append("")
    if report_data.get("confidence_gaps"):
        lines.append("## Confidence Gaps")
        for g in report_data["confidence_gaps"][:5]:
            lines.append(f"  {g.get('indicator_name','')} ({g.get('level','')}): confidence={g.get('confidence','')}, signal={g.get('weakest_signal','')}")
        lines.append("")
    if report_data.get("anomaly_patterns"):
        lines.append("## Anomaly Patterns")
        for a in report_data["anomaly_patterns"][:5]:
            lines.append(f"  {a.get('rate_name','')}: |z|={a.get('avg_z_score','')}, type={a.get('pattern_type','')} ({a.get('description','')})")
        lines.append("")

    lines.append("""Return a JSON array of recommendation objects only (no markdown, no explanation).
Each object has these fields:
- category: str (e.g. "Data Entry Training", "Process Improvement", "System Configuration")
- priority: str (one of "critical", "high", "medium", "low")
- title: str (short, max 80 chars)
- description: str (1-2 sentences explaining the root cause issue)
- rationale: str (why this matters for data quality, 1-2 sentences)
- action_items: list[str] (3-5 specific actionable steps)
- affected_indicators: list[str] (indicator codes or rule codes affected)
- category_ar: str (Arabic name of the category)
- title_ar: str (Arabic translation of title)
- description_ar: str (Arabic translation of description)
- rationale_ar: str (Arabic translation of rationale)
- action_items_ar: list[str] (Arabic translations of action items)

Give concrete, hospital-specific advice. Prioritize critical data quality issues first.

Return between 1 and """ + str(AI_MAX_RECOMMENDATIONS) + """ recommendations in order of priority.""")
    return "\n".join(lines)


def _build_root_cause_prompt_enhanced(report_data: dict) -> str:
    """
    Build enhanced root cause prompt with historical and comparative context.
    """
    lines = []
    lines.append("You are a maternal health data quality expert analyzing ROOT CAUSES with HISTORICAL and COMPARATIVE context.")
    lines.append("Focus on data quality improvements, confidence gaps, and operational fixes for the specific hospital.")
    lines.append("")
    lines.append(f"Hospital: {report_data.get('hospital', 'Unknown')}")
    lines.append(f"Month: {report_data.get('month', 'Unknown')}")
    lines.append(f"Overall Quality Score: {report_data.get('overall_quality_score', 'N/A')}")
    lines.append(f"Overall Confidence: {report_data.get('overall_confidence', 'N/A')}")
    lines.append(f"Critical Issues Count: {report_data.get('critical_issues_count', 0)}")
    lines.append("")

    if report_data.get("historical_trends"):
        lines.append("## Historical Trends (Last 6 Months)")
        for factor, trend in report_data["historical_trends"].items():
            lines.append(f"  {factor}: {trend.get('direction', 'unknown')} "
                         f"(slope={trend.get('slope', 0):.2f}, "
                         f"significant={trend.get('significant_change', False)})")
        lines.append("")

    if report_data.get("peer_comparisons"):
        lines.append("## Peer Comparisons")
        for group, comp in report_data["peer_comparisons"].items():
            lines.append(f"  {group}: percentile={comp.get('hospital_percentile', 0)}, "
                         f"z-score={comp.get('hospital_z_score', 0)}, "
                         f"gap_to_benchmark={comp.get('gap_to_benchmark', 0)}")
        lines.append("")

    if report_data.get("causal_chains"):
        lines.append("## Causal Chains Detected")
        for chain in report_data["causal_chains"]:
            lines.append(f"  Root Cause: {chain.get('root_cause_arabic', '')}")
            lines.append(f"  Confidence: {chain.get('confidence', 0)}")
            lines.append(f"  Impact if fixed: {chain.get('impact_if_fixed', 0)} points")
        lines.append("")

    if report_data.get("top_rule_failures"):
        lines.append("## Top Rule Failures")
        for f in report_data["top_rule_failures"][:5]:
            lines.append(f"  {f.get('rule_code','')} ({f.get('severity','')}): {f.get('description','')}")
            lines.append(f"    Failure rate: {f.get('failure_rate','')}% | Cause: {f.get('primary_cause','')}")
        lines.append("")

    if report_data.get("quality_drivers"):
        lines.append("## Quality Drivers")
        for d in report_data["quality_drivers"]:
            lines.append(f"  {d.get('component','')}: {d.get('value','')}% ({d.get('status','')})")
        lines.append("")

    if report_data.get("confidence_gaps"):
        lines.append("## Confidence Gaps")
        for g in report_data["confidence_gaps"][:5]:
            lines.append(f"  {g.get('indicator_name','')} ({g.get('level','')}): confidence={g.get('confidence','')}")
        lines.append("")

    if report_data.get("anomaly_patterns"):
        lines.append("## Anomaly Patterns")
        for a in report_data["anomaly_patterns"][:5]:
            lines.append(f"  {a.get('rate_name','')}: |z|={a.get('avg_z_score','')}, type={a.get('pattern_type','')}")
        lines.append("")

    lines.append("""Based on the historical trends and peer comparisons above, provide:
1. Root cause analysis with historical context (why is this happening now?)
2. Why this hospital differs from peers (what makes it unique?)
3. Specific actionable recommendations with timelines
4. Expected impact if recommendations are implemented

Return a JSON array of recommendation objects only (no markdown, no explanation).
Each object has these fields:
- category: str (e.g. "Historical Decline", "Peer Comparison", "Data Entry Training")
- priority: str (one of "critical", "high", "medium", "low")
- title: str (short, max 80 chars)
- description: str (1-2 sentences explaining the root cause issue)
- rationale: str (why this matters, 1-2 sentences)
- action_items: list[str] (3-5 specific actionable steps with timelines)
- affected_indicators: list[str] (indicator codes or rule codes affected)
- expected_impact: float (numeric improvement estimate in quality score points)
- implementation_timeline: str (e.g., "1-2 weeks", "1 month")
- category_ar: str (Arabic name of the category)
- title_ar: str (Arabic translation of title)
- description_ar: str (Arabic translation of description)
- rationale_ar: str (Arabic translation of rationale)
- action_items_ar: list[str] (Arabic translations of action items)

Give concrete, hospital-specific advice. Prioritize critical data quality issues first.

Return between 1 and """ + str(AI_MAX_RECOMMENDATIONS) + """ recommendations in order of priority.""")
    return "\n".join(lines)
