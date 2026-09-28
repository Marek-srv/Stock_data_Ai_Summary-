"""Versioned dependency-aware research update API."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field


class UpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    request_key: UUID


def routes(app, tasks):
    router = APIRouter(prefix="/api/v1/updates")

    async def execute(run_id):
        async with app.state.update_semaphore:
            operation = asyncio.create_task(asyncio.to_thread(app.state.updates.execute, run_id))
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
            return app.state.updates.get(str(run_id))
        except KeyError:
            raise HTTPException(404, "Research update not found") from None

    @router.get("")
    def recent():
        return app.state.updates.recent()

    @router.post("", status_code=202)
    async def start(body: UpdateRequest):
        run_id, created = app.state.updates.submit(body.source_id, str(body.request_key))
        if created:
            schedule(run_id)
        return get(run_id)

    @router.get("/{run_id}")
    def status(run_id: UUID):
        return get(run_id)

    @router.get("/{run_id}/report")
    def report(run_id: UUID, download: bool = False):
        try:
            content = app.state.updates.read_report(str(run_id))
            headers = {"Content-Disposition": f'attachment; filename="update-{run_id}.md"'} if download else {}
            return PlainTextResponse(content, headers=headers)
        except KeyError:
            raise HTTPException(404, "Update report not available") from None
        except (OSError, ValueError, UnicodeError):
            raise HTTPException(409, "Update report unavailable in the original vault") from None

    @router.get("/{run_id}/specialists/{kind}")
    def specialist(run_id: UUID, kind: str, download: bool = False):
        try:
            content = app.state.updates.read_specialist(str(run_id), kind)
            headers = {"Content-Disposition": f'attachment; filename="{kind}-{run_id}.md"'} if download else {}
            return PlainTextResponse(content, headers=headers)
        except KeyError:
            raise HTTPException(404, "Specialist report not available") from None
        except (OSError, ValueError, UnicodeError):
            raise HTTPException(409, "Specialist report unavailable in the original vault") from None

    @router.get("/{run_id}/research/{kind}")
    def event_research(run_id: UUID, kind: str, download: bool = False):
        try:
            content = app.state.updates.read_event_research(str(run_id), kind)
            headers = {"Content-Disposition": f'attachment; filename="{kind}-{run_id}.md"'} if download else {}
            return PlainTextResponse(content, headers=headers)
        except KeyError:
            raise HTTPException(404, "Research report not available") from None
        except (OSError, ValueError, UnicodeError):
            raise HTTPException(409, "Research report unavailable in the original vault") from None

    @router.get("/{run_id}/synthesis/{kind}")
    def synthesis(run_id: UUID, kind: str, download: bool = False):
        try:
            content = app.state.updates.read_synthesis(str(run_id), kind)
            headers = {"Content-Disposition": f'attachment; filename="{kind}-{run_id}.md"'} if download else {}
            return PlainTextResponse(content, headers=headers)
        except KeyError:
            raise HTTPException(404, "Synthesis report not available") from None
        except (OSError, ValueError, UnicodeError):
            raise HTTPException(409, "Synthesis report unavailable in the original vault") from None

    @router.post("/{run_id}/resume", status_code=202)
    async def resume(run_id: UUID):
        get(run_id)
        if app.state.updates.resume(str(run_id)):
            schedule(str(run_id))
        return get(run_id)

    @router.post("/{run_id}/cancel", status_code=202)
    async def cancel(run_id: UUID):
        get(run_id)
        app.state.updates.cancel(str(run_id))
        return get(run_id)

    app.include_router(router)
    return schedule
