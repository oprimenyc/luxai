-- =============================================================================
-- Migration 004: Workbench Analyses Audit Log
-- =============================================================================
-- Table: workbench_analyses
--   Stores every Trade Idea Workbench analysis result for a user.
--   Provides a historical record for learning, pattern review, and
--   future AI recommendations.
--
-- RLS: users read and insert their own rows only. Updates/deletes not allowed.
--
-- Rollback:
--   DROP TABLE IF EXISTS workbench_analyses CASCADE;
-- =============================================================================

CREATE TABLE IF NOT EXISTS workbench_analyses (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Input parameters
    symbol              TEXT NOT NULL,
    direction           TEXT NOT NULL CHECK (direction IN ('bullish', 'bearish')),
    expiration          DATE NOT NULL,
    budget_usd          NUMERIC(10, 2) NOT NULL,
    account_size_usd    NUMERIC(12, 2) NOT NULL,
    account_tier        TEXT NOT NULL CHECK (account_tier IN ('tiny', 'growth', 'aggressive')),
    source              TEXT,                          -- where the tip came from (optional)

    -- Market context
    underlying_price    NUMERIC(10, 4),

    -- Best Value recommendation (summary — full payload in result_payload)
    best_value_score    NUMERIC(4, 1),
    best_value_symbol   TEXT,                          -- OCC option symbol
    best_value_strike   NUMERIC(10, 2),
    best_value_cost_usd NUMERIC(10, 2),
    best_value_dte      INTEGER,

    -- Spread recommendation
    spread_net_debit    NUMERIC(10, 2),

    -- Macro context
    macro_event_count   INTEGER NOT NULL DEFAULT 0,
    earnings_warning    BOOLEAN NOT NULL DEFAULT FALSE,

    -- Verdict
    verdict             TEXT NOT NULL CHECK (verdict IN ('accept', 'caution', 'reject')),
    verdict_rationale   TEXT,

    -- Full JSON payload (for complete replay / learning)
    result_payload      JSONB NOT NULL DEFAULT '{}'::JSONB,

    -- Timing
    analyzed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS workbench_analyses_user_id_idx
    ON workbench_analyses(user_id);

CREATE INDEX IF NOT EXISTS workbench_analyses_symbol_idx
    ON workbench_analyses(symbol);

CREATE INDEX IF NOT EXISTS workbench_analyses_analyzed_at_idx
    ON workbench_analyses(analyzed_at DESC);

CREATE INDEX IF NOT EXISTS workbench_analyses_verdict_idx
    ON workbench_analyses(user_id, verdict);

-- Row Level Security
ALTER TABLE workbench_analyses ENABLE ROW LEVEL SECURITY;

-- Users may read their own analyses
CREATE POLICY "workbench_analyses_select_own"
    ON workbench_analyses FOR SELECT
    USING (auth.uid() = user_id);

-- Users may insert their own analyses (workbench writes on analyze call)
CREATE POLICY "workbench_analyses_insert_own"
    ON workbench_analyses FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- No updates or deletes — analyses are immutable audit records
CREATE POLICY "workbench_analyses_no_update"
    ON workbench_analyses FOR UPDATE
    USING (FALSE);

CREATE POLICY "workbench_analyses_no_delete"
    ON workbench_analyses FOR DELETE
    USING (FALSE);
