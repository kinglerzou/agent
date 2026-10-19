"""Game operations RAG. Real OpenAI-compatible gateway; no fabricated fallback."""
import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

import anyio
import psycopg
from psycopg_pool import PoolTimeout
from redis import RedisError

import httpx
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from .game_storage import GameStorage
from .game_rag import attach_rag_routes
from .game_tools import plan_search, tool_result
from .game_langchain import answer_system, retrieval_chain, search_tool


@asynccontextmanager
async def aclosing(iterator):
    """Close nested generators on disconnect, including on Python 3.9."""
    try:
        yield iterator
    finally:
        await iterator.aclose()


SEEDS = [
 ('game-banner', '【示例】首页 Banner 配置与不展示排查', '本文为演示流程，不代表内部真实规则。配置首页 Banner 时，确认目标游戏、投放渠道、客户端版本、素材比例、跳转链接、开始结束时间以及发布状态。先在测试环境预览，校验跳转落地页，再按内部审批流程发布。上线后不展示时，依次核对当前时间是否在投放区间、渠道及版本是否命中、人群条件是否匹配、素材是否通过审核、配置是否已发布，以及客户端缓存。请提供活动 ID、渠道、客户端版本和脱敏截图以进一步定位。'),
 ('game-gift', '【示例】礼包配置与领取失败', '本文为演示流程。礼包配置需核对游戏 ID、礼包名称、有效期、库存、领取次数限制、人群范围和兑换说明。测试领取与兑换成功后再发布。领取失败时先检查礼包是否在有效期、库存是否耗尽、用户是否已领取、账号是否命中渠道及人群条件。领取成功但兑换失败，应核对兑换码有效期、适用区服和使用状态；不要在聊天中提交完整兑换码或用户个人信息。实际次数和库存策略以内部文档为准。'),
 ('game-activity', '【示例】活动上线检查与下线回滚', '本文为演示流程。活动上线前检查活动 ID、游戏关联、投放时间及时区、渠道白名单、版本范围、人群条件、资源素材、跳转链接和奖励配置。在测试环境完成展示、参与、领奖链路验收，按内部审批流程发布。异常下线时记录活动 ID、异常发生时间与影响范围，按内部权限流程暂停投放或恢复已审核的上一版配置，并复核客户端展示；无法确认奖励影响时联系对应业务负责人。助手仅提供查询建议，不直接修改线上配置。'),
 ('game-channel', '【示例】渠道、版本与灰度人群', '本文为演示流程。投放条件可能同时包含渠道、客户端版本、登录状态和灰度人群。排查配置不生效时，逐项对照测试账号实际渠道与版本，检查是否满足全部条件。灰度发布先用测试白名单验证，再按内部规范扩大范围。不要假设所有渠道共用相同配置；缺少渠道编号或版本信息时应补充信息。具体优先级、比例与生效延迟必须依据内部业务文档。'),
]


class GameMessage(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=6000)


class GameChat(BaseModel):
    tool_calling: bool = False
    conversation_id: UUID
    request_id: UUID
    message: str = Field(min_length=1, max_length=6000)

    @model_validator(mode='after')
    def check(self):
        if not self.message.strip():
            raise ValueError('问题不能为空')
        return self


class LegacySource(BaseModel):
    id: str = Field(max_length=200)
    title: str = Field(max_length=100)
    content: str = Field(max_length=20000)


class LegacyMessage(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(max_length=24000)
    complete: bool = False
    sources: list[LegacySource] = Field(default_factory=list, max_length=5)


class LegacyConversation(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=100)
    messages: list[LegacyMessage] = Field(max_length=500)


class GameDocument(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=20000)

    @model_validator(mode='after')
    def check(self):
        if not self.title.strip() or not self.content.strip():
            raise ValueError('标题和正文不能为空')
        return self


def model_config():
    return { 'base_url': os.getenv('GAME_LLM_BASE_URL', '').rstrip('/'),
             'model': os.getenv('GAME_LLM_MODEL', ''),
             'key': os.getenv('GAME_LLM_API_KEY', '') }


def encode(event):
    return 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'


async def model_tokens(config, messages):
    headers = {'Authorization': 'Bearer ' + config['key']} if config['key'] else {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10)) as client:
        async with client.stream('POST', config['base_url'] + '/chat/completions', headers=headers,
                                 json={'model': config['model'], 'messages': messages, 'stream': True}) as response:
            if response.status_code != 200:
                raise RuntimeError(f'模型服务返回 HTTP {response.status_code}，请检查服务端配置或额度')
            async for line in response.aiter_lines():
                if not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    return
                if not data:
                    continue
                event = json.loads(data)
                if event.get('error'):
                    raise RuntimeError('模型服务报告错误，请检查服务端配置')
                for choice in event.get('choices', []):
                    if choice.get('finish_reason') in ('length', 'content_filter'):
                        raise RuntimeError('回答因长度限制或模型策略中断，请缩小问题范围后重试')
                    token = choice.get('delta', {}).get('content')
                    if isinstance(token, str) and token:
                        yield token
            raise RuntimeError('模型连接提前结束，请重试')


def build_context(pairs, question, budget=12000):
    recent = [{'role': 'user', 'content': question}]
    remaining = budget - len(question)
    for pair in reversed(pairs):
        size = sum(len(m['content']) for m in pair)
        if size > remaining:
            break
        recent = pair + recent
        remaining -= size
    return recent


def create_game_router():
    storage = GameStorage()

    @asynccontextmanager
    async def lifespan(app):
        yield
        await asyncio.to_thread(storage.close)

    router = APIRouter(prefix='/api/game', lifespan=lifespan)
    active = 0

    def repository():
        try:
            storage.initialize(SEEDS)
        except (psycopg.Error, PoolTimeout):
            raise HTTPException(503, 'PostgreSQL 连接失败，请检查 GAME_DATABASE_URL')
        return storage

    attach_rag_routes(router, repository)

    def owner():
        # Local single-operator identity. Replace with verified SSO identity before multi-user deployment.
        return os.getenv('GAME_OWNER_ID', 'local-operator')

    @router.get('/status')
    def status(repo=Depends(repository)):
        c = model_config()
        try:
            redis_ok = bool(repo.redis.ping())
        except RedisError:
            redis_ok = False
        return {'configured': bool(c['base_url'] and c['model']), 'model': c['model'],
                'documents': len(repo.documents()), 'retrieval': os.getenv('GAME_RETRIEVAL_STRATEGY', 'bm25'), 'orchestration': 'LangChain',
                'storage': 'PostgreSQL', 'redis': 'connected' if redis_ok else 'unavailable'}

    @router.get('/conversations')
    def conversations(repo=Depends(repository), user=Depends(owner)):
        return repo.conversations(user)

    @router.post('/conversations', status_code=201)
    def new_conversation(repo=Depends(repository), user=Depends(owner)):
        return repo.new_conversation(user)

    @router.post('/conversations/import')
    def import_conversation(body: LegacyConversation, repo=Depends(repository), user=Depends(owner)):
        return repo.import_conversation(user, body.id, body.title, [m.model_dump() for m in body.messages])

    @router.get('/conversations/{conversation_id}')
    def conversation(conversation_id: UUID, repo=Depends(repository), user=Depends(owner)):
        return repo.conversation(user, conversation_id)

    @router.delete('/conversations/{conversation_id}')
    def delete_conversation(conversation_id: UUID, repo=Depends(repository), user=Depends(owner)):
        repo.delete_conversation(user, conversation_id)
        return {'deleted': True}

    @router.get('/knowledge')
    def documents(repo=Depends(repository)):
        return repo.documents()

    @router.post('/knowledge', status_code=201)
    def add(doc: GameDocument, repo=Depends(repository)):
        return {'id': repo.add_document(doc.title, doc.content)}

    @router.delete('/knowledge/{doc_id}')
    def delete(doc_id: str, repo=Depends(repository)):
        repo.delete_document(doc_id)
        return {'deleted': True}

    @router.post('/chat')
    async def chat(body: GameChat, repo=Depends(repository), user=Depends(owner)):
        nonlocal active
        c = model_config()
        if not c['base_url'] or not c['model']:
            raise HTTPException(503, '尚未配置已有模型：请在服务端设置 GAME_LLM_BASE_URL 和 GAME_LLM_MODEL')
        if active >= 8:
            raise HTTPException(429, '当前咨询较多，请稍后重试')
        active += 1
        token = None
        try:
            # Check ownership before touching another conversation's Redis lease.
            await asyncio.to_thread(repo.conversation, user, body.conversation_id)
            token = await asyncio.to_thread(repo.lock, body.conversation_id)
            turn, replay = await asyncio.to_thread(repo.start, user, body.conversation_id, body.request_id, body.message)
        except BaseException:
            active -= 1
            if token:
                await asyncio.to_thread(repo.unlock, body.conversation_id, token)
            raise

        async def stream():
            nonlocal active
            answer, sources, outcome, error = '', [], 'cancelled', '已停止生成'
            try:
                if replay:
                    yield encode({'type': 'sources', 'sources': turn['sources']})
                    yield encode({'type': 'token', 'text': turn['answer']})
                    yield encode({'type': 'done', 'request_id': str(body.request_id)})
                    return
                yield encode({'type': 'status', 'message': '正在读取服务端上下文并通过 LangChain 检索知识库'})
                deadline = asyncio.get_running_loop().time() + 90
                pairs = await asyncio.to_thread(repo.context, user, body.conversation_id)
                question = body.message
                recent = build_context(pairs, question)
                query = question
                if len(question) < 30 and pairs:
                    query = pairs[-1][0]['content'][-1000:] + ' ' + question
                tool_messages = []
                if body.tool_calling:
                    yield encode({'type': 'status', 'message': '模型正在选择知识检索参数'})
                    assistant, call_id, query = await plan_search(c, recent)
                    yield encode({'type': 'tool_call', 'name': 'search_knowledge', 'query': query})
                if body.tool_calling:
                    sources = await search_tool(repo).ainvoke({'query': query})
                else:
                    sources = await retrieval_chain(repo).ainvoke(query)
                if body.tool_calling:
                    tool_messages = [assistant, tool_result(call_id, sources)]
                    yield encode({'type': 'tool_result', 'count': len(sources)})
                yield encode({'type': 'sources', 'sources': sources})
                if not sources:
                    answer = '知识库暂无足够依据回答这个问题。请补充业务模块、活动或配置 ID、渠道和客户端版本，或导入相关内部操作文档；必要时转交业务负责人确认。'
                    yield encode({'type': 'token', 'text': answer})
                else:
                    system = answer_system(sources)
                    yield encode({'type': 'status', 'message': '已检索到依据，模型正在生成回答'})
                    async with aclosing(model_tokens(c, [{'role': 'system', 'content': system}] + recent + tool_messages)) as iterator:
                        while True:
                            try:
                                text = await asyncio.wait_for(iterator.__anext__(), max(.01, deadline - asyncio.get_running_loop().time()))
                            except StopAsyncIteration:
                                break
                            answer += text
                            if len(answer) > 24000:
                                raise RuntimeError('回答超过长度预算，请缩小问题范围')
                            yield encode({'type': 'token', 'text': text})
                    if not answer:
                        raise RuntimeError('模型未返回正文，请检查模型是否支持文本流式回答')
                # Never announce success until the authoritative database commit succeeds.
                saved = await asyncio.to_thread(repo.finish, turn['id'], 'completed', answer, sources)
                if not saved:
                    raise RuntimeError('该生成任务已过期，请重新读取咨询记录')
                outcome = 'completed'
                yield encode({'type': 'done', 'request_id': str(body.request_id)})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                outcome = 'failed'
                if isinstance(exc, RuntimeError):
                    error = str(exc)
                elif isinstance(exc, (httpx.HTTPError, asyncio.TimeoutError)):
                    error = '模型连接失败或超时，请检查服务地址后重试'
                else:
                    error = '生成或保存失败，请稍后重新读取咨询记录'
                yield encode({'type': 'error', 'message': error})
            finally:
                # Starlette cancels the stream on disconnect; shield durable cleanup from its cancel scope.
                with anyio.CancelScope(shield=True):
                    try:
                        if not replay and outcome != 'completed':
                            await asyncio.to_thread(repo.finish, turn['id'], outcome, answer, sources, error)
                    finally:
                        await asyncio.to_thread(repo.unlock, body.conversation_id, token)
                        active -= 1
        return StreamingResponse(stream(), media_type='text/event-stream', headers={
            'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    return router
