"""RAG layer configuration.

Corpus location and retrieval knobs in one env-overridable place. No secrets
here — LLM keys live in agents/config + .env.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parent.parent

#: Where the governance corpus lives. The user places SR 26-2, SR 11-7, an EU
#: AI Act high-risk excerpt, NIST AI RMF, and a synthetic model-validation
#: report here. Never fetched, never committed (real letters may be large PDFs).
CORPUS_DIR: Path = Path(os.getenv("GOVERNANCE_CORPUS_DIR", REPO_ROOT / "docs" / "governance"))

#: How many citations retrieval returns by default.
TOP_K: int = int(os.getenv("RAG_TOP_K", "4"))
