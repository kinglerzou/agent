"""SQLite persistence. Short transactions; WAL; parameterized queries."""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, session TEXT, status TEXT, payload TEXT,
                    answer TEXT DEFAULT '', created REAL, updated REAL,
                    attempts INTEGER DEFAULT 0, feedback INTEGER, error TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT, seq INTEGER, data TEXT, PRIMARY KEY(run_id, seq)
                );
                CREATE TABLE IF NOT EXISTS memories (
                    session TEXT, content TEXT, created REAL,
                    PRIMARY KEY(session, content)
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, title TEXT, content TEXT
                );
                CREATE INDEX IF NOT EXISTS runs_status ON runs(status, created);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, payload):
        run_id = str(uuid.uuid4())
        now = time.time()
        with self.connect() as db:
            db.execute('INSERT INTO runs(id,session,status,payload,created,updated) VALUES(?,?,?,?,?,?)',
                       (run_id, payload['session_id'], 'queued', json.dumps(payload), now, now))
        return run_id

    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM runs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE runs SET status='running', attempts=attempts+1, updated=? WHERE id=?",
                       (time.time(), row['id']))
            return dict(row)

    def recover(self):
        # Single worker process only. A process crash leaves running checkpoints for restart.
        with self.connect() as db:
            db.execute("UPDATE runs SET status='queued', updated=? WHERE status='running'", (time.time(),))

    def event(self, run_id, event):
        with self.connect() as db:
            seq = db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?', (run_id,)).fetchone()[0]
            event = dict(event, seq=seq, run_id=run_id, timestamp=time.time())
            db.execute('INSERT INTO events VALUES(?,?,?)', (run_id, seq, json.dumps(event, ensure_ascii=False)))
        return event

    def events(self, run_id):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT data FROM events WHERE run_id=? ORDER BY seq', (run_id,))]

    def finish(self, run_id, status, answer='', error=''):
        with self.connect() as db:
            db.execute("UPDATE runs SET status=?,answer=?,error=?,updated=? WHERE id=? AND status!='cancelled'",
                       (status, answer, error, time.time(), run_id))

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        return dict(row) if row else None

    def runs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM runs ORDER BY created DESC LIMIT 100')]

    def remember(self, session, content):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO memories VALUES(?,?,?)', (session, content, time.time()))
            db.execute('DELETE FROM memories WHERE session=? AND rowid NOT IN '
                       '(SELECT rowid FROM memories WHERE session=? ORDER BY created DESC LIMIT 20)', (session, session))

    def memories(self, session):
        with self.connect() as db:
            return [r[0] for r in db.execute('SELECT content FROM memories WHERE session=? ORDER BY created DESC', (session,))]

    def forget(self, session):
        with self.connect() as db:
            db.execute('DELETE FROM memories WHERE session=?', (session,))

    def feedback(self, run_id, score):
        with self.connect() as db:
            db.execute('UPDATE runs SET feedback=? WHERE id=?', (score, run_id))
