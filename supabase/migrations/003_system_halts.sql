-- =============================================================================
-- Migration 003: System Halts (Persistent Kill Switch)
-- =============================================================================
-- Table: system_halts
--   Durable audit ledger for all emergency halt activations and clearances.
--   Redis key kill_switch:{user_id} is the fast hot-path read.
--   This table is the authoritative record that survives Redis restarts.
--
-- Design: one row per halt event (append-only). The "current" state is the
--   row with the highest created_at that has cleared_at IS NULL.
--
-- RLS: users read own rows only. No user writes — service role only.
--
-- Rollback:
--   DROP TABLE IF EXISTS system_halts CASCADE;
-- =============================================================================

CREATE TABLE IF NOT EXISTS system_halts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Who activated the halt and why
    activated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_by    TEXT NOT NULL,
    reason          TEXT NOT NULL DEFAULT 'operator_triggered',
    audit_notes     TEXT,

    -- Populated when the halt is cleared (admin only)
    cleared_at      TIMESTAMPTZ,
    cleared_by      TEXT,
    clear_notes     TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS system_halts_user_id_idx ON system_halts(user_id);
CREATE INDEX IF NOT EXISTS system_halts_activated_at_idx ON system_halts(activated_at DESC);

-- Fast lookup: is there an active (non-cleared) halt for this user?
CREATE INDEX IF NOT EXISTS system_halts_active_idx
    ON system_halts(user_id, cleared_at)
    WHERE cleared_at IS NULL;

ALTER TABLE system_halts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "system_halts_select_own"
    ON system_halts FOR SELECT
    USING (auth.uid() = user_id);

-- No user writes — service role only
CREATE POLICY "system_halts_no_user_write"
    ON system_halts FOR ALL
    USING (FALSE)
    WITH CHECK (FALSE);
