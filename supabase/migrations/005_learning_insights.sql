-- Migration: 005_learning_insights.sql
-- Purpose: Self-learning engine output table.
--          Stores weekly win-rate analysis and scanner threshold recommendations.
-- Rollback: DROP TABLE IF EXISTS learning_insights;

CREATE TABLE IF NOT EXISTS learning_insights (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT        NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    trade_count     INTEGER     NOT NULL DEFAULT 0,
    win_count       INTEGER     NOT NULL DEFAULT 0,
    overall_win_rate NUMERIC(5,4) NOT NULL DEFAULT 0,

    -- JSONB breakdowns: { "NVDA": 0.72, "SPY": 0.50, ... }
    win_rate_by_symbol      JSONB NOT NULL DEFAULT '{}',
    win_rate_by_option_type JSONB NOT NULL DEFAULT '{}',
    win_rate_by_day         JSONB NOT NULL DEFAULT '{}',
    win_rate_by_score_bucket JSONB NOT NULL DEFAULT '{}',

    -- Scanner threshold recommended for next week
    recommended_threshold NUMERIC(4,1) NOT NULL DEFAULT 7.0,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for time-series queries (latest insight per user)
CREATE INDEX IF NOT EXISTS idx_learning_insights_user_computed
    ON learning_insights (user_id, computed_at DESC);

-- RLS: users can read only their own insights; service role writes
ALTER TABLE learning_insights ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users_read_own_insights"
    ON learning_insights
    FOR SELECT
    USING (auth.uid()::text = user_id);

-- Service role bypasses RLS (enforced by Supabase when using service key)
