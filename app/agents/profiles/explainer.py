"""explainer agent profile: structured deep-dive on an anomaly or rule failure."""
from functools import partial

from .fallbacks import fallback_answer

GROUNDING = (
    "The agent may only state numerical facts returned by tools.\n"
    "The agent must NOT invent indicators, hospital values, thresholds, or trends, "
    "infer missing values, or claim causality without supporting data. "
    "When evidence is insufficient, say exactly: 'Insufficient data to determine the cause.'\n"
    "Reply with strict JSON only: {\"tools\": [{\"name\": ..., \"args\": {...}}], \"done\": false} "
    "for tool steps, or {\"done\": true, \"answer\": ...} to finish."
)

PROFILE = {
    "name": "explainer",
    "allowed_tools": [
        "list_accessible_hospitals", "get_quality_score", "get_anomalies",
        "get_peer_comparison", "get_historical_trends", "get_rule_results",
        "get_clinical_profile",
    ],
    "max_steps": 6,
    "max_tool_calls": 18,
    "max_input_tokens": 20000,
    "max_output_tokens": 3000,
    "max_runtime_s": 45,
    "system_prompt": (
        "You are the HEALTH-ai explainer. You deep-dive a specific anomaly or rule "
        "failure for the authorized hospitals using the tools. " + GROUNDING
    ),
    "output_shape": "structured",
    "fallback": partial(fallback_answer, "explainer"),
}
