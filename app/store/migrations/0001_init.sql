-- Phase 1: users, topics, outbox, processed updates, message links. Idempotent.

CREATE TABLE IF NOT EXISTS users (
    tg_id       BIGINT PRIMARY KEY,
    name        TEXT,
    username    TEXT,
    settings    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS topics (
    id               BIGSERIAL PRIMARY KEY,
    chat_id          BIGINT NOT NULL,
    thread_id        BIGINT,
    title            TEXT,
    cwd              TEXT NOT NULL,
    session_id       UUID,
    model            TEXT,
    effort           TEXT,
    permission_mode  TEXT,
    soul_path        TEXT,
    settings         JSONB NOT NULL DEFAULT '{}'::jsonb,
    state            TEXT NOT NULL DEFAULT 'idle',
    awaiting         JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS topics_chat_thread_uq ON topics (chat_id, COALESCE(thread_id, 0));

CREATE TABLE IF NOT EXISTS outbox (
    id                   BIGSERIAL PRIMARY KEY,
    topic_key            TEXT NOT NULL,
    method               TEXT NOT NULL,
    payload              JSONB NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending',   -- pending | delivered | failed
    attempts             INT NOT NULL DEFAULT 0,
    next_attempt_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at         TIMESTAMPTZ,
    delivered_message_id BIGINT,
    last_error           TEXT
);
CREATE INDEX IF NOT EXISTS outbox_pending_idx ON outbox (topic_key, id) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS processed_updates (
    update_id  BIGINT PRIMARY KEY,
    at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS message_links (
    chat_id        BIGINT NOT NULL,
    tg_message_id  BIGINT NOT NULL,
    topic_id       BIGINT REFERENCES topics(id) ON DELETE CASCADE,
    turn_id        BIGINT,
    role           TEXT NOT NULL,   -- user | assistant | card | progress
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chat_id, tg_message_id)
);
