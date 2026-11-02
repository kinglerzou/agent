"""Graph tests do not need network services or model credentials."""
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from studio.game_review import ReviewDecision, review_graph


@pytest.mark.parametrize('decision,status,answer', [
    ({'action': 'approve'}, 'completed', '原草稿 [1]'),
    ({'action': 'edit', 'answer': '修订回答 [1]'}, 'completed', '修订回答 [1]'),
    ({'action': 'reject', 'comment': '证据不足'}, 'rejected', '原草稿 [1]'),
])
def test_pause_and_resume_new_graph(decision, status, answer):
    saver = InMemorySaver()
    config = {'configurable': {'thread_id': 'turn-1'}}
    graph = review_graph(saver)
    state = graph.invoke({'question': '问题', 'draft': '原草稿 [1]', 'sources': [{'id': 'doc'}]}, config)
    assert state['status'] == 'pending_review'
    assert state['__interrupt__'][0].value['draft'] == '原草稿 [1]'
    assert 'answer' not in state
    assert graph.get_state(config).next == ('human_review',)
    # Rebuild graph: resumption must depend on the checkpoint, not the graph instance.
    restored = review_graph(saver)
    result = restored.invoke(Command(resume=decision), config)
    assert result['status'] == status
    assert result['answer'] == answer
    assert restored.get_state(config).next == ()


@pytest.mark.parametrize('payload', [
    {'action': 'edit', 'answer': '  '}, {'action': 'reject', 'comment': ' '},
    {'action': 'approve', 'answer': '不能偷偷改写'}, {'action': 'unknown'},
    {'action': 'approve', 'reviewer': 'forged'},
])
def test_invalid_decision(payload):
    with pytest.raises(ValidationError):
        ReviewDecision.model_validate(payload)
