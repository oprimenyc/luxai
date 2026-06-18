-- Path: supabase/migrations/006_account_settings.sql
-- Rollback: DROP TABLE IF EXISTS account_settings; DROP FUNCTION IF EXISTS update_account_settings_updated_at;

CREATE TABLE IF NOT EXISTS account_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL UNIQUE,

    -- Shadow testing overrides (applied only when shadow_mode is active)
    -- These relax the Tiny tier defaults so more signal types can be tested.
    -- CRITICAL: these values NEVER apply to live order submission.
    shadow_min_dte INTEGER NOT NULL DEFAULT 3
        CHECK (shadow_min_dte BETWEEN 1 AND 7),
    shadow_max_dte INTEGER NOT NULL DEFAULT 21
        CHECK (shadow_max_dte BETWEEN 7 AND 60),
    shadow_max_contracts INTEGER NOT NULL DEFAULT 3
        CHECK (shadow_max_contracts BETWEEN 1 AND 3),
    shadow_max_risk_usd NUMERIC(10,2) NOT NULL DEFAULT 15.00
        CHECK (shadow_max_risk_usd BETWEEN 5.00 AND 15.00),
    shadow_allow_earnings BOOLEAN NOT NULL DEFAULT FALSE,

    -- Scanner quality threshold (shared between shadow and live)
    score_threshold NUMERIC(4,1) NOT NULL DEFAULT 7.0
        CHECK (score_threshold BETWEEN 6.0 AND 9.0),

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION update_account_settings_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER account_settings_updated_at
    BEFORE UPDATE ON account_settings
    FOR EACH ROW EXECUTE FUNCTION update_account_settings_updated_at();

ALTER TABLE account_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users_read_own_settings"
    ON account_settings FOR SELECT
    USING (auth.uid()::text = user_id);

CREATE POLICY "users_insert_own_settings"
    ON account_settings FOR INSERT
    WITH CHECK (auth.uid()::text = user_id);

CREATE POLICY "users_update_own_settings"
    ON account_settings FOR UPDATE
    USING (auth.uid()::text = user_id);
