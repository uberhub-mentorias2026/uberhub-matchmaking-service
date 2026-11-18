CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS mentors_index (
    mentor_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    bio TEXT NOT NULL,
    skills TEXT[] NOT NULL DEFAULT '{}',
    language VARCHAR(16) NOT NULL,
    format VARCHAR(32) NOT NULL,
    experience_years INT NOT NULL DEFAULT 0,
    current_load INT NOT NULL DEFAULT 0,
    max_load INT NOT NULL DEFAULT 3,
    availability_slots TEXT[] NOT NULL DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    embedding vector(384),
    version INT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mentors_filter
    ON mentors_index (is_active, language, format);

CREATE INDEX IF NOT EXISTS idx_mentors_skills_gin
    ON mentors_index USING GIN (skills);

CREATE TABLE IF NOT EXISTS match_requests (
    id UUID PRIMARY KEY,
    idempotency_key VARCHAR(128) UNIQUE,
    status VARCHAR(32) NOT NULL,
    revalidation_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    payload JSONB NOT NULL,
    result JSONB,
    algorithm_version VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS match_decisions (
    id UUID PRIMARY KEY,
    match_request_id UUID NOT NULL REFERENCES match_requests(id) ON DELETE CASCADE,
    mentor_id VARCHAR(64) NOT NULL,
    rank_position INT NOT NULL,
    total_score NUMERIC(5, 4) NOT NULL,
    score_breakdown JSONB NOT NULL,
    algorithm_version VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_decisions_mentor
    ON match_decisions (mentor_id, created_at DESC);

CREATE TABLE IF NOT EXISTS match_feedback (
    id UUID PRIMARY KEY,
    match_request_id UUID NOT NULL REFERENCES match_requests(id) ON DELETE CASCADE,
    mentor_id VARCHAR(64) NOT NULL,
    decision VARCHAR(16) NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
