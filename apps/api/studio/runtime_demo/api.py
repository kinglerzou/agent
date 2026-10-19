from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import Conflict


class CreateRun(BaseModel):
    order_id: str = Field(default='A123', min_length=1, max_length=80, pattern=r'^\S+$')
    reason: str = Field(default='', max_length=500)
    auto: bool = False
    fault: bool = False


class Action(BaseModel):
    action: Literal['step', 'approve', 'input', 'pause', 'resume', 'retry', 'cancel']
    version: int = Field(ge=0)
    event_id: str = Field(min_length=1, max_length=100)
    value: str = Field(default='', max_length=500)


def create_demo_router(runtime):
    router = APIRouter()

    @router.get('/runtime-demo', include_in_schema=False)
    def page():
        return FileResponse(Path(__file__).with_name('index.html'))

    @router.get('/api/runtime-demo/runs')
    def runs():
        return runtime.list()

    @router.post('/api/runtime-demo/runs', status_code=201)
    def create(body: CreateRun):
        return runtime.create(**body.model_dump())

    @router.get('/api/runtime-demo/runs/{run_id}')
    def get(run_id: str):
        try:
            return runtime.get(run_id)
        except KeyError:
            raise HTTPException(404, '任务不存在')

    @router.post('/api/runtime-demo/runs/{run_id}/actions')
    def action(run_id: str, body: Action):
        try:
            return runtime.mutate(run_id, **body.model_dump())
        except KeyError:
            raise HTTPException(404, '任务不存在')
        except Conflict as exc:
            raise HTTPException(409, str(exc))

    return router
