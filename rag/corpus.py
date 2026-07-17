"""Load and chunk the governance corpus into citable units.

Every chunk carries a STABLE `doc:section` citation so nothing an agent later
claims is uncited. The doc id is canonical and short (e.g. ``SR_26-2``); the
section id is taken from a leading section number in the heading when present
(``## III.B Threshold setting`` -> ``III.B``), otherwise a slug of the heading
text. Stability matters: a drafted memo cites ``SR_26-2:III.B`` and that string
must resolve to the same passage across re-indexes.

Supported formats: Markdown (``.md``) and plain text (``.txt``). Markdown is
chunked on headings; a heading and the body beneath it (until the next heading)
form one chunk. Plain-text files become a single chunk. PDFs are intentionally
out of scope here — convert governance PDFs to Markdown first (keeps chunk
boundaries and section numbers under our control rather than a parser's).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Canonical doc ids for the known corpus. Unknown files fall back to an
#: uppercased slug of the filename stem, so dropping in a new doc still works.
DOC_IDS: dict[str, tuple[str, str]] = {
    "sr_26_2": ("SR_26-2", "SR 26-2 — Guidance on Model Risk Management (2026)"),
    "sr_11_7": ("SR_11-7", "SR 11-7 — Guidance on Model Risk Management (2011, superseded)"),
    "eu_ai_act": ("EU_AI_Act", "EU AI Act — High-Risk Obligations (excerpt)"),
    "nist_ai_rmf": ("NIST_AI_RMF", "NIST AI Risk Management Framework"),
    "model_validation_synthetic": (
        "ModelVal",
        "Synthetic Model Validation Report (SYNTHETIC — illustrative only)",
    ),
}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
# A leading section label like "3", "3.2", "III", "III.B", "A.1".
_SECTION_LABEL_RE = re.compile(r"^([0-9IVXivx]+(?:\.[0-9A-Za-z]+)*)\b[.)]?\s+(.*)$")


@dataclass(frozen=True)
class Chunk:
    """One citable passage."""

    doc_id: str
    doc_title: str
    section_id: str
    section_title: str
    text: str

    @property
    def citation(self) -> str:
        """The canonical ``doc:section`` citation string."""
        return f"{self.doc_id}:{self.section_id}"


def _slug(text: str, *, maxlen: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:maxlen] or "section"


def _doc_identity(stem: str) -> tuple[str, str]:
    key = stem.lower()
    if key in DOC_IDS:
        return DOC_IDS[key]
    doc_id = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_").upper() or "DOC"
    return doc_id, stem


def _section_identity(heading_text: str, seen: set[str]) -> tuple[str, str]:
    """Return (section_id, section_title) for a heading, ensuring uniqueness."""
    m = _SECTION_LABEL_RE.match(heading_text)
    if m:
        section_id = m.group(1)
        title = heading_text
    else:
        section_id = _slug(heading_text)
        title = heading_text
    # Disambiguate collisions deterministically.
    base = section_id
    n = 2
    while section_id in seen:
        section_id = f"{base}-{n}"
        n += 1
    seen.add(section_id)
    return section_id, title


def _chunk_markdown(text: str, doc_id: str, doc_title: str) -> list[Chunk]:
    lines = text.splitlines()
    chunks: list[Chunk] = []
    seen: set[str] = set()

    # Preamble before the first heading (if any) becomes a "preamble" section.
    current_heading: str | None = None
    buffer: list[str] = []

    def flush(heading: str | None, body: list[str]) -> None:
        body_text = "\n".join(body).strip()
        if heading is None:
            if not body_text:
                return
            section_id, section_title = _section_identity("preamble", seen)
            chunks.append(
                Chunk(doc_id, doc_title, section_id, "Preamble", body_text)
            )
            return
        section_id, section_title = _section_identity(heading, seen)
        full = heading if not body_text else f"{heading}\n\n{body_text}"
        chunks.append(Chunk(doc_id, doc_title, section_id, section_title, full.strip()))

    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            flush(current_heading, buffer)
            current_heading = m.group(2).strip()
            buffer = []
        else:
            buffer.append(line)
    flush(current_heading, buffer)
    return chunks


def load_corpus(corpus_dir: Path) -> list[Chunk]:
    """Load every ``.md`` / ``.txt`` file under ``corpus_dir`` into Chunks.

    Raises FileNotFoundError if the directory is missing (a clear signal that
    the user hasn't placed the corpus yet) and ValueError if it's empty.
    """
    corpus_dir = Path(corpus_dir)
    if not corpus_dir.exists():
        raise FileNotFoundError(
            f"governance corpus dir not found: {corpus_dir}. Place SR 26-2, "
            "SR 11-7, the EU AI Act excerpt, NIST AI RMF, and the synthetic "
            "model-validation report there (see docs/governance/README.md)."
        )

    chunks: list[Chunk] = []
    files = sorted(
        [p for p in corpus_dir.iterdir() if p.suffix.lower() in (".md", ".txt")]
    )
    for path in files:
        if path.name.lower() == "readme.md":
            continue  # the explainer file, not corpus content
        doc_id, doc_title = _doc_identity(path.stem)
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".md":
            doc_chunks = _chunk_markdown(text, doc_id, doc_title)
        else:
            section_id, _ = _section_identity("full", set())
            doc_chunks = [Chunk(doc_id, doc_title, section_id, "Full text", text.strip())]
        chunks.extend(doc_chunks)

    if not chunks:
        raise ValueError(
            f"no .md/.txt governance documents found in {corpus_dir}."
        )
    return chunks
