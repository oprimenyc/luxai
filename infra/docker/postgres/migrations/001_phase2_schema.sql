-- ══════════════════════════════════════════════════════════════════════════════
-- LuxAI Phase 2 — Database migrations
-- Run in Supabase SQL Editor or via psql.
-- ══════════════════════════════════════════════════════════════════════════════

-- ── Prerequisites ─────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";  -- pgvector for semantic search

-- ══════════════════════════════════════════════════════════════════════════════
-- EVENTS TABLE — persistent event log for audit, replay, analytics
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type            TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'info'
                        CHECK (severity IN ('debug','info','warning','error','critical')),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_id      TEXT,
    agent_id        TEXT,
    user_id         UUID,
    correlation_id  TEXT,
    payload         JSONB NOT NULL DEFAULT '{}',
    metadata        JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_events_type         ON events (type);
CREATE INDEX IF NOT EXISTS idx_events_session_id   ON events (session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_user_id      ON events (user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_timestamp    ON events (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_severity     ON events (severity) WHERE severity IN ('warning','error','critical');

-- Partition hint: in production, partition events by month
-- ALTER TABLE events PARTITION BY RANGE (timestamp);

ALTER TABLE events ENABLE ROW LEVEL SECURITY;
CREATE POLICY events_user_isolation ON events
    FOR SELECT USING (user_id = auth.uid() OR user_id IS NULL);

-- ══════════════════════════════════════════════════════════════════════════════
-- MEMORIES TABLE — pgvector semantic memory store
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS memories (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL,
    content             TEXT NOT NULL,
    memory_type         TEXT NOT NULL
                            CHECK (memory_type IN ('semantic','episodic','workflow','user','project','strategic')),
    embedding           vector(1536),           -- OpenAI text-embedding-3-small
    embedding_model     TEXT NOT NULL DEFAULT 'text-embedding-3-small',
    agent_id            TEXT,
    session_id          TEXT,
    tags                TEXT[] NOT NULL DEFAULT '{}',
    metadata            JSONB NOT NULL DEFAULT '{}',
    importance_score    DOUBLE PRECISION NOT NULL DEFAULT 0.5
                            CHECK (importance_score >= 0.0 AND importance_score <= 1.0),
    confidence_score    DOUBLE PRECISION NOT NULL DEFAULT 1.0
                            CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
    status              TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active','archived','compressed','evicted')),
    access_count        INTEGER NOT NULL DEFAULT 0,
    last_accessed_at    TIMESTAMPTZ,
    expires_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Exact-match indexes
CREATE INDEX IF NOT EXISTS idx_memories_user_id      ON memories (user_id);
CREATE INDEX IF NOT EXISTS idx_memories_type         ON memories (memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_agent_id     ON memories (agent_id) WHERE agent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memories_session_id   ON memories (session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memories_status       ON memories (status);
CREATE INDEX IF NOT EXISTS idx_memories_tags         ON memories USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_memories_created_at   ON memories (created_at DESC);

-- IVFFlat ANN index for vector similarity search
-- lists=100 is appropriate for ~100k rows; tune up as dataset grows
CREATE INDEX IF NOT EXISTS idx_memories_embedding
    ON memories USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
CREATE POLICY memories_user_isolation ON memories USING (user_id = auth.uid());

CREATE OR REPLACE TRIGGER memories_set_updated_at
    BEFORE UPDATE ON memories
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ── pgvector search function ──────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION search_memories(
    query_embedding     vector(1536),
    user_id_filter      UUID,
    match_threshold     DOUBLE PRECISION DEFAULT 0.6,
    match_count         INTEGER DEFAULT 10,
    memory_types        TEXT[] DEFAULT NULL,
    agent_id_filter     TEXT DEFAULT NULL,
    session_id_filter   TEXT DEFAULT NULL,
    tags_filter         TEXT[] DEFAULT NULL
)
RETURNS TABLE (
    id                  UUID,
    user_id             UUID,
    content             TEXT,
    memory_type         TEXT,
    embedding_model     TEXT,
    agent_id            TEXT,
    session_id          TEXT,
    tags                TEXT[],
    metadata            JSONB,
    importance_score    DOUBLE PRECISION,
    confidence_score    DOUBLE PRECISION,
    status              TEXT,
    access_count        INTEGER,
    last_accessed_at    TIMESTAMPTZ,
    expires_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ,
    similarity          DOUBLE PRECISION
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        m.id, m.user_id, m.content, m.memory_type, m.embedding_model,
        m.agent_id, m.session_id, m.tags, m.metadata,
        m.importance_score, m.confidence_score, m.status,
        m.access_count, m.last_accessed_at, m.expires_at,
        m.created_at, m.updated_at,
        -- Hybrid score: cosine similarity + importance weight
        (1 - (m.embedding <=> query_embedding)) * 0.8
            + m.importance_score * 0.2 AS similarity
    FROM memories m
    WHERE
        m.user_id = user_id_filter
        AND m.status = 'active'
        AND (m.expires_at IS NULL OR m.expires_at > NOW())
        AND (1 - (m.embedding <=> query_embedding)) >= match_threshold
        AND (memory_types IS NULL OR m.memory_type = ANY(memory_types))
        AND (agent_id_filter IS NULL OR m.agent_id = agent_id_filter)
        AND (session_id_filter IS NULL OR m.session_id = session_id_filter)
        AND (tags_filter IS NULL OR m.tags && tags_filter)
    ORDER BY similarity DESC
    LIMIT match_count;
END;
$$;

-- ══════════════════════════════════════════════════════════════════════════════
-- WORKFLOWS TABLE — autonomous workflow execution state
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS workflows (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL,
    name            VARCHAR(100) NOT NULL,
    description     VARCHAR(500) NOT NULL DEFAULT '',
    steps           JSONB NOT NULL DEFAULT '[]',
    step_executions JSONB NOT NULL DEFAULT '[]',
    schedule        TEXT,
    context         JSONB NOT NULL DEFAULT '{}',
    tags            TEXT[] NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft','queued','running','paused','completed','failed','cancelled','recovering')),
    checkpoint      JSONB,
    current_step_id TEXT,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflows_user_id    ON workflows (user_id);
CREATE INDEX IF NOT EXISTS idx_workflows_status     ON workflows (status);
CREATE INDEX IF NOT EXISTS idx_workflows_created_at ON workflows (created_at DESC);

ALTER TABLE workflows ENABLE ROW LEVEL SECURITY;
CREATE POLICY workflows_user_isolation ON workflows USING (user_id = auth.uid());

CREATE OR REPLACE TRIGGER workflows_set_updated_at
    BEFORE UPDATE ON workflows
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ══════════════════════════════════════════════════════════════════════════════
-- GOVERNANCE TABLES — RBAC, approvals, audit log
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS user_roles (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL,
    role        TEXT NOT NULL
                    CHECK (role IN ('owner','admin','operator','viewer','auditor')),
    granted_by  UUID,
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ,
    UNIQUE (user_id)
);

CREATE TABLE IF NOT EXISTS approval_requests (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id      TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    user_id         UUID NOT NULL,
    risk_assessment JSONB NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','approved','denied','expired','auto_approved')),
    approved_by     UUID,
    denial_reason   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    resolved_at     TIMESTAMPTZ,
    metadata        JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_approvals_user_id    ON approval_requests (user_id);
CREATE INDEX IF NOT EXISTS idx_approvals_status     ON approval_requests (status);
CREATE INDEX IF NOT EXISTS idx_approvals_session_id ON approval_requests (session_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID,
    action      TEXT NOT NULL,
    resource    TEXT NOT NULL,
    resource_id TEXT,
    ip_address  TEXT,
    user_agent  TEXT,
    before_data JSONB,
    after_data  JSONB,
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_user_id    ON audit_log (user_id);
CREATE INDEX IF NOT EXISTS idx_audit_action     ON audit_log (action);
CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log (created_at DESC);

-- Audit log is append-only — no updates or deletes
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_log_select ON audit_log FOR SELECT
    USING (user_id = auth.uid());
CREATE POLICY audit_log_insert ON audit_log FOR INSERT
    WITH CHECK (true);  -- Insert allowed; service role handles this

-- ══════════════════════════════════════════════════════════════════════════════
-- TELEMETRY TABLE — token usage and latency tracking
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS telemetry_spans (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id      TEXT,
    agent_id        TEXT,
    user_id         UUID,
    operation       TEXT NOT NULL,
    model           TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    duration_ms     INTEGER,
    cost_usd        DOUBLE PRECISION,
    status          TEXT DEFAULT 'ok',
    error           TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telemetry_session_id  ON telemetry_spans (session_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_user_id     ON telemetry_spans (user_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_created_at  ON telemetry_spans (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_model       ON telemetry_spans (model);

-- ── Telemetry aggregation views ───────────────────────────────────────────────

CREATE OR REPLACE VIEW v_token_usage_daily AS
SELECT
    DATE_TRUNC('day', created_at) AS day,
    user_id,
    model,
    SUM(input_tokens)  AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(input_tokens + output_tokens) AS total_tokens,
    SUM(cost_usd)      AS total_cost_usd,
    COUNT(*)           AS span_count
FROM telemetry_spans
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY 1, 2, 3
ORDER BY 1 DESC;

CREATE OR REPLACE VIEW v_latency_p95 AS
SELECT
    DATE_TRUNC('hour', created_at) AS hour,
    operation,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99_ms,
    COUNT(*) AS request_count
FROM telemetry_spans
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY 1, 2
ORDER BY 1 DESC;
