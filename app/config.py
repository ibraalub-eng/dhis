import os
import secrets
import sys
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load .env from project root (ensures DATABASE_URL is available even if
# config.py is imported before main.py's load_dotdotenv() call)
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Data directories (uploads, samples — stored on disk, not in DB)
DATA_DIR = os.getenv("DATA_DIR", os.path.join(BASE_DIR, "data"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
SAMPLE_DIR = os.path.join(DATA_DIR, "sample")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# PostgreSQL required in production; tests use in-memory SQLite via conftest.py
DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    # Allow import without DATABASE_URL (tests set it via conftest)
    if "pytest" in sys.modules or os.environ.get("TESTING"):
        DATABASE_URL = "sqlite://"  # in-memory, overridden by conftest
    else:
        # Log warning but don't exit — let the app start and show an error page
        print("[WARN] DATABASE_URL not set — app will show setup instructions", file=sys.stderr)
        DATABASE_URL = ""

# Normalize Render's DATABASE_URL (some Render plans use postgres:// instead of postgresql://)
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# JWT / Auth
def _secret(name: str, *, dev_default: str | None = None) -> str:
    """Read a secret from the environment, never shipping a known default.

    Under pytest a stable dev default may be used so tokens survive within a
    test process. Otherwise, if the variable is unset, a random unguessable
    value is generated (and a warning logged) so a missing env var can never
    fall back to a hardcoded production credential.
    """
    val = os.getenv(name)
    if val:
        return val
    if "pytest" in sys.modules or os.environ.get("TESTING"):
        return dev_default or secrets.token_urlsafe(48)
    if dev_default is not None:
        print(f"[WARN] {name} is not set — using an insecure development default. Set it for production.", file=sys.stderr)
        return dev_default
    print(f"[WARN] {name} is not set — generated a random value; tokens/logins reset on restart. Set {name} for production.", file=sys.stderr)
    return secrets.token_urlsafe(48)


JWT_SECRET = _secret("JWT_SECRET", dev_default="dev-secret-change-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "90"))  # 90 days


# ── Environment + admin password policy ─────────────────────────────────────
# APP_ENV (or ENVIRONMENT) selects development vs production. Managed hosts set
# RENDER / K_SERVICE, so infer production there even when APP_ENV is absent.
def _detect_environment() -> str:
    explicit = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    if explicit:
        return explicit
    if any(os.getenv(v) for v in ("RENDER", "RENDER_GIT_COMMIT", "K_SERVICE")):
        return "production"
    return "development"


APP_ENV = _detect_environment()
IS_PRODUCTION = APP_ENV in ("production", "prod")

# The admin password seeded for LOCAL DEVELOPMENT / TESTS only. It is never used
# in production: startup is refused instead (see _resolve_admin_password).
DEV_ADMIN_PASSWORD = "admin123"
MIN_ADMIN_PASSWORD_LENGTH = 12
INSECURE_ADMIN_PASSWORDS = frozenset({
    "admin", "admin123", "admin1234", "adminadmin", "password", "passw0rd",
    "changeme", "letmein", "secret", "123456", "12345678", "123456789",
    "qwerty", "welcome", "root", "toor",
})


class InsecureAdminPasswordError(RuntimeError):
    """Raised at startup when production runs without a secure ADMIN_PASSWORD."""


def is_insecure_admin_password(password: str | None) -> bool:
    """True when `password` is missing, a known default, or shorter than the minimum."""
    if not password:
        return True
    pw = password.strip()
    if pw.lower() in INSECURE_ADMIN_PASSWORDS:
        return True
    return len(pw) < MIN_ADMIN_PASSWORD_LENGTH


def validate_production_admin_password(password: str | None) -> None:
    """Raise InsecureAdminPasswordError when `password` is unfit for production."""
    if is_insecure_admin_password(password):
        raise InsecureAdminPasswordError(
            "Refusing to start: ADMIN_PASSWORD must be set to a strong, non-default "
            f"value (at least {MIN_ADMIN_PASSWORD_LENGTH} characters) when APP_ENV="
            f"{APP_ENV!r}. The built-in development default is not allowed in production."
        )


def _resolve_admin_password() -> str:
    """ADMIN_PASSWORD policy — dev and production are intentionally different.

    - tests: a stable dev password (env override honored) so auth flows stay testable.
    - production: the env var is REQUIRED and must be strong; otherwise startup is
      refused, so no shipped fallback can ever become a production credential.
    - development: the env var if set, otherwise the documented dev default + a warning.
    """
    val = (os.getenv("ADMIN_PASSWORD") or "").strip()
    if "pytest" in sys.modules or os.environ.get("TESTING"):
        return val or DEV_ADMIN_PASSWORD
    if IS_PRODUCTION:
        validate_production_admin_password(val)
        return val
    if val:
        return val
    print(
        "[WARN] ADMIN_PASSWORD is not set — using the development default. "
        "Set ADMIN_PASSWORD before deploying to production.",
        file=sys.stderr,
    )
    return DEV_ADMIN_PASSWORD


ADMIN_PASSWORD = _resolve_admin_password()

# Upload size limit (10 MB default, safe for Render free tier 512MB RAM)
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))
MAX_UPLOAD_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024
