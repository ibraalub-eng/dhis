# Indicator Groups Feature — Design Specification (rev. 2)

> **Rev 2 (2026-09-28):** corrected after a full codebase review. Rev 1 assumed
> `HospitalIndicatorConfig` supported a month range (it does not), placed the
> completeness denominator in the wrong file, and backfilled `requirement_type`
> to a behavior-breaking value. All sections affected were rewritten.

## Overview

Add an **Indicator Group** management screen for Admins to logically group
indicators and apply bulk enable/disable actions across hospitals and date
ranges. The group is a **bulk action macro** — toggling it upserts member
indicator config rows, which then flow through the existing effective-state
resolution into the indicator tree.

The group itself is **never consulted at runtime**. After a bulk action
completes, the config rows are the only thing that matters — identical to how
the existing single-indicator toggles work today.

---

## Data Model

### New Tables

#### `indicator_groups`
```sql
CREATE TABLE indicator_groups (
    id INTEGER PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    scope_type VARCHAR(20) NOT NULL,  -- 'hospital' | 'all'
    hospital_id INTEGER REFERENCES hospitals(id),  -- NULL when scope_type='all'
    month_from VARCHAR(7),  -- YYYY-MM, inclusive; only meaningful when scope_type='all'
    month_to VARCHAR(7),    -- YYYY-MM, inclusive; only meaningful when scope_type='all'
    created_at TIMESTAMP DEFAULT NOW(),
    CHECK (
        (scope_type = 'all' AND hospital_id IS NULL)
        OR
        (scope_type = 'hospital' AND hospital_id IS NOT NULL)
    )
);
```

**No `is_enabled` column.** Rev 1 had a "UI state only" enabled flag; it is
dropped. A group's enabled appearance in the list view is *derived* from the
config rows its last toggle wrote (see "Derived group state" below), so a
stored flag would go stale the moment anyone edits a single indicator
afterwards.

#### `indicator_group_members`
```sql
CREATE TABLE indicator_group_members (
    id INTEGER PRIMARY KEY,
    group_id INTEGER REFERENCES indicator_groups(id) ON DELETE CASCADE,
    indicator_id INTEGER REFERENCES indicators(id) ON DELETE CASCADE,
    sort_order INTEGER DEFAULT 0,
    UNIQUE(group_id, indicator_id)
);
```

**Exclusive membership (AC #3) is enforced in the service layer, not the
schema.** Adding an indicator to a group deletes it from all other groups
first (within the same transaction). A DB-level unique on `indicator_id`
alone would forbid root-less orphans entirely, which we do not want — an
indicator may legitimately belong to no group.

### Existing Model Changes

#### `Indicator` model — `requirement_type`
```python
class Indicator(Base):
    # ... existing fields ...
    requirement_type = Column(String(10), nullable=False, server_default="Required",
                              default="Required")  # "Required" | "Optional"
```

- `server_default="Required"` makes the column safe for the startup
  `_ensure_required_columns()` self-heal path (which only adds nullable or
  server-defaulted columns) on DBs already stamped at head.
- **Backfill is `Required`, not `Optional`.** Backfilling `Optional` and then
  excluding Optional indicators from the completeness denominator would leave
  the denominator near-empty and reset every historical score on first read.
  `Required` preserves today's behavior exactly (every enabled, non-covered
  indicator counts); admins mark individual indicators `Optional` afterwards.

---

## Core Logic

### Bulk Action Execution

When admin toggles a group (via `PUT /indicator-groups/{id}/toggle`):

1. **Resolve target hospitals**:
   - `scope_type='all'` → all active hospitals (same filter as the
     never-reported bulk endpoint: `Hospital.is_active.is_(True)`)
   - `scope_type='hospital'` → the single configured hospital

2. **Resolve target months**:
   - **Only when `scope_type='all'`**: expand `month_from`–`month_to`
     inclusive; if both NULL, fall back to `_all_known_months(db)` (every
     month appearing in `indicator_values` or `indicator_default_configs`)
     — same expansion the existing `toggle-default` endpoint uses for
     `month='__all__'`.
   - **`scope_type='hospital'` ignores the date range entirely** (see the
     constraint box below). The stored `month_from`/`month_to` are still
     saved on the group for documentation purposes but are not applied.

3. **For each target hospital × month × member indicator**:
   - `scope_type='all'` → upsert `IndicatorDefaultConfig(indicator_id, month,
     is_enabled=new_state)`
   - `scope_type='hospital'` → upsert `HospitalIndicatorConfig(hospital_id,
     indicator_id, is_enabled=new_state)`

4. **Post-toggle bookkeeping** (mirrors the never-reported endpoint):
   - invalidate the smart-analytics caches:
     `_smart_cache.invalidate("smart_drilldown_")`, `"smart_trend_"`,
     `"smart_overview_"`
   - recalculate quality scores for affected hospitals via the existing
     `_recalc_hospital_scores()` / `_recalc_all_hospital_scores()`

> **⛔ HARD CONSTRAINT — hospital scope has no time dimension.**
> `HospitalIndicatorConfig` has **no month column**; a per-hospital override
> applies to *every* month for that hospital. Writing one for "March only"
> would silently disable the indicator for that hospital in all months.
> Therefore:
> - the API rejects `PUT /{id}/toggle` with `422` when `scope_type='hospital'`
>   and the request would imply month scoping is expected to apply;
> - the UI hides the date-range picker when "Specific Hospital" is selected.
>
> Extending `HospitalIndicatorConfig` with a month column was considered and
> rejected for rev 2: it changes effective-state resolution semantics in the
> pipeline, dashboard, and audit engines — a much larger blast radius than
> the feature warrants. Revisit if a real need emerges.

### Toggle semantics — explicit, not a flip

Rev 1 left the toggle semantics ambiguous. Existing single-indicator
endpoints *flip* from effective state, which is fine for one indicator but
nondeterministic for a group whose members may currently disagree. Group
toggle takes an explicit body:

```json
PUT /indicator-groups/{id}/toggle
{ "enabled": true }   // or false — idempotent and deterministic
```

"Enable All" / "Disable All" buttons each send the literal state; pressing
either twice in a row is a no-op the second time. No effective-state read is
needed to decide the direction.

### Effective State Logic (UNCHANGED)

Existing `_get_effective_state()` in `app/api/indicator_config.py` remains
the source of truth:

```
HospitalIndicatorConfig (per-hospital override)
    → IndicatorDefaultConfig (monthly default for all hospitals)
    → True (global default)
```

Group membership has **no runtime effect** — only the config rows created by
bulk actions matter. The tree reflects bulk actions automatically through
`get_effective_manual_disabled_ids()` in `app/engine/pipeline.py`.

### Completeness Calculation

`requirement_type` on `Indicator` determines whether an indicator counts
toward the completeness denominator:

- `Required` → counts in denominator (enabled, not covered by a sum rule,
  per the Coverage-Disable Doctrine)
- `Optional` → excluded from the denominator entirely (not "weighted" —
  a weighted variant would reintroduce the covered-vs-missing ambiguity the
  doctrine exists to prevent)

**The denominator is NOT computed in `app/engine/quality/scoring.py`.**
Rev 1 named the wrong file. `scoring.py` only *receives*
`active_indicator_count` from its callers. There are **three** call sites
that build the denominator and all three must apply the same
`requirement_type` filter:

| Call site | What it does today |
|---|---|
| `app/engine/pipeline.py::_compute_full_analysis` | `total_indicators - len(disabled_ids)` |
| `app/api/dashboard.py::_recalc_completeness` | doctrine §3 reference implementation (`manual_map` / `default_map` / `override_map` / `_dis()`) |
| `app/api/indicator_config.py::_recalc_hospital_scores` | same math, per-hospital loop |

Recommended shape: add a tiny shared helper (e.g.
`get_required_indicator_ids(db, hospital_id, month)` alongside the existing
disabled-id helpers in `pipeline.py`) that composes
`enabled = not disabled` ∧ `requirement_type == 'Required'`, and have all
three call sites use it. Do not re-derive the set per call site.

> **⛔ Doctrine gate (docs/COVERAGE-DISABLE-DOCTRINE.md).** Any code touching
> "required" / "missing" indicator lists is bound by the Coverage-Disable
> Doctrine and its guard test (`tests/test_ui_doctrine_docs.py`). The
> `requirement_type` exclusion is a new path in the covered/disabled gate, so:
> 1. document it in the doctrine (a §3-style entry: `requirement_type =
>    'Optional'` is a third legitimate reason an indicator is absent);
> 2. extend the doctrine checklist in §6;
> 3. add protection tests next to `tests/test_covered_children.py` /
>    `tests/test_recalc_scores.py` proving Optional indicators are excluded
>    from the denominator *and* still appear correctly when re-marked
>    Required.
> Skipping this recreates the exact bug class the doctrine was written to
> prevent ("Why?" popup flags a missing indicator that completeness forgives).

---

## API Endpoints

All endpoints mount on a new router registered in `app/main.py`:
`app.include_router(indicator_groups.router)`.

**Permission gating** (rev 1 omitted auth entirely): read endpoints use
`require_permission("settings.read")`, mutation endpoints use
`require_permission("settings.write")` — consistent with the
indicator-config router.

### Indicator Groups
| Method | Path | Description |
|--------|------|-------------|
| POST | `/indicator-groups` | Create group (name unique, scope, optional months) |
| GET | `/indicator-groups` | List groups with member counts and derived enabled state |
| GET | `/indicator-groups/{id}` | Group detail with ordered members |
| PUT | `/indicator-groups/{id}` | Update name/description/scope/months |
| DELETE | `/indicator-groups/{id}` | Delete group (cascades to members) |
| PUT | `/indicator-groups/{id}/toggle` | **Bulk action** — body `{"enabled": bool}`; 422 on hospital scope misuse (see constraint box) |
| POST | `/indicator-groups/{id}/members` | Add indicators to group (bulk; evicts from other groups — exclusive membership) |
| DELETE | `/indicator-groups/{id}/members/{indicator_id}` | Remove indicator from group |
| PUT | `/indicator-groups/{id}/members/reorder` | Reorder members (`sort_order`) |

### Derived group state (list view)

Instead of a stored `is_enabled`, `GET /indicator-groups` derives per group:

- `scope_type='all'` → member is "enabled" iff no
  `IndicatorDefaultConfig(indicator_id, any month).is_enabled == false`
  exists (mirrors `_get_default_state(month='__all__')` semantics); group
  state = all members enabled.
- `scope_type='hospital'` → member is enabled iff
  `HospitalIndicatorConfig(hospital_id, indicator_id)` is absent or
  `is_enabled=True`; group state = all members enabled.

This stays correct when a user toggles a single member outside the group
afterwards — a stored flag would not.

### Indicator Requirement Type
| Method | Path | Description |
|--------|------|-------------|
| PUT | `/hospitals/indicators/{id}/requirement-type` | Set Required/Optional |

**Path note (rev 1 correction):** all indicator mutation endpoints live
under the `/hospitals` prefix in `app/api/indicator_config.py` today
(`/hospitals/indicators/{id}/toggle`, `/toggle-default`, `/weight`, …). The
new endpoint follows that convention and lands in the same router rather
than introducing a parallel `/indicators` prefix.

---

## Admin UI

The frontend is a **vanilla-JS static app** (`static/js/*.js`, no framework,
no build step). Rev 1's "Components: GroupList, GroupForm, IndicatorTreePicker"
implied a component framework; the real work is:

- a new static JS module (e.g. `static/js/indicator-groups.js`) wired through
  `static/js/app.js`;
- a sidebar entry via `app/menu_registry.py` + permission check, following
  the existing admin screens (see `static/js/settings.js`,
  `static/js/rules-manager.js` for structure);
- Arabic labels via `static/js/i18n.js`, consistent with the rest of the UI.

### Group List View
- Table: Name | Description | Scope | Date Range | Members Count | Derived Enabled Toggle | Actions
- "Create Group" button
- Toggle column shows the derived state; clicking sends the explicit
  `{enabled: !current}` to the toggle endpoint.

### Group Detail / Create View
- **Basic Info**: Name, Description
- **Scope Selector**: Radio — "All Hospitals" | "Specific Hospital" (dropdown).
  Selecting "Specific Hospital" **hides and clears** the date-range inputs
  (server enforces the same rule).
- **Date Range** (scope=all only): From Month (YYYY-MM) | To Month (YYYY-MM) —
  both optional; empty = all known months.
- **Members Panel**:
  - Left: indicator tree (read-only, checkable) — reuse the tree-fetching
    logic from `static/js/tree.js` against the tree config API
  - Right: selected members list (draggable for ordering)
  - "Add Selected" / "Remove" buttons
- **Bulk Toggle**: "Enable All" / "Disable All" buttons (explicit body).

### Indicator Tree Integration
- No changes to tree structure or effective-state resolution.
- Tree displays effective state from existing configs; bulk actions reflect
  immediately after the standard config-invalidation path.

---

## Migration Strategy

1. Alembic migration `add_indicator_groups`:
   - create `indicator_groups` and `indicator_group_members`;
   - add `indicators.requirement_type` with `server_default='Required'`.
2. Backfill `UPDATE indicators SET requirement_type = 'Required'` —
   a no-op for rows created after the server_default lands, and the correct
   value for rows created before.
3. No data migration for groups (start empty).
4. `_ensure_all_tables()` / `_ensure_required_columns()` at startup
   additionally self-heal drifted databases (missing tables/columns) —
   the server_default is what makes the column-heal path safe.

---

## Testing Scenarios

1. Create group "Maternal Health" with indicators 10, 11, 12; scope=all;
   months=2026-01 → 2026-12.
2. Toggle OFF (`{"enabled": false}`) → verify `IndicatorDefaultConfig` rows
   with `is_enabled=False` for exactly those indicators × those months.
3. Verify tree shows indicators disabled for all hospitals in those months.
4. Toggle ON → verify configs updated to True. Toggle ON again → no-op
   (idempotent).
5. Create group "NICU" with indicator 16; scope=hospital A; **no date range
   applies**. Toggle OFF → verify `HospitalIndicatorConfig` created for
   Hospital A only.
6. Verify Hospital B unaffected, and Hospital A's indicator 16 remains
   enabled in months where it had no override — i.e. understand the override
   is month-agnostic (this is the documented constraint, not a bug).
7. Attempt `PUT /{id}/toggle` on a hospital-scoped group with month
   expectations → 422 (contract test for the constraint box).
8. Add indicator 10 to a second group → verify it was evicted from the first
   (exclusive membership).
9. Set indicator 10 to `Optional` → verify all three completeness call sites
   exclude it from the denominator (pipeline, dashboard recalc,
   `_recalc_hospital_scores`), and that re-marking Required restores it.
10. Doctrine guard: run
    `pytest tests/test_covered_children.py tests/test_explain_covered_missing.py tests/test_recalc_scores.py tests/test_ui_doctrine_docs.py -q`
    green after the completeness change.

---

## Files to Modify/Create

### New Files
- `app/models.py` — add `IndicatorGroup`, `IndicatorGroupMember` models
  (single models file per existing convention)
- `app/schemas.py` — Pydantic schemas for groups + `requirement_type`
- `app/api/indicator_groups.py` — new router
- `alembic/versions/xxxx_add_indicator_groups.py` — migration
- `static/js/indicator-groups.js` — admin screen
- tests: `tests/test_indicator_groups.py`,
  `tests/test_requirement_type_completeness.py`

### Modified Files
- `app/models.py` — `Indicator.requirement_type`
- `app/engine/pipeline.py` — shared
  `get_required_indicator_ids()` helper (composes disabled ∧ Required)
- `app/engine/pipeline.py::_compute_full_analysis` — use the helper for
  `active_indicator_count`
- `app/api/dashboard.py::_recalc_completeness` — use the helper
- `app/api/indicator_config.py` — use the helper in
  `_recalc_hospital_scores`; add `/hospitals/indicators/{id}/requirement-type`
- `app/main.py` — register the new router
- `app/menu_registry.py` — admin menu entry
- `docs/COVERAGE-DISABLE-DOCTRINE.md` — document the Optional exclusion as a
  doctrine path (§3-style) + checklist update
- `app/engine/quality/scoring.py` — **no changes** (rev 1 correction: it only
  receives `active_indicator_count`; the denominator lives at the call sites)
- `app/engine/pipeline.py` effective-state helpers — **no logic changes**
  (only consumed by the bulk action)

---

## Acceptance Criteria

1. ✅ Admin can create/edit/delete indicator groups
2. ✅ Group has scope (all hospitals / specific hospital) and — for
   all-hospitals scope only — an optional date range
3. ✅ Admin can add/remove indicators to/from group (exclusive membership,
   service-layer enforced)
4. ✅ Toggling group applies bulk enable/disable to member configs with an
   explicit, idempotent target state
5. ✅ Changes reflect immediately in indicator tree for affected
   hospitals/months (via existing effective-state logic, unchanged)
6. ✅ Indicators not in any group behave exactly as before
7. ✅ Required/Optional flag affects the completeness denominator at all
   three call sites, consistently, with doctrine documentation and guard
   tests
8. ✅ No changes to existing effective state resolution logic
9. ✅ Hospital-scoped groups never silently claim month scoping (API 422 +
   UI hides the picker)
