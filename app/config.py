import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# يُسمح بإعادة توجيه دليل البيانات عبر البيئة (مثل /tmp على Cloud Run حيث
# نظام الملفات غير قابل للكتابة خارج /tmp) — الافتراضي باقٍ كما هو محلياً.
DATA_DIR = os.getenv("DATA_DIR", os.path.join(BASE_DIR, "data"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
SAMPLE_DIR = os.path.join(DATA_DIR, "sample")

# Ensure DATA_DIR exists before SQLAlchemy tries to open the SQLite file.
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(DATA_DIR, 'health_ai.db')}")