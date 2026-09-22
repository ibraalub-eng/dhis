#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Health AI — SRMNH  →  Google Cloud Run + Supabase Postgres (free tier)
#
#  Like deploy-cloudrun.sh, but the database is a FREE external Supabase
#  Postgres instead of Cloud SQL (which has no free tier, ~$8-10/month).
#  Result: $0/month hosting on GCP's always-free Cloud Run allocation.
#
#  PREREQUISITES (do these once, yourself):
#    1. Install gcloud CLI  → https://cloud.google.com/sdk/docs/install
#    2. gcloud auth login
#    3. gcloud config set project YOUR_PROJECT_ID   (billing enabled)
#    4. Create a FREE project at https://supabase.com  (no card required)
#    5. In Supabase: Project Settings → Database → Connection string,
#       copy the **Session pooler** URI (port 5432 — NOT the direct
#       connection on 5432 without the pooler host, and NOT transaction
#       mode on port 6543).
#
#  WHY THE POOLER HOST: Supabase's direct `db.<ref>.supabase.co:5432`
#  resolves to IPv6 only. Cloud Run is IPv4, so it cannot reach it. The
#  Supavisor pooler (aws-0-<region>.pooler.supabase.com) always has IPv4.
#  Session mode (5432) behaves like plain Postgres, so Alembic migrations
#  and SQLAlchemy work untouched.
#
#  The app auto-runs alembic migrations + seed data on boot, so the Supabase
#  schema is created automatically on first deploy. Existing local SQLite
#  data is NOT migrated automatically — start fresh and re-upload Excels.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── EDIT THESE ───────────────────────────────────────────────────────────────
PROJECT_ID="${PROJECT_ID:-health-ai-srmnh}"   # your GCP project id
REGION="${REGION:-europe-west1}"              # e.g. europe-west1, us-central1
SERVICE_NAME="${SERVICE_NAME:-health-ai}"
# Full Supabase session-pooler connection string (see prerequisites):
SUPABASE_DB_URL="${SUPABASE_DB_URL:-}"
# Strong admin login password for the app (user: admin):
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
# Optional: leave empty to auto-generate JWT_SECRET:
JWT_SECRET="${JWT_SECRET:-}"
# ─────────────────────────────────────────────────────────────────────────────

command -v gcloud >/dev/null 2>&1 || {
    echo "❌ gcloud CLI not found. Install it first: https://cloud.google.com/sdk/docs/install"
    exit 1
}

echo "==> Validating inputs"
if [[ -z "$SUPABASE_DB_URL" ]]; then
    echo "❌ Set SUPABASE_DB_URL to the Supabase SESSION POOLER connection string"
    echo "   (Supabase Dashboard → Connect → Session pooler, port 5432)."
    exit 1
fi

# The URL must target the Supavisor pooler host — the direct connection is
# IPv6-only and unreachable from Cloud Run; port 6543 is transaction mode,
# which breaks SQLAlchemy prepared statements / Alembic migrations.
if [[ ! "$SUPABASE_DB_URL" =~ pooler\.supabase\.(com|co) ]]; then
    echo "❌ SUPABASE_DB_URL must use the POOLER host (aws-0-<region>.pooler.supabase.com)."
    echo "   The direct db.<ref>.supabase.co host is IPv6-only → Cloud Run can't reach it."
    exit 1
fi
if [[ "$SUPABASE_DB_URL" =~ :6543/ ]]; then
    echo "❌ Port 6543 is Supabase TRANSACTION mode — it breaks migrations."
    echo "   Use the SESSION pooler URI (port 5432): Dashboard → Connect → Session pooler."
    exit 1
fi
if [[ ! "$SUPABASE_DB_URL" =~ :5432/ ]]; then
    echo "⚠️  SUPABASE_DB_URL does not use port 5432 — continuing, but session"
    echo "    mode (5432) is the tested path for this app."
fi
if [[ -z "$ADMIN_PASSWORD" ]]; then
    echo "❌ Set ADMIN_PASSWORD (the app's admin login) before running."
    exit 1
fi
if [[ -z "$JWT_SECRET" ]]; then
    JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null) \
        || JWT_SECRET=$(openssl rand -hex 32) \
        || { echo "❌ Could not generate JWT_SECRET (install python or openssl)"; exit 1; }
    echo "   -> generated a random JWT_SECRET (re-runs reuse the stored secret)"
fi

echo "==> Checking gcloud auth"
gcloud auth list --format="value(account)" >/dev/null || { echo "❌ Run: gcloud auth login"; exit 1; }
gcloud config set project "$PROJECT_ID" >/dev/null

echo "==> Enabling required APIs"
gcloud services enable \
    artifactregistry.googleapis.com \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    secretmanager.googleapis.com

echo "==> Building and pushing image to Artifact Registry"
AR_REPO="health-ai-images"
gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker --location="$REGION" 2>/dev/null || true

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE_NAME}"
gcloud builds submit --tag "$IMAGE" .

upsert_secret() { # name, value — create the secret, or add a new version
    local name="$1" value="$2"
    printf '%s' "$value" | gcloud secrets create "$name" --replication-policy=automatic --data-file=- 2>/dev/null \
        || printf '%s' "$value" | gcloud secrets versions add "$name" --data-file=-
}

echo "==> Creating/updating Secret Manager secrets"
upsert_secret "database-url" "$SUPABASE_DB_URL"
upsert_secret "jwt-secret" "$JWT_SECRET"
upsert_secret "admin-password" "$ADMIN_PASSWORD"

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
    --set-secrets "DATABASE_URL=database-url:latest,JWT_SECRET=jwt-secret:latest,ADMIN_PASSWORD=admin-password:latest"

URL=$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format="value(status.url)")

echo ""
echo "==> Smoke-testing ${URL}/health"
SMOKE_OK=0
for i in $(seq 1 24); do
    if curl -fsS --max-time 10 "${URL}/health" >/dev/null 2>&1; then
        echo "✅ Health check passed (attempt ${i})"
        SMOKE_OK=1
        break
    fi
    echo "   attempt ${i} failed, retrying in 5s... (first boot runs migrations + seeds)"
    sleep 5
done
if [[ "$SMOKE_OK" != "1" ]]; then
    echo "⚠️  /health never returned 200. Check logs:"
    echo "   gcloud run services logs read ${SERVICE_NAME} --region ${REGION} --limit 50"
fi

echo ""
echo "✅ Deployment complete. URL:"
echo "   ${URL}"
echo ""
echo "Login: admin / (your ADMIN_PASSWORD)"
echo ""
echo "Next steps:"
echo "  • AI_API_KEY → gcloud secrets create ai-api-key ... then redeploy with"
echo "    --set-secrets \"...,AI_API_KEY=ai-api-key:latest\" and AI_RECOMMENDATIONS_ENABLED=true"
echo "  • uploads/ and trained XGBoost models live on the ephemeral disk — they reset per instance."
echo "  • Supabase free tier = 500 MB; Database → Backups are on paid plans, so export"
echo "    periodically if the data matters."
