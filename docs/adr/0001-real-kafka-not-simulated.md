# ADR 0001 — Use real Kafka, not a simulated stream

- **Status:** Accepted
- **Date:** 2026-06-21
- **Context source:** `docs/research/Sentinel_Scoping_Brief.md` (re-scoping note)

## Context

An earlier scoping draft recommended simulating the transaction stream with a
Python loop and treating Kafka and live deployment as future work. The current
brief explicitly **re-scopes** that: the target roles screen on hands-on Kafka,
Airflow, and live deployment, so the thin-but-real versions are built, not
deferred.

## Decision

The streaming layer is **real Kafka (Redpanda locally)**, with IEEE-CIS
replayed through it as a live stream. Orchestration is a **real daily Airflow
DAG**. The system is **deployed live** (Docker → GCP Cloud Run, public URL).

These are deliberately **thin but real** — minimal topics, a single DAG, a small
Cloud Run service — rather than simulated stand-ins.

## Consequences

- More upfront infra work than a Python loop, but it is the part the project is
  meant to demonstrate.
- "Thin but real" is the guardrail: resist both over-engineering the infra and
  quietly reverting to a simulated loop under time pressure.
- If a future change proposes faking the stream "just to move faster," it
  contradicts this ADR and needs an explicit superseding decision.
