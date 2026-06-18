-- Path: supabase/migrations/007_drop_shadow_trades_user_fk.sql
-- Security: Allows reserved service UUID to write shadow trades without auth.users membership.
-- Scale: Single-tenant. If multi-tenant, namespace scanner UUID per account.

-- The auto-scanner service writes shadow_trades with a reserved UUID
-- (00000000-0000-0000-0000-000000000001) that is not an auth.users row.
-- The FK to auth.users causes every scanner insert to fail with a FK violation.
-- Shadow trades are internal telemetry — they do not require an auth user identity.

ALTER TABLE shadow_trades
  DROP CONSTRAINT IF EXISTS shadow_trades_user_id_fkey;

-- Rollback:
-- ALTER TABLE shadow_trades
--   ADD CONSTRAINT shadow_trades_user_id_fkey
--   FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;
