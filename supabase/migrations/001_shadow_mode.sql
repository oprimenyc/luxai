-- =============================================================================
-- Migration 001: Shadow Mode Tables
-- =============================================================================
-- Tables:
--   shadow_mode_config  — per-user shadow mode state (active/inactive)
--   shadow_trades       — every intercepted order logged here
--   shadow_pnl          — aggregated shadow P&L per user
--
-- RLS: enforced on all three tables. Users see only their own rows.
--      Service role bypasses RLS for admin operations.
--
-- Rollback:
--   DROP TABLE IF EXISTS shadow_pnl CASCADE;
--   DROP TABLE IF EXISTS shadow_trades CASCADE;
--   DROP TABLE IF EXISTS shadow_mode_config CASCADE;
-- =============================================================================


-- ── shadow_mode_config ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS shadow_mode_config (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    activated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_by    TEXT NOT NULL DEFAULT 'system_default',
    deactivated_at  TIMESTAMPTZ,
    deactivated_by  TEXT,
    -- Gate fields: filled in by admin after 2-week shadow audit
    gate_passed_at  TIMESTAMPTZ,
    gate_notes      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS shadow_mode_config_user_id_idx ON shadow_mode_config(user_id);
CREATE INDEX IF NOT EXISTS shadow_mode_config_is_active_idx ON shadow_mode_config(is_active);

ALTER TABLE shadow_mode_config ENABLE ROW LEVEL SECURITY;

-- Users may read their own config
CREATE POLICY "shadow_config_select_own"
    ON shadow_mode_config FOR SELECT
    USING (auth.uid() = user_id);

-- Users cannot modify their own config — all writes via service role
CREATE POLICY "shadow_config_no_user_write"
    ON shadow_mode_config FOR ALL
    USING (FALSE)
    WITH CHECK (FALSE);

-- Trigger: keep updated_at fresh
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER shadow_mode_config_updated_at
    BEFORE UPDATE ON shadow_mode_config
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();


-- ── shadow_trades ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS shadow_trades (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    symbol                      TEXT NOT NULL,
    side                        TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    qty                         INTEGER NOT NULL CHECK (qty > 0),
    order_type                  TEXT NOT NULL,
    -- Entry data (recorded at interception time)
    intended_entry_price        NUMERIC(12, 4) NOT NULL,
    intended_idempotency_key    TEXT NOT NULL,
    -- Exit data (recorded when the trade signal would have closed)
    intended_exit_price         NUMERIC(12, 4),
    shadow_pnl_usd              NUMERIC(12, 4),
    shadow_pnl_pct              NUMERIC(8, 4),
    -- Lifecycle
    status                      TEXT NOT NULL DEFAULT 'open'
                                    CHECK (status IN ('open', 'closed', 'expired', 'cancelled')),
    intercepted_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at                   TIMESTAMPTZ,
    -- Free-form context
    metadata                    JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS shadow_trades_user_id_idx ON shadow_trades(user_id);
CREATE INDEX IF NOT EXISTS shadow_trades_symbol_idx ON shadow_trades(symbol);
CREATE INDEX IF NOT EXISTS shadow_trades_intercepted_at_idx ON shadow_trades(intercepted_at DESC);
CREATE INDEX IF NOT EXISTS shadow_trades_status_idx ON shadow_trades(status);

ALTER TABLE shadow_trades ENABLE ROW LEVEL SECURITY;

-- Users may read their own shadow trades (for the report/banner)
CREATE POLICY "shadow_trades_select_own"
    ON shadow_trades FOR SELECT
    USING (auth.uid() = user_id);

-- No user writes — service role only
CREATE POLICY "shadow_trades_no_user_write"
    ON shadow_trades FOR ALL
    USING (FALSE)
    WITH CHECK (FALSE);


-- ── shadow_pnl ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS shadow_pnl (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    period_label        TEXT NOT NULL,                          -- e.g. '2026-W22', 'all-time'
    period_start        TIMESTAMPTZ NOT NULL,
    period_end          TIMESTAMPTZ,                            -- NULL = rolling/all-time
    total_shadow_pnl    NUMERIC(12, 4) NOT NULL DEFAULT 0,
    total_trades        INTEGER NOT NULL DEFAULT 0,
    winning_trades      INTEGER NOT NULL DEFAULT 0,
    losing_trades       INTEGER NOT NULL DEFAULT 0,
    largest_win         NUMERIC(12, 4),
    largest_loss        NUMERIC(12, 4),
    hit_rate_pct        NUMERIC(5, 2),                          -- winning_trades / total_trades * 100
    avg_win_usd         NUMERIC(12, 4),
    avg_loss_usd        NUMERIC(12, 4),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (user_id, period_label)
);

CREATE INDEX IF NOT EXISTS shadow_pnl_user_id_idx ON shadow_pnl(user_id);
CREATE INDEX IF NOT EXISTS shadow_pnl_period_label_idx ON shadow_pnl(user_id, period_label);
CREATE INDEX IF NOT EXISTS shadow_pnl_updated_at_idx ON shadow_pnl(updated_at DESC);

ALTER TABLE shadow_pnl ENABLE ROW LEVEL SECURITY;

CREATE POLICY "shadow_pnl_select_own"
    ON shadow_pnl FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "shadow_pnl_no_user_write"
    ON shadow_pnl FOR ALL
    USING (FALSE)
    WITH CHECK (FALSE);

CREATE TRIGGER shadow_pnl_updated_at
    BEFORE UPDATE ON shadow_pnl
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
