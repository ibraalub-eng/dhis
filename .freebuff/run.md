# Health AI — Preview Run Doc

FastAPI app serving the SPA frontend from `static/` at `/` (dashboard at `/dashboard`, API at `/api/...`, docs at `/docs`).

## How to run the server

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- Dependencies: `pip install -r requirements.txt` (already present in this checkout).
- `.env` (already present in checkout, copied/created from `.env.example`): contains `AI_API_KEY` (Gemini) and `DATABASE_URL=sqlite:///data/health_ai.db`. No port config there.
- Default port 8000 (matches `START PYTHON.ps1`). If taken, pick a free port and use `--port <n>`.
- On startup the app runs alembic migrations + seeds config/indicators/rules into `data/health_ai.db` automatically.
- For live preview: run detached, e.g. `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > .freebuff/preview-<id>.log 2>&1 &`, then register `http://127.0.0.1:8000/`.

No build step or uncommitted artifacts are required — the frontend is plain static HTML/JS/CSS served directly.
