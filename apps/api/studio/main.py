import asyncio
import json
import os
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from .game import create_game_router
from .evaluation import evaluate
from .knowledge import Knowledge
from .runtime import Runtime
from .sandbox import calculate
from .store import Store
from .runtime_demo import DemoRuntime, Conflict
from .runtime_demo.api import create_demo_router


class Message(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=8000)


class Chat(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=20)
    session_id: str = Field(default='default', pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    mode: Literal['react', 'plan', 'multi'] = 'react'
    max_steps: int = Field(default=6, ge=1, le=12)
    context_budget: int = Field(default=12000, ge=1000, le=32000)
    top_k: int = Field(default=3, ge=1, le=5)
    fault: Literal['none', 'tool_error'] = 'none'

    @model_validator(mode='after')
    def validate_history(self):
        if self.messages[-1].role != 'user' or any(not m.content.strip() for m in self.messages):
            raise ValueError('末条必须为用户消息，内容不得为空白')
        if len(self.messages[-1].content) > self.context_budget:
            raise ValueError('问题长度超过上下文预算')
        return self


class Document(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=20000)


class Feedback(BaseModel):
    score: Literal[-1, 1]


def create_app(db_path=None):
    store = Store(db_path or os.environ.get('STUDIO_DB', 'data/studio.sqlite3'))
    knowledge = Knowledge(store)
    runtime = Runtime(store, knowledge)
    demo = DemoRuntime(str(Path(store.path).with_name('runtime-demo.sqlite3')))

    async def demo_worker():
        while True:
            for run in demo.scheduled():
                if run['auto'] and run['status'] == 'ready':
                    try:
                        demo.mutate(run['id'], 'step', version=run['version'])
                    except Conflict:
                        pass
            await asyncio.sleep(.6)

    async def execute(run_id, payload):
        answer = ''
        try:
            async for event in runtime.execute(payload):
                if store.get(run_id)['status'] == 'cancelled':
                    return
                store.event(run_id, event)
                if event['type'] == 'token':
                    answer += event['text']
            store.finish(run_id, 'completed', answer)
        except asyncio.CancelledError:
            store.event(run_id, {'type': 'error', 'message': '执行中断；后台任务将在重启后重新执行'})
            raise
        except Exception as exc:
            store.event(run_id, {'type': 'error', 'message': str(exc)})
            store.finish(run_id, 'failed', answer, str(exc))

    async def worker():
        while True:
            row = store.claim()
            if row:
                try:
                    await asyncio.wait_for(execute(row['id'], json.loads(row['payload'])), timeout=30)
                except asyncio.TimeoutError:
                    store.finish(row['id'], 'failed', error='任务超过 30 秒预算')
            else:
                await asyncio.sleep(.1)

    @asynccontextmanager
    async def lifespan(app):
        store.recover()
        task = asyncio.create_task(worker())
        demo_task = asyncio.create_task(demo_worker())
        yield
        demo_task.cancel()
        with suppress(asyncio.CancelledError):
            await demo_task
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title='Agent Engineering Studio', version='1.0.0', lifespan=lifespan)
    app.include_router(create_demo_router(demo))
    app.state.demo_runtime = demo
    app.include_router(create_game_router())
    app.state.store = store
    app.state.runtime = runtime
    app.state.active_streams = 0
    app.state.evaluating = False

    @app.middleware('http')
    async def request_limits(request: Request, call_next):
        # Enforce the actual body size, including chunked transfer requests.
        if request.method in ('POST', 'PUT', 'PATCH'):
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 220000:
                    return Response('request too large', status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def require_run(run_id):
        row = store.get(run_id)
        if not row:
            raise HTTPException(404, '任务不存在')
        return row

    def enqueue(payload):
        with store.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0]
        if count >= 32:
            raise HTTPException(429, '任务队列已满')
        return store.create(payload)

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'provider': 'mock', 'model': 'Python Mock / deterministic', 'runtime': 'python'}

    @app.get('/api/knowledge')
    def documents():
        return knowledge.documents()

    @app.post('/api/knowledge', status_code=201)
    def add_document(doc: Document):
        return {'id': knowledge.add(doc.title, doc.content)}

    @app.get('/api/search')
    def search(q: str = ''):
        if not 1 <= len(q) <= 8000:
            raise HTTPException(422, '查询长度必须为 1–8000')
        return knowledge.search(q)

    @app.post('/api/chat')
    async def chat(body: Chat, request: Request):
        if app.state.active_streams >= 8:
            raise HTTPException(429, '流式连接达到上限')
        run_id = enqueue(body.model_dump())
        app.state.active_streams += 1

        async def stream():
            last = 0
            started = time.monotonic()
            try:
                yield 'data: ' + json.dumps({'type': 'status', 'message': '任务 ' + run_id + ' 已入队'}) + '\n\n'
                while time.monotonic() - started < 90:
                    if await request.is_disconnected():
                        return
                    for event in store.events(run_id):
                        if event['seq'] > last:
                            last = event['seq']
                            yield 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'
                    row = store.get(run_id)
                    if row['status'] in ('completed', 'failed', 'cancelled'):
                        if row['status'] != 'completed':
                            yield 'data: ' + json.dumps({'type': 'error', 'message': row['error'] or row['status']}) + '\n\n'
                        return
                    await asyncio.sleep(.04)
                yield 'data: ' + json.dumps({'type': 'error', 'message': '流式请求超时'}) + '\n\n'
            finally:
                app.state.active_streams -= 1
                if store.get(run_id)['status'] in ('queued', 'running'):
                    store.finish(run_id, 'cancelled')
        return StreamingResponse(stream(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'X-Run-Id': run_id})

    @app.post('/api/runs', status_code=202)
    def submit(body: Chat):
        return {'id': enqueue(body.model_dump())}

    @app.get('/api/runs')
    def runs():
        return [{k: v for k, v in r.items() if k != 'payload'} for r in store.runs()]

    @app.get('/api/runs/{run_id}')
    def run_detail(run_id: str):
        return dict(require_run(run_id), events=store.events(run_id))

    @app.post('/api/runs/{run_id}/cancel')
    def cancel(run_id: str):
        row = require_run(run_id)
        if row['status'] not in ('queued', 'running'):
            raise HTTPException(409, '只能取消待执行或运行中的任务')
        store.finish(run_id, 'cancelled')
        return {'status': 'cancelled'}

    @app.post('/api/runs/{run_id}/retry', status_code=202)
    def retry(run_id: str):
        row = require_run(run_id)
        if row['status'] not in ('failed', 'cancelled'):
            raise HTTPException(409, '只能重试失败或已取消的任务')
        payload = json.loads(row['payload'])
        payload['fault'] = 'none'
        return {'id': enqueue(payload)}

    @app.post('/api/runs/{run_id}/feedback')
    def feedback(run_id: str, body: Feedback):
        require_run(run_id)
        store.feedback(run_id, body.score)
        return {'saved': True}

    @app.get('/api/memory/{session}')
    def memory(session: str):
        return store.memories(session)

    @app.delete('/api/memory/{session}')
    def forget(session: str):
        store.forget(session)
        return {'deleted': True}

    @app.post('/api/evaluations')
    async def evaluations():
        if app.state.evaluating:
            raise HTTPException(429, '已有评测正在执行')
        app.state.evaluating = True
        try:
            return {'baseline': await evaluate(runtime, 1), 'candidate': await evaluate(runtime, 3),
                    'release': '人工检查回归与延迟后决定是否发布；不会自动修改策略'}
        finally:
            app.state.evaluating = False

    @app.get('/api/improvements')
    def improvements():
        return [{'run_id': r['id'], 'reason': r['error'] or '用户负反馈', 'action': '加入回归集并人工复核'}
                for r in store.runs() if r['status'] == 'failed' or r['feedback'] == -1]

    @app.get('/api/skills')
    def skills():
        root = Path(os.environ.get('STUDIO_SKILLS') or str(Path(__file__).resolve().parents[3] / 'skills'))
        return [{'name': p.parent.name, 'content': p.read_text()} for p in sorted(root.glob('*/SKILL.md'))]

    @app.get('/api/metrics')
    def metrics():
        with store.connect() as db:
            rows = db.execute('SELECT status, COUNT(*) AS total FROM runs GROUP BY status').fetchall()
        return Response('\n'.join(f'studio_runs_total{{status="{r["status"]}"}} {r["total"]}' for r in rows) + '\n',
                        media_type='text/plain')

    @app.post('/api/mcp')
    async def mcp(request: Request):
        try:
            rpc = await request.json()
        except ValueError:
            return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}
        if not isinstance(rpc, dict) or rpc.get('jsonrpc') != '2.0' or not isinstance(rpc.get('method'), str):
            return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid request'}}
        envelope = {'jsonrpc': '2.0', 'id': rpc.get('id')}
        method = rpc['method']
        if method == 'notifications/initialized':
            return Response(status_code=202)
        if method == 'initialize':
            return dict(envelope, result={'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                                         'serverInfo': {'name': 'studio-teaching-subset', 'version': '1.0.0'}})
        if method == 'tools/list':
            return dict(envelope, result={'tools': [
                {'name': 'calculator', 'description': '受限算术解释器', 'inputSchema': {
                    'type': 'object', 'properties': {'expression': {'type': 'string', 'maxLength': 200}},
                    'required': ['expression'], 'additionalProperties': False}}]})
        if method == 'tools/call':
            params = rpc.get('params', {})
            try:
                if not isinstance(params, dict) or params.get('name') != 'calculator':
                    raise ValueError('未知工具')
                args = params.get('arguments', {})
                if not isinstance(args, dict) or set(args) != {'expression'}:
                    raise ValueError('参数错误')
                output = calculate(args['expression'])
                return dict(envelope, result={'content': [{'type': 'text', 'text': output}], 'isError': False})
            except (ValueError, SyntaxError, ZeroDivisionError, TypeError) as exc:
                return dict(envelope, result={'content': [{'type': 'text', 'text': str(exc)}], 'isError': True})
        return dict(envelope, error={'code': -32601, 'message': 'Method not found'})

    return app
