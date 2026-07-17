# Deploy runbook (Phase 5) — Docker → GCP Cloud Run

Sentinel ships as **one container**: a multi-stage `Dockerfile` builds the React
dashboard and the FastAPI backend serves it as static files alongside the API,
so there's one image and one public URL. No secrets are baked into the image —
all configuration comes from Cloud Run env vars / Secret Manager at deploy time.

> You run `gcloud auth` and set the project yourself. The commands below assume
> you're already authenticated (`gcloud auth login`) and have picked a project
> (`gcloud config set project YOUR_PROJECT`). Sentinel never authenticates or
> deploys on your behalf.

## 1. Build & run locally (optional sanity check)

```bash
docker build -t sentinel:local .
docker run --rm -p 8080:8080 sentinel:local
# open http://localhost:8080  (runs in demo mode: no DB, no API key)
```

## 2. Deploy to Cloud Run — simplest path (demo mode)

Cloud Build builds the Dockerfile from source; Cloud Run hosts it. This runs the
**self-contained demo** (bundled fixtures + synthetic corpus + offline drafter),
which is the right target for a public portfolio URL — no database, no keys.

```bash
gcloud config set project YOUR_PROJECT            # you do this
gcloud services enable run.googleapis.com cloudbuild.googleapis.com

gcloud run deploy sentinel \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --set-env-vars SENTINEL_BACKEND_MODE=demo
```

The command prints a `https://sentinel-XXXX-uc.a.run.app` URL — that's the live
demo. Cloud Run injects `$PORT` (8080); the container already binds it.

## 3. Optional: real LLM prose

The offline drafter is deterministic. To have the Drafter write with a real
model, store the key in Secret Manager (never in the image or env literals) and
reference it:

```bash
echo -n "sk-ant-..." | gcloud secrets create anthropic-key --data-file=-
gcloud run services update sentinel --region us-central1 \
  --update-secrets ANTHROPIC_API_KEY=anthropic-key:latest \
  --set-env-vars LLM_PROVIDER=anthropic
```

## 4. Optional: real metrics via Postgres (Cloud SQL)

Demo mode needs no database. To serve **real** Phase 2 metrics instead:

```bash
# Provision Cloud SQL (Postgres) — one-time
gcloud sql instances create sentinel-pg --database-version=POSTGRES_16 \
  --tier=db-f1-micro --region=us-central1
gcloud sql databases create sentinel --instance=sentinel-pg
# create a user; store the DSN in Secret Manager, then:
gcloud run services update sentinel --region us-central1 \
  --add-cloudsql-instances YOUR_PROJECT:us-central1:sentinel-pg \
  --update-secrets POSTGRES_DSN=sentinel-dsn:latest \
  --set-env-vars SENTINEL_BACKEND_MODE=postgres
```

Then apply the schema and seed metrics (from a machine with the pipeline
installed, pointing `POSTGRES_DSN` at the Cloud SQL instance):

```bash
python -c "from pipeline.db import apply_schema; apply_schema()"   # init.sql + agents.sql
# compute at least one day of metrics so /api/health has data:
python -m pipeline.daily_drift --date 2026-06-21 --raw-data data/paysim.csv
```

## What must run OUTSIDE Cloud Run

Cloud Run is request-scoped and stateless — it's the right home for the
**backend + dashboard**, not for long-running infrastructure:

| Component | Where it runs | For the hosted demo |
|---|---|---|
| **Postgres** | Cloud SQL (managed) — see step 4 | not needed in demo mode |
| **Kafka / Redpanda** | local `docker compose` (Phase 1), or a managed Kafka | not needed by the hosted app — the stream feeds Postgres upstream |
| **Airflow** | local `--profile airflow`, or Cloud Composer | run the daily job as a one-off / Cloud Run **Job** instead of a service |

**How the stream is seeded for a live demo:** the hosted service only *reads*
metrics — it never touches Kafka. For a real-data demo you run the Phase 1–2
pipeline (producer → consumer → sink → `daily_drift`) once against the Cloud SQL
instance to populate `daily_metrics` / `psi_bins` / `fairness_metrics`, then the
Cloud Run service serves them. The **demo mode** skips all of this and is the
recommended target for a public URL.

## Notes

- **No secrets in the image.** `.dockerignore` excludes `.env`, `data/`,
  `models/`, and all `*.pkl/*.csv/*.sqlite/*.jsonl`. Keys and DSNs are supplied
  only via Cloud Run env / Secret Manager.
- The agent-graph checkpointer and JSONL audit write to `/tmp` in the container
  (ephemeral). In `postgres` mode the audit log is the durable Postgres table;
  demo mode's `/tmp` audit resets when the instance recycles, which is fine for
  a demo.
- Single instance recommended for the demo (`--max-instances 1`) so the
  in-container demo queue is consistent across requests.
