<div align="center">

# 🛡️ Sentinel

### A Fraud Model Risk Copilot for the post-SR&nbsp;26-2 world

*Watch a deployed fraud model drift in real time. Translate the drift into a business decision. Cite the governing policy. Then stop — and wait for a human to approve.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Data: public only](https://img.shields.io/badge/data-public%20only-brightgreen.svg)](docs/runbooks/data.md)
[![Phase 1: streaming spine](https://img.shields.io/badge/phase%201-streaming%20spine%20✓-success.svg)](#-project-status)
[![Phase 2: drift + fairness](https://img.shields.io/badge/phase%202-drift%20+%20fairness%20✓-success.svg)](#-project-status)
[![Phase 3: agents + RAG](https://img.shields.io/badge/phase%203-agents%20+%20RAG%20✓-success.svg)](#-project-status)
[![Human-in-the-loop](https://img.shields.io/badge/actions-human%20approved-orange.svg)](#-design-principles)

</div>

---

## The one-paragraph pitch

In **April 2026, SR 26-2 replaced SR 11-7** and deliberately placed generative and
agentic AI **outside** US model-risk guidance — while keeping traditional ML fraud
models **fully in scope**. That leaves banks owning the riskiest AI (agents that act)
with no regulatory template, and still on the hook for the classical models those
agents would touch. **Sentinel is built directly on that fault line:** it monitors an
in-scope traditional fraud model **and** demonstrates the exact controls the carve-out
now demands of agentic systems — scoped agent actions, mandatory human approval, and an
immutable, policy-cited audit trail.

> Built solo, end-to-end, on **public data only**, and deployed live.

---

## Why it matters (the business case)

A fraud model that quietly degrades is expensive in **two opposite directions**, and a
single drift number hides which one you're bleeding from:

| Drift direction | What's happening | The cost | Route to |
| --- | --- | --- | --- |
| **High-side** shift | model over-flagging | **false declines** — lost revenue, friction, investigation load | Product / Sales / CX |
| **Low-side** shift | under-detection | **fraud losses + regulatory exposure** | Risk / Finance / Legal |
| **Mid / threshold** shift | unstable at the decision boundary | **decision instability** | Ops / Finance planning |

Catching this early, daily, and turning it into a routed business decision is slow,
manual work today. Sentinel automates the **analysis and the policy lookup** — and keeps
the human firmly in charge of the **decision**.

---

## Architecture

A real build, not a simulation — Kafka, Airflow, and a live deployment are first-class,
not future work.

```
   PaySim / IEEE-CIS CSV  (public data)
            │
            ▼
   Kafka  (Redpanda locally)  ──►  transactions topic
            │
            ▼
   XGBoost scoring  ──►  scored-txns topic  (score + ground-truth label)
            │
            ▼
   Daily Airflow DAG
     • PSI on model score — read BAND-WISE, not just the aggregate
     • CSI per feature vs a frozen baseline
     • precision / recall / FPR + fairness gaps
            │
            ▼
   Postgres  (metrics + immutable audit log)
            │
            ▼
   LangGraph agents
     Monitor ──► Investigator (RAG, cited) ──► Drafter ──► 🧑 Human gate
            │
            ▼
   FastAPI backend  ◄──►  React dashboard
            │
            ▼
   Docker ──► GCP Cloud Run  (public URL)
```

---

## 🚦 Project status

Sentinel is being built in honest, verifiable phases. This table is the source of truth
for what actually runs today.

| Phase | Scope | Status |
| --- | --- | --- |
| **1 — Streaming spine** | Redpanda + Postgres via Compose · shared feature module · XGBoost baseline (PR-AUC, imbalance-aware) · producer → `transactions` · consumer → `scored-txns` with label | ✅ **Built** |
| **2 — Daily drift, trend & fairness** | Frozen reference baseline · band-wise PSI + per-feature CSI + precision/recall/FPR · sustained-rise trend detector (early warning before RED) · BAF fairness audit (per-slice FPR + approval gaps) · Postgres schema + sink · daily CLI + Airflow DAG | ✅ **Built** |
| **3 — Agents + RAG** | Haystack BM25 RAG over the governance corpus (`doc:section` citations) · LangGraph Monitor → Investigator → Drafter → human gate (interrupt-based pause) · thin Anthropic/OpenAI/offline LLM router · immutable append-only audit log (agent runs, memos, decisions) | ✅ **Built** |
| **4 — API + dashboard** | FastAPI service, audit-log + approve/reject endpoints · React dashboard | ⬜ Planned |
| **5 — Deploy** | Docker → GCP Cloud Run, public URL | ⬜ Planned |

---

## ⚡ Quickstart (Phase 1)

**Prerequisites:** Docker, Python 3.11+.

```bash
# 1. install deps
pip install -r pipeline/requirements.txt

# 2. get data — drop the real Kaggle PaySim CSV at data/paysim.csv
#    (https://www.kaggle.com/datasets/ealaxi/paysim1), OR generate a synthetic sample:
python -m pipeline.sample_paysim --rows 200000 --out data/paysim.csv

# 3. bring up the streaming spine (Redpanda + Console + Postgres)
docker compose -f infra/docker-compose.yml up -d        # Console → http://localhost:8080

# 4. train + freeze the XGBoost baseline
python -m pipeline.train_model                          # → models/fraud_xgb_v1.pkl

# 5. start the scorer (terminal A)
python -m pipeline.consumer

# 6. replay transactions through Kafka (terminal B)
python -m pipeline.producer --limit 5000 --rate 200

# 7. watch scored messages land:  Redpanda Console → Topics → scored-txns → Messages
```

A scored message carries the score, the thresholded flag, the model version, **and the
ground-truth label** (so downstream metrics can compute precision/recall/FPR):

```json
{
  "txn_id": "paysim-000000142",
  "fraud_score": 0.999984,
  "is_fraud_pred": 1,
  "label": 1,
  "model_version": "v1",
  "type": "TRANSFER",
  "amount": 54.28,
  "scored_at": "2026-06-21T10:38:24Z"
}
```

Run the tests (no broker or download needed — they use a synthetic sample):

```bash
python -m pytest pipeline/tests/ -q
```

---

## ⚡ Phase 2 — daily drift, trend & fairness

Once Phase 1 is running and `scored-txns` is producing events, layer in the
governance metrics:

```bash
# 1. sink scored events into Postgres for daily-batch querying
python -m pipeline.sink_postgres &

# 2. compute one day's metrics (PSI / CSI / health / trend) and write to Postgres
python -m pipeline.daily_drift --date 2026-06-21

# 3. fairness audit on the Bank Account Fraud Suite (separate runnable)
#    place the CSV at data/baf.csv first (public, never committed; see data.md)
python -m pipeline.baf_fairness --slice customer_age
```

Each daily metric row carries the **semantic band** (`stable`/`monitor`/`investigate`),
the **visual color** (`GREEN`/`AMBER`/`RED`), the **direction** of the score
shift (`high`/`low`/`mid`/`stable` — what the Phase 3 Drafter agent will route
on), and a **trend status** flagging a sustained PSI creep *before* it crosses
the RED threshold. The band-wise per-bin breakdown (expected % / actual % /
signed delta / contribution) lands in `psi_bins`, joined to `daily_metrics` by
foreign key, so the Phase 4 dashboard can render it directly.

The Phase 1 CLI is the primary entry point; an Airflow DAG
(`pipeline/dags/daily_drift_dag.py`) is checked in as a thin wrapper and can
be enabled with `docker compose --profile airflow up -d` (then
<http://localhost:8081>). See [`docs/runbooks/drift.md`](docs/runbooks/drift.md)
for the full schema, sample queries, and tuning knobs.

---

## ⚡ Phase 3 — agents, RAG & the human gate

The copilot turns a drift breach into a cited, human-gated memo. It runs fully
**offline** for demos/CI (deterministic composer + BM25 retrieval + JSONL
audit) — no API key or database required:

```bash
python -m agents.run \
  --breach-file agents/tests/fixtures/breach_red.json \
  --corpus-dir rag/tests/fixtures/governance \
  --offline \
  --decision approve --reviewer human:mrm@bank.example
```

The graph is **Monitor → Investigator → Drafter → Human gate**:

- **Monitor** reads the day's metrics + trend and decides which breaches are
  *material* (red always; amber only at/above a floor or on a rising trend).
- **Investigator** re-derives the shift **direction** straight from the
  band-wise PSI breakdown, relates it to the 0.85 decision threshold, and
  **RAG-retrieves** the governing policy — every hit carries a `doc:section`
  citation.
- **Drafter** writes the four-part memo — finding · business implication
  (cost type + rough size + stakeholder to route to) · policy basis *with
  citations* · recommended action — for a non-technical Risk/Legal reader.
- **Human gate** is a structural pause: the graph compiles with
  `interrupt_before=["human_gate"]`, so **nothing proceeds without an explicit
  approve/reject**. It never auto-approves.

The materiality/direction decisions are deterministic (a control system
shouldn't outsource "is this material?" to a stochastic model); the **LLM is
used where language matters — the Drafter — behind a thin router** (`anthropic`
/ `openai` / `offline`, swappable with one config change, keys from `.env`).
With `ANTHROPIC_API_KEY` set and the real corpus in `docs/governance/`, the
same command runs against Anthropic and Postgres unchanged. Every node's input,
output, citations, and the human decision are written to an **append-only audit
log** (`agent_runs` / `memos` / `decisions`, enforced by triggers). See
[`docs/runbooks/agents.md`](docs/runbooks/agents.md).

---

## 🧭 Design principles

These are enforced, not aspirational — see [`CLAUDE.md`](CLAUDE.md) for the full contract.

- **One feature module, train and serve.** `pipeline/features.py` is the single source of
  truth, imported by both training and scoring. Train/serve skew is *exactly* the failure
  Sentinel exists to catch — so the model that catches it must never commit it. A parity
  test asserts batch and single-record featurization agree byte-for-byte.
- **PSI read band-wise.** A middling aggregate PSI can hide a dangerous shift right at the
  decision boundary. Sentinel reads per-bin direction, not just the headline number.
- **Every agent output is a business implication.** Name the cost type, a rough size, and
  the stakeholder to route to — never a bare statistic.
- **Every decision cites its policy source** (`doc:section`) and writes to an **immutable
  audit log**, with the model version attached.
- **Nothing side-effecting happens without human approval.** The gate is not optional and
  not a checkbox an agent can flip.

---

## 📚 Governance corpus (for RAG)

| Document | Role |
| --- | --- |
| **SR 26-2** | Primary, current guidance (2026) |
| **SR 11-7** | Historical predecessor — cited explicitly as superseded |
| **EU AI Act** | High-risk obligations (full enforcement Aug 2026); fairness/bias angle |
| **NIST AI RMF** | Risk-management framework |
| *Synthetic model-validation report* | Clearly labeled synthetic |

---

## 🔒 Data policy

**Public datasets only.** Sentinel uses **PaySim** (the streaming spine), the **Bank
Account Fraud Suite** (NeurIPS 2022 — protected attributes for the fairness audit), and
optionally **IEEE-CIS**. **Real bank data is confidential and is never used in this
project.** `data/` and `models/` are gitignored; raw data and trained binaries are never
committed and must be re-derived from the documented public sources
(see [`docs/runbooks/data.md`](docs/runbooks/data.md)).

---

## 🗂️ Repository layout

```
pipeline/
  features.py        # SINGLE shared feature module (train & serve)
  train_model.py     # XGBoost baseline + frozen reference baseline snapshot
  producer.py        # PaySim -> transactions topic
  consumer.py        # transactions -> scored-txns (with label)
  scoring.py         # broker-free serving path + schema-drift guard
  drift.py           # PSI / CSI / banding / direction inference
  health.py          # precision / recall / FPR + per-slice fairness gaps
  baseline.py        # frozen reference distribution captured at training
  trend.py           # sustained-rise early warning
  sink_postgres.py   # scored-txns -> Postgres
  daily_drift.py     # daily governance metrics CLI
  baf_fairness.py    # BAF fairness audit (separate runnable)
  dags/              # Airflow DAGs (thin wrappers over the CLIs)
agents/
  llm.py             # thin Anthropic/OpenAI/offline router
  graph.py           # LangGraph Monitor->Investigator->Drafter->Human gate
  nodes.py           # node logic (materiality, direction, RAG, memo)
  audit.py           # append-only audit sink (Postgres + JSONL)
  prompts/           # one readable prompt per agent
rag/
  corpus.py          # chunk governance docs into stable doc:section ids
  retriever.py       # Haystack BM25 retrieval -> Citations
backend/     # FastAPI service, audit log, human-gate endpoints                 [Phase 4]
frontend/    # React dashboard                                                  [Phase 4]
infra/       # Docker Compose, Postgres init.sql, Cloud Run deploy
docs/        # research brief, ADRs, runbooks (data, drift), governance notes
data/        # gitignored — public datasets, locally derived
models/      # gitignored — trained artifacts + baseline sidecar, locally derived
```

---

## ⚠️ Honest scope and limits

Sentinel is a **prototype, not production**. On public/synthetic data the results are
**illustrative, not deployable** — e.g. the synthetic PaySim sample is deliberately clean
and will show an unrealistically high PR-AUC; real PaySim lands lower. LLM drafts are
RAG-grounded with citations to limit fabrication. Sentinel **assists** a human model-risk
manager — it never self-heals or acts autonomously.

---

## License

MIT — see [`LICENSE`](LICENSE). Canonical spec in [`CLAUDE.md`](CLAUDE.md); positioning
brief in [`docs/research/Sentinel_Scoping_Brief.md`](docs/research/Sentinel_Scoping_Brief.md).
