# CLAUDE.md — Sentinel canonical spec

This file is the working contract for any agent (human or AI) contributing to
Sentinel. The full scoping brief lives at
`docs/research/Sentinel_Scoping_Brief.md` and is the source of truth; this file
distills the parts that govern day-to-day decisions.

---

## 1. Overview

Sentinel is a multi-agent copilot that monitors a deployed fraud-scoring model
over a real transaction stream, detects drift and performance/fairness decay
daily, retrieves the relevant governance policy via RAG, and drafts a
regulator-style risk memo with a recommended action — **which a human must
approve before anything happens**.

Built solo, end-to-end, on **public data only**, and deployed live.

## 2. Thesis

In April 2026, **SR 26-2** replaced SR 11-7 and deliberately placed generative
and agentic AI **outside** model-risk guidance, while keeping traditional ML
fraud models fully in scope.

Sentinel sits on that fault line:

- It **monitors an in-scope traditional fraud model** (the SR 26-2 / classical
  side).
- It **demonstrates the controls the carve-out now demands for agentic
  systems**: defined agent actions, mandatory human approval, immutable audit
  trail.

Every design choice should reinforce this dual posture.

## 3. Architecture

Real build, not simulated:

```
PaySim / IEEE-CIS CSV
    │
    ▼
Kafka (Redpanda locally)
    │
    ▼
XGBoost scoring  ──►  scored-txns topic
    │
    ▼
Daily Airflow DAG
    • PSI on model score (band-wise read, not just aggregate)
    • CSI per feature vs frozen baseline
    • precision / recall / FPR, fairness gaps
    │
    ▼
Postgres (metrics + audit log)
    │
    ▼
LangGraph agents:
    Monitor  ──►  Investigator (RAG)  ──►  Drafter  ──►  Human gate
    │
    ▼
FastAPI backend  ◄──►  React dashboard
    │
    ▼
Docker  ──►  GCP Cloud Run (public URL)
```

## 4. Stack

- **Language / ML:** Python, XGBoost
- **Streaming:** Kafka via Redpanda (local)
- **Orchestration:** Airflow
- **Storage:** Postgres
- **Agents:** LangGraph
- **RAG:** Haystack or RAGFlow, with citations
- **LLMs:** Anthropic + OpenAI behind a thin router
- **API / UI:** FastAPI + React
- **Infra:** Docker → GCP Cloud Run

## 5. Data policy

- **Public datasets only.** IEEE-CIS (primary stream), Bank Account Fraud Suite
  (protected attributes → fairness/bias audit), PaySim (optional — scale and
  replay).
- **Real bank data is confidential and is never used.** State this in the
  README.
- `data/` and `models/` are gitignored. Never commit raw data, derived
  artifacts, or model binaries.
- `.env` and any credential files are gitignored. Use `.env.example` for
  documented placeholders only.

## 6. Governance corpus (for RAG)

- **SR 26-2** — primary, current guidance.
- **SR 11-7** — historical reference; cite explicitly as superseded.
- **EU AI Act** — high-risk obligations (full enforcement Aug 2026); the
  fairness/bias angle, powered by the Bank Account Fraud Suite's protected
  attributes.
- **NIST AI RMF.**
- A **synthetic model-validation report** (clearly labeled synthetic).

Retrieval returns `doc:section` citations so every drafted claim is traceable.

## 7. Conventions — enforce throughout

### Drift and metrics

- **Daily PSI** on the model score and **CSI per feature** vs a **frozen
  baseline**.
- Bands: `<0.10` stable, `0.10–0.25` monitor, `>0.25` investigate.
- Read PSI **band-wise** (per-bin direction), not just the aggregate — a
  middling aggregate can hide a dangerous shift at the decision boundary.
- Also track model **health metrics** daily: precision, recall, FPR, and
  **fairness gaps** across the protected-attribute slices.

### Model code

- **Train and serve features must stay identical** — exactly one shared feature
  module, imported by both paths. No parallel implementations.
- The XGBoost baseline is **frozen and versioned**. Every score and every drift
  reading is attributable to a specific model version in the audit log.

### Agent outputs

- Every agent output translates drift into a **business implication**: name the
  cost type, a rough size, and the stakeholder to route to. The Drafter routes
  by the **direction of the shift** (read band-wise):

  | Shift | Mechanism | Cost type | Route to |
  | --- | --- | --- | --- |
  | **High-side** | model over-flagging | **false declines** (lost revenue, friction, investigation load) | Product / Sales / CX |
  | **Low-side** | under-detection | **fraud losses + regulatory exposure** | Risk / Finance / Legal |
  | **Mid / threshold** | unstable at the decision boundary | **decision instability** | Ops / Finance planning |

- Every agent decision **cites its policy source** (`doc:section`) and writes to
  the immutable audit log.
- **Nothing side-effecting happens without human approval.** The human gate is
  not optional, and not a checkbox the agent can flip. **Exceptions escalate**
  rather than being silently swallowed.

### Workflow

- Small, verifiable steps. Commit after each phase with a clear message
  describing what works now.
- Prefer editing existing files to adding new ones. No speculative
  abstractions.
- No secrets, no private data, no scraped real-bank artifacts — ever.

## 8. Repository layout

```
data/        # gitignored — public datasets, locally derived
models/      # gitignored — trained artifacts, locally derived
pipeline/    # ingestion, feature module, scoring, drift jobs, Airflow DAGs
agents/      # LangGraph agent definitions (Monitor, Investigator, Drafter, gate)
rag/         # corpus loaders, indexers, retrievers, citation plumbing
backend/     # FastAPI service, audit log, human-gate endpoints
frontend/    # React dashboard
infra/       # Docker, Compose, Cloud Run deploy, IaC
docs/        # research/, ADRs, runbooks, governance notes
```

## 9. Honest scope and limits

Sentinel is a **prototype, not production**. On public/synthetic data, results
are **illustrative, not deployable**. LLM drafts are RAG-grounded with citations
to limit fabrication. Sentinel **assists** a human model-risk manager — it never
self-heals or acts autonomously.

Out of scope (for now):

- Real bank data, scraped PII, or any non-public source.
- Auto-applied actions from agents.
- Replacing human judgment on model risk — Sentinel **augments** the validator,
  it does not substitute.
