# Sentinel — 3-minute demo script

A tight walkthrough of the full human-in-the-loop: a drift event fires, the
agents investigate and draft a **cited** memo, the business implication and
stakeholder routing are shown, a human approves, and the immutable audit log
updates. Timings are a guide for a live demo or a screen recording.

**Setup (before you start):**
```bash
# backend (demo mode — no DB, no API key)
SENTINEL_BACKEND_MODE=demo python -m uvicorn backend.app:app --port 8000
# dashboard
cd frontend && npm install && npm run dev      # http://localhost:5173
```
Or just open the live Cloud Run URL.

---

## 0:00 — The stakes (20s)

> "This is Sentinel. It watches a deployed fraud-scoring model. When that model
> silently drifts, it costs money in one of two directions — either it starts
> **over-blocking good customers** (false declines: lost revenue and friction)
> or it **misses fraud** (direct losses plus regulatory exposure). Catching that
> early, and turning it into a decision, is slow manual work today."

Point at the header: a **RED breach** banner is already showing.

## 0:20 — Model health, read band-wise (35s)

> "Today the model tripped a red flag. Score PSI is 0.47 — well past the 0.25
> investigate threshold — and the trend is **rising**, so this has been building."

Point at the **health tiles**: PSI band (RED), FPR, trend (RISING), worst
fairness gap.

> "But a single PSI number hides *where* the distribution moved. This is the
> band-wise view —"

Point at the **band-wise PSI chart**.

> "— green bars are score bins that *gained* mass, red *lost* it. The mass has
> piled up at the high end. The model is scoring more transactions as fraud.
> That's a **high-side** shift — over-flagging."

## 0:55 — Trigger the investigation (25s)

Click **Trigger investigation on current breach**.

> "That kicks off a LangGraph agent graph: a Monitor decides the breach is
> material, an Investigator confirms the direction from the band-wise data and
> retrieves the governing policy, and a Drafter writes the memo. It then
> **stops** — and waits for a human."

The copilot panel fills in; status shows **awaiting approval**.

## 1:20 — The cited memo (50s)

Walk the four parts in the copilot panel:

> "**(a) Finding** — plain English: the score distribution shifted to the
> high, over-flagging end; PSI 0.47, RED, read band-wise.
>
> **(b) Business implication** — and this is the point: it names the **cost
> type** (false declines), a **rough size** tied to daily volume, and the
> **stakeholder to route to** — Product / Sales / CX, because this is a customer-
> friction problem, not a fraud-loss problem.
>
> **(c) Policy basis** — every claim is **cited**: SR&nbsp;26-2 III.B on
> population stability and thresholds, the model-validation report's threshold
> section. These aren't invented — they're retrieved from the governance corpus.
>
> **(d) Recommended action** — review the 0.85 threshold, convene model risk
> with the routed team. A recommendation, not an action."

## 2:10 — The human gate (30s)

> "Nothing has happened yet. This is the control the new guidance demands for
> agentic systems — the agent **proposes**, a human **disposes**."

Enter a reviewer, optionally click **Edit** to add a note, then click
**Approve**.

> "Approve resumes the paused graph and records the decision."

Status flips to **approved**.

## 2:40 — The audit trail (20s)

Point at the **audit trail** at the bottom.

> "And here's the whole chain, append-only: the Monitor's materiality call, the
> Investigator's retrieval with its citations, the Drafter's memo, and — 
> highlighted — the human approval, with who and when. That immutable record is
> the third carve-out control. Every step is attributable."

## 3:00 — Close (10s)

> "Traditional model monitoring on one side, agentic-governance controls —
> scoped actions, human approval, immutable audit — on the other. That's the
> fault line SR&nbsp;26-2 created, and that's what Sentinel is built on."

---

### One-liner (if you have 20 seconds, not 3 minutes)

> "Sentinel watches a fraud model for drift, and when it finds some, an agent
> drafts a **cited, regulator-style memo** that names the business cost and the
> team to route to — then **waits for a human to approve** before anything
> happens, logging every step to an immutable audit trail."
