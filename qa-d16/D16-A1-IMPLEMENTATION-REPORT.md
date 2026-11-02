# D16-A1 — Implementation Report: Central Configuration Resolver

**Increment:** A1 only — resolver built alongside the existing loaders
**Base:** `very-high-gate-integration` @ `4b82b19` (unchanged)
**Status:** A1 complete; **no consumer migrated**; A2–A5 not started
**Test outcome:** 104 passed, 0 failed, 0 skipped (exit 0)

---

## 1. Deliverables

| # | Deliverable | Path | State |
|---|---|---|---|
| 1 | Resolver implementation | `app/engine/config_resolver.py` | new, untracked |
| 2 | Focused tests (14) | `tests/test_config_resolver.py` | new, untracked |
| 3 | This report | `qa-d16/D16-A1-IMPLEMENTATION-REPORT.md` | new, untracked |
| 4 | Parity results | §5 below | measured |
| 5 | Scope manifest | §7 below | measured |
| 6 | Risks + A2 prerequisites | §8–§9 | recorded |

No existing file was modified. `git diff --name-only` is still **65 files**, identical to
the pre-task baseline, and the two new source files are the only additions on the code side.

---

## 2. What was implemented

`app/engine/config_resolver.py` (727 lines) provides:

- **`PolicySnapshot`** — frozen dataclass; `entries` and `frozen_constants` are
  `MappingProxyType`, so neither the snapshot nor the mappings can be mutated. `values` returns a
  plain dict **copy**, so a caller cannot write back through it.
- **`resolve_policy(app_config, system_settings, *, strict=True, read_error=None)`** — pure: no
  session, no I/O, no module state. Resolves every consumed parameter from the two raw
  `{key: value}` mappings.
- **`load_policy_snapshot(db, *, strict=True)`** — the only DB-aware function: one read of
  `app_config`, one read of `system_settings`, then delegation to `resolve_policy`. Nothing else in
  the module touches a session.
- **Per-key provenance** — `PolicyEntry(key, value, source, component, configurable,
  fallback_applied, validation, storage)` with `source ∈ {database, default, invalid,
  unavailable}` and `storage ∈ {app_config, system_settings, code}`. Frozen constants carry
  `configurable=False` and never appear in `values`.
- **Error tracking** — `PolicyError(key, raw, reason, fallback)` per rejected value, plus
  `invalid_keys` / `unavailable_keys` views.
- **Component version metadata** — `component_versions()`: the real
  `COMPARISON_POLICY_VERSION` (`2026-10-24.1`) plus every still-unversioned plane marked
  `"unversioned"` rather than given an invented semver (D15 §5).
- **Deterministic canonical serialization** — `canonical_json()`: sorted keys, compact separators,
  numbers normalised to float, frozen constants included; **full 64-hex SHA-256** `digest`.
- **Strictness split** — `strict=True` raises `PolicyUnavailable` on an unreadable store (run
  paths); `strict=False` returns a snapshot with every key marked `unavailable`, its documented
  default retained, and the read error recorded (display paths). Invalid *individual* values never
  raise — they are reported per key, exactly as `resolve_trend_settings` already does.

Reuse rather than restatement: `severity.TREND_SETTING_SPECS` / `coerce_setting` /
`resolve_trend_settings` / `default_trend_bands` / `ZSCORE_MIN|MAX` /
`DEFAULT_ZSCORE_THRESHOLD`, `comparison_policy.resolve_comparison_policy` /
`COMPARISON_POLICY_VERSION`, `scoring.resolve_scoring_config` / `QUALITY_WEIGHT_KEYS` /
`SEVERITY_WEIGHT_KEYS` / `OUTLIER_MULTIPLIER_KEY`, and the frozen constants are read from
`anomaly.layered` (lazily, to avoid an import cycle). **No default, bound or example is restated** in
the new module.

---

## 3. Behaviour preserved per plane

| Plane | Reproduced behaviour | Verification |
|---|---|---|
| `severity` | Z clamped to [1.0, 5.0], rounded 2dp, `database`/`default`/`invalid` | parity + clamp tests |
| `alerts` | Z only rejects non-numeric/`<=0`, **no upper clamp**; per-key defaults | parity + distinct-clamp tests |
| `alerts.history_window` | resolved **without** the trend window (the scan's pre-policy value) | parity test |
| `comparison` | `min(alert window, trend window)` + clamped min-observations / min-peers | parity + cross-table test |
| `trend` | 11 spec controls + 4 slope bands, two storage tables, monotonic band ladder | parity + cross-table test |
| `scoring` | 4 weights + multiplier + 4 severity weights via `resolve_scoring_config` | parity test |
| `confidence` | raw `thresholds` cutoffs + raw Z, no clamping/rounding | parity test |
| `frozen` | 11 constants as metadata, `configurable=False` | frozen-constant test |

Two documented deviations, both where the current code would **raise** rather than return a value:
an unreadable `confidence` cutoff, or a non-numeric `confidence` Z, is recorded as `invalid` with
the documented default instead of propagating an exception. Nothing else deviates.

The two Z clamp policies remain **distinct by test**: a stored `99` resolves to `5.0` on the severity
plane and `99.0` on the alerts plane; a stored `0.5` resolves to `1.0` and `0.5`. This is the
amendment's I1 preserved, not "fixed".

---

## 4. What A1 deliberately did not do

- `severity.load_analysis_config`, `comparison_policy.load_comparison_policy`,
  `quality_alerts._alerts_config`, `resolve_scoring_config`, all `get_config_dict` consumers: unchanged.
- `trends.set_trends_config` and `_TRENDS_CONFIG`: unchanged (asserted by test).
- No production module imports the resolver: `grep -rn "config_resolver" app/ --include=*.py`
  returns **no matches outside the module itself**, asserted by
  `test_no_consumer_is_migrated_in_a1`.
- No default, threshold, cutoff, weight, formula, cap, gate or peer policy changed.
- `zscore_threshold` remains 2.5 wherever it was 2.5.

---

## 5. Parity results (measured)

Command (exit status preserved):

```
.venv/Scripts/python.exe -m pytest tests/test_config_resolver.py tests/test_severity_trends.py \
  tests/test_comparison_policy.py tests/test_api_config.py tests/test_dashboard_analysis_ux.py \
  -q -p no:warnings --tb=short
```

```
104 passed in 106.55s (0:01:46)
EXIT=0
```

Breakdown: 14 new A1 tests + 90 existing tests across four configuration suites, **0 failed,
0 skipped**.

The 14 new tests, all passing:

| # | Test | Requirement covered |
|---|---|---|
| 1 | `test_resolver_values_match_existing_loader_outputs` | resolver parity with all five loaders on one populated config |
| 2 | `test_missing_configuration_reproduces_documented_defaults` | legacy/default behaviour with zero rows |
| 3 | `test_configured_zscore_threshold_is_unchanged` | Z value preserved (2.5 → 2.5, 3.0 → 3.0) |
| 4 | `test_both_zscore_clamp_policies_remain_distinct` | the two clamp policies stay distinct (99 / 0.5 / 0) |
| 5 | `test_peer_minimums_are_unchanged` | configurable floor clamps, frozen `MIN_PEERS_FOR_TOP_BAND=4` untouched |
| 6 | `test_trend_settings_resolve_across_both_storage_tables` | both tables + per-key storage plane + shared window |
| 7 | `test_invalid_values_are_explicitly_reported` | invalid value → `invalid` source, default value, error, loader agreement |
| 8 | `test_snapshot_is_immutable` | frozen dataclass, read-only mapping, `values` copy |
| 9 | `test_two_snapshots_from_different_configs_do_not_overwrite_each_other` | snapshot independence |
| 10 | `test_fingerprint_is_deterministic` | same config → same 64-hex digest twice |
| 11 | `test_different_configuration_produces_a_different_fingerprint` | 2.5 vs 2.6 → different digest |
| 12 | `test_fingerprint_ignores_input_key_ordering` | reversed insertion order → same digest |
| 13 | `test_unreadable_configuration_raises_when_strict_and_is_labelled_otherwise` | strict raise vs `unavailable` + defaults |
| 14 | `test_no_consumer_is_migrated_in_a1` | pipeline free of the resolver; legacy loaders/setter intact |

One defect was found and fixed **by the parity test itself** during development: the alerts
`min_score` was recorded under its raw key instead of the namespaced `alerts.min_score`. That is
exactly the drift the parity test exists to catch; no production code was involved.

---

## 6. Database, migrations, server

- **No production database connection was opened by this task.** Every test used the `db_session`
  fixture, which builds a **file-backed SQLite database in a temporary directory**
  (`tempfile.mkdtemp(prefix="healthai_test_db_")`) and is disposed at teardown. No test touches
  Postgres.
- **No writes to any real store**: no `AppConfig` or `SystemSetting` row was created, updated or
  deleted outside those temporary SQLite files.
- **No migration was run and none was created**: `git status --porcelain alembic/` shows zero
  modified files.
- **No server started**: nothing is listening on 8000 / 3000 / 5173 / 8501.
- **No commit, stage, stash, reset or branch switch**: 0 staged, 2 stashes (unchanged), HEAD
  `4b82b19`.

---

## 7. Scope manifest

| Classification | Path | Evidence |
|---|---|---|
| **D16-A1 artifact** | `app/engine/config_resolver.py` | created this task, untracked |
| **D16-A1 artifact** | `tests/test_config_resolver.py` | created this task, untracked |
| **D16-A1 artifact** | `qa-d16/D16-A1-IMPLEMENTATION-REPORT.md` | created this task, untracked |
| **D15 artifact (pre-existing)** | `qa-d15/*.md` | created in the previous task, untracked |
| **Pre-existing modification** | 65 tracked files (`app/api/*`, `app/engine/*`, `static/*`, `tests/*`) | present in the baseline; **none touched by this task** |

Working-tree counts: baseline **137** porcelain entries → now **141** = 137 + `qa-d15/` +
`config_resolver.py` + `test_config_resolver.py` + `qa-d16/`. Tracked modifications stay at **65**;
the delta is untracked additions only.

---

## 8. Remaining risks

| # | Risk | Status / mitigation |
|---|---|---|
| AR1 | Parity drifts as loaders evolve | Parity tests pin the mapping; A2 must re-run them before switching any consumer |
| AR2 | Resolver's `confidence` plane deviates on unreadable values (defaults instead of raising) | Documented; only reachable where current code would crash |
| AR3 | Digest includes frozen constants, so a code change alters every new digest | Intended: a frozen-policy change *is* a configuration change; historical digests are never rewritten |
| AR4 | `alerts` plane resolves `history_window` twice (pre-policy and comparison) | Both are recorded; this mirrors the current two-stage behaviour and must persist in A2 |
| AR5 | `component_versions` marks six planes `unversioned` | Honest, not invented; D15 §5 versioning work (P0) supplies real versions later |
| AR6 | Resolver reads **all** `app_config` rows (one query) instead of three category reads | Behaviourally equivalent (keys are globally unique); one query is cheaper — not yet measured against the old path |
| AR7 | A caller could treat `values` as authoritative for frozen constants | They live in a separate `frozen_constants` mapping, `configurable=False`, absent from `values` |

---

## 9. A2 prerequisites (not started)

1. **Explicit snapshot hand-off** — `run_analysis` and `scan_quality_alerts` call
   `load_policy_snapshot(db)` once and pass the object down; no engine function may read config
   itself afterwards.
2. **Global removal plan** — `set_trends_config` / `_TRENDS_CONFIG` replaced by an explicit
   per-call parameter, with a deprecation shim that logs every caller for one full run before
   removal.
3. **Two-stage alerts window** — A2 must preserve `alerts.history_window` (pre-policy) and
   `comparison.history_window` (policy) as distinct values, or the alert scan's effective window
   changes.
4. **Strictness policy per entry point** — analysis/scan/recalc strict; explain/dashboard/preview
   tolerant and labelled. Enumerate the call sites before switching any of them.
5. **Re-run this parity suite plus the broader configuration and pipeline suites**; a single
   severity or score delta blocks A2.
6. **Approval** — A2, A3, A4 and A5 each require explicit approval; this report ends A1.

---

## 10. Status statement

A1 is complete and verified by tests, not by compilation alone: 104 tests passed with exit 0,
including all 14 new parity/immutability/determinism tests. No production consumer was migrated, no
existing loader or default was changed, no policy value moved, no migration ran, no server started,
and no real database was read or written. **Stopped after A1 as instructed; awaiting approval before
A2.**
