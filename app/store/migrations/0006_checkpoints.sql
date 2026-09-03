-- Phase 8: the user-message uuid of a turn (file checkpoint for --rewind-files). Idempotent.

ALTER TABLE turns ADD COLUMN IF NOT EXISTS checkpoint_uuid TEXT;
