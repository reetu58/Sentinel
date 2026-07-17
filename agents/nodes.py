"""The four agent nodes.

Design choice (deliberate, and a feature not a shortcut): the **decision logic**
in Monitor and Investigator is deterministic — materiality is a governance
threshold, and drift direction is read straight from the band-wise breakdown
(`drift.direction_from_deltas`). A control system shouldn't outsource "is this
breach material?" or "which way did the score move?" to a stochastic model. The
**LLM is used where language matters** — the Drafter — behind the thin router,
so the same graph runs offline (deterministic composer) or against Anthropic /
OpenAI with one config change.

Every node appends its input + output (and any citations) to the immutable
audit log before returning.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pipeline.drift import direction_from_deltas

from . import config
from .audit import AuditSink
from .llm import LLMRouter
from .prompts import load_prompt

# Routing table from CLAUDE.md, keyed by shift direction.
ROUTING: dict[str, dict[str, str]] = {
    "high": {
        "mechanism": "the model is over-flagging",
        "cost_type": "false declines (lost revenue, friction, investigation load)",
        "route_to": "Product / Sales / CX",
    },
    "low": {
        "mechanism": "the model is under-detecting",
        "cost_type": "fraud losses + regulatory exposure",
        "route_to": "Risk / Finance / Legal",
    },
    "mid": {
        "mechanism": "instability at the decision boundary",
        "cost_type": "decision instability",
        "route_to": "Ops / Finance planning",
    },
    "stable": {
        "mechanism": "no material shift",
        "cost_type": "none",
        "route_to": "n/a",
    },
}

DECISION_THRESHOLD = 0.85


def _next_seq(state) -> int:
    return int(state.get("seq", 0)) + 1


# --- Monitor ------------------------------------------------------------


def make_monitor(sink: AuditSink) -> Callable:
    def monitor(state) -> dict[str, Any]:
        metrics = state["metrics"]
        score = metrics["score_psi"]
        trend = metrics.get("trend", {})
        band = score["band"]
        value = float(score["value"])
        trend_rising = trend.get("status") == "rising"

        if band == "investigate":
            material = True
            why = f"score PSI {value:.4f} is in the RED (investigate) band"
        elif band == "monitor" and (value >= config.MATERIAL_AMBER_MIN or trend_rising):
            material = True
            why = (
                f"score PSI {value:.4f} is AMBER and "
                + ("the trend is rising (early warning)" if trend_rising
                   else f"at/above the materiality floor ({config.MATERIAL_AMBER_MIN})")
            )
        else:
            material = False
            why = f"score PSI {value:.4f} ({band}) with trend {trend.get('status','flat')} — not material"

        objective = (
            "Confirm the direction of the score shift from the band-wise breakdown, "
            f"check it against the {DECISION_THRESHOLD} decision threshold, and "
            "retrieve the monitoring/threshold policy governing a breach of this "
            "magnitude and direction."
            if material
            else "No investigation required."
        )
        summary = (
            f"Material breach: {score['color']} score PSI {value:.4f} "
            f"(direction={score.get('direction','?')}). {why}."
            if material
            else f"No material breach. {why}."
        )

        out = {
            "material": material,
            "breach_summary": summary,
            "monitor_objective": objective,
        }
        seq = _next_seq(state)
        sink.record_agent_run(
            run_id=state["run_id"], node="monitor", seq=seq,
            model_version=state.get("model_version"), run_date=state.get("run_date"),
            input={"score_psi": score, "trend": trend,
                   "materiality_floor": config.MATERIAL_AMBER_MIN},
            output=out, citations=[],
        )
        sink.log(actor="monitor_agent", action="assess_materiality",
                 target=f"daily_metrics:{state.get('run_date')}/{state.get('model_version')}",
                 citation="SR_26-2:III.C", payload={"material": material, "why": why})
        return {**out, "seq": seq}

    return monitor


# --- Investigator -------------------------------------------------------


def make_investigator(sink: AuditSink, retriever) -> Callable:
    def investigator(state) -> dict[str, Any]:
        metrics = state["metrics"]
        score = metrics["score_psi"]
        bins = score.get("bins", [])
        signed_deltas = [b["signed_delta"] for b in bins]

        # Re-derive direction straight from the band-wise breakdown.
        direction = direction_from_deltas(signed_deltas, score["band"])
        route = ROUTING.get(direction, ROUTING["mid"])

        threshold_note = {
            "high": f"A high-side shift pushes more transactions over the "
                    f"{DECISION_THRESHOLD} threshold — more declines.",
            "low": f"A low-side shift pulls true frauds below the "
                   f"{DECISION_THRESHOLD} threshold — missed fraud.",
            "mid": f"Mass is churning around the {DECISION_THRESHOLD} operating "
                   "point — unstable decisions.",
        }.get(direction, "Direction inconclusive.")

        # RAG: retrieve the governing policy for this breach.
        query = (
            f"score distribution {direction}-side shift {route['mechanism']} "
            f"population stability index decision threshold ongoing monitoring "
            f"escalation thresholds"
        )
        hits = retriever.retrieve(query, top_k=4)
        citations = [
            {
                "citation": h.citation,
                "doc_id": h.doc_id,
                "doc_title": h.doc_title,
                "section_id": h.section_id,
                "section_title": h.section_title,
                "note": f"Relevant to {direction}-side drift handling.",
                "score": round(h.score, 4),
            }
            for h in hits
        ]

        out = {
            "direction": direction,
            "mechanism": route["mechanism"],
            "threshold_note": threshold_note,
            "citations": citations,
        }
        seq = _next_seq(state)
        sink.record_agent_run(
            run_id=state["run_id"], node="investigator", seq=seq,
            model_version=state.get("model_version"), run_date=state.get("run_date"),
            input={"band_wise_breakdown": bins, "objective": state.get("monitor_objective")},
            output={k: v for k, v in out.items() if k != "citations"},
            citations=citations,
        )
        sink.log(actor="investigator_agent", action="determine_direction_and_retrieve",
                 target=f"daily_metrics:{state.get('run_date')}/{state.get('model_version')}",
                 citation=";".join(c["citation"] for c in citations) or None,
                 payload={"direction": direction, "mechanism": route["mechanism"]})
        return {**out, "seq": seq}

    return investigator


# --- Drafter ------------------------------------------------------------


def _rough_size(direction: str, metrics: dict) -> str:
    health = metrics.get("health", {})
    n = int(health.get("n", 0))
    fpr = float(health.get("fpr", 0.0))
    if direction == "high":
        return (
            f"On ~{n:,} scored transactions/day at FPR {fpr:.3f}, a high-side shift "
            "increases false declines. Size with Finance as: incremental declines × "
            "(avg basket value + handling cost)."
        )
    if direction == "low":
        return (
            f"On ~{n:,} scored transactions/day, a low-side shift lets more true "
            "fraud through. Size with Finance/Risk as: missed-fraud count × avg "
            "fraud loss, plus regulatory exposure."
        )
    return (
        f"On ~{n:,} scored transactions/day, decisions near the threshold are "
        "unstable. Size with Ops as forecast variance in daily alert volume."
    )


def make_drafter(sink: AuditSink, router: LLMRouter) -> Callable:
    system = load_prompt("drafter")

    def drafter(state) -> dict[str, Any]:
        import json

        metrics = state["metrics"]
        score = metrics["score_psi"]
        direction = state["direction"]
        route = ROUTING.get(direction, ROUTING["mid"])
        citations = state.get("citations", [])

        # Locate where the shift concentrated, for the band-wise note.
        bins = score.get("bins", [])
        if bins:
            top_bin = max(bins, key=lambda b: b["signed_delta"])
            band_wise_note = (
                f"the largest mass gain is in bin {top_bin['label']} "
                f"({top_bin['signed_delta']*100:+.1f} pts)"
            )
        else:
            band_wise_note = "shift concentrated away from the stable bins"

        rough = _rough_size(direction, metrics)
        recommended = (
            f"Review the {DECISION_THRESHOLD} decision threshold against the shifted "
            f"distribution and convene model risk management with {route['route_to']}. "
            "This is a recommendation pending human approval — Sentinel takes no "
            "action itself."
        )

        # Deterministic four-part fields (reliable regardless of provider).
        finding = (
            f"The model's score distribution has shifted "
            f"{_dir_phrase(direction)}. PSI = {float(score['value']):.4f} "
            f"({score['band']} / {score['color']}), read band-wise: {band_wise_note}."
        )
        business = (
            f"Mechanism: {route['mechanism']}. Cost type: {route['cost_type']}. "
            f"Rough size: {rough} Route to: {route['route_to']}."
        )
        cite_inline = ", ".join(c["citation"] for c in citations) or "(none retrieved)"
        policy = (
            "Grounded in: "
            + "; ".join(f"[{c['citation']}] {c['section_title']}" for c in citations)
            + f". Citations: {cite_inline}."
        ) if citations else "No governing policy retrieved."

        # Build the facts block the router (and offline composer) renders from.
        facts = {
            "metric_label": "score PSI",
            "psi_value": round(float(score["value"]), 4),
            "band": score["band"],
            "color": score["color"],
            "direction": direction,
            "mechanism": route["mechanism"],
            "cost_type": route["cost_type"],
            "route_to": route["route_to"],
            "rough_size": rough,
            "band_wise_note": band_wise_note,
            "recommended_action": recommended,
            "finding_subject": "score distribution",
            "citations": citations,
        }
        user = (
            "Draft the four-part alert memo. Use ONLY these facts; do not invent "
            "numbers or citations.\n\n"
            f"<facts>{json.dumps(facts)}</facts>"
        )
        resp = router.complete(system, user)

        memo = {
            "run_date": state.get("run_date"),
            "model_version": state.get("model_version"),
            "metric_label": "score PSI",
            "color": score["color"],
            "direction": direction,
            "finding": finding,
            "business_implication": business,
            "policy_basis": policy,
            "recommended_action": recommended,
            "citations": citations,
            "full_text": resp.text,
            "status": "pending_approval",
            "llm_provider": resp.provider,
            "llm_model": resp.model,
        }
        memo_id = sink.record_memo(run_id=state["run_id"], memo=memo)
        memo["id"] = memo_id

        seq = _next_seq(state)
        sink.record_agent_run(
            run_id=state["run_id"], node="drafter", seq=seq,
            model_version=state.get("model_version"), run_date=state.get("run_date"),
            input={"facts": facts}, output={"memo_id": memo_id, "provider": resp.provider},
            citations=citations,
        )
        sink.log(actor="drafter_agent", action="draft_memo",
                 target=f"memo:{memo_id}",
                 citation=";".join(c["citation"] for c in citations) or None,
                 payload={"provider": resp.provider, "model": resp.model})
        return {"memo": memo, "seq": seq, "status": "pending_approval"}

    return drafter


def _dir_phrase(direction: str) -> str:
    return {
        "high": "toward the high (over-flagging) end of the score range",
        "low": "toward the low (under-detection) end of the score range",
        "mid": "around the decision threshold (instability at the operating point)",
        "stable": "only marginally",
    }.get(direction, "in a non-stable direction")


# --- Human gate ---------------------------------------------------------


def make_human_gate(sink: AuditSink) -> Callable:
    def human_gate(state) -> dict[str, Any]:
        """Records the human decision. The graph PAUSES *before* this node
        (interrupt_before=['human_gate']); it only runs once a reviewer's
        decision has been injected on resume. It never auto-approves."""
        decision = state.get("human_decision")
        memo = state.get("memo", {})
        if not decision:
            # Defensive: should not run without a decision. Leave pending.
            return {"status": "pending_approval"}

        verdict = decision["decision"]  # 'approved' | 'rejected'
        sink.record_decision(
            run_id=state["run_id"], memo_id=memo.get("id"),
            decision=verdict, reviewer=decision.get("reviewer", "human:unknown"),
            note=decision.get("note"),
        )
        sink.log(actor=decision.get("reviewer", "human:unknown"),
                 action=verdict, target=f"memo:{memo.get('id')}",
                 citation="SR_26-2:VII", payload={"note": decision.get("note")})
        return {"status": verdict}

    return human_gate
