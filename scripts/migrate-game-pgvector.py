"""Explicit, idempotent pgvector setup for the configured game's PostgreSQL database."""
import sys
import argparse
from pathlib import Path

root = Path(__file__).resolve().parents[1]
api_root = root / 'apps/api' if (root / 'apps/api').exists() else root
sys.path.insert(0, str(api_root))
from studio.game_storage import GameStorage  # noqa: E402
from studio.game import SEEDS  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--build-index', action='store_true', help='Embed and persist the current knowledge snapshot')
args = parser.parse_args()

storage = GameStorage()
try:
    storage.initialize(SEEDS)
    with storage.connection() as db:
        db.execute("SELECT pg_advisory_xact_lock(hashtext('game-pgvector-extension'))")
        db.execute('CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public')
        row = db.execute("""SELECT extversion, nspname FROM pg_extension e
            JOIN pg_namespace n ON n.oid=e.extnamespace WHERE extname='vector'""").fetchone()
        if row['nspname'] != 'public' or tuple(int(v) for v in row['extversion'].split('.')[:2]) < (0, 8):
            raise RuntimeError('pgvector 必须位于 public schema，版本 >= 0.8.0')
        db.execute((api_root / 'studio/migrations/002_game_vectors.sql').read_text())
    print('pgvector', row['extversion'], 'ready; vector(384) tables and HNSW index created in', storage.schema)
    if args.build_index:
        from studio.game_embeddings import get_embeddings
        from studio.game_pgvector import PgVectorStore
        from studio.game_retrieval import RetrievalIndex
        revision, documents = storage.knowledge_snapshot()
        index = RetrievalIndex(documents, get_embeddings(), PgVectorStore(storage))
        index.prepare_vectors()
        print('Indexed knowledge revision', revision, 'with', len(index.chunks), 'chunks; snapshot', index.vector_set_id)
finally:
    storage.close()
