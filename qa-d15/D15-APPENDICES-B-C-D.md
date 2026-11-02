# D15 — Appendices B, C, D

Companion to `qa-d15/D15-OUTLIER-PROVENANCE-ARCHITECTURE.md` (Deliverable A).
Design only. Nothing implemented.

---

## Deliverable B — Data flow diagram

Legend: **[EXISTS]** implemented in the working tree · **[PARTIAL]** exists but incomplete/inconsistent · **[PROPOSED]** not implemented.

```
┌──────────────────────────────┐
│ 1. INPUT DATA                │  [EXISTS]
│ indicator_values, hospital   │  upload / manual entry
│ month enablement, registry   │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ 2. CONFIGURATION SNAPSHOT    │  [PARTIAL]
│ • AppConfig alerts/quality   │  scoring: snapshot+fingerprint (EXISTS)
│ • System Control thresholds  │  severity: fingerprint only (PARTIAL)
│ • rate_config per-formula    │  comparison: constant version, resolved
│ • registry formula versions  │  per run, NOT snapshotted (GAP G2)
│ • canonical policy docs      │  policy_registry (PROPOSED, C1)
│ • config_revision history    │  (PROPOSED; absent today → G10)
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ 3. RUN CONTEXT               │  [PROPOSED, C2]
│ run_id, trigger, scope,      │  today only quality_alert_audit covers
│ engine_version+dirty,        │  batch actions (PARTIAL)
│ policy tuple + digest        │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ 4. ENGINE EXECUTION          │  [EXISTS]
│ layered.score_window_detail  │  window → layers → scores
│ choose_method                │  method selection (reason NOT stored, G8)
│ peer group selection         │  ids+values captured (EXISTS)
│ history window policy        │  window+values captured (EXISTS)
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ 5. POLICY EVALUATION         │  [PARTIAL]
│ classification (rule 1..n)   │  stored (EXISTS)
│ zero-spread cap              │  stored per layer (EXISTS)
│ thin-peer cap                │  stored per layer (EXISTS)
│ pct-change cap               │  stored ONLY when it lowered (G6/G7)
│ top-band gate                │  READ TIME only, not stored (G6)
│ severity/trend resolution    │  stored with fingerprint (EXISTS)
│ quality-score combination    │  stored config+fingerprint (EXISTS)
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ 6. PROVENANCE CAPTURE        │  [PARTIAL → PROPOSED]
│ result_provenance envelope   │  (PROPOSED, C4)
│ history/peer/classification  │  (EXISTS, three JSON blocks)
│ alert evidence JSON          │  (EXISTS, richest but inconsistent)
│ revision of replaced value   │  quality_score_revisions (EXISTS)
│                              │  outlier_result_revisions (PROPOSED, C5)
│ reproducibility status       │  (PROPOSED, C6)
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ 7. STORED RESULT             │  [EXISTS, destructively]
│ layered_outlier_results      │  DELETE+INSERT per hospital/month (G3)
│ quality_alerts               │  upsert in place, keeps detected_at (G3)
│ quality_scores               │  overwrite + revision (correct pattern)
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ 8. API                       │  [EXISTS, no provenance envelope]
│ /quality-alerts  /analysis   │  effective band computed here (gate)
│ /dashboard  /reports  explain│  stored_severity + policy band present
│                              │  provenance/verification blocks (PROPOSED)
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ 9. UI                        │  [EXISTS, no provenance surface]
│ Alerts list/detail, Explain  │  stored vs displayed band (EXISTS)
│ Diagnostics, Dashboard,      │  threshold-source marker (PROPOSED)
│ Reports                      │  reproducibility badge (PROPOSED)
│                              │  three-value display EN/AR (PROPOSED)
└──────────────────────────────┘
```

### Stage-by-stage gap summary

| Stage | Exists | Missing | Gap refs |
|---|---|---|---|
| 1 Input | yes | nothing required for the contract | — |
| 2 Configuration snapshot | scoring only | comparison/eligibility/severity snapshot; config revision history | G2, G10 |
| 3 Run context | batch audit only | per-run identity, engine version, policy tuple | G1, G4 |
| 4 Engine execution | yes | method-selection reason, raw-vs-final score | G7, G8 |
| 5 Policy evaluation | most decisions | gate decision, unconditional cap record, threshold + source | G5, G6, G7 |
| 6 Provenance capture | substantial | envelope, revision trail, reproducibility status | G3, G13 |
| 7 Storage | yes | non-destructive replacement | G3 |
| 8 API | yes | provenance envelope, stored band in reports | G6 (display), §10 |
| 9 UI | yes | provenance badge, three-value display, threshold source | §10.8 |

---

## Deliverable C — Field mapping

Columns: proposed field → existing DB field → existing code source → proposed storage → result types.

| Proposed field | Existing DB field | Existing code source | Proposed storage | Result types |
|---|---|---|---|---|
| `result_id` | `id` (integer, recycled by delete/insert) | table PK | keep PK + add `result_uuid` | alert, layered, score |
| `result_key` | implicit unique key | `_identity_key` (`api/quality_alerts.py`), `UniqueConstraint(hospital_id, analysis_code, month)`, `canonical_identity.stored_identity` | derived, stored in envelope | alert, layered |
| `superseded_by` | — | — | new scalar | alert, layered, score |
| `run_id` | — | — | new scalar + `analysis_runs` | all |
| `engine_version` | — | none (searched: 0 matches) | new scalar | all |
| `engine_semantics` | — | `layered.py` module (implicit) | new constant + run row | layered, alert |
| `engine_dirty` | — | — | run row | all |
| `policy.comparison` | `history_provenance.policy_version`, `peer_provenance.policy_version`, `evidence.comparison_policy.version` | `comparison_policy.COMPARISON_POLICY_VERSION`, `resolve_comparison_policy` | `policy_registry` ref + digest | alert, layered |
| `policy.severity` | `evidence.severity_policy.fingerprint` | `severity.policy_fingerprint` | registry ref (version) + keep fingerprint | alert |
| `policy.eligibility` | `classification_provenance.cap`, `.min_peers_for_top_band`, `evidence.dispersion`, `.thin_peer_group`, `.pct_change_cap` | `layered.ZERO_SPREAD_LEVEL_CAP`, `THIN_PEER_LEVEL_CAP`, `MIN_PEERS_FOR_TOP_BAND`, `cap_pct_change`, `cap_zero_spread`, `cap_thin_peer` | registry ref | alert, layered |
| `policy.scoring` | `scoring_fingerprint`, `scoring_config` | `scoring.scoring_config_fingerprint` / `_snapshot` | registry ref + existing columns | score |
| `policy.registry_formula` | `formula_version` (alerts); none on layered | `IndicatorDefinition.formula_version` | direct | alert, layered |
| `policy_digest` | — | — | new scalar | all |
| `config_fingerprint` | `scoring_fingerprint` (score only) | `scoring_config_fingerprint`, `severity.policy_fingerprint` | new scalar (64 hex); run row | all |
| `config_snapshot_ref` | `scoring_config` (score only) | `scoring_config_snapshot` | `analysis_runs.config_snapshot` | all |
| `threshold.value` | `evidence.z_threshold` (alerts); `classification_provenance.zscore_threshold` (layered, 217 rows) | `pipeline._save_layered_results`, `quality_alerts` evidence build | direct (exists) | alert, layered |
| `threshold.source` | — (currently implicit fallback) | `quality_alerts.stored_threshold` → `layered.gate_threshold` | direct (new rows) / derived (legacy) | alert, layered |
| `inputs.current` | `current_value`, `raw_value` | engine | direct (exists) | alert, layered |
| `inputs.previous` | `previous_value` | engine | direct (exists) | layered |
| `inputs.window.months` | `history_provenance.months` | `comparison_policy.history_window` | direct (exists) | alert (`evidence.history`), layered |
| `inputs.window.values` | `history_provenance.values` | same | direct (exists) | alert, layered |
| `inputs.window.skipped` | `history_provenance.skipped_months` | `HistoryWindow.skipped_months` | direct (exists) | layered (alerts: absent) |
| `inputs.peer_ids` | `peer_provenance.peer_ids`; `evidence.peer_ids[:50]`; `evidence.comparison_policy.peer.peer_ids` | `quality_alerts.get_stored_peer_ids`, `comparison_identity.resolve_peer_ids` | direct (exists; remove truncation for new rows) | alert, layered |
| `inputs.peer_values` | `peer_provenance.values` (array); `evidence.comparison_policy.peer.values` (object) | `peer_provenance` writer | direct (exists; unify shape) | alert, layered |
| `inputs.peer_group` | `peer_provenance.group`; `evidence.comparison_policy.peer.group` | `DETECTION_PEER_GROUP`, `stratified_peer_group` | direct (exists) | alert, layered |
| `inputs.eligible_count` | `peer_provenance.eligible_count` | engine | direct (exists) | layered |
| `method.chosen` | `outlier_method`, `method` | `layered.choose_method` | direct (exists) | alert, layered |
| `method.reason` | — | `choose_method` inputs (CV, n, mean, indicator type) | new key in envelope | alert, layered |
| `score.raw` | — (overwritten by capped value) | `score_window_detail` (pre-cap) | new key | alert, layered |
| `score.final` | `score`; `historical_outlier_score` | engine | direct (exists) | alert, layered |
| `caps[]` | `classification_provenance.cap`, `.zero_spread_layers`, `.thin_peer_layers`; `evidence.dispersion`, `.thin_peer_group`, `.pct_change_cap` | cap functions | direct (exists, normalise into one array) | alert, layered |
| `gate.decision` | — (read-time only) | `layered.very_high_eligibility`, `row_level_assessment`, `quality_alerts.top_band_gate` | derived + audit snapshot for new rows | alert, layered |
| `band.stored` | `severity`; `outlier_level` | write path | direct (exists) | alert, layered |
| `formula.identity` | — (implicit) | `canonical_identity.alert_identity`, `resolved_identity` | new key | alert, layered |
| `formula.text` / `unit` | `formula`, `unit` (alerts only) | registry copy at scan time | direct (exists; add to layered) | alert, layered |
| `reproducibility_status` | — | `provenance.classify` (proposed) | new scalar (new rows) / derived (legacy) | alert, layered |
| `provenance_schema` | — | — | new scalar | all |
| `period` | `month` | — | direct (exists) | all |
| `created_at` | `created_at`, `detected_at` | defaults | direct (exists; not a write clock — D14 §B) | all |

---

## Deliverable D — Scope manifest

Everything changed or created during D15, classified as required.

| Path | Classification | Note |
|---|---|---|
| `qa-d15/D15-OUTLIER-PROVENANCE-ARCHITECTURE.md` | **D15 report artifact** | Deliverable A (created this phase) |
| `qa-d15/D15-APPENDICES-B-C-D.md` | **D15 report artifact** | Deliverables B, C, D (created this phase) |
| 65 modified tracked files (e.g. `app/engine/anomaly/layered.py`, `app/api/quality_alerts.py`, `tests/test_dashboard_analysis_ux.py`) | **Pre-existing work** | Present at D15 baseline (HEAD `4b82b19`, 65 modified / 12,489 insertions / 857 deletions); not touched |
| 72 untracked entries — including `app/engine/comparison_policy.py`, `app/engine/quality/outlier_eligibility.py`, `app/engine/quality/scoring_audit.py`, `alembic/versions/{a1c2e3f4b5d6,c3d4e5f6a7b8,d6f7a8b9c0d1,e1f2a3b4c5d6,f5a6b7c8d9e0}_*.py`, `docs/*.md`, `scripts/*.py`, `tests/test_*.py`, `qa-d10*/`, `qa-d11/`, `qa-d12/`, `qa-d14/`, `static/js/explain-prose.js`, `.cloud-attachments/` | **Pre-existing work** | Present at D15 baseline; content read for design, never modified |
| `qa-d14/D14-HISTORICAL-PROVENANCE-AUDIT.md` | **Pre-existing work (read only)** | Contains two claims D15 corrects in §2.5; the file was **not** edited |
| `.claude/`, `.freebuff/` runtime files | — | not inspected or modified |
| **Mixed / uncertain ownership** | **none** | No file was edited, created or deleted in D15 beyond the two artifacts above |

### Baseline facts used for the manifest

- Branch `very-high-gate-integration`, HEAD `4b82b19388f0b8568ca8c33c62a9b5f7aa60daac`.
- `git status --porcelain` → 137 entries (65 modified + 72 untracked entries; directories such as `qa-d14/` count as one entry).
- `git diff --cached` → empty (0 staged); `git diff --stat` → 65 files changed, 12,489 insertions(+), 857 deletions(-).
- `git stash list` → `stash@{0}` "revert-to-4b82b19 requested by user 2026-10-24T09:12:41Z", `stash@{1}` "other-thread-wip-during-comparative-why" — both untouched.
- No listener on ports 8000 / 3000 / 5173 / 8501 (no application server running, none started).
- D15 opened **no database connection** at all — no `SELECT`, no write, no migration; all architectural claims come from source inspection plus the D14 measurements.

### Post-D15 verification (same phase, after writing the artifacts)

| Check | Baseline | After D15 | Delta |
|---|---|---|---|
| Branch / HEAD | `very-high-gate-integration` / `4b82b19` | identical | none |
| `git status --porcelain` entries | 137 | **138** | +1 = untracked `qa-d15/` |
| Modified tracked files | 65 | 65 | none |
| Staged files | 0 | 0 | none |
| Stashes | 2 | 2 | none |
| `alembic/` modified files | 0 | 0 | none |
| Application server on 8000/3000/5173/8501 | none | none | none |
| Test files added or modified by D15 | — | 0 | the 48 `tests/` porcelain entries are all pre-existing (present in the baseline listing) |
