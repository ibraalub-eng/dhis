"""ReAct agent runtime: budgets, retries, strict tool-call JSON, fallback."""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.agents.cache import (
    build_agent_cache_key,
    current_data_version,
    get_agent_cache,
    set_agent_cache,
)
from app.agents.llm import llm_chat, resolve_agent_provider
from app.agents.tools import ToolContext, execute_tool

MAX_NON_PROGRESS_RETRIES = 2


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
        raise ValueError("not JSON") from None


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
            cached = get_agent_cache(db, key)
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

    try:
        resolved = resolve_agent_provider(profile, db)
    except Exception:
        resolved = None
    caller = llm_caller or llm_chat
    executor = tool_executor or execute_tool
    calls_made = 0
    steps = 0
    retries = 0
    tool_log = []
    tokens = {"in": 0, "out": 0}
    system = P["system_prompt"]
    transcript_parts = []
    if history:
        # spec §7 history compression: older turns -> summary, last ~6 verbatim
        older, recent = history[:-6], history[-6:]
        if older:
            transcript_parts.append(
                f"Earlier conversation summary: {len(older)} earlier turns (summarized)")
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
                and tokens["in"] < P["max_input_tokens"]
                and retries < MAX_NON_PROGRESS_RETRIES
                and time.time() - start < P["max_runtime_s"])

    if resolved is not None:
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
            tokens["in"] += getattr(result, "prompt_tokens", 0) or 0
            tokens["out"] += getattr(result, "completion_tokens", 0) or 0
            try:
                step = _parse_step(result.text)
            except ValueError:
                retries += 1
                if retries >= MAX_NON_PROGRESS_RETRIES:
                    break
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
                retries += 1
                if retries >= MAX_NON_PROGRESS_RETRIES:
                    break
                obs = [{"tool": t["name"], "result": {"ok": False,
                       "error": f"validation: tool {t['name']} is not allowed for profile {profile}"}}
                       for t in rejected]
                transcript_parts.append("Tool observations: " + json.dumps(obs, ensure_ascii=False)[:4000])
                continue
            if not batch and not rejected:
                retries += 1
                if retries >= MAX_NON_PROGRESS_RETRIES:
                    break
                transcript_parts.append("No tools specified. Respond with {\"done\": true, ...} to finish.")
                continue
            room = P["max_tool_calls"] - calls_made
            if room <= 0:
                break
            batch = batch[:room]
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
            retries = 0
            steps += 1
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

    provider_name = resolved.provider if resolved is not None else ""
    model_name = resolved.model if resolved is not None else ""
    if status == "completed":
        try:
            set_agent_cache(db, key, {"answer": answer, "facts": agent_facts, "sources": [],
                                      "provider": provider_name, "model": model_name},
                            data_version=data_version, hospital_scope_hash=hospital_scope_hash)
        except Exception:
            pass

    return AgentResult(agent=profile, answer=answer, facts=agent_facts, sources=[],
                       status=status, steps=steps, tool_calls=tool_log, tokens=tokens,
                       provider=provider_name, model=model_name, language=lang,
                       fallback_used=fallback_used, cache_hit=False,
                       duration_ms=int((time.time() - start) * 1000),
                       data_version=data_version, hospital_scope_hash=hospital_scope_hash,
                       permission_scope_hash=permission_scope_hash, prompt_hash=prompt_hash)
