"""Retrieval benchmark with optional PostgreSQL pgvector backend."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/api'))
from studio.game_rag_eval import EvalRequest, evaluate  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--top-k', type=int, default=4)
parser.add_argument('--min-score', type=float, default=0)
parser.add_argument('--output', type=Path)
parser.add_argument('--backend', choices=['local', 'pgvector'], default='local')
parser.add_argument('--search-mode', choices=['exact', 'hnsw'], default='exact')
parser.add_argument('--with-vectors', action='store_true')
parser.add_argument('--min-similarity', type=float, default=.35)
args = parser.parse_args()
strategies = ['bm25', 'expanded_bm25'] + (['vector', 'hybrid'] if args.with_vectors else [])
request = EvalRequest(top_k=args.top_k, min_score=args.min_score,
                      min_similarity=args.min_similarity, strategies=strategies,
                      vector_backend=args.backend, vector_search_mode=args.search_mode)
storage = None
try:
    vector_store = None
    if args.backend == 'pgvector' and args.with_vectors:
        from studio.game_storage import GameStorage
        from studio.game import SEEDS
        from studio.game_pgvector import PgVectorStore
        storage = GameStorage()
        storage.initialize(SEEDS)
        vector_store = PgVectorStore(storage)
    report = evaluate(request, vector_store=vector_store)
finally:
    if storage:
        storage.close()
serialized = json.dumps(report, ensure_ascii=False, indent=2)
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized + '\n')
print(json.dumps({r['strategy']: r['summary'] for r in report['reports']}, ensure_ascii=False, indent=2))
