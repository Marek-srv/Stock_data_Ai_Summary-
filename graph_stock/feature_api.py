"""Point-in-time feature snapshot API."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field


class FeatureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9&-]+$")
    decision_time: str = Field(min_length=20, max_length=40)
    request_key: UUID


def routes(app):
    router = APIRouter(prefix="/api/v1/features")

    @router.get("")
    def recent():
        return app.state.features.recent()

    @router.post("", status_code=201)
    def build(body: FeatureRequest):
        return app.state.features.submit(body.symbol, body.decision_time, str(body.request_key))[0]

    @router.get("/{snapshot_id}")
    def get(snapshot_id: UUID):
        try:
            return app.state.features.get(str(snapshot_id))
        except KeyError:
            raise HTTPException(404, "Feature snapshot not found") from None

    @router.get("/{snapshot_id}/report")
    def report(snapshot_id: UUID, download: bool = False):
        try:
            content = app.state.features.read_report(str(snapshot_id))
        except KeyError:
            raise HTTPException(404, "Feature snapshot report not found") from None
        headers = {"Content-Disposition": f'attachment; filename="features-{snapshot_id}.md"'} if download else {}
        return PlainTextResponse(content, headers=headers)

    app.include_router(router)
