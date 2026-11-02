# D15 — Amendment A1: System Control as the Single Source of Analysis Policy

**Status:** design proposal — not implemented, not approved
**Amends:** `D15-OUTLIER-PROVENANCE-ARCHITECTURE.md` (sections 3.3 config, 4 contract, 5 versioning, 9 phases, 12 risks)
**Base commit:** `4b82b19` on `very-high-gate-integration`
**Companion:** `D15-APPENDICES-B-C-D.md` (deliverables B/C/D)

---

## 0. Scope of this amendment, and one stated assumption

This amendment adds a **mandatory architectural requirement**: System Control is the authoritative
source of every *configurable* analysis policy and threshold, and the analysis engine must hold no
independent static value that duplicates a setting System Control already manages.

The brief that requested this amendment was received truncated mid-sentence in section 4
("Its responsibilities: 1. Read the currently"). Sections 1–4.1 are therefore answered exactly as
written; **§4.2 onward and §5–§12 below are my completion of the same intent**, marked so they can be
corrected rather than mistaken for quoted requirements. Nothing in them relaxes a requirement from
§1–§4.1.

Everything below is derived from reading the implementation. Where a claim is about a value that
lives in the database, it is stated as *seeded default* or *stored shape* — **this phase opened no
database connection**, so no row count or saved value is asserted here. D14's measurements remain
the only empirical figures in the D15 family.

Explicitly untouched: `zscore_threshold = 2.5`, every severity cutoff, the peer policy, the
zero-spread / thin-peer / top-band caps, all scoring weights and every formula. This amendment
proposes *where values are read from and how they reach the engine* — not *what the values are*.

---

## 1. What "System Control" actually is (verified, not assumed)

There is no `SystemControl` class and no `system_control` table. System Control is a **screen and an
API prefix** (`/config/*`, permission `settings.read` / `settings.write`) over **two independent
key/value tables**, plus a module of seeded defaults.

| Layer | Storage | Type | Written by | Read by |
|---|---|---|---|---|
| `AppConfig` | table `app_config` | `key`, `value` **Float**, `category`, `label`, `updated_at` | `main.py` seed, `PUT /config/`, `PUT /config/control/settings` | `config_utils.get_config_dict(db, category)` |
| `SystemSetting` | table `system_settings` | `key` (PK), `value` **Text**, `updated_at` | `PUT /config/control/settings`, month toggles, AI settings, seed of new trend keys | `config_utils.get_ai_config`, direct `query(SystemSetting)`, `severity.load_analysis_config` |
| Seeded defaults | `app/main.py: APP_CONFIG_DEFAULTS` | list of `(key, default, category, label)` | idempotent startup seed | as above |

Consequences that matter for this amendment:

1. **`AppConfig.value` is a Float column.** Anything non-numeric (an enum, a boolean-looking string)
   cannot be stored there losslessly, which is exactly why `severity.py` introduced
   `EXISTING_TREND_KEYS` and stores the *new* trend controls in `SystemSetting` while their numeric
   siblings stay in `AppConfig`. **The storage location of a policy is therefore an artefact of the
   column type, not a design decision.** Any resolver must abstract this, because a caller cannot
   guess which table holds which knob.
2. **The same logical category is split across both tables.** Category `trends` is partly
   `AppConfig` (`trend_slope_*`, `trend_finding_*`) and partly `SystemSetting`
   (`trend_analysis_window`, `trend_assessment_enabled`, `trend_direction`,
   `trend_severity_policy`, …). `load_analysis_config` merges them; nothing else does.
3. **A legacy duplicate was already removed once, deliberately.** `SystemSetting
   ('anomaly_zscore_threshold')` (default 2.0) competed with `AppConfig
   ('zscore_threshold')` (2.5). `config_api.reconcile_legacy_settings` deletes it on startup and
   again inside `PUT /config/control/settings`. **This is the precedent the whole amendment
   generalises: one knob, one storage location, the duplicate actively deleted.** That duplication
   was found and fixed by hand for one parameter; nothing prevents the next one.

---

## 2. Parameter inventory (every configurable parameter in the outlier path)

`Storage`: `AC` = `AppConfig` (numeric), `SS` = `SystemSetting` (text). `Default`: seeded value.
Consumers are the call sites that actually read it (file:line at `4b82b19`).

### 2.1 Thresholds and detection

| # | Parameter | Key | Storage | Default | Bounds / validation | Consumers | Static duplicate? | Configurable |
|---|---|---|---|---|---|---|---|---|
| 1 | Z-score threshold | `zscore_threshold` | AC `thresholds` | 2.5 | `ZSCORE_MIN..MAX` 1.0–5.0, `ZSCORE_STEP` 0.1, rounded 2dp (`severity.py`); `PUT` clamps identically | `severity.load_analysis_config`; `pipeline` → `anomaly_config` → `Thresholds.peer_z_threshold`; `quality_alerts` (`cfg["z_threshold"]`); `confidence.py`; `anomaly/zscore.py`; `explain._zscore_threshold`; `dashboard`; `config_api` | **YES ×5** — `severity.DEFAULT_ZSCORE_THRESHOLD=2.5`, `layered.PEER_Z_THRESHOLD_DEFAULT=2.5`, `trends._TRENDS_CONFIG["zscore_threshold"]=2.5`, `.get("zscore_threshold", 2.5)` in `confidence.py:477`, `2.5` literals in `quality_alerts._alerts_config` | Yes |
| 2 | Top-band peer floor | *none* | **code** | `MIN_PEERS_FOR_TOP_BAND = 4` | frozen constant | `layered.py`, `pipeline._save_layered_results`, explain, consistency tools | n/a | **No — deliberately not a knob** |
| 3 | Zero-spread cap | *none* | **code** | `ZERO_SPREAD_LEVEL_CAP = HIGH` | frozen | `layered.py` | n/a | No |
| 4 | Thin-peer cap | *none* | **code** | `THIN_PEER_LEVEL_CAP = HIGH` | frozen | `layered.py`, `pipeline` | n/a | No |
| 5 | %-change cap policy | *none* | **code** | `PCT_CHANGE_CAP_POLICY` | frozen tuple | `layered`, `classify` | n/a | No |
| 6 | Method selection | *none* | **code** | `CV_MAX=0.5`, `MIN_IQR_POINTS=6`, `MIN_TREND_POINTS=6`, `RARE_EVENT_MEAN_MAX=10.0`, `MAD_SCALE=1.4826` | frozen | `layered` | n/a | No |

### 2.2 Comparison policy (history window + peers)

| # | Parameter | Key | Storage | Default | Bounds | Consumers | Static duplicate? | Configurable |
|---|---|---|---|---|---|---|---|---|
| 7 | History window (alerts) | `alerts_history_window` | AC `alerts` | 12 | `_bounded_int(..., 1, 120)` | `resolve_comparison_policy`, `_alerts_config` | `HISTORY_WINDOW_DEFAULT=12` (module constant = the same default) | Yes |
| 8 | Analysis window (trend) | `trend_analysis_window` | **SS** (new key) | 12 | spec 1–36 | `severity.TrendSettings.window`; **also caps #7 via `min()`** | `_TRENDS_CONFIG` has no such key | Yes |
| 9 | Minimum observations | `alerts_min_history` | AC `alerts` | 3 | `_bounded_int(..., 2, 24)` | `resolve_comparison_policy` | `MIN_HISTORY_OBSERVATIONS_DEFAULT=3` | Yes |
| 10 | Minimum peers | `alerts_min_peers` | AC `alerts` | 2 | `_bounded_int(..., 2, 100)` | `resolve_comparison_policy`, `_alerts_config`, `Thresholds.min_peers` | `MIN_PEERS_DEFAULT=2` | Yes |
| 11 | Per-indicator history floor | `Indicator.minimum_history_period` | **DB column per indicator** | `DEFAULT_MINIMUM_HISTORY=3` | per-row | `HistoryPolicy.with_item_minimum` | constant fallback only | Yes (data, not System Control) |

### 2.3 Alerts

| # | Parameter | Key | Storage | Default | Bounds | Consumers |
|---|---|---|---|---|---|---|
| 12 | Minimum alert score | `alerts_min_score` | AC `alerts` | 0.5 | none in code | `_alerts_config` |
| 13 | ML cross-check on | `alerts_ml_enabled` | AC `alerts` | 1 | `== 1` | `_alerts_config` |
| 14 | ML min samples | `alerts_ml_min_samples` | AC `alerts` | 12 | `max(4, …)` | `_alerts_config` |
| 15 | Auto-scan after analysis | `alerts_auto_scan` | AC `alerts` | 1 | string compare | `pipeline:775` |

### 2.4 Severity / trend

| # | Parameter | Key | Storage | Default | Bounds |
|---|---|---|---|---|---|
| 16 | Trend assessment on | `trend_assessment_enabled` | SS | true | bool |
| 17 | Minimum history months | `trend_min_history_months` | SS | 2 | 2–24 |
| 18 | Direction that counts | `trend_direction` | SS | `any` | enum: any / increasing / decreasing / indicator_specific |
| 19 | Persistence | `trend_finding_consecutive` | AC `trends` (**existing key, reused**) | 3 | 1–12 |
| 20 | Min cumulative change % | `trend_min_cumulative_change_pct` | SS | 5.0 | 0–100 |
| 21 | Trend severity policy | `trend_severity_policy` | SS | `none` | enum: none / escalate / override |
| 22 | Escalation bands | `trend_severity_escalation` | SS | 1 | 1–4 |
| 23 | Override target | `trend_severity_target` | SS | `HIGH` | enum: LOW/MODERATE/HIGH/VERY_HIGH |
| 24 | Min completeness gate | `trend_min_completeness` | SS | 0.0 | 0–100 |
| 25–28 | Slope bands | `trend_slope_stable/low/moderate/high` | AC `trends` | 2 / 5 / 15 / 30 | monotonic clamp at load |
| 29 | R² threshold | `trend_r_squared` | AC `trends` | 0.5 | none |
| 30–33 | Finding thresholds | `trend_finding_slope/deviation/cv/r_squared` | AC `trends` | 5 / 20 / 30 / 0.7 | none |

### 2.5 Scoring (Quality Score)

| # | Parameter | Key | Storage | Default |
|---|---|---|---|---|
| 34–37 | Component weights | `quality_rule_compliance / _completeness / _consistency / _outlier_penalty` | AC `quality` | 0.35 / 0.25 / 0.25 / 0.15 |
| 38 | Outlier multiplier | `outlier_multiplier` | AC `quality` | 2.0 (`PREVIOUS_OUTLIER_MULTIPLIER=1.5` kept for audit recognition only) |
| 39–42 | Severity weights | `severity_critical/high/medium/low` | AC `quality` | 1.0 / 3.0 / 2.0 / 1.0 |
| 43–45 | Confidence cutoffs | `confidence_high/medium/low` | AC `thresholds` | 80 / 50 / 25 |

### 2.6 Verdict on configurable vs hardcoded

- **43 parameters** are genuinely configurable and stored (45 rows counting the three confidence
  cutoffs and the four finding thresholds).
- **11 constants** are frozen algorithm policy and are **correctly not knobs**: the top-band peer
  floor (4), the two level caps, the %-change cap tuple, and the five method-selection constants +
  MAD scale + default minimum history. Moving any of them into System Control would create a
  policy surface nobody approved; §3.4 states the test that keeps them out.
- **5 modules** independently restate a configurable value as a literal (§3.2).

---

## 3. Static duplication and reconstruction — the actual defects

### 3.1 The one structural defect: process-global config mutation

```python
# app/engine/anomaly/trends.py
_TRENDS_CONFIG = {...}                    # module-level defaults, incl. zscore_threshold: 2.5
def set_trends_config(config: dict):      # mutates the global
    _TRENDS_CONFIG.update(config)
```

`pipeline.run_analysis` calls `set_trends_config(...)` for **every** hospital/month. Consequences:

- The effective trend policy is **process state**, not run state. Two overlapping scans (API request
  + background alerts scan) write the same dict; the later writer wins for both.
- After any scan, the module keeps the *last* configuration it saw. A caller that does not pass a
  config (explain, audit, a future script) silently inherits whatever the last analysis set —
  a value that is neither the current saved policy nor a documented default.
- `_resolved_settings()` merges per-call config over the global, so a *stale global key* survives
  whenever the caller's dict omits it. `trend_engine_config()` masks this only because it happens
  to include every spec key.

This is the "consumer independently reconstructs policy" failure in its most concrete form. No
per-module literal is as dangerous as a surviving process global.

### 3.2 Literal duplication (same knob, restated)

| Value | Canonical | Duplicated in |
|---|---|---|
| 2.5 | `severity.DEFAULT_ZSCORE_THRESHOLD` | `layered.PEER_Z_THRESHOLD_DEFAULT`; `trends._TRENDS_CONFIG["zscore_threshold"]`; `confidence.py:477` `.get(...,2.5)`; `anomaly/zscore.py:85,152` `.get(...,2.5)`; `quality_alerts._alerts_config` fallbacks |
| 12 / 3 / 2 | `comparison_policy.*_DEFAULT` | `_alerts_config` docstring defaults, `resolve_comparison_policy` call without the trend window |
| 0.5 / 0.35 / 0.25 / 0.15 / 2.0 | `scoring.QUALITY_WEIGHT_DEFAULTS`, `OUTLIER_MULTIPLIER_DEFAULT` | `main.py` seed literals (acceptable: seed must be a literal) and `_as_float` fallbacks (acceptable: same module) |

The scoring module is the **good pattern** and should be the template: one
`QUALITY_WEIGHT_KEYS` map, one defaults map, one `resolve_scoring_config()`, one fingerprint, one
snapshot. Nothing else in the analysis path has that shape.

### 3.3 Inconsistent failure policy (silent defaults)

| Site | On config read failure |
|---|---|
| `severity.load_analysis_config` | raises `AnalysisConfigError` → pipeline aborts, alerts scan returns `{"configuration_error": True}` |
| `comparison_policy.load_comparison_policy` | `except Exception: pass` → **window silently 12** |
| `confidence.py` | `except Exception: pass` → **z threshold silently 2.5, cutoffs default** |
| `_alerts_config` | per-key `TypeError/ValueError` → per-key default, no record |

Two read paths refuse to run on unreadable config; two silently substitute defaults. A row produced
by the second pair is `LEGACY_UNKNOWN` by construction (D15 §6.4) and cannot be distinguished from a
row produced by an ordinary defaulted install.

### 3.4 The rule that keeps constants out of System Control

> A value becomes a System Control parameter **only** if a qualified operator could legitimately
> choose a different value tomorrow and the system would still be correct. A value is frozen in code
> when changing it would invalidate an approved clinical/statistical policy that other artefacts
> (D12 caps, `PEER-ELIGIBILITY-PROPOSAL.md`, the very-high gate) depend on.

By that rule: `MIN_PEERS_FOR_TOP_BAND = 4` stays frozen (the proposal document shows it refuses 346
otherwise-supported rows — a policy change, not a preference); `ZERO_SPREAD_LEVEL_CAP`,
`THIN_PEER_LEVEL_CAP` stay frozen (approved caps); `MAD_SCALE = 1.4826` is a mathematical identity;
`CV_MAX`, `MIN_IQR_POINTS`, `MIN_TREND_POINTS`, `RARE_EVENT_MEAN_MAX` are method-selection
thresholds whose change alters which *estimator* runs, not how strict it is.

A knob may be *added* later only by the same approval path that froze it, and it then appears in the
inventory in §2 — never as a magic number inside an engine.

---

## 4. The Configuration Resolver

### 4.1 Responsibilities (as required)

1. **Read the currently effective configuration** from System Control (`AppConfig` + `SystemSetting`)
   in **one** pass, and return a single immutable snapshot object.
2. **Normalise and validate** every parameter through the existing `SettingSpec` metadata
   (`severity.TREND_SETTING_SPECS`, the Z-score bounds, `_bounded_int` clamps) — the resolver must
   not invent a second set of bounds.
3. **Record provenance per parameter**: the value, the storage key it came from, whether it was
   `database` / `default` / `invalid` / `unavailable`, and the raw stored text when it could not be
   used.
4. **Resolve cross-parameter rules once**: the `min(alerts_history_window, trend_analysis_window)`
   history window, the monotonic slope-band ladder, the `max(2, …)` peer floor — computed in one
   place instead of re-derived by each consumer.
5. **Compute one digest** over the resolved snapshot (canonical JSON, sorted keys, full SHA-256) plus
   the component policy versions, so a result can name the exact configuration that produced it.
6. **Be reconstructible without the database**: the same pure function must accept a *stored*
   snapshot and return the same resolved values, which is what makes `REPRODUCIBLE` (D15 §6) a
   verifiable claim rather than a hope.

### 4.2 Shape (proposed)

```python
# app/engine/config_resolver.py  — pure except for the single loader

@dataclass(frozen=True)
class PolicySnapshot:
    values: Mapping[str, Any]        # every resolved parameter, flat keys
    sources: Mapping[str, str]       # key -> database | default | invalid | unavailable
    errors: Tuple[PolicyError, ...]  # key, raw value, reason, fallback used
    component_versions: Mapping[str, str]   # layered@, alerts@, comparison@, ...
    resolver_version: str
    digest: str                      # sha256 of canonical JSON of the above

def resolve_policy(raw_app_config: Mapping[str, Any],
                   raw_system_settings: Mapping[str, str],
                   *, strict: bool = True) -> PolicySnapshot: ...

def load_policy_snapshot(db, *, strict: bool = True) -> PolicySnapshot: ...
```

`strict=True` raises `PolicyUnavailable` (run paths: analysis, alerts scan, recalculation).
`strict=False` returns a snapshot whose affected keys are marked `unavailable` with their defaults
recorded as *assumed* (read/display paths: explain, dashboards, previews). **No path may silently
substitute a default and report nothing.**

### 4.3 Consumption contract (the part that is mandatory)

1. **Resolved once per run.** `run_analysis` / `scan_quality_alerts` call `load_policy_snapshot` once
   and pass the snapshot down as an explicit argument.
2. **No engine function reads configuration itself.** After this amendment, no module under
   `app/engine/anomaly/`, `app/engine/quality/`, `app/engine/quality_alerts.py` or
   `app/engine/confidence.py` may call `get_config_dict`, `SystemSetting` or
   `load_analysis_config`. They receive `PolicySnapshot`.
3. **No mutable module-level policy.** `set_trends_config`, `set_rules_config` and `_TRENDS_CONFIG`
   are removed from the analysis path. If a legacy caller needs them, they become an explicit
   per-call parameter with a deprecation shim that does not mutate global state.
4. **One resolved configuration per analysis run, shared by every layer.** Diagnostics, alerts,
   scoring, confidence and explain must all consume the *same* snapshot object — the amendment to
   D15 §4 adds the snapshot digest to the contract so a mismatch is detectable rather than
   theoretical.
5. **Every consumer keeps its current effective behaviour.** The resolver reproduces today's
   semantics exactly, including the asymmetries listed in §5 — it does not "fix" them silently.

### 4.4 What the resolver must NOT do

- It must not add, remove or retune a parameter.
- It must not move a value between tables (that is a separate, reversible migration decision, UD-A2).
- It must not round, clamp or coerce differently from the current loaders: `load_analysis_config`
  rounds Z to 2dp and clamps to 1.0–5.0; `_alerts_config` only rejects `<= 0`. A row scanned via
  alerts can therefore carry a Z of `0.5` where the severity path would report `1.0`. **The
  resolver must reproduce the reader it replaces, per plane, until UD-A1 is decided.**
- It must not hash the *storage* (key names, table) into the digest in a way that changes when a
  value is merely re-saved with the same meaning.

---

## 5. Recorded inconsistencies the resolver must preserve (not fix)

These are behaviour-preserving requirements, listed so a later implementer cannot mistake them for
bugs to clean up mid-amendment:

| # | Inconsistency | Where | Required resolver behaviour |
|---|---|---|---|
| I1 | Two clamp policies for one knob | `severity` clamps Z to [1,5]; `_alerts_config` only rejects `<=0`; `layered.gate_threshold` accepts any float | Reproduce per plane; report `zscore_threshold` as **two sources** (`severity`, `alerts`) in the snapshot until unified by approval |
| I2 | Two peer floors, one configurable | `min_peers` (config, ≥2) vs `MIN_PEERS_FOR_TOP_BAND = 4` (frozen) | Keep both; expose both in the snapshot with `configurable: true/false` |
| I3 | `_TRENDS_CONFIG` global survives between runs | `trends.py` | Resolver output must be identical whether or not a previous run configured the module |
| I4 | `load_comparison_policy` swallows read errors | `comparison_policy.py:169` | Replaced by snapshot; the failure becomes a recorded `unavailable` entry, not a silent 12 |
| I5 | `trend_analysis_window` in `SystemSetting`, siblings in `AppConfig` | §2.4 #17 vs #25–33 | Snapshot abstracts storage; `storage` field records which table each key came from, for the UI only |
| I6 | Z default stated 5× | §3.2 | Snapshot exposes exactly one canonical value; duplicates removed from the engine, constants kept only where a default is genuinely needed |

---

## 6. Effect on the D15 contract and versioning

Additions to the 37-field contract (D15 §4). No existing field changes meaning.

| Field | Group | Storage | Purpose |
|---|---|---|---|
| `config_resolver_version` | configuration | direct scalar | which resolver implementation resolved the snapshot |
| `config_snapshot_digest` | configuration | direct scalar (full SHA-256) | identity of the resolved values |
| `config_snapshot_ref` | configuration | reference to `analysis_runs` | the stored snapshot itself (by reference, not duplicated per row) |
| `config_unavailable_keys` | configuration | `result_provenance` JSON | keys that fell back to defaults, and why |

Versioning impact (D15 §5): `config@<semver>` joins the seven component versions, and the
`policy_registry` entry for each parameter records **definition** — key, storage plane, bounds,
default, and the rule that makes it configurable or frozen. The digest therefore changes when a
*meaning* changes, not when a value is saved.

`PARTIALLY_REPRODUCIBLE` gains a named cause: `config_snapshot_absent` (row predates snapshots) and
`config_key_duplicated` (row's plane cannot be identified).

---

## 7. Deliberately excluded from this amendment

- Migrating existing rows or adding the snapshot columns (P0/P1 of D15 §9; separate approval).
- Moving parameters between `AppConfig` and `SystemSetting` (UD-A2).
- Unifying the two Z clamp policies (UD-A1) — a behaviour change.
- Promoting any frozen constant to System Control (§3.4 forbids it without approval).
- The System Control UI beyond adding an `effective` / `source` display (D15 §8 already specifies
  bilingual labels).

---

## 8. Phases (all after the D15 P0–P1 approval already pending)

| Phase | Scope | Behaviour change | Risk |
|---|---|---|---|
| **A1** | Resolver + snapshot type; every existing loader wrapped, no consumer switched | none | low |
| **A2** | Pipeline and alerts scan consume one snapshot per run | none (parity-tested) | medium — `set_trends_config` removal |
| **A3** | Remove duplicate literals and the process-global setters; freeze list encoded in code | none | low |
| **A4** | Store snapshot digest/reference on new results (needs D15 P1) | new rows only | as D15 P1 |
| **A5** | System Control shows effective value + source + "assumed default" badges | UI only | low |

A1 is independently reviewable and reversible; A2 is the only phase that touches execution flow.

---

## 9. Testing strategy (planned, none executed)

16 scenarios already exist in D15 §11; this adds six:

1. **Parity** — for a fixture of stored configurations, `PolicySnapshot.values` equals what
   `load_analysis_config` + `_alerts_config` + `resolve_scoring_config` return today, key by key.
2. **No-global** — configure module global A, then resolve snapshot B; assert B's output does not
   depend on A (kills I3).
3. **Strictness** — unreadable config raises on run paths, and yields `unavailable` + recorded
   defaults on display paths; assert no path returns a default without recording it.
4. **One literal** — a source scan asserts `2.5` appears exactly once as a Z default (in
   `severity.py`) plus the seed; same for 12/3/2 and the weight defaults.
5. **Digest stability** — same resolved values in a different row order or storage plane produce the
   same digest; a changed enum produces a different one.
6. **Frozen constants** — `MIN_PEERS_FOR_TOP_BAND == 4`, both caps `HIGH`, %-change cap tuple
   unchanged; a resolver missing any of them in its snapshot fails the test.
7. **Reconstruction** — resolve, store the snapshot, resolve *from the stored snapshot*, and assert
   identical values and digest.

---

## 10. Risks

| # | Risk | Mitigation |
|---|---|---|
| AR1 | Parity failure silently shifts severities | Phase A1 ships the resolver **beside** the loaders; A2 switches only after parity tests pass; no value changes in the same phase |
| AR2 | Removing `set_trends_config` breaks a caller not found by grep | Deprecation shim in A2, removal in A3 after a run with shim warnings |
| AR3 | Digest churn makes every historical row look stale | Digest covers meaning, not storage; versions are appended to `policy_registry`, never edited |
| AR4 | Resolver becomes a second source of truth (its own defaults) | Bounds/defaults/examples must come from existing `SettingSpec`/`DEFAULT_*`; test #4 enforces one literal |
| AR5 | Snapshot is large and copied per row | Store once per run (`analysis_runs`), reference from rows; only the digest is a scalar |
| AR6 | Perf: one extra read pass per run | One pass replaces the 3–4 current reads per run; expected net improvement, must be measured (not claimed) |
| AR7 | Operator expects "System Control is authoritative" to mean every constant is editable | §3.4 rule published in the UI help text: frozen constants are listed read-only with the reason |

---

## 11. Unresolved decisions

| # | Decision | Options | Recommendation |
|---|---|---|---|
| UD-A1 | Unify the two Z clamp policies? | (a) keep per-plane, record both (b) single [1,5] everywhere | (a) now, (b) only with an explicit behaviour-change approval |
| UD-A2 | Consolidate trend keys into one table? | (a) leave split, abstract it (b) migrate `SystemSetting`→`AppConfig` (needs text/int anywhere) | (a); storage is an implementation detail the resolver hides |
| UD-A3 | Does the snapshot digest replace `scoring_fingerprint` / `policy_fingerprint`? | (a) add alongside (b) replace | (a) in D15, replacement only after a dual-written period |
| UD-A4 | Should `comparison_policy.COMPARISON_POLICY_VERSION` become a registry entry? | (a) yes, as a component version (b) keep the constant | (a) — it is exactly the hand-edited constant D15 §5 rejects |
| UD-A5 | Frozen constants in the snapshot? | (a) include with `configurable:false` (b) exclude | (a): a result then records which frozen policy judged it, at zero config cost |
| UD-A6 | Strictness of `explain` | (a) tolerant + labelled (b) strict | (a); explain must render legacy rows, but must say a default was assumed |

---

## 12. Status

Design only. No code, schema, migration, data, config, threshold, formula, severity, peer policy or
scoring weight was changed; no test was executed; no server was started; no database connection was
opened. Every statement about stored configuration above is derived from source (seed list, model
columns, loaders), not from a query.

The single mandatory architectural conclusion:

> **One resolver, one snapshot per analysis run, one canonical value per parameter, and a digest that
> names the configuration a result was produced under.** System Control remains the only place an
> operator changes policy; the engine consumes resolved configuration and holds no competing value.
