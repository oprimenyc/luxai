-- =============================================================================
-- Migration 008: Scanner Daily Log + Scanner Debates
-- =============================================================================
-- Two new tables for scanner observability:
--
-- scanner_daily_log  — one row per market-day scan run. Written by the
--   auto_scanner_loop at the end of each daily scan. This is the primary
--   monitoring surface: if this table has no row for today, the scanner
--   did not run.
--
-- scanner_debates — one row per per-symbol TradingAgents debate result.
--   Replaces the broken insert into workbench_analyses that used the wrong
--   schema (wrong verdict values, missing required columns). The scanner
--   adapter now writes here instead.
--
-- RLS: service_role writes (bypasses RLS). Auth users cannot read these
--   tables — they are internal audit tables for admin/MCP access only.
--
-- Rollback:
--   DROP TABLE IF EXISTS scanner_debates CASCADE;
--   DROP TABLE IF EXISTS scanner_daily_log CASCADE;
-- =============================================================================

-- ── scanner_daily_log ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS scanner_daily_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_date           DATE NOT NULL,

    -- Watchlist stats
    symbols_scanned     INTEGER NOT NULL DEFAULT 0,
    symbols_skipped     INTEGER NOT NULL DEFAULT 0,   -- failed pre-filter
    debates_attempted   INTEGER NOT NULL DEFAULT 0,
    debates_completed   INTEGER NOT NULL DEFAULT 0,   -- returned non-NEUTRAL
    signals_generated   INTEGER NOT NULL DEFAULT 0,

    -- Infrastructure state at scan time
    deepseek_available  BOOLEAN NOT NULL DEFAULT FALSE,

    -- Zero-signal monitoring
    zero_signal_streak  INTEGER NOT NULL DEFAULT 0,   -- consecutive zero-signal days
    scanner_alert       TEXT,                         -- NULL = healthy; set when streak >= 3

    -- Error log — array of error message strings
    errors              JSONB NOT NULL DEFAULT '[]'::JSONB,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One row per calendar day — enforce via unique constraint so duplicate
-- inserts upsert rather than duplicate.
CREATE UNIQUE INDEX IF NOT EXISTS scanner_daily_log_scan_date_uidx
    ON scanner_daily_log(scan_date);

CREATE INDEX IF NOT EXISTS scanner_daily_log_created_at_idx
    ON scanner_daily_log(created_at DESC);

-- scanner_daily_log is an internal audit table; no user-facing RLS needed.
-- service_role key bypasses RLS entirely.
ALTER TABLE scanner_daily_log ENABLE ROW LEVEL SECURITY;

-- No public access — service_role only
CREATE POLICY "scanner_daily_log_deny_all"
    ON scanner_daily_log FOR ALL
    USING (FALSE);


-- ── scanner_debates ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS scanner_debates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_date       DATE NOT NULL,
    user_id         UUID NOT NULL,      -- scanner service UUID
    symbol          TEXT NOT NULL,
    verdict         TEXT NOT NULL CHECK (verdict IN ('BULLISH', 'BEARISH', 'NEUTRAL')),
    confidence      NUMERIC(5, 3),
    reasoning       TEXT,
    token_input     INTEGER NOT NULL DEFAULT 0,
    token_output    INTEGER NOT NULL DEFAULT 0,
    raw_decision    JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS scanner_debates_scan_date_idx
    ON scanner_debates(scan_date DESC);

CREATE INDEX IF NOT EXISTS scanner_debates_symbol_idx
    ON scanner_debates(symbol);

ALTER TABLE scanner_debates ENABLE ROW LEVEL SECURITY;

CREATE POLICY "scanner_debates_deny_all"
    ON scanner_debates FOR ALL
    USING (FALSE);
