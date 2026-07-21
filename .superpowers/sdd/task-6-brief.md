# Task 6

Seed defaults + final verification

- [ ] **Step 1: Seed ML config defaults**

Run seed script from Task 2 Step 4.

- [ ] **Step 2: Run all tests**

Run: `python -m pytest -v`

Expected: All 337+ tests pass (no regressions).

- [ ] **Step 3: Verify final build**

Run: `python -c "from app.main import app; print('App loads OK')"`

Expected: No import errors.

- [ ] **Step 4: Commit any remaining changes**

```bash
git add -A
git commit -m "chore: seed ML config and final fixes"
```
