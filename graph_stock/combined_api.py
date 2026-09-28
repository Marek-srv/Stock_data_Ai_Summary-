"""Combined paper-book API."""
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field


class ActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9&-]+$")
    member_book_ids: list[UUID] = Field(min_length=2)
    request_key: UUID
    initial_cash: str = "100000"
    allocations_percent: dict[str, str] | None = None


class ProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    market_run_id: UUID
    request_key: UUID


def routes(app):
    router = APIRouter(prefix="/api/v1/combined-books")

    @router.get("")
    def recent():
        return app.state.combined.recent()

    @router.post("", status_code=201)
    def activate(body: ActivateRequest):
        members = [str(value) for value in body.member_book_ids]
        return app.state.combined.activate(
            body.symbol,
            members,
            str(body.request_key),
            body.initial_cash,
            body.allocations_percent,
        )[0]

    @router.get("/{book_id}")
    def get(book_id: UUID):
        try:
            return app.state.combined.get(str(book_id))
        except KeyError:
            raise HTTPException(404, "Combined paper book not found") from None

    @router.post("/{book_id}/process")
    def process(book_id: UUID, body: ProcessRequest):
        return app.state.combined.process(
            str(book_id), str(body.market_run_id), str(body.request_key)
        )[0]

    @router.post("/{book_id}/catch-up")
    def catch_up(book_id: UUID, body: ProcessRequest):
        return app.state.combined.catch_up(
            str(book_id), str(body.market_run_id), str(body.request_key)
        )[0]

    @router.get("/{book_id}/report")
    def report(book_id: UUID, download: bool = False):
        try:
            content = app.state.combined.read_report(str(book_id))
        except KeyError:
            raise HTTPException(404, "Combined paper book not found") from None
        headers = {
            "Content-Disposition": f'attachment; filename="combined-{book_id}.md"'
        } if download else {}
        return PlainTextResponse(content, headers=headers)

    app.include_router(router)
