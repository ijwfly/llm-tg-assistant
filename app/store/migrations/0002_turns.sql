-- Phase 2: turns, resumable flag on topics, delivery metadata on outbox. Idempotent.

ALTER TABLE topics ADD COLUMN IF NOT EXISTS session_resumable BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS turns (
    id             BIGSERIAL PRIMARY KEY,
    topic_id       BIGINT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    prompt         JSONB NOT NULL,                 -- content blocks sent to Claude Code (for /retry)
    status         TEXT NOT NULL DEFAULT 'queued', -- queued | running | done | cancelled | timeout | error | crashed | aborted
    result_subtype TEXT,
    duration_ms    INT,
    num_turns      INT,
    cost_usd       DOUBLE PRECISION,
    usage          JSONB,
    error          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at     TIMESTAMPTZ,
    finished_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS turns_topic_idx ON turns (topic_id, id DESC);

ALTER TABLE outbox ADD COLUMN IF NOT EXISTS topic_id BIGINT;
ALTER TABLE outbox ADD COLUMN IF NOT EXISTS turn_id BIGINT;
ALTER TABLE outbox ADD COLUMN IF NOT EXISTS role TEXT;
