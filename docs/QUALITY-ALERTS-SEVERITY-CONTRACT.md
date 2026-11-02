# Quality Alerts — stored vs effective severity

**Audience:** anyone querying `quality_alerts` directly (BI, SQL reports, exports) or
consuming `GET /quality-alerts/issues`.

## The contract

| Layer | Field | Meaning |
|---|---|---|
| Database | `quality_alerts.severity` | The band the row was scored at **before** the Very-High eligibility caps. |
| API issue | `effective_severity` | **The authoritative band for operational reporting.** Cap applied. |
| API issue | `primary_severity` | Same value as `effective_severity` (kept for existing consumers). |
| API issue | `stored_severity` | The pre-cap band of the issue's primary row, i.e. `quality_alerts.severity`. |
| API issue | `primary_severity_cap` | Why a cap applied (`stored_severity`, `resolved_level`, `final_level`, `reason`, `policy`), or `null` when none did. |

`primary_severity`/`effective_severity` is what the screen shows, what the Very High
counts count, and what every KPI on the Quality Alerts screen uses. `stored_severity`
exists so the difference stays traceable — a cap is disclosed, never silently applied.

## Why they differ

A comparison can score into the top band while its own dispersion is too thin to
support it. `app/engine/quality_alerts.py::severity_cap` then resolves the issue to a
lower `final_level` and stores the reason under
`primary_severity_cap.very_high_eligibility` (for example
`reason: DISPERSION_BAND_BELOW_VERY_HIGH`, `resolved_level: VERY_HIGH`,
`final_level: HIGH`). Stored rows are never rewritten by this step.

On the live store (2026-11) **1,073 of 2,658 issues carry a cap record**, and the two
counts diverge accordingly:

| Measure | Value |
|---|---|
| Issue groups with `severity = 'VERY_HIGH'` (SQL, pre-cap) | 947 |
| `summary.very_high_issues` (effective) | **801** |

## How to report correctly

- **Use the API** for any risk figure: `GET /quality-alerts/summary`
  (`very_high_issues`, `very_high_only_issues`, `mixed_severity_issues`) and
  `GET /quality-alerts/issues` (`effective_severity` per issue).
- **If you must use SQL**, treat `severity` as provisional. There is no
  band-after-cap column in the database; the cap is computed from the row's stored
  evidence (`evidence.stats`, method, peer count, series, perspective). A SQL
  consumer that needs effective bands should read the API rather than re-derive
  caps — re-deriving them is how a report drifts from the screen.
- **Never** present `severity` and `effective_severity` as two findings for the same
  issue: they are one finding and its audited band.

## Verifying

```
GET /quality-alerts/summary            -> very_high_issues == 801 (live 2026-11 baseline)
GET /quality-alerts/issues?page_size=0 -> sum(issue.effective_severity == "VERY_HIGH") == 801
                                          every issue: effective_severity == primary_severity
```

Any change to these numbers must come from new data or a re-scan, never from a
reporting query.
