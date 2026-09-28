"""Official bulk NSE history API."""
import asyncio
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID


def routes(app, tasks):
    router = APIRouter(prefix="/api/v1/bulk-market-history")

    def schedule(run_id):
        task = asyncio.create_task(asyncio.to_thread(app.state.bulk_market.execute, run_id))
        tasks.add(task); task.add_done_callback(tasks.discard)

    @router.get("")
    def recent(): return app.state.bulk_market.recent()

    @router.post("", status_code=202)
    async def refresh(body: RefreshRequest):
        result, created = app.state.bulk_market.submit(str(body.request_key))
        if created: schedule(result["id"])
        return result

    @router.get("/{run_id}")
    def get(run_id: UUID): return app.state.bulk_market.get(str(run_id))

    @router.get("/{run_id}/report", response_class=PlainTextResponse)
    def report(run_id: UUID): return app.state.bulk_market.read_report(str(run_id))

    app.include_router(router)
    return schedule
