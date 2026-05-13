-- ══════════════════════════════════════════════════════════════════════════════
-- LuxAI — PostgreSQL initialization script (development only)
-- In production, use Supabase migrations.
-- ══════════════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Enums ────────────────────────────────────────────────────────────────────

CREATE TYPE agent_status AS ENUM (
    'idle', 'running', 'paused', 'error', 'terminated'
);

CREATE TYPE session_status AS ENUM (
    'pending', 'running', 'completed', 'failed', 'cancelled'
);

-- ── Agents ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agents (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id       UUID NOT NULL,
    name          VARCHAR(100) NOT NULL,
    description   VARCHAR(500) NOT NULL DEFAULT '',
    capabilities  TEXT[] NOT NULL DEFAULT '{}',
    system_prompt TEXT NOT NULL DEFAULT '',
    model         VARCHAR(100) NOT NULL DEFAULT 'gpt-4o',
    temperature   DOUBLE PRECISION NOT NULL DEFAULT 0.7
                      CHECK (temperature >= 0.0 AND temperature <= 2.0),
    max_tokens    INTEGER NOT NULL DEFAULT 4096
                      CHECK (max_tokens >= 1 AND max_tokens <= 200000),
    status        agent_status NOT NULL DEFAULT 'idle',
    metadata      JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agents_user_id     ON agents (user_id);
CREATE INDEX IF NOT EXISTS idx_agents_status      ON agents (status);
CREATE INDEX IF NOT EXISTS idx_agents_created_at  ON agents (created_at DESC);

-- ── Sessions ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sessions (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id      UUID NOT NULL,
    agent_id     UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    task         TEXT NOT NULL,
    context      JSONB NOT NULL DEFAULT '{}',
    status       session_status NOT NULL DEFAULT 'pending',
    messages     JSONB NOT NULL DEFAULT '[]',
    result       JSONB,
    error        TEXT,
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id    ON sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_agent_id   ON sessions (agent_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status     ON sessions (status);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions (created_at DESC);

-- ── updated_at trigger ────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER agents_set_updated_at
    BEFORE UPDATE ON agents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE TRIGGER sessions_set_updated_at
    BEFORE UPDATE ON sessions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ── Row Level Security ────────────────────────────────────────────────────────

ALTER TABLE agents  ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;

-- Users can only access their own agents
CREATE POLICY agents_user_isolation ON agents
    USING (user_id = auth.uid());

-- Users can only access their own sessions
CREATE POLICY sessions_user_isolation ON sessions
    USING (user_id = auth.uid());
