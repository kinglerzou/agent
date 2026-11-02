"""Durable LangGraph workflow for reviewing a generated answer before publication."""
from typing import Literal
from typing_extensions import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['approve', 'edit', 'reject']
    answer: str = Field(default='', max_length=24000)
    comment: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def validate_decision(self):
        if self.action == 'edit' and not self.answer.strip():
            raise ValueError('修改后通过必须填写回答')
        if self.action != 'edit' and self.answer:
            raise ValueError('仅修改后通过可以提交新回答')
        if self.action == 'reject' and not self.comment.strip():
            raise ValueError('驳回时请填写原因')
        return self


class ReviewState(TypedDict, total=False):
    question: str
    draft: str
    sources: list
    decision: dict
    answer: str
    status: str


def draft_ready(state: ReviewState):
    return {'status': 'pending_review'}


def human_review(state: ReviewState):
    # No side effects before interrupt: LangGraph re-runs this node on resume.
    decision = interrupt({'question': state['question'], 'draft': state['draft'],
                          'sources': state['sources'], 'actions': ['approve', 'edit', 'reject']})
    return {'decision': ReviewDecision.model_validate(decision).model_dump()}


def publish(state: ReviewState):
    decision = state['decision']
    return {'status': 'completed', 'answer': decision['answer'] if decision['action'] == 'edit' else state['draft']}


def reject(state: ReviewState):
    return {'status': 'rejected', 'answer': state['draft']}


def review_graph(checkpointer):
    graph = StateGraph(ReviewState)
    graph.add_node('draft_ready', draft_ready)
    graph.add_node('human_review', human_review)
    graph.add_node('publish', publish)
    graph.add_node('reject', reject)
    graph.add_edge(START, 'draft_ready')
    graph.add_edge('draft_ready', 'human_review')
    graph.add_conditional_edges('human_review',
                                lambda state: 'reject' if state['decision']['action'] == 'reject' else 'publish')
    graph.add_edge('publish', END)
    graph.add_edge('reject', END)
    return graph.compile(checkpointer=checkpointer)
