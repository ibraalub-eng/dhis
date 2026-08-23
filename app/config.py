import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Data directories (uploads, samples — stored on disk, not in DB)
DATA_DIR = os.getenv("DATA_DIR", os.path.join(BASE_DIR, "data"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
SAMPLE_DIR = os.path.join(DATA_DIR, "sample")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# PostgreSQL required in production; tests use in-memory SQLite via conftest.py
DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    # Allow import without DATABASE_URL (tests set it via conftest.py)
    if "pytest" in sys.modules or os.environ.get("TESTING"):
        DATABASE_URL = "sqlite://"  # in-memory, overridden by conftest
    else:
        print("[FATAL] DATABASE_URL environment variable is not set.", file=sys.stderr)
        print("[FATAL] Set it to a PostgreSQL connection string, e.g.:", file=sys.stderr)
        print('  export DATABASE_URL="postgresql://user:pass@host:5432/health_ai"', file=sys.stderr)
        sys.exit(1)

# Normalize Render's DATABASE_URL (some Render plans use postgres:// instead of postgresql://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
