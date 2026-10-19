"""Explicit model download and local inference smoke test. No API key needed."""
import os
import sys

# Standard HTTP supports reliable resume on networks without Xet connectivity.
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT', '30')
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'apps/api' if (root / 'apps/api').exists() else root))
from studio.game_embeddings import LocalEmbeddings, settings  # noqa: E402

backend = LocalEmbeddings(settings(), download=True)
vectors = backend.encode(['礼包领取失败检查库存', '首页轮播图无法显示'])
print('Model:', backend.identity)
print('Ready:', len(vectors), 'vectors,', len(vectors[0]), 'dimensions')
print('Local cache:', settings())
