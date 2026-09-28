"""Dated news and catalyst API."""

from typing import Any
from uuid import UUID
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field


class NewsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    request_key: UUID


class NewsImport(NewsRequest):
    records: list[dict[str, Any]] = Field(min_length=1, max_length=50)


def routes(app):
    router = APIRouter(prefix="/api/v1/news")

    @router.get("")
    def recent():
        return app.state.news.recent()

    @router.post("", status_code=201)
    def refresh(body: NewsRequest):
        return app.state.news.submit(body.source_id, str(body.request_key))[0]

    @router.post("/import", status_code=201)
    def manual(body: NewsImport):
        return app.state.news.submit(body.source_id, str(body.request_key), body.records)[0]

    @router.get("/{run_id}")
    def get(run_id: UUID):
        try:
            return app.state.news.get(str(run_id))
        except KeyError:
            raise HTTPException(404, "News run not found") from None

    @router.get("/{run_id}/report")
    def report(run_id: UUID, download: bool = False):
        try:
            content = app.state.news.read_report(str(run_id))
        except KeyError:
            raise HTTPException(404, "News report not found") from None
        headers = {"Content-Disposition": f'attachment; filename="news-{run_id}.md"'} if download else {}
        return PlainTextResponse(content, headers=headers)

    app.include_router(router)
