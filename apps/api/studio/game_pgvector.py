"""Immutable PostgreSQL vector snapshots; exact and HNSW cosine search.

The set ID includes corpus, model and chunking version. Every query filters by it.
An atomic insert transaction prevents readers observing a partial index generation.
"""
import json

import psycopg

from .game_embeddings import DIMENSION, EmbeddingUnavailable, normalize
from .game_retrieval import VERSION, fingerprint


class PgVectorUnavailable(EmbeddingUnavailable):
    pass


def vector_literal(vector):
    normalized = normalize(vector)
    if len(normalized) != DIMENSION:
        raise PgVectorUnavailable(f'pgvector 需要 {DIMENSION} 维向量，请检查 Embedding 模型')
    return json.dumps(normalized, allow_nan=False)


class PgVectorStore:
    def __init__(self, repository):
        self.repository = repository

    def _ready(self, db):
        row = db.execute("""SELECT e.extversion, n.nspname FROM pg_extension e
            JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'""").fetchone()
        if not row or row['nspname'] != 'public':
            raise PgVectorUnavailable('请先运行 npm run migrate:vector，在 public schema 启用 pgvector')
        if tuple(int(x) for x in row['extversion'].split('.')[:2]) < (0, 8):
            raise PgVectorUnavailable('需要 pgvector 0.8.0 或更新版本以支持 HNSW 迭代扫描')
        if not db.execute("SELECT to_regclass('rag_vectors') AS name").fetchone()['name']:
            raise PgVectorUnavailable('向量表尚未初始化，请运行 npm run migrate:vector')

    def ensure(self, index, backend):
        set_id = fingerprint([VERSION, index.corpus_hash, backend.identity])
        try:
            with self.repository.connection() as db:
                self._ready(db)
                if db.execute('SELECT 1 FROM rag_vector_sets WHERE id=%s', (set_id,)).fetchone():
                    return set_id
            # Compute outside the transaction/lock; a failed encoder leaves no partial generation.
            vectors = backend.encode([chunk['title'] + '\n' + chunk['content'] for chunk in index.chunks])
            if len(vectors) != len(index.chunks):
                raise PgVectorUnavailable('Embedding 数量与分块数不一致')
            records = [(set_id, chunk['id'], chunk['document_id'], chunk['title'], chunk['content'],
                        chunk['offset'], vector_literal(vector)) for chunk, vector in zip(index.chunks, vectors)]
            with self.repository.connection() as db:
                # Same snapshot writers serialize; a second writer can reuse the committed generation.
                db.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('rag-vector:' + set_id,))
                if db.execute('SELECT 1 FROM rag_vector_sets WHERE id=%s', (set_id,)).fetchone():
                    return set_id
                db.execute('INSERT INTO rag_vector_sets(id,corpus_hash,model_identity,retrieval_version,chunk_count) VALUES(%s,%s,%s,%s,%s)',
                           (set_id, index.corpus_hash, backend.identity, VERSION, len(records)))
                with db.cursor() as cursor:
                    cursor.executemany('''INSERT INTO rag_vectors
                        (set_id,chunk_id,document_id,title,content,chunk_offset,embedding)
                        VALUES(%s,%s,%s,%s,%s,%s,%s::public.vector)''', records)
            return set_id
        except psycopg.Error as exc:
            raise PgVectorUnavailable('pgvector 索引准备失败，请检查迁移、数据库权限与连接') from exc

    def search(self, set_id, vector, options):
        literal = vector_literal(vector)
        limit = options.candidate_k
        try:
            with self.repository.connection() as db:
                if options.vector_search_mode == 'exact':
                    # Disable ANN index scans for a genuinely exact reference baseline.
                    db.execute('SET LOCAL enable_indexscan=off')
                    db.execute('SET LOCAL enable_indexonlyscan=off')
                else:
                    db.execute("SET LOCAL hnsw.iterative_scan='strict_order'")
                    db.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(max(100, limit)),))
                # Keep ORDER BY as the distance operator so the planner can use HNSW.
                tie_break = ', chunk_id' if options.vector_search_mode == 'exact' else ''
                rows = db.execute('''SELECT chunk_id AS id, document_id, title, content,
                    chunk_offset AS offset, 1-(embedding OPERATOR(public.<=>) %s::public.vector) AS score
                    FROM rag_vectors WHERE set_id=%s
                    ORDER BY embedding OPERATOR(public.<=>) %s::public.vector''' + tie_break + ' LIMIT %s',
                                  (literal, set_id, literal, limit)).fetchall()
            sources = [dict(row, score=round(max(-1., min(1., row['score'])), 6),
                            vector_score=round(max(-1., min(1., row['score'])), 6), matched_terms=[])
                       for row in rows if row['score'] >= options.min_similarity]
            sources.sort(key=lambda source: (-source['score'], source['id']))
            return sources
        except psycopg.Error as exc:
            raise PgVectorUnavailable('pgvector 查询失败，请检查数据库和向量索引') from exc
