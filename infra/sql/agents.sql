-- Sentinel Phase 3 schema: agent runs, drafted memos, and decisions.
--
-- Applied after init.sql (which already defines the append-only `audit_log`
-- and its no-UPDATE/no-DELETE triggers). Idempotent — every CREATE uses
-- IF NOT EXISTS. The Phase 4 dashboard reads `memos` + `audit_log`.
--
-- This is the SR 26-2 carve-out control, not logging-as-afterthought:
--   * agent_runs   one append-only row per graph node (input, output, cites)
--   * memos        the drafted alert; status is set once at insert and never
--                  updated — the human decision is a SEPARATE append row
--   * decisions    append-only approve/reject records (the human gate)
-- Append-only is enforced by triggers, mirroring audit_log.

CREATE TABLE IF NOT EXISTS agent_runs (
    id              BIGSERIAL PRIMARY KEY,
    run_id          UUID NOT NULL,            -- one graph invocation
    node            TEXT NOT NULL,            -- 'monitor' | 'investigator' | 'drafter' | 'human_gate'
    seq             INTEGER NOT NULL,         -- order within the run
    model_version   TEXT,
    run_date        DATE,
    input           JSONB NOT NULL DEFAULT '{}'::jsonb,
    output          JSONB NOT NULL DEFAULT '{}'::jsonb,
    citations       JSONB NOT NULL DEFAULT '[]'::jsonb,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_runs_run_idx ON agent_runs (run_id, seq);


CREATE TABLE IF NOT EXISTS memos (
    id              UUID PRIMARY KEY,
    run_id          UUID NOT NULL,
    run_date        DATE,
    model_version   TEXT,
    metric_label    TEXT,                     -- e.g. 'psi_score'
    color           TEXT,                     -- GREEN | AMBER | RED
    direction       TEXT,                     -- high | low | mid | stable
    finding         TEXT NOT NULL,
    business_implication TEXT NOT NULL,
    policy_basis    TEXT NOT NULL,
    recommended_action  TEXT NOT NULL,
    citations       JSONB NOT NULL DEFAULT '[]'::jsonb,
    full_text       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending_approval',  -- set once, never updated
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS memos_run_idx ON memos (run_id);


CREATE TABLE IF NOT EXISTS decisions (
    id              BIGSERIAL PRIMARY KEY,
    memo_id         UUID NOT NULL REFERENCES memos(id),
    run_id          UUID NOT NULL,
    decision        TEXT NOT NULL,            -- 'approved' | 'rejected'
    reviewer        TEXT NOT NULL,            -- 'human:<email>'
    note            TEXT,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS decisions_memo_idx ON decisions (memo_id, ts DESC);


-- Append-only enforcement (reuse the function defined in init.sql if present,
-- else define an equivalent here so this file is self-sufficient).
CREATE OR REPLACE FUNCTION sentinel_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only (% blocked)', TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS agent_runs_no_update ON agent_runs;
CREATE TRIGGER agent_runs_no_update BEFORE UPDATE OR DELETE ON agent_runs
    FOR EACH ROW EXECUTE FUNCTION sentinel_append_only();

DROP TRIGGER IF EXISTS memos_no_update ON memos;
CREATE TRIGGER memos_no_update BEFORE UPDATE OR DELETE ON memos
    FOR EACH ROW EXECUTE FUNCTION sentinel_append_only();

DROP TRIGGER IF EXISTS decisions_no_update ON decisions;
CREATE TRIGGER decisions_no_update BEFORE UPDATE OR DELETE ON decisions
    FOR EACH ROW EXECUTE FUNCTION sentinel_append_only();
