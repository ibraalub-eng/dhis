# D16-A3 — Design Review: Policy Snapshot Authority, Configuration Version History, and Atomic Result Publication

**Status:** design only — this review made no application-code, schema, migration, data or git change
**Prepared against:** `very-high-gate-integration` @ `264801f` (D16-A2 accepted)
**Supersedes:** nothing. Extends `qa-d16/D16-A1-*` and `qa-d16/D16-A2-*`.
**Approval required before any implementation.**

---

## 0. Method and non-goals

Every claim about current behaviour below was read from the code at the commit above, with the
file and line given so it can be re-checked during review. No database was opened, no server was
started, no migration was written or run, and no System Control value was read from production.

Non-goals: changing any threshold, cutoff, formula, weight, cap, gate, peer policy or severity
band; re-designing the severity model; moving alerts to a different storage.

---

## 1. Findings that constrain the design

These are the facts the design has to work with. Several are defects relative to the stated goal
("operational results always represent the latest successfully completed analysis"), so they are
called out rather than papered over.

| # | Finding | Evidence |
|---|---|---|
| F1 | **Publication is not atomic.** One analysis commits five times: rule results, anomaly rows, quality score, confidence score, then layered rows. A crash between commits leaves a mixture of two runs visible. | `pipeline.py:1086` `_save_validation_results` (commit 1104), `:1107` `_save_anomaly_results` (1133), `:1306` `_save_quality_score` (1340), `:1343` `_save_confidence_score` (1373), `:1194` `_save_layered_results` (1303); call order `pipeline.py:695–709` |
| F2 | **A failed run publishes.** `run_full_analysis` catches every exception and writes a fallback `QualityScore` with score 0 — replacing the previous score for that hospital/month. The empty-data path does the same. | `pipeline.py:856–866` (no data), `:884–899` (exception) |
| F3 | **"Analysed" means "a score row exists".** `check_analysis_exists` is the cache predicate, so a fallback 0-score row also makes the month look computed for non-forced calls. | `pipeline.py:437` (early return), `:846` (`if not result.get("cached") and not check_analysis_exists(...)`) |
| F4 | **No uniqueness on the result key.** `QualityScore` has no unique constraint on `(hospital_id, month)` — only two indexes — so two concurrent runs can both insert. | `models.py:575–578` |
| F5 | **Layered rows are written last and separately**, after the score is already visible: a reader between commits sees a new score with the previous run's layered rows. | `pipeline.py:695–709` |
| F6 | **No run identity anywhere.** Result tables (`anomaly_results`, `layered_outlier_results`, `quality_scores`, `confidence_scores`) carry hospital + month only; provenance exists as `quality_scores.scoring_fingerprint/_config` and `quality_alerts.evidence.severity_policy.fingerprint`, neither of which names a run or a full policy. | `models.py:553–571`, `:822–872` |
| F7 | **Configuration saves have no history and no actor.** `PUT /config/control/settings` validates everything, writes `AppConfig`/`SystemSetting` rows and commits once — no version, no previous values, no user. The signature has no `user` dependency; only `require_permission("settings.write")` is applied. A save also silently deletes the legacy duplicate Z-score key. | `config_api.py:271–276` (signature), `:330–348` (writes + single commit), `:121–140` (`reconcile_legacy_settings`), `:344–352` (legacy delete) |
| F8 | **Read-time policy re-application is real.** Diagnostics re-applies the cap policy when listing stored rows, and the dashboard/alerts screens compare a stored fingerprint to the *current* policy. So "which policy judged this row" is today partly a read-time function, not a stored fact. | `api/analysis.py:630–699`, `api/dashboard.py:41–72`, `api/quality_alerts.py:367–372` |
| F9 | **Cache invalidation does not fire on in-place updates.** The cache epoch fingerprints `COUNT(*) FROM quality_scores`; a re-analysis updates rows in place, so the count is unchanged and cached dashboard/report payloads can outlive the new result. | `cache.py:195–239` (epoch query), `:40–55` (epoch-scoped keys) |
| F10 | **Concurrency is guarded in-process only.** The only lock near analysis is `_LATEST_RECOMPUTE_LOCK` for rules; background workers each open their own `SessionLocal`. No advisory lock, no `FOR UPDATE`, no unique publish pointer. | `api/rules.py:171,224,263,288,300`; `api/reports.py:443`; `api/analysis.py:1405`; `api/file_ops.py:463`; `api/upload.py:85` |
| F11 | **Existing audit patterns to reuse, not reinvent.** Append-only revision rows with previous/new values + fingerprints + config JSON already exist for scores, alert batches, month toggles and indicator definitions. | `models.py:581–601` (`QualityScoreRevision`), `:893–910` (`QualityAlertAudit`), `:912–930` (`HospitalMonthAudit`), `:311–330` (`IndicatorDefinitionVersion`) |
| F12 | **Explain recomputes live** from the current configuration rather than reading the stored run, so it can legitimately disagree with the published result set. | `audit/explain.py:1754–1758` |

The design below is shaped by F1–F3 and F6 in particular: without a run identity and a single
publish commit, "the current result set" cannot be defined, and configuration history alone would
not make the screens tell one story.

---

## 2. Deliverable 1 — Consumer-by-consumer migration matrix

Legend for **source today**: `stored` = reads persisted result/alert rows; `live` = recomputes
from current configuration at request time; `config` = reads System Control for display or
validation.

| Consumer | Entry point | Source today | Legacy loader still used | Target under A3 |
|---|---|---|---|---|
| **Quality Alerts list/KPIs** | `api/quality_alerts.py` | stored `QualityAlert` + current fingerprint for the "stale policy" badge (`:367–372`) | `load_analysis_config` | stored rows stamped with `run_id`; "stale" = `run.policy_digest != current_digest`; no per-request config read for the badge |
| **Quality Alerts scan** | `engine/quality_alerts.py::scan` | **snapshot** (A2) | none (A2 removed both) | unchanged; additionally records `run_id`/`policy_digest` on each row |
| **Dashboard** | `api/dashboard.py` | stored `QualityScore`/`QualityAlert`; drift count uses current fingerprint (`:41–72`) | `load_analysis_config` | stored rows of the **published run**; drift from run digests; tolerant snapshot only to render a banner |
| **Outlier Diagnostics** | `api/analysis.py::/analysis/layered*` (`:630–699`) | stored `LayeredOutlierResult`, with caps re-applied at read time (F8) | none for rows; `load_analysis_config` at `:126` for other analysis endpoints | published-run rows only; read-time caps parameterised by that run's snapshot, not current config |
| **Explain** | `engine/audit/explain.py` | **live recomputation** (`:1754–1758`), `:151` z-threshold, `:2763` comparison policy | `load_analysis_config`, `load_comparison_policy` | either read the published run's stored evidence, or keep live recomputation but label it explicitly with its own snapshot digest and never present it as the operational result |
| **Reports** | `api/reports.py` | stored `QualityScore` + `AnomalyResult`; also *triggers* `run_full_analysis` (`:422–430`, `:443`) | none | read published run; generation goes through the same publish protocol |
| **Analysis API** | `api/analysis.py` (`:1113`, `:1424`, `:126`) | triggers runs; live endpoints read current config | `load_analysis_config` | snapshot resolved per request/run; batch endpoints pass one snapshot to every hospital/month (A2 already does this for the pipeline) |
| **File operations** | `api/file_ops.py` (`:667`, `:683`, `:463`) | triggers runs; trend recompute from current config | `load_analysis_config` (`:683`) | batch resolves one snapshot and passes it; trend recompute uses that snapshot |
| **Configuration screens** | `api/config_api.py` (`:155`, `:174`, `:376`) + `admin.js` | current config, severity preview | `load_analysis_config` | read the current **configuration version**; previews evaluate a proposed version against stored base severities (pattern already exists at `:355–430`) |
| **Background workers** | `upload.py:85`, `reports.py:443`, `analysis.py:1405`, `file_ops.py:463` | each opens its own session, then re-reads config per run | inherited | one snapshot per worker batch, carried on the `AnalysisRun` |

**What A2 did not fix, and this design must:** A2 guarantees one policy *per analysis run*. It
does not guarantee that every screen reads the *same run's results* — and today several screens
(Diagnostics, Dashboard, Reports) read whatever rows are currently in the table, which F1 and F5
allow to be a mixture. Migrating the two entry points was necessary but nowhere near sufficient.

---

## 3. Deliverable 2 — Proposed configuration-history data model

Two append-only tables plus one pointer. Names are proposals; nothing here is implemented.

### 3.1 `config_version`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `version_number` | int, unique | monotonic, allocated under the save lock |
| `created_at` | timestamptz, not null | |
| `actor_id`, `actor_name` | int null / varchar | name snapshotted so the trail outlives the user (mirrors `HospitalMonthAudit`) |
| `reason` | varchar(500) null | optional free text from the save dialog |
| `source` | varchar(20) | `save` \| `restore` \| `seed` \| `repair` |
| `parent_version_id` | int null FK self | version this one replaced |
| `restored_from_version_id` | int null FK self | set only when `source='restore'` |
| `fingerprint` | char(64), indexed, not null | full SHA-256 of the canonical snapshot (A1 resolver digest + non-resolver categories, §3.4) |
| `snapshot` | JSONB, not null | complete resolved configuration, per-key provenance included |
| `validation` | JSONB null | per-key `ok`/`clamped`/`monotonic_floor`/`invalid`, plus any request-level errors |
| `settings_count` | int | sanity counter for the UI |

### 3.2 `config_version_change`

One row per **changed** setting (unchanged settings appear only inside the snapshot).

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `version_id` | int FK → `config_version`, cascade | |
| `setting_key` | varchar(120), indexed | resolver key (`severity.zscore_threshold`) where one exists, else the storage key |
| `plane` | varchar(30) | `severity` \| `alerts` \| `comparison` \| `scoring` \| `trend` \| `rules` \| `rates` \| `ml` \| `quality` \| `ui` |
| `storage` | varchar(20) | `app_config` \| `system_settings` |
| `old_value`, `new_value` | JSONB | typed values, not strings |
| `old_source`, `new_source` | varchar(20) | `database` \| `default` \| `invalid` \| `absent` |
| `validation_status` | varchar(20) | from the snapshot entry |

### 3.3 Sequencing and immutability

* A version row and its change rows are written **in the same transaction as the settings
  themselves**; a rejected save writes nothing (the existing all-or-nothing validation at
  `config_api.py:283–307` already supports this).
* No `UPDATE` or `DELETE` on either table after commit. A restore is a new version pointing at
  the old one — history is never rewritten (Finding F11's pattern).
* `version_number` is allocated under the same lock that serialises saves (§6.3), so two
  concurrent saves cannot share a number.

### 3.4 Snapshot coverage — the honest scope question

The A1 resolver covers six planes (severity, alerts, comparison, scoring, confidence, trend).
It does **not** cover `rules`, `rates`, `ml`, `quality` scoring inputs, or UI flags. A
"complete configuration snapshot" therefore has two halves:

1. `PolicySnapshot.as_dict()` — already canonical, already digested, already provenance-aware.
2. The remaining categories, read once in the same transaction and stored verbatim as
   `snapshot["other_categories"]`.

`fingerprint` = SHA-256 over canonical `{policy_digest, other_categories}`. This keeps the A1
digest meaningful while extending coverage; a phase-2 resolver expansion changes the *input*,
not the storage format.

**Open decision D5:** whether `rules` (which are data, not policy scalars) belong in the
snapshot at all. Recommendation: include their **version stamp** (rule set hash) but not every
rule body, and say so in the UI.

---

## 4. Deliverable 3 — Restore workflow

Ordered, all steps server-side and auditable:

1. **List** — `GET /config/versions?limit=&cursor=` returns version number, created_at, actor,
   reason, source, fingerprint prefix, and a one-line diff summary ("+3 −1 settings").
2. **Inspect** — `GET /config/versions/{id}` returns the stored snapshot, per-key provenance and
   the list of keys that differ from current, each with `current_source`.
3. **Preview** — `POST /config/versions/{id}/preview` returns:
   * the diff (old → new, per key, typed);
   * affected planes and which consumers depend on them;
   * the *severity impact* preview reusing the existing pattern
     (`config_api.py:355–430`: replay stored base severity + trend assessment, report how many
     alert rows would change), run against the proposed version instead of ad-hoc edits;
   * the count of published analysis runs whose `policy_digest` differs from the proposed
     fingerprint (i.e. how much becomes stale).
   No write occurs.
4. **Confirm** — `POST /config/restore` with `{version_id, reason, confirm: true}`. `confirm` is
   mandatory; a missing flag is a 400, not a default-yes.
5. **Apply** — validate every value with the existing coercion path; write settings; create a
   **new** `config_version` with `source='restore'`, `restored_from_version_id={id}`,
   `parent_version_id=<current>`; commit once.
6. **Mark, don't publish** — published analysis runs are *not* touched. Their
   `policy_digest` now differs from current, which is exactly the staleness signal the screens
   already understand (F8's fingerprint comparison, generalised). The UI must say: *"Configuration
   restored. N analyses were computed under the previous configuration and are now stale. Re-run
   analysis to publish updated results."*
7. **Re-run is explicit** — an optional "Re-analyse affected months" action lists the scopes and
   enqueues runs through the normal publish protocol. Restore itself never starts a run and never
   re-publishes old results.

Invariants: previous versions are never modified or deleted; a restore that would produce an
identical fingerprint is rejected as a no-op (or recorded with an explicit `noop` marker — open
decision D7, recommendation: reject).

---

## 5. Deliverable 4 — Current-result publication and replacement

### 5.1 Run identity — `analysis_run`

Metadata only, as the brief requires ("keep run metadata only where needed for audit and
troubleshooting"):

| Column | Notes |
|---|---|
| `id` | monotonic PK = the **fencing token** |
| `hospital_id`, `month` | scope |
| `status` | `running` \| `published` \| `failed` \| `superseded` |
| `policy_digest` | the `PolicySnapshot.digest` the run actually used |
| `config_version_id` | which configuration version was current when it started |
| `started_at`, `finished_at`, `published_at` | |
| `actor` | who/what triggered it (`system`, user, worker batch id) |
| `error` | failure text when `status='failed'` |

One `published` run per `(hospital_id, month)` enforced by a partial unique index
(`WHERE status='published'`). This is the "older run finishing after a newer run" guard: the
newer run's `id` is higher and publishing fences on it.

### 5.2 Two-phase publish inside one transaction

1. **Compute** everything with the run's snapshot (A2 already does this), writing result rows
   with `run_id` set, **without committing**. The five existing `session.commit()` calls in the
   save helpers (F1) become flushes inside one unit of work.
2. **Publish** — in the same transaction, after all rows are flushed:
   * acquire the scope lock (§6.1);
   * re-read the current published run id; **abort** if it is greater than this run's id (a newer
     run already published);
   * demote the previous published run to `superseded`;
   * delete its result rows for the same `(hospital_id, month)` — *replacement, not retention*
     (the brief forbids competing operational history; raw `IndicatorValue` input is untouched);
   * set this run `published`, stamp `published_at`;
   * commit **once**.
3. **Invalidate** the response cache epoch (§6.5) after commit.

Readers then always filter `run_id = <published run for that scope>`. Legacy rows written before
this change (no `run_id`) are treated as `legacy` and remain current until their scope is
re-analysed — a documented, temporary compatibility rule.

### 5.3 Failed and empty runs

* `status='failed'` — rows (if any) are deleted in the failure transaction; the published pointer
  does not move; the previous result set stays operational.
* Empty-data month — today this publishes a score-0 row and deletes previous results (F2). Under
  A3 it becomes a published run **only if the month genuinely has no data**, recorded as
  `status='published'` with `reason='no_data'` so "no data" remains distinguishable from "failed".
  **Open decision D1** — this changes today's behaviour and needs explicit approval; the harmless
  alternative (keep the old behaviour) leaves a known contradiction with the stated goal.

### 5.4 Alerts are not the same object as analysis results

`QualityAlert` rows carry investigation state (`status`, `assignee`, events). Deleting them at
publication would destroy review history. Recommendation (**D3**): alerts keep the current
upsert-and-deactivate semantics, gain `run_id`/`policy_digest` stamps, and are never deleted by a
publication. The scan already commits once per month (`quality_alerts.py:1943`), so it is closer
to atomic than analysis is today.

---

## 6. Deliverable 5 — Concurrency and failure handling

### 6.1 Overlapping runs, same scope
`pg_advisory_xact_lock(hashtext('analysis:'||hospital_id||':'||month))` inside the publish
transaction. Cross-process (works for multiple uvicorn workers; F10 rules out `threading.Lock`).
`SELECT ... FOR UPDATE` on the `analysis_run` row is the fallback on non-Postgres (SQLite tests).

### 6.2 Which run may publish
Rule: **the published run must be the highest `analysis_run.id` started for that scope that has
completed successfully.** A run that finishes late finds a higher id already published and marks
itself `superseded` without touching results. A run that crashes marks `failed` and moves nothing.
No wall-clock comparison is used anywhere — clocks disagree across workers; ids do not.

### 6.3 Configuration changing during a run
Each run stores the digest it resolved at entry (A2 guarantees it resolves once). Publishing does
**not** re-resolve. If the current configuration fingerprint differs at publish time, the run
still publishes (its results are internally consistent) and is flagged `policy_stale`; the UI
shows *"computed under configuration v41; current is v42 — re-run recommended."*
**Open decision D2:** the strict alternative (refuse publish, require re-run) discards completed
work whenever an operator edits a setting mid-run. Recommendation: publish + flag.

### 6.4 Partial publication
Single commit (5.2). Any exception before commit leaves no visible change. A process kill during
commit is resolved by the transaction boundary itself; the `running` run row is then recoverable
as orphaned (stale `running` rows older than N minutes are surfaced, never auto-published).

### 6.5 Stale read paths
* Cache epoch (F9) must incorporate `MAX(published_at)` across published runs and
  `MAX(updated_at)` of `quality_scores`, not just `COUNT(*)`, so an in-place re-analysis
  invalidates file caches. This is a **bug fix that publication depends on**, not an optimisation.
* Read endpoints filter on the published run id, so an in-flight run's rows are invisible by
  construction.

### 6.6 Restored configuration not yet analysed
Staleness is derived (`run.policy_digest != config_version.fingerprint`), never written by the
restore. Nothing is auto-published.

### 6.7 Failure of the publish step itself
`analysis_run.status` stays `running`; the transaction rolled back; a watchdog surfaces
`running` rows older than the configured timeout with their error, and the operator re-runs. No
automatic retry that could publish twice.

---

## 7. Deliverable 6 — Compatibility risks and unresolved decisions

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | Adding `run_id` to result tables changes every read query and every index used by the screens | high (touches Diagnostics, Dashboard, Reports, Explain) | additive nullable column + partial index; `legacy` fallback rule; migrate screen by screen behind the same helper |
| R2 | Publishing replaces rows, so any hard-coded `COUNT(*)`/`EXISTS` check changes meaning | medium | `check_analysis_exists` must consult published run, not row presence (F3) |
| R3 | Read-time cap re-application (F8) is part of the current contract | medium | caps stay read-time, but parameterised from the run's snapshot; a test must pin "old row keeps its band, filters use the run's policy" |
| R4 | Explain recomputes live and will disagree with a published run | medium | label live recomputation with its digest, or migrate Explain to stored evidence (phase 6) |
| R5 | Cache epoch currently misses in-place updates (F9) | high (silent staleness) | epoch change in phase 4, with a regression test |
| R6 | Configuration saves gain a user dependency; some callers (scripts, tests) post without auth | medium | actor optional at the model level (`system` when absent), required in the HTTP path |
| R7 | Restoring a configuration invalidates many months at once | medium | staleness list + explicit re-run queue, no automatic publish |
| R8 | Multi-instance deployments have no cross-process lock today | high | advisory locks from phase 4 onward |
| R9 | Legacy rows without `run_id` are "current" | low, temporary | documented rule + one-time backfill decision (D8) |
| R10 | `QualityScore` lacks a unique constraint (F4) | medium | add `(hospital_id, month)` uniqueness **after** confirming no duplicate rows exist in production (a read-only check, not part of this design) |

**Open decisions requiring your approval**

| # | Decision | Recommendation |
|---|---|---|
| D1 | Should a failed/empty run keep today's behaviour of publishing a score-0 row? | No — keep last good result, mark the attempt failed; this is the one deliberate behaviour change |
| D2 | Config changed mid-run: publish-and-flag, or refuse? | publish and flag `policy_stale` |
| D3 | Do alert rows get replaced at publication? | No — they carry review state; stamp + deactivate only |
| D4 | Should restore auto-re-run affected analyses? | No — list and enqueue explicitly |
| D5 | Snapshot scope: resolver planes only, or all categories? | All categories, with `rules` stored as a hash + version |
| D6 | Retention of superseded analysis rows | Metadata only, per the brief; optional export for audit |
| D7 | Restore to an identical configuration | Reject as a no-op |
| D8 | Backfill `run_id` for legacy rows | No backfill; treat as `legacy` and replace on next successful run |

---

## 8. Deliverable 7 — Phased implementation plan with tests

Each phase is independently reviewable and leaves the system working. No phase changes a
threshold, formula or band.

| Phase | Content | Tests that must exist before merge |
|---|---|---|
| **A3.1 — Resolver completion (no consumer change)** | extend the resolver to `rules`/`rates`/`ml`/`quality` + config fingerprint service; keep A1/A2 parity | parity for every new plane; digest stability; still no new consumer |
| **A3.2 — Configuration history (write path only)** | `config_version` + `config_version_change`; hook the save transaction; actor plumbing; read API | version created on every save; no version on rejected save; old versions immutable; concurrent saves get distinct numbers; diff content correct |
| **A3.3 — Restore workflow** | preview/diff/confirm/apply; new version with `restored_from`; staleness count | restore writes a new version and never edits history; missing `confirm` → 400; restored values equal the stored snapshot; no analysis row touched; no auto re-run |
| **A3.4 — Run identity and atomic publish** | `analysis_run`; `run_id` stamps; single commit; advisory lock; fencing; cache epoch fix | one published run per scope; late older run → `superseded`; failure → pointer unmoved; partial commit invisible; two concurrent runs produce one published result; cache invalidated on in-place update |
| **A3.5 — Consumer migration** | Diagnostics, Dashboard, Reports read published run; alerts stamping; Explain labelled | each screen returns identical numbers before/after for the same published run; stale labels derived from digests |
| **A3.6 — Cleanup** | retire the 0-score fallback publication (D1), remove A2 shims once counters are zero, drop `_alerts_config` | shim counter zero over a full run; no consumer imports the removed helpers |

Regression policy for every phase: the 281-test A2 baseline plus the specific suites for the
touched consumer, measured **before** and **after** the phase, with any delta explained.

---

## 9. Deliverable 8 — Files that would likely be affected

Ownership is stated as of this design review. "Pre-existing" means the file already carried
uncommitted work before D16 began; "mixed" means it holds pre-existing changes **and** D16 work.
The tree is clean at review time (all D16 work is committed in `264801f`), so these labels
describe **provenance**, not current git status. Before implementation, re-check ownership with
`git log --follow` on each file rather than trusting this table.

**New files created by D16 (committed in `264801f`)**
* `app/engine/config_resolver.py` (A1)
* `app/engine/policy_view.py` (A2)
* `tests/test_config_resolver.py`, `tests/test_policy_snapshot_integration.py` (A1/A2)
* `alembic/versions/<new>_config_versions.py`, `..._analysis_runs.py` (proposed, not written)
* `app/engine/config_history.py`, `app/engine/publish.py` (proposed services)
* `tests/test_config_history.py`, `tests/test_restore_workflow.py`,
  `tests/test_analysis_publication.py`, `tests/test_consumer_consistency.py`

**Pre-existing modified — expected to change**
`app/models.py`, `app/engine/pipeline.py` (mixed), `app/engine/quality_alerts.py` (mixed),
`app/api/config_api.py`, `app/api/dashboard.py`, `app/api/analysis.py`,
`app/api/quality_alerts.py`, `app/api/reports.py`, `app/engine/audit/explain.py`,
`app/main.py` (seed/defaults only, if versions need a baseline), plus the screens
`static/js/admin.js`, `static/tabs/quality-alerts.html`, `static/tabs/dashboard.html`.

**Mixed ownership — extra care required**
* `app/engine/pipeline.py` — pre-existing edits + A2 snapshot plumbing + this publication work.
* `app/engine/quality_alerts.py` — pre-existing edits + A2 scan migration + run stamping.
* `app/engine/anomaly/trends.py` — A2 shim is the only change today; A3 cleanup edits it again.
* `tests/test_config_resolver.py` — A1 artifact amended once in A2 (§7 of the A2 report).

**Clean tracked files that would change (currently unmodified)**
`app/api/file_ops.py` (`:683` config read), `app/cache.py` (epoch), `app/engine/severity.py`
(only if the fingerprint service moves there), `app/tasks.py` (background task ids, if batches
are tracked as runs).

**Explicitly not changed by this design**
`app/engine/anomaly/layered.py`, `app/engine/anomaly/zscore.py`, `app/engine/comparison_policy.py`,
`app/engine/quality/scoring.py` and every frozen constant: no algorithm, cap, gate or weight is
in scope.

---

## 10. What I need from you

Approval of, or corrections to, these points before any code is written:

1. **D1** (failed/empty run must not publish) — the only deliberate behaviour change.
2. **D2** (publish-and-flag when configuration changed mid-run).
3. **D3** (alert review state survives result replacement).
4. **D5** (snapshot covers all categories, with `rules` as a version stamp).
5. **D6** (no retention of superseded analysis rows — metadata only).
6. Phase order in §8, and whether A3.1 (resolver completion, no consumer change) should be the
   first implementation increment.

No code, schema, migration, data or git state has been touched by this review.
