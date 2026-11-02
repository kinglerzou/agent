ALTER TABLE turns DROP CONSTRAINT IF EXISTS turns_status_check;
ALTER TABLE turns ADD CONSTRAINT turns_status_check
    CHECK(status IN ('running','pending_review','completed','rejected','failed','cancelled'));
ALTER TABLE turns ADD COLUMN IF NOT EXISTS draft text NOT NULL DEFAULT '';
ALTER TABLE turns ADD COLUMN IF NOT EXISTS review jsonb;
INSERT INTO schema_versions VALUES(3) ON CONFLICT DO NOTHING;
