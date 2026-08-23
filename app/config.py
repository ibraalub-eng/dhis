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
