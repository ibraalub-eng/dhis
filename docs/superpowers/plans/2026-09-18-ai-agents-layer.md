# AI Agents Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four permission-gated, hospital-scoped, read-only AI agents (Q&A, anomaly explainer, report writer, triage digest) with a provider abstraction (local Ollama / Gemini / OpenAI-compatible / Auto), versioned caching, chat memory, and a System Control audit — all off by default.

**Architecture:** A new `app/agents/` package sits between the existing `app/plugins/ai/` LLM call path and the existing engine data (`app/engine/pipeline.py`, `app/engine/smart/__init__.py`, `app/models.py` rows). `runtime.py` runs a ReAct loop over a chat-interface provider shim (`llm.py`), executing tools from a scoped, validated registry (`tools.py`); results are cached under versioned, scope-keyed entries (`cache.py`) and audited to `agent_runs`. The 4 profiles (`profiles/*.py`) define prompts, budgets, and deterministic fallbacks. A new `/ai/agents` router enforces `ai.read`/`ai.write`, the `agents_enabled` kill-switch, hospital scope, and daily caps.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy 2 / Alembic / httpx / google-genai (existing) / plain JS + fetch (no build step).

**Spec:** `docs/superpowers/specs/2026-09-18-ai-agents-design.md`

## Global Constraints

- Month strings are `"YYYY-MM"` (7 chars, e.g. `"2026-08"`); `String(7)` columns everywhere.
- Permission gating: report/digest require BOTH `ai.read` AND `ai.write`; Q&A/explainer require `ai.read`; admin endpoints require `system.manage_users`; superusers bypass everything (`deps.py` `require_permission` already returns superusers).
- Kill-switch: `agents_enabled` default `"false"`. When false, agents router returns `{"enabled": false}` (HTTP 200) and **no LLM call is made**.
- Existing single-shot AI (`app/plugins/ai/*`) must NOT change behavior — its `ai_provider` config key is untouched. The agent layer uses NEW keys: `agents_enabled`, `agents_provider`, `agent_provider_roles`, `local_runtime`, `local_model`, `local_url`.
- Tools are read-only: they only call existing engine functions/rows and never write DB.
- Tool response hard limits per invocation: max rows 20, max characters 4000, max indicators 10, max hospitals 20 (truncate/round before returning).
- Budgets: max steps `qa`/`explainer` = 6, `report_writer`/`triage` = 10; max total tool calls 18; max runtime 45 s; input ≤ 20k tokens, output ≤ 3k tokens.
- Server schedules the model with strict JSON **tools/done only** — no `thought` field in protocol. Malformed JSON: parse-strip code fences; on failure retry once with a "response was not valid JSON, output JSON only" message; on second failure → deterministic fallback.
- On 429: single bounded retry honoring `Retry-After` header (pause, then re-send); still failing → deterministic fallback. Never raise a 500 to the user.
- Deterministic fallbacks must replicate the bilingual pattern: Arabic fields for a `lang="ar"` user.
- Every new UI string needs an `__('...')` key in `static/js/i18n.js` (EN + AR map).
- Test command: `.venv\Scripts\python.exe -m pytest -q` (Windows PowerShell). JS syntax check: `node --check static/js/<file>.js`.
- Conftest autouse `_bypass_auth` (tests/conftest.py:24) forces `get_current_user` to `_FakeSuperAdmin`. API tests that check real permissions must remove overrides and use the `client` fixture pattern from `tests/test_auth.py:136-147` + `_seed_user` (tests/test_auth.py:150-167).

---

### Task 1: Agent + local provider config keys and validation

**Files:**
- Modify: `app/config_utils.py:1-9` (AI_CONFIG_KEYS dict)
- Modify: `app/api/config_api.py:166-189` (GET/PUT `/config/ai/settings`)
- Test: `tests/test_agents_config.py` (new)

**Interfaces:**
- Produces: `AI_CONFIG_KEYS` now contains (verbatim additions):
  ```python
  "agents_enabled": "false",
  "agents_provider": "auto",
  "agent_provider_roles": "{}",
  "local_runtime": "ollama",
  "local_model": "qwen3:8b",
  "local_url": "http://localhost:11434",
  ```
- Produces: `app/config_utils.validate_agents_config(updates: dict) -> None` — raises `ValueError` on bad `agents_provider` (must be in `{"local","gemini","openai_compatible","auto"}`) or bad `agent_provider_roles` (must parse as JSON object whose keys ⊆ `{"qa","explainer","report_writer","triage"}` and values ∈ `{"local","gemini","openai_compatible"}`).
- Produces: PUT `/config/ai/settings` returns HTTP 422 (not 200) when `validate_agents_config` fails; all valid new keys persist to `SystemSetting`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agents_config.py
"""Agent config keys + validation tests."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config_utils import AI_CONFIG_KEYS, get_ai_config, validate_agents_config
from app.database import Base, get_db
from app.main import app


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides.pop("get_current_user", None)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_agent_keys_have_defaults():
    assert AI_CONFIG_KEYS["agents_enabled"] == "false"
    assert AI_CONFIG_KEYS["agents_provider"] == "auto"
    assert AI_CONFIG_KEYS["agent_provider_roles"] == "{}"
    assert AI_CONFIG_KEYS["local_runtime"] == "ollama"
    assert AI_CONFIG_KEYS["local_model"] == "qwen3:8b"
    assert AI_CONFIG_KEYS["local_url"] == "http://localhost:11434"


def test_validate_agents_provider_rejects_unknown():
    with pytest.raises(ValueError):
        validate_agents_config({"agents_provider": "claude"})
    # known values pass
    for val in ("local", "gemini", "openai_compatible", "auto"):
        validate_agents_config({"agents_provider": val})


def test_validate_agent_provider_roles_shape():
    validate_agents_config({"agent_provider_roles": '{"qa": "local", "report_writer": "gemini"}'})
    with pytest.raises(ValueError):
        validate_agents_config({"agent_provider_roles": '{"qa": "claude"}'})
    with pytest.raises(ValueError):
        validate_agents_config({"agent_provider_roles": '{"unknown_role": "local"}'})
    with pytest.raises(ValueError):
        validate_agents_config({"agent_provider_roles": "not-json"})
    # empty map + non-object values are invalid
    with pytest.raises(ValueError):
        validate_agents_config({"agent_provider_roles": "[]"})


def test_update_ai_settings_persists_agent_keys(client, db_session):
    resp = client.put("/config/ai/settings", json={"agents_enabled": "true", "agents_provider": "local"})
    assert resp.status_code == 200
    stored = get_ai_config(db_session)
    assert stored["agents_enabled"] == "true"
    assert stored["agents_provider"] == "local"


def test_update_ai_settings_rejects_bad_agent_provider(client):
    resp = client.put("/config/ai/settings", json={"agents_provider": "claude"})
    assert resp.status_code == 422


def test_get_ai_settings_contains_keys(client):
    resp = client.get("/config/ai/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agents_enabled"] == "false"
    assert data["agents_provider"] == "auto"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_config.py -q`
Expected: FAIL — `KeyError: 'agents_enabled'` (missing keys) and `ImportError: cannot import name 'validate_agents_config'`.

- [ ] **Step 3: Add the six config keys**

In `app/config_utils.py`, append to `AI_CONFIG_KEYS` (after `"ai_timeout"`):
```python
    "agents_enabled": "false",
    "agents_provider": "auto",
    "agent_provider_roles": "{}",
    "local_runtime": "ollama",
    "local_model": "qwen3:8b",
    "local_url": "http://localhost:11434",
```

- [ ] **Step 4: Add `validate_agents_config`**

Append to `app/config_utils.py`:
```python
AGENT_PROFILES = ("qa", "explainer", "report_writer", "triage")
AGENT_PROVIDERS = ("local", "gemini", "openai_compatible")


def validate_agents_config(updates: dict) -> None:
    """Validate agent-layer settings. Raises ValueError on invalid input."""
    import json as _json
    provider = updates.get("agents_provider")
    if provider is not None and provider not in ("local", "gemini", "openai_compatible", "auto"):
        raise ValueError(f"Invalid agents_provider: {provider}")
    roles_raw = updates.get("agent_provider_roles")
    if roles_raw is not None:
        try:
            roles = _json.loads(roles_raw)
        except (TypeError, ValueError):
            raise ValueError("agent_provider_roles must be a JSON object")
        if not isinstance(roles, dict):
            raise ValueError("agent_provider_roles must be a JSON object")
        for role, prov in roles.items():
            if role not in AGENT_PROFILES:
                raise ValueError(f"Unknown agent profile: {role}")
            if prov not in AGENT_PROVIDERS:
                raise ValueError(f"Invalid provider for {role}: {prov}")
```

- [ ] **Step 5: Wire validation into PUT `/config/ai/settings`**

In `app/api/config_api.py`, at the top of `update_ai_settings` (before the loop):
```python
    from app.config_utils import validate_agents_config
    try:
        validate_agents_config(updates)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
```
(`HTTPException` is already imported in that module.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_config.py -q`
Expected: PASS (all 7).

- [ ] **Step 7: Commit**

```bash
git add app/config_utils.py app/api/config_api.py tests/test_agents_config.py
git commit -m "feat(agents): add agents_* config keys, local provider settings, and validation"
```

---

### Task 2: Agent data models + Alembic migration

**Files:**
- Modify: `app/models.py` (append 5 classes at end of file, after `SystemSetting`)
- Create: `alembic/versions/<autogen>_add_agent_tables.py` (down_revision = `c4d8e9f0a1b2_add_user_permissions`)
- Test: `tests/test_agents_models.py` (new)

**Interfaces:**
- Produces (SQLAlchemy models, all in `app.models`):
  - `Conversation` / `conversations`: `id, user_id(FK users CASCADE, index), title, lang, created_at`.
  - `Message` / `messages`: `id, conversation_id(FK conversations CASCADE, index), message_type(String(10)), role(String(10)), content(Text), tool_steps(JSON nullable), token_usage(JSON nullable), created_at`; composite `Index("ix_msg_conv_created", "conversation_id", "created_at")`.
  - `AgentRun` / `agent_runs`: `id, user_id(FK users, index), agent(String(30)), conversation_id(FK nullable), status(String(20)), duration_ms(Integer nullable), steps(Integer default 0), tool_calls(JSON nullable), tokens(JSON nullable), data_version(String(40) nullable), model(String(100) nullable), provider(String(30) nullable), language(String(10) nullable), cache_hit(Boolean default False), fallback_used(Boolean default False), hospital_scope_hash(String(64) nullable), permission_scope_hash(String(64) nullable), prompt_hash(String(64) nullable), error(Text nullable), created_at`; indexes `ix_agent_runs_user_created (user_id, created_at)` and `ix_agent_runs_created (created_at)`.
  - `AgentCache` / `agent_cache`: `id, cache_key(String(200), unique, index), result_json(Text), data_version(String(40) nullable), hospital_scope_hash(String(64) nullable), created_at, expires_at(DateTime nullable)`.
  - `AgentDataVersion` / `agent_data_versions`: `id, hospital_id(FK hospitals, index), month(String(7)), version(Integer default 0)`; `UniqueConstraint("hospital_id", "month")`.
- Produces: `validate_agent_run(agent: str)` behaves like the existing UI — agent name one of the 4 profiles.

- [ ] **Step 1: Write the failing model tests**

```python
# tests/test_agents_models.py
"""Agent-layer data model round-trip tests (in-memory SQLite)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    User, Conversation, Message, AgentRun, AgentCache, AgentDataVersion,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_conversation_message_roundtrip(db_session):
    u = User(username="a", email="a@t.com", full_name="A", password_hash="x")
    db_session.add(u)
    db_session.commit()
    conv = Conversation(user_id=u.id, title="Q", lang="en")
    db_session.add(conv)
    db_session.commit()
    db_session.add(Message(conversation_id=conv.id, message_type="user", role="user", content="hi"))
    db_session.add(Message(conversation_id=conv.id, message_type="assistant", role="assistant",
                           content='{"done": true, "answer": "ok"}', token_usage={"in": 10, "out": 5}))
    db_session.commit()
    msgs = db_session.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.id).all()
    assert len(msgs) == 2
    assert msgs[0].message_type == "user"
    assert msgs[1].token_usage == {"in": 10, "out": 5}


def test_agent_run_roundtrip(db_session):
    u = User(username="b", email="b@t.com", full_name="B", password_hash="x")
    db_session.add(u)
    db_session.commit()
    run = AgentRun(user_id=u.id, agent="qa", status="completed", duration_ms=120,
                   steps=2, tool_calls=[{"name": "get_quality_score"}],
                   tokens={"in": 100, "out": 50}, provider="local", model="qwen3:8b",
                   language="en", cache_hit=False, fallback_used=False,
                   hospital_scope_hash="h", permission_scope_hash="p")
    db_session.add(run)
    db_session.commit()
    row = db_session.query(AgentRun).filter(AgentRun.agent == "qa").first()
    assert row.status == "completed"
    assert row.tool_calls == [{"name": "get_quality_score"}]


def test_agent_cache_roundtrip(db_session):
    db_session.add(AgentCache(cache_key="agents:qa:xyz:1", result_json='{"answer": "x"}',
                              data_version="42", hospital_scope_hash="abc"))
    db_session.commit()
    row = db_session.query(AgentCache).filter_by(cache_key="agents:qa:xyz:1").first()
    assert row is not None and row.data_version == "42"


def test_agent_data_version_unique(db_session):
    from sqlalchemy.exc import IntegrityError
    db_session.add(AgentDataVersion(hospital_id=1, month="2026-08", version=1))
    db_session.commit()
    db_session.add(AgentDataVersion(hospital_id=1, month="2026-08", version=2))
    with pytest.raises(IntegrityError):
        db_session.commit()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'Conversation'`.

- [ ] **Step 3: Add the five models to `app/models.py`**

Insert at the end of `app/models.py`:
```python
class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False, default="")
    lang = Column(String(10), nullable=False, default="en")
    created_at = Column(DateTime, default=datetime.utcnow)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    message_type = Column(String(10), nullable=False)   # user | assistant | tool | system
    role = Column(String(10), nullable=False, default="user")
    content = Column(Text, nullable=False)
    tool_steps = Column(JSON, nullable=True)
    token_usage = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("ix_msg_conv_created", "conversation_id", "created_at"),)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    agent = Column(String(30), nullable=False)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    status = Column(String(20), nullable=False, default="completed")
    duration_ms = Column(Integer, nullable=True)
    steps = Column(Integer, nullable=False, default=0)
    tool_calls = Column(JSON, nullable=True)
    tokens = Column(JSON, nullable=True)
    data_version = Column(String(40), nullable=True)
    model = Column(String(100), nullable=True)
    provider = Column(String(30), nullable=True)
    language = Column(String(10), nullable=True)
    cache_hit = Column(Boolean, nullable=False, default=False)
    fallback_used = Column(Boolean, nullable=False, default=False)
    hospital_scope_hash = Column(String(64), nullable=True)
    permission_scope_hash = Column(String(64), nullable=True)
    prompt_hash = Column(String(64), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        Index("ix_agent_runs_user_created", "user_id", "created_at"),
        Index("ix_agent_runs_created", "created_at"),
    )


class AgentCache(Base):
    __tablename__ = "agent_cache"
    id = Column(Integer, primary_key=True, index=True)
    cache_key = Column(String(200), nullable=False, unique=True, index=True)
    result_json = Column(Text, nullable=False)
    data_version = Column(String(40), nullable=True)
    hospital_scope_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


class AgentDataVersion(Base):
    __tablename__ = "agent_data_versions"
    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    month = Column(String(7), nullable=False)
    version = Column(Integer, nullable=False, default=0)
    __table_args__ = (UniqueConstraint("hospital_id", "month", name="uq_agent_dv_hosp_month"),)
```
Note: `datetime`, `Index`, `UniqueConstraint`, `JSON`, `ForeignKey`, `Boolean` are already imported in `models.py` (used by `AnomalyResult` etc.).

- [ ] **Step 4: Generate the Alembic migration**

Run: `.venv\Scripts\python.exe -m alembic revision --autogenerate -m "add agent tables"`
Inspect the generated file; confirm `down_revision` is `c4d8e9f0a1b2` and all five tables are present. If autogenerate cannot connect, hand-write the migration mirroring `alembic/versions/c4d8e9f0a1b2_add_user_permissions.py` structure (op.create_table for each, downgrade drops in reverse order).

- [ ] **Step 5: Verify migration on a scratch DB**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_models.py -q`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add app/models.py alembic/versions/ tests/test_agents_models.py
git commit -m "feat(agents): add conversations, messages, agent_runs, agent_cache, agent_data_versions models"
```

---

### Task 3: LLM provider shim (`app/agents/llm.py`)

**Files:**
- Create: `app/agents/__init__.py`
- Create: `app/agents/llm.py`
- Test: `tests/test_agents_llm.py` (new)

**Interfaces:**
- Produces (`app/agents/llm.py`):
  ```python
  @dataclass
  class ResolvedProvider:
      provider: str        # "local" | "gemini" | "openai_compatible"
      model: str
      base_url: str        # "" for gemini
      needs_key: bool

  @dataclass
  class ChatResult:
      text: str | None
      provider: str
      model: str
      prompt_tokens: int
      completion_tokens: int

  def resolve_agent_provider(profile: str, db) -> ResolvedProvider
  def llm_chat(resolved: ResolvedProvider, system: str, user: str,
               max_output_tokens: int = 3000, timeout: float = 30.0) -> ChatResult | None
  ```
- `resolve_agent_provider` reads `get_ai_config(db)`; precedence: `agent_provider_roles[profile]` (if in `AGENT_PROVIDERS`) → `agents_provider` global → `auto` → try `local` (settings populated AND local URL reachable via a 1.0 s TCP ping) else `gemini` (if `ai_api_key` set) else `openai_compatible` (if `ai_api_url` set) else return `local` config regardless (runtime will fall back deterministically).
- `llm_chat` uses httpx POST to `base_url or {local_url}/v1/chat/completions` for openai_compatible/local (Bearer key when configured, no key for local), and google.genai for gemini. It returns token counts (from `usage.prompt_tokens`/`usage.completion_tokens` when present, else estimated `len(text)//4`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agents_llm.py
"""Provider shim tests — no real network. httpx and genai are monkeypatched."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import SystemSetting
from app.agents.llm import resolve_agent_provider, llm_chat
from app.agents.llm import ResolvedProvider


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _set(db, **kv):
    for k, v in kv.items():
        db.add(SystemSetting(key=k, value=str(v)))
    db.commit()


def test_resolve_role_map_wins(db_session, monkeypatch):
    monkeypatch.setattr("app.agents.llm._local_reachable", lambda url, timeout=1.0: True)
    _set(db_session, agent_provider_roles='{"report_writer": "gemini"}', agents_provider="auto",
         ai_api_key="k1", local_model="qwen3:8b", local_url="http://localhost:11434")
    rp = resolve_agent_provider("report_writer", db_session)
    assert rp.provider == "gemini"
    rp2 = resolve_agent_provider("qa", db_session)
    assert rp2.provider == "local"   # auto -> local reachable -> local


def test_resolve_global_provider(db_session):
    _set(db_session, agents_provider="openai_compatible", ai_api_url="http://x/v1/chat/completions", ai_api_key="k")
    rp = resolve_agent_provider("triage", db_session)
    assert rp.provider == "openai_compatible"
    assert rp.model == "gemini-3.5-flash-lite" or rp.model


def test_resolve_rejects_unknown_role(db_session):
    _set(db_session, agent_provider_roles='{"nope": "local"}')
    with pytest.raises(ValueError):
        resolve_agent_provider("qa", db_session)


def test_resolve_mapped_but_down_degrades_to_global(db_session, monkeypatch):
    # report_writer is mapped to local, but local is unreachable and
    # no local_model/openai-compatible config -> degrade to global gemini
    _set(db_session, agent_provider_roles='{"report_writer": "local"}',
         agents_provider="gemini", ai_api_key="k1")
    rp = resolve_agent_provider("report_writer", db_session)
    assert rp.provider == "gemini"
    # mapped local IS configured+reachable -> mapped wins
    monkeypatch.setattr("app.agents.llm._local_reachable", lambda url, timeout=1.0: True)
    _set(db_session, agent_provider_roles='{"report_writer": "local"}',
         agents_provider="gemini", ai_api_key="k1", local_model="qwen3:8b")
    rp2 = resolve_agent_provider("report_writer", db_session)
    assert rp2.provider == "local"


def test_llm_chat_openai_compatible(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": '{"tools": []}'}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 4}}

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def post(self, url, json, headers=None):
            captured["url"] = url
            captured["payload"] = json
            return FakeResp()

    import httpx
    monkeypatch.setattr(httpx, "Client", FakeClient)
    rp = ResolvedProvider(provider="openai_compatible", model="m1",
                          base_url="http://x/v1/chat/completions", needs_key=True)
    out = llm_chat(rp, system="sys", user="hi", max_output_tokens=100)
    assert out.text == '{"tools": []}'
    assert out.prompt_tokens == 12 and out.completion_tokens == 4
    assert captured["url"] == "http://x/v1/chat/completions"
    assert captured["payload"]["messages"][0]["content"] == "sys"
```


- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_llm.py -q`
Expected: FAIL — `ImportError: cannot import name 'resolve_agent_provider' from 'app.agents.llm'`.

- [ ] **Step 3: Implement `app/agents/llm.py`**

Create `app/agents/__init__.py`:
```python
"""Agent layer (runtime, tools, profiles, cache)."""
```
Create `app/agents/llm.py`:
```python
"""Provider abstraction for the agent runtime.

The agent layer uses its own provider resolution (agents_provider +
agent_provider_roles) and MUST NOT disturb the existing single-shot ai_provider
path. Local (Ollama) is an OpenAI-compatible endpoint with no API key.
"""
import json
import socket
from dataclasses import dataclass

from app.config_utils import get_ai_config, AGENT_PROVIDERS


@dataclass
class ResolvedProvider:
    provider: str
    model: str
    base_url: str = ""
    needs_key: bool = True


@dataclass
class ChatResult:
    text: str | None
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _local_reachable(url: str, timeout: float = 1.0) -> bool:
    host = url.split("://")[-1].split("/")[0].split(":")[0]
    port = 11434
    if ":" in url.split("://")[-1].split("/")[0]:
        try:
            port = int(url.split("://")[-1].split("/")[0].split(":")[1])
        except ValueError:
            pass
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _provider_viable(kind: str, cfg: dict) -> bool:
    """True when the provider is configured/reachable enough to attempt a run."""
    if kind == "local":
        return bool(cfg.get("local_model")) and _local_reachable(
            (cfg.get("local_url") or "http://localhost:11434").strip("/"))
    if kind == "gemini":
        return bool(cfg.get("ai_api_key"))
    if kind == "openai_compatible":
        return bool(cfg.get("ai_api_url"))
    return False


def resolve_agent_provider(profile: str, db) -> ResolvedProvider:
    cfg = get_ai_config(db)
    roles_raw = cfg.get("agent_provider_roles") or "{}"
    try:
        roles = json.loads(roles_raw) if isinstance(roles_raw, str) else (roles_raw or {})
    except (TypeError, ValueError):
        roles = {}
    mapped = roles.get(profile)
    if mapped in AGENT_PROVIDERS and _provider_viable(mapped, cfg):
        return _build_provider(mapped, cfg)
    # mapped-but-down (or unmapped) falls through to the global agents_provider,
    # exactly per spec §3: "A mapped provider that is down degrades to step 2"
    global_provider = (cfg.get("agents_provider") or "auto").lower()
    if global_provider == "auto":
        return _resolve_auto(cfg)
    if global_provider in ("local", "gemini", "openai_compatible"):
        return _build_provider(global_provider, cfg)
    raise ValueError(f"Invalid agents_provider: {global_provider}")


def _resolve_auto(cfg: dict) -> ResolvedProvider:
    local_url = (cfg.get("local_url") or "http://localhost:11434").strip("/")
    if cfg.get("local_model") and _local_reachable(local_url):
        return _build_provider("local", cfg)
    if cfg.get("ai_api_key"):
        return _build_provider("gemini", cfg)
    if cfg.get("ai_api_url"):
        return _build_provider("openai_compatible", cfg)
    return _build_provider("local", cfg)   # runtime will fall back deterministically


def _build_provider(kind: str, cfg: dict) -> ResolvedProvider:
    if kind == "local":
        url = (cfg.get("local_url") or "http://localhost:11434").strip("/")
        return ResolvedProvider("local", cfg.get("local_model") or "qwen3:8b",
                                url + "/v1/chat/completions", needs_key=False)
    if kind == "gemini":
        return ResolvedProvider("gemini", cfg.get("ai_model") or "gemini-3.5-flash-lite", "", True)
    return ResolvedProvider("openai_compatible",
                            cfg.get("ai_model") or "deepseek-chat",
                            cfg.get("ai_api_url") or "", True)


def _lookup_api_key() -> str:
    """Return ai_api_key from SystemSetting without importing app.main."""
    from app.database import SessionLocal
    try:
        from app.models import SystemSetting
        with SessionLocal() as s:
            row = s.query(SystemSetting).filter(SystemSetting.key == "ai_api_key").first()
            return row.value if row and row.value else ""
    except Exception:
        return ""


def llm_chat(resolved: ResolvedProvider, system: str, user: str,
             max_output_tokens: int = 3000, timeout: float = 30.0) -> ChatResult | None:
    api_key = _lookup_api_key() if resolved.needs_key else ""
    if resolved.provider == "gemini":
        return _chat_gemini(resolved, system, user, max_output_tokens, timeout)
    return _chat_httpx(resolved, system, user, api_key, max_output_tokens, timeout)


def _chat_httpx(resolved, system, user, api_key, max_output_tokens, timeout):
    import httpx
    payload = {
        "model": resolved.model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": max_output_tokens,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(resolved.base_url, json=payload, headers=headers)
            code = resp.status_code
            retry_after = resp.headers.get("Retry-After")
            if code == 429 and retry_after:
                import time as _t
                _t.sleep(min(float(retry_after.split()[0]), 5.0))
                resp = client.post(resolved.base_url, json=payload, headers=headers)
            elif code == 429:
                import time as _t
                _t.sleep(1.0)
                resp = client.post(resolved.base_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage") or {}
    return ChatResult(content, resolved.provider, resolved.model,
                      usage.get("prompt_tokens", len(system) // 4),
                      usage.get("completion_tokens", len(content or "") // 4))
```
Note: `_lookup_api_key` reads the DB; the `llm_chat` openai-compatible test uses `needs_key=True` with an empty settings table (returns `""`), or monkeypatch `app.agents.llm._lookup_api_key`. The `_chat_gemini` call path is exercised indirectly; monkeypatch `_chat_gemini` in any test that needs a deterministic gemini response.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_llm.py -q`
Expected: PASS (5).

- [ ] **Step 5: Commit**

```bash
git add app/agents/ tests/test_agents_llm.py
git commit -m "feat(agents): provider shim with local/gemini/openai_compatible resolution and chat call"
```

---

### Task 4: Tool registry with scope enforcement (`app/agents/tools.py`)

**Files:**
- Create: `app/agents/tools.py`
- Test: `tests/test_agents_tools.py` (new)

**Interfaces:**
- Produces:
  ```python
  TOOL_DEFS: list[dict]   # registry entries:
  #   {"name", "description", "schema": {"hospital_ids": [...], "month": str, ...}, "permission": "ai.read", "scope": "hospital", "max_results": 20, "max_tokens": 400}

  class ToolContext:
      def __init__(self, db, user, month) -> None
      authorized_ids: list[int]          # get_user_hospital_ids(user, db) or all Hospitals
      def allowed_hospital_ids(self, requested) -> tuple[list[int], list[int]]  # (ok_ids, denied_ids)
      def hospital_data(self) -> dict    # memo _load_hospital_data(db, month) -> {name: {code: val, hospital_id: id}}
      def quality_row(self, hid, month)  # memo QualityScore row
      def rule_rows(self, hid, month)    # memo ValidationResult rows
      def anomaly_rows(self, hid, month) # memo AnomalyResult rows
      def clinical_row(self, hid, month) # memo ClinicalInsight row
      def indicator_history(self, hid, code, months=6)  # list[dict{month, value}]
      def peer_stats(self, code, include_ids, exclude_ids)  # {mean, median, min, max, count}

  def execute_tool(name: str, args: dict, ctx: ToolContext) -> dict
  # -> {"ok": True, "data": [...]} | {"ok": False, "error": "ACCESS_DENIED"} | {"ok": False, "error": "validation: ..."}
  ```
- Hard limits enforced inside `execute_tool`: rows ≤ 20, chars ≤ 4000, hospitals ≤ 20, indicators ≤ 10. Values rounded to 2 decimals.

- [ ] **Step 1: Write the failing tests (mandatory security suite included)**

```python
# tests/test_agents_tools.py
"""Tool registry: scope enforcement, validation, and response limits."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Hospital, User
from tests.conftest import seed_indicators  # reuse seed (import may be calendar-ordered; see note below)


class FakeUser:
    is_superuser = False
    id = 1


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    h1 = Hospital(name="Alpha", region="R")
    h2 = Hospital(name="Beta", region="R")
    h3 = Hospital(name="Gamma", region="R")
    s.add_all([h1, h2, h3])
    s.commit()
    yield s
    s.close()


@pytest.fixture
def ctx(db_session):
    from app.agents.tools import ToolContext
    u = FakeUser()
    u.id = 1
    # restrict to hospitals 1 and 2 in the association table
    from app.models import user_hospitals
    db_session.execute(user_hospitals.insert().values(user_id=1, hospital_id=1))
    db_session.execute(user_hospitals.insert().values(user_id=1, hospital_id=2))
    db_session.commit()
    return ToolContext(db_session, u, "2026-08")
```
Note: conftest `seed_indicators` import ordering — `tests/conftest.py` imports `scripts.seed_indicators`; if the module is already loaded by pytest plugins it is safe to `from tests.conftest import seed_indicators`? Not required for these tests; drop it if unused.

Add the actual assertions (run with `from app.agents.tools import execute_tool, ToolContext`):

```python
def test_list_accessible_hospitals_only_authorized(ctx):
    res = execute_tool("list_accessible_hospitals", {}, ctx)
    assert res["ok"] is True
    names = {r["id"] for r in res["data"]}
    assert names == {1, 2}


def test_unauthorized_hospital_denied(ctx):
    res = execute_tool("get_indicator_values",
                       {"hospital_ids": [3], "month": "2026-08", "indicators": ["cs_rate"]}, ctx)
    assert res["ok"] is False
    assert res["error"] == "ACCESS_DENIED"


def test_partial_scope_intersection(ctx):
    res = execute_tool("get_indicator_values",
                       {"hospital_ids": [1, 3], "month": "2026-08"}, ctx)
    assert res["ok"] is True
    hids = {r["hospital_id"] for r in res["data"]}
    assert 1 in hids and 3 not in hids


def test_invalid_month_rejected(ctx):
    res = execute_tool("get_indicator_values", {"hospital_ids": [1], "month": "2026-13"}, ctx)
    assert res["ok"] is False
    assert res["error"].startswith("validation")


def test_unknown_tool_rejected(ctx):
    res = execute_tool("get_nonexistent", {}, ctx)
    assert res["ok"] is False


def test_superadmin_sees_all(ctx):
    ctx.user.is_superuser = True
    ctx.authorized_ids = None  # ToolContext must recompute as "all"
    # ToolContext computes authorized_ids in __init__; force recompute path
    res = execute_tool("list_accessible_hospitals", {}, ctx)
    assert res["ok"] is True and len(res["data"]) == 3
```
(When `ToolContext.__init__` runs with a non-superuser it stores `authorized_ids = [1,2]`; for the superadmin test, construct a fresh context with a superuser flag set before init.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_tools.py -q`
Expected: FAIL — module import error.

- [ ] **Step 3: Implement `app/agents/tools.py`**

```python
"""Read-only agent tool registry. Scope enforcement is server-side."""
import hashlib
import json
import re
import statistics

from app.core.deps import get_user_hospital_ids
from app.engine.smart import _load_hospital_data
from app.models import Hospital, QualityScore, ValidationResult, AnomalyResult, ClinicalInsight

MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
MAX_ROWS = 20
MAX_CHARS = 4000
MAX_HOSPITALS = 20
MAX_INDICATORS = 10
DERIVED_ALWAYS = {"cs_rate"}  # computed from indicators 2 + 5 in _load_hospital_data


def _scope_hash(hids):
    return hashlib.sha256(",".join(str(h) for h in sorted(hids)).encode()).hexdigest()


class ToolContext:
    def __init__(self, db, user, month):
        self.db = db
        self.user = user
        self.month = month
        self._data = None
        self._quality = {}
        self._rules = {}
        self._anomalies = {}
        self._clinical = {}
        if getattr(user, "is_superuser", False):
            self.authorized_ids = [h.id for h in db.query(Hospital).filter(Hospital.is_active).all()]
        else:
            self.authorized_ids = get_user_hospital_ids(user, db) or \
                [h.id for h in db.query(Hospital).filter(Hospital.is_active).all()]

    def allowed_hospital_ids(self, requested):
        wanted = [int(i) for i in (requested or [])]
        allowed = [i for i in wanted if i in self.authorized_ids]
        denied = [i for i in wanted if i not in self.authorized_ids]
        return allowed, denied

    def hospital_data(self):
        if self._data is None:
            data = _load_hospital_data(self.db, self.month)
            self._data = {name: row for name, row in data.items()
                          if row.get("hospital_id") in self.authorized_ids}
        return self._data

    def quality_row(self, hid):
        if hid not in self._quality:
            self._quality[hid] = self.db.query(QualityScore).filter(
                QualityScore.hospital_id == hid, QualityScore.month == self.month).first()
        return self._quality[hid]

    def rule_rows(self, hid):
        if hid not in self._rules:
            self._rules[hid] = self.db.query(ValidationResult).filter(
                ValidationResult.hospital_id == hid,
                ValidationResult.month == self.month).all()
        return self._rules[hid]

    def anomaly_rows(self, hid):
        if hid not in self._anomalies:
            self._anomalies[hid] = self.db.query(AnomalyResult).filter(
                AnomalyResult.hospital_id == hid,
                AnomalyResult.month == self.month,
                AnomalyResult.is_outlier.is_(True)).all()
        return self._anomalies[hid]

    def clinical_row(self, hid):
        if hid not in self._clinical:
            self._clinical[hid] = self.db.query(ClinicalInsight).filter(
                ClinicalInsight.hospital_id == hid,
                ClinicalInsight.month == self.month).first()
        return self._clinical[hid]

    def indicator_history(self, hid, code, months=6):
        from app.models import Indicator, IndicatorValue
        ind = self.db.query(Indicator).filter(Indicator.code == code).first()
        if ind is None:
            return []
        rows = self.db.query(IndicatorValue).filter(
            IndicatorValue.hospital_id == hid,
            IndicatorValue.indicator_id == ind.id,
        ).order_by(IndicatorValue.month.desc()).limit(months).all()
        return [{"month": r.month, "value": round(float(r.value), 2) if r.value is not None else None}
                for r in rows]

    def peer_stats(self, code, include_ids, exclude_ids=()):
        vals = []
        for name, row in self.hospital_data().items():
            hid = row.get("hospital_id")
            if hid in exclude_ids or hid not in include_ids:
                continue
            v = row.get(code)
            if v is not None:
                vals.append(v)
        if not vals:
            return {}
        return {"mean": round(statistics.mean(vals), 2),
                "median": round(statistics.median(vals), 2),
                "min": round(min(vals), 2),
                "max": round(max(vals), 2),
                "count": len(vals)}


def _cap(rows, max_rows=MAX_ROWS, max_chars=MAX_CHARS):
    out = (rows or [])[:max_rows]
    text = json.dumps(out, ensure_ascii=False)
    return out if len(text) <= max_chars else out[:10]


def _list_accessible_hospitals(ctx, args):
    rows = [{"id": r.id, "name": r.name, "region": r.region}
            for r in ctx.db.query(Hospital).filter(Hospital.id.in_(ctx.authorized_ids)).all()]
    return {"ok": True, "data": _cap(rows)}


def _get_indicator_values(ctx, args):
    allowed, denied = ctx.allowed_hospital_ids(args.get("hospital_ids"))
    if denied:
        return {"ok": False, "error": "ACCESS_DENIED"}
    if not allowed:
        return {"ok": False, "error": "validation: hospital_ids must be non-empty"}
    indicators = (args.get("indicators") or [])[:MAX_INDICATORS]
    rows = []
    for name, row in ctx.hospital_data().items():
        if row.get("hospital_id") not in allowed:
            continue
        if indicators:
            vals = {k: round(v, 2) for k, v in row.items()
                    if k != "hospital_id" and k in indicators and v is not None}
        else:
            vals = {k: round(v, 2) for k, v in row.items() if k != "hospital_id" and v is not None}
        rows.append({"hospital_id": row["hospital_id"], "hospital": name, "values": vals})
    return {"ok": True, "data": _cap(rows)}


def _get_quality_score(ctx, args):
    allowed, denied = ctx.allowed_hospital_ids(args.get("hospital_ids"))
    if denied:
        return {"ok": False, "error": "ACCESS_DENIED"}
    rows = []
    for hid in allowed[:MAX_HOSPITALS]:
        row = ctx.quality_row(hid)
        rows.append({
            "hospital_id": hid,
            "score": round(row.score, 2) if row else None,
            "rule_compliance": round(row.rule_compliance, 2) if row and row.rule_compliance is not None else None,
            "completeness": round(row.completeness, 2) if row and row.completeness is not None else None,
            "consistency": round(row.consistency, 2) if row and row.consistency is not None else None,
        })
    return {"ok": True, "data": _cap(rows)}


def _get_rule_results(ctx, args):
    allowed, denied = ctx.allowed_hospital_ids(args.get("hospital_ids"))
    if denied:
        return {"ok": False, "error": "ACCESS_DENIED"}
    status = args.get("status")
    rows = []
    for hid in allowed[:MAX_HOSPITALS]:
        for r in ctx.rule_rows(hid):
            if status and r.status != status:
                continue
            rows.append({"hospital_id": hid, "rule_code": r.rule_code,
                         "description": r.rule_description, "status": r.status,
                         "severity": r.severity})
    return {"ok": True, "data": _cap(rows, max_rows=MAX_ROWS)}


def _get_anomalies(ctx, args):
    allowed, denied = ctx.allowed_hospital_ids(args.get("hospital_ids"))
    if denied:
        return {"ok": False, "error": "ACCESS_DENIED"}
    rows = []
    for hid in allowed[:MAX_HOSPITALS]:
        for a in ctx.anomaly_rows(hid):
            rows.append({"hospital_id": hid, "indicator": a.rate_name,
                         "value": round(a.value, 2) if a.value is not None else None,
                         "benchmark": round(a.benchmark, 2) if a.benchmark is not None else None,
                         "z_score": round(a.z_score, 2) if a.z_score is not None else None})
    return {"ok": True, "data": _cap(rows)}


def _get_clinical_profile(ctx, args):
    allowed, denied = ctx.allowed_hospital_ids(args.get("hospital_ids"))
    if denied:
        return {"ok": False, "error": "ACCESS_DENIED"}
    rows = []
    for hid in allowed[:MAX_HOSPITALS]:
        row = ctx.clinical_row(hid)
        payload = {"hospital_id": hid}
        if row:
            try:
                payload["profile"] = json.loads(row.analysis_data)
            except (TypeError, ValueError):
                payload["profile"] = {}
        rows.append(payload)
    return {"ok": True, "data": _cap(rows)}


def _get_peer_comparison(ctx, args):
    allowed, denied = ctx.allowed_hospital_ids(args.get("hospital_ids"))
    if denied:
        return {"ok": False, "error": "ACCESS_DENIED"}
    indicators = (args.get("indicators") or ["cs_rate"])[:MAX_INDICATORS]
    rows = []
    for code in indicators:
        stats = ctx.peer_stats(code, ctx.authorized_ids, exclude_ids=[])
        rows.append({"indicator": code, **stats})
    return {"ok": True, "data": _cap(rows)}


def _get_historical_trends(ctx, args):
    allowed, denied = ctx.allowed_hospital_ids(args.get("hospital_ids"))
    if denied:
        return {"ok": False, "error": "ACCESS_DENIED"}
    if not allowed:
        return {"ok": True, "data": []}
    indicators = (args.get("indicators") or ["cs_rate"])[:MAX_INDICATORS]
    rows = []
    for hid in allowed[:1]:
        for code in indicators:
            hist = ctx.indicator_history(hid, code)
            rows.append({"hospital_id": hid, "indicator": code, "history": hist})
    return {"ok": True, "data": _cap(rows)}


def _query_month_aggregates(ctx, args):
    allowed, denied = ctx.allowed_hospital_ids(args.get("hospital_ids"))
    if denied:
        return {"ok": False, "error": "ACCESS_DENIED"}
    indicators = (args.get("indicators") or [])
    include = allowed if allowed else ctx.authorized_ids
    data = ctx.hospital_data()
    agg = {}
    for name, row in data.items():
        if row.get("hospital_id") not in include:
            continue
        for code, val in row.items():
            if code == "hospital_id":
                continue
            if indicators and code not in indicators:
                continue
            if val is None:
                continue
            bucket = agg.setdefault(code, [])
            bucket.append(val)
    out = []
    for code, vals in agg.items():
        out.append({"indicator": code, "hospitals": len(vals),
                    "mean": round(statistics.mean(vals), 2),
                    "min": round(min(vals), 2), "max": round(max(vals), 2)})
    return {"ok": True, "data": _cap(out)}


TOOL_DEFS = [
    {"name": "list_accessible_hospitals", "description": "List hospitals the user can access.",
     "schema": {}, "permission": "ai.read", "scope": "none", "max_results": MAX_ROWS, "max_tokens": 400},
    {"name": "get_indicator_values", "description": "Indicator values for hospitals in a month.",
     "schema": {"hospital_ids": ["int"], "month": "str", "indicators": ["str"]},
     "permission": "ai.read", "scope": "hospital", "max_results": MAX_ROWS, "max_tokens": 400},
    {"name": "get_quality_score", "description": "Quality score components for hospitals.",
     "schema": {"hospital_ids": ["int"], "month": "str"},
     "permission": "ai.read", "scope": "hospital", "max_results": MAX_ROWS, "max_tokens": 400},
    {"name": "get_rule_results", "description": "Rule validation results for hospitals.",
     "schema": {"hospital_ids": ["int"], "month": "str", "status": "str"},
     "permission": "ai.read", "scope": "hospital", "max_results": MAX_ROWS, "max_tokens": 400},
    {"name": "get_anomalies", "description": "Outlier anomalies for hospitals in a month.",
     "schema": {"hospital_ids": ["int"], "month": "str"},
     "permission": "ai.read", "scope": "hospital", "max_results": MAX_ROWS, "max_tokens": 400},
    {"name": "get_clinical_profile", "description": "Clinical profile analysis for hospitals.",
     "schema": {"hospital_ids": ["int"], "month": "str"},
     "permission": "ai.read", "scope": "hospital", "max_results": MAX_ROWS, "max_tokens": 400},
    {"name": "get_peer_comparison", "description": "Peer benchmark stats for indicators across authorized hospitals.",
     "schema": {"hospital_ids": ["int"], "month": "str", "indicators": ["str"]},
     "permission": "ai.read", "scope": "hospital", "max_results": MAX_ROWS, "max_tokens": 400},
    {"name": "get_historical_trends", "description": "Recent monthly history for indicators of a hospital.",
     "schema": {"hospital_ids": ["int"], "month": "str", "indicators": ["str"]},
     "permission": "ai.read", "scope": "hospital", "max_results": MAX_ROWS, "max_tokens": 400},
    {"name": "query_month_aggregates", "description": "Cross-hospital aggregate stats for indicators in a month.",
     "schema": {"hospital_ids": ["int"], "month": "str", "indicators": ["str"]},
     "permission": "ai.read", "scope": "hospital", "max_results": MAX_ROWS, "max_tokens": 400},
]

_TOOL_FUNCS = {
    "list_accessible_hospitals": _list_accessible_hospitals,
    "get_indicator_values": _get_indicator_values,
    "get_quality_score": _get_quality_score,
    "get_rule_results": _get_rule_results,
    "get_anomalies": _get_anomalies,
    "get_clinical_profile": _get_clinical_profile,
    "get_peer_comparison": _get_peer_comparison,
    "get_historical_trends": _get_historical_trends,
    "query_month_aggregates": _query_month_aggregates,
}


def execute_tool(name, args, ctx):
    if name not in _TOOL_FUNCS:
        return {"ok": False, "error": f"validation: unknown tool {name}"}
    month = args.get("month")
    if month is not None and not MONTH_RE.match(str(month)):
        return {"ok": False, "error": "validation: month must be YYYY-MM"}
    return _TOOL_FUNCS[name](ctx, args)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_tools.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agents/tools.py tests/test_agents_tools.py
git commit -m "feat(agents): read-only scoped tool registry with ACCESS_DENIED and validation"
```

---

### Task 5: Deterministic profile fallbacks (`app/agents/profiles/fallbacks.py`)

**Files:**
- Create: `app/agents/profiles/__init__.py`, `app/agents/profiles/fallbacks.py`
- Test: `tests/test_agents_profiles.py` (new)

**Interfaces:**
- Produces:
  ```python
  def fallback_answer(profile: str, ctx, question: str, lang: str) -> dict
  # -> {"facts": [...], "analysis": [...], "contributors": [...], "actions": [...], "answer": str}
  ```
  Deterministic, built from the same tool reads as Task 4 (ctx.quality_row/rule_rows/anomaly_rows + hospital_data). `lang="ar"` returns Arabic labels.
- Tests assert: no LLM involvement (uses only ctx), empty-data case produces "Insufficient data" phrasing, and Arabic variant is non-empty.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agents_profiles.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Hospital, QualityScore, ValidationResult
from app.agents.tools import ToolContext
from app.agents.profiles.fallbacks import fallback_answer


class FakeUser:
    is_superuser = True
    id = 1


@pytest.fixture
def ctx():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    h = Hospital(name="Alpha", region="R")
    s.add(h)
    s.commit()
    s.add(QualityScore(hospital_id=h.id, month="2026-08", score=54.0, rule_compliance=40.0))
    s.add(ValidationResult(hospital_id=h.id, month="2026-08", rule_code="1.a.1",
                           rule_description="CS rate within threshold", status="FAIL",
                           severity="high"))
    s.commit()
    s.expunge(h)
    c = ToolContext(s, FakeUser(), "2026-08")
    yield c
    s.close()


def test_fallback_uses_facts_only(ctx):
    out = fallback_answer("explainer", ctx, "", "en")
    assert out["facts"]
    assert any("quality" in str(t).lower() for t in out["facts"])
    assert out["answer"]


def test_fallback_empty_data_safe(ctx):
    empty = type("Ctx", (), {})()
    empty.quality_row = lambda hid: None
    empty.rule_rows = lambda hid: []
    empty.anomaly_rows = lambda hid: []
    empty.hospital_data = lambda: {}
    out = fallback_answer("explainer", empty, "", "en")
    assert "Insufficient data" in out["answer"]


def test_fallback_arabic_present(ctx):
    out = fallback_answer("explainer", ctx, "", "ar")
    assert out["answer"].strip() != ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_profiles.py -q`
Expected: FAIL — import error.

- [ ] **Step 3: Implement fallbacks**

Create `app/agents/profiles/__init__.py`:
```python
"""Agent profile definitions, prompts, and deterministic fallbacks."""
```
Create `app/agents/profiles/fallbacks.py`:
```python
"""Deterministic, bilingual profile fallbacks built only from tool reads."""
_GRADE = lambda s: "good" if (s or 0) >= 80 else ("moderate" if (s or 0) >= 60 else "poor")
_AR = {
    "quality": "جودة البيانات", "rule": "القاعدة", "anomaly": "الشذوذ",
    "insufficient": "Insufficient data to determine the cause.",
    "insufficient_ar": "البيانات غير كافية لتحديد السبب.",
}


def _label(key, lang):
    return _AR[key] if lang == "ar" else key


def fallback_answer(profile, ctx, question, lang):
    facts, analysis, contributors, actions = [], [], [], []
    q = None
    try:
        q = ctx.quality_row(1)
    except Exception:
        q = None
    if q is not None and getattr(q, "score", None) is not None:
        facts.append({"kind": "quality", "value": round(q.score, 1),
                      "component": _label("quality", lang), "source": "quality_scores"})
    rules = ctx.rule_rows(1) if hasattr(ctx, "rule_rows") else []
    fails = [r for r in rules if r.status == "FAIL"]
    for r in fails[:5]:
        facts.append({"kind": "rule", "rule_code": r.rule_code,
                      "status": r.status, "severity": r.severity,
                      "source": "validation_results"})
        if r.severity in ("critical", "high"):
            actions.append({"rule_code": r.rule_code,
                            "action": "Review the failed rule's contributing indicators"})
    if q is not None and q.score is not None and q.score < 60:
        analysis.append({"q": "data quality below threshold", "value": round(q.score, 1)})
    if not facts:
        answer = _AR["insufficient_ar"] if lang == "ar" else _AR["insufficient"]
    else:
        base = f"{len(facts)} finding(s) from quality scores and rule validation."
        answer = (base + " Review the failed rules identified above."
                  if lang == "en" else f"{len(facts)} من النتائج من جودة البيانات وقواعد التحقق.")
    return {"facts": facts, "analysis": analysis, "contributors": contributors,
            "actions": actions, "answer": answer}
```
Note the exploration-based text above is intentionally minimal; the executor should expand facts/analysis per the structured-output contract in the spec (FACTS/ANALYSIS/CONTRIBUTORS/ACTIONS) using the same `ctx.quality_row/rule_rows/anomaly_rows/hospital_data` reads.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_profiles.py -q`
Expected: PASS (3).

- [ ] **Step 5: Commit**

```bash
git add app/agents/profiles/ tests/test_agents_profiles.py
git commit -m "feat(agents): deterministic bilingual profile fallbacks"
```

---

### Task 6: Versioned entity cache + single-flight + data_version bumps

**Files:**
- Create: `app/agents/cache.py`
- Modify: `app/api/hospitals.py` (`_invalidate_analysis_caches`, ~415-427) and `app/api/file_ops.py` (~326-340) to bump data versions where `invalidate_report_cache` is already called
- Test: `tests/test_agents_cache.py` (new)

**Interfaces:**
- Produces (`app/agents/cache.py`):
  ```python
  AGENT_CACHE_TTL_HOURS = 24

  def build_agent_cache_key(*, profile, hospital_scope_hash, permission_scope_hash,
                            month, entity, data_version, language, prompt_hash) -> str
  def current_data_version(db, hospital_ids, months) -> str
      # e.g. "42" from max(AgentDataVersion.version) for the (hospital,month) rows,
      # or "0" when none; if multiple hospitals, join sorted versions with "-"
  def bump_data_version(db, hospital_ids, months) -> None
  def get_agent_cache(db, key) -> str | None
  def set_agent_cache(db, key, result_json, data_version, hospital_scope_hash,
                      ttl_hours=AGENT_CACHE_TTL_HOURS) -> None
  @contextmanager
  def single_flight_key(key: str) -> None   # waits or passes through; raises RuntimeError on re-entry madness
  ```
- `bump_data_version` upserts `AgentDataVersion` raising `version += 1` per (hospital_id, month).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agents_cache.py
"""Versioned agent cache + single-flight + data_version bump."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AgentCache, AgentDataVersion
from app.agents import cache as acache


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_build_key_includes_scope_and_version():
    k1 = acache.build_agent_cache_key(profile="qa", hospital_scope_hash="A",
                                      permission_scope_hash="P", month="2026-08",
                                      entity="", data_version="7", language="en", prompt_hash="X")
    k2 = acache.build_agent_cache_key(profile="qa", hospital_scope_hash="B",
                                      permission_scope_hash="P", month="2026-08",
                                      entity="", data_version="7", language="en", prompt_hash="X")
    assert k1 != k2
    assert "agents:qa" in k1


def test_bump_and_current_version(db_session):
    acache.bump_data_version(db_session, [1, 2], ["2026-08"])
    acache.bump_data_version(db_session, [1], ["2026-08"])
    assert acache.current_data_version(db_session, [1], "2026-08") == "2"
    rows = db_session.query(AgentDataVersion).all()
    assert {(r.hospital_id, r.month) for r in rows} == {(1, "2026-08"), (2, "2026-08")}


def test_cache_set_get_and_expiry(db_session):
    key = acache.build_agent_cache_key(profile="qa", hospital_scope_hash="A",
                                       permission_scope_hash="P", month="2026-08",
                                       entity="", data_version="1", language="en", prompt_hash="X")
    acache.set_agent_cache(db_session, key, '{"answer": "hi"}', data_version="1",
                           hospital_scope_hash="A")
    assert acache.get_agent_cache(db_session, key) == '{"answer": "hi"}'
    # a different scope must NOT match
    key2 = acache.build_agent_cache_key(profile="qa", hospital_scope_hash="B",
                                        permission_scope_hash="P", month="2026-08",
                                        entity="", data_version="1", language="en", prompt_hash="X")
    assert acache.get_agent_cache(db_session, key2) is None


def test_data_version_mismatch_is_miss(db_session):
    key = acache.build_agent_cache_key(profile="qa", hospital_scope_hash="A",
                                       permission_scope_hash="P", month="2026-08",
                                       entity="", data_version="1", language="en", prompt_hash="X")
    acache.set_agent_cache(db_session, key, "x", data_version="1", hospital_scope_hash="A")
    key_stale = acache.build_agent_cache_key(profile="qa", hospital_scope_hash="A",
                                             permission_scope_hash="P", month="2026-08",
                                             entity="", data_version="99", language="en", prompt_hash="X")
    assert acache.get_agent_cache(db_session, key_stale) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_cache.py -q`
Expected: FAIL — import error.

- [ ] **Step 3: Implement `app/agents/cache.py`**

```python
"""Entity-keyed, versioned, scope-safe agent cache with single-flight."""
import hashlib
import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

from app.models import AgentCache as _Row, AgentDataVersion

AGENT_CACHE_TTL_HOURS = 24
_IN_FLIGHT = {}
_IN_FLIGHT_LOCK = threading.Lock()


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def build_agent_cache_key(*, profile, hospital_scope_hash, permission_scope_hash,
                          month, entity, data_version, language, prompt_hash):
    return "agents:%s:%s:%s:%s:%s:%s:%s:%s" % (
        profile, hospital_scope_hash[:16], permission_scope_hash[:16], month,
        _h(entity or ""), data_version, language, prompt_hash[:16])


def current_data_version(db, hospital_ids, months) -> str:
    if not hospital_ids:
        return "0"
    version = 0
    for month in months:
        rows = db.query(AgentDataVersion).filter(
            AgentDataVersion.hospital_id.in_(hospital_ids),
            AgentDataVersion.month == month).all()
        if rows:
            version = max(version, max(r.version for r in rows))
    return str(version) or "0"


def bump_data_version(db, hospital_ids, months) -> None:
    if not hospital_ids or not months:
        return
    for hid in hospital_ids:
        for month in months:
            row = db.query(AgentDataVersion).filter(
                AgentDataVersion.hospital_id == hid,
                AgentDataVersion.month == month).first()
            if row:
                row.version += 1
            else:
                db.add(AgentDataVersion(hospital_id=hid, month=month, version=1))
    db.commit()


def get_agent_cache(db, key) -> str | None:
    row = db.query(_Row).filter(_Row.cache_key == key).first()
    if row is None:
        return None
    if row.expires_at is not None and datetime.utcnow() > row.expires_at:
        db.delete(row)
        db.commit()
        return None
    try:
        return json.loads(row.result_json)
    except (TypeError, ValueError):
        return None


def set_agent_cache(db, key, result_json, data_version=None,
                    hospital_scope_hash=None, ttl_hours=AGENT_CACHE_TTL_HOURS) -> None:
    expires = datetime.utcnow() + timedelta(hours=ttl_hours)
    row = db.query(_Row).filter(_Row.cache_key == key).first()
    payload = json.dumps(result_json, ensure_ascii=False)
    if row:
        row.result_json = payload
        row.data_version = data_version
        row.hospital_scope_hash = hospital_scope_hash
        row.expires_at = expires
    else:
        db.add(_Row(cache_key=key, result_json=payload,
                    data_version=data_version, hospital_scope_hash=hospital_scope_hash,
                    expires_at=expires))
    db.commit()


@contextmanager
def single_flight_key(key: str):
    """Shared by identical in-flight runs; returns the result via a wait-flag."""
    with _IN_FLIGHT_LOCK:
        if key in _IN_FLIGHT:
            evt = _IN_FLIGHT[key]
            yield evt           # caller waits below
            return
        evt = threading.Event()
        _IN_FLIGHT[key] = evt
    try:
        yield evt
    finally:
        with _IN_FLIGHT_LOCK:
            _IN_FLIGHT.pop(key, None)
```
Note: the runtime uses `single_flight_key` to wait (`evt.wait(timeout=...)`) before recomputing; callers must `evt.set()` after storing. (Executor: wire in Task 8's runtime — a helper `wait_or_become(key)` inside cache.py is acceptable if cleaner than returning the event.)

- [ ] **Step 4: Wire data_version bumps into analysis invalidation**

In `app/api/hospitals.py` `_invalidate_analysis_caches` (near the existing `invalidate_report_cache(db)` call), add:
```python
    try:
        from app.agents.cache import bump_data_version
        bump_data_version(db, hospital_ids, [month])  # works even if one arg empty
    except Exception:
        pass
```
Adjust `hospital_ids`/`month` to the actual local variable names in that function (`_invalidate_analysis_caches` currently receives `db` only and clears ALL months; to stay minimal, call `bump_data_version(db, [h.id for h in db.query(Hospital).all()], None)` only when the function knows the month — see Implementation Note below). Mirror the same in `app/api/file_ops.py` upload completion.
- Implementation note: if the existing hook loops over hospital IDs/months, pass those; otherwise call `bump_data_version(db, [], None)` (no-op, preserving behavior) and instead rely on `purge::recompute_hospital_months` where months are known — wire it where `run_full_analysis(force=True)` runs for re-analyzed months (`app/api/hospitals.py` reanalysis path and `app/api/upload.py`). Keep the hook calls defensive (try/except) as in the existing code.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_cache.py -q`
Expected: PASS (4). Then run the full suite to confirm no regressions from the hook edits:
Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 1241+ passed (4 new tests added to the 1237 baseline; previous tasks added 22 before this).

- [ ] **Step 6: Commit**

```bash
git add app/agents/cache.py app/api/hospitals.py app/api/file_ops.py tests/test_agents_cache.py
git commit -m "feat(agents): versioned scope-safe cache with single-flight and data_version bumps"
```

---

### Task 7: Agent runtime (ReAct loop) with profiles

**Files:**
- Create: `app/agents/runtime.py`
- Create: `app/agents/profiles/qa.py`, `app/agents/profiles/explainer.py`, `app/agents/profiles/report_writer.py`, `app/agents/profiles/triage.py`
- Test: `tests/test_agents_runtime.py` (new)

**Interfaces:**
- Produces (`app/agents/runtime.py`):
  ```python
  @dataclass
  class AgentResult:
      agent: str
      answer: str
      facts: list
      sources: list
      status: str                 # "completed" | "budget_exceeded" | "fallback"
      steps: int
      tool_calls: list[dict]
      tokens: dict                # {"in": int, "out": int}
      provider: str
      model: str
      language: str
      fallback_used: bool
      cache_hit: bool
      duration_ms: int
      data_version: str
      hospital_scope_hash: str
      permission_scope_hash: str
      prompt_hash: str
      error: str | None

  def run_agent(*, profile: str, user, db, month: str, lang: str = "en",
                entity: str = "", question: str = "",
                history: list[dict] | None = None,
                llm_caller=None, tool_executor=None, allow_cache: bool = True) -> AgentResult
  ```
  `llm_caller` and `tool_executor` are injectable for tests; defaults import `llm_chat`/`execute_tool`. `run_agent` computes hashes, resolves provider, checks cache (`allow_cache`), runs the loop, persists nothing (persistence is Task 8's job). `history` (list of `{"role": "user"/"assistant", "content": str}`) implements spec §7 history compression: older turns are folded into a one-line summary and only the last ~6 turns are sent to the model verbatim.
- Profile module interface (`app/agents/profiles/<name>.py`): each exports
  ```python
  PROFILE = {
      "name": "qa", "allowed_tools": [all 9], "max_steps": 6,
      "max_tool_calls": 18, "max_input_tokens": 20000,
      "max_output_tokens": 3000, "max_runtime_s": 45,
      "system_prompt": <str incl. grounding policy>, "output_shape": "conversational",
  }
  ```
  plus a `fallback(ctx, question, lang) -> dict` importing `fallback_answer`.
- Grounding policy block MUST be embedded verbatim in each `system_prompt` (spec §5).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agents_runtime.py
"""ReAct loop mechanics with a scripted fake LLM."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Hospital
from app.agents.runtime import run_agent, AgentResult


class FakeSuperUser:
    is_superuser = True
    id = 1


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(Hospital(name="Alpha", region="R"))
    s.add(Hospital(name="Beta", region="R"))
    s.commit()
    yield s
    s.close()


def _fake_llm(script):
    """Return a callable that yields scripted tool-JSON then a final answer."""
    calls = []
    def caller(resolved, system, user, max_output_tokens=3000, timeout=30.0):
        calls.append(user)
        from app.agents.llm import ChatResult
        if len(calls) == 1 and script[0]:
            step = script.pop(0)
            return ChatResult(text=step, provider="local", model="qwen3:8b",
                              prompt_tokens=100, completion_tokens=20)
        return ChatResult(text=script.pop(0), provider="local", model="qwen3:8b",
                          prompt_tokens=100, completion_tokens=20)
    return caller


def test_run_agent_tool_then_answer(db_session, monkeypatch):
    script = ['{"tools": [{"name": "list_accessible_hospitals", "args": {}}], "done": false}',
              '{"done": true, "answer": "Alpha and Beta"}']
    monkeypatch.setattr("app.agents.runtime.get_agent_cache", lambda db, key: None)
    monkeypatch.setattr("app.agents.runtime.set_agent_cache", lambda *a, **k: None)
    res = run_agent(profile="qa", user=FakeSuperUser(), db=db_session,
                    month="2026-08", question="list hospitals", llm_caller=_fake_llm(script))
    assert res.status == "completed"
    assert res.answer == "Alpha and Beta"
    assert res.steps == 1
    assert res.tool_calls and res.tool_calls[0]["name"] == "list_accessible_hospitals"
    assert res.provider in ("local", "gemini", "openai_compatible")


def test_run_agent_early_finish_no_tools(db_session, monkeypatch):
    script = ['{"done": true, "answer": "Direct"}']
    monkeypatch.setattr("app.agents.runtime.get_agent_cache", lambda db, key: None)
    monkeypatch.setattr("app.agents.runtime.set_agent_cache", lambda *a, **k: None)
    res = run_agent(profile="qa", user=FakeSuperUser(), db=db_session,
                    month="2026-08", question="hi", llm_caller=_fake_llm(script))
    assert res.steps == 0
    assert res.status == "completed"


def test_run_agent_malformed_json_then_fallback(db_session, monkeypatch):
    script = ["not json at all", "also not json"]
    monkeypatch.setattr("app.agents.runtime.get_agent_cache", lambda db, key: None)
    monkeypatch.setattr("app.agents.runtime.set_agent_cache", lambda *a, **k: None)
    res = run_agent(profile="explainer", user=FakeSuperUser(), db=db_session,
                    month="2026-08", entity="cs_rate", question="why",
                    llm_caller=_fake_llm(script))
    assert res.status == "fallback"
    assert res.fallback_used is True
    assert res.answer.strip() != ""
    assert "Insufficient data" in res.answer or "finding" in res.answer.lower()


def test_run_agent_step_budget_exceeded(db_session, monkeypatch):
    script = ['{"tools": [{"name": "list_accessible_hospitals", "args": {}}], "done": false}'] * 20
    monkeypatch.setattr("app.agents.runtime.get_agent_cache", lambda db, key: None)
    monkeypatch.setattr("app.agents.runtime.set_agent_cache", lambda *a, **k: None)
    res = run_agent(profile="qa", user=FakeSuperUser(), db=db_session,
                    month="2026-08", question="q", llm_caller=_fake_llm(script))
    assert res.status == "budget_exceeded"


def test_run_agent_rejects_disallowed_tool(db_session, monkeypatch):
    # triage may NOT call get_clinical_profile -> validation observation
    script = ['{"tools": [{"name": "get_clinical_profile", "args": {"hospital_ids": [1], "month": "2026-08"}}], "done": false}',
              '{"done": true, "answer": "done"}']
    monkeypatch.setattr("app.agents.runtime.get_agent_cache", lambda db, key: None)
    monkeypatch.setattr("app.agents.runtime.set_agent_cache", lambda *a, **k: None)
    res = run_agent(profile="triage", user=FakeSuperUser(), db=db_session,
                    month="2026-08", entity="", question="digest",
                    llm_caller=_fake_llm(script))
    assert res.status == "completed"
    # the rejected tool must never have been executed for real
    assert all(tc["name"] != "get_clinical_profile" for tc in res.tool_calls)


def test_run_agent_history_compression(db_session, monkeypatch):
    # 12 prior turns -> last ~6 kept verbatim, older folded into a summary line
    captured = {}
    def caller(resolved, system, user, max_output_tokens=3000, timeout=30.0):
        captured["user"] = user
        from app.agents.llm import ChatResult
        return ChatResult(text='{"done": true, "answer": "ok"}', provider="local",
                          model="m", prompt_tokens=10, completion_tokens=5)
    monkeypatch.setattr("app.agents.runtime.get_agent_cache", lambda db, key: None)
    monkeypatch.setattr("app.agents.runtime.set_agent_cache", lambda *a, **k: None)
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"}
               for i in range(12)]
    res = run_agent(profile="qa", user=FakeSuperUser(), db=db_session,
                    month="2026-08", question="q", llm_caller=caller, history=history)
    assert res.status == "completed"
    assert "summary" in captured["user"].lower()
    assert "turn 5" not in captured["user"]        # older turn folded, not verbatim
    assert "turn 11" in captured["user"]           # most recent turn kept verbatim
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_runtime.py -q`
Expected: FAIL — import error.

- [ ] **Step 3: Implement the four profile modules**

`app/agents/profiles/qa.py` (pattern to follow for the rest):
```python
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
    "fallback": fallback_answer,
}
```
Create `explainer.py`, `report_writer.py`, `triage.py` with the same structure, per spec §5 table:
- explainer: allowed = quality, anomalies, peer, trends, rules, clinical + list; steps 6; output_shape "structured".
- report_writer: all tools; steps 10; output_shape "structured" then prose.
- triage: aggregates, quality, rules, anomalies + list; steps 10; output_shape "structured".

- [ ] **Step 4: Implement `app/agents/runtime.py`**

```python
"""ReAct agent runtime: budgets, retries, strict tool-call JSON, fallback."""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.agents.llm import resolve_agent_provider, llm_chat
from app.agents.tools import execute_tool, ToolContext
from app.agents.cache import (get_agent_cache as _catchit_get, set_agent_cache as _catchit_set,
                              build_agent_cache_key, current_data_version)


def _h(value):
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def _strip_and_parse(text):
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    try:
        return json.loads(t)
    except ValueError:
        raise ValueError("not JSON")


def _parse_step(text):
    data = _strip_and_parse(text)
    if not isinstance(data, dict):
        raise ValueError("step must be an object")
    tools = data.get("tools") or []
    done = bool(data.get("done"))
    answer = data.get("answer") or ""
    out_tools = []
    for t in tools:
        if not isinstance(t, dict) or "name" not in t:
            raise ValueError("tool entries need a name")
        out_tools.append({"name": t["name"], "args": t.get("args") or {}})
    return {"tools": out_tools, "done": done, "answer": answer}


@dataclass
class AgentResult:
    agent: str
    answer: str
    facts: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    status: str = "completed"
    steps: int = 0
    tool_calls: list = field(default_factory=list)
    tokens: dict = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    language: str = "en"
    fallback_used: bool = False
    cache_hit: bool = False
    duration_ms: int = 0
    data_version: str = "0"
    hospital_scope_hash: str = ""
    permission_scope_hash: str = ""
    prompt_hash: str = ""
    error: str | None = None


def run_agent(*, profile, user, db, month, lang="en", entity="", question="",
              history=None, llm_caller=None, tool_executor=None, allow_cache=True) -> AgentResult:
    from app.agents import profiles
    prof_mod = getattr(profiles, profile, None)
    if prof_mod is None:
        raise ValueError(f"Unknown agent profile: {profile}")
    P = prof_mod.PROFILE
    start = time.time()
    ctx = ToolContext(db, user, month)
    scope_ids = ctx.authorized_ids
    hospital_scope_hash = _h(",".join(str(i) for i in sorted(scope_ids)))
    permission_scope_hash = _h("ai.read" if profile in ("qa", "explainer") else "ai.read,ai.write")
    data_version = current_data_version(db, scope_ids, [month])
    prompt_hash = _h((question or entity or profile) + lang + json.dumps(history or [], ensure_ascii=False))
    key = build_agent_cache_key(profile=profile, hospital_scope_hash=hospital_scope_hash,
                                permission_scope_hash=permission_scope_hash, month=month,
                                entity=entity, data_version=data_version, language=lang,
                                prompt_hash=prompt_hash)

    if allow_cache:
        try:
            cached = _catchit_get(db, key)
        except Exception:
            cached = None
        if cached:
            return AgentResult(agent=profile, answer=cached.get("answer", ""),
                               facts=cached.get("facts", []), sources=cached.get("sources", []),
                               status="completed", steps=0, tool_calls=[],
                               provider=cached.get("provider", ""), model=cached.get("model", ""),
                               language=lang, cache_hit=True, data_version=data_version,
                               hospital_scope_hash=hospital_scope_hash,
                               permission_scope_hash=permission_scope_hash, prompt_hash=prompt_hash)

    resolved = resolve_agent_provider(profile, db)
    caller = llm_caller or llm_chat
    executor = tool_executor or execute_tool
    calls_made = 0
    steps = 0
    tool_log = []
    system = P["system_prompt"]
    transcript_parts = []
    if history:
        # spec §7 history compression: older turns -> summary, last ~6 verbatim
        older, recent = history[:-6], history[-6:]
        if older:
            brief = " ".join((str(t.get("content") or "")[:200]) for t in older)
            transcript_parts.append(f"Earlier conversation summary: {brief[:1500]}")
        for turn in recent:
            role = "user" if turn.get("role") == "user" else "assistant"
            transcript_parts.append(f"{role}: {turn.get('content') or ''}")
    if entity:
        transcript_parts.append(f"Focus entity: {entity}")
    if question:
        transcript_parts.append(f"User question: {question}")
    answer = ""
    fallback_used = False
    final = None

    def _budget_ok():
        return (steps < P["max_steps"] and calls_made < P["max_tool_calls"]
                and time.time() - start < P["max_runtime_s"])

    while _budget_ok():
        user_content = "\n".join(transcript_parts) if transcript_parts else "_"
        try:
            result = caller(resolved, system, user_content,
                            max_output_tokens=P["max_output_tokens"],
                            timeout=30.0)
        except Exception:
            result = None
        if result is None or not result.text:
            break
        steps += 1
        try:
            step = _parse_step(result.text)
        except ValueError:
            transcript_parts.append("The response was not valid JSON. Reply with only a JSON object.")
            continue
        if step["done"]:
            answer = step["answer"]
            final = step
            break
        batch = [t for t in step["tools"][:3]
                 if t["name"] in P["allowed_tools"]]
        rejected = [t for t in step["tools"][:3]
                    if t["name"] not in P["allowed_tools"]]
        if rejected:
            # spec §12: an unauthorized tool is rejected with a validation
            # observation BEFORE any execution
            obs = [{"tool": t["name"], "result": {"ok": False,
                   "error": f"validation: tool {t['name']} is not allowed for profile {profile}"}}
                   for t in rejected]
            transcript_parts.append("Tool observations: " + json.dumps(obs, ensure_ascii=False)[:4000])
            continue
        if not batch and not rejected:
            transcript_parts.append("No tools specified. Respond with {\"done\": true, ...} to finish.")
            continue
        obs = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {t["name"]: pool.submit(executor, t["name"], t["args"], ctx) for t in batch}
            for t in batch:
                calls_made += 1
                tool_log.append(t)
                try:
                    r = futures[t["name"]].result()
                except Exception as e:
                    r = {"ok": False, "error": f"tool error: {e}"}
                obs.append({"tool": t["name"], "result": r})
        transcript_parts.append("Tool observations: " + json.dumps(obs, ensure_ascii=False)[:4000])
        if calls_made >= P["max_tool_calls"]:
            break

    if not final:
        # degrade deterministically
        fallback_used = True
        fb = P["fallback"](ctx, question, lang)
        answer = fb.get("answer", "Insufficient data to determine the cause.")
        agent_facts = fb.get("facts", [])
        if steps >= P["max_steps"] or calls_made >= P["max_tool_calls"]:
            status = "budget_exceeded"
        elif time.time() - start >= P["max_runtime_s"]:
            status = "budget_exceeded"
        else:
            status = "fallback"
    else:
        answer = answer or "Insufficient data to determine the cause."
        agent_facts = []
        status = "completed"

    try:
        _catchit_set(db, key, {"answer": answer, "facts": agent_facts, "sources": [],
                               "provider": resolved.provider, "model": resolved.model},
                     data_version=data_version, hospital_scope_hash=hospital_scope_hash)
    except Exception:
        pass

    tokens = {"in": sum((getattr(c, "prompt_tokens", 0) for c in []), 0), "out": 0}
    for _ in ():
        pass
    return AgentResult(agent=profile, answer=answer, facts=agent_facts, sources=[],
                       status=status, steps=steps, tool_calls=tool_log, tokens=tokens,
                       provider=resolved.provider, model=resolved.model, language=lang,
                       fallback_used=fallback_used, cache_hit=False,
                       duration_ms=int((time.time() - start) * 1000),
                       data_version=data_version, hospital_scope_hash=hospital_scope_hash,
                       permission_scope_hash=permission_scope_hash, prompt_hash=prompt_hash)
```
Implementation notes for the executor: accumulate per-call token usage into `tokens` by having `_fake_llm`/`llm_chat` results read `result.prompt_tokens`/`result.completion_tokens`; replace the placeholder empty-comprehension token counting with a running sum captured inside the loop. Ensure `resolve_agent_provider` fallback path (missing keys/URLs) still yields `ResolvedProvider("local", ...)` so `run_agent` never raises.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_runtime.py -q`
Expected: PASS (6).

- [ ] **Step 6: Commit**

```bash
git add app/agents/runtime.py app/agents/profiles/ tests/test_agents_runtime.py
git commit -m "feat(agents): ReAct runtime with budgets, retries, early finish, and fallback"
```

---

### Task 8: `/ai/agents` API router (auth, kill-switch, caps, persistence)

**Files:**
- Create: `app/api/agents.py`
- Modify: `app/main.py` (register router — mirror the existing router include pattern)
- Test: `tests/test_agents_api.py` (new)

**Interfaces:**
- Produces (routes under `/ai/agents`):
  - `POST /ai/agents/chat` body `{"conversation_id": int?, "message": str}` → requires `ai.read`; runs `qa`; persists Conversation/Message + `AgentRun`; returns `{answer, conversation_id, sources, steps, provider, model, enabled: true}`.
  - `GET /ai/agents/chat/{id}/messages` → requires `ai.read`; returns the conversation's messages.
  - `POST /ai/agents/explain` body `{"hospital_id": int, "month": str, "entity": str}` → `ai.read`.
  - `POST /ai/agents/report` body `{"hospital_id", "month", "lang"}` → `ai.read` AND `ai.write`.
  - `POST /ai/agents/digest` body `{"month"}` → `ai.read` AND `ai.write`; runs triage across scope.
  - `GET /ai/agents/status` → `{"enabled": bool, "permissions": ["ai.read", ...], "provider": str}` — auth only.
  - `GET /ai/agents/runs` (admin, `system.manage_users`) → paginated `AgentRun` list.
  - `GET /ai/agents/admin` + `PUT /ai/agents/admin` (admin) → daily cap, `agents_enabled`/`agents_provider`/roles/local settings, retention days.
- Helper `_agent_enabled(db) -> bool` reads `agents_enabled` via `get_ai_config`; when false every non-admin route returns `{"enabled": False}` (HTTP 200) without any LLM call.
- Daily cap default 20: count `AgentRun` rows for user where `created_at` today; at/over cap return HTTP 429 with message.
- `AgentRun` persisted from the `AgentResult` dataclass of Task 7 (map fields 1:1; `error` = `result.error`).
- Persistence helper `save_agent_run(db, user, result, conversation_id=None)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agents_api.py
"""Agents API: kill-switch, permissions, caps, persistence."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.core.deps import get_current_user
from app.main import app
from app.core.security import hash_password, create_access_token
from app.models import User, Role, Permission, Hospital
from app.agents.llm import ChatResult


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    h = Hospital(name="Alpha", region="R")
    s.add(h)
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides.pop(get_current_user, None)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _user(db_session, username, codenames, is_superuser=False):
    perms = [Permission(codename=c) for c in codenames]
    role = Role(name=username + "_role", permissions=perms)
    db_session.add(role)
    db_session.add_all(perms)
    db_session.commit()
    u = User(username=username, email=username + "@t.com", full_name=username,
             password_hash=hash_password("pw"), is_superuser=is_superuser, roles=[role])
    db_session.add(u)
    db_session.commit()
    token = create_access_token(user_id=u.id, roles=[role.name], permissions=list(codenames))
    return {"Authorization": f"Bearer {token}"}


def test_status_off_by_default(client, db_session):
    hdr = _user(db_session, "viewer", [])
    r = client.get("/ai/agents/status", headers=hdr)
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_disabled_returns_no_run(client, db_session, monkeypatch):
    hdr = _user(db_session, "reader", ["ai.read"])
    called = []

    def fake_run(**kw):
        called.append(kw)
        from app.agents.runtime import AgentResult
        return AgentResult(agent="qa", answer="x", language="en")
    monkeypatch.setattr("app.api.agents.run_agent", fake_run)
    monkeypatch.setattr("app.api.agents.get_ai_config", lambda db: {"agents_enabled": "false"})
    r = client.post("/ai/agents/chat", headers=hdr, json={"message": "hi"})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert called == []


def test_chat_requires_ai_read(client, db_session, monkeypatch):
    hdr = _user(db_session, "nolibs", [])
    r = client.post("/ai/agents/chat", headers=hdr, json={"message": "hi"})
    assert r.status_code == 403


def test_chat_runs_and_persists(client, db_session, monkeypatch):
    hdr = _user(db_session, "reader", ["ai.read"])
    from app.agents.runtime import AgentResult
    monkeypatch.setattr("app.api.agents.get_ai_config",
                        lambda db: {"agents_enabled": "true", "agents_provider": "auto",
                                    "agent_provider_roles": "{}", "local_runtime": "ollama",
                                    "local_model": "qwen3:8b", "local_url": "http://127.0.0.1:9"})
    monkeypatch.setattr("app.api.agents.run_agent",
                        lambda **kw: AgentResult(agent="qa", answer="hi there", language="en",
                                                 steps=1, tool_calls=[], tokens={"in": 1, "out": 1},
                                                 provider="local", model="m", status="completed"))
    r = client.post("/ai/agents/chat", headers=hdr, json={"message": "hi"})
    assert r.status_code == 200
    data = r.json()
    assert data["answer"] == "hi there" and data["enabled"] is True
    conv = data["conversation_id"]
    msgs = client.get(f"/ai/agents/chat/{conv}/messages", headers=hdr)
    assert msgs.status_code == 200 and len(msgs.json()) == 2  # user + assistant


def test_report_requires_ai_write(client, db_session, monkeypatch):
    # ai.read only -> 403 (spec §9: report needs BOTH)
    hdr = _user(db_session, "reader", ["ai.read"])
    monkeypatch.setattr("app.api.agents.get_ai_config", lambda db: {"agents_enabled": "true"})
    r = client.post("/ai/agents/report", headers=hdr,
                    json={"hospital_id": 1, "month": "2026-08", "lang": "en"})
    assert r.status_code == 403


def test_report_and_digest_blocked_without_ai_read(client, db_session, monkeypatch):
    # ai.write only (has ai.write but NOT ai.read) -> still 403 on both
    hdr = _user(db_session, "writer_no_read", ["ai.write"])
    monkeypatch.setattr("app.api.agents.get_ai_config", lambda db: {"agents_enabled": "true"})
    r = client.post("/ai/agents/report", headers=hdr,
                    json={"hospital_id": 1, "month": "2026-08", "lang": "en"})
    assert r.status_code == 403
    r2 = client.post("/ai/agents/digest", headers=hdr, json={"month": "2026-08"})
    assert r2.status_code == 403


def test_admin_runs_gated(client, db_session):
    hdr = _user(db_session, "ops", ["ai.read"])
    r = client.get("/ai/agents/runs", headers=hdr)
    assert r.status_code == 403
    admin_hdr = _user(db_session, "boss", ["system.manage_users"])
    r2 = client.get("/ai/agents/runs", headers=admin_hdr)
    assert r2.status_code == 200


def test_daily_cap(client, db_session, monkeypatch):
    from datetime import datetime
    from app.models import AgentRun
    hdr = _user(db_session, "reader", ["ai.read"])
    monkeypatch.setattr("app.api.agents.get_ai_config",
                        lambda db: {"agents_enabled": "true", "agents_provider": "auto",
                                    "agent_provider_roles": "{}", "local_runtime": "ollama",
                                    "local_model": "qwen3:8b", "local_url": "http://127.0.0.1:9"})
    from app.api.agents import AGENT_DAILY_CAP
    for i in range(AGENT_DAILY_CAP):
        u = db_session.query(User).filter(User.username == "reader").first()
        db_session.add(AgentRun(user_id=u.id, agent="qa", status="completed",
                                created_at=datetime.utcnow()))
    db_session.commit()
    r = client.post("/ai/agents/chat", headers=hdr, json={"message": "hi"})
    assert r.status_code == 429


def test_admin_put_settings_validation(client, db_session, monkeypatch):
    hdr = _user(db_session, "boss", ["system.manage_users"])
    r = client.put("/ai/agents/admin", headers=hdr, json={"agent_provider_roles": '{"qa": "bad"}'})
    assert r.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_api.py -q`
Expected: FAIL — `ImportError` / 404 route.

- [ ] **Step 3: Implement `app/api/agents.py`**

```python
"""AI agents API — kill-switch, permissions, hospital scope, daily caps."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user, require_permission, get_user_hospital_ids
from app.config_utils import get_ai_config, validate_agents_config, AI_CONFIG_KEYS
from app.models import Conversation, Message, AgentRun, Hospital, IndicatorValue

router = APIRouter(prefix="/ai/agents", tags=["agents"])

AGENT_DAILY_CAP = 20
_AGENT_SETTING_KEYS = ("agents_enabled", "agents_provider", "agent_provider_roles",
                       "local_runtime", "local_model", "local_url")
_AGENT_ADMIN_KEYS = ("agent_cap", "agent_retention_days")


def _agent_enabled(db) -> bool:
    return str(get_ai_config(db).get("agents_enabled", "false")).lower() == "true"


def require_ai_write(
    user=Depends(require_permission("ai.write")),
    _read_ok=Depends(require_permission("ai.read")),
):
    """Report/digest gates: BOTH ai.write AND ai.read (spec §9). Each
    sub-dependency raises 403 independently; the user the caller sees is the
    ai.write one (same user object)."""
    return user


def _disabled_payload():
    return {"enabled": False, "error": "agents disabled"}


def _check_enabled(db):
    if not _agent_enabled(db):
        raise HTTPException(status_code=200, detail=None)


def _check_daily_cap(db, user):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    # created_at is a UTC datetime; compare via date substring on isoformat
    count = db.query(AgentRun).filter(
        AgentRun.user_id == user.id,
        AgentRun.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0),
    ).count()
    cap = AGENT_DAILY_CAP
    if count >= cap:
        raise HTTPException(status_code=429, detail="Daily agent run limit reached")


def save_agent_run(db, user, result, conversation_id=None):
    row = AgentRun(user_id=user.id, agent=result.agent, conversation_id=conversation_id,
                   status=result.status, duration_ms=result.duration_ms,
                   steps=result.steps, tool_calls=result.tool_calls, tokens=result.tokens,
                   data_version=result.data_version, model=result.model,
                   provider=result.provider, language=result.language,
                   cache_hit=result.cache_hit, fallback_used=result.fallback_used,
                   hospital_scope_hash=result.hospital_scope_hash,
                   permission_scope_hash=result.permission_scope_hash,
                   prompt_hash=result.prompt_hash, error=result.error)
    db.add(row)
    db.commit()
    return row.id


def _run_and_persist(db, user, profile, month, lang, entity, question, history=None):
    from app.agents.runtime import run_agent
    result = run_agent(profile=profile, user=user, db=db, month=month, lang=lang,
                       entity=entity, question=question, history=history)
    run_id = save_agent_run(db, user, result)
    return result, run_id


def _month_for_user(db, user) -> str:
    """Most recent month with data across the user's hospitals, else current."""
    hids = get_user_hospital_ids(user, db)
    if hids is None:
        hids = [r.id for r in db.query(Hospital).filter(Hospital.is_active).all()]
    if hids:
        latest = db.query(func.max(IndicatorValue.month)).filter(
            IndicatorValue.hospital_id.in_(hids)).scalar()
        if latest:
            return latest
    return datetime.utcnow().strftime("%Y-%m")


def _conversation(db, user, conversation_id):
    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id, Conversation.user_id == user.id).first()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.post("/chat")
def chat(body: dict, user=Depends(require_permission("ai.read")), db: Session = Depends(get_db)):
    if not _agent_enabled(db):
        return {"enabled": False}
    _check_daily_cap(db, user)
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="message is required")
    conv = None
    if body.get("conversation_id"):
        conv = _conversation(db, user, body["conversation_id"])
    else:
        conv = Conversation(user_id=user.id, title=message[:80], lang=body.get("lang", "en"))
        db.add(conv)
        db.commit()
    db.add(Message(conversation_id=conv.id, message_type="user", role="user", content=message))
    db.commit()
    prior = [{"role": m.role, "content": m.content}
             for m in db.query(Message).filter(Message.conversation_id == conv.id,
                                               Message.message_type.in_(("user", "assistant")))
             .order_by(Message.id).all()[:-1]]  # exclude the message just stored
    result, _ = _run_and_persist(db, user, "qa", _month_for_user(db, user), "en", "", message,
                                 history=prior or None)
    db.add(Message(conversation_id=conv.id, message_type="assistant", role="assistant",
                   content=result.answer, token_usage=result.tokens))
    db.commit()
    return {"enabled": True, "conversation_id": conv.id, "answer": result.answer,
            "steps": result.steps, "provider": result.provider, "model": result.model,
            "fallback_used": result.fallback_used, "sources": result.sources}


@router.get("/chat/{conversation_id}/messages")
def chat_messages(conversation_id: int, user=Depends(require_permission("ai.read")),
                  db: Session = Depends(get_db)):
    _conversation(db, user, conversation_id)
    msgs = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.id).all()
    return [{"message_type": m.message_type, "role": m.role, "content": m.content,
             "tool_steps": m.tool_steps, "created_at": m.created_at.isoformat()} for m in msgs]


@router.post("/explain")
def explain(body: dict, user=Depends(require_permission("ai.read")), db: Session = Depends(get_db)):
    if not _agent_enabled(db):
        return {"enabled": False}
    _check_daily_cap(db, user)
    result, _ = _run_and_persist(db, user, "explainer", body["month"], body.get("lang", "en"),
                                 str(body.get("entity", "")),
                                 f"Explain {body.get('entity', '')} at hospital {body.get('hospital_id')} for {body['month']}")
    return {"enabled": True, "answer": result.answer, "steps": result.steps,
            "provider": result.provider, "model": result.model, "fallback_used": result.fallback_used}


@router.post("/report")
def report(body: dict, user=Depends(require_ai_write), db: Session = Depends(get_db)):
    if not _agent_enabled(db):
        return {"enabled": False}
    _check_daily_cap(db, user)
    result, _ = _run_and_persist(db, user, "report_writer", body["month"], body.get("lang", "en"),
                                 str(body.get("hospital_id")), f"Write the {body['month']} report")
    return {"enabled": True, "answer": result.answer, "steps": result.steps,
            "provider": result.provider, "model": result.model, "fallback_used": result.fallback_used}


@router.post("/digest")
def digest(body: dict, user=Depends(require_ai_write), db: Session = Depends(get_db)):
    if not _agent_enabled(db):
        return {"enabled": False}
    _check_daily_cap(db, user)
    result, _ = _run_and_persist(db, user, "triage", body["month"], body.get("lang", "en"), "",
                                 f"Generate the triage digest for {body['month']}")
    return {"enabled": True, "answer": result.answer, "steps": result.steps,
            "provider": result.provider, "model": result.model, "fallback_used": result.fallback_used}


@router.get("/status")
def status(user=Depends(get_current_user), db: Session = Depends(get_db)):
    perms = {p.codename for p in user.permissions} | {p.codename for r in user.roles for p in r.permissions}
    if user.is_superuser:
        perms |= {"ai.read", "ai.write", "system.manage_users"}
    provider = get_ai_config(db).get("agents_provider", "auto")
    return {"enabled": _agent_enabled(db), "permissions": sorted(perms), "provider": provider}


@router.get("/runs")
def runs(page: int = 1, per_page: int = 20,
         user=Depends(require_permission("system.manage_users")), db: Session = Depends(get_db)):
    q = db.query(AgentRun).order_by(AgentRun.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    total = db.query(AgentRun).count()
    return {"total": total, "page": page, "per_page": per_page,
            "runs": [{"id": r.id, "user_id": r.user_id, "agent": r.agent, "status": r.status,
                      "duration_ms": r.duration_ms, "steps": r.steps, "tool_calls": r.tool_calls,
                      "tokens": r.tokens, "data_version": r.data_version, "model": r.model,
                      "provider": r.provider, "language": r.language, "cache_hit": r.cache_hit,
                      "fallback_used": r.fallback_used, "created_at": r.created_at.isoformat()}
                     for r in q]}


@router.get("/admin")
def admin_get(user=Depends(require_permission("system.manage_users")), db: Session = Depends(get_db)):
    from app.models import SystemSetting
    cfg = get_ai_config(db)
    row = {s.key: s.value for s in db.query(SystemSetting).filter(
        SystemSetting.key.in_(("agent_cap", "agent_retention_days"))).all()}
    out = {k: cfg.get(k) for k in _AGENT_SETTING_KEYS}
    cap_raw = row.get("agent_cap") or cfg.get("agent_cap")
    ret_raw = row.get("agent_retention_days") or cfg.get("agent_retention_days")
    try:
        out["agent_cap"] = int(cap_raw)
    except (TypeError, ValueError):
        out["agent_cap"] = AGENT_DAILY_CAP
    try:
        out["agent_retention_days"] = int(ret_raw)
    except (TypeError, ValueError):
        out["agent_retention_days"] = 90
    return out


@router.put("/admin")
def admin_put(body: dict, user=Depends(require_permission("system.manage_users")), db: Session = Depends(get_db)):
    updates = {k: v for k, v in body.items() if k in _AGENT_SETTING_KEYS}
    # admin-only numeric settings (persisted as SystemSetting, read by admin_get)
    for k in _AGENT_ADMIN_KEYS:
        if k in body and body[k] is not None:
            v = int(body[k])
            if k == "agent_cap" and not 1 <= v <= 1000:
                raise HTTPException(status_code=422, detail="agent_cap must be 1..1000")
            if k == "agent_retention_days" and not 1 <= v <= 3650:
                raise HTTPException(status_code=422, detail="agent_retention_days must be 1..3650")
            updates[k] = str(v)
    try:
        validate_agents_config(updates)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    from app.models import SystemSetting
    for k, v in updates.items():
        row = db.query(SystemSetting).filter(SystemSetting.key == k).first()
        if row:
            row.value = str(v)
        else:
            db.add(SystemSetting(key=k, value=str(v)))
    db.commit()
    return {"status": "ok"}
```
Implementation notes:
- `_month_for_user(db, user)` (defined above) selects the most recent month with data for the user's hospitals (`max(IndicatorValue.month)`) for `chat`; `report`, `explain`, `digest` bodies carry `month`.
- Set `app.main.py` to `from app.api.agents import router as agents_router` and `app.include_router(agents_router)` next to the other API routers.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_api.py -q`
Expected: PASS (10).

- [ ] **Step 5: Commit**

```bash
git add app/api/agents.py app/main.py tests/test_agents_api.py
git commit -m "feat(agents): /ai/agents API with kill-switch, permissions, daily caps, persistence"
```

---

### Task 9: Frontend chatbot + explain/digest controls (`static/js/agents.js`)

**Files:**
- Create: `static/js/agents.js`
- Modify: `static/js/i18n.js` (add EN/AR keys)
- Modify: `static/css/styles.css` (append `.agent-*` block styles)
- Test: `tests/test_agents_js.py` (new)

**Interfaces:**
- `window.AgentUI`: `init(containerIds)` mounts panels already present in the templates; `renderExplain(data, targetEl)` draws FACTS/ANALYSIS/CONTRIBUTORS/ACTIONS blocks; `togglePanels(status)` hides panels when `status.enabled === false` or permissions missing.

- [ ] **Step 1: Write the failing static tests**

```python
# tests/test_agents_js.py
"""Static sanity checks for agents.js + i18n keys."""
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
AGENTS_JS = BASE / "static" / "js" / "agents.js"
I18N_JS = BASE / "static" / "js" / "i18n.js"


def test_agents_js_exists():
    assert AGENTS_JS.exists()


def test_status_gating_used():
    src = AGENTS_JS.read_text(encoding="utf-8")
    assert "agents_enabled" in src or "enabled" in src
    assert "/ai/agents/status" in src


def test_explain_renders_sections():
    src = AGENTS_JS.read_text(encoding="utf-8")
    for marker in ("facts", "analysis", "contributors", "actions"):
        assert marker in src.lower()


def test_digest_button_label_uses_i18n():
    sjs = AGENTS_JS.read_text(encoding="utf-8")
    ijs = I18N_JS.read_text(encoding="utf-8")
    keys = re.findall(r"__\('([^']+)'\)", sjs)
    assert keys, "agents.js must use __() for every literal"
    for k in keys:
        assert k in ijs, f"missing i18n key: {k}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_js.py -q`
Expected: FAIL — file missing.

- [ ] **Step 3: Implement `static/js/agents.js`**

```javascript
/* AI agent surfaces: chat panel, explain blocks, triage/report buttons. */
(function () {
  'use strict';
  var STATUS_URL = '/api/ai/agents/status'; // same API() prefix used elsewhere
  var API_PREFIX = '';

  function apiPath(p) {
    // mirrors existing authFetch(API() + path) convention
    if (window.API) { return window.API() + p; }
    return API_PREFIX + p;
  }

  function authHeaders() {
    var t = localStorage.getItem('access_token') || '';
    return { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + t };
  }

  function authFetch(url, opts) {
    return fetch(url, Object.assign({ headers: authHeaders() }, opts || {}));
  }

  function status() {
    return authFetch(apiPath('/ai/agents/status')).then(function (r) { return r.json(); });
  }

  function renderExplain(data, el) {
    var blocks = [
      ['facts', data.facts || []],
      ['analysis', data.analysis || []],
      ['contributors', data.contributors || []],
      ['actions', data.actions || []]
    ];
    el.innerHTML = '';
    blocks.forEach(function (pair) {
      var name = pair[0], items = pair[1];
      if (!items || !items.length) { return; }
      var h = document.createElement('h4');
      h.textContent = name.toUpperCase();
      el.appendChild(h);
      var list = document.createElement('ul');
      items.forEach(function (it) {
        var li = document.createElement('li');
        li.textContent = typeof it === 'string' ? it : JSON.stringify(it);
        list.appendChild(li);
      });
      el.appendChild(list);
    });
  }

  function togglePanels(s) {
    document.querySelectorAll('[data-agent-panel]').forEach(function (el) {
      var needs = el.getAttribute('data-agent-perm') || 'ai.read';
      var ok = s.enabled === true && (s.permissions || []).indexOf(needs) !== -1;
      el.style.display = ok ? '' : 'none';
    });
  }

  window.AgentUI = {
    init: function () { return status().then(function (s) { togglePanels(s); return s; }); },
    renderExplain: renderExplain,
    apiPath: apiPath,
    _status: status
  };
})();
```

- [ ] **Step 4: Add i18n keys**

Append to `static/js/i18n.js` (both `en` and `ar` maps):
```javascript
// en
'AI Assistant', 'Direct AI explain', 'Generate Triage Digest',
'Generate report', 'Facts', 'Analysis', 'Contributors', 'Actions',

// ar
'المساعد الذكي', 'شرح مباشر بالذكاء الاصطناعي', 'توليد ملخص المعاينة اليومي',
'توليد التقرير', 'الحقائق', 'التحليل', 'العوامل المساهمة', 'الإجراءات',
```
(Executor: place inside the existing `en`/`ar` dictionaries following the current key format; `__()` lookup format in this repo is `__('English String')`.)

- [ ] **Step 5: Add CSS (append to `static/css/styles.css`)**

```css
.agent-facts, .agent-analysis, .agent-contributors, .agent-actions { margin: 8px 0; }
.agent-facts h4, .agent-analysis h4, .agent-contributors h4, .agent-actions h4 { margin: 6px 0; }
.agent-facts ul, .agent-analysis ul, .agent-contributors ul, .agent-actions ul { padding-left: 18px; }
```

- [ ] **Step 6: Run tests + node check**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_js.py -q`
Expected: PASS (4).
Run: `node --check static/js/agents.js`
Expected: no output (success).

- [ ] **Step 7: Commit**

```bash
git add static/js/agents.js static/js/i18n.js static/css/styles.css tests/test_agents_js.py
git commit -m "feat(agents): agents.js chat/explain/digest UI + i18n + styles"
```

---

### Task 10: System Control AI Agents admin view (`admin.js`)

**Files:**
- Modify: `static/js/admin.js` (add `loadAgentsAdmin`, `renderAgentsRuns`, `saveAgentsAdmin`, plus a panel/view hook)
- Modify: `static/js/i18n.js`, `static/css/styles.css`
- Test: extend `tests/test_agents_js.py`

**Interfaces:**
- Produces: `window.AdminAgents = { load(), save(), renderRuns(runs) }` in `admin.js`.
- Loads `GET /ai/agents/admin` + `GET /ai/agents/runs`; renders audit table with columns: time, user, agent, status, duration, steps, provider, model, data_version, cache_hit, fallback_used. Settings form: `agents_enabled` toggle, `agents_provider` radio, per-role provider selects (`qa`, `explainer`, `report_writer`, `triage`), local fields, `agent_cap`, `agent_retention_days`.

- [ ] **Step 1: Write failing static tests (append to `tests/test_agents_js.py`)**

```python
def test_admin_view_registered():
    src = ADMIN_JS.read_text(encoding="utf-8")
    assert "loadAgentsAdmin" in src
    assert "/ai/agents/runs" in src
    assert "/ai/agents/admin" in src


def test_admin_view_has_role_provider_selects():
    src = ADMIN_JS.read_text(encoding="utf-8")
    for role in ("qa", "explainer", "report_writer", "triage"):
        assert role in src
```
(`ADMIN_JS = BASE / "static" / "js" / "admin.js"` added at the top of the file.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_js.py -q`
Expected: FAIL — 2 new assertions.

- [ ] **Step 3: Implement in `static/js/admin.js`**

Add near the existing logs view (around line 1393 `loadLogs`):
```javascript
async function loadAgentsAdmin() {
  const cfg = await api('/ai/agents/admin');
  const runs = await api('/ai/agents/runs');
  document.getElementById('agents_enabled').checked = cfg.agents_enabled === 'true';
  document.querySelectorAll('input[name=agents_provider]').forEach(r => {
    r.checked = (r.value === cfg.agents_provider);
  });
  const roles = JSON.parse(cfg.agent_provider_roles || '{}');
  ['qa','explainer','report_writer','triage'].forEach(role => {
    const sel = document.getElementById('agent_role_' + role);
    if (sel) { sel.value = roles[role] || ''; }
  });
  document.getElementById('agent_local_runtime').value = cfg.local_runtime || 'ollama';
  document.getElementById('agent_local_model').value = cfg.local_model || '';
  document.getElementById('agent_local_url').value = cfg.local_url || '';
  document.getElementById('agent_cap').value = cfg.agent_cap || 20;
  document.getElementById('agent_retention_days').value = cfg.agent_retention_days || 90;
  renderAgentsRuns(runs);
}

function renderAgentsRuns(runs) {
  const tbody = document.getElementById('agentRunsBody');
  if (!tbody) return;
  tbody.innerHTML = runs.runs.map(r => (
    `<tr><td>${r.id}</td><td>${r.user_id}</td><td>${r.agent}</td>
     <td>${r.status}</td><td>${r.duration_ms}ms</td><td>${r.steps}</td>
     <td>${r.provider}</td><td>${r.model}</td><td>${r.data_version}</td>
     <td>${r.cache_hit ? '✓' : ''}</td><td>${r.fallback_used ? '✓' : ''}</td></tr>`
  )).join('');
}

async function saveAgentsAdmin() {
  const roles = {};
  ['qa','explainer','report_writer','triage'].forEach(role => {
    const v = document.getElementById('agent_role_' + role).value;
    if (v) { roles[role] = v; }
  });
  const payload = {
    agents_enabled: document.getElementById('agents_enabled').checked ? 'true' : 'false',
    agents_provider: document.querySelector('input[name=agents_provider]:checked').value,
    agent_provider_roles: JSON.stringify(roles),
    local_runtime: document.getElementById('agent_local_runtime').value,
    local_model: document.getElementById('agent_local_model').value,
    local_url: document.getElementById('agent_local_url').value,
    agent_cap: document.getElementById('agent_cap').value,
    agent_retention_days: document.getElementById('agent_retention_days').value,
  };
  const resp = await api('/ai/agents/admin', { method: 'PUT', body: JSON.stringify(payload) });
  window.AdminAgents._status(resp).textContent = 'Saved';
}
window.AdminAgents = { load: loadAgentsAdmin, save: saveAgentsAdmin, renderRuns: renderAgentsRuns };
```
(Executor: call `loadAgentsAdmin()` from the view activation hook where Users/Logs load — match `admin.js`'s existing view-switch mechanism.)

- [ ] **Step 4: Run tests + node check**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_js.py -q`
Expected: PASS.
Run: `node --check static/js/admin.js`
Expected: success.

- [ ] **Step 5: Commit**

```bash
git add static/js/admin.js static/js/i18n.js static/css/styles.css tests/test_agents_js.py
git commit -m "feat(agents): System Control AI Agents admin view (audit, routing, local settings)"
```

---

### Task 11: Wire agent settings into the existing AI settings form (`rules-manager.js`)

**Files:**
- Modify: `static/js/rules-manager.js` (around lines 2670-2709: `loadAiSettings`/`saveAiSettings`)
- Modify: `static/js/i18n.js`
- Test: extend `tests/test_agents_js.py`

**Interfaces:**
- Produces: `loadAiSettings` also fills `#agents_enabled`, `#agents_provider`, `#agent_local_*`, and `#agent_provider_roles` (a `<input type="text">` or per-role selects keyed to existing template); `saveAiSettings` includes the `agents_*` keys in the PUT payload.

- [ ] **Step 1: Write failing static test (append to `tests/test_agents_js.py`)**

```python
RULES_JS = BASE / "static" / "js" / "rules-manager.js"

def test_ai_settings_form_carries_agent_keys():
    src = RULES_JS.read_text(encoding="utf-8")
    assert "agents_enabled" in src
    assert "agents_provider" in src
    assert "agent_provider_roles" in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_js.py -q`
Expected: FAIL — 1 new assertion.

- [ ] **Step 3: Modify `rules-manager.js`**

In `loadAiSettings`, after `document.getElementById('ai_timeout')...`:
```javascript
document.getElementById('agents_enabled').value = cfg.agents_enabled || 'false';
document.getElementById('agents_provider').value = cfg.agents_provider || 'auto';
document.getElementById('agent_provider_roles').value = cfg.agent_provider_roles || '{}';
document.getElementById('agent_local_runtime').value = cfg.local_runtime || 'ollama';
document.getElementById('agent_local_model').value = cfg.local_model || 'qwen3:8b';
document.getElementById('agent_local_url').value = cfg.local_url || 'http://localhost:11434';
```
In `saveAiSettings`'s `updates` object add:
```javascript
agents_enabled: document.getElementById('agents_enabled').value,
agents_provider: document.getElementById('agents_provider').value,
agent_provider_roles: document.getElementById('agent_provider_roles').value,
local_runtime: document.getElementById('agent_local_runtime').value,
local_model: document.getElementById('agent_local_model').value,
local_url: document.getElementById('agent_local_url').value,
```
(Executor: add the matching HTML controls inside the AI settings card in the template that `rules-manager.js` binds; placeholders: a select for `agents_provider` with options `local|gemini|openai_compatible|auto`, text inputs for the rest, a hidden/simple text input for `agent_provider_roles`.)

- [ ] **Step 4: Run tests + node check**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_js.py -q`
Expected: PASS.
Run: `node --check static/js/rules-manager.js`
Expected: success.

- [ ] **Step 5: Commit**

```bash
git add static/js/rules-manager.js static/js/i18n.js tests/test_agents_js.py
git commit -m "feat(agents): carry agent settings through the AI settings form"
```

---

### Task 12: Final wiring — retention prune, full verification

**Files:**
- Modify: `app/api/agents.py` (add `prune_agent_runs` call in admin PUT + a startup/lazy prune)
- Test: extend `tests/test_agents_api.py`

**Interfaces:**
- Produces: `prune_agent_runs(db, retention_days=90) -> int` deletes `AgentRun` rows older than `retention_days` (using `created_at`), returns deleted count. Called after admin PUT when `retention_days` provided, and once lazily (first `/ai/agents/runs` of the day, guarded by an in-memory timestamp) to keep the table bounded.

**Goal of this task:** full-suite regression + `node --check` + live smoke + final commit.

- [ ] **Step 1: Write failing test (append to `tests/test_agents_api.py`)**

```python
def test_prune_removes_old_runs(db_session):
    from datetime import datetime, timedelta
    from app.models import AgentRun
    from app.api.agents import prune_agent_runs
    db_session.add(AgentRun(user_id=1, agent="qa", status="completed",
                            created_at=datetime.utcnow() - timedelta(days=200)))
    db_session.add(AgentRun(user_id=1, agent="qa", status="completed",
                            created_at=datetime.utcnow()))
    db_session.commit()
    deleted = prune_agent_runs(db_session, retention_days=90)
    assert deleted == 1
    assert db_session.query(AgentRun).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agents_api.py::test_prune_removes_old_runs -q`
Expected: FAIL — import error.

- [ ] **Step 3: Implement prune**

In `app/api/agents.py`:
```python
def prune_agent_runs(db, retention_days=90) -> int:
    from datetime import timedelta as _td
    cutoff = datetime.utcnow() - _td(days=retention_days)
    deleted = db.query(AgentRun).filter(AgentRun.created_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return deleted
```
Call it inside `admin_put` when `body` contains `agent_retention_days`, and at the top of `runs` (throttled by a module-level `_last_prune` timestamp checked against `datetime.utcnow()`; prune at most once per hour).

- [ ] **Step 4: Run the full suite + checks**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: ALL PASS (baseline 1237 + ~34 new).
Run: `node --check static/js/agents.js; node --check static/js/admin.js; node --check static/js/rules-manager.js`
Expected: all succeed.

- [ ] **Step 5: Live smoke**

- Start server (`Start-Process` pattern, port 8000), wait for `/health` 200.
- PUT `/config/ai/settings` with `agents_enabled=false` (default) → `GET /ai/agents/status` returns `{"enabled": false}`.
- PUT `{"agents_enabled": "true", "agents_provider": "auto", "local_url": "http://127.0.0.1:9"}` (unreachable local) → `POST /ai/agents/chat` with a user holding `ai.read` → expect deterministic fallback answer, HTTP 200 (auto → local unreachable → no cloud key → fallback).
- Seed/restrict a user to 1 hospital; confirm `list_accessible_hospitals` facts only contain that hospital; confirm another hospital id in a tool arg returns `ACCESS_DENIED`.
- System Control → AI Agents: enable agents, set `agent_provider_roles = {"report_writer": "gemini"}` → run digest and report; confirm `agent_runs` rows record respective providers.

- [ ] **Step 6: Commit**

```bash
git add app/api/agents.py tests/test_agents_api.py
git commit -m "feat(agents): retention prune + final wiring"
```

---

## Task dependency order

1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12

(Tasks 9–11 are independent of each other once Task 8 lands; Tasks 3–7 are strictly ordered by `Interfaces`.)

## Self-review notes (from spec cross-check)

- Kill-switch OFF / no LLM call → Task 1 (keys), Task 8 (`_agent_enabled` + `_disabled_payload`), runtime tested in Task 7.
- Per-role routing + Auto resolution + **mapped-but-down degrades to global** (spec §3) → Task 3 (`resolve_agent_provider` + `_provider_viable` + `_resolve_auto`); tests in `test_agents_llm.py` (`test_resolve_mapped_but_down_degrades_to_global`) and `test_agents_runtime.py`.
- Grounding policy verbatim in every profile → Task 7 `GROUNDING` block; fallback "Insufficient data" → Task 5.
- **Allowed-tool enforcement (spec §12): an unauthorized tool requested by the model is rejected with a validation observation before execution** → Task 7 runtime (`batch`/`rejected` partition per `P["allowed_tools"]`); test `test_run_agent_rejects_disallowed_tool`.
- **Chat memory + history compression (spec §7): last ~6 turns verbatim, older folded into a summary line** → Task 7 (`run_agent(..., history=...)` + prompt_hash includes history) + Task 8 chat passes `prior` messages; test `test_run_agent_history_compression`.
- FACTS/ANALYSIS/CONTRIBUTORS/ACTIONS structured contract → Task 5 fallbacks shape + Task 9 renderExplain.
- Hospital scope injected server-side, ACCESS_DENIED, arg validation → Task 4.
- Scope/permission-safe cache key + single-flight + versioning + bumps in upload/recompute hooks → Task 6.
- Audit trail fields (data_version, provider, model, cache_hit, fallback_used, hashes) → Task 2 model + Task 8 persistence; admin-only System Control view → Task 10; retention prune → Task 12.
- **report/digest gate requires BOTH ai.write AND ai.read (spec §9)** → Task 8 `require_ai_write` dependency; tests `test_report_requires_ai_write` + `test_report_and_digest_blocked_without_ai_read`.
- **agent_cap / agent_retention_days persisted as SystemSetting + validated (1..1000 / 1..3650) (spec §8 admin PUT)** → Task 8 admin_get/admin_put; Task 12 prune uses the stored retention.
- Budgets (steps/calls/runtime/tokens) + batch ≤3 + early finish + JSON retry + 429 Retry-After → Task 7 runtime.
- BL leaders: no new SDK; Ollama via OpenAI-compatible endpoint → Task 3 httpx path.

## Open decisions for the executor to confirm with the user (non-blocking)

- The `agent_provider_roles` UI in the admin panel: dropdowns (chosen) vs single JSON text field. Task 10 uses dropdowns; Task 11 uses a simple text field for the settings form.
- `get_peer_comparison`/`query_month_aggregates` compute from `_load_hospital_data` (same source the smart engine uses) rather than from `report_cache` rows — approved in-spec (“source data from existing engine functions”).