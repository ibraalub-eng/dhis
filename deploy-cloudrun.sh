#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Health AI — SRMNH  →  Google Cloud Run
#  Guided deployment: Cloud SQL (Postgres) + Artifact Registry + Cloud Run.
#
#  PREREQUISITES (do these once, yourself):
#    1. Install gcloud CLI  → https://cloud.google.com/sdk/docs/install
#    2. gcloud auth login
#    3. gcloud config set project YOUR_PROJECT_ID
#    4. Enable billing on the project.
#
#  IMPORTANT: Cloud Run has an EPHEMERAL filesystem — SQLite (data/health_ai.db)
#  would be wiped on every restart and is NOT shared across instances. This
#  script therefore provisions Cloud SQL Postgres and points DATABASE_URL at it.
#  The app auto-runs alembic migrations + seed data on boot, so the schema is
#  created automatically on first deploy.
#
#  Existing SQLite data is NOT migrated automatically. Either start fresh and
#  re-upload, or dump your SQLite DB and import it into Postgres before going live.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── EDIT THESE ───────────────────────────────────────────────────────────────
PROJECT_ID="${PROJECT_ID:-health-ai-srmnh}"          # your GCP project id
REGION="${REGION:-europe-west1}"                      # e.g. europe-west1, us-central1
SERVICE_NAME="${SERVICE_NAME:-health-ai}"
DB_INSTANCE="${DB_INSTANCE:-health-ai-db}"            # Cloud SQL instance name
DB_NAME="${DB_NAME:-health_ai}"
DB_USER="${DB_USER:-health_ai}"
DB_PASSWORD="${DB_PASSWORD:-}"                        # set a strong password!
# ─────────────────────────────────────────────────────────────────────────────

command -v gcloud >/dev/null 2>&1 || { echo "❌ gcloud CLI not found. Install it first: https://cloud.google.com/sdk/docs/install"; exit 1; }
[[ -n "$DB_PASSWORD" ]] || { echo "❌ Set DB_PASSWORD (a strong password) before running."; exit 1; }

echo "==> Checking gcloud auth"
gcloud auth list --format="value(account)" >/dev/null || { echo "❌ Run: gcloud auth login"; exit 1; }
gcloud config set project "$PROJECT_ID" >/dev/null

echo "==> Enabling required APIs"
gcloud services enable \
    artifactregistry.googleapis.com \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    sqladmin.googleapis.com \
    secretmanager.googleapis.com

echo "==> Provisioning Cloud SQL Postgres (${DB_INSTANCE})"
if ! gcloud sql instances describe "$DB_INSTANCE" --format="value(name)" >/dev/null 2>&1; then
    gcloud sql instances create "$DB_INSTANCE" \
        --database-version=POSTGRES_16 \
        --tier=db-f1-micro \
        --region="$REGION"
    echo "   -> instance created"
else
    echo "   -> instance already exists"
fi

gcloud sql databases create "$DB_NAME" --instance="$DB_INSTANCE" 2>/dev/null || echo "   -> database already exists"

gcloud sql users set-password "$DB_USER" --instance="$DB_INSTANCE" --password="$DB_PASSWORD" 2>/dev/null \
    || gcloud sql users create "$DB_USER" --instance="$DB_INSTANCE" --password="$DB_PASSWORD"

echo "==> Building and pushing image to Artifact Registry"
AR_REPO="health-ai-images"
gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker --location="$REGION" 2>/dev/null || true

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE_NAME}"
gcloud builds submit --tag "$IMAGE" .

echo "==> Creating DATABASE_URL secret (used by the app on boot)"
DB_HOST=$(gcloud sql instances describe "$DB_INSTANCE" --format="value(ipAddresses[0].ipAddress)")
DB_URL="postgresql+psycopg2://${DB_USER}:${DB_PASSWORD}@${DB_HOST}/${DB_NAME}"
printf '%s' "$DB_URL" | gcloud secrets create database-url --replication-policy=automatic --data-file=- 2>/dev/null \
    || printf '%s' "$DB_URL" | gcloud secrets versions add database-url --data-file=-

echo "==> Deploying to Cloud Run"
gcloud run deploy "$SERVICE_NAME" \
    --image "$IMAGE" \
    --platform managed \
    --region "$REGION" \
    --allow-unauthenticated \
    --min-instances 0 \
    --max-instances 3 \
    --memory 1Gi \
    --cpu 1 \
    --timeout 300 \
    --set-env-vars "AI_RECOMMENDATIONS_ENABLED=false,DATA_DIR=/tmp/health-ai-data" \
    --set-secrets "DATABASE_URL=database-url:latest"

echo ""
echo "✅ Deployment complete. URL:"
gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format="value(status.url)"
echo ""
echo "Next steps:"
echo "  • AI_API_KEY → gcloud secrets create ai-api-key ... then add --set-secrets \"AI_API_KEY=ai-api-key:latest\""
echo "  • If you want AI on: set AI_RECOMMENDATIONS_ENABLED=true (keep the key in Secret Manager)."
echo "  • uploads/ and trained XGBoost models live on the ephemeral disk — they reset per instance."
