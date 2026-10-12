"""Fixed tab registry and default menu groups for the sidebar."""
from collections import OrderedDict

TAB_REGISTRY = OrderedDict([
    ("dashboard",       {"label": "Dashboard",            "icon": "📊", "permission": "dashboard.read"}),
    ("upload",          {"label": "Upload Data",          "icon": "📤", "permission": "data.upload"}),
    ("indicator-tree",  {"label": "Indicator Tree",       "icon": "🌳", "permission": "settings.read"}),
    ("indicator-groups", {"label": "Indicator Groups",   "icon": "🗂️", "permission": "settings.read"}),
    ("rules-manager",   {"label": "Validation Rules",     "icon": "📋", "permission": "rules.read"}),
    ("analysis",        {"label": "Hospital Comparisons", "icon": "📈", "permission": "analysis.read"}),
    ("root-cause",      {"label": "Root Cause",           "icon": "🔍", "permission": "root_cause.read"}),
    ("smart-analytics", {"label": "Smart Analytics",      "icon": "🛡️", "permission": "smart_analytics.read"}),
    ("quality",         {"label": "Quality Reports",      "icon": "✅", "permission": "quality.read"}),
    ("clinical",        {"label": "Clinical Intelligence","icon": "🏥", "permission": "clinical.read"}),
    ("outliers",        {"label": "Outlier Scan",          "icon": "⚠️", "permission": "outliers.read"}),
    ("layered",         {"label": "Outlier Diagnostics",   "icon": "🧱", "permission": "analysis.read"}),
    ("alerts",          {"label": "Alerts",                "icon": "🔔", "permission": "alerts.read"}),
    ("audit",           {"label": "Audit Log",             "icon": "📝", "permission": "audit.read"}),
    ("admin",           {"label": "System Control",       "icon": "⚙️", "permission": "system.manage_users", "superadmin_only": True}),
    ("settings",        {"label": "Settings",             "icon": "🔧", "permission": "system.manage_users", "hidden": True}),
])

DEFAULT_GROUPS = [
    {"name": "Home",      "icon": "🏠", "items": ["dashboard"]},
    {"name": "Data",      "icon": "📊", "items": ["upload", "indicator-tree", "indicator-groups", "rules-manager"]},
    {"name": "Analysis",  "icon": "📈", "items": ["analysis", "smart-analytics", "clinical", "root-cause"]},
    {"name": "Oversight", "icon": "🛡️", "items": ["quality", "outliers", "layered", "alerts", "audit"]},
    {"name": "System",    "icon": "⚙️", "items": ["admin", "settings"]},
]