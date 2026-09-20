"""q&a agent profile: conversational answers grounded strictly in tool data."""
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
    "name": "qa",
    "allowed_tools": [  # all nine registry names
        "list_accessible_hospitals", "get_indicator_values", "get_quality_score",
        "get_rule_results", "get_anomalies", "get_clinical_profile",
        "get_peer_comparison", "get_historical_trends", "query_month_aggregates",
    ],
    "max_steps": 6,
    "max_tool_calls": 18,
    "max_input_tokens": 20000,
    "max_output_tokens": 3000,
    "max_runtime_s": 45,
    "system_prompt": (
        "You are the HEALTH-ai data assistant. You answer questions about the "
        "authorized hospitals' maternal health indicators using the tools. " + GROUNDING
    ),
    "output_shape": "conversational",
    "fallback": partial(fallback_answer, "qa"),
}
