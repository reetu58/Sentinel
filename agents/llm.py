"""Thin LLM router — swap Anthropic / OpenAI with one config change.

A single `complete(system, user)` interface over three providers:

- ``anthropic`` — Claude via the Anthropic SDK.
- ``openai``    — GPT via the OpenAI SDK.
- ``offline``   — a deterministic, no-API-key composer. It does NOT call any
  model; it assembles the memo from the structured facts the Drafter passes in
  its user prompt (the finding, the business routing, and the retrieved
  citations). This keeps the whole graph verifiable offline and in CI, and
  makes the "drafting" step reproducible. With a real key configured, the
  router uses the actual model instead.

Provider resolution (when LLM_PROVIDER=auto): anthropic if ANTHROPIC_API_KEY is
set, else openai if OPENAI_API_KEY is set, else offline. Keys come from the
environment / .env only.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: str
    model: str


def resolve_provider() -> str:
    """Pick the provider, honoring LLM_PROVIDER and falling back to keys."""
    provider = config.LLM_PROVIDER.lower()
    if provider != "auto":
        return provider
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "offline"


class LLMRouter:
    """Routes `complete()` to the configured provider."""

    def __init__(self, provider: str | None = None):
        self.provider = (provider or resolve_provider()).lower()

    @property
    def model(self) -> str:
        return {
            "anthropic": config.ANTHROPIC_MODEL,
            "openai": config.OPENAI_MODEL,
            "offline": "offline-deterministic",
        }.get(self.provider, "unknown")

    def complete(self, system: str, user: str) -> LLMResponse:
        if self.provider == "anthropic":
            return self._anthropic(system, user)
        if self.provider == "openai":
            return self._openai(system, user)
        if self.provider == "offline":
            return LLMResponse(_offline_compose(user), "offline", self.model)
        raise ValueError(f"unknown LLM provider: {self.provider!r}")

    def _anthropic(self, system: str, user: str) -> LLMResponse:
        import anthropic  # lazy

        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=config.LLM_MAX_TOKENS,
            temperature=config.LLM_TEMPERATURE,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in msg.content if block.type == "text")
        return LLMResponse(text, "anthropic", config.ANTHROPIC_MODEL)

    def _openai(self, system: str, user: str) -> LLMResponse:
        from openai import OpenAI  # lazy

        client = OpenAI()
        resp = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            max_tokens=config.LLM_MAX_TOKENS,
            temperature=config.LLM_TEMPERATURE,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return LLMResponse(resp.choices[0].message.content or "", "openai", config.OPENAI_MODEL)


# --- Offline deterministic composer -------------------------------------
#
# The Drafter passes the structured facts as a JSON block in its user prompt
# (see agents/prompts/drafter.md and nodes.drafter). Offline mode parses that
# block and renders the four-part memo verbatim from those facts — no
# invention, every citation already supplied by the RAG layer.


def _offline_compose(user_prompt: str) -> str:
    facts = _extract_facts(user_prompt)
    if facts is None:
        # Nothing structured to work with; echo so the pipeline still proceeds.
        return user_prompt.strip()

    f = facts
    cites = f.get("citations", [])
    cite_lines = [
        f"- [{c['citation']}] {c.get('section_title', '')}".rstrip()
        for c in cites
    ] or ["- (no citations retrieved)"]
    cite_inline = ", ".join(c["citation"] for c in cites) or "(none)"

    rough_size = f.get("rough_size", "to be sized with Finance")
    lines = [
        f"# Model Risk Alert — {f.get('metric_label', 'model drift')} "
        f"({f.get('color', 'AMBER')})",
        "",
        "## (a) Finding",
        f"The model's {f.get('finding_subject', 'score distribution')} has shifted "
        f"{_direction_phrase(f.get('direction'))}. The Population Stability Index is "
        f"{f.get('psi_value')} ({f.get('band')} / {f.get('color')}), read band-wise: "
        f"{f.get('band_wise_note', 'the shift is concentrated away from the stable bins.')}",
        "",
        "## (b) Business implication",
        f"Mechanism: {f.get('mechanism')}. Cost type: **{f.get('cost_type')}**. "
        f"Rough size: {rough_size}. Route to: **{f.get('route_to')}**.",
        "",
        "## (c) Policy basis",
        "This finding and the recommended handling are grounded in:",
        *cite_lines,
        f"\nCitations: {cite_inline}.",
        "",
        "## (d) Recommended action",
        f"{f.get('recommended_action')}",
        "",
        "_Awaiting human approval. No action is taken until a reviewer approves._",
    ]
    return "\n".join(lines)


_FACTS_RE = re.compile(r"<facts>\s*(\{.*?\})\s*</facts>", re.DOTALL)


def _extract_facts(user_prompt: str) -> dict | None:
    m = _FACTS_RE.search(user_prompt)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _direction_phrase(direction: str | None) -> str:
    return {
        "high": "toward the high (over-flagging) end of the score range",
        "low": "toward the low (under-detection) end of the score range",
        "mid": "around the decision threshold (instability at the operating point)",
        "stable": "only marginally",
    }.get(direction or "", "in a non-stable direction")
