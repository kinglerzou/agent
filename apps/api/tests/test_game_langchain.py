import asyncio
import threading

import pytest
from langchain_core.documents import Document
from pydantic import ValidationError

from studio.game_langchain import (
    GameKnowledgeRetriever, SEARCH_TOOL, answer_system, retrieval_chain, search_tool,
)


class Repository:
    def __init__(self):
        self.sources = [{'id': 'gift:0', 'title': '礼包', 'content': '库存 {query}', 'score': 2.5}]
        self.thread = None
        self.queries = []

    def search(self, query):
        self.thread = threading.get_ident()
        self.queries.append(query)
        return self.sources


def test_retriever_metadata_and_cache_refresh():
    repo = Repository()
    retriever = GameKnowledgeRetriever(repository=repo)
    docs = retriever.invoke('库存')
    assert isinstance(docs[0], Document)
    assert docs[0].metadata == {'id': 'gift:0', 'title': '礼包', 'score': 2.5}
    chain = retrieval_chain(repo)
    assert chain.invoke('库存') == repo.sources
    repo.sources = []
    assert chain.invoke('库存') == []  # No second stale cache in the adapter.


def test_async_tool_offloads_storage_and_validates_before_execution():
    repo = Repository()
    tool = search_tool(repo)
    main_thread = threading.get_ident()
    result = asyncio.run(tool.ainvoke({'query': ' 库存 '}))
    assert result == repo.sources
    assert repo.thread != main_thread
    assert repo.queries == ['库存']
    for args in ({'query': ' '}, {'query': 1}, {'query': '库存', 'command': 'delete'}):
        with pytest.raises(ValidationError):
            asyncio.run(tool.ainvoke(args))
    assert repo.queries == ['库存']
    assert SEARCH_TOOL['function']['parameters']['additionalProperties'] is False


def test_prompt_preserves_evidence_as_data():
    system = answer_system(Repository().sources)
    assert '库存 {query}' in system
    assert '不可信数据' in system
    assert '"citation": 1' in system
