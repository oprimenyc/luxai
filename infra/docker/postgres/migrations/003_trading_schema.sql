-- ══════════════════════════════════════════════════════════════════════════════
-- LuxAI Phase 3 — Paper Trading Schema
-- Run via: psql $DATABASE_URL -f 003_trading_schema.sql
-- ══════════════════════════════════════════════════════════════════════════════

-- ── Trade Journal ─────────────────────────────────────────────────────────────
-- Append-only audit log for every order lifecycle event.
-- Never updated after insert.

CREATE TABLE IF NOT EXISTS trade_journal (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entry_type      TEXT NOT NULL,
    order_id        UUID,
    symbol          TEXT,
    payload         JSONB NOT NULL DEFAULT '{}',
    execution_mode  TEXT NOT NULL DEFAULT 'paper'
                        CHECK (execution_mode IN ('paper', 'simulation')),
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tj_entry_type  ON trade_journal (entry_type);
CREATE INDEX IF NOT EXISTS idx_tj_symbol      ON trade_journal (symbol) WHERE symbol IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tj_order_id    ON trade_journal (order_id) WHERE order_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tj_recorded_at ON trade_journal (recorded_at DESC);

-- ── Orders ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS paper_orders (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    broker_order_id   TEXT NOT NULL UNIQUE,
    user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    symbol            TEXT NOT NULL,
    side              TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    qty               INTEGER NOT NULL CHECK (qty > 0),
    order_type        TEXT NOT NULL DEFAULT 'market',
    status            TEXT NOT NULL DEFAULT 'pending',
    limit_price       NUMERIC(18, 4),
    stop_price        NUMERIC(18, 4),
    filled_qty        INTEGER NOT NULL DEFAULT 0,
    avg_fill_price    NUMERIC(18, 4),
    time_in_force     TEXT NOT NULL DEFAULT 'day',
    execution_mode    TEXT NOT NULL DEFAULT 'paper',
    submitted_at      TIMESTAMPTZ,
    filled_at         TIMESTAMPTZ,
    cancelled_at      TIMESTAMPTZ,
    metadata          JSONB NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_user_id    ON paper_orders (user_id);
CREATE INDEX IF NOT EXISTS idx_orders_symbol     ON paper_orders (symbol);
CREATE INDEX IF NOT EXISTS idx_orders_status     ON paper_orders (status);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON paper_orders (created_at DESC);

-- ── Positions (snapshot) ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS paper_positions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    symbol          TEXT NOT NULL,
    qty             INTEGER NOT NULL,
    avg_cost        NUMERIC(18, 4) NOT NULL,
    current_price   NUMERIC(18, 4),
    opened_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_positions_user_id ON paper_positions (user_id);

-- ── PnL Records ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS paper_pnl_records (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id                 UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    symbol                  TEXT NOT NULL,
    side                    TEXT NOT NULL,
    qty                     INTEGER NOT NULL,
    entry_price             NUMERIC(18, 4) NOT NULL,
    exit_price              NUMERIC(18, 4) NOT NULL,
    commission              NUMERIC(18, 4) NOT NULL DEFAULT 0,
    realized_pnl            NUMERIC(18, 4) NOT NULL,
    realized_pnl_pct        NUMERIC(10, 6) NOT NULL,
    holding_period_seconds  NUMERIC(18, 2),
    opened_at               TIMESTAMPTZ NOT NULL,
    closed_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata                JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_pnl_user_id    ON paper_pnl_records (user_id);
CREATE INDEX IF NOT EXISTS idx_pnl_symbol     ON paper_pnl_records (symbol);
CREATE INDEX IF NOT EXISTS idx_pnl_closed_at  ON paper_pnl_records (closed_at DESC);

-- ── Risk Triggers ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS risk_triggers (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    symbol          TEXT NOT NULL,
    action          TEXT NOT NULL,
    reason          TEXT NOT NULL,
    entry_price     NUMERIC(18, 4) NOT NULL,
    trigger_price   NUMERIC(18, 4) NOT NULL,
    current_price   NUMERIC(18, 4) NOT NULL,
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_risk_user_id     ON risk_triggers (user_id);
CREATE INDEX IF NOT EXISTS idx_risk_symbol      ON risk_triggers (symbol);
CREATE INDEX IF NOT EXISTS idx_risk_triggered   ON risk_triggers (triggered_at DESC);

-- ── Portfolio Snapshots ───────────────────────────────────────────────────────
-- Hourly snapshots for equity curve charting.

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    account_id      TEXT NOT NULL,
    cash            NUMERIC(18, 4) NOT NULL,
    equity          NUMERIC(18, 4) NOT NULL,
    unrealized_pnl  NUMERIC(18, 4) NOT NULL DEFAULT 0,
    realized_pnl    NUMERIC(18, 4) NOT NULL DEFAULT 0,
    position_count  INTEGER NOT NULL DEFAULT 0,
    execution_mode  TEXT NOT NULL DEFAULT 'paper',
    snapshotted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_snapshots_user_id ON portfolio_snapshots (user_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_ts      ON portfolio_snapshots (snapshotted_at DESC);

-- ── RLS Policies ─────────────────────────────────────────────────────────────

ALTER TABLE trade_journal      ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_orders       ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_positions    ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_pnl_records  ENABLE ROW LEVEL SECURITY;
ALTER TABLE risk_triggers      ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_snapshots ENABLE ROW LEVEL SECURITY;

-- trade_journal: service role only (no user_id column)
CREATE POLICY tj_service_all   ON trade_journal   TO service_role USING (true);

-- per-user isolation
CREATE POLICY orders_user_own  ON paper_orders
    FOR ALL USING (user_id = auth.uid());

CREATE POLICY positions_own    ON paper_positions
    FOR ALL USING (user_id = auth.uid());

CREATE POLICY pnl_own          ON paper_pnl_records
    FOR ALL USING (user_id = auth.uid());

CREATE POLICY risk_own         ON risk_triggers
    FOR ALL USING (user_id = auth.uid());

CREATE POLICY snapshots_own    ON portfolio_snapshots
    FOR ALL USING (user_id = auth.uid());
