"""Fixed tab registry and default menu groups for the sidebar."""
from collections import OrderedDict

TAB_REGISTRY = OrderedDict([
    ("dashboard",       {"label": "Dashboard",            "icon": "📊", "permission": "dashboard.read"}),
    ("upload",          {"label": "Upload Data",          "icon": "📤", "permission": "data.upload"}),
    ("indicator-tree",  {"label": "Data Tree",            "icon": "🌳", "permission": "settings.read"}),
    ("indicator-groups", {"label": "Data Group",         "icon": "🗂️", "permission": "settings.read"}),
    ("indicators",       {"label": "Indicators",          "icon": "📐", "permission": "settings.read"}),
    ("direction-coverage", {"label": "Direction Coverage", "icon": "🧭", "permission": "settings.read"}),
    ("rules-manager",   {"label": "Validation Rules",     "icon": "📋", "permission": "rules.read"}),
    ("analysis",        {"label": "Hospital Comparisons", "icon": "📈", "permission": "analysis.read"}),
    ("root-cause",      {"label": "Root Cause",           "icon": "🔍", "permission": "root_cause.read"}),
    ("smart-analytics", {"label": "Smart Analytics",      "icon": "🛡️", "permission": "smart_analytics.read"}),
    ("smart-forecast",  {"label": "Smart Forecast",       "icon": "🔮", "permission": "smart_analytics.read"}),
    ("quality",         {"label": "Quality Reports",      "icon": "✅", "permission": "quality.read"}),
    ("quality-completeness", {"label": "Completeness",     "icon": "🧩", "permission": "quality.read"}),
    ("quality-consistency",  {"label": "Consistency",      "icon": "🔗", "permission": "quality.read"}),
    ("quality-confidence",   {"label": "Confidence",       "icon": "🎯", "permission": "quality.read"}),
    ("quality-alerts",  {"label": "Quality Alerts",       "icon": "🚨", "permission": "quality_alerts.read"}),
    ("clinical",        {"label": "Clinical Intelligence","icon": "🏥", "permission": "clinical.read"}),
    ("outliers",        {"label": "Outlier Scan",          "icon": "⚠️", "permission": "outliers.read"}),
    ("layered",         {"label": "Outlier Diagnostics",   "icon": "🧱", "permission": "analysis.read"}),
    ("alerts",          {"label": "Validation Alerts",     "icon": "🔔", "permission": "alerts.read"}),
    ("audit",           {"label": "Audit Log",             "icon": "📝", "permission": "audit.read"}),
    ("admin",           {"label": "System Control",       "icon": "⚙️", "permission": "system.manage_users", "superadmin_only": True}),
    ("guides",          {"label": "Guides",               "icon": "📚", "permission": "dashboard.read"}),
    ("user-guide",      {"label": "User Guide",           "icon": "📖", "permission": "dashboard.read"}),
    ("settings",        {"label": "Settings",             "icon": "🔧", "permission": "system.manage_users", "hidden": True}),
])

DEFAULT_GROUPS = [
    {"name": "Home",      "icon": "🏠", "items": ["dashboard"]},
    {"name": "Data",      "icon": "📊", "items": ["upload", "indicator-tree", "indicator-groups", "indicators", "direction-coverage", "rules-manager"]},
    {"name": "Analysis",  "icon": "📈", "items": ["analysis", "smart-analytics", "smart-forecast", "clinical", "root-cause"]},
    {"name": "Oversight", "icon": "🛡️", "items": [
        # Rule Compliance (quality-compliance) is retired as a screen: its view
        # is the "Compliance by hospital" sub-tab of the alerts screen, which is
        # what this group lists. Do not re-add it without a registry entry.
        "quality", "quality-completeness", "quality-consistency",
        "quality-confidence", "quality-alerts", "outliers", "layered", "alerts", "audit",
    ]},
    {"name": "System",    "icon": "⚙️", "items": ["admin", "guides", "user-guide", "settings"]},
]
