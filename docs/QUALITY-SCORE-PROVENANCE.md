# Quality Score provenance and controlled recomputation

## Why

Stored Quality Scores were not reproducible. The scoring code read the outlier
multiplier from `AppConfig["outlier_multiplier"]` (seeded as **2.0** in
`app/main.py`), but the isolated fallback in two penalty functions was **1.5**.
Any calculation path without an AppConfig row therefore used a different
policy from every path that loaded one — silently, and without leaving any mark
on the stored score.

The approved multiplier is **2.0**. It is now a single constant
(`OUTLIER_MULTIPLIER_DEFAULT` in `app/engine/quality/scoring.py`) used by both
penalty components (classic anomalies and layered/data-tree outliers). A saved
AppConfig value still overrides it; the fallback is no longer a second policy.
`PREVIOUS_OUTLIER_MULTIPLIER = 1.5` exists only so the audit can *recognise*
rows produced by the old hidden fallback — it is never used to write scores.

## What a stored score records

`quality_scores` gains two nullable columns:

| Column | Meaning |
|---|---|
| `scoring_fingerprint` | 16-char SHA-256 digest of the fully resolved configuration |
| `scoring_config` | that resolved configuration, verbatim (JSON) |

The fingerprinted settings are the four component weights, the outlier
multiplier and the four severity weights — everything that can move a score.
Missing keys resolve to the canonical defaults before hashing, so a DB with no
AppConfig rows and a DB with the seeded rows produce the same fingerprint.

Rows written before this change have `NULL` provenance. They are **unknown, not
wrong**: see identification below before assuming anything.

All score writers stamp provenance through `apply_score_update()`:

* `_save_quality_score` (full analysis and revalidation),
* Dashboard → recalculate completeness,
* Indicators → toggle/recalculate (`_recalc_hospital_scores`),
* Admin → shallow repair.

Every numeric overwrite first appends a row to `quality_score_revisions`
(previous/new score and components, previous/new fingerprint, full previous
snapshot, configuration used, actor, action, timestamp). A recalculation can
therefore never erase the evidence of what it replaced.

## Identifying affected history

`GET /admin/quality-scores/scoring-audit` (read-only) reports:

* counts by provenance state — `current`, `previous_configuration`,
  `other_configuration`, `unknown` (no fingerprint);
* `affected_count`: rows whose stored score/outlier penalty differ beyond the
  0.1 rounding tolerance from a recomputation under the approved configuration;
* `recomputable_count`: rows that can be recomputed from persisted outlier rows;
* `needs_deep_recompute`: rows with no persisted outlier rows (recomputation
  must rerun detection from raw indicator values via the existing deep repair);
* `unreconciled_count`: rows whose stored penalty matches neither the approved
  nor the previous configuration — left untouched;
* `items`: one entry per stored score with a `penalty` block reporting the
  approved `eligible` denominator, the number of `evaluated` layered rows,
  `matches`, and `scored_under_evaluated_rows_denominator` for rows written
  under the old row-count divisor (see `OUTLIER-PENALTY-DENOMINATOR.md`).

Layered recomputation uses the approved eligible denominator, not the number of
persisted rows. A stored layered score written under the old divisor is
reported as not matching; it is never silently rewritten by the audit.

Identification combines two independent signals: the stored fingerprint, and a
recomputation from the persisted `layered_outlier_results` / `anomaly_results`.
A legacy row with no fingerprint is reported as affected only when its stored
numbers themselves reproduce under the old multiplier. A legacy row whose
numbers match the approved configuration stays `unknown` and is not touched.

## Controlled recomputation

`POST /admin/quality-scores/recompute`

| Parameter | Default | Meaning |
|---|---|---|
| `apply` | `false` | dry run; `true` writes the changes |
| `hospital_id` | all | scope |
| `month_from`, `month_to` | all | scope (inclusive, `YYYY-MM`) |

The recompute reuses the persisted outlier rows and the stored rule/
completeness/consistency components. It does **not** rerun detection, so the
same stored inputs and configuration always produce the same result. The
outlier source (layered vs classic) is chosen by which stored penalty the rows
reproduce; when neither matches, the row is reported and skipped.

Operational sequence for a real deployment:

1. **Back up** the database (and note the current `scoring_fingerprint`).
2. Run the audit and review `needs_deep_recompute` /
   `unreconciled_count`.
3. Run `POST /admin/quality-scores/recompute` without `apply` and archive the
   dry-run response (it lists every intended change).
4. With explicit approval, run it with `apply=true`.
5. Rows needing a deep recompute are handled separately by
   `POST /admin/quality-scores/repair?deep=true`, which reruns the full engine
   pipeline from raw values (same audited writer, so revisions are recorded).
6. Verify with `GET /admin/quality-scores/{hospital_id}/{month}/revisions`.

Nothing here runs automatically, and no production-wide recalculation is part
of the migration.

## Migration

`alembic/versions/d6f7a8b9c0d1_add_quality_score_scoring_provenance.py`
(`down_revision = c9d0e1f2a3b4`) adds the two columns, their index and
`quality_score_revisions`. It is idempotent (safe when a fresh database was
bootstrapped with `create_all` + stamp) and reversible. It preserves existing
rows with `NULL` provenance and performs no backfill.
