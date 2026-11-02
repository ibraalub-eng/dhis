# Layered Outlier Penalty Denominator

Status: approved policy (2026-10-24)

## The defect

The layered Quality Score outlier component is

```
outlier_penalty = min(1.0, flagged_units / denominator × outlier_multiplier)
```

where `flagged_units` counts distinct rows whose `outlier_level` is `HIGH` or
`VERY_HIGH`. The denominator used to be **the number of layered rows that
happened to be evaluated**. A row exists only when the hospital reported the
element (or the rate could be computed), so an incomplete month had fewer rows:

| Month | Required units | Reported | Flagged | Old penalty (2.0×) |
|---|---|---|---|---|
| Complete | 40 | 40 | 1 | 1/40 × 2 = **5%** |
| Sparse | 40 | 1 | 1 | 1/1 × 2 = **100%** |

A single finding became a maximum penalty purely because the month was
incomplete. Completeness already scores that missingness; the outlier
component must not punish it a second time.

## Approved denominator

`pipeline.get_outlier_eligible_codes(db, hospital_id, month, evaluated_codes=...)`
returns the set of assessment units the hospital is required to be assessed on
for that month. Its logic lives in `app/engine/quality/outlier_eligibility.py`.

| Category | Rule | Rationale |
|---|---|---|
| **Required** (`requirement_type = 'Required'`, NULL treated as Required) | Always included, reported or missing. | A reporting gap must not shrink the divisor. A missing required unit has no row and therefore counts as *not flagged*; completeness owns the gap. |
| **Optional** (`requirement_type = 'Optional'`) | Included only when the element was assessed (its code is in `evaluated_codes`). | Absence of an optional element is a legitimate non-event. If it was reported and assessed, it is a real assessment unit. |
| **Optional by inheritance** | A Required node whose entire source subtree is Optional follows the Optional rule: included only when that node itself was assessed. | The form never asks for it, but an explicitly assessed parent/child is still analysable. |
| **Manually disabled** | Excluded (hospital override wins over the monthly default). | The approved configuration says this hospital/month is not assessed on it. |
| **Covered by a total** | Excluded when the same child absence is already covered by a reported total, using the shared `compute_covered_codes` rule. | There is nothing of its own to analyse; this matches the completeness denominator. |
| **Auto-disable-on-null** | **Not applied.** A required element is not removed because its value is missing. | Auto-disable is a completeness rule. Applying it here would recreate the original defect: missing data would shrink the denominator and inflate the penalty. |
| **Synthetic labels** | Never eligible. | They are form headers, not assessments. |
| **Derived rates** | Included only when the rate was evaluated **and** all numerator/denominator inputs are eligible. | A rate built on Optional, disabled or covered data is not a required assessment. |

`evaluated_codes` is normally the set of `analysis_code` values on the
hospital+month `LayeredOutlierResult` rows. Required elements are added even
when they have no row; Optional elements and rates must appear in that set.
When no set is supplied, reported non-NULL values are treated as assessed.

The denominator is a `set`, so a rate whose code collides with an element code
is counted once. The result is deterministic: order of rows cannot change it.

## Zero versus missing

- **Zero** is a reported value. A required element with value `0` stays in the
  denominator, produces a normal layered row, and may be flagged. An Optional
  element with value `0` was assessed and is eligible.
- **Missing** (no value, or `NULL`) also stays in the denominator for Required
  elements, but has no row and therefore cannot contribute to the numerator.
  For Optional elements it is absent from the denominator entirely.

## Numerator and range

Every flagged row is counted, including a defensive case where a flagged row's
code is not in the eligible set. A denominator bug must never hide a finding.
The penalty is `min(1.0, flagged / max(len(denominator), 1) × multiplier)`, so:

- an empty denominator yields `0.0`, not a division error;
- the result is always within `[0, 1]`;
- repeated runs on the same rows and configuration are identical.

## Separate from completeness

Completeness is `filled required values / (required codes − covered required
codes)`. The outlier denominator is the *set of required assessment units* and
points in the opposite direction: a missing required observation lowers
completeness while leaving the outlier denominator unchanged (and adding no
flagged numerator). No missing observation is penalized through both components
as if it were an outlier.

## Where it is applied

| Surface | Behaviour |
|---|---|
| `pipeline.run_full_analysis` | Computes the eligible set from the live layered rows and passes it to `calculate_quality_score`. |
| `pipeline.revalidate_hospital_months` | Recomputes from the stored `LayeredOutlierResult` rows with the same eligible set. |
| `quality.scoring.calculate_quality_score` | Accepts `outlier_eligible_codes` (alias `eligible_codes`); without it, the legacy row-count denominator is kept for DB-free callers. |
| `quality.scoring_audit` | `identify_scores` reports per-month `eligible`, `evaluated`, `matches`, and whether the stored value was scored under the old evaluated-rows denominator; recompute uses the eligible denominator. |

Existing stored scores were computed with the old divisor and are **not**
rewritten automatically. Use the reading-only scoring audit / recompute
endpoint to identify and, if desired, apply the corrected component. Detection,
thresholds, severity classes and the outlier multiplier are unchanged.
