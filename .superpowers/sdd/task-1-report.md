### Task 1 Report: Backend — Add `/dashboard/ranking` endpoint

**Status:** DONE

**Commits:** None (pre-commit verification only)

**Changes:**
- `app/api/dashboard.py`: Added `import json`, added `ClinicalInsight` to model imports, added `GET /dashboard/ranking` endpoint function after existing endpoints.

**Verification:**

Command: `python -c "from app.api.dashboard import router; routes = [r.path for r in router.routes]; print('Routes:', routes); assert '/dashboard/ranking' in routes, 'Missing /dashboard/ranking'; print('OK')"`

Output:
```
Routes: ['/dashboard/overview', '/dashboard/yoy', '/dashboard/kpi', '/dashboard/ranking']
OK
```

**Concerns:**
- The verification command in the task brief (`assert '/ranking' in routes`) fails because `router.routes` returns full paths including the prefix (e.g., `/dashboard/ranking`), not just the endpoint path (`/ranking`). The corrected assertion `'/dashboard/ranking' in routes` passes. The endpoint itself is correctly implemented.
