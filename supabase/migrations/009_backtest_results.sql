-- Migration: 009_backtest_results.sql
-- Purpose: Store backtest run summaries and DTE/delta analysis results
-- Rollback: see bottom of file
-- Applied: 2026-06-26

-- ── backtest_runs ─────────────────────────────────────────────────────────────
-- One row per Lumibot backtest execution.

CREATE TABLE IF NOT EXISTS backtest_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_date        DATE NOT NULL DEFAULT CURRENT_DATE,
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    starting_cash   NUMERIC(10, 2) NOT NULL,
    ending_value    NUMERIC(10, 2),
    total_return_pct NUMERIC(8, 4),
    benchmark_return_pct NUMERIC(8, 4),   -- SPY buy-and-hold over same period
    total_trades    INTEGER DEFAULT 0,
    winning_trades  INTEGER DEFAULT 0,
    win_rate        NUMERIC(5, 4),
    data_mode       TEXT NOT NULL DEFAULT 'SYNTHETIC_BLACK_SCHOLES',
    synthetic_iv    NUMERIC(5, 4),
    notes           TEXT,
    raw_results     JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── backtest_trades ───────────────────────────────────────────────────────────
-- Individual trade events from a backtest run.

CREATE TABLE IF NOT EXISTS backtest_trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    symbol          TEXT NOT NULL,
    contract_symbol TEXT,
    option_type     TEXT CHECK (option_type IN ('call', 'put')),
    strike          NUMERIC(10, 2),
    expiry          DATE,
    target_dte      INTEGER,
    target_delta    NUMERIC(5, 3),
    entry_date      DATE,
    exit_date       DATE,
    entry_price     NUMERIC(10, 4),
    exit_price      NUMERIC(10, 4),
    pnl_pct         NUMERIC(8, 4),
    days_held       INTEGER,
    exit_reason     TEXT CHECK (exit_reason IN ('stop_loss', 'take_profit', 'expiry', 'manual')),
    score           NUMERIC(4, 1),
    data_mode       TEXT NOT NULL DEFAULT 'SYNTHETIC_BLACK_SCHOLES',
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── dte_delta_analysis ────────────────────────────────────────────────────────
-- DTE/delta sweep summary from scripts/run_options_analysis.py
-- One row per (symbol, option_type, dte, delta) bucket per analysis run.

CREATE TABLE IF NOT EXISTS dte_delta_analysis (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_date        DATE NOT NULL DEFAULT CURRENT_DATE,
    period          TEXT NOT NULL,         -- e.g. '6mo'
    symbol          TEXT NOT NULL,
    option_type     TEXT CHECK (option_type IN ('call', 'put')),
    target_dte      INTEGER NOT NULL,
    target_delta    NUMERIC(5, 3) NOT NULL,
    trades          INTEGER NOT NULL DEFAULT 0,
    win_rate        NUMERIC(5, 4),
    avg_pnl_pct     NUMERIC(8, 4),
    max_loss_pct    NUMERIC(8, 4),
    max_gain_pct    NUMERIC(8, 4),
    data_mode       TEXT NOT NULL DEFAULT 'SYNTHETIC_BLACK_SCHOLES',
    synthetic_iv    NUMERIC(5, 4),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_date, symbol, option_type, target_dte, target_delta)
);

-- ── Indexes ───────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_backtest_runs_date
    ON backtest_runs (run_date DESC);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_run_id
    ON backtest_trades (run_id);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_symbol
    ON backtest_trades (symbol, entry_date DESC);

CREATE INDEX IF NOT EXISTS idx_dte_delta_run_date
    ON dte_delta_analysis (run_date DESC, symbol);

-- ── RLS ───────────────────────────────────────────────────────────────────────
-- Deny public access. service_role bypasses RLS for script writes.

ALTER TABLE backtest_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE backtest_trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE dte_delta_analysis ENABLE ROW LEVEL SECURITY;

CREATE POLICY "deny_public_backtest_runs"
    ON backtest_runs FOR ALL TO public USING (false);

CREATE POLICY "deny_public_backtest_trades"
    ON backtest_trades FOR ALL TO public USING (false);

CREATE POLICY "deny_public_dte_delta"
    ON dte_delta_analysis FOR ALL TO public USING (false);

-- ── ROLLBACK ──────────────────────────────────────────────────────────────────
-- DROP TABLE IF EXISTS dte_delta_analysis CASCADE;
-- DROP TABLE IF EXISTS backtest_trades CASCADE;
-- DROP TABLE IF EXISTS backtest_runs CASCADE;
