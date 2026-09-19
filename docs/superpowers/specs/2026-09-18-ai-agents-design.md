# AI Agents Layer for DHIS

## Date
2026-09-18

## Status
Approved design (brainstorming complete, user-confirmed scope; updated per review
rounds 1–3 — provider abstraction + admin-controlled per-role provider routing)

## Problem
The app already ships single-shot LLM features (`app/plugins/ai/`): generated
recommendations, executive summaries, and root-cause narratives via Gemini /
OpenAI-compatible / MiniMax calls with deterministic bilingual fallbacks. There
is no *agentic* capability: users cannot ask free-form questions about their data,
deep-dive a flagged outlier with gathered context, generate narrative reports on
demand, or get a prioritized triage digest — and any such capability must stay
permission-gated, hospital-scoped, off-by-default, grounded in tool-fetched facts,
and free of cost/blowups on a free-tier Gemini key.

## Goals (user-confirmed)
1. Four specialized, read-only agents: **NL Q&A**, **anomaly/alert explainer**,
   **narrative report writer**, **triage digest** (on-demand, not scheduled).
2. Synchronous execution with capped budgets (steps, tool calls, tokens, runtime).
3. **Free-tier friendly**: entity-keyed caching, single-flight dedup, history
   compression, batched tool calls, early finish, compact tool results.
4. **Chat memory + run audit**: conversations/messages persisted per user;
   `agent_runs` audit visible **only in System Control** (admin).
5. **Access control**: default-deny permissions (`ai.read`, `ai.write`), hospital
   scoping enforced server-side (never by the LLM), global kill-switch
   `agents_enabled` default **OFF**. When OFF, all existing AI behavior is unchanged.
6. **Grounding policy**: agents state only tool-returned facts; no invented data,
   thresholds, trends, or causal claims.
7. **Provider abstraction + admin routing**: the runtime resolves its synthesis
   model from configuration — local LLM (Ollama), Gemini, OpenAI-compatible, or
   Auto — with all agent behavior provider-independent. As admin, control the
   on/off kill-switch, which providers are used, and which **type of work
   (agent profile)** runs on each provider when two are running.

## Non-goals
- No DB writes by agents (read-only tools). No production scheduler/cron.
- No streaming/websockets/SSE. No agent-framework dependency (no LangGraph etc.).
- No schema/seed changes for permissions (reuses existing `ai.read`/`ai.write`).
- No parallel tool execution beyond the 3-call per-step batch already designed.
- No per-profile provider routing is hard-coded in the runtime: role→provider
  assignment is an admin-setting (`agent_provider_roles`), with the global
  `ai_provider` selection as the fallback for roles without an explicit mapping.
- Existing single-shot AI features are **not** rewired by the provider selector
  (it applies to the agents layer only).

## Design principle (verified against codebase)
The agent layer is an **orchestration + explanation layer**. Every tool calls the
existing engine functions (quality, rules, smart analytics, clinical, comparative,
regional, root-cause) or compact read-only DB queries. The LLM never computes
medical indicators independently — a number an agent cites must be the same number
the dashboard renders.

```
Existing HEALTH-ai Engine (quality / rules / anomalies / clinical / peers / trends / root cause)
        │  (no duplicate calculations)
        ▼
Agent Tool Layer (read-only, hospital-scoped, validated)
        │
        ▼
Agent Runtime (profiles, budgets, retries, fallback)
        │
        ▼
   LLM Provider (resolved from config)
        │
   ┌────┼───────────────┐
   │    │               │
  Local  Gemini   OpenAI-compatible
  (Ollama)
   │
 Qwen3 8B / Gemma 4 12B
        │
        ▼
User / Dashboard
```

## Design

### 1. New package `app/agents/`

```
app/agents/
  __init__.py        # public API: run_agent(), get_agent_profile(), is_enabled()
  runtime.py         # ReAct loop: prompt -> model -> tool-call JSON -> execute -> repeat
  tools.py           # tool registry (metadata contract) + scope enforcement
  profiles/
    qa.py            # NL Q&A assistant
    explainer.py     # anomaly / alert deep-dive explainer
    report_writer.py # narrative report writer
    triage.py        # on-demand triage digest
  cache.py           # entity-keyed versioned cache + single-flight + history compression
```

### 2. Agent runtime (`runtime.py`)

ReAct loop over the resolved provider's `_call_api` (from
`app/plugins/ai/providers.py`, provider chosen per Section 3 — same base
interface, config, and error handling as existing AI features):

1. Build context: profile system prompt (incl. grounding policy) + compressed
   conversation history + this run's transcript (tool calls and observations).
2. Call the model. The model replies with strict JSON **only** — no `thought`
   field on the wire:
   - tool step: `{"tools": [{"name": "...", "args": {...}}, ...], "done": false}`
   - finish:     `{"done": true, "answer": "..."}`
   The model's natural-language lead-in preceding the JSON is captured as the
   assistant transcript message (so multi-turn context stays intact) but is not
   part of the protocol or audited.
3. Execute up to **3 tool calls in parallel** per step; append one combined
   observation; loop.
4. **Early finish**: `done: true` stops before the budget is spent.
5. **Budgets** (per profile, profile-configured): max steps (6/6/10/10),
   **max total tool calls** (default 18), **max runtime** (default 45 s),
   token budget (input ≤ 20k, output ≤ 3k, total ≤ 23k). First budget hit →
   finish with the last grounded answer or a clear "budget exceeded" note; fall
   back deterministically if insufficient.
6. On JSON-parse failure or API error: one bounded retry honoring `Retry-After`
   (429), else degrade to the profile's **deterministic fallback** (template
   output built from the same tool data, reusing `_local_*` generation). The app
   must never error because the LLM failed:
   `LLM ok → answer · timeout → retry · 429 → bounded retry · still failed →
   deterministic fallback · never a 500/broken screen`.

All LLM answers are **bilingual by default** (Arabic or English per requesting
user), matching existing AI output.

### 3. LLM provider abstraction

The agent runtime resolves its synthesis model through an explicit provider
abstraction. **The runtime MUST NOT depend on a specific provider.** The agent
tools, permissions, hospital scope, grounding, budgets, caching, and fallback
behavior are provider-independent — the same four agents work regardless of the
selected model.

Supported providers:

- **Local LLM** — Ollama (e.g. Qwen3 8B, Gemma 4 12B) exposed via its
  OpenAI-compatible endpoint (`http://localhost:11434/v1`, no API key). Reuses
  the existing OpenAI-compatible path in `app/plugins/ai/providers.py` — **no new
  SDK dependency**.
- **Gemini** — existing default provider.
- **OpenAI-compatible** — existing provider path (incl. MiniMax).

All providers implement the same interface, already satisfied by the existing
`_call_api` (returns text + prompt/completion token counts):

- `chat()` — single-turn completion for one ReAct step.
- Structured JSON response (strict-parse; tolerate code fences).
- Token usage reporting.
- Timeout handling.
- Retry/error handling (incl. 429 `Retry-After`).

**Configuration (System Control → Settings → AI):**

| Setting | Values | Effect |
|---|---|---|
| `agents_provider` | `local` \| `gemini` \| `openai_compatible` \| `auto` (default `auto`) | global provider for agents **when a profile has no explicit mapping** — new key; the existing `ai_provider` key stays as the single-shot provider |
| `agent_provider_roles` | JSON role→provider map, default `{}` (below) | per-profile ("type of work") provider assignment |
| `local_runtime` | `ollama` (default) | local runtime type |
| `local_model` | e.g. `qwen3:8b` (default) | model name for the local provider |
| `local_url` | `http://localhost:11434` (default) | local provider base URL |

**Role→provider routing (`agent_provider_roles`):** the admin assigns each of
the four agent profiles (Q&A, explainer, report_writer, triage) to a provider
(`local` / `gemini` / `openai_compatible`), or leaves a profile unset. Example
hybrid: `{"report_writer": "gemini", "qa": "local", "explainer": "local",
"triage": "local"}`.

**Per-run resolution order (per profile):**
1. If `agent_provider_roles[profile]` is set **and** that provider is configured
   and reachable → use it for that run.
2. Otherwise resolve the global `agents_provider`:
   - `local` → local provider if configured and reachable, else deterministic
     fallback (no cloud).
   - `gemini` → the Gemini provider.
   - `openai_compatible` → the OpenAI-compatible path.
   - `auto` (default) → local provider if configured and reachable, else the
     existing default cloud provider.

`auto` with a role map therefore means: "use the role map; unset roles → local
if reachable, else default cloud." A mapped provider that is down degrades to
step 2 (global) for that role, never to an error. Exactly one provider is
resolved per (profile, run).

The `agents_enabled` toggle is independent of provider selection.

**Expectation setting for local models:** small models (8B–12B) are weaker at
strict tool-call JSON and may consume more budget steps or reach the
deterministic fallback more often. Grounding holds in all cases — the model only
summarizes tool-fetched facts — and bounded retry + fallback absorb the extra
malformed JSON.

**Deployment models**

| Deployment | Stack |
|---|---|
| Private / on-prem install | HEALTH-ai → Ollama → Qwen3 8B (fully offline) |
| Cloud install | HEALTH-ai → Gemini |
| Hybrid | admin routes roles via `agent_provider_roles`, e.g. Q&A/triage/explainer → local Qwen3, report_writer → Gemini |

In every mode: the same four agents, tools, permissions, hospital scope,
grounding, budgets, caching, and fallback — only the synthesis model changes.

### 4. Tools (`tools.py`) — read-only, hospital-scoped, validated

**Scope enforcement is server-side and cannot be bypassed by the LLM:**
the runtime computes `authorized_hospital_ids = get_user_hospital_ids(user, db)`
and injects it into every tool context. A tool internally enforces it:
- `hospital_ids` supplied by the model are **intersected** with the authorized
  set. Any requested-but-unauthorized hospital → the tool returns a
  `ACCESS_DENIED` observation (never data).
- Invalid/unknown hospital IDs or malformed `month` → rejected with a validation
  observation.
- Tools never accept the caller's scope from the model as authoritative.

Common tools:

- `list_accessible_hospitals(scope)` — the user's allowed hospitals (id, name).
- `get_indicator_values(scope, hospital_ids, month, indicators?)` — compact
  top-k/rounded values (per C7 and the response limits below).
- `get_quality_score(scope, hospital_ids, month)`
- `get_rule_results(scope, hospital_ids, month, status?)`
- `get_anomalies(scope, hospital_ids, month)`
- `get_clinical_profile(scope, hospital_ids, month)`
- `get_peer_comparison(scope, hospital_ids, month, indicator?)`
- `get_historical_trends(scope, hospital_ids, month, indicator?)`
- `query_month_aggregates(scope, month, group_by, indicators?)`

**Tool registry contract** (each tool exposes metadata; profiles declare
`allowed_tools` by name — no profile reaches into implementation):

```python
{
  "name": "get_quality_score",
  "description": "...",
  "schema": {...},            # JSON schema for args validation
  "permission": "ai.read",
  "scope": "hospital",        # hospital | none
  "max_results": 20,
  "max_tokens": 400,          # tool response budget (see limits below)
}
```

**Tool response hard limits** (per tool): max rows 20, max characters 4k, max
indicators 10, max hospitals 20. Oversized results are truncated/rounded before
reaching the model.

### 5. Profiles

| Profile | Role | allowed_tools | steps | Output shape |
|---|---|---|---|---|
| `qa` | NL Q&A over the indicator DB; cites numbers + which tool fetched them | all tools | 6 | conversational; includes facts + source list |
| `explainer` | Deep-dive a given anomaly / rule failure | `get_quality_score`, `get_anomalies`, `get_peer_comparison`, `get_historical_trends`, `get_rule_results`, `get_clinical_profile` (+ `list_accessible_hospitals`) | 6 | structured sections (below) |
| `report_writer` | Bilingual monthly narrative sections | all tools | 10 | structured sections, then prose |
| `triage` | Prioritized digest across the user's hospitals ("Generate Triage Digest") | `query_month_aggregates`, `get_quality_score`, `get_rule_results`, `get_anomalies` (+ `list_accessible_hospitals`) | 10 | structured sections |

**Structured output contract** for explainer / report_writer / triage (and used
as a described shape by Q&A): the agent response separates

- **Facts** — exactly the numbers returned by tools (value, threshold, peer
  median, previous month, rule status) with the tool that produced each.
- **Analysis** — observed changes/deltas computed by tools or engines (e.g.
  "↑ 1.2 pp MoM"), never invented.
- **Potential contributing factors supported by available data** — explicitly
  correlational phrasing, not causality. If evidence is insufficient: the agent
  says `"Insufficient data to determine the cause."` instead of asserting one.
- **Suggested actions** — generic/process-level recommendations.

The UI renders these as separate labeled blocks so the LLM's interpretation is
clearly distinct from the numbers.

**Grounding policy (in every profile system prompt):**
```
The agent may only state numerical facts returned by tools.
The agent must NOT:
- invent indicators, hospital values, thresholds, or trends
- infer missing values
- claim causality without supporting data (use "potential contributing
  factors supported by available data")
If evidence is insufficient: "Insufficient data to determine the cause."
```

### 6. Data model + migrations (3 new Alembic migrations, one commit)

- `conversations` — id, user_id (FK users, CASCADE, index), title, lang,
  created_at.
- `messages` — id, conversation_id (FK, CASCADE, index), **message_type**
  (`user | assistant | tool | system`) + role, content, tool_steps (JSON),
  token_usage (JSON, nullable), created_at. Composite index
  `(conversation_id, created_at)`.
- `agent_runs` — **metadata + audit trail, NOT full response content**:
  id, user_id (FK, index), agent, conversation_id (nullable), status,
  duration_ms, steps, tool_calls (JSON summary), tokens (JSON),
  **data_version**, **model/provider**, **language**, **cache_hit**,
  **fallback_used**, **hospital_scope_hash**, **permission_scope_hash**,
  prompt_hash, error, created_at. Index `(user_id, created_at)`, index
  `created_at`.
  Narrative content lives in `messages`, not here. **Retention**: full detailed
  audit rows are pruned to summarized metadata after a configurable retention
  period (default 90 days, System Control setting); messages comply with the
  existing audit/data retention posture.

Models in `app/models.py`; tables follow the `user_permissions` migration
pattern; startup `create_all(checkfirst=True)` heal covers drift as usual.

### 7. Caching (free-tier: entity-keyed, versioned, scope-safe)

- Cache key includes **the complete effective authorization scope** so a cache
  hit can never leak data across users:
  ```
  agents:{profile}:{hospital_scope_hash}:{permission_scope_hash}:{month}:
         {entity}:{data_version}:{language}:{prompt_hash}
  ```
  Two users whose access differs (different hospital/permission scope) never
  share entries. **Authorization is never bypassed by a cache hit.**
- **Versioning**: the cache identity is `hospital + month + data_version`
  where `data_version` bumps on reprocessing. Upload / analysis re-run hooks
  bump the affected hospital+month `data_version` stamps; mismatched stamps
  are misses and stale entries are lazily replaced.
- **Single-flight**: an in-process map of live run keys; identical in-flight
  requests await the shared result instead of duplicating LLM calls.
- **History compression**: older turns are folded into a short summary stored on
  the conversation; only the last ~6 messages + summary are sent to the model.

### 8. API — new router `app/api/agents.py` (prefix `/ai/agents`)

All non-admin endpoints: require `ai.read`, respect `agents_enabled`, inject the
current user, and enforce hospital scope. Structured responses carry
`facts / analysis / contributors / actions` where applicable.

- `POST /ai/agents/chat` — start/continue a conversation (body: conversation_id?,
  message) → runs `qa`, returns answer + step log + sources. Requires `ai.read`.
- `GET /ai/agents/chat/{id}/messages` — multi-turn history. Requires `ai.read`.
- `POST /ai/agents/explain` — (body: hospital_id, month, entity) → runs
  `explainer`. Requires `ai.read`.
- `POST /ai/agents/report` — (body: hospital_id, month, lang) → runs
  `report_writer`, stores the narrative with existing report persistence.
  Requires `ai.read` **and** `ai.write`.
- `POST /ai/agents/digest` — (body: month) → runs `triage` across the user's
  hospitals. Requires `ai.read` **and** `ai.write`. UI label:
  **"Generate Triage Digest"** (on-demand; not a scheduled daily job).
- `GET /ai/agents/status` — `{enabled, permissions, provider}` for UI gating.
  Auth only.
- Admin-only (System Control, `system.manage_users`):
  - `GET /ai/agents/runs` — paginated audit (metadata columns above).
  - `GET/PUT /ai/agents/admin` — per-user daily caps, `agents_enabled` toggle,
    `ai_provider` + local model settings + **`agent_provider_roles`
    (per-profile provider assignment)**, retention period.

Daily cap: per-user daily counter (default 20 runs/day) stops a single account,
with a clear message.

### 9. Access control summary (user-confirmed + review-clarified)

Explicit permission semantics:

| Permission | Meaning |
|---|---|
| `ai.read` | Agent may **read authorized analytical data** and run Q&A/explainer. |
| `ai.write` | Agent may **create/persist AI-generated artifacts** (report, digest) in addition to `ai.read`. Agents never modify analytical/source data under either permission. |
| `system.manage_users` (admin) | `agent_runs` audit + daily caps + `agents_enabled` toggle + provider settings + retention, **in System Control only**. |
| superadmin | bypasses all permission gates. |

| Config | Effect |
|---|---|
| `agents_enabled` (**default OFF**) | OFF → all `/ai/agents/*` disabled (UI hidden, API returns `{enabled:false}`), existing AI features untouched. |
| `agents_provider` / `agent_provider_roles` / `local_runtime` / `local_model` / `local_url` | provider resolution + per-role routing for agents (Section 3); independent of the kill-switch. |

Hospital scope: every tool limited to `get_user_hospital_ids` (server-enforced,
Section 4).

Permissions are existing seeded rows (`ai.read`/`ai.write` in
CANONICAL_PERMISSION_CODENAMES); no role except superadmin is granted them by
seed — admins grant via the existing Role editor / Direct-Permission picker.

### 10. Kill-switch

- New keys added to `AI_CONFIG_KEYS` (`app/config_utils.py`): `agents_enabled`
  (default `"false"`), `agents_provider`, `agent_provider_roles`, `local_runtime`,
  `local_model`, `local_url` — stored in SystemSetting, editable from System
  Control → Settings → AI via the existing config GET/PUT endpoints (with
  validation: `agent_provider_roles` must be a JSON object mapping only the four
  profile names to known provider values).
- Runtime reads them via `reload_ai_config()`-style refresh; the agents router
  checks `agents_enabled` before any work. When OFF, **no LLM call is made**.

### 11. Frontend

- New `static/js/agents.js` (+ chat panel):
  - AI Assistant surface for Q&A (visible only with `ai.read` + `agents_enabled`).
  - "Explain" buttons on outlier/anomaly/rule-failure/report cards → renders the
    explainer result as FACTS / ANALYSIS / CONTRIBUTORS / ACTION blocks.
  - "Generate report" reuse in AI Reports; **"Generate Triage Digest"** button on
    Dashboard / System Control (both need `ai.write`).
  - All panels auto-hide when `agents_enabled` is false (status endpoint).
- System Control gains an **AI Agents admin view**: `agent_runs` audit table
  (showing data_version, model, language, cache_hit, fallback_used, duration,
  status), daily-cap fields, `agents_enabled` toggle, **AI provider radio
  (Local / Gemini / OpenAI-compatible / Auto), per-profile ("type of work")
  provider dropdowns for the four agents (uses global selection when unset),
  and local fields (runtime, model, URL)**, retention setting — admin-only,
  mirroring Users/Logs patterns in `admin.js`.
- i18n keys added for every new static string (EN + AR) per repo policy.

### 12. Tests (TDD — write failing tests first)

- `tests/test_agents_runtime.py` — mock LLM (scripted tool JSON): loop mechanics,
  protocol shape (tools/done only), parallel batching, early finish, step/
  tool-call/token/runtime budget enforcement, JSON-parse failure + 429 retry +
  deterministic fallback, single-flight dedup, history compression, **provider
  resolution: `agents_provider` = local/gemini/openai_compatible/auto (auto
  picks local when configured and reachable, else default cloud); unreachable
  local falls back without erroring; `agent_provider_roles` per-profile routing —
  mapped role wins, unmapped role falls back to global `agents_provider`, mapped
  but unreachable provider degrades to global without erroring; invalid
  `agent_provider_roles` rejected by settings validation**.
- `tests/test_agents_tools.py` — **mandatory security/isolation suite**:
  - User A (hospital A) requests hospital B → `ACCESS_DENIED`.
  - Invalid hospital ID / malformed month → rejected.
  - LLM requests an unauthorized tool → tool rejected with a validation observation.
  - Cache entry from User B's scope is never served to User A (scope-hash mismatch).
  - `agents_enabled=false` → no LLM call is made.
  - `ai.write` missing → report/digest blocked; `ai.read` missing → all blocked.
  - Tool response limits: max rows/chars enforced; top-k truncation works.
  - Daily-cap enforcement.
- `tests/test_agents_api.py` — permissions (403s), status endpoint with
  `agents_enabled` off/on and provider field, superadmin bypass, admin runs
  audit (retention-aware), admin provider settings round-trip
  (`agents_provider`, `agent_provider_roles` validation included), conversation/
  messages round-trip with `message_type`.
- `tests/test_agents_js.py` — static checks: gating vars, explain blocks, digest
  button label, `agents_enabled` hiding, provider radio/labels in the AI config
  view, `__()` i18n coverage for `agents.js`.

## Files touched
- New: `app/agents/` package (runtime, tools, cache, 4 profiles, grounding
  policy), `app/api/agents.py`, 3 Alembic migrations, `static/js/agents.js`,
  `tests/test_agents_*.py`.
- Edited: `app/models.py` (3 tables), `app/plugins/ai/cache.py` (entity key +
  version stamp), `app/plugins/ai/providers.py` (local/Ollama provider config
  reusing the OpenAI-compatible path), `app/config_utils.py` (`agents_enabled`,
  `agents_provider`, `agent_provider_roles`, `local_runtime`, `local_model`,
  `local_url` keys), `app/api/config_api.py` (validation + System Control AI
  settings), upload/analysis re-run hooks (data_version stamp bump),
  `static/css/styles.css`, `static/js/i18n.js`, `static/js/admin.js` (AI Agents
  admin view + provider settings incl. per-role dropdowns), existing
  report/anomaly UI (explain buttons), `app/main.py` route registration if
  needed.

## Verification
- Full pytest suite green (currently 1237); `node --check` on new/modified JS.
- Live smoke: `agents_enabled` OFF → status disabled + existing AI reports
  unchanged; ON + `ai.read` granted → Q&A returns tool-grounded numbers in the
  FACTS block; quota exhausted (mock 429) → deterministic fallback, HTTP 200;
  restricted user cannot obtain another hospital's numbers via chat, cache, or
  malformed args; provider = `auto` with local reachable → runs against local
  (Ollama), with local unreachable → cloud fallback, HTTP 200; hybrid
  `agent_provider_roles` {report_writer→gemini, others→local} → report run
  records `model/provider=gemini`, Q&A run records local, unmapped profile
  follows global selection.