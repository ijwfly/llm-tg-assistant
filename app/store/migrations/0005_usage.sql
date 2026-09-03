-- Phase 7: the model that served a turn (from system/init), for /usage. Idempotent.

ALTER TABLE turns ADD COLUMN IF NOT EXISTS model TEXT;
CREATE INDEX IF NOT EXISTS turns_finished_idx ON turns (finished_at);
