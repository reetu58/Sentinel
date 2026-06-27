"""Agent system prompts, kept as readable Markdown files in this directory."""

from __future__ import annotations

from pathlib import Path

_PROMPT_DIR = Path(__file__).resolve().parent


def load_prompt(name: str) -> str:
    """Load the system prompt for an agent (e.g. load_prompt('drafter'))."""
    path = _PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {path}")
    return path.read_text(encoding="utf-8")
