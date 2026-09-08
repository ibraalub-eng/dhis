# Health AI — Preview Run Doc

FastAPI app serving the SPA frontend from `static/` at `/` (dashboard at `/dashboard`, API at `/api/...`, docs at `/docs`).

## How to reproduce the artifacts

- **Python**: Python 3.13.15 is installed per-user at `C:\dhis-main\tools\python\python.exe` (registered in `HKCU\SOFTWARE\Python\PythonCore\3.13`). It is NOT on PATH — always call it by full path.
- **Venv**: `.venv` in the checkout root, created with the interpreter above (`<python>\python.exe -m venv .venv`).
- **Dependencies**: `.venv/Scripts/python.exe -m pip install -r requirements.txt python-dotenv`. Note `python-dotenv` is imported by `app/config.py` but missing from `requirements.txt` — install it explicitly.
- **`.env`**: NOT committed. Create it from `.env.example`. For local SQLite preview:
  ```
  DATABASE_URL=sqlite:///data/health_ai.db
  JWT_SECRET=<any random string>
  ADMIN_PASSWORD=admin123
  AI_RECOMMENDATIONS_ENABLED=false
  ```
  Leave `AI_API_KEY` unset unless Gemini recommendations are needed.

## How to run the server

```bash
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- Default port 8000 (matches `START PYTHON.ps1`). If taken, pick a free port and use `--port <n>`.
- On startup the app runs alembic migrations + seeds config/indicators/rules into `data/health_ai.db` automatically (fresh DB starts empty).
- Login: `admin` / `admin123` (or whatever `ADMIN_PASSWORD` is set to).
- For live preview (Windows, detached, PowerShell):
  ```powershell
  (Start-Process -FilePath '<checkout>\.venv\Scripts\python.exe' -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory '<checkout>' -RedirectStandardOutput '<log>.log' -RedirectStandardError '<log>.err' -WindowStyle Hidden -PassThru).Id
  ```
  then register `http://127.0.0.1:8000/`.

No build step or other uncommitted artifacts are required — the frontend is plain static HTML/JS/CSS served directly.