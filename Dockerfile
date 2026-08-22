# ── Health AI — SRMNH Data Quality System ──
# Build image for Google Cloud Run / Render.com / any Docker host.
# Uses a stable Python release with prebuilt wheels for scipy/xgboost/shap/sklearn.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system deps required by some wheels (shap/scikit-learn/xgboost)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY alembic/ alembic/
COPY alembic.ini .
COPY app/ app/
COPY scripts/ scripts/
COPY static/ static/

# Runtime: Cloud Run / Render inject $PORT and expect the app to listen on it.
# The app lifespan already runs alembic migrations + seeding on boot.
EXPOSE 8080

# Healthcheck: /health returns 200 only when the DB is reachable.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT:-8080}/health || exit 1

CMD ["sh", "-c", "gunicorn app.main:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --worker-class uvicorn.workers.UvicornWorker --timeout 30 --access-logfile -"]
