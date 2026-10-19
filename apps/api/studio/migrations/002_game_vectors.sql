-- Run explicitly with scripts/migrate-game-pgvector.py after enabling vector in public.
CREATE TABLE IF NOT EXISTS rag_vector_sets (
    id text PRIMARY KEY,
    corpus_hash text NOT NULL,
    model_identity text NOT NULL,
    retrieval_version text NOT NULL,
    chunk_count integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS rag_vectors (
    set_id text NOT NULL REFERENCES rag_vector_sets(id) ON DELETE CASCADE,
    chunk_id text NOT NULL,
    document_id text NOT NULL,
    title text NOT NULL,
    content text NOT NULL,
    chunk_offset integer NOT NULL,
    embedding public.vector(384) NOT NULL,
    PRIMARY KEY (set_id, chunk_id)
);
CREATE INDEX IF NOT EXISTS rag_vectors_cosine_hnsw
    ON rag_vectors USING hnsw (embedding public.vector_cosine_ops)
    WITH (m=16, ef_construction=64);
INSERT INTO schema_versions VALUES(2) ON CONFLICT DO NOTHING;
