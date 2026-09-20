"""triage agent profile: prioritized digest across the user's hospitals."""
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
    "name": "triage",
    "allowed_tools": [
        "list_accessible_hospitals", "query_month_aggregates",
        "get_quality_score", "get_rule_results", "get_anomalies",
    ],
    "max_steps": 10,
    "max_tool_calls": 18,
    "max_input_tokens": 20000,
    "max_output_tokens": 3000,
    "max_runtime_s": 45,
    "system_prompt": (
        "You are the HEALTH-ai triage agent. You produce a prioritized digest "
        "across the user's authorized hospitals using the tools. " + GROUNDING
    ),
    "output_shape": "structured",
    "fallback": partial(fallback_answer, "triage"),
}