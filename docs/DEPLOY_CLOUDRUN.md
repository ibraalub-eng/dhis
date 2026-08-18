# النشر على Google Cloud Run

دليل خطوة بخطوة لنشر النظام (FastAPI + SQLAlchemy + Alembic) على Google Cloud Run.

## ⚠️ أهم تنبيه قبل النشر: قاعدة البيانات

Cloud Run بيئة **بلا حالة**: نظام الملفات مؤقت (يُمسح عند كل إعادة تشغيل، ولا يُشارك بين النسخ).
تطبيقنا الحالي يستخدم **SQLite** (`data/health_ai.db`) مع ملفات مرفوعة ونماذج XGBoost على القرص —
**لن تنجو من أول إعادة تشغيل على Cloud Run**.

الحل الموصى به (والمجهَّز في `deploy-cloudrun.sh`): **Cloud SQL Postgres**.
التطبيق جاهز لها بدون تغيير كود: يقرأ `DATABASE_URL` من المتغيرات، ويشغّل ترحيلات Alembic
والبذور تلقائياً عند الإقلاع (ترحيلات Alembic محايدة اللهجة — لا SQL خاص بـ SQLite).

> بيانات SQLite الحالية **لا تُهاجر تلقائياً**. إما أن تبدأ نظيفاً وتعيد رفع الملفات،
> أو صدِّر SQLite واستوردها إلى Postgres قبل التشغيل الفعلي.

## الخطوات

### 1) المتطلبات (مرة واحدة — بنفسك)
```bash
# تثبيت gcloud CLI: https://cloud.google.com/sdk/docs/install
gcloud auth login
gcloud config set project YOUR_PROJECT_ID   # مع تفعيل الفوترة billing
```

### 2) التشغيل
```bash
DB_PASSWORD="ضع-كلمة-مرور-قوية" PROJECT_ID="YOUR_PROJECT_ID" bash deploy-cloudrun.sh
```
السيناريو يقوم تلقائياً بـ:
1. تفعيل الـ APIs المطلوبة (Artifact Registry / Cloud Run / Cloud Build / Cloud SQL / Secret Manager).
2. إنشاء مثيل Postgres 16 (tier مجاني `db-f1-micro`) + قاعدة بيانات + مستخدم.
3. بناء الصورة ورفعها إلى Artifact Registry.
4. حفظ `DATABASE_URL` في Secret Manager.
5. نشر الخدمة (وصول عام، حتى 3 نسخ، 1Gi ذاكرة) مع تعطيل AI مبدئياً.

### 2ب) النشر الآلي عبر Cloud Build (CI/CD) — مُوصى به
بدل البناء والنشر يدوياً، يمكن إطلاق **خط أنابيب واحد** يبني الصورة، ويشغّل الاختبارات،
وينشر، ويفحص الخدمة الحية — وكل ذلك قبل أن تُعتبر النسخة الجديدة جاهزة:

```bash
# شرط مسبق: تأكد أن سكرت DATABASE_URL موجود (أنشأه deploy-cloudrun.sh مرة واحدة)
gcloud builds submit --config cloudbuild.yaml \
    --substitutions=_REGION=europe-west1,_SERVICE=health-ai
```

الخطوات الأربع في `cloudbuild.yaml`:
1. **build** — بناء الصورة.
2. **test** — تشغيل حزمة `pytest` الكاملة **داخل الصورة** (SQLite في الذاكرة، بدون قاعدة بيانات خارجية)؛ أي اختبار فاشل يوقف الخط أنابيب قبل النشر.
3. **deploy** — النشر إلى Cloud Run (نفس الإعدادات: 3 نسخ، 1Gi، AI معطّل مبدئياً).
4. **smoke** — فحص `GET /health` على الرابط الحي مع إعادة محاولة حتى يصبح الخدمة جاهزة.

**للتفعيل التلقائي عند كل push:** أنشئ Trigger في Cloud Build (Console → Cloud Build → Triggers)
يربط مستودعك (GitHub/GitLab/Bitbucket) بهذا الملف — ستُبنى الصورة وتُختبر وتُنشر تلقائياً عند كل دمج،
ولا يُنشر أي كود يفشل في الاختبارات.

> `DATABASE_URL` يُقرأ من Secret Manager (الذي أنشأه السكربت). لو نشرتَ أول مرة عبر
> Cloud Build دون تشغيل السكربت، أنشئ السكرت يدوياً:
> `printf 'postgresql+psycopg2://USER:PASS@HOST/DB' | gcloud secrets create database-url --replication-policy=automatic --data-file=-`

### 3) تفعيل الذكاء الاصطناعي (اختياري)
```bash
printf '%s' "AIza..." | gcloud secrets create ai-api-key --replication-policy=automatic --data-file=-
gcloud run services update health-ai --region "$REGION" \
    --set-env-vars "AI_RECOMMENDATIONS_ENABLED=true" \
    --set-secrets "AI_API_KEY=ai-api-key:latest"
```

### 4) تحقق
```bash
gcloud run services describe health-ai --region "$REGION" --format="value(status.url)"
curl <URL>/health   # 200 = الخدمة وقاعدة البيانات سليمتان (يُستخدمه Cloud Build في خطوة smoke)
curl <URL>/dashboard
```

نقطة النهاية `/health` (أضيفت في `app/main.py`): تُرجع `200 {"status":"ok","database":"ok"}`
عندما يمكن الوصول لقاعدة البيانات، و`503` عند فشل الاتصال بها — وهي نفس النقطة التي
يستخدمها `HEALTHCHECK` في Dockerfile والفحص اللاحق للنشر في Cloud Build.

## حدود يجب معرفتها

| البند | الوضع على Cloud Run |
|---|---|
| SQLite / الملفات المرفوعة / نماذج XGBoost | **مؤقتة** — تُمسح عند إعادة التشغيل (الملفات المرفوعة أصلها خارجي، والنماذج يُعاد تدريبها) |
| المزامنة بين النسخ | لا توجد — استخدم Cloud SQL (جاري في السكربت) |
| الأسرار | `.env` **مستثنى من الصورة** — الأسرار عبر Secret Manager |
| البث/الرفع الكبير | حد 32MB لطلب الواحد على Cloud Run (مناسب للملفات الحالية) |
| تكلفة | `db-f1-micro` ضمن الطبقة المجانية؛ تفعّل `--min-instances 0` لإيقاف النسخ عند الخمول |

## ملفات النشر

- `Dockerfile` — Python 3.12-slim، يستمع على `$PORT` (يفرضه Cloud Run) مع `HEALTHCHECK` على `/health`.
- `.dockerignore` — يستثني `.env` و`data/` و`*.db` والأدوات المحلية.
- `deploy-cloudrun.sh` — سكربت النشر المُوجَّه (إنشاء Cloud SQL/سكرت + نشر) — تشغيل يدوي لمرة واحدة.
- `cloudbuild.yaml` — خط أنابيب CI/CD: build → test → deploy → smoke، يُشغَّل يدوياً أو من Trigger تلقائي.
