-- Phase 4: staging items and inbox files. Idempotent.

CREATE TABLE IF NOT EXISTS staging_items (
    id            BIGSERIAL PRIMARY KEY,
    topic_id      BIGINT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,            -- forward | document | voice
    order_group   INT NOT NULL DEFAULT 0,   -- 0 forwards, 1 files, 2 transcripts
    payload       JSONB NOT NULL,           -- {"text": str, "images": [paths]}
    tg_message_id BIGINT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS staging_topic_idx ON staging_items (topic_id, order_group, id);

CREATE TABLE IF NOT EXISTS inbox_files (
    id          BIGSERIAL PRIMARY KEY,
    topic_id    BIGINT REFERENCES topics(id) ON DELETE SET NULL,
    path        TEXT NOT NULL,
    tg_file_id  TEXT,
    kind        TEXT NOT NULL,              -- photo | document | voice | out
    size        BIGINT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS inbox_files_topic_idx ON inbox_files (topic_id, id DESC);
