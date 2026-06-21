# Sentinel — Fraud Model Risk Copilot
**Scoping & positioning brief**

## Thesis
In April 2026, SR 26-2 replaced SR 11-7 and deliberately placed generative and agentic AI *outside* the scope of US model-risk guidance — calling them "novel and rapidly evolving" — while directing banks to govern them under their own risk-management practices. Traditional ML fraud and credit models remain fully in scope. The result is a governance gap that banks now own with no regulatory template.

Sentinel is built directly on that fault line. It does two things at once: it **monitors an in-scope traditional fraud model**, and it **demonstrates the controls the carve-out now demands for agentic systems** — defined agent actions, mandatory human approval, and a complete activity audit trail. That dual position is the project's strongest interview line.

## What it is
A multi-agent copilot that watches a deployed fraud-scoring model over a real transaction stream, detects drift and performance/fairness decay **daily**, retrieves the relevant governance policy via RAG, and drafts a regulator-style risk memo with a recommended action — which a human must approve before anything happens. Built solo, end to end, on public data, deployed live.

## Why it matters (the business case)
A fraud model that quietly degrades is expensive in two directions: it either over-blocks good customers (false declines → lost revenue, friction, investigation load) or under-detects fraud (direct losses + regulatory exposure). Catching that drift early, daily, and translating it into a business decision is manual, slow work today. Sentinel automates the analysis and the policy lookup while keeping the human in charge of the decision.

## Data — all public (real transaction data is confidential)
- **IEEE-CIS Fraud Detection** — real-world anonymized e-commerce transactions; the primary stream.
- **Bank Account Fraud Suite (NeurIPS 2022)** — ships protected attributes; powers the fairness/bias audit (the EU AI Act angle).
- **PaySim** — synthetic mobile-money dataset, optional, for scale and replay.

Using public datasets *because* real data is confidential is itself a governance-aware signal — say it explicitly.

## Architecture — real build, not simulated
Stream → score → monitor → investigate → draft → human gate → deploy.

- **Streaming:** IEEE-CIS replayed through **Kafka** (Redpanda locally) as a live stream.
- **Scoring:** **XGBoost** baseline, frozen and versioned; train/serve features kept identical.
- **Monitoring:** a **daily Airflow DAG** computes PSI on the model score + CSI per feature against a frozen baseline, plus precision/recall/FPR and fairness gaps → **Postgres**.
- **Agents (LangGraph):** Monitor → Investigator (RAG) → Drafter → Human gate.
- **Serving:** **FastAPI** backend + **React** dashboard.
- **Deploy:** **Docker** → **GCP Cloud Run** (public URL).

> Note: an earlier scoping draft recommended simulating the stream with a Python loop and treating Kafka/deployment as future work. That is re-scoped here. The target roles screen on hands-on Kafka, Airflow, and live deployment, so the thin-but-real versions are built, not deferred.

## Monitoring — daily, band-wise, business-translated
PSI runs **daily** against a frozen reference, banded **< 0.10 stable / 0.10–0.25 monitor / > 0.25 investigate**. It is read **band-wise** (per-bin direction), not just as an aggregate number:

- **High-side shift** → model over-flagging → **false declines** → route to Product / Sales / CX.
- **Low-side shift** → under-detection → **fraud losses + regulatory exposure** → route to Risk / Finance / Legal.
- **Mid / threshold shift** → **decision instability** → route to Ops / Finance planning.

The Drafter agent names the cost type, a rough size, and the stakeholder to route to — turning a metric into a business decision.

## Governance corpus (RAG, with citations)
SR 26-2 (primary, 2026) · SR 11-7 (historical predecessor) · EU AI Act high-risk obligations (full enforcement Aug 2026) · NIST AI RMF · a synthetic model-validation report. Retrieval returns `doc:section` citations so every drafted claim is traceable.

## Human-in-the-loop = the carve-out controls
No agent action ships without human approval. Every agent decision is cited to policy and written to an **immutable audit log**, and exceptions escalate. These are precisely the controls SR 26-2 leaves banks to build for agentic systems — so the design isn't just safe, it's a worked example of post-SR-26-2 agentic governance.

## Honest scope and limits
Prototype, not production. Public/synthetic data, so results are illustrative, not deployable. The streaming and orchestration layer is a deliberate thin-but-real learning build — in my day-job analyst role I consume transformed data; here I built the pipeline myself. LLM drafts are RAG-grounded with citations to limit fabrication. Sentinel assists a human model-risk manager; it never self-heals or acts autonomously.

## Resume talking points
- Built and deployed an end-to-end multi-agent fraud model-governance copilot (LangGraph; Anthropic + OpenAI via a thin router) on public data — monitors a deployed fraud model for drift, fairness, and false-positive decay, retrieves SR 26-2 / NIST AI RMF policy via RAG, and drafts cited risk memos requiring human approval.
- Engineered the streaming and orchestration layer solo — IEEE-CIS replayed through Kafka, scored with XGBoost, with daily drift and health metrics (band-wise PSI, CSI, FPR, fairness gaps) computed via Airflow into Postgres.
- Designed the human-approval gate, scoped agent actions, and immutable audit log to mirror the governance controls SR 26-2 leaves banks to build for agentic systems.
- Shipped the full system — FastAPI, React, Docker, GCP Cloud Run — from problem discovery to live demo in under two weeks.
