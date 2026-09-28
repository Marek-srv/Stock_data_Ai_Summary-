"""Versioned financial extraction API."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field


class FinancialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    request_key: UUID
    use_reasoning: bool = False


def routes(app, tasks):
    router = APIRouter(prefix="/api/v1/financials")

    async def execute(run_id):
        async with app.state.financial_semaphore:
            operation = asyncio.create_task(asyncio.to_thread(app.state.financials.execute, run_id))
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError:
                await operation
                raise

    def schedule(run_id):
        task = asyncio.create_task(execute(run_id))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def get(run_id):
        try:
            return app.state.financials.get(str(run_id))
        except KeyError:
            raise HTTPException(404, "Financial analysis not found") from None

    @router.get("")
    def recent():
        return app.state.financials.recent()

    @router.post("", status_code=202)
    async def start(body: FinancialRequest):
        run_id, created = app.state.financials.submit(body.source_id, str(body.request_key), body.use_reasoning)
        if created:
            schedule(run_id)
        return get(run_id)

    @router.get("/{run_id}")
    def status(run_id: UUID):
        return get(run_id)

    @router.get("/{run_id}/note")
    def note(run_id: UUID, download: bool = False):
        try:
            content = app.state.financials.read_note(str(run_id))
            headers = {"Content-Disposition": f'attachment; filename="financials-{run_id}.md"'} if download else {}
            return PlainTextResponse(content, headers=headers)
        except KeyError:
            raise HTTPException(404, "Financial note not found") from None
        except (OSError, ValueError, UnicodeError):
            raise HTTPException(409, "Financial note unavailable in the original vault") from None

    @router.post("/{run_id}/retry", status_code=202)
    async def retry(run_id: UUID):
        get(run_id)
        if app.state.financials.retry(str(run_id)):
            schedule(str(run_id))
        return get(run_id)

    app.include_router(router)
    return schedule
