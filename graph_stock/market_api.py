"""Market data and corporate-action inspection API."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field


class MarketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9&-]+$")
    request_key: UUID


class MarketImport(MarketRequest):
    bundle: dict[str, Any]


def routes(app):
    router = APIRouter(prefix="/api/v1/market-data")

    @router.get("")
    def recent():
        return app.state.market_data.recent()

    @router.post("", status_code=201)
    def collect(body: MarketRequest):
        return app.state.market_data.submit(body.symbol, str(body.request_key))[0]

    @router.post("/import", status_code=201)
    def manual(body: MarketImport):
        return app.state.market_data.submit(body.symbol, str(body.request_key), body.bundle)[0]

    @router.get("/{run_id}")
    def get(run_id: UUID):
        try:
            return app.state.market_data.get(str(run_id))
        except KeyError:
            raise HTTPException(404, "Market data run not found") from None

    @router.get("/{run_id}/report")
    def report(run_id: UUID, download: bool = False):
        try:
            content = app.state.market_data.read_report(str(run_id))
        except KeyError:
            raise HTTPException(404, "Market data report not found") from None
        headers = {"Content-Disposition": f'attachment; filename="market-data-{run_id}.md"'} if download else {}
        return PlainTextResponse(content, headers=headers)

    app.include_router(router)
