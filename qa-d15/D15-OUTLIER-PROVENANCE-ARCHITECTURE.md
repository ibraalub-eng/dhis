# D15 — Outlier Provenance Architecture (Design Only)

**Project:** Health AI – SRMNH Data Quality System
**Date:** 2026-11-02
**Phase:** Design and investigation only — **no code, schema, data or configuration was changed**
**Branch / HEAD:** `very-high-gate-integration` / `4b82b19388f0b8568ca8c33c62a9b5f7aa60daac`
**Working tree:** 65 modified tracked files, 72 untracked entries, 0 staged, 2 stashes (all pre-existing)
**Primary evidence:** `qa-d14/D14-HISTORICAL-PROVENANCE-AUDIT.md`, plus inspection of the working-tree implementation
**Appendix (Deliverables B, C, D):** `qa-d15/D15-APPENDICES-B-C-D.md`

---

## 1. Executive summary

The system already records **more provenance than D14 credited it with**, but it records it **inconsistently, unversioned, and destructively**.

Three facts shape the whole design:

1. **What exists is good but partial.** Every layered result stores its exact history window (`history_provenance`), its peer group ids and values (`peer_provenance`) and its cap decisions (`classification_provenance`). Every alert stores its threshold, statistics, history series, peer ids, severity resolution and policy fingerprint. This is enough to reproduce 70.7% of alerts and 55.7% of layered results in-memory with no schema change (D14 §C).
2. **Nothing identifies the code that produced a row.** There is no engine version anywhere in the system, `COMPARISON_POLICY_VERSION` is a hand-edited string constant stamped on every row, and the caps/gate that the latest results were produced under exist **only in the uncommitted working tree**.
3. **Historical results are destroyed by recomputation.** `_save_layered_results` deletes every row for hospital+month and reinserts; `_upsert_alert` updates rows in place keeping the original `detected_at`. Only `QualityScore` keeps a revision trail. So "the original result" survives today only because nobody has rescanned — not because the architecture preserves it.

The proposed architecture therefore does four things and nothing more:

- **Identifies** each result with engine + policy versions and a run id (`analysis_runs` + per-result scalars);
- **Preserves** the original result when a row is recomputed (append-only revisions, mirroring the existing `quality_score_revisions` precedent);
- **Classifies** reproducibility at read time with a formal status (`app/engine/provenance.py`, pure functions);
- **Never rewrites history** — all new fields nullable, all classifications explicit, no backfill, no reinterpretation.

Versioning: **seven independent component versions**, not one global version, each `name@semver` plus a SHA-256 definition digest held in an immutable `policy_registry` table.

---

## 2. Current-state findings

### 2.1 What each result type records today

| Result type | Storage | Stored provenance (verified in code) | Derived at read time | Missing |
|---|---|---|---|---|
| **Quality Alerts** | `quality_alerts` | `severity`, `score`, `method`, `current_value`, `baseline_value`, `deviation_pct`, `z_score`, `peer_count`, `direction`, `interpretation`, `confidence`, `reason`, `detected_at`; `evidence` JSON with `z_threshold`, `min_score`, `stats`, `peer_ids[:50]`, `history`, `comparison_policy`, `canonical`, `base_severity`, `trend_assessment`, `final_severity`, `severity_policy.fingerprint`, `dispersion`, `thin_peer_group`, `pct_change_cap`, `numerator`/`denominator`; registry identity columns `indicator_code`, `indicator_name`, `unit`, `formula`, `formula_version` | Effective band (`effective_severity` + gate), z provenance, zero-spread flag, thin-peer flag, comparison identity hash, issue key | Engine version; run id; policy version on 25.5% of rows; `unit`/`formula` on 74.4%; **why the method was chosen**; raw vs capped score as separate values; preservation of the previous version of an updated row |
| **Layered results** | `layered_outlier_results` | Five layer scores + band + type + method + interpretation; `history_provenance` (`policy_version`, `window`, `min_observations`, `months`, `values`, `skipped_months`); `peer_provenance` (`policy_version`, `group`, `month`, `min_peers`, `scored_peer_count`, `eligible_count`, `peer_ids`, `values`); `classification_provenance` (`policy_version`, `zscore_threshold`, `zero_spread_layers`, `thin_peer_layers`, `min_peers_for_top_band`, `level_from_layers`, `level`, `cap`) | Displayed level (`effective_row_level`), capped layers for legacy rows (`row_capped_layers`), layer bands (`row_layer_bands`) | Engine version; run id; `zscore_threshold` on 98% of rows; gate decision (gate is read-time by design); **the previous version of the row is deleted, not archived** |
| **Diagnostics** | projection over `layered_outlier_results` | Nothing of its own | Recomputes caps, bands and the gate per request (`app/engine/anomaly/layered.py`, `projection.py`) | Any stored statement of what the screen showed |
| **Explain** | projection over layered rows + alert evidence | Nothing of its own | Recomputes classification, re-applies caps, reports `classification_provenance`, `stored` vs `displayed_outlier_level` | Engine/policy version of the row it explains |
| **Dashboard** | projection over alerts/layered/scores | Nothing of its own | `effective_severity` fold, `stored_threshold` fallback to 2.5, severity-policy drift count by fingerprint | Provenance status of the rows behind a KPI |
| **Reports** | projection over layered rows | Nothing of its own | `effective_row_level`, registry `anomaly_provenance` (formula status) | The **stored** band (reports carry only the policy band) |
| **Quality Scores** | `quality_scores` + `quality_score_revisions` | `score`, four components, `issues`, `scoring_fingerprint` (SHA-256, 16 hex), `scoring_config` (full resolved dict); revisions carry previous/new values, fingerprints and config | Component state (`current`/`previous_configuration`/`other_configuration`/`unknown`) from the stored fingerprint | Engine version; run id; a *named* scoring policy version (only a digest); no revision rows exist yet (0) |
| **Root Cause / evidence** | `app/engine/root_cause.py` | Nothing persistent | Derivation from stored values | Provenance of the evidence it cites |

### 2.2 Write paths (the destruction problem)

| Path | Behaviour | Provenance consequence |
|---|---|---|
| `app/engine/pipeline.py::_save_layered_results` | `DELETE` every row for `(hospital_id, month)` then `INSERT` fresh rows, then `commit()` | The **previous** layered result for that month is gone. Ids are recycled upward (D14: 10,787 rows, max id 211,960), which is itself evidence of repeated delete/insert cycles. |
| `app/engine/quality_alerts.py::_upsert_alert` | Matches an existing row by key and updates values in place; `detected_at` is not changed | The previous scored values are gone; only `detected_at` hints that the row is older than its contents (D14 §B showed both scan batches contain both capped and uncapped rows). |
| `app/engine/pipeline.py::_save_quality_score` → `scoring_audit.apply_score_update` | Writes a `QualityScoreRevision` **before** changing any numeric value | **The only correct pattern in the codebase** — reuse it for outlier results. |
| `app/api/config_api.py`, `admin.py` | Configuration edits | No config revision trail for alerts/scan settings; `quality_score_revisions.config` captures scoring config only. |

### 2.3 Identity and deduplication

- Layered rows are unique on `(hospital_id, analysis_code, month)`.
- Alerts are keyed by hospital + month + canonical formula identity + perspective (see `_identity_key`), and separate perspectives are intentionally separate rows.
- `app/engine/comparison_identity.py` already computes a **deterministic SHA-256 identity** of one peer comparison from hospital + canonical formula + month + sorted peer ids. It is pure, read-only and currently used only by a shadow KPI — the right primitive for the contract's `comparison_identity` field.
- `app/engine/canonical_identity.py` supplies the canonical formula key shared by both engines — the right primitive for `formula_identity`.

### 2.4 Configuration provenance that already exists

| Mechanism | Location | Shape | Reusable? |
|---|---|---|---|
| `scoring_config_snapshot` / `scoring_config_fingerprint` | `app/engine/quality/scoring.py:114-130` | `json.dumps(resolve_scoring_config(...), sort_keys=True, separators=(",",":"))` → SHA-256, first 16 hex | **Yes** — the canonical-serialization pattern to generalise |
| `severity.policy_fingerprint` | `app/engine/severity.py:565` | Payload of z threshold, trend settings, trend bands, rounded to 4 dp; SHA-256 first 16 hex | Yes — but it has **no human-readable version name**, so a fingerprint identifies a configuration without naming a policy |
| `evidence["severity_policy"]["fingerprint"]` | `app/engine/quality_alerts.py:1851` | Stamped per alert | Yes |
| `COMPARISON_POLICY_VERSION` | `app/engine/comparison_policy.py:45` | A string constant copied onto every layered row and alert peer block | **No** — unversioned contents: the window, min-observations and min-peers are resolved from AppConfig per run, so one "version" covers many different behaviours |
| `classification_provenance.zscore_threshold` | `pipeline.py:1244` | Stored only when the scan passes a threshold; NULL on 98% of rows | Partly — the fallback is silent |
| `quality_alert_audit` | `app/models.py:893` | Append-only batch record: `action`, `actor`, `months`, `details`, `created_at` | **Yes** — the precedent for run-level provenance |

### 2.5 Corrections to the D14 report (recorded here, not applied there)

Two D14 statements were wrong and must not be inherited:

1. `layered_outlier_results` has **no `evidence` column at all** — its columns are `history_provenance`, `peer_provenance`, `classification_provenance` and `created_at`. D14's "layered `evidence` NULL on 100%" described a non-existent column.
2. `quality_scores` has **no `config_fingerprint` / `config_snapshot` columns** — only `scoring_fingerprint` (16-hex SHA-256) and `scoring_config` (the full resolved snapshot). The real residual gap is that `scoring_fingerprint` is NULL on 39 of 176 rows and that the fingerprint covers the scoring config only, not the detection engine.

Everything else in D14 (reproducibility counts, the 1,091 legacy uncapped alerts, the uncommitted policy layer, null engine identity) is confirmed by this inspection. D14 remains unmodified.

---

## 3. Provenance gaps

| ID | Gap | Severity | Consequence | Evidence |
|---|---|---|---|---|
| G1 | No engine identity (version / build) on any row | **Critical** | A row cannot be attributed to an implementation. The policy that produced the newest results is uncommitted. | no `engine_version` anywhere (grep, 0 matches) |
| G2 | Policy version is a hand-edited constant covering many resolved behaviours | **Critical** | `2026-10-24.1` is stamped on all 10,787 layered rows although the window/min-peers are resolved per run | `comparison_policy.py:45`; `load_comparison_policy` |
| G3 | Recalculation destroys the previous result (`DELETE`+`INSERT`, in-place upsert) | **Critical** | "Original result" is not recoverable; cap-era and pre-cap-era values cannot coexist on the same key | `_save_layered_results`, `_upsert_alert`; D14 §B |
| G4 | No run/batch identity per result | High | Cannot group results of one scan, nor replay a scan's inputs | only `quality_alert_audit` at batch level |
| G5 | Threshold source is not recorded | High | 10,570 layered rows rely on the 2.5 default; a reader cannot tell "stored 2.5" from "fell back to 2.5" | `classification_provenance.zscore_threshold` present on 217 |
| G6 | Gate/cap decision not stored as a decision, only as inputs | Medium | Every reader re-derives the band; a later policy change silently changes the displayed band of an old row (which is why `stored_severity` had to be added) | `effective_severity`, `effective_row_level` |
| G7 | Raw vs capped score not distinguished | Medium | 1,091 legacy alerts store an uncapped score in the `score` column with no marker | D14 §D.2 |
| G8 | Method-selection reason absent | Medium | `layered.choose_method` picks z / IQR / pct-change / rolling-MAD from data properties; the row records the winner only | `layered.py` `choose_method` |
| G9 | Formula/unit missing on 74.4% of alerts | Medium | Registry identity absent on data-element rows; identity falls back to the code | D14 §E |
| G10 | No configuration revision trail for scan settings | Medium | An AppConfig change silently alters the next scan; nothing records the previous values | only `quality_score_revisions` covers scoring |
| G11 | Peers stored in two shapes (object in alerts, array in layered) | Low | Readers need two code paths | D14 §C |
| G12 | Alerts truncate `peer_ids` at 50 | Low | Completeness of the stored peer group cannot be proven beyond 50 | `quality_alerts.py:1828` `[:50]` |
| G13 | No reproducibility status per row | Low (derivable) | Every reader (or audit script) must re-derive reproducibility | D14 recomputed 17,943 rows by hand |

---

## 4. Proposed architecture

### 4.1 Principles

1. **Results are immutable facts about a moment.** A recomputation creates a new result and marks the old one superseded; it never destroys it.
2. **Identity is versioned, not inferred.** Every result names the engine and each policy it used, by name and digest.
3. **Capture at write time; explain at read time.** Anything that cannot be recovered later (which code, which config, which peers, which threshold) is written when the result is written. Anything derivable (gate decision under today's policy) is computed at read time and labelled as such.
4. **Unknown is a value.** Absent provenance is `unknown`, never defaulted, never invented.
5. **No backfill.** New fields apply to results written after approval; historical rows keep NULL and are classified.

### 4.2 Components

| # | Component | Kind | Purpose |
|---|---|---|---|
| C1 | `policy_registry` (immutable table) | New storage | One row per `(component, version)`: canonical definition JSON + SHA-256 digest + optional `effective_from`. Append-only; a version's digest may never change. |
| C2 | `analysis_runs` (append-only table) | New storage | One row per scan/recompute: `run_id`, trigger, scope (months, hospitals, indicators), engine version + dirty flag, policy digest tuple, config fingerprint + snapshot, started/finished, counters, actor. Extends the existing `quality_alert_audit` idea to all result types. |
| C3 | Per-result scalar columns | New storage (small) | `run_id`, `engine_version`, `policy_digest`, `provenance_status`, `superseded_by`. Indexed so "all rows from build X / policy Y / run Z" is a query, not a scan. |
| C4 | `result_provenance` JSON envelope | New storage (per row) | Everything a reproduction needs that is specific to the row: raw score, final score, caps applied, gate inputs, threshold + source, method choice + reason, input snapshot, peer/history references, formula identity. Detail stays in JSON; identity/config lives in C1–C3 by reference. |
| C5 | `outlier_result_revisions` (append-only) | New storage | Previous values of a layered row before it is replaced, mirroring `quality_score_revisions` (previous/new values, fingerprints, run id, actor, timestamp). |
| C6 | `app/engine/provenance.py` | New module (pure) | `classify(result)` → reproducibility class + evidence + permitted claims; `current_policy_result(result)` → labelled comparison; `verify_fingerprint(snapshot, digest)`. No session, no writes. |
| C7 | API envelope `provenance` | Additive payload | `original` / `current_policy` / `verified` + status + versions + threshold source, on alert, layered, diagnostics, explain, dashboard, report payloads. |
| C8 | UI provenance block | Additive | Badge + three-value display + bilingual labels (§10). |

### 4.3 Why this shape (and not simpler or heavier alternatives)

| Alternative | Verdict |
|---|---|
| One giant `provenance` JSON per row containing config too | Rejected: duplicates the same config across 7,156+10,787 rows, makes "which rows used config X" a full scan, and invites drift between copies. Config belongs to the **run**, referenced by id. |
| Only new scalar columns | Rejected: ~25 values are row-specific and variable-length (window values, peer ids, caps). Columns would be sparse and frequently altered. JSON envelope + small identity columns is the right split. |
| Keep delete+insert, trust `created_at` | Rejected: G3. Provenance without the previous result is provenance of a fact that no longer exists. |
| Store a full input snapshot of every raw indicator per row | Rejected as default: the row's own window + peers + current value is sufficient to reproduce the score; raw indicator dumps belong to the run record only when a deep recompute is requested. |
| Recompute-and-store reproducibility status for all rows now | Rejected: that is a write and a backfill. Status is computed at read time (C6) for historical rows; stored only for new rows. |

### 4.4 The three concepts, enforced structurally

| Concept | Source of truth | Can be wrong? | Allowed to be substituted? |
|---|---|---|---|
| **Original result** | `layered_outlier_results` row as written (+ `outlier_result_revisions` once superseded), `quality_alerts` row as written, `quality_scores` | No — it is what happened | Never |
| **Current policy result** | `provenance.current_policy_result(row)` recomputed from stored inputs with today's policy | It answers a *hypothetical*, and may differ | Never silently — always labelled `policy_now` |
| **Verified historical result** | Requires engine version + policy versions + inputs + a reproduction run recorded in `analysis_runs` | Reproducible or not | Never presented as "what the engine did" unless the exact engine/policy is available |

Rule: a screen may show current-policy output **beside** the original, never **instead of** it, and never under a label implying it is the original.

---

## 5. Proposed field contract

Groups: **A** result identity, **B** engine, **C** policy, **D** configuration, **E** input, **F** decision, **G** reproducibility. Storage: *direct* = own column/JSON key; *ref* = id pointing at C1/C2; *derived* = computed at read time.

| Field | Group | Purpose | Type | Required | Source | Storage | Applicable result types |
|---|---|---|---|---|---|---|---|
| `result_id` | A | Stable identity of this result | string (uuid) | yes | generated at write | direct | alert, layered, score |
| `result_key` | A | Natural key (hospital, formula identity, month, perspective) | string | yes | `canonical_identity` | direct | alert, layered |
| `superseded_by` | A | Which result replaced this one | string/uuid | no | write path | direct | alert, layered, score |
| `run_id` | A | Which scan produced it | uuid | yes | `analysis_runs` | ref | all |
| `engine_version` | B | Code identity (build) | string (SHA + dirty) | yes | build metadata | direct | all |
| `engine_semantics` | B | Algorithm family/version (e.g. `layered@2`) | string | yes | code constant | direct | layered, alert |
| `engine_dirty` | B | Build had uncommitted changes | bool | yes | build metadata | direct (in run) | all |
| `policy.comparison` | C | Window / min observations / min peers / group | `name@ver` + digest | yes | `policy_registry` | ref + digest | alert, layered |
| `policy.severity` | C | Trend resolution, bands, escalation | `name@ver` + digest | yes | registry | ref | alert |
| `policy.eligibility` | C | Top-band gate, thin-peer, zero-spread, pct cap | `name@ver` + digest | yes | registry | ref | alert, layered |
| `policy.scoring` | C | Quality-score weights + outlier multiplier | `name@ver` + digest | yes for scores | registry | ref | quality score |
| `policy.registry_formula` | C | Formula/unit version of the indicator definition | string | yes when applicable | `IndicatorDefinition` | direct | alert, layered |
| `policy_digest` | C | Composite digest of the tuple above | string (64) | yes | computed | direct | all |
| `config_fingerprint` | D | Digest of the resolved settings used | string (64) | yes | canonical serialization | direct | all |
| `config_snapshot_ref` | D | Which stored snapshot is authoritative | `run_id` | yes | `analysis_runs` | ref | all |
| `threshold.value` | C/F | Z threshold actually used | float | yes when a threshold applied | scan config | direct | alert, layered |
| `threshold.source` | C/F | `stored` / `historical_config` / `legacy_fallback` / `current_config` / `unknown` | enum | yes | read-time rule | derived for legacy; direct for new | alert, layered |
| `inputs.current` | E | Value analysed | float | yes | pipeline | direct (exists) | alert, layered |
| `inputs.previous` | E | Prior reporting value | float | no | pipeline | direct (exists) | layered |
| `inputs.window.months` | E | Months examined | string[] | yes | comparison policy | direct (exists) | alert, layered |
| `inputs.window.values` | E | Values in order | float[] | yes | pipeline | direct (exists) | alert, layered |
| `inputs.window.skipped` | E | Months with no computable value | string[] | no | pipeline | direct (exists) | layered |
| `inputs.peer_ids` | E | Exact peer group | int[] | yes for peer comparisons | pipeline | direct (exists; **no truncation** for new rows) | alert, layered |
| `inputs.peer_values` | E | Peer values | number map/array | no | pipeline | direct (exists) | alert, layered |
| `inputs.peer_group` | E | Which group was compared | string | yes | comparison policy | direct (exists) | alert, layered |
| `inputs.eligible_count` | E | Eligible peer universe | int | no | pipeline | direct (exists) | layered |
| `method.chosen` | F | Scoring method used | string | yes | `choose_method` | direct (exists) | alert, layered |
| `method.reason` | F | Why this method (properties that selected it) | string/code | yes | `choose_method` | direct (new) | alert, layered |
| `score.raw` | F | Score before caps | float | yes | engine | direct (new) | alert, layered |
| `score.final` | F | Score after caps | float | yes | engine | direct (= current `score`) | alert, layered |
| `caps[]` | F | Caps/gates applied, with inputs | object[] | yes (empty allowed) | engine | direct (partly exists) | alert, layered |
| `gate.decision` | F | Eligible for top band + reason | object | yes for VH-capable rows | read-time gate | derived (+ audit snapshot) | alert, layered |
| `band.stored` | F | Band written at calculation | enum | yes | write path | direct (exists as `severity`/`outlier_level`) | alert, layered |
| `formula.identity` | E/F | Canonical formula identity | string | yes | `canonical_identity` | direct (new) | alert, layered |
| `formula.text`,`unit` | E | Formula and unit as used | string | yes when defined | registry copy | direct (exists on alerts; new on layered) | alert, layered |
| `reproducibility_status` | G | `REPRODUCIBLE` / `PARTIALLY_REPRODUCIBLE` / `NOT_REPRODUCIBLE` / `LEGACY_UNKNOWN` / `NO_RESULT` | enum | no (NULL = unknown) | `provenance.classify` | direct for new rows; **derived** for legacy | alert, layered |
| `provenance_schema` | G | Which contract version this row follows | int | yes for new rows | constant | direct | all |
| `created_at`, `period` | A | When written / which month it describes | timestamp, string | yes | write path | direct (exists) | all |

**Not proposed for storage:** hospital/indicator *names* (PII and mutable — ids suffice; registry snapshot already copies names where needed), user identity of the analyser (belongs to `analysis_runs`), and any value derivable from the window (`mean`, `std`, `z`) as authoritative — §4.3 duplication rule.

---

## 6. Versioning strategy

### 6.1 Separate component versions (single global version rejected)

| Component | What it governs | Current state | Proposed identifier |
|---|---|---|---|
| Layered engine | layer construction, method selection, scoring functions | code only | `layered@2.0.0` + build SHA |
| Alert detection composition | which findings become alerts, perspectives | code only | `alerts@2.0.0` |
| Comparison policy | window, min observations, min peers, group id | `2026-10-24.1` constant, contents resolved per run | `comparison@2.1.0` + digest of *resolved* policy |
| Severity policy | trend resolution, bands, escalation | fingerprint only | `severity@1.3.0` (fingerprint retained) |
| Eligibility policy | VH gate, thin-peer cap, zero-spread cap, pct-change cap | unversioned constants (uncommitted) | `eligibility@2.0.0` |
| Scoring policy | quality weights, outlier multiplier | fingerprint + snapshot | `scoring@1.1.0` |
| Formula registry | indicator formula/unit/version | `IndicatorDefinition.formula_version` | `formula@<definition version>` |

Single global version is **insufficient**, demonstrated by the data: `2026-10-24.1` covers rows produced before and after the caps were introduced (D14 §B), while the severity policy changed independently and left its own fingerprint — one string cannot describe two independently moving policies.

### 6.2 Assignment rules

A version changes **when the meaning of a decision changes**, not when the code is refactored without behavioural change:

- **Patch** — bug fix that restores intended behaviour without changing any stored output for unchanged inputs.
- **Minor** — new optional capability that cannot change an existing result shape.
- **Major** — any change that can change a stored score, band, eligibility decision or cap for unchanged inputs (including a threshold default, a band boundary, a cap value, a peer-count floor, or a method-selection rule).

### 6.3 Immutability enforcement

1. `policy_registry` rows are append-only: a new version is a new row; no `UPDATE` of `definition` or `digest` (enforced by a read-only ORM mapping and a DB trigger or permission in implementation).
2. The engine reads a policy **by version**, not "whatever is in code now"; a version's definition is loaded from the registry and the code asserts `digest(code_definition) == registry.digest`, failing loudly on drift.
3. A **golden test per version** pins the outputs of a fixture set for that version; editing the fixture or the expected output under an existing version fails the suite, which is the practical guard against "silently changing what `2026-10-24.1` means".
4. `engine_version` always accompanies a policy version, so a code-only change is still traceable.

### 6.4 Effective dates

`policy_registry.effective_from` is **nullable and never invented**. Historical rows keep `UNKNOWN`; the design forbids deriving an effective date from `detected_at` (D14 established that it is not a write timestamp).

---

## 7. Threshold provenance

### 7.1 Five distinguishable states

| State | Meaning | How established | Current rows | Display |
|---|---|---|---|---|
| `stored` | The row itself recorded the threshold it scored with | `evidence["z_threshold"]` (alerts, 7,156 rows) or `classification_provenance.zscore_threshold` (layered, 217 rows) | majority of alerts | "Threshold 2.5 (stored with the result)" |
| `historical_config` | Recoverable from a configuration snapshot for that period | requires `analysis_runs`/config revisions (proposed) | **none today** | "Threshold 2.5 (historical configuration, <date>)" |
| `legacy_fallback` | No stored threshold; the documented default was used **by the reader** | absence of a stored value | 10,570 layered rows | "Threshold assumed 2.5 — the default for legacy rows; not recorded with the result" |
| `current_config` | Read from today's settings for a *comparison* | `gate_threshold` at read time | n/a for original results | "Current setting 2.5 (applied for comparison only)" |
| `unknown` | Neither stored nor reconstructable, and no fallback may be applied | — | **none today** (a fallback always exists) | "Threshold unknown" |

### 7.2 Rules

1. The existing fallback is **preserved exactly**: `stored_threshold(evidence)` → `None` → `gate_threshold` (currently 2.5). No behavioural change is proposed.
2. A fallback is **labelled at read time**, never written into the row: a legacy row must never gain a `z_threshold` it did not store.
3. `2.5` remains the configured default (`zscore_threshold_source` already distinguishes `database` / `default` / `invalid` in System Control). The design adds no new threshold and changes none.
4. New rows always store `threshold.value` + `threshold.source`; `stored` is the only source a reproduction may rely on, `current_config` may only feed a labelled comparison.

---

## 8. Reproducibility classification

### 8.1 Classes

| Class | Exact criteria | Required evidence | May display | Must not claim | Current-policy comparison |
|---|---|---|---|---|---|
| `REPRODUCIBLE` | Engine + all applicable policy versions known; stored inputs sufficient; a reproduction with the **same** engine/policy reproduces the score within 1e-6 | engine_version, policy tuple, inputs, method, threshold + source | "Verified: reproduced with engine X, policy Y" | "Correct" or "current policy agrees" | Allowed, labelled |
| `PARTIALLY_REPRODUCIBLE` | Inputs present and the score is explained, but one element is missing/irrecoverable (a cap's divisor, a degenerate spread's magnitude, a policy version, a truncated peer list) | stored inputs + a documented fallback used at the time | "Reproduced only partially — <missing element>" | "Reproducible", "verified" | Allowed, labelled; result of comparison marked provisional |
| `NOT_REPRODUCIBLE` | Essential inputs absent, contradictory, or the stored score cannot be derived from them under any plausible policy | absence/contradiction recorded | "Not reproducible — inputs missing/inconsistent" | Any reconstruction presented as the original | Allowed, labelled as hypothetical |
| `LEGACY_UNKNOWN` | Row predates reliable provenance capture (no engine version, and its policy cannot be established) — even when the score is explainable | absence of version identity, optionally a matching historical formula | "Legacy result — policy generation unknown; score explained under the pre-cap rule" | "Produced by policy X", an effective date, or "verified" | Allowed, labelled "current policy would produce Z" |
| `NO_RESULT` | No scored result was stored (e.g. `insufficient_history`, NULL score) | method/level recorded, score NULL | "No result stored — not assessable" | "Reproducible", "failed" | Not applicable |

Decision order (deterministic): `NO_RESULT` → `NOT_REPRODUCIBLE` → `LEGACY_UNKNOWN` → `PARTIALLY_REPRODUCIBLE` → `REPRODUCIBLE`.

### 8.2 Mapping to D14's empirical classes

| D14 class | D14 count | Proposed status |
|---|---|---|
| A exact | alerts 5,062 · layered 6,005 | `REPRODUCIBLE` — *only after* the engine version is known; until then the honest label is `LEGACY_UNKNOWN` with an "inputs reproduce this score" note |
| B partial | alerts 1,003 · layered 164 | `PARTIALLY_REPRODUCIBLE` |
| C impossible | 0 | `NOT_REPRODUCIBLE` |
| D legacy policy | alerts 1,091 | `LEGACY_UNKNOWN` (current-policy comparison available and already measured) |
| N no result | layered 4,618 | `NO_RESULT` |

The mapping is deliberately **not** 1:1: D14 could recompute a score from stored inputs, which proves *inputs suffice*, not that *the historical engine did this*. A row cannot be `REPRODUCIBLE` until its engine and policy identities exist, so today's historical corpus is at best `PARTIALLY_REPRODUCIBLE` / `LEGACY_UNKNOWN`. This is the central discipline of the design.

---

## 9. Historical compatibility

| Requirement | Mechanism |
|---|---|
| No mandatory backfill | All new columns/keys nullable; `provenance_schema` NULL means "pre-contract" |
| No historical recalculation | Nothing in the design writes a score or a band to an existing row |
| No change to stored severity | `severity` / `outlier_level` remain the original values; policy bands stay read-time (`effective_severity`, `effective_row_level`) |
| No invented effective dates | `effective_from` nullable; UNKNOWN is a legal value |
| No inferred engine version as fact | `engine_version` NULL on historical rows; readers report "unknown", never a guess from `created_at` |
| Unknown stays unknown | `threshold.source = legacy_fallback` is explicitly *not* `stored`; `provenance.status = unknown` on absent data |
| APIs remain compatible | New payload keys only; no key renamed or removed; existing rows keep the same shapes (`stored_severity` pattern extended) |
| Reports do not reinterpret | Reports gain `stored_band` beside the policy band; the policy band keeps its current meaning |
| Introduction path | Phases P0–P7 (§11); each phase additive and independently revertible; no phase depends on a backfill |

---

## 10. API and UI proposal

### 10.1 Envelope (additive, on all result payloads)

```json
"provenance": {
  "schema": 1,
  "status": "REPRODUCIBLE",
  "engine": {"version": "4b82b19", "dirty": false, "semantics": "layered@2.0.0"},
  "policies": {"comparison": {"version": "comparison@2.1.0", "digest": "…"},
               "eligibility": {"version": "eligibility@2.0.0", "digest": "…"},
               "severity": {"version": "severity@1.3.0", "digest": "…"}},
  "run_id": "…",
  "threshold": {"value": 2.5, "source": "stored"},
  "reproducibility": {"checked_at": "2026-11-02T10:00:00Z",
                      "method": "same_engine_replay | inputs_only | none",
                      "note": null}
}
```

### 10.2 Example — fully reproducible alert

```json
{"id": 7001, "hospital_id": 21, "month": "2026-08", "perspective": "all",
 "severity": "HIGH", "stored_severity": "HIGH", "score": 0.62,
 "provenance": {"schema": 1, "status": "REPRODUCIBLE",
   "engine": {"version": "4b82b19", "dirty": false, "semantics": "alerts@2.0.0"},
   "policies": {"comparison": {"version": "comparison@2.1.0", "digest": "9f1c…"},
                "eligibility": {"version": "eligibility@2.0.0", "digest": "3ab7…"},
                "severity": {"version": "severity@1.3.0", "digest": "b806…"}},
   "run_id": "a1f0…", "threshold": {"value": 2.5, "source": "stored"},
   "reproducibility": {"checked_at": "2026-11-02T10:00:00Z", "method": "same_engine_replay"}},
 "verification": {"original": 0.62, "current_policy": 0.62, "verified": 0.62, "agreement": "identical"}}
```

### 10.3 Example — partially reproducible legacy alert

```json
{"id": 6589, "hospital_id": 21, "month": "2026-04", "perspective": "all",
 "severity": "VERY_HIGH", "stored_severity": "VERY_HIGH", "score": 0.9333,
 "provenance": {"schema": 0, "status": "LEGACY_UNKNOWN",
   "engine": {"version": null, "note": "written before engine identity existed"},
   "policies": {"comparison": {"version": "2026-10-24.1", "digest": null}},
   "threshold": {"value": 2.5, "source": "stored"},
   "reproducibility": {"checked_at": "2026-11-02T10:00:00Z", "method": "inputs_only",
                       "note": "score equals the uncapped percentage change; the cap did not exist when this row was written"}},
 "verification": {"original": 0.9333, "current_policy": 0.0467, "verified": null,
                  "agreement": "policy_generation_differs", "effective_band_now": "HIGH"}}
```

### 10.4 Example — stored historical threshold

```json
"provenance": {"threshold": {"value": 2.5, "source": "stored",
               "note": "recorded with the result at calculation time"}}
```

### 10.5 Example — unknown historical threshold

```json
"provenance": {"threshold": {"value": 2.5, "source": "legacy_fallback",
               "note": "not recorded with the result; the documented default is used to display it and is NOT evidence the scan used 2.5"}}
```

### 10.6 Example — original severity differs from current policy

```json
{"id": 6589, "severity": "HIGH", "stored_severity": "VERY_HIGH",
 "provenance": {"status": "LEGACY_UNKNOWN"},
 "verification": {"original_band": "VERY_HIGH", "policy_band": "HIGH",
                  "reason": "top-band eligibility gate: dispersion band below VERY_HIGH",
                  "policy_version": "eligibility@2.0.0"}}
```

### 10.7 Bilingual labels (suggested)

| Concept | English | Arabic |
|---|---|---|
| Provenance block | Provenance | التوثيق |
| Original result | Original result | النتيجة الأصلية |
| Current policy result | Result under current policy | النتيجة وفق السياسة الحالية |
| Verified historical result | Verified historical result | النتيجة التاريخية الموثّقة |
| Reproducibility status | Reproducibility | حالة إعادة الإنتاج |
| REPRODUCIBLE | Reproducible | قابلة لإعادة الإنتاج |
| PARTIALLY_REPRODUCIBLE | Partially reproducible | قابلة لإعادة الإنتاج جزئياً |
| NOT_REPRODUCIBLE | Not reproducible | غير قابلة لإعادة الإنتاج |
| LEGACY_UNKNOWN | Legacy — policy unknown | سجل قديم — السياسة غير معروفة |
| NO_RESULT | No result stored | لا توجد نتيجة محسوبة |
| Engine version | Engine version | إصدار المحرك |
| Policy version | Policy version | إصدار السياسة |
| Threshold | Threshold | الحد الفاصل |
| Threshold source | Threshold source | مصدر الحد الفاصل |
| stored | Stored with the result | مخزَّن مع النتيجة |
| historical_config | Historical configuration | إعداد تاريخي |
| legacy_fallback | Legacy default (assumed) | الافتراضي للسجلات القديمة (مُفترض) |
| current_config | Current setting | الإعداد الحالي |
| unknown | Unknown | غير معروف |
| Cap applied | Cap applied | تم تطبيق سقف |
| Top-band gate | Top-band eligibility | أهلية النطاق الأعلى |
| Not verified | Not verified | غير موثّق |

### 10.8 UI rules

1. When `status != REPRODUCIBLE`, show a badge; never colour it as an error (it is a provenance fact, not a fault).
2. Show `original` and `policy_now` **side by side** whenever they differ; never replace one with the other.
3. A `legacy_fallback` threshold is rendered with the assumption marker (Arabic: «مُفترض») and a tooltip stating it was not recorded.
4. Explain gains a "Provenance" section listing engine/policy versions, run id and caps, and states `verified: not available` where no replay exists.
5. Dashboard KPIs carry a footnote when any contributing row is `LEGACY_UNKNOWN` or `PARTIALLY_REPRODUCIBLE`.
6. Reports print `stored_band` and `policy_band` when they differ, plus the provenance status per row.
7. No screen displays a current-policy recomputation under the word "original" or "stored".

---

## 11. Implementation roadmap

Each phase is independently reviewable, reversible, and writes nothing to existing rows.

### P0 — Policy registry + version constants (foundation)
- **Scope:** add `policy_registry` (immutable), seed current definitions, add `policy_registry` reader and drift assertion.
- **Files likely:** `app/models.py`, new `app/engine/policy_registry.py`, `alembic/versions/*` (new), seeds.
- **DB impact:** one new table + seed rows; no column changes elsewhere.
- **API/UI:** none.
- **Tests:** digest determinism, immutability, drift assertion fails on edited definition.
- **Rollback:** drop table; code behind a feature flag.
- **Risks:** freezing an inaccurate definition of today's policy — mitigate by generating the definition from code, not by hand.
- **Depends on:** nothing.

### P1 — Run identity (`analysis_runs`)
- **Scope:** create the table, generate a `run_id` per scan/recompute, write started/finished/counters/engine version/config snapshot.
- **Files:** `app/models.py`, `app/engine/pipeline.py`, `app/engine/quality_alerts.py`, `app/api/upload.py`, admin rescan endpoints, migration.
- **DB impact:** new table; no existing rows touched.
- **API/UI:** optional `run_id` echo on upload response.
- **Tests:** one run per scan; counters match written rows; failure path closes the run.
- **Rollback:** stop writing; table retained.
- **Risks:** long-running scans holding a run open — use explicit finish + timeout status.
- **Depends on:** P0 (for the policy digest tuple).

### P2 — Layered result provenance + revision trail
- **Scope:** add `result_provenance` envelope, scalar identity columns, `outlier_result_revisions`; replace destructive `DELETE`+`INSERT` with supersede-or-replace-plus-revision; store threshold + source, method reason, raw/final score, formula identity.
- **Files:** `app/models.py`, `app/engine/pipeline.py`, `app/engine/anomaly/layered.py`, migration.
- **DB impact:** 1 JSON column + 5 scalars on `layered_outlier_results`; 1 new revision table.
- **API/UI:** none in this phase.
- **Tests:** recomputation leaves a revision; ids of superseded rows unchanged; unique constraint still satisfied.
- **Rollback:** revert write path; columns remain NULL on new rows.
- **Risks:** write volume growth (≈1 extra row per recomputed result) — acceptable, bounded by rescans.
- **Depends on:** P1.

### P3 — Alert provenance envelope
- **Scope:** same envelope for alerts; always copy formula/unit; store full peer ids (no 50-cap) or an explicit `peer_ids_truncated` flag; store `score.raw` vs `score.final`, method reason, threshold source; add revision on upsert when numeric values change.
- **Files:** `app/engine/quality_alerts.py`, `app/engine/pipeline.py`, `app/models.py`, migration.
- **DB impact:** 1 JSON column + 5 scalars; optional revision table reuse from P2 (generalise to a shared table).
- **API/UI:** none yet (payload unchanged until P5).
- **Tests:** upsert with changed values writes a revision; unchanged rescans write none; evidence keys stable.
- **Rollback:** feature flag off → old behaviour.
- **Risks:** doubling evidence size where the envelope duplicates `evidence`; mitigate by keeping `evidence` as-is and storing only the delta (identity/versions/decision) in the envelope.
- **Depends on:** P1, P2 (shared revision primitive).

### P4 — Reproducibility evaluator
- **Scope:** `app/engine/provenance.py` (pure): `classify`, `current_policy_result`, `verify_fingerprint`; store `provenance_status` on new rows only.
- **Files:** new module, read-path call sites (none yet), tests.
- **DB impact:** one scalar column (already added in P2/P3).
- **API/UI:** none.
- **Tests:** the §12 matrix; determinism; no session use.
- **Rollback:** delete module; NULL status returns.
- **Risks:** mis-classifying legacy rows as `REPRODUCIBLE`; the decision order in §8.1 prevents it.
- **Depends on:** P0–P3.

### P5 — API exposure
- **Scope:** additive `provenance` and `verification` blocks on alert, layered, diagnostics, explain, dashboard, report payloads; `?provenance=summary|full`.
- **Files:** `app/api/quality_alerts.py`, `app/api/analysis.py`, `app/api/dashboard.py`, `app/api/reports.py`, `app/engine/audit/explain.py`, `app/schemas.py`.
- **DB impact:** none.
- **API impact:** new keys only; documented in the OpenAPI description.
- **UI:** none yet.
- **Tests:** payload snapshot per case; existing consumers unchanged; no key removed.
- **Rollback:** remove keys; clients ignore unknown keys by construction.
- **Risks:** payload size on list endpoints — summary mode caps it.
- **Depends on:** P4.

### P6 — UI
- **Scope:** provenance badge, three-value display, threshold-source marker, Explain provenance section, report `stored_band` column; EN/AR strings.
- **Files:** `static/js/*`, `static/tabs/*.html`, `static/css/styles.css`.
- **DB/API impact:** none.
- **Tests:** rendering with fixtures for each status; Arabic labels; no number changes.
- **Rollback:** revert static assets.
- **Risks:** visual overload — collapse by default, expand on demand.
- **Depends on:** P5.

### P7 — Historical verification tooling (separate approval)
- **Scope:** a read-only audit script that classifies the historical corpus and can, when authorised, record `provenance_status` **without** touching scores/bands; optionally a replay runner using pinned engine versions.
- **Files:** `scripts/*` (new), docs.
- **DB impact:** at most a status column update, explicitly approved per run; no score/band writes.
- **Tests:** dry-run by default; explicit `--apply` required.
- **Risks:** this is the only phase that can write to historical rows — hence separate approval.
- **Depends on:** P4, and the operator's decision on UD6 (§13).

---

## 12. Testing strategy

| Scenario | Fixture | Expected outcome |
|---|---|---|
| New result stores complete provenance | one scan, one hospital/month | envelope present, engine/policy/run ids set, threshold source `stored`, status `REPRODUCIBLE` |
| Historical thresholds remain unchanged | row with `z_threshold` 2.5 and row with 2.2 | both keep their stored value; no write; `threshold.source = stored` |
| Legacy missing threshold | row without a stored threshold | displayed 2.5 with source `legacy_fallback`; `stored` never claimed; no update |
| Configuration change after calculation | store config A, change config to B | old row reports A's fingerprint + `policy_state = stale`; no value changes |
| Policy version change | bump `eligibility` version in fixture | old row keeps stored band; payload reports the row's version and the current version separately |
| Engine version change | two rows with different engine versions | both classified independently; no cross-attribution |
| Deterministic fingerprint | same resolved config, two key orders | identical digest; different value → different digest (existing test `test_fingerprint_is_stable_across_input_shape_and_sensitive_to_every_setting` is the precedent) |
| Reproducibility classification | one fixture per class | exactly the specified class, per the §8.1 decision order |
| Original vs current policy differ | 6589-style fixture | original 0.9333 preserved, current 0.0467 labelled `policy_now`, `verified = null` |
| API backward compatibility | pre-change payload fixture | all old keys present with identical values; new keys additive |
| Arabic and English rendering | UI fixture both locales | every label from §10.7 renders; no missing translation, no layout overflow |
| No silent historical reinterpretation | freeze a legacy row, run every read endpoint | zero writes; stored band unchanged; policy band labelled |
| Supersede preserves original | recompute a layered month | old row retained (revision), new row points at run; no deletion |
| Alert upsert revision | rescan with changed values | revision row written; unchanged rescan writes none |
| No-result rows | `insufficient_history` fixture | `NO_RESULT`, no reproduction attempted, no failure reported |
| Peer truncation honesty | alert with 60 peers | complete ids stored (new) or `peer_ids_truncated = true` (legacy), never silently partial |

No tests are added or executed in D15.

---

## 13. Risks and unresolved decisions

### Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Policy registry definition drifts from code | False provenance, worse than none | Generate definitions from code constants; assert digest equality at import; golden tests per version |
| Writing revisions doubles write volume | Slower scans, larger DB | Revisions only when values change (the quality-score precedent already does this) |
| Envelope duplicates `evidence` | Storage growth | Envelope holds identity/versions/decision only; existing blocks stay authoritative for inputs |
| UI exposes `LEGACY_UNKNOWN` widely | Perceived regression | Frame as provenance honesty; badge not error; explain what is known |
| Misclassification as `REPRODUCIBLE` | Overclaims history | Decision order requires version identity first; `verified` requires a replay |
| Engine version from runtime git call | Fragile in production | Read build-time metadata; `unknown` when absent, never guessed |

### Unresolved decisions (require the operator)

| ID | Decision | Recommendation |
|---|---|---|
| UD1 | Is `effective_from` mandatory for new policy versions? | No — nullable, UNKNOWN allowed; dates require human entry |
| UD2 | Build-version source (`APP_BUILD_VERSION` env vs packaged metadata) | Env at build/deploy, `unknown` fallback; never runtime `git` |
| UD3 | Digest length for new fields | 64 hex (full SHA-256); keep existing 16-hex values as-is |
| UD4 | Store peer values inline or reference the run's input snapshot | Inline for ≤100 peers; reference above that |
| UD5 | Retention for run-level config snapshots | Keep indefinitely (small, and the only record of past configuration) |
| UD6 | Backfill `provenance_status` for historical rows? | Defers to D14 §L: no backfill of scores; a status-only update is optional and separately approved (P7) |
| UD7 | Materialise the read-time gate decision? | Only as an audit snapshot (`gate.decision` for new rows); never as the authoritative band |
| UD8 | Arabic terminology for "provenance" (التوثيق vs مصدر النتيجة) | Adopt التوثيق consistently, matching the proposed labels |

---

**Design status:** complete for review. Nothing implemented, nothing written to the database, no schema or migration created, no server started, no test added or run.

---

## Amendment A1 — System Control is the single source of analysis policy

**Mandatory architectural requirement.** System Control (the `/config/*` surface over
`app_config` + `system_settings`) is the authoritative source of every *configurable* analysis
policy and threshold. The analysis engine must hold no independent static value that duplicates a
setting System Control manages, and no consumer may reconstruct policy values on its own.

Full design: **`qa-d15/D15-AMENDMENT-A1-SYSTEM-CONTROL-AUTHORITY.md`**.

What it changes in this document:

- **§3.3 (configuration provenance)** — configuration is now captured as one immutable
  `PolicySnapshot` resolved **once per analysis run**, not re-read by each layer. `set_trends_config`
  (a process-global dict mutated by every run) is removed from the analysis path.
- **§4 (contract)** — four added fields: `config_resolver_version`, `config_snapshot_digest`,
  `config_snapshot_ref` (reference to `analysis_runs`, not a per-row copy),
  `config_unavailable_keys` (keys that fell back to a default, with the reason).
- **§5 (versioning)** — `config@<semver>` joins the seven component versions; `policy_registry`
  entries record each parameter's *definition* (storage plane, bounds, default, configurable vs
  frozen) so a digest changes when meaning changes, not when a value is saved.
- **§9 (phases)** — a new phase A1 (resolver beside existing loaders, zero behaviour change)
  precedes A2 (consumers switched), A3 (duplicate literals and globals removed), A4 (digest stored,
  needs P1), A5 (System Control shows effective value + source).

Verdict preserved from the verification of the implementation: 43 parameters are genuinely
configurable and stored across two tables; 11 constants are frozen algorithm policy and must **not**
be promoted to knobs (top-band peer floor 4, zero-spread and thin-peer caps, %-change cap tuple, and
the method-selection constants); five modules restate the Z-score default 2.5 independently.
`zscore_threshold = 2.5` and every other saved value, cutoff, weight and formula are unchanged by
this amendment.
