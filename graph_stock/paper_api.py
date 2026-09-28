"""Independent paper-book API."""
from uuid import UUID
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field


class ActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9&-]+$")
    validation_id: UUID
    request_key: UUID


class ProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    market_run_id: UUID
    request_key: UUID


def routes(app):
    router = APIRouter(prefix="/api/v1/paper-books")

    @router.get("")
    def recent(): return app.state.paper.recent()

    @router.post("", status_code=201)
    def activate(body: ActivateRequest):
        return app.state.paper.activate(body.symbol, str(body.validation_id), str(body.request_key))[0]

    @router.get("/{book_id}")
    def get(book_id: UUID):
        try: return app.state.paper.get(str(book_id))
        except KeyError: raise HTTPException(404, "Paper book not found") from None

    @router.post("/{book_id}/process")
    def process(book_id: UUID, body: ProcessRequest):
        return app.state.paper.process(str(book_id), str(body.market_run_id), str(body.request_key))[0]

    @router.post("/{book_id}/catch-up")
    def catch_up(book_id: UUID, body: ProcessRequest):
        return app.state.paper.catch_up(str(book_id), str(body.market_run_id), str(body.request_key))[0]

    @router.get("/{book_id}/monitoring")
    def monitoring(book_id: UUID):
        return app.state.paper.monitoring(str(book_id))

    @router.post("/{book_id}/catch-up")
    def catch_up(book_id: UUID, body: ProcessRequest):
        return app.state.paper.catch_up(str(book_id), str(body.market_run_id), str(body.request_key))[0]

    @router.get("/{book_id}/monitoring")
    def monitoring(book_id: UUID):
        return app.state.paper.monitoring(str(book_id))

    @router.get("/{book_id}/report")
    def report(book_id: UUID, download: bool = False):
        try: content = app.state.paper.read_report(str(book_id))
        except KeyError: raise HTTPException(404, "Paper book not found") from None
        headers = {"Content-Disposition": f'attachment; filename="paper-{book_id}.md"'} if download else {}
        return PlainTextResponse(content, headers=headers)

    app.include_router(router)
