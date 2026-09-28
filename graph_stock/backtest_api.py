"""Versioned backtest inspection API."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9&-]+$")
    market_run_id: UUID
    request_key: UUID


def routes(app):
    router = APIRouter(prefix="/api/v1/backtests")

    @router.get("")
    def recent():
        return app.state.backtests.recent()

    @router.post("", status_code=201)
    def build(body: BacktestRequest):
        return app.state.backtests.submit(body.symbol, str(body.market_run_id), str(body.request_key))[0]

    @router.get("/{run_id}")
    def get(run_id: UUID):
        try:
            return app.state.backtests.get(str(run_id))
        except KeyError:
            raise HTTPException(404, "Backtest not found") from None

    @router.get("/{run_id}/report")
    def report(run_id: UUID, download: bool = False):
        try:
            content = app.state.backtests.read_report(str(run_id))
        except KeyError:
            raise HTTPException(404, "Backtest report not found") from None
        headers = {"Content-Disposition": f'attachment; filename="backtest-{run_id}.md"'} if download else {}
        return PlainTextResponse(content, headers=headers)

    app.include_router(router)
