-- Sentinel Phase 2 schema: metrics, baselines, audit log.
--
-- This script is mounted into the Postgres container at first start (see
-- infra/docker-compose.yml). It is idempotent — every CREATE uses IF NOT
-- EXISTS, so re-applying it on an existing DB is a no-op.
--
-- The Phase 3 agents and the Phase 4 dashboard read from these tables:
--   scored_transactions  raw stream sinked from the scored-txns topic
--   model_baselines      frozen reference distribution per model_version
--   daily_metrics        one row per (run_date, model_version, metric)
--   psi_bins             band-wise per-bin breakdown for each PSI/CSI metric
--   fairness_metrics     group-wise FPR / approval-rate per slice
--   audit_log            immutable, append-only — Phase 3 agents write here
--
-- Conventions:
--   - All timestamps are TIMESTAMPTZ.
--   - "payload" is jsonb for anything an agent might want to read.
--   - Every metrics row carries both the semantic band and the visual color.

CREATE TABLE IF NOT EXISTS scored_transactions (
    id              BIGSERIAL PRIMARY KEY,
    txn_id          TEXT NOT NULL,
    fraud_score     DOUBLE PRECISION NOT NULL,
    is_fraud_pred   INTEGER NOT NULL,
    label           INTEGER,
    model_version   TEXT NOT NULL,
    type            TEXT,
    amount          DOUBLE PRECISION,
    scored_at       TIMESTAMPTZ NOT NULL,
    CONSTRAINT scored_transactions_unique UNIQUE (txn_id, model_version)
);
CREATE INDEX IF NOT EXISTS scored_transactions_date_idx
    ON scored_transactions ((scored_at::date), model_version);


CREATE TABLE IF NOT EXISTS model_baselines (
    model_version   TEXT PRIMARY KEY,
    captured_at     TIMESTAMPTZ NOT NULL,
    n_train         INTEGER NOT NULL,
    snapshot        JSONB NOT NULL
);


CREATE TABLE IF NOT EXISTS daily_metrics (
    id              BIGSERIAL PRIMARY KEY,
    run_date        DATE NOT NULL,
    model_version   TEXT NOT NULL,
    metric_kind     TEXT NOT NULL,        -- 'psi_score' | 'csi_feature' | 'health' | 'trend'
    metric_name     TEXT NOT NULL,        -- feature name for csi_feature, else kind
    value           DOUBLE PRECISION,     -- aggregate (PSI/CSI/precision/...)
    band            TEXT,                 -- 'stable' | 'monitor' | 'investigate' | NULL
    color           TEXT,                 -- 'GREEN' | 'AMBER' | 'RED' | NULL
    direction       TEXT,                 -- 'low'|'mid'|'high'|'stable' for PSI score
    trend_status    TEXT,                 -- 'rising'|'flat' for trend rows
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT daily_metrics_unique UNIQUE (run_date, model_version, metric_kind, metric_name)
);
CREATE INDEX IF NOT EXISTS daily_metrics_date_idx
    ON daily_metrics (run_date DESC, model_version);
CREATE INDEX IF NOT EXISTS daily_metrics_kind_idx
    ON daily_metrics (metric_kind, metric_name, run_date DESC);


-- Band-wise per-bin breakdown for each PSI/CSI row in daily_metrics. Stored
-- in its own table (rather than just jsonb) so the dashboard can join /
-- filter on individual bins.
CREATE TABLE IF NOT EXISTS psi_bins (
    id              BIGSERIAL PRIMARY KEY,
    daily_metric_id BIGINT NOT NULL REFERENCES daily_metrics(id) ON DELETE CASCADE,
    bin_index       INTEGER NOT NULL,
    bin_label       TEXT NOT NULL,
    expected_pct    DOUBLE PRECISION NOT NULL,
    actual_pct      DOUBLE PRECISION NOT NULL,
    signed_delta    DOUBLE PRECISION NOT NULL,
    contribution    DOUBLE PRECISION NOT NULL,
    CONSTRAINT psi_bins_unique UNIQUE (daily_metric_id, bin_index)
);


CREATE TABLE IF NOT EXISTS fairness_metrics (
    id              BIGSERIAL PRIMARY KEY,
    run_date        DATE NOT NULL,
    dataset         TEXT NOT NULL,        -- 'baf' | 'paysim' | ...
    model_version   TEXT NOT NULL,
    slice_column    TEXT NOT NULL,        -- the protected attribute
    slice_value     TEXT NOT NULL,        -- 'group_A', '<30', etc.
    n               INTEGER NOT NULL,
    positives       INTEGER NOT NULL,
    fpr             DOUBLE PRECISION NOT NULL,
    approval_rate   DOUBLE PRECISION NOT NULL,
    precision       DOUBLE PRECISION,
    recall          DOUBLE PRECISION,
    f1              DOUBLE PRECISION,
    is_reference    BOOLEAN NOT NULL DEFAULT false, -- the overall / reference slice
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fairness_metrics_unique
        UNIQUE (run_date, dataset, model_version, slice_column, slice_value)
);
CREATE INDEX IF NOT EXISTS fairness_metrics_date_idx
    ON fairness_metrics (run_date DESC, dataset, slice_column);


-- Immutable, append-only. The Phase 3 agents will write here on every
-- decision; the Phase 4 dashboard reads it. No UPDATE / DELETE — enforced
-- by a trigger because PostgreSQL has no first-class append-only constraint.
CREATE TABLE IF NOT EXISTS audit_log (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor           TEXT NOT NULL,        -- 'daily_drift_job' | 'monitor_agent' | 'human:<email>' | ...
    action          TEXT NOT NULL,        -- 'compute_metrics' | 'draft_memo' | 'approve' | ...
    target          TEXT NOT NULL,        -- 'daily_metrics:<id>' | 'memo:<id>' | ...
    citation        TEXT,                 -- e.g. 'SR_26-2:III.B' for Phase 3 agents
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS audit_log_ts_idx ON audit_log (ts DESC);

CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only (% on id=%)', TG_OP, OLD.id;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log;
CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log;
CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
