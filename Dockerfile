# Sentinel — single-service image for Cloud Run.
#
# Stage 1 builds the React dashboard; stage 2 runs the FastAPI backend and
# serves the built dashboard as static files, so the whole app is ONE container
# and ONE public URL. No secrets are baked in — configuration and any API keys
# come from Cloud Run env vars / Secret Manager at deploy time.
#
# Default runtime mode is SENTINEL_BACKEND_MODE=demo: the live demo runs
# self-contained from bundled fixtures + the synthetic governance corpus, with
# no external database or API key required. Flip to postgres via env to point
# at Cloud SQL (see docs/runbooks/deploy.md).

# ---- Stage 1: build the frontend ----
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: backend runtime ----
FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    SENTINEL_BACKEND_MODE=demo \
    STATIC_DIR=/app/static \
    AGENT_CHECKPOINT_DB=/tmp/agent_checkpoints.sqlite \
    AUDIT_JSONL_PATH=/tmp/audit_log.jsonl

WORKDIR /app

# Install backend deps first for layer caching.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install -r /app/backend/requirements.txt

# App code needed at serve time (backend + the agent/rag/pipeline libs it imports).
COPY backend/ /app/backend/
COPY agents/ /app/agents/
COPY rag/ /app/rag/
COPY pipeline/ /app/pipeline/

# Built dashboard from stage 1.
COPY --from=frontend /app/frontend/dist /app/static

# Cloud Run sends traffic to $PORT (default 8080). Bind 0.0.0.0.
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn backend.app:app --host 0.0.0.0 --port ${PORT}"]
