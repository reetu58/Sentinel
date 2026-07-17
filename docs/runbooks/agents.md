# Agents & RAG runbook (Phase 3)

The LangGraph copilot that turns a drift breach into a cited, human-gated memo.

## Components

| Component | Where | What it does |
|---|---|---|
| RAG retrieval | `rag/` | Haystack BM25 index over `docs/governance/`; returns `Citation`s (`doc:section`) |
| LLM router | `agents/llm.py` | `anthropic` / `openai` / `offline`, one config switch; keys from `.env` |
| Agent graph | `agents/graph.py` | LangGraph `Monitor → Investigator → Drafter → Human gate` |
| Node logic | `agents/nodes.py` | materiality, band-wise direction, RAG, four-part memo |
| Prompts | `agents/prompts/*.md` | one readable file per agent |
| Audit log | `agents/audit.py` + `infra/sql/agents.sql` | append-only `agent_runs`, `memos`, `decisions` |
| CLI | `agents/run.py` | run the graph on a breach |

## Why Haystack BM25 (not RAGFlow, not dense embeddings)

Haystack is a pip-only library — no separate server, which fits a solo build
(RAGFlow is a full containerized service). BM25 lexical retrieval needs no
embedding-model API key, is deterministic, and runs offline, so retrieval and
the agents that depend on it are verifiable in CI. The corpus is small (a
handful of governance docs) where lexical retrieval is strong. Swapping in a
dense retriever later is a localized change behind the `Retriever` interface.

## Why the decision logic is deterministic

Materiality (Monitor) and drift direction (Investigator) are computed
deterministically — materiality is a governance threshold, and direction is
read straight from the band-wise PSI breakdown. A control system shouldn't ask
a stochastic model "is this breach material?" The **LLM is used where language
matters** — the Drafter — behind the router. So the graph runs identically
offline (deterministic composer) or against Anthropic/OpenAI.

## The human gate

The graph compiles with `interrupt_before=["human_gate"]` and a checkpointer,
so it **pauses before** the gate and persists state. Nothing proceeds until a
reviewer's decision is injected and the graph is resumed. It never
auto-approves. Phase 4 exposes approve/reject as an API + dashboard action;
Phase 3's CLI simulates it with `--decision`.

## Run it (offline, no DB or API key)

```bash
pip install -r pipeline/requirements.txt

# Draft a memo from a RED breach fixture, then PAUSE at the gate:
python -m agents.run \
  --breach-file agents/tests/fixtures/breach_red.json \
  --corpus-dir rag/tests/fixtures/governance \
  --offline

# Same, but supply the human decision and resume through the gate:
python -m agents.run \
  --breach-file agents/tests/fixtures/breach_red.json \
  --corpus-dir rag/tests/fixtures/governance \
  --offline \
  --decision approve --reviewer human:mrm@bank.example \
  --note "Confirmed high-side drift; threshold review scheduled."
```

Offline, the audit log is written append-only to `models/audit_log.jsonl`.

## Run it against Phase 2 Postgres + the real corpus

```bash
# Place the real corpus in docs/governance/ (see docs/governance/README.md),
# set ANTHROPIC_API_KEY (or OPENAI_API_KEY) in .env, then:
python -m agents.run --date 2026-06-21 --model-version v1
```

With a key set, `LLM_PROVIDER=auto` selects the real model; the four-part memo
and the deterministic facts/citations are unchanged — only the prose improves.

## Audit log

Every node writes its input + output + citations; the drafted memo and the
human decision are separate append-only records. Inspect:

```sql
SELECT node, seq, jsonb_array_length(citations) AS n_cites
FROM agent_runs WHERE run_id = '<run_id>' ORDER BY seq;

SELECT id, color, direction, status FROM memos WHERE run_id = '<run_id>';

SELECT decision, reviewer, ts FROM decisions WHERE run_id = '<run_id>';
```

Or, offline, read `models/audit_log.jsonl` (one JSON record per line).
