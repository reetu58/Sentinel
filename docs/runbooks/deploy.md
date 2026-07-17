# Deploy runbook — Docker → Render (live) / Cloud Run / others

Sentinel ships as **one container**: a multi-stage `Dockerfile` builds the React
dashboard and the FastAPI backend serves it as static files alongside the API,
so there's one image and one public URL. No secrets are baked into the image —
all configuration comes from the host's env vars / secret store at deploy time.

**The live demo is hosted free on Render:
<https://sentinel-g6gw.onrender.com/>.** Render is the simplest path and the one
below leads with it; Cloud Run and Hugging Face Spaces are documented as
alternatives.

## 1. Build & run locally (optional sanity check)

```bash
docker build -t sentinel:local .
docker run --rm -p 8080:8080 sentinel:local
# open http://localhost:8080  (runs in demo mode: no DB, no API key)
```

## 2. Render — the live-demo path (free, no credit card)

A `render.yaml` blueprint is checked in at the repo root, so this is one click.

1. Push the repo to GitHub (public is fine).
2. Go to <https://dashboard.render.com> → **New +** → **Blueprint** → pick the
   repo. Render reads `render.yaml`, builds the root `Dockerfile`, and deploys a
   free web service in demo mode (no database, no API key).
3. It assigns a URL like `https://sentinel-XXXX.onrender.com` — that's the live
   demo. Paste it into the README's `[Live demo]` link.

Render injects `$PORT` automatically (the container's CMD already binds it) and
health-checks `/api/status`. **Free-tier note:** the instance **sleeps when
idle**, so the first load after a quiet spell cold-starts in ~30–60 s, then it's
fast — fine for a portfolio link (warm it up before a live demo).

> Other free container hosts work the same way (they read the Dockerfile and
> expose `$PORT`): **Fly.io** (`fly launch`), **Railway**.

## 3. Hugging Face Spaces — alternative (nice for an ML audience)

1. Create a Space at <https://huggingface.co/new-space> → SDK: **Docker** →
   **Blank**.
2. In the Space's own `README.md` front matter, set the container port:
   ```yaml
   ---
   title: Sentinel
   sdk: docker
   app_port: 8080
   ---
   ```
3. Push the Sentinel code to the Space's git remote (or link the GitHub repo).
   HF builds the root Dockerfile and serves it at
   `https://<user>-sentinel.hf.space`.

The image already defaults to `SENTINEL_BACKEND_MODE=demo` and writes its
ephemeral checkpoint/audit to `/tmp`, so no extra config is needed.

> **Why not Vercel/Netlify?** They target static sites + short serverless
> functions. Sentinel runs a long-lived FastAPI process with the agent graph and
> a checkpointer held across requests — a real container host (Render / HF /
> Fly) is the right fit; splitting the app would only add CORS wiring.

## 4. Cloud Run — alternative (GCP)

If you prefer GCP, the same image deploys to Cloud Run. You run `gcloud auth`
and set the project yourself; Sentinel never authenticates or deploys for you.

```bash
gcloud config set project YOUR_PROJECT
gcloud services enable run.googleapis.com cloudbuild.googleapis.com

gcloud run deploy sentinel \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi --cpu 1 --max-instances 1 \
  --set-env-vars SENTINEL_BACKEND_MODE=demo
```

It prints a `https://sentinel-XXXX-uc.a.run.app` URL. Cloud Run injects `$PORT`
(8080); the container already binds it.

## 5. Optional upgrades (any host)

**Real LLM prose.** The offline drafter is deterministic. To draft with a real
model, set the key via the host's **secret store** (never in the image) —
`ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) plus `LLM_PROVIDER=anthropic`. On
Cloud Run that's Secret Manager:

```bash
echo -n "sk-ant-..." | gcloud secrets create anthropic-key --data-file=-
gcloud run services update sentinel --region us-central1 \
  --update-secrets ANTHROPIC_API_KEY=anthropic-key:latest \
  --set-env-vars LLM_PROVIDER=anthropic
```

**Real metrics via Postgres.** Demo mode needs no database. To serve real
Phase 2 metrics, point the service at a managed Postgres (e.g. Cloud SQL) with
`SENTINEL_BACKEND_MODE=postgres` and `POSTGRES_DSN=...` (from a secret), then
apply the schema and seed at least one day of metrics:

```bash
python -c "from pipeline.db import apply_schema; apply_schema()"   # init.sql + agents.sql
python -m pipeline.daily_drift --date 2026-06-21 --raw-data data/paysim.csv
```

## What must run OUTSIDE the web host

The hosted service is request-scoped — it's the right home for the **backend +
dashboard**, not for long-running infrastructure:

| Component | Where it runs | For the hosted demo |
|---|---|---|
| **Postgres** | managed (Cloud SQL / Neon / Render Postgres) | not needed in demo mode |
| **Kafka / Redpanda** | local `docker compose` (Phase 1), or managed Kafka | not needed by the hosted app — the stream feeds Postgres upstream |
| **Airflow** | local `--profile airflow`, or Cloud Composer | run the daily job as a one-off / scheduled Job |

**How the stream is seeded for a real-data demo:** the hosted service only
*reads* metrics — it never touches Kafka. You run the Phase 1–2 pipeline
(producer → consumer → sink → `daily_drift`) once against the managed Postgres to
populate `daily_metrics` / `psi_bins` / `fairness_metrics`, then the service
serves them. **Demo mode** skips all of this and is the recommended target for a
public URL.

## Notes

- **No secrets in the image.** `.dockerignore` excludes `.env`, `data/`,
  `models/`, and all `*.pkl/*.csv/*.sqlite/*.jsonl`. Keys and DSNs are supplied
  only via the host's env / secret store.
- The agent-graph checkpointer and JSONL audit write to `/tmp` in the container
  (ephemeral). In `postgres` mode the audit log is the durable Postgres table;
  demo mode's `/tmp` audit resets when the instance recycles — fine for a demo.
- Single instance recommended for the demo so the in-container demo queue is
  consistent across requests (`render.yaml` uses the free plan's single
  instance; on Cloud Run pass `--max-instances 1`).
