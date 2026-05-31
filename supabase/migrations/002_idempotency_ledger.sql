-- =============================================================================
-- Migration 002: Order Idempotency Ledger
-- =============================================================================
-- Table: order_idempotency_log
--   Durable audit ledger for all order idempotency checks.
--   Redis is the fast hot-path check (SETNX). This table is the
--   authoritative record that survives Redis restarts/evictions.
--
-- RLS: users read own rows only. No user writes — service role only.
--
-- Rollback:
--   DROP TABLE IF EXISTS order_idempotency_log CASCADE;
-- =============================================================================

CREATE TABLE IF NOT EXISTS order_idempotency_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- SHA-256 hex of the normalized request payload (symbol+side+qty+type+key)
    payload_hash        TEXT NOT NULL,

    -- Original request payload stored for deduplication response replay
    request_payload     JSONB NOT NULL DEFAULT '{}'::JSONB,

    -- Cached response returned on duplicate detection
    response_payload    JSONB NOT NULL DEFAULT '{}'::JSONB,

    -- Lifecycle
    status              TEXT NOT NULL DEFAULT 'received'
                            CHECK (status IN ('received', 'completed', 'failed')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,

    -- Unique constraint: same user cannot submit same payload hash within 24h window
    -- (enforced additionally in application layer via Redis TTL)
    UNIQUE (user_id, payload_hash)
);

CREATE INDEX IF NOT EXISTS order_idempotency_log_user_id_idx
    ON order_idempotency_log(user_id);

CREATE INDEX IF NOT EXISTS order_idempotency_log_created_at_idx
    ON order_idempotency_log(created_at DESC);

-- Compound index for fast duplicate lookups (user + hash).
-- Note: partial index on NOW() removed — NOW() is not IMMUTABLE in Postgres
-- and cannot appear in index predicates. The 24h window is enforced by
-- the application layer via Redis TTL (idempotency.py, _REDIS_TTL=86400).
CREATE INDEX IF NOT EXISTS order_idempotency_log_lookup_idx
    ON order_idempotency_log(user_id, payload_hash);

ALTER TABLE order_idempotency_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "idempotency_log_select_own"
    ON order_idempotency_log FOR SELECT
    USING (auth.uid() = user_id);

-- No user writes — service role only
CREATE POLICY "idempotency_log_no_user_write"
    ON order_idempotency_log FOR ALL
    USING (FALSE)
    WITH CHECK (FALSE);
