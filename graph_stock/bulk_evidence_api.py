"""Official NSE financial and ownership coverage API."""
import asyncio
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    symbols: list[str] | None = Field(default=None, min_length=1, max_length=10)


def routes(app, tasks):
    router = APIRouter(prefix="/api/v1/bulk-evidence")

    def schedule(run_id):
        task = asyncio.create_task(asyncio.to_thread(app.state.bulk_evidence.execute, run_id))
        tasks.add(task); task.add_done_callback(tasks.discard)

    @router.get("")
    def recent(): return app.state.bulk_evidence.recent()

    @router.post("", status_code=202)
    async def refresh(body: RefreshRequest):
        result, created = app.state.bulk_evidence.submit(str(body.request_key), body.symbols)
        if created: schedule(result["id"])
        return result

    @router.get("/{run_id}")
    def get(run_id: UUID): return app.state.bulk_evidence.get(str(run_id))

    @router.get("/{run_id}/report", response_class=PlainTextResponse)
    def report(run_id: UUID): return app.state.bulk_evidence.read_report(str(run_id))

    app.include_router(router)
    return schedule
