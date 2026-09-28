"""Persisted local scheduler API."""
import asyncio
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID


def routes(app):
    router = APIRouter(prefix="/api/v1/scheduler")

    @router.get("/jobs")
    def jobs(): return app.state.scheduler.jobs()

    @router.get("/runs")
    def runs(): return app.state.scheduler.history()

    @router.get("/jobs/{job_id}/runs")
    def job_runs(job_id: str): return app.state.scheduler.history(job_id)

    @router.post("/jobs/{job_id}/run")
    async def run(job_id: str, body: RunRequest):
        return (await asyncio.to_thread(app.state.scheduler.run_manual, job_id, str(body.request_key)))[0]

    @router.post("/sync")
    async def sync(): return await asyncio.to_thread(app.state.scheduler.sync_targets)

    app.include_router(router)
