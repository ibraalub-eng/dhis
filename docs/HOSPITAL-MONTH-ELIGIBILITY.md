# Disabled Hospital/Month Eligibility

Status: implemented. This document is the single reference for how a disabled
`(hospital_id, month)` pair is treated by every output.

## The rule

A month is **disabled** for one hospital when a `SystemSetting` row exists with

```
key   = month_enabled_<hospital_id>_<YYYY-MM>
value = "false"
```

Only that exact pair is disabled. A month disabled for hospital 19 remains
active for every other hospital. Values other than `"false"` (including a
missing row) mean enabled.

`app/eligibility.py` owns the rule:

| Function | Purpose |
|---|---|
| `parse_month_setting` | Parse and validate a setting key |
| `disabled_pairs` | All disabled pairs, read fresh from `SystemSetting` |
| `is_month_enabled` / `month_disabled` | In-memory check for one pair |
| `exclude_disabled` | SQL filter shared by every query |
| `disabled_quality_scores` | Read-only inventory of hidden stored rows |
| `include_disabled_requested` | Parse the explicit historical-view flag |

No reader may re-derive the rule, and no reader filters by "all months that are
disabled anywhere" — that would incorrectly hide a month for hospitals that
still report it.

## Change audit trail

The setting row only keeps the latest value, so `PUT /config/month-settings`
appends every real change to **`hospital_month_audit`** (`app/models.py`):

| Column | Meaning |
|---|---|
| `hospital_id`, `hospital_name` | Which hospital, with the name snapshotted |
| `month` | `YYYY-MM` |
| `action` | `enabled` / `disabled` (the resulting state) |
| `previous_state` | `enabled` / `disabled` / `unset` (no setting row existed) |
| `actor_id`, `actor` | The authenticated user's id and username snapshot |
| `created_at` | When the change was saved |

Guarantees:

- **one row per real change** — re-saving the value a month already has, or
  "enabling" a month with no setting row, records nothing;
- the write is rejected before it can be audited when the month is not a real
  `YYYY-MM` (400) or the hospital does not exist (404);
- `hospital_name` and `actor` are snapshots and `hospital_id` is `SET NULL` on
  delete, so the trail outlives its subjects (same pattern as `rule_history`);
- rows are **append-only**: no reader updates or deletes them.

Read the trail (requires `settings.read`, newest first):

```
GET /config/month-settings/audit
GET /config/month-settings/audit?hospital_id=19
GET /config/month-settings/audit?hospital_id=19&month=2026-02
GET /config/month-settings/audit?limit=200
```

The **Analysis Months** card on System Control shows the same rows (month,
change, previous state, actor, time) and refreshes after every save.

## Hide is not delete

Disabled-month scores are **retained unchanged**:

- no reader deletes or rewrites them;
- `QualityScore`, revisions, validation results, anomalies and raw indicator
  values all stay in the database;
- re-enabling the pair restores it to active results immediately, with no
  analysis rerun or data reconstruction;
- the rows remain available through the audit/historical views below.

## Active readers

All of these apply the shared rule by default.

### Dashboard (`app/api/dashboard.py`)

- `/dashboard/kpi`
- `/dashboard/overview`
- `/dashboard/trend`
- `/dashboard/attention`
- `/dashboard/ranking`
- `/dashboard/hospital-performance/{hospital_id}`
- `/dashboard/component-diagnostics`

Confidence-score aggregates use the same pair rule as quality scores. The
previous-period and peer (network) comparisons exclude disabled pairs too.

### Analysis (`app/api/analysis.py`)

- `/analysis/quality-trend/{hospital_id}` (including peer averages)
- `/analysis/heatmap` (a disabled cell is returned as no data)
- `/analysis/historical/{hospital_id}` — disabled months are removed before
  the trend, the peer comparisons and the cross-hospital anomalies are
  computed; hospitals whose `last_month` is disabled cannot set that
  month's peer baseline
- `/analysis/ml` — a disabled pair contributes no input to the ML analysis,
  while the month stays available for the hospitals that still report it
  (previously ANY hospital disabling a month blanked the month network-wide)

### Outlier diagnostics (`app/api/analysis.py`)

Every stored-result reader applies the same pair rule:

- `/analysis/outliers` (AnomalyResult) — network-wide and per-hospital; the
  local month-list re-derivation is gone
- `/analysis/layered`, `/analysis/layered/summary`, `/analysis/layered/trend`,
  `/analysis/layered/heatmap` (LayeredOutlierResult) — table, chips, trend and
  grid agree with each other and with `/analysis/outliers`

### Rule failures (`app/api/analysis.py`, `app/api/alerts.py`, `app/api/rules.py`)

- `/analysis/rule-failures` (the rule-failure panel on the Outliers screen)
- `/alerts/overview` and `/alerts/list` (counts, severity split, top hospitals
  and the critical list)
- `/rules/failures` (rules-manager failure drilldown)

### Quality Alerts (`app/api/quality_alerts.py`)

- `/quality-alerts/issues` and `/quality-alerts/summary` — the issue table,
  its KPIs and its pager exclude disabled pairs, using the same rule as every
  other screen.
- The alert **detail** (`/quality-alerts/{id}`) and the audit trail keep
  returning the stored row: an investigation already opened, or a Why-popup
  link from another screen, is evidence and must not silently empty.

All of these are cache keys under `v2|analysis:` (or uncached), so toggling a
month in `/api/config/month-settings` invalidates them.

### Reports and exports (`app/api/reports.py`)

- `/reports/` (filtering happens before pagination)
- `/reports/detail/{hospital_id}`
- `/reports/generate/{hospital_id}` (GET and POST)
- `/reports/from-file/{source_file}`
- `/reports/export/{hospital_id}/pdf`
- `/reports/export/{hospital_id}/excel`

An active detail/generate/export request for a disabled month returns
**404** with a message naming the disabled month. It is rejected before any
analysis runs, so it cannot silently refresh a hidden score.

### Drilldowns and clinical views

- `/clinical/{hospital_id}` and `/clinical/analyze`
- `/root-cause/{hospital_id}` and `/root-cause/{hospital_id}/timeline`
- `/smart/drilldown/{hospital_id}/{month}` and `/smart/trend/{hospital_id}`

`/smart/drilldown/.../all` and the smart trend omit disabled months per hospital.

### Writers and audit tools (intentional exceptions)

These do not publish active results and deliberately read all stored rows:

- `app/engine/quality/scoring_audit.py` and `/admin/quality-scores/*` —
  configuration audit and controlled recomputation;
- `/admin/quality-scores/{hospital_id}/{month}/revisions` — append-only history;
- repair/recalculate endpoints and upload/import jobs — they write or
  inventory rows, they do not present a dashboard result;
- `app/engine/audit/*` and `/audit/*` — authorized historical explanation.

## Historical / audit views

Pass `include_disabled=true` to any of:

```
GET /reports/?include_disabled=true
GET /reports/detail/{hospital_id}?month=YYYY-MM&include_disabled=true
GET /reports/generate/{hospital_id}?month=YYYY-MM&include_disabled=true
GET /reports/from-file/{source_file}?include_disabled=true
GET /reports/export/{hospital_id}/excel?month=YYYY-MM&include_disabled=true
GET /reports/export/{hospital_id}/pdf?month=YYYY-MM&include_disabled=true
GET /analysis/quality-trend/{hospital_id}?include_disabled=true
GET /analysis/heatmap?include_disabled=true
GET /clinical/{hospital_id}?month=YYYY-MM&include_disabled=true
GET /root-cause/{hospital_id}?month=YYYY-MM&include_disabled=true
GET /root-cause/{hospital_id}/timeline?month=YYYY-MM&include_disabled=true
GET /smart/drilldown/{hospital_id}/{month}?include_disabled=true
```

`/reports/` marks the returned rows with `is_enabled=false`, so a historical
response can never be mistaken for an active report. This flag is the only way
an active HTTP endpoint returns a disabled month.

Read-only inventory of all hidden stored scores:

```
GET /admin/quality-scores/disabled-month-inventory
GET /admin/quality-scores/disabled-month-inventory?hospital_id=19
GET /admin/quality-scores/disabled-month-inventory?month=2026-02
```

The response reports `count`, the per-pair rows, `deleted: 0` and
`read_only: true`. It never writes.

## Current database inventory (identified, not deleted)

At implementation time the production-shaped database contains **31** stored
`QualityScore` rows for disabled pairs:

| Hospital | Name | Disabled months | QualityScore ids | Rows |
|---|---|---|---|---|
| 19 | الميداني الأردني | 2026-01 … 2026-08 | 1620–1627 | 8 |
| 29 | مستشفى العودة- جباليا | 2026-01 … 2026-08 | 1684–1691 | 8 |
| 31 | مستشفى كمال عدوان | 2026-01 … 2026-08 | 1700–1707 | 8 |
| 37 | مستشفى الشمال الميداني PRCS | 2026-01 … 2026-07 | 1796–1802 | 7 |
| 46 | (no stored score rows) | 2026-01 … 2026-07 | — | 0 |

All 31 rows have score `15.0` and no scoring fingerprint. They are historical
records and are retained. Deleting or recomputing them is an explicit,
separate administrator decision — this change only hides them from active
readers.

## Re-enabling

Set the setting to `"true"` (or remove it) through
`PUT /api/config/month-settings`. The next request reads the new state and the
months return to dashboards, reports and exports. Cache keys that can carry an
eligibility-sensitive payload include the disabled-pair signature, and the
settings endpoint also invalidates the report/analysis caches.

## Tests

`tests/test_disabled_month_eligibility.py` covers:

- the shared parser and exact-pair semantics;
- dashboard KPI/overview/trend/ranking/performance/diagnostics agreement;
- report list, quality trend and heatmap agreement;
- active 404s for report detail, generate, PDF/Excel export, clinical, root cause;
- `include_disabled=true` historical access for rows and export;
- dashboard-versus-export consistency;
- disabling after scores already exist;
- re-enabling without reconstruction;
- row counts unchanged after every read and after the audit inventory;
- the read-only disabled-month inventory endpoint;
- outlier diagnostics and all four layered endpoints agree, while the peer
  hospital keeps the same month;
- rule-failure agreement across `/analysis/rule-failures`, `/alerts/overview`,
  `/alerts/list` and `/rules/failures`;
- the Quality Alerts list and KPIs exclude the pair while the stored row is
  retained;
- historical analysis and ML ignore the disabled pair without hiding the
  month from peers.

`tests/test_month_settings_audit.py` covers the trail: actor and timestamp are
recorded, a no-op save records nothing, a first disable reports
`previous_state=unset`, the read endpoint filters and orders newest first, the
real authenticated account (not client input) is recorded, and rejected
requests leave no setting and no audit row.
