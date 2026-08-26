# Task 1: Fix settings.js bugs and dead code

## What was implemented

Deleted 5 blocks of dead/buggy code from `static/js/settings.js`:

1. **Duplicate `changeSelfPassword`** — Removed the first definition (original lines 195–227). Kept the second definition (~line 1704) which includes "new password must be different from current" validation.

2. **`initDevHints()` call** — Removed the call at (original) line 1332. This function was never defined in any JS file, causing a ReferenceError on every settings page load.

3. **`loadHospitalToggles` function** — Removed the function definition (original lines 1584–1595) and the dangling call inside `toggleHospital` to prevent a ReferenceError.

4. **`PARAM_TEMPLATES` export** — Removed the object definition (original lines 1729–1743). Never imported by any module.

5. **`PARAM_HINTS` export** — Removed the object definition (original lines 1744–1758). Never imported by any module.

## What was tested

```
python -m pytest tests/test_chart_migration.py tests/test_auth.py -q --tb=short
```

**Result:** 72 passed, 5164 warnings in 38.95s

## Files changed

| File | Action | Original lines |
|------|--------|----------------|
| `static/js/settings.js` | Modified | 195–227 (changeSelfPassword #1), 1332 (initDevHints call), 1550–1561 + 1566 (loadHospitalToggles def + call), 1681–1710 (PARAM_TEMPLATES + PARAM_HINTS) |

File reduced from 1824 lines to 1746 lines (78 lines removed).

## Issues or concerns

- The `toggleHospital` function (line ~1550) still references `loadHospitalToggles` conceptually — the function is dead but `toggleHospital` remains exported. This is fine since the call was removed; `toggleHospital` still works for toggling hospital active status and refreshing other UI components.
- The second `changeSelfPassword` at line 1704 uses `API()` prefix for the URL (`API() + '/auth/change-password'`) while the first used a bare path. The kept version is more robust.
