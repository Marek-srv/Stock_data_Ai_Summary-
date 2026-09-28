"""Ownership history API."""

from uuid import UUID
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field


class OwnershipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    request_key: UUID


def routes(app):
    router = APIRouter(prefix="/api/v1/ownership")

    @router.get("")
    def recent():
        return app.state.ownership.recent()

    @router.post("", status_code=201)
    def build(body: OwnershipRequest):
        return app.state.ownership.submit(body.source_id, str(body.request_key))[0]

    @router.get("/{run_id}")
    def get(run_id: UUID):
        try:
            return app.state.ownership.get(str(run_id))
        except KeyError:
            raise HTTPException(404, "Ownership comparison not found") from None

    @router.get("/{run_id}/reports/{kind}")
    def report(run_id: UUID, kind: str, download: bool = False):
        try:
            content = app.state.ownership.read_report(str(run_id), kind)
        except KeyError:
            raise HTTPException(404, "Ownership report not found") from None
        headers = {"Content-Disposition": f'attachment; filename="{kind}-{run_id}.md"'} if download else {}
        return PlainTextResponse(content, headers=headers)

    app.include_router(router)
