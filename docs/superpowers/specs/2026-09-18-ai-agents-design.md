# AI Agents Layer for DHIS

## Date
2026-09-18

## Status
Approved design (brainstorming complete, user-confirmed scope)

## Problem
The app already ships single-shot LLM features (`app/plugins/ai/`): generated
recommendations, executive summaries, and root-cause narratives via Gemini /
OpenAI-compatible / MiniMax calls with deterministic bilingual fallbacks. There
is no *agentic* capability: users cannot ask free-form questions about their data,
deep-dive a flagged outlier with gathered context, generate narrative reports on
demand, or get a prioritized daily digest — and access to any such capability must
stay permission-gated, hospital-scoped, off-by-default, and free of cost blowups on
a free-tier Gemini key.

## Goals (user-confirmed)
1. Four specialized, read-only agents: **NL Q&A**, **anomaly/alert explainer**,
   **narrative report writer**, **daily triage digest**.
2. Synchronous execution with **capped turns** (no async jobs, no scheduler).
3. **Free-tier friendly**: entity-keyed caching, single-flight dedup, history
   compression, batched tool calls, early finish, compact tool results.
4. **Chat memory + run audit**: conversations/messages persisted per user;
   `agent_runs` audit visible **only in System Control** (admin).
5. **Access control**: default-deny permissions (`ai.read`, `ai.write`), hospital
   scoping, global kill-switch `agents_enabled` default **OFF**. When OFF, all
   existing AI behavior stays exactly as today.

## Non-goals
- No DB writes by agents (read-only tools). No production scheduler/digest cron.
- No streaming/websockets/SSE. No agent-framework dependency (no LangGraph etc.).
- No schema/seed changes for permissions (reuses existing `ai.read`/`ai.write`).

## Design

### 1. New package `app/agents/`

```
app/agents/
  __init__.py        # public API: run_agent(), get_agent_profile(), is_enabled()
  runtime.py         # ReAct loop: prompt -> model -> tool-call JSON -> execute -> repeat
  tools.py           # read-only tool registry + hospital-scoping wrapper
  profiles/
    qa.py            # NL Q&A assistant
    explainer.py     # anomaly / alert deep-dive explainer
    report_writer.py # narrative report writer
    triage.py        # daily triage digest
  cache.py           # entity-keyed cache + invalidation stamp helpers
```

### 2. Agent runtime (`runtime.py`)

ReAct loop over `_call_api` from `app/plugins/ai/providers.py` (same provider,
config, and error handling as existing AI features):

1. Build context: system prompt (profile) + compressed chat history + conversation
   transcript (tool calls and observations from this run only).
2. Call the model; the model must answer with strict tool-call JSON:
   `{"thought": "...", "tools": [{"name": "...", "args": {...}}], "done": false}`.
   `tools` may be empty when `done: true` (final answer).
3. Execute up to **3 tool calls in parallel** per step; append one combined
   observation as a new `ASSISTANT observation` message; loop.
4. **Early finish**: if the model sets `done: true` (answer grounded), stop
   before the budget is spent.
5. **Budget**: per-turn cap by profile (Q&A/explainer 6 steps, report/digest 10)
   plus a token guard (~20k input tokens / run) and the existing per-call timeout.
6. On JSON-parse failure or API error: one bounded retry honoring `Retry-After`
   (429), else degrade to the profile's **deterministic fallback** (template output
   built from the same tool data, reusing `_local_*` style generation from
   `app/plugins/ai/`). The app must never error because the LLM failed.

All LLM answers are **bilingual by default** (Arabic primary or English — whatever
the requesting user set), matching existing AI output.

### 3. Tools (`tools.py`) — all read-only, hospital-scoped

Each tool receives the caller's hospital scope from
`get_user_hospital_ids(user, db)` (None = all for superadmin); restricted users can
only ever query their assigned hospitals. Tools:

- `list_accessible_hospitals(scope)` — the user's allowed hospitals (id, name).
- `get_indicator_values(scope, hospital_ids, month, indicators?)` — latest/aggregate
  indicator values; result is **compact** (top-k, rounded) per optimization C7.
- `get_quality_score(scope, hospital_ids, month)` — score + completeness/consistency/
  compliance/outlier penalty.
- `get_rule_results(scope, hospital_ids, month, status?)` — PASS/FAIL breakdown.
- `get_anomalies(scope, hospital_ids, month)` — outlier/anomaly list from Smart
  Analytics / outlier engine.
- `get_clinical_profile(scope, hospital_ids, month)` — clinical rates/classifications.
- `get_peer_comparison(scope, hospital_ids, month, indicator?)` — peer-group gaps/z.
- `get_historical_trends(scope, hospital_ids, month, indicator?)` — last N months.
- `query_month_aggregates(scope, month, group_by, indicators?)` — roll-ups across
  the user's hospitals (used by digest and cross-hospital questions).

Tools source data from the **existing engine functions** (quality, rules, smart
analytics, clinical, comparative, regional, root-cause modules) — no new computation,
no direct DB writes.

### 4. Profiles

| Profile | System-prompt role | Tools (allow-list) | Step cap | Deterministic fallback |
|---|---|---|---|---|
| `qa` | NL Q&A over the indicator DB; cites numbers + which tool fetched them | all | 6 | template: query → summarize top indicators for the month |
| `explainer` | Deep-dive a given outlier / rule failure: peers, trends, rules, likely causes, actions | quality, anomalies, peers, trends, rules, clinical | 6 | existing `_local_root_cause_fallback_enhanced` |
| `report_writer` | Bilingual monthly narrative sections from computed results | all | 10 | existing `generate_executive_summary` local fallback |
| `triage` | Prioritized digest across the user's hospitals; errors/failures/anomalies + suggested actions | aggregated tools, quality, rule, anomalies | 10 | sorted FAIL/anomaly listing |

### 5. Data model + migrations (3 new Alembic migrations, one commit)

- `conversations` — id, user_id (FK users, CASCADE, index), title, lang, created_at.
- `messages` — id, conversation_id (FK, CASCADE, index), role, content, tool_steps
  (JSON), token_usage (JSON, nullable), created_at. Composite index
  `(conversation_id, created_at)`.
- `agent_runs` — id, user_id (FK, index), agent (str), conversation_id (nullable),
  prompt_hash, status, duration_ms, tool_calls (JSON), tokens (JSON), result,
  error, created_at. Index `(user_id, created_at)`, index `created_at`.

Models in `app/models.py`; tables follow the `user_permissions` migration pattern
(association-style file). Startup `create_all(checkfirst=True)` heal covers drift as
usual.

### 6. Caching (optimization A1–A3)

- Extend `app/plugins/ai/cache.py` with an **entity-keyed** store: key =
  `agents:{profile}:{hospital_ids_hash}:{month}:{entity}:{prompt_hash}` so repeated
  questions/digests across users reuse a prior run's final answer.
- **Invalidation**: add a per-hop data **version stamp** (`agents_data_version` per
  hospital+month, bumped by the existing upload / analysis re-run hooks). Cache
  entries carry the stamp; mismatched stamps are treated as misses. Stale entries
  are lazily replaced.
- **Single-flight**: an in-process map of live run keys; identical in-flight requests
  await the shared result instead of issuing duplicate LLM calls.
- Conversation **history compression** (A4): on each turn, older turns are folded
  into a short summary line stored on the conversation; only the last ~6 messages
  plus the summary are sent to the model.

### 7. API — new router `app/api/agents.py` (prefix `/ai/agents`)

All endpoints: require `ai.read` (default-deny), respect `agents_enabled` (see 9),
and inject the current user for hospital scoping.

- `POST /ai/agents/chat` — start/continue a conversation (body: conversation_id?,
  message) → creates/updates conversation + messages, runs `qa`, returns answer +
  step log. Requires `ai.read`.
- `GET /ai/agents/chat/{id}/messages` — multi-turn history. Requires `ai.read`.
- `POST /ai/agents/explain` — (body: hospital_id, month, entity — an anomaly/outlier
  rule id or codename) → runs `explainer`. Requires `ai.read`.
- `POST /ai/agents/report` — (body: hospital_id, month, lang) → runs `report_writer`,
  stores the narrative with the existing report persistence if applicable.
  Requires `ai.read` **and** `ai.write`.
- `POST /ai/agents/digest` — (body: month) → runs `triage` across the user's
  hospitals. Requires `ai.read` **and** `ai.write`.
- `GET /ai/agents/status` — `{enabled: bool, permissions: {...}}` for UI gating.
  Requires auth.
- Admin-only (System Control, `system.manage_users`):
  - `GET /ai/agents/runs` — paginated `agent_runs` audit.
  - `GET/PUT /ai/agents/admin` — per-user daily caps, `agents_enabled` toggle
    (mirrors the settings vetted in `config_api.py` / `config_utils.py`).

Daily cap: a per-user counter (bumped per run, reset daily) stops a single account
at the configured max runs/day (default 20) with a clear message.

### 8. Access control summary (user-confirmed)

| Permission / config | Effect |
|---|---|
| `agents_enabled` (**default OFF**) | OFF → all `/ai/agents/*` disabled (UI hidden, API returns `{enabled:false}`), existing AI features untouched. ON → agents available (subject to permissions below). |
| `ai.read` | Q&A + explainer. |
| `ai.write` | report writer + digest (in addition to `ai.read`). |
| `system.manage_users` (admin) | `agent_runs` audit + daily caps + `agents_enabled` toggle, **in System Control only**. |
| superadmin | bypasses all permission gates. |
| hospital scope | every tool limited to `get_user_hospital_ids`. |

Permissions are rows already seeded (canonical `ai.read`/`ai.write`,
`app/main.py` CANONICAL_PERMISSION_CODENAMES); no role except superadmin is granted
them by seed — admins grant via the existing Role editor / Direct-Permission picker.

### 9. Kill-switch (user-confirmed)

- New key `agents_enabled` added to `AI_CONFIG_KEYS` in `app/config_utils.py`
  (default `"false"`), stored in SystemSetting, editable from System Control →
  Settings → AI, via the existing config GET/PUT endpoints.
- Runtime reads it through `reload_ai_config()`-style refresh; agents router checks
  it before any work.

### 10. Frontend

- New `static/js/agents.js` (+ a small chart-free chat panel):
  - AI Assistant surface for Q&A (entry points from existing tabs; visible only with
    `ai.read` and `agents_enabled`).
  - "Explain" buttons on outlier/anomaly/rule-failure/report cards (renders the
    explainer result inline).
  - "Generate report" reuse in the AI Reports screen; "Daily digest" button on the
    Dashboard/System Control area (both need `ai.write`).
  - All panels auto-hide when `agents_enabled` is false (status endpoint).
- System Control gains an **AI Agents admin view** (`agent_runs` table + daily-cap
  fields + toggle) — admin-only, mirroring the Users/Logs pattern in `admin.js`.
- i18n keys added for every new static string (EN + AR) per repo policy.

### 11. Tests (TDD — write failing tests first)

- `tests/test_agents_runtime.py` — mock LLM (scripted tool-call JSON): loop
  mechanics, parallel tool batching, early finish, turn/token cap enforcement,
  JSON-parse failure and 429 fallback, single-flight dedup, history compression.
- `tests/test_agents_tools.py` — hospital-scope enforcement on every tool; compact
  top-k output; entity-keyed cache hit/stamp-invalidate; daily-cap enforcement.
- `tests/test_agents_api.py` — permissions (no `ai.read` → 403; `ai.write` gates
  report/digest), `agents_enabled` off → disabled, superadmin bypass, admin runs
  audit, conversation/messages round-trip.
- `tests/test_agents_js.py` — static checks: gating vars, explain buttons,
  `agents_enabled` hiding, `__()` i18n coverage for `agents.js`.

## Files touched
- New: `app/agents/` package (runtime, tools, cache, 4 profiles), `app/api/agents.py`,
  3 Alembic migrations, `static/js/agents.js`, `tests/test_agents_*.py`.
- Edited: `app/models.py` (3 tables), `app/plugins/ai/cache.py` (entity key +
  stamp), `app/config_utils.py` (`agents_enabled` key), `app/api/config_api.py`
  (`agents_enabled` in AI settings), upload/analysis re-run hooks (stamp bump),
  `static/css/styles.css`, `static/js/i18n.js`, `static/js/admin.js` (AI Agents
  admin view), existing report/anomaly UI (explain buttons), `app/main.py` if any
  endpoint route registration needed.

## Verification
- Full pytest suite green (currently 1237); `node --check` on new/modified JS.
- Live smoke: with `agents_enabled` OFF → `/ai/agents/status` disabled + existing AI
  reports unchanged; ON + `ai.read` granted → Q&A returns grounded numbers; quota
  exhausted (mock 429) → deterministic fallback, HTTP 200.