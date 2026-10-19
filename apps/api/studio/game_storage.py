"""PostgreSQL is authoritative. Redis contains only versioned, expiring caches and leases."""
import hashlib
import json
import os
import re
import threading
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from redis import Redis, RedisError
from fastapi import HTTPException

from .knowledge import Knowledge
from .game_retrieval import RetrievalIndex, RetrievalOptions, VERSION, VECTOR_STRATEGIES


class GameStorage:
    def __init__(self, url=None, redis_url=None, schema=None):
        self.url = url or os.getenv('GAME_DATABASE_URL', 'postgresql://localhost/game_ops')
        self.schema = schema or os.getenv('GAME_DB_SCHEMA', 'game_ops')
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', self.schema):
            raise ValueError('Invalid GAME_DB_SCHEMA')
        self.redis = Redis.from_url(redis_url or os.getenv('GAME_REDIS_URL', 'redis://127.0.0.1:6379/0'),
                                    decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
        self.prefix = os.getenv('GAME_REDIS_PREFIX', 'game-ops') + ':' + self.schema + ':'
        self.pool = None
        self.guard = threading.Lock()

    def initialize(self, seeds):
        with self.guard:
            if self.pool:
                return
            # Migrations are transactional and serialized across API processes.
            with psycopg.connect(self.url, connect_timeout=3) as db:
                db.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('game-schema:' + self.schema,))
                db.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(self.schema)))
                db.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(self.schema)))
                db.execute((Path(__file__).parent / 'migrations/001_game.sql').read_text())
                if not db.execute("SELECT 1 FROM data_imports WHERE name='seeds-v1'").fetchone():
                    for doc in seeds:
                        db.execute('INSERT INTO documents(id,title,content) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', doc)
                    db.execute("INSERT INTO data_imports(name) VALUES('seeds-v1')")
                    db.execute('UPDATE knowledge_state SET revision=revision+1 WHERE id=1')
            self.pool = ConnectionPool(self.url, min_size=0, max_size=8, timeout=5, open=True,
                                       kwargs={'row_factory': dict_row, 'connect_timeout': 3,
                                               'options': '-c search_path=' + self.schema + ' -c statement_timeout=5000'},
                                       check=ConnectionPool.check_connection)

    def close(self):
        if self.pool:
            self.pool.close()
            self.pool = None
        self.redis.close()

    @contextmanager
    def connection(self):
        with self.pool.connection() as db:
            yield db

    def cache_get(self, key):
        try:
            raw = self.redis.get(self.prefix + key)
            return json.loads(raw) if raw else None
        except (RedisError, ValueError):
            return None

    def cache_set(self, key, value, ttl=900):
        try:
            self.redis.set(self.prefix + key, json.dumps(value, ensure_ascii=False), ex=ttl)
        except RedisError:
            pass  # Cache failure never discards persistent records.

    def lock(self, conversation_id):
        token = str(uuid.uuid4())
        try:
            if not self.redis.set(self.prefix + 'lock:' + str(conversation_id), token, nx=True, ex=120):
                raise HTTPException(409, '该咨询正在生成回答，请稍后重试')
        except RedisError:
            raise HTTPException(503, 'Redis 暂不可用，无法安全开启新的生成任务')
        return token

    def unlock(self, conversation_id, token):
        try:
            self.redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end",
                            1, self.prefix + 'lock:' + str(conversation_id), token)
        except RedisError:
            pass  # A lease expires; never delete another request's lease.

    def require(self, db, owner, conversation_id, lock=False):
        row = db.execute('SELECT * FROM conversations WHERE id=%s AND owner_id=%s' + (' FOR UPDATE' if lock else ''),
                         (conversation_id, owner)).fetchone()
        if not row:
            raise HTTPException(404, '咨询不存在')
        return row

    def new_conversation(self, owner):
        with self.connection() as db:
            row = db.execute('INSERT INTO conversations(id,owner_id) VALUES(%s,%s) RETURNING *',
                             (uuid.uuid4(), owner)).fetchone()
        return dict(row, messages=[])

    def conversations(self, owner):
        with self.connection() as db:
            return db.execute('SELECT id,title,created_at,updated_at FROM conversations WHERE owner_id=%s ORDER BY updated_at DESC LIMIT 100', (owner,)).fetchall()

    def expire_turns(self, db, conversation_id):
        db.execute("UPDATE turns SET status='failed', error='生成任务中断或超时，请重新提问', finished_at=now() WHERE conversation_id=%s AND status='running' AND deadline<now()", (conversation_id,))

    @staticmethod
    def messages(turns):
        messages = []
        for turn in turns:
            messages.append({'role': 'user', 'content': turn['question']})
            messages.append({'role': 'assistant', 'content': turn['answer'], 'sources': turn['sources'],
                             'complete': turn['status'] == 'completed', 'status': turn['status'], 'error': turn['error']})
        return messages

    def conversation(self, owner, conversation_id):
        with self.connection() as db:
            row = self.require(db, owner, conversation_id)
            self.expire_turns(db, conversation_id)
            turns = db.execute('SELECT * FROM (SELECT * FROM turns WHERE conversation_id=%s ORDER BY created_at DESC,id DESC LIMIT 100) t ORDER BY created_at,id', (conversation_id,)).fetchall()
        return dict(row, messages=self.messages(turns))

    def delete_conversation(self, owner, conversation_id):
        with self.connection() as db:
            self.require(db, owner, conversation_id, lock=True)
            self.expire_turns(db, conversation_id)
            if db.execute("SELECT 1 FROM turns WHERE conversation_id=%s AND status='running'", (conversation_id,)).fetchone():
                raise HTTPException(409, '回答生成中，请停止或等待完成后删除')
            db.execute('DELETE FROM conversations WHERE id=%s', (conversation_id,))
        # Ownership and existence are always checked in PostgreSQL before cache reads.
        try:
            for key in self.redis.scan_iter(match=self.prefix + 'context:' + str(conversation_id) + ':*', count=100):
                self.redis.delete(key)
        except RedisError:
            pass

    def start(self, owner, conversation_id, request_id, question):
        with self.connection() as db:
            self.require(db, owner, conversation_id, lock=True)
            self.expire_turns(db, conversation_id)
            existing = db.execute('SELECT * FROM turns WHERE conversation_id=%s AND request_id=%s', (conversation_id, request_id)).fetchone()
            if existing:
                if existing['question'] != question:
                    raise HTTPException(409, '同一 request_id 不能用于不同问题')
                if existing['status'] != 'completed':
                    raise HTTPException(409, '该请求已受理或已中断，请读取咨询记录；重新提问须使用新的 request_id')
                return existing, True
            if db.execute("SELECT 1 FROM turns WHERE conversation_id=%s AND status='running'", (conversation_id,)).fetchone():
                raise HTTPException(409, '该咨询已有生成任务')
            row = db.execute("INSERT INTO turns(id,conversation_id,request_id,question,status,deadline) VALUES(%s,%s,%s,%s,'running',now()+interval '120 seconds') RETURNING *",
                             (uuid.uuid4(), conversation_id, request_id, question)).fetchone()
            db.execute('UPDATE conversations SET title=%s,updated_at=now() WHERE id=%s', (question[:24], conversation_id))
        return row, False

    def finish(self, turn_id, status, answer, sources, error=''):
        with self.connection() as db:
            # Lock in the same order as start/delete to avoid deadlocks.
            turn = db.execute('SELECT conversation_id FROM turns WHERE id=%s', (turn_id,)).fetchone()
            if not turn:
                return False
            db.execute('SELECT id FROM conversations WHERE id=%s FOR UPDATE', (turn['conversation_id'],))
            row = db.execute("UPDATE turns SET status=%s,answer=%s,sources=%s,error=%s,finished_at=now() WHERE id=%s AND status='running' RETURNING conversation_id",
                             (status, answer, Jsonb(sources), error, turn_id)).fetchone()
            if row:
                db.execute('UPDATE conversations SET revision=revision+1,updated_at=now() WHERE id=%s', (row['conversation_id'],))
        return row is not None

    def context(self, owner, conversation_id):
        with self.connection() as db:
            row = self.require(db, owner, conversation_id)
            key = 'context:' + str(conversation_id) + ':' + str(row['revision'])
            cached = self.cache_get(key)
            if cached is not None:
                return cached
            turns = db.execute("SELECT question,answer FROM turns WHERE conversation_id=%s AND status='completed' ORDER BY created_at DESC,id DESC LIMIT 10", (conversation_id,)).fetchall()
        pairs = [[{'role': 'user', 'content': t['question']}, {'role': 'assistant', 'content': t['answer']}] for t in reversed(turns)]
        self.cache_set(key, pairs)
        return pairs

    def documents(self):
        with self.connection() as db:
            return db.execute('SELECT id,title,content FROM documents ORDER BY created_at,id').fetchall()

    def add_document(self, title, content):
        doc_id = str(uuid.uuid4())
        with self.connection() as db:
            db.execute('INSERT INTO documents(id,title,content) VALUES(%s,%s,%s)', (doc_id, title, content))
            db.execute('UPDATE knowledge_state SET revision=revision+1 WHERE id=1')
        return doc_id

    def delete_document(self, doc_id):
        with self.connection() as db:
            if not db.execute('DELETE FROM documents WHERE id=%s RETURNING id', (doc_id,)).fetchone():
                raise HTTPException(404, '文档不存在')
            db.execute('UPDATE knowledge_state SET revision=revision+1 WHERE id=1')

    def knowledge_snapshot(self):
        # One SQL statement gives revision and documents the same MVCC snapshot.
        with self.connection() as db:
            row = db.execute("""SELECT revision, COALESCE(
                (SELECT jsonb_agg(jsonb_build_object('id',id,'title',title,'content',content) ORDER BY id)
                 FROM documents), '[]'::jsonb) AS documents FROM knowledge_state WHERE id=1""").fetchone()
        return row['revision'], row['documents']

    def retrieve(self, query, options=None):
        options = options or RetrievalOptions()
        revision, documents = self.knowledge_snapshot()
        embeddings = None
        if options.strategy in VECTOR_STRATEGIES:
            from .game_embeddings import get_embeddings
            embeddings = get_embeddings()
        payload = json.dumps([VERSION, query, options.model_dump(), embeddings.identity if embeddings else None],
                             sort_keys=True)
        key = 'search:' + str(revision) + ':' + hashlib.sha256(payload.encode()).hexdigest()
        result = self.cache_get(key)
        if result is not None:
            result['trace']['cache_hit'] = True
            return result
        vector_store = None
        if options.strategy in VECTOR_STRATEGIES and options.vector_backend == 'pgvector':
            from .game_pgvector import PgVectorStore
            vector_store = PgVectorStore(self)
        result = RetrievalIndex(documents, embeddings=embeddings, vector_store=vector_store).search(query, options)
        result['trace'].update(revision=revision, cache_hit=False)
        self.cache_set(key, result, ttl=300)
        return result

    def search(self, query):
        options = RetrievalOptions(strategy=os.getenv('GAME_RETRIEVAL_STRATEGY', 'bm25'),
                                   min_similarity=float(os.getenv('GAME_MIN_SIMILARITY', '.35')),
                                   vector_backend=os.getenv('GAME_VECTOR_BACKEND', 'pgvector'),
                                   vector_search_mode=os.getenv('GAME_VECTOR_SEARCH_MODE', 'exact'))
        return self.retrieve(query, options)['sources']

    def import_conversation(self, owner, legacy_id, title, messages):
        with self.connection() as db:
            row = db.execute('INSERT INTO conversations(id,owner_id,title,legacy_id) VALUES(%s,%s,%s,%s) ON CONFLICT(owner_id,legacy_id) DO NOTHING RETURNING id',
                             (uuid.uuid4(), owner, title, legacy_id)).fetchone()
            if not row:
                return {'imported': False}
            question = None
            for index, msg in enumerate(messages):
                if msg['role'] == 'user':
                    if question is not None:
                        self._import_turn(db, row['id'], question, {}, index)
                    question = msg['content']
                elif question is not None:
                    self._import_turn(db, row['id'], question, msg, index)
                    question = None
            if question is not None:
                self._import_turn(db, row['id'], question, {}, len(messages))
        return {'imported': True}

    @staticmethod
    def _import_turn(db, conversation_id, question, answer, index):
        complete = bool(answer.get('complete') and answer.get('content'))
        db.execute("INSERT INTO turns(id,conversation_id,request_id,question,answer,sources,status,error,created_at,finished_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,now()+%s*interval '1 microsecond',now())",
                   (uuid.uuid4(), conversation_id, uuid.uuid4(), question, answer.get('content', ''), Jsonb(answer.get('sources') or []),
                    'completed' if complete else 'cancelled', '' if complete else '旧咨询未完成的回答', index))


class StoredKnowledge(Knowledge):
    """Reuse lexical ranking without SQLite initialization or cross-request LRU state."""
    def __init__(self, repository):
        self.repository = repository
        self.cache = OrderedDict()

    def documents(self):
        return self.repository.documents()
