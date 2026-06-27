"""Agent-layer configuration: LLM router + graph + audit settings.

One env-overridable place so swapping Anthropic <-> OpenAI is a single change.
Secrets (API keys) are read from the environment / .env only — never committed.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# --- LLM router ----------------------------------------------------------

#: Provider for drafting. One of: "anthropic", "openai", "offline".
#: "offline" is a deterministic, no-API-key composer used for local
#: verification and CI; it is selected automatically when no key is present.
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "auto")

#: Default model per provider. Anthropic default is the latest Claude.
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")

#: Sampling — low temperature: this is regulator-facing drafting, not prose.
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "1200"))

# --- Audit ---------------------------------------------------------------

#: When Postgres isn't reachable (e.g. offline verification), the audit log
#: falls back to this append-only JSONL file so runs are still fully recorded.
AUDIT_JSONL_PATH: Path = Path(
    os.getenv("AUDIT_JSONL_PATH", REPO_ROOT / "models" / "audit_log.jsonl")
)

# --- Graph ---------------------------------------------------------------

#: Materiality: an amber breach is only escalated by the Monitor if its value
#: reaches this floor (so not every 0.10 wiggle becomes a memo). Red always
#: escalates. Tunable without code changes.
MATERIAL_AMBER_MIN: float = float(os.getenv("MATERIAL_AMBER_MIN", "0.15"))
