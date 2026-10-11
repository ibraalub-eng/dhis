# US-01 — Report Cache Isolation by Hospital / User / Permission Scope — Design Specification

## User Story

> As a DHIS system user, I want cached reports to be isolated by hospital, user
> scope, and permission scope, so that Hospital A and Hospital B never share
> results.

### Acceptance Criteria

1. **AC1** — Same request, same user → served from cache.
2. **AC2** — Hospital A cannot obtain Hospital B's cache.
3. **AC3** — Changing any effective filter produces a different cache key.
4. **AC4** — All tests pass.
5. **AC5** — The report logic itself (scoring, ordering, aggregation) does **not** change.

---

## Context — current state (verified)

| Fact | Evidence |
|---|---|
| `GET /reports/` cache key = `reports:list_v2` built from `month, source_file, skip, limit, hospital_id` — no user, no hospital scope, no permissions | `app/api/reports.py:45-52` |
| `hospital_id` was already added to that key by an uncommitted working-tree change (AC3 groundwork) | `git diff app/api/reports.py` |
| `list_reports` imports `get_user_hospital_ids` but never calls it → the query has **no** hospital-scope filter | `app/api/reports.py:15`, body `:29-56` |
| Precedent for per-user cache keys exists: `cache.make_key("hospitals:list", uid=…)` | `app/api/hospitals.py:37` |
| Scope helper returns `None` (superuser), `[]` (no assignment), `[ids]` (restricted) | `app/core/deps.py:49-66` |
| Admin API contract: `[]` = **no restriction** ("Pass `{hospital_ids: []}` to allow all", `is_restricted = len>0`) | `app/api/admin.py:241-267` |
| `alerts.py` / `dashboard.py` instead treat `[]` as *zero rows* (`if user_hosp_ids is not None: .in_(…)`) | `app/api/alerts.py:35,130`, `app/api/dashboard.py:181` |
| `hospitals.py` treats empty assignment as *unrestricted* (`if _assigned:`) | `app/api/hospitals.py:67-72` |
| Comprehensive report cache = `comparative_report_v2:{month}:{lang}` in `AnalysisCache`, written **only** when the AI path succeeded; explanations stripped at read time | `app/engine/comparative/report_cache.py:10-14`, `report_generator.py:1126-1128,1219` |
| The one cache *inside* report generation: `regional_{month}_6` (TTL 300 s) — global key, global content | `report_generator.py:1139-1142` |
| Every hospital-level analysis in the generation path funnels through `_load_hospital_data(session, month)` | `smart/__init__.py`, used by `lag_analysis.py:135`, `regional.py:198,866` |
| `run_smart_analytics` callers that must keep current behavior | `report_generator.py:1130`, `export.py:130`, `advanced_comparison.py:57,82`, `smart_analytics.py:233` |
| XGBoost artifacts are trained/persisted into one shared `SMART_XGB_MODEL_DIR` | `xgboost_predictor.py:27-29,655-676` |

**Decisions taken during brainstorming (user-approved):**

- Scope covers **all report-related caches** (`reports:list_v2` **and** the
  comprehensive-report cache), not just `list_v2`.
- Hospital scope is applied to the **query as well as the key** (access
  control), pattern-matched on `alerts.py`.
- The month-level comprehensive report is **isolated by scope too** (Approach A:
  explicit optional parameters threaded through the engine — chosen over
  ContextVar and over 403-rejection).

---

## Scope

### In scope

1. `GET /reports/` (`reports:list_v2` → `list_v3`): scope-filtered query + scoped key.
2. `GET /comparative/comprehensive-report/{month}`: scope-filtered generation + scoped `report_cache` key.
3. Every data-loading seam feeding that generation path, including the internal `regional_*` cache and the XGBoost model directory.
4. Tests proving AC1–AC5.

### Out of scope (documented, deliberately untouched)

- `alerts.py` / `dashboard.py` `[] = zero rows` semantics and the self-contradictory docstring at `deps.py:53-55`. This spec **resolves the ambiguity locally** (see "Scope semantics") rather than changing other screens.
- `hospitals.py:67-72` treating empty assignment as unrestricted (already matches the admin contract, but keyed by `uid` only).
- Caches of non-report screens: `smart_overview_*`, `analysis:*`, `hospitals:*`.
- Uncached report endpoints (`/detail`, `/from-file`, `/export/*`) — they compute per request today; nothing shared to isolate.
- Frontend changes: scoping is entirely server-side; the UI already sends the same requests.

---

## Design

### 1. Scope helper — `app/core/deps.py`

Functions added next to the existing `get_user_hospital_ids` (plus
`import hashlib` at the top):

```python
def get_scope_hospital_ids(user, db) -> list[int] | None:
    """None = unrestricted (all hospitals); [ids] = restricted to these."""
    ids = get_user_hospital_ids(user, db)
    return list(ids) if ids else None


def hospital_scope_tag(user, db) -> str:
    """Content scope of a payload: "all" | "h1-2-3".

    Follows the admin API contract (admin.py: "empty list = all"): an empty
    assignment collapses to "all". This is the ONLY scope component the
    comprehensive report's content depends on (see "Why two token forms").
    """
    ids = get_user_hospital_ids(user, db)
    return "all" if not ids else "h" + "-".join(str(i) for i in sorted(ids))


def scope_token(user, db) -> str:
    """Full cache-scope fingerprint: u{id}_{hospital-part}_{perm-part}."""
    hosp = hospital_scope_tag(user, db)
    if getattr(user, "is_superuser", False):
        perm = "super"
    else:
        perms = ({p.codename for p in user.permissions}
                 | {p.codename for r in user.roles for p in r.permissions})
        perm = hashlib.sha1(",".join(sorted(perms)).encode("utf-8")).hexdigest()[:10]
    return f"u{user.id}_{hosp}_{perm}"
```

Examples: `u12_h1-2-3_3f9a1c2d0b`, `u1_all_super`; `hospital_scope_tag` →
`all`, `h1-2-3`.

**Why two token forms.** A payload is keyed by everything that can change its
content:

- `GET /reports/` rows are a function of `(filters, hospital scope)` and the
  endpoint is cheap — `scope_token` (uid + hospital + perms) is used anyway so
  AC2 holds under the strictest reading (nobody can hit another user's entry)
  and because it matches the existing `hospitals.py` `uid=` precedent.
- The comprehensive report is an **expensive AI artifact** whose stored content
  is a function of `(month, lang, hospital scope)` only — uid does not change a
  single byte of it (explanations are stripped at *read* time, not stored
  scope-dependently), and permissions gate the endpoint uniformly. Keying it by
  uid would trigger one AI generation per user per month×lang for byte-identical
  payloads. So it is keyed by `hospital_scope_tag`: AC2 holds because the
  content of two entries differs *exactly* when their hospital scopes differ,
  and unrestricted users intentionally share the single global entry they all
  have full rights to see (today's behavior preserved).

Token properties (each is an AC3 dimension):

- **user scope** → `u{id}` changes when the user changes;
- **hospital scope** → `h…` changes when the assignment changes (unrestricted
  and restricted can never collide: `all` vs `h…`);
- **permission scope** → `perm` changes when the effective permission set changes.

Token contains only `[0-9a-zA-Z_-]`, so it is filename-safe (TTLCache
`_safe_filename`), SQL-`LIKE`-safe (invalidation templates) and keeps
`AnalysisCache.cache_key` (String(200)) comfortably short:
`comparative_report_v2:2026-06:ar:h1-2-3` ≈ 40 chars.

**Scope semantics** (the resolution of the `[]` ambiguity for *this* feature):

| User | `get_user_hospital_ids` | `get_scope_hospital_ids` | Token hosp-part | Query |
|---|---|---|---|---|
| Superuser | `None` | `None` | `all` | unfiltered |
| Regular, no assignment | `[]` | `None` (admin contract) | `all` | unfiltered |
| Regular, assigned | `[ids]` | `[ids]` | `h…` | `hospital_id IN (ids)` |

### 2. `GET /reports/` — `app/api/reports.py`

```python
def list_reports(..., db=Depends(get_db),
                 user=Depends(require_permission("analysis.read"))):
    scope = get_scope_hospital_ids(user, db)
    if scope is not None:
        query = query.filter(QualityScore.hospital_id.in_(scope))
    cache_key = cache.make_key(
        "reports:list_v3",
        month=month, source_file=source_file, skip=skip, limit=limit,
        hospital_id=hospital_id,
        scope=scope_token(user, db),
    )
    ...
```

- `require_permission` is already a router-level dependency (`reports.py:17`);
  repeating it at parameter level only materializes the `user` object (FastAPI
  caches the dependency).
- An explicit `hospital_id` outside the scope intersects with the scope filter →
  empty result, never a leak.
- Bumping `v2 → v3` orphans every legacy unscoped entry immediately; they still
  expire via the 24 h TTL and the data-epoch sweep.
- **Unchanged:** ordering, the inactive-hospital filter (`:65`), `ReportOut`
  shaping, pagination, cache `set` call → report logic untouched (AC5).

### 3. Comprehensive report — threading the scope

Every function below gains `hospital_ids: Optional[list[int]] = None`
(**default `None` ⇒ byte-identical behavior for all existing callers**):

| Function | File | What the parameter does there |
|---|---|---|
| `get_comprehensive_report` | `app/api/comparative.py:12` | computes `hospital_ids = get_scope_hospital_ids(user, db)` (engine filtering) and `scope = hospital_scope_tag(user, db)` (cache component) — user already injected at `:18` — and passes both down |
| `generate_comprehensive_report` | `report_generator.py:1122` | gains **two** parameters: `hospital_ids: Optional[list[int]] = None` (engine filtering) and `scope: str = "all"` (cache-key component). It has no request context of its own, so both are computed at the API layer and passed in; `scope` is used for `get_stored_report` / `store_report` and for the internal regional key |
| `_load_indicator_stats` | `report_generator.py` | → `_load_hospital_data(..., hospital_ids)` for current + previous month |
| `_build_forecast_brief` | `report_generator.py` | → `run_lag_analysis(..., hospital_ids)` |
| regional fetch block | `report_generator.py:1139-1142` | reads/writes `regional_{month}_6` when unrestricted, `regional_{month}_6_{scope}` when scoped; calls `run_regional_analysis(..., hospital_ids)` |
| `run_smart_analytics` | `smart/__init__.py:154` | → `_load_hospital_data`, → `run_xgboost_predictions` |
| `_load_hospital_data` | `smart/__init__.py` | `q = q.filter(Hospital.id.in_(hospital_ids))` **before** `.all()` — the whole result (values, disabled maps, auto-disable, `all_data`) is built by iterating `hospitals`, so this single filter scopes everything |
| `_load_series`/lag window loader, `run_lag_analysis` | `lag_analysis.py:127-147,279` | passes `hospital_ids` into every `_load_hospital_data(session, m)` in the window |
| `run_regional_analysis`, `_monthly_gov_metrics`, gov completeness/confidence loop | `regional.py:198,735-740,864` | scope the `_load_hospital_data` calls **and** the `Hospital` / `QualityScore` / `ConfidenceScore` iterations |
| `_load_multi_month_data`, `run_xgboost_predictions` | `xgboost_predictor.py:99,753` | restrict training/prediction hospitals to the scope; model artifacts saved under `MODEL_DIR/{scope}` (see below) |

**XGBoost model directory.** Models are persisted into a single shared
`SMART_XGB_MODEL_DIR` (`xgboost_predictor.py:28`). If a scoped run trained on a
narrower hospital set wrote into that same directory, it would (a) leak
aggregate information from excluded hospitals through the reused artifact and
(b) thrash with the unrestricted run. Therefore `run_xgboost_predictions` gains
an optional `model_dir` (default = current `MODEL_DIR`): unrestricted runs keep
today's directory byte-for-byte, scoped runs use
`os.path.join(MODEL_DIR, hospital_scope_tag)` — e.g. `…/models/h1-2-3`.
`config["xgboost_enabled"]` and failure handling stay as they are.

**Consumers left untouched (defaults):** `export.py:130`,
`advanced_comparison.py:57,82`, `smart_analytics.py:233` — no signature
breakage, no behavior change.

### 4. Cache keys

| Cache | Today | After | Scope component |
|---|---|---|---|
| Reports list (TTLCache) | `v2\|reports:list_v2\|…` | `v2\|reports:list_v3\|…\|scope=<token>` | `scope_token(user, db)` — uid + hospital + perms |
| Comprehensive report (`AnalysisCache`) | `comparative_report_v2:{month}:{lang}` | `comparative_report_v2:{month}:{lang}:{scope}` | `hospital_scope_tag(user, db)` → `all` / `h1-2-3` |
| Internal regional (TTLCache, TTL 300 s) | `regional_{month}_6` | unchanged for unrestricted; `regional_{month}_6_{scope}` when scoped — scoped runs neither read nor write the global entry | `hospital_scope_tag` |
| XGBoost models | `SMART_XGB_MODEL_DIR/` | `SMART_XGB_MODEL_DIR/{scope}` for scoped runs only | `hospital_scope_tag` |

`get_stored_report` / `store_report` gain `scope: str = "all"`; the default keeps
every current call site valid.

**Invalidation.** `invalidate_report_cache(month)` filters
`LIKE 'comparative_report_v2:{month}:%'`, which still matches every
`…:{lang}:{scope}` row → one upload invalidates all scopes (callers already in
place: `file_ops.py:332,602`, `hospitals.py:419`). TTLCache prefix invalidation
and data-epoch scoping (`app/cache.py`) behave per key as before.

### 5. Error handling & edge cases

- **No "empty scope" state exists**: empty assignment collapses to `None`
  (admin contract), so generation never runs against zero hospitals because of
  scope.
- Stale scope ids (deleted/inactive hospitals) → empty report list /
  `hospitals_count == 0`, mirroring the empty list endpoint — no new exception
  types.
- Generation failures keep mapping to HTTP 500 with the existing message
  (`comparative.py:28-30`); cache JSON decode failures still return `None`
  (`report_cache.py:42-46`).
- Cached payloads are epoch- and TTL-scoped as today; a scope change for a user
  (assignment edited) produces a brand-new key, so stale per-scope rows are
  unreachable rather than served.

---

## Testing (AC mapping)

New file `tests/test_report_scope_us01.py`, reusing existing fixtures:
`_FakeSuperAdmin` / `_bypass_auth` (`conftest.py:81-107`), `db_session` with
seeded hospitals, `_isolate_cache_dir`, and the `mock_api` pattern from
`test_comparative.py`. Restricted users are built in the test DB (a `User` with
`analysis.read` + `user_hospitals` rows) and injected through an override of
`get_current_user` — which works because `require_permission` resolves its user
through the same dependency (`deps.py:32-34`). The data epoch is frozen in
tests (`compute_data_epoch` patched), so test 1's mid-test row mutation cannot
be masked by an epoch change.

| # | Test | AC |
|---|---|---|
| 1 | `test_list_reports_cache_hit_same_user` — two identical GETs with a `QualityScore` row mutated in between → second response equals first (cache served) | AC1 |
| 2 | `test_list_reports_isolated_between_restricted_users` — users scoped to h1 and h2: each sees only its own rows, distinct keys, and neither can read the other's entry after it is cached | AC2 |
| 3 | `test_scope_key_changes_with_effective_filter` — parametrized over `month, source_file, skip, limit, hospital_id, uid, hospital scope, permission set` → distinct keys; `scope_token` is stable for identical input | AC3 |
| 4 | `test_report_cache_scoped_keys` + `test_invalidate_month_covers_all_scopes` — cross-scope `get_stored_report` → `None`; month invalidation removes every scope | AC2 |
| 5 | `test_load_hospital_data_respects_scope` + `test_run_smart_analytics_scoped` — one seeded hospital in scope → `hospitals_count == 1` and anomalies from that hospital only; call without parameter → unchanged results | AC2, AC5 |
| 6 | `test_regional_cache_key_scoped` — scoped generation writes/reads only the scoped regional key | AC2 |
| 7 | `test_comprehensive_report_endpoint_scoped` — restricted user calls `/comparative/comprehensive-report/{month}` → sections/KPI cover their hospitals only | AC2 |
| 8 | `test_list_reports_superuser_unfiltered` (regression) + full suite | AC4 |

## Verification

```
python -m pytest tests/test_report_scope_us01.py -q
python -m pytest -q
```

Both must be green, including every pre-existing test (the suite currently
contains ~50 files modified by earlier, uncommitted work — this change adds
files/edits only and must not regress them).

---

## Risks / notes

- **Cache cardinality**: the reports-list key includes `uid` → one entry per
  user per filter-combo (file-backed). Deliberate — AC2 is read literally and it
  matches the `hospitals.py` precedent; entries are TTL/epoch-scoped. The
  comprehensive report deliberately does **not** include `uid` (see "Why two
  token forms") — it multiplies only by hospital scope, not by user.
- **Scoped AI reports multiply `AnalysisCache` rows** (one per scope × lang).
  Acceptable: rows are written only on AI success and are wiped by upload
  invalidation.
- **Scoped runs train narrower models** — expected; artifacts are isolated per
  scope directory so the unrestricted model is never overwritten.
- **`deps.py:53-55` docstring contradicts its own code comment**; left as is
  (other callers depend on the behavior). Recorded here as a known debt.
