# HEALTH-ai — Local Setup Cheat Sheet (Windows Server 2019)

> Machine: `WIN-UKHBT5CF436` · LAN IP `172.15.3.201` · Gateway `10.15.3.1` · WAN IP `213.6.253.119`

## URLs & Ports

| What | URL / Port |
|---|---|
| Web app (this machine) | http://127.0.0.1:9090 |
| Web app (LAN) | http://172.15.3.201:9090 |
| Health check JSON | http://127.0.0.1:9090/health |
| API docs (Swagger) | http://127.0.0.1:9090/docs |
| PostgreSQL | 127.0.0.1:5432 |
| Public access (planned) | **Permanent tunnel READY but pending domain** — Cloudflare zone (nameservers `kaiser`/`lauryn.ns.cloudflare.com`) still propagating. Tunnel `healthai` (ID `3a4604d7-2683-4a19-8882-1edd2bdfbdd4`) is live and connected. Once the zone is active, run:
  `cloudflared tunnel route dns -f healthai healthai.<domain>` → app at `https://healthai.<domain>` |
| Quick tunnel (LIVE) | `https://leader-quantities-management-adventure.trycloudflare.com` — auto-managed by the watchdog (URL changes if it restarts; always check `logs\CURRENT-PUBLIC-URL.txt`) |

## Credentials

| What | Value |
|---|---|
| App login | `admin` / `admin123` ⚠️ change before public exposure (`ADMIN_PASSWORD` in `.env`) |
| PostgreSQL | user `postgres` / password `health_ai_local` / db `health_ai` |
| DB URL (`.env`) | `postgresql://postgres:health_ai_local@127.0.0.1:5432/health_ai` |
| pgAdmin | connection "HEALTH-ai (local PostgreSQL 17)" — Desktop & Start Menu shortcuts created; master-password gate disabled (`web\config_local.py`) |
| App DB contents | **Production snapshot restored 2026-09-24** (`dhis_prod_snapshot_2026-09-22.sql`, 32 tables, 9 users, 41 hospitals) — logins are the PRODUCTION ones, not the seeded `admin`/`admin123` |

## Windows Services (auto-start at boot, in this order)

| Service | Role |
|---|---|
| `postgresql17` | PostgreSQL 17.11 (runs as NETWORK SERVICE) |
| `HealthAI` | FastAPI via NSSM — venv uvicorn on 0.0.0.0:9090, auto-restart on crash, 10 MB rotating logs, depends on postgresql17 |
| `cloudflaredAI` | Cloudflare Tunnel (NSSM) — runs `tunnel run 3a4604d7…` with `--config C:\Users\Administrator\.cloudflared\config.yml`, auto-start, depends on HealthAI, logs to `logs\cf-tunnel-*.log` |

## Watchdog (scheduled task "HEALTH-ai Watchdog")

Every 5 minutes, as SYSTEM: checks app service + `/health` (restarts if failing), ensures `cloudflaredAI` service is running, and recreates the quick tunnel if its process died (writing the new URL to `logs\CURRENT-PUBLIC-URL.txt`). All actions logged to `logs\watchdog.log`.

```powershell
Get-ScheduledTask "HEALTH-ai Watchdog"          # status
Start-ScheduledTask "HEALTH-ai Watchdog"        # run now
Get-Content logs\watchdog.log -Tail 20          # recent activity
cat logs\CURRENT-PUBLIC-URL.txt                 # current public URL
```

## Service commands (PowerShell)

```powershell
# App (use the scripts — killing python directly just gets auto-restarted by NSSM)
.\STOP PYTHON.ps1
.\START PYTHON.ps1

sc query HealthAI            # app status
sc query postgresql17        # database status
Get-Content logs\service-err.log -Tail 50   # app logs (also service-out.log)
```

## Database quick commands

```powershell
$pg = "C:\Program Files\PostgreSQL\17\bin"
& "$pg\psql.exe" -h 127.0.0.1 -U postgres -d health_ai            # interactive SQL
& "$pg\pg_dump.exe" -h 127.0.0.1 -U postgres -Fc health_ai > backup.dump   # backup
```
psql password prompt → `health_ai_local` (or set `$env:PGPASSWORD` first).

## Key paths

| Path | What |
|---|---|
| `C:\Users\Administrator\Documents\GitHub\dhis` | Project root |
| `C:\Program Files\PostgreSQL\17\bin` | psql, pg_dump, pgAdmin tools |
| `C:\Program Files\PostgreSQL\17\data` | Database files |
| `C:\Program Files\PostgreSQL\17\pgAdmin 4\runtime\pgAdmin4.exe` | pgAdmin GUI |
| `C:\Python313\` | **Global Python 3.13.15** (machine PATH; `python`/`pip`/`py` in any new shell) — also the base of `.venv` and every future project |
| `%APPDATA%\pgAdmin\pgadmin4.db` | pgAdmin's own DB (query history bloats it; safe to clear when pgAdmin is closed) |
| `C:\Users\Administrator\.cloudflared\` | Tunnel credentials (`cert.pem`, tunnel UUID `.json`, `config.yml`) — keep secret |
| `watchdog.ps1` (project root) | Watchdog script — app `/health` restart, tunnel revival, status logging |
| `logs\watchdog.log` | Watchdog activity log (task runs every 5 min as SYSTEM) |
| `logs\CURRENT-PUBLIC-URL.txt` | Current quick-tunnel URL — rewritten by watchdog whenever it recreates the tunnel |
| `.env.bak.local` | Backup of original `.env` |
| `data\health_ai.db` | Old SQLite data (unused, kept) |

## MikroTik (pending — to publish publicly)

```routeros
/ip firewall nat
add chain=dstnat in-interface=ether1 protocol=tcp dst-port=9090 action=dst-nat \
    to-addresses=172.15.3.201 to-ports=9090 comment="HEALTH-ai web app"
```
Windows firewall rule `HEALTH-ai 9090` already open; app verified on LAN IP. If public IP isn't on the MikroTik itself (double-NAT), forward on the real edge device or use Cloudflare Tunnel.

## Restoring a SQL dump (do NOT use pgAdmin Query Tool)

Dumps contain psql meta-commands (`\restrict`, `\connect`) that the Query Tool cannot run — always use psql:

```powershell
.\STOP PYTHON.ps1
$env:PGPASSWORD = "health_ai_local"
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -h 127.0.0.1 -U postgres -d postgres -c "DROP DATABASE IF EXISTS health_ai WITH (FORCE);" -c "CREATE DATABASE health_ai;"
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -h 127.0.0.1 -U postgres -d health_ai -f C:\path\to\dump.sql
# The DB content changed wholesale — rotate the cache epoch so every cached
# payload from the old data state (all endpoints, memory + data\cache files)
# is unreachable immediately. Deleting files manually is no longer needed:
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, '.'); from app.cache import refresh_data_epoch; print('new epoch:', refresh_data_epoch())"
.\START PYTHON.ps1
# On the next restart the epoch sweep also deletes the old-epoch files.
# Optional hygiene: preview + delete ghost '__all__'/never-analyzed rows
.\.venv\Scripts\python.exe scripts\purge_ghost_results.py            # dry run
.\.venv\Scripts\python.exe scripts\purge_ghost_results.py --execute  # apply (rotates epoch)
```

## Notes

- Docker is **not** available on this OS (Windows Server 2019, no WSL2); repo's `docker-compose.yml` is for other machines.
- App startup on an already-migrated DB is idempotent; NSSM start may briefly show "Paused/failed" in SCM while seeding — check `/health` before assuming failure.
- Global Python lives at `C:\Python313` (registered MSI install — do NOT move it; `.venv\pyvenv.cfg` and the `py` launcher reference this path). The old `C:\dhis-main` location was removed 09-24; if the venv ever breaks, fix its base by editing `.venv\pyvenv.cfg` → `home = C:\Python313`.
- Change `JWT_SECRET` in `.env` before real production use.
