"""Local material-alert API."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(pattern=r"^[A-Za-z0-9&-]{1,30}$")
    request_key: UUID


class AlertConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minimum_severity: Literal["low", "medium", "high", "critical"]
    material_only: bool


class AcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=500)


def routes(app):
    router = APIRouter(prefix="/api/v1/alerts")

    @router.get("")
    def alerts(symbol: str | None = Query(default=None, max_length=30)):
        return app.state.alerts.recent(symbol)

    @router.post("/scan")
    def scan(body: ScanRequest):
        return app.state.alerts.scan(body.symbol, str(body.request_key))

    @router.get("/config")
    def config():
        return app.state.alerts.config()

    @router.put("/config")
    def configure(body: AlertConfigRequest):
        return app.state.alerts.configure(body.minimum_severity, body.material_only)

    @router.get("/{alert_id}")
    def alert(alert_id: UUID):
        return app.state.alerts.get(str(alert_id))

    @router.post("/{alert_id}/acknowledge")
    def acknowledge(alert_id: UUID, body: AcknowledgeRequest):
        return app.state.alerts.acknowledge(str(alert_id), body.note)

    @router.get("/{alert_id}/note", response_class=PlainTextResponse)
    def note(alert_id: UUID):
        return app.state.alerts.read_note(str(alert_id))

    app.include_router(router)
