-- ══════════════════════════════════════════════════════════════════════════════
-- LuxAI Phase 2 — Supplementary RLS Policies & Helper Functions
-- Run after 001_phase2_schema.sql
-- ══════════════════════════════════════════════════════════════════════════════

-- ── set_updated_at trigger (if not already defined) ───────────────────────────
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ── Governance: approvals RLS ─────────────────────────────────────────────────
ALTER TABLE approval_requests ENABLE ROW LEVEL SECURITY;
CREATE POLICY approval_requests_user ON approval_requests
    FOR ALL USING (user_id = auth.uid());

-- ── Governance: user_roles RLS ────────────────────────────────────────────────
ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_roles_self ON user_roles
    FOR SELECT USING (user_id = auth.uid());

-- ── Telemetry: spans RLS ──────────────────────────────────────────────────────
ALTER TABLE telemetry_spans ENABLE ROW LEVEL SECURITY;
CREATE POLICY telemetry_spans_user ON telemetry_spans
    FOR SELECT USING (user_id = auth.uid());
CREATE POLICY telemetry_spans_insert ON telemetry_spans
    FOR INSERT WITH CHECK (true);  -- Service role inserts

-- ── Memory: increment access count safely ─────────────────────────────────────
CREATE OR REPLACE FUNCTION increment_memory_access(memory_id UUID)
RETURNS VOID AS $$
    UPDATE memories
    SET
        access_count = access_count + 1,
        last_accessed_at = NOW()
    WHERE id = memory_id;
$$ LANGUAGE sql;

-- ── Analytics: active sessions view ──────────────────────────────────────────
CREATE OR REPLACE VIEW v_active_sessions AS
SELECT
    s.id,
    s.user_id,
    s.agent_id,
    s.status,
    s.created_at,
    s.updated_at,
    EXTRACT(EPOCH FROM (NOW() - s.created_at)) AS duration_seconds
FROM sessions s
WHERE s.status IN ('pending', 'running')
ORDER BY s.created_at DESC;

-- ── Analytics: governance summary ────────────────────────────────────────────
CREATE OR REPLACE VIEW v_governance_summary AS
SELECT
    user_id,
    COUNT(*) FILTER (WHERE status = 'pending')       AS pending_approvals,
    COUNT(*) FILTER (WHERE status = 'approved')      AS approved_count,
    COUNT(*) FILTER (WHERE status = 'denied')        AS denied_count,
    COUNT(*) FILTER (WHERE status = 'auto_approved') AS auto_approved_count,
    COUNT(*) FILTER (WHERE status = 'expired')       AS expired_count
FROM approval_requests
GROUP BY user_id;
