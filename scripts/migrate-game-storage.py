"""Idempotent, non-destructive SQLite knowledge migration. Env is loaded by npm script."""
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/api'))
from studio.game_storage import GameStorage
from studio.game import SEEDS

source = Path(os.getenv('GAME_LEGACY_DB', 'data/game.sqlite3')).resolve()
store = GameStorage()
try:
    exists = source.is_file()
    store.initialize([] if exists else SEEDS)
    rows = []
    if exists:
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as db:
            rows = db.execute('SELECT id,title,content FROM documents').fetchall()
    with store.connection() as db:
        db.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('game-import:' + store.schema,))
        imported = db.execute("SELECT 1 FROM data_imports WHERE name='sqlite-knowledge-v1'").fetchone()
        if not imported:
            for row in rows:
                db.execute('INSERT INTO documents(id,title,content) VALUES(%s,%s,%s) ON CONFLICT(id) DO NOTHING', row)
            db.execute("INSERT INTO data_imports(name) VALUES('sqlite-knowledge-v1')")
            db.execute('UPDATE knowledge_state SET revision=revision+1 WHERE id=1')
    print('Knowledge migration: already applied' if imported else f'Knowledge migration complete: {len(rows)} source documents; SQLite preserved')
    print('Redis: connected' if store.redis.ping() else 'Redis: unavailable')
finally:
    store.close()
