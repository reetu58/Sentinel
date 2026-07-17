"""Backend configuration.

Mode selection:
  SENTINEL_BACKEND_MODE = auto | postgres | demo
    auto    -> try Postgres; fall back to demo if unreachable (default)
    postgres-> read metrics/queue/audit from the Phase 2/3 tables
    demo    -> read from bundled fixtures + JSONL audit (no DB needed)

No secrets here; LLM keys come from .env via the agents/llm router.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parent.parent

BACKEND_MODE: str = os.getenv("SENTINEL_BACKEND_MODE", "auto")

HOST: str = os.getenv("BACKEND_HOST", "127.0.0.1")
PORT: int = int(os.getenv("BACKEND_PORT", "8000"))

#: Allowed CORS origins for the React dev server.
CORS_ORIGINS: list[str] = os.getenv(
    "BACKEND_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")

#: LangGraph checkpointer DB — lets the paused graph resume across separate
#: HTTP requests (and process restarts). Lives under models/ (gitignored).
CHECKPOINT_DB: Path = Path(
    os.getenv("AGENT_CHECKPOINT_DB", REPO_ROOT / "models" / "agent_checkpoints.sqlite")
)

#: Governance corpus for retrieval. Demo mode falls back to the synthetic
#: fixtures so the loop runs with nothing placed in docs/governance/.
DEMO_CORPUS_DIR: Path = REPO_ROOT / "rag" / "tests" / "fixtures" / "governance"

#: Demo breach fixture (a real RED high-side breach computed via the PSI math).
DEMO_BREACH_FILE: Path = REPO_ROOT / "agents" / "tests" / "fixtures" / "breach_red.json"

#: Built React dashboard to serve as static files (single-service deploy). In
#: the Docker image the frontend build is copied to /app/static and this points
#: at it; locally it's usually unset (you run `npm run dev` with the vite proxy).
STATIC_DIR: str = os.getenv("STATIC_DIR", "")
