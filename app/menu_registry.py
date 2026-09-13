"""Fixed tab registry and default menu groups for the sidebar."""
from collections import OrderedDict

TAB_REGISTRY = OrderedDict([
    ("dashboard",       {"label": "Dashboard",            "icon": "📊", "permission": "dashboard.read"}),
    ("upload",          {"label": "Upload Data",          "icon": "📤", "permission": "data.upload"}),
    ("indicator-tree",  {"label": "Indicator Tree",       "icon": "🌳", "permission": "settings.read"}),
    ("rules-manager",   {"label": "Rules Manager",        "icon": "📋", "permission": "rules.read"}),
    ("analysis",        {"label": "Comparative Analysis", "icon": "📈", "permission": "analysis.read"}),
    ("root-cause",      {"label": "Root Cause",           "icon": "🔍", "permission": "root_cause.read"}),
    ("smart-analytics", {"label": "Smart Analytics",      "icon": "🛡️", "permission": "smart_analytics.read"}),
    ("quality",         {"label": "Quality Reports",      "icon": "✅", "permission": "quality.read"}),
    ("clinical",        {"label": "Clinical Intelligence","icon": "🏥", "permission": "clinical.read"}),
    ("outliers",        {"label": "Outliers",              "icon": "⚠️", "permission": "outliers.read"}),
    ("alerts",          {"label": "Alerts",                "icon": "🔔", "permission": "alerts.read"}),
    ("audit",           {"label": "Audit Log",             "icon": "📝", "permission": "audit.read"}),
    ("admin",           {"label": "System Control",       "icon": "⚙️", "permission": "system.manage_users", "superadmin_only": True}),
    ("settings",        {"label": "Settings",             "icon": "🔧", "permission": "system.manage_users", "hidden": True}),
])

DEFAULT_GROUPS = [
    {"name": "الرئيسية",  "icon": "🏠", "items": ["dashboard"]},
    {"name": "البيانات",  "icon": "📊", "items": ["upload", "indicator-tree", "rules-manager"]},
    {"name": "التحليل",   "icon": "📈", "items": ["analysis", "root-cause", "smart-analytics"]},
    {"name": "التقارير",  "icon": "📋", "items": ["quality", "clinical", "outliers", "alerts"]},
    {"name": "الإدارة",   "icon": "⚙️", "items": ["audit", "admin", "settings"]},
]