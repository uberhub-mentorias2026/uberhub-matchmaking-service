ALTER TABLE mentors_index
    ADD COLUMN IF NOT EXISTS search_tsv tsvector;

UPDATE mentors_index
SET search_tsv =
    setweight(to_tsvector('portuguese', coalesce(array_to_string(skills, ' '), '')), 'A') ||
    setweight(to_tsvector('portuguese', coalesce(name, '')), 'B') ||
    setweight(to_tsvector('portuguese', coalesce(bio, '')), 'C');

CREATE INDEX IF NOT EXISTS idx_mentors_fts_gin
    ON mentors_index USING GIN (search_tsv);

CREATE TABLE IF NOT EXISTS processed_events (
    event_id VARCHAR(128) PRIMARY KEY,
    mentor_id VARCHAR(64) NOT NULL,
    event_version INT NOT NULL,
    status VARCHAR(32) NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
