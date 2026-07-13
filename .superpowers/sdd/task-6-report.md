# Task 6 Report: Split AI Plugin + hospitals.py API

## Summary
Successfully split two large monolithic modules into focused, maintainable files.

## Part A: Split AI Plugin

**Before:** `app/plugins/ai.py` (891 lines)
**After:**
```
app/plugins/ai/
├── __init__.py          # re-exports + main generate functions
├── providers.py         # OpenAI, Anthropic, local provider classes + config + fallbacks
├── prompts.py           # prompt builders + templates
└── cache.py             # AI response caching
```

### File breakdown:
- `cache.py` (51 lines): `_make_cache_key`, `get_ai_cache`, `set_ai_cache`, `CACHE_TTL_HOURS`
- `providers.py` (340 lines): AI config vars, `_try_load_db_config`, `reload_ai_config`, provider call functions (`_call_openai_api`, `_call_gemini_api`, `_call_minimax_api`, `_call_api`), `_parse_response`, `AIRuleDef`, and all fallback functions
- `prompts.py` (200 lines): `_build_prompt`, `_build_executive_summary_prompt`, `_build_root_cause_prompt`
- `__init__.py` (108 lines): Re-exports + `generate`, `generate_executive_summary`, `generate_root_cause_ai`

### Import compatibility:
All existing consumers continue to work unchanged:
- `app/api/config_api.py` — `from app.plugins.ai import reload_ai_config`
- `app/engine/root_cause.py` — `from app.plugins.ai import generate_root_cause_ai`
- `app/engine/clinical/recommendations.py` — `from app.plugins.ai import generate`

## Part B: Split hospitals.py API

**Before:** `app/api/hospitals.py` (583 lines)
**After:**
```
app/api/
├── hospitals.py         # CRUD only (~60 lines)
├── indicator_config.py  # indicator enable/disable + weight + global CRUD (~270 lines)
└── tree_config.py       # tree configuration (~150 lines)
```

### File breakdown:
- `hospitals.py` (60 lines): `list_hospitals`, `list_all_indicators`, `get_hospital`, `reanalyze_hospital`
- `indicator_config.py` (270 lines): `get_hospital_indicator_config`, `toggle_indicator`, `update_indicator_weight`, `bulk_reorder_indicators`, `update_global_indicator`, `create_global_indicator`, `delete_global_indicator`, `reparent_indicator`, `global_toggle_indicator`, `set_indicator_sort_order` + helpers (`_get_or_create_config`, `_get_all_descendant_ids`)
- `tree_config.py` (150 lines): `save_tree_config`, `get_management_tree`, `get_indicator_tree`

### Router registration:
Updated `app/main.py` to include all three routers:
```python
app.include_router(hospitals.router)
app.include_router(indicator_config.router)
app.include_router(tree_config.router)
```

## Test Results
- **151 tests passed** (baseline maintained)
- **0 tests failed**
- No breaking changes — all existing API endpoints preserved with same routes
