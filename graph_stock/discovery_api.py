"""Candidate discovery and research-queue API."""
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict


class ScreenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID


class QueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID


def routes(app, schedule_research):
    router = APIRouter(prefix="/api/v1/discovery")

    @router.get("")
    def recent(): return app.state.discovery.recent()

    @router.post("", status_code=201)
    def screen(body: ScreenRequest): return app.state.discovery.screen(str(body.request_key))[0]

    @router.get("/{run_id}")
    def get(run_id: UUID): return app.state.discovery.get(str(run_id))

    @router.get("/{run_id}/report", response_class=PlainTextResponse)
    def report(run_id: UUID): return app.state.discovery.read_report(str(run_id))

    @router.post("/{run_id}/candidates/{security_id}/queue", status_code=202)
    async def queue(run_id: UUID, security_id: str, body: QueueRequest):
        outcome = app.state.discovery.queue(str(run_id), security_id, str(body.request_key))
        if outcome["created"]: schedule_research(outcome["research_run_id"])
        return outcome

    app.include_router(router)
