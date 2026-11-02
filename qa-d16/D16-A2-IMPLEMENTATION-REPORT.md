# D16-A2 — Implementation Report: Explicit PolicySnapshot Integration

**Increment:** A2 only — controlled consumer migration, behaviour preserved
**Base:** `very-high-gate-integration` @ `4b82b19` (unchanged)
**Status:** A2 complete; A3/A4/A5 not started
**Result:** 281 passed, 0 failed, 0 skipped (exit 0); baseline 231/231 still green

---

## 1. What changed, precisely

| File | Change | Tracked state |
|---|---|---|
| `app/engine/policy_view.py` | **new** — snapshot → consumer shapes (AnalysisConfig, alerts dict, ComparisonPolicy) | untracked |
| `app/engine/pipeline.py` | one snapshot resolved at the run entry point; passed to the analysis and to the alerts auto-scan; trends/anomaly config derived from it | pre-existing modification, extended (190/35 includes the pre-task edits) |
| `app/engine/quality_alerts.py` | `scan()` / `scan_all_months()` accept a snapshot and build both config stages from it; no `_alerts_config` or `load_analysis_config` call | pre-existing modification, extended (997/67 includes the pre-task edits) |
| `app/engine/anomaly/trends.py` | `set_trends_config` kept, documented as deprecated, warns once and every 100th call, call counter added | **newly modified** (27/0) |
| `tests/test_policy_snapshot_integration.py` | **new** — 13 integration proofs | untracked |
| `tests/test_config_resolver.py` | one A1 guard amended (§7) — its "no consumer migrated" premise is exactly what A2 approves | A1 artifact (untracked), amended |

No other tracked file was touched: `git diff --name-only` is **66** files against the
**65** pre-task baseline, and the single delta is `app/engine/anomaly/trends.py` (27
insertions, shim only — verified with `git diff --stat`).

---

## 2. Consumer migration matrix

| Consumer | Before A2 | After A2 | Migrated? |
|---|---|---|---|
| `pipeline.run_full_analysis` | — | resolves **one** `PolicySnapshot` at entry | **yes** |
| `pipeline._compute_full_analysis` | `severity.load_analysis_config(session)` + `get_config_dict("trends")` | `analysis_config_from_snapshot(policy)` | **yes** |
| `pipeline._maybe_auto_scan_quality_alerts` | `quality_alerts.scan(session, month)` | `scan(..., policy=policy)` — same object | **yes** |
| `quality_alerts.scan` | `_alerts_config(db)` + `load_analysis_config(db)` + `resolve_comparison_policy(get_config_dict("alerts"), …)` | `alerts_config_from_snapshot` + `analysis_config_from_snapshot` + `comparison_policy_from_snapshot` | **yes** |
| `quality_alerts.scan_all_months` | one config read **per month** | one snapshot for the whole backfill | **yes** |
| `severity.load_analysis_config` | used by the two above | unchanged; still the loader for display paths | no (A3) |
| `comparison_policy.load_comparison_policy` | used by explain/config screens | unchanged | no (A3) |
| `quality_alerts._alerts_config` | used by `scan` | retained, now **no production caller** (tests only) | no (A3 removal) |
| `api/analysis.py`, `api/file_ops.py`, `audit/explain.py` | `load_analysis_config(db).trend_engine_config()` | unchanged — display/explain paths | no (A3) |
| `api/config_api.py` (PUT) | writes System Control | unchanged | no — correct |
| `pipeline` rules / rates / ml / quality categories | `get_config_dict` | unchanged — **outside the resolver's authority** | no (A3 candidate) |

### The five trend keys that are still read (and why)

`trend_r_squared`, `trend_finding_slope`, `trend_finding_deviation`, `trend_finding_cv`,
`trend_finding_r_squared` live in the `trends` category but are **not** in
`TREND_SETTING_SPECS`, so A1 does not resolve them. They are consumed by
`analyze_historical_trends` (`raw["trend_finding_*"]`). The pipeline therefore still reads
that ONE category **at the entry point** and applies the snapshot last, so every setting the
resolver owns overrides it and the two sources cannot disagree inside a run. Dropping the
read would silently change `_TRENDS_CONFIG` content for legacy callers, so it stays until
those five keys are resolved (A3 prerequisite 2).

---

## 3. Behaviour preserved

| Invariant | How it is held |
|---|---|
| `zscore_threshold = 2.5` untouched | resolver defaults unchanged; `analysis_config_from_snapshot` reads `severity.zscore_threshold` verbatim (clamped by the resolver, not re-clamped) |
| Alerts two-stage window | stage 1 = `alerts.history_window` (alert window only); stage 2 = `comparison.history_window` (`min(alert, trend)`). Both remain distinct snapshot entries; only the scan-local dict is overwritten, exactly as before |
| Alerts plane Z still unclamped | `alerts_config_from_snapshot` reads `alerts.z_threshold`; the scan then applies the severity Z **as it always did** |
| Persisted alert fingerprint unchanged | `policy_fingerprint(view) == policy_fingerprint(load_analysis_config(db))` asserted — so existing rows are **not** re-labelled "stale" by the migration |
| Severity policy, bands, escalation | identical `TrendSettings` values and identical monotonic band ladder (parity test compares `dict(view.trend_bands)` to the loader's) |
| Frozen constants | untouched; no cap, gate, weight or peer policy edited |
| Legacy fallbacks | defaults resolve identically with zero rows (test) |

---

## 4. Strictness policy per entry point

| Entry point | Store unreadable | Invalid single value |
|---|---|---|
| `run_full_analysis` / `_compute_full_analysis` | `PolicyUnavailable` → existing fallback quality report (`Analysis failed during report generation`), as before | `invalid` entry + documented fallback, run continues |
| **cached** report | snapshot is not required: read failure is swallowed at entry and the cached result renders (unchanged pre-A2 behaviour) | n/a |
| `quality_alerts.scan` | `PolicyUnavailable` → `{"error": …, "configuration_error": True}` (unchanged contract) | warning naming every fallback key; scan continues |
| `scan_all_months` | logged; each month reports `configuration_error` | same warning per scan |
| Display/explain paths | unchanged legacy loaders | unchanged |

Falls back **visibly**: `policy.invalid_keys` is logged with the affected keys in both the
analysis and the scan, and `snapshot_provenance()` exposes digest, resolver version,
component versions and both key lists.

---

## 5. Trend global state

`set_trends_config` / `_TRENDS_CONFIG` are kept (A2 does not remove them):

* `set_trends_config` now logs `set_trends_config() is deprecated (D16-A2) …` on the first
  call and every 100th, with a process-wide counter (`_SET_TRENDS_CONFIG_CALLS`), so any
  remaining caller is visible in the logs instead of being found later by a wrong number.
* Update semantics are unchanged.
* **Callers (setters):** exactly one — `pipeline._compute_full_analysis`. No other module in
  `app/` calls it.
* **Readers:** `analyze_historical_trends` via `_resolved_settings` / `_resolved_bands`; every
  in-app call site (`api/analysis.py`, `api/file_ops.py`, `audit/explain.py`) already passes
  `analysis_config.trend_engine_config()`. With a complete config the global cannot decide a
  value — asserted for interleaved runs with a deliberately poisoned global (window 3,
  stable band 99) against snapshots asking for 12 and 4.

---

## 6. Tests and exact counts

Baseline was measured **before** any A2 edit, then the same commands were re-run.

| Command (all: `-q -p no:warnings`) | Before | After |
|---|---|---|
| `pytest tests/test_pipeline.py tests/test_quality_score.py tests/test_quality_alerts_canonical.py` | 53 passed | **53 passed** |
| `pytest tests/test_quality_alerts_api.py` | (inside the 178 block) | **73 passed** |
| `pytest tests/test_quality_score_provenance.py tests/test_severity_consistency.py tests/test_severity_trends.py tests/test_comparison_policy.py tests/test_audit_quality_breakdown.py tests/test_config_resolver.py` | (inside the 178 block) | **105 passed** |
| → 178-test baseline block total | **178 passed** | **178 passed** |
| `pytest tests/test_dashboard_analysis_ux.py tests/test_api_config.py` | not in baseline set | **37 passed** |
| `pytest tests/test_policy_snapshot_integration.py` (new) | — | **13 passed** |
| `pytest tests/test_config_resolver.py tests/test_policy_snapshot_integration.py` | — | **27 passed** |

Every command exited **0**; no test was skipped or deselected anywhere.

### The 13 new proofs → required evidence

| Requirement | Test |
|---|---|
| 1. one snapshot shared throughout a run | `test_full_analysis_resolves_exactly_one_snapshot` (counts resolutions = 1) |
| 1b. the scan gets *that* object | `test_alerts_auto_scan_receives_the_same_snapshot` (`is` identity) |
| 2. no downstream configuration reload | `test_run_does_not_reload_configuration_downstream` (`load_analysis_config`, `_alerts_config`, `load_policy_snapshot` all raise if touched) |
| 3. interleaved runs cannot contaminate trend settings | `test_interleaved_runs_cannot_contaminate_trend_settings` |
| 4. alerts keeps its two-stage window | `test_alerts_keeps_its_two_stage_history_window`, `test_scan_consumes_the_supplied_snapshot_without_reloading` |
| 5. loader parity intact | `test_snapshot_views_match_the_existing_loaders` (values, bands, engine config, fingerprint) |
| 6. alert values/severity unchanged | same test: identical `policy_fingerprint` ⇒ identical severity inputs |
| 7. layered results unchanged | `tests/test_pipeline.py`, `test_layered_*` suites (231-test baseline) |
| 8. diagnostics/explain consistent | `test_audit_quality_breakdown.py`, `test_dashboard_analysis_ux.py` |
| 9. Quality Score unchanged | `test_quality_score.py`, `test_quality_score_provenance.py` |
| 10. legacy fallback unchanged | `test_defaults_are_unchanged_when_nothing_is_configured` |
| 11. no unapproved migration | `test_only_the_two_run_entry_points_consume_the_snapshot`, `test_public_entry_points_stay_backwards_compatible` |
| strictness | `test_scan_reports_an_unreadable_configuration`, `test_analysis_reports_an_unreadable_configuration` |
| shim is labelled, not silent | `test_trend_global_setter_warns_but_still_works` |

---

## 7. Amendments to earlier artifacts

**One** A1 test was amended, and only because its premise is what A2 approves:
`tests/test_config_resolver.py::test_no_consumer_is_migrated_in_a1` asserted
`"config_resolver" not in inspect.getsource(pipeline)`. It is now
`test_migration_is_limited_to_the_two_run_entry_points`, which is **stricter in scope**: the
resolver must appear in exactly `pipeline` and `quality_alerts`, must **not** appear in
`api/analysis.py` or `audit/explain.py`, and every legacy loader plus the compatibility
setter must still exist. No other A1 test was changed; all 14 still pass.

---

## 8. Before/after parity — what was measured, and what was not

Measured:

* **231/231 baseline tests pass unchanged** (53 + 178), exit 0, across pipeline, layered,
  quality-score, alerts API, severity, comparison, audit and dashboard suites.
* **Byte-identical severity fingerprint** from the snapshot view and the legacy loader over
  the same rows — the value stored in every alert's `evidence.severity_policy.fingerprint`.
* **Identical alerts config** for all seven keys (`min_score`, `min_peers`, `min_history`,
  `history_window`, `ml_enabled`, `ml_min_samples`, `z_threshold`) versus `_alerts_config`.
* **Identical comparison policy** (`as_dict()` equality with `load_comparison_policy`),
  including the version string `2026-10-24.1`.
* **Distinct window planes**: 12 (alerts) vs 6 (comparison) from the same snapshot.

Not measured, and not claimed: corpus-level counts of alerts, severity distributions, gate
decisions or Quality Scores against production data. **No production database was read**;
producing those numbers would require opening it, which this task does not authorize. Because
the fingerprint and every policy input are provably identical, a corpus diff would be
explained by data, not policy — but that is an inference, not a measurement.

---

## 9. Scope manifest

| Classification | Path | Evidence |
|---|---|---|
| A2 artifact (new) | `app/engine/policy_view.py` | untracked |
| A2 artifact (new) | `tests/test_policy_snapshot_integration.py` | untracked |
| A2 artifact (new) | `qa-d16/D16-A2-IMPLEMENTATION-REPORT.md` | untracked |
| A2 edit | `app/engine/pipeline.py` | pre-existing modification extended |
| A2 edit | `app/engine/quality_alerts.py` | pre-existing modification extended |
| A2 edit | `app/engine/anomaly/trends.py` | **newly modified**, 27 insertions (shim) |
| A2 edit | `tests/test_config_resolver.py` | one guard amended (§7) |
| A1 artifacts, untouched | `app/engine/config_resolver.py`, `qa-d16/D16-A1-*.md` | unchanged |
| Pre-existing | remaining 63 tracked modifications, other untracked files | present before A2 |

HEAD `4b82b19`; **0 staged**, 2 stashes, no branch change, no commit, no reset.

### Environment

* No migration was created or run: `git diff --name-only alembic/` is empty (0 tracked
  changes). The 5 entries under `alembic/versions/` are pre-existing **untracked** scratch
  migrations that were already there before A2; none was opened, edited or executed here.
* No server started; nothing listens on 8000/3000/5173/8501.
* No production database connection; every test used the file-backed SQLite `db_session`
  fixture (temp directory, disposed at teardown).
* No System Control value written: the only `AppConfig`/`SystemSetting` inserts happen inside
  those temporary SQLite files, in the test file itself.

---

## 10. Remaining legacy global state and callers

| Item | Remaining caller | Risk |
|---|---|---|
| `set_trends_config` | `pipeline._compute_full_analysis` only | low — every analysis overwrites it with snapshot-derived values and warns |
| `_TRENDS_CONFIG` as a *source* | argument-less `analyze_historical_trends` only | low — no in-app caller is argument-less |
| `_alerts_config` | none in production (tests only) | dead code, kept deliberately for A2 |
| `severity.load_analysis_config` | `api/analysis.py`, `api/file_ops.py`, `audit/explain.py`, `comparison_policy.load_comparison_policy`, config screens | medium — display paths can still disagree with a run's snapshot until A3 |

---

## 11. A3 prerequisites (not started)

1. Delete `set_trends_config` / `_TRENDS_CONFIG` after a run in which the shim logged **zero**
   calls (the counter is the gate), and prove every in-app call passes an explicit config.
2. Resolve the five legacy trend gates (`trend_r_squared`, `trend_finding_slope`,
   `trend_finding_deviation`, `trend_finding_cv`, `trend_finding_r_squared`) so the `trends`
   category read in the pipeline can be removed.
3. Migrate display/explain paths to the snapshot (or to a labelled tolerant snapshot) and
   delete `_alerts_config`.
4. Decide the cached-path cost: resolution currently happens before the cache check (2 small
   SELECTs on a cached report) so the snapshot can be shared with the auto-scan. Moving it
   after the cache check needs a way to hand the snapshot out of `_compute_full_analysis`.
5. Persist the snapshot digest next to analysis/alerts rows (new provenance field) so a stored
   result can name the exact configuration, not only the severity fingerprint.
6. Remove or scope `quality_alerts._alerts_config`, and migrate `rules`/`rates`/`ml`/`quality`
   categories into the resolver if they are to become snapshot-owned.

---

## 12. Status statement

A2 is complete and verified by execution, not inspection alone: 281 tests pass (0 failed,
0 skipped), including 13 new integration proofs and the full 231-test baseline measured before
the change. One configuration is resolved per run and shared with the alerts auto-scan; no
participating component re-reads System Control; the alerts two-stage window, the distinct Z
clamp policies, the trend bands and the persisted severity fingerprint are all provably
unchanged; the trend global survives only as a warning-emitting compatibility shim with a
single caller. **Stopped after A2; A3–A5 await approval.**
