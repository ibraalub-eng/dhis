# Install & Run on a New Machine

Deploy HEALTH-ai (SRMNH Data Quality System) from scratch on any server or
workstation. Two paths: **bare Python** (Option A) or **Docker** (Option B).

---

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | **3.12** recommended (3.13 works) | ML wheels (xgboost, shap, scipy) have prebuilt builds for these |
| PostgreSQL | 14+ | Required for real use; the app shows a setup page without `DATABASE_URL` |
| Git | any | To clone the repo |
| Docker | 24+ | Only for Option B |
| Node.js | 18+ | **Optional** — used only for JS syntax checks (`npm run check`), not at runtime |

> Windows: install from python.org and check "Add Python to PATH".
> Linux (bare metal): you need `libpq-dev` (psycopg2) and `libgomp1` (xgboost):
> `sudo apt-get install -y python3-venv python3-pip libpq-dev libgomp1`

---

## 2. Get the code

```bash
git clone https://github.com/ibraalub-eng/dhis.git
cd dhis
```

---

## 3. Option A — Bare Python

### 3.1 Virtual environment + dependencies

```bash
# Windows
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# Linux / macOS
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The ML stack (scipy, scikit-learn, shap, xgboost, plotly, statsmodels) makes
this a large download — expect several minutes on first install.

### 3.2 PostgreSQL

Create a database and user (psql):

```sql
CREATE DATABASE health_ai;
CREATE USER health_ai WITH PASSWORD 'strong-password-here';
GRANT ALL PRIVILEGES ON DATABASE health_ai TO health_ai;
```

Or run Postgres in Docker (no local install needed):

```bash
docker run -d --name dhis-pg -e POSTGRES_DB=health_ai \
  -e POSTGRES_USER=health_ai -e POSTGRES_PASSWORD=strong-password-here \
  -p 5432:5432 postgres:16
```

> Using the Docker Compose stack (Option 4.1)? Skip this — it starts its own
> PostgreSQL with credentials from `.env` and pre-wires `DATABASE_URL`.

### 3.3 Configure `.env`

```bash
# Windows
copy .env.example .env
# Linux / macOS
cp .env.example .env
```

Edit `.env` — the keys that matter:

```ini
DATABASE_URL=postgresql://health_ai:strong-password-here@localhost:5432/health_ai
JWT_SECRET=<generate: python -c "import secrets; print(secrets.token_hex(32))">
ADMIN_PASSWORD=<first admin password>
```

- `JWT_SECRET` — set a long random value in any shared/production environment.
- `ADMIN_PASSWORD` — password for the auto-seeded `admin` user (default `admin123`).
- The `AI_*` keys are optional; AI recommendations stay off without them.

> Render-style `postgres://` URLs are normalized to `postgresql://` automatically.

### 3.4 Run

```bash
# Windows
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
# (equivalently: .\START PYTHON.ps1)

# Linux / macOS
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

Open **http://127.0.0.1:8000** → log in with `admin` / your `ADMIN_PASSWORD`.

**What startup does automatically (no manual steps):**

1. Runs Alembic migrations to head (creating tables on an empty DB).
2. Seeds AppConfig, indicators, validation rules, and menu reference data.
3. Creates the `admin` user if the users table is empty.
4. Applies hospital metadata from `scripts/hospital_metadata.json`.

`GET /health` returns 200 once the database is reachable — use it as a smoke test.

---

## 4. Option B — Docker (any host)

### 4.1 One command (recommended): Docker Compose

`docker-compose.yml` starts **PostgreSQL 16 + the app together**, gated by a DB
healthcheck; the app's lifespan runs migrations + seeding on first boot.

```bash
docker compose up -d --build
```

Then open **http://localhost:8080** and log in as `admin` (password from
`ADMIN_PASSWORD`, default `admin123`). Check readiness with
`docker compose ps` (both services `healthy`) and logs with
`docker compose logs -f app`.

Customize via the existing `.env` (compose reads it automatically) —
`ADMIN_PASSWORD`, `JWT_SECRET`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
`POSTGRES_DB`, `APP_PORT`, `TAG`. AI recommendations enable with
`AI_RECOMMENDATIONS_ENABLED=true` + `AI_API_KEY`.

Notes:

- Postgres data persists in the `pgdata` named volume across restarts; the
  database is reachable on the host at `127.0.0.1:5433` for debugging only —
  the app uses the internal network.
- Wipe everything (including data): `docker compose down -v`.
- Stop/start without rebuilding: `docker compose stop` / `docker compose start`.

### 4.2 Manual `docker run` (existing external DB)

The included `Dockerfile` also runs standalone when you already have a
PostgreSQL server:

```bash
docker build -t dhis-app .

docker run -d --name dhis -p 8080:8080 \
  -e DATABASE_URL=postgresql://health_ai:strong-password-here@HOST:5432/health_ai \
  -e JWT_SECRET=<random-64-hex> \
  -e ADMIN_PASSWORD=<first admin password> \
  dhis-app
```

Run on `http://HOST:8080` (the container respects `$PORT`; it defaults to 8080).

**Cloud deploys** — the repo ships with everything wired:

- `render.yaml` — Render.com blueprint (injects `DATABASE_URL`, `JWT_SECRET`).
- `cloudbuild.yaml` + `deploy-cloudrun.sh` — Google Cloud Run.
- Production process: `gunicorn` with `uvicorn.workers.UvicornWorker`, 120s timeout.

---

## 5. Post-install checklist

- [ ] `GET /health` → 200
- [ ] Login works, then **change the admin password** (System Control)
- [ ] Upload an Excel file (Upload Data) — analysis populates the dashboard
- [ ] Indicator Tree, Rules Manager, and drilldowns render with data
- [ ] Arabic/English toggle and dark mode work

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| App shows a "setup instructions" page | `DATABASE_URL` missing or unreachable — check `.env` and that Postgres is running; with compose, `docker compose ps` should show `db` healthy |
| `pip install` fails on psycopg2 | Install `libpq-dev` (Debian/Ubuntu) or `postgresql-devel` (RHEL) — or use `psycopg2-binary` (already in requirements.txt) |
| xgboost import error on Linux bare metal | `sudo apt-get install libgomp1` |
| Port already in use | Start with another `--port` (dev) or `-p` mapping (Docker) |
| Login fails on a fresh DB | Admin seeds only when the users table is empty; check startup logs for `[startup] Admin user setup error`, then restart |
| 401 loops after restart | `JWT_SECRET` changed between runs — set it fixed in `.env` |
| Stale JS after upgrade | Hard refresh (Ctrl+F5); the SPA caches tab fragments aggressively |
