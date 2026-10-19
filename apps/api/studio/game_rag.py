"""Local retrieval inspection/evaluation. No model provider is called."""
from fastapi import Depends, HTTPException

from .game_embeddings import EmbeddingUnavailable
from .game_retrieval import SearchRequest, RetrievalOptions, VECTOR_STRATEGIES
from .game_pgvector import PgVectorStore
from .game_rag_eval import EvalRequest, evaluate, fixture


def attach_rag_routes(router, repository):
    @router.post('/retrieval/search')
    def search(body: SearchRequest, repo=Depends(repository)):
        try:
            return repo.retrieve(body.query, RetrievalOptions(**body.model_dump(exclude={'query'})))
        except EmbeddingUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.get('/retrieval/dataset')
    def dataset():
        return fixture()

    @router.post('/retrieval/evaluate')
    def run(body: EvalRequest):
        # The fixed fixture can run without PostgreSQL/Redis or model credentials.
        documents, revision = None, None
        if body.corpus == 'current':
            revision, documents = repository().knowledge_snapshot()
        try:
            vector_store = None
            if body.vector_backend == 'pgvector' and any(s in VECTOR_STRATEGIES for s in body.strategies):
                vector_store = PgVectorStore(repository())
            return evaluate(body, documents, revision, vector_store=vector_store)
        except EmbeddingUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
