# Backend + dashboard runbook (Phase 4)

The human-in-the-loop made usable: a FastAPI backend over the Phase 2 metrics
and the Phase 3 agent graph, and a React dashboard that drives the full loop.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/health` | current daily PSI band + **band-wise bins**, CSI, FPR, fairness gaps, trend |
| GET  | `/api/investigations` | the alert / investigation queue |
| POST | `/api/investigations` | trigger the agent graph on the current breach |
| GET  | `/api/investigations/{run_id}` | one investigation (memo + status + agent runs) |
| POST | `/api/investigations/{run_id}/approve` | resume the paused graph; append decision to audit |
| POST | `/api/investigations/{run_id}/reject` | resume the paused graph; append decision to audit |
| GET  | `/api/audit` | the immutable audit log |
| GET  | `/api/status` | mode (postgres/demo) + active LLM provider |

All state is server-side: metrics in Postgres, the paused graph in a SQLite
checkpointer, the record in the append-only audit log. The dashboard holds no
durable client state and uses **no** localStorage/sessionStorage.

## Modes

`SENTINEL_BACKEND_MODE`:
- `auto` (default) — use Postgres if reachable, else fall back to `demo`.
- `postgres` — read metrics/queue/audit from the Phase 2/3 tables.
- `demo` — run the whole loop from bundled fixtures + the synthetic governance
  corpus + a JSONL audit log. No database or API key required.

## Run it (demo mode — no DB, no API key)

Terminal 1 — backend:
```bash
pip install -r pipeline/requirements.txt -r backend/requirements.txt
SENTINEL_BACKEND_MODE=demo python -m uvicorn backend.app:app --port 8000
```

Terminal 2 — dashboard:
```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 (proxies /api -> :8000)
```

## Walk the loop in the browser

1. The header shows a **RED breach** banner; the tiles show the PSI band, FPR,
   trend (RISING), and the worst fairness gap.
2. The **band-wise PSI chart** shows expected vs actual mass per score bin —
   green where the distribution gained mass, red where it lost it. (A single
   PSI number can't show this; the per-bin view is the differentiator.)
3. Click **Trigger investigation on current breach**. The agent graph runs
   Monitor → Investigator → Drafter and **pauses at the human gate**.
4. The copilot panel renders the four-part memo: finding (band direction),
   business implication (cost type + rough size + stakeholder to route to),
   policy basis **with citations**, recommended action.
5. Enter a reviewer, optionally **Edit** a note, then **Approve** (or Reject).
   This resumes the paused graph and appends the decision to the audit log.
6. The **audit trail** updates with the human decision (highlighted), below the
   agent runs that preceded it.

## Run it against Postgres + a real LLM

Bring up Phase 1/2 infra and populate metrics (see `docs/runbooks/drift.md`),
put the real corpus in `docs/governance/`, set `ANTHROPIC_API_KEY` in `.env`,
then:
```bash
SENTINEL_BACKEND_MODE=postgres python -m uvicorn backend.app:app --port 8000
```
The dashboard and the loop are identical; the memo prose comes from the model.

## Notes

- The trigger endpoint runs the graph synchronously (FastAPI threadpool) — fine
  for a prototype; a production build would enqueue it.
- The SQLite checkpointer (`models/agent_checkpoints.sqlite`, gitignored) is
  what lets Approve/Reject — a *separate* request from Trigger — resume the
  exact paused graph.
