-- Phase 5: permission / question / plan prompts and "always" rules. Idempotent.

CREATE TABLE IF NOT EXISTS pending_prompts (
    id            BIGSERIAL PRIMARY KEY,
    topic_id      BIGINT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    turn_id       BIGINT,
    kind          TEXT NOT NULL,              -- permission | question | plan
    tool_name     TEXT NOT NULL,
    tool_use_id   TEXT,
    payload       JSONB NOT NULL,             -- the tool input as received
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending | answered | timeout | cancelled | stale
    answer        JSONB,                      -- the decision sent back to Claude Code
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS pending_prompts_topic_idx ON pending_prompts (topic_id, id DESC);

CREATE TABLE IF NOT EXISTS topic_rules (
    topic_id   BIGINT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    rule       TEXT NOT NULL,                 -- e.g. Bash(git status *)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (topic_id, rule)
);
