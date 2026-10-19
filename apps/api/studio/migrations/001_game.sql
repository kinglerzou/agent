CREATE TABLE IF NOT EXISTS schema_versions (version integer PRIMARY KEY);
CREATE TABLE IF NOT EXISTS knowledge_state (id integer PRIMARY KEY CHECK(id=1), revision bigint NOT NULL DEFAULT 0);
INSERT INTO knowledge_state(id) VALUES(1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS documents (
    id text PRIMARY KEY, title text NOT NULL, content text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS conversations (
    id uuid PRIMARY KEY, owner_id text NOT NULL, title text NOT NULL DEFAULT '新的咨询',
    revision bigint NOT NULL DEFAULT 0, legacy_id text,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(owner_id, legacy_id)
);
CREATE INDEX IF NOT EXISTS conversations_owner_updated ON conversations(owner_id,updated_at DESC);
CREATE TABLE IF NOT EXISTS turns (
    id uuid PRIMARY KEY, conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    request_id uuid NOT NULL, question text NOT NULL, answer text NOT NULL DEFAULT '',
    sources jsonb NOT NULL DEFAULT '[]',
    status text NOT NULL CHECK(status IN ('running','completed','failed','cancelled')),
    error text NOT NULL DEFAULT '', deadline timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
    UNIQUE(conversation_id, request_id)
);
CREATE INDEX IF NOT EXISTS turns_conversation_created ON turns(conversation_id,created_at,id);
CREATE TABLE IF NOT EXISTS data_imports (name text PRIMARY KEY, imported_at timestamptz NOT NULL DEFAULT now());
INSERT INTO schema_versions VALUES(1) ON CONFLICT DO NOTHING;
