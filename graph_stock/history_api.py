"""Correction history and verified backup API."""
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field


class CorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: str = Field(min_length=1, max_length=160)
    corrected_value: str = Field(min_length=1, max_length=80)
    evidence_id: str = Field(min_length=1, max_length=240)
    reason: str = Field(min_length=3, max_length=1000)
    request_key: UUID


def routes(app):
    router = APIRouter(prefix="/api/v1/history")

    @router.get("/corrections")
    def corrections(symbol: str | None = Query(default=None, max_length=30)):
        return app.state.history.corrections(symbol)

    @router.post("/corrections", status_code=201)
    def correct(body: CorrectionRequest):
        return app.state.history.correct_fact(body.target_id, body.corrected_value, body.evidence_id,
                                              body.reason, str(body.request_key))[0]

    @router.get("/corrections/{correction_id}/note", response_class=PlainTextResponse)
    def correction_note(correction_id: UUID):
        return app.state.history.read_correction(str(correction_id))

    @router.get("/financial/{run_id}/current")
    def current_financial(run_id: UUID):
        return app.state.history.current_financial(str(run_id))

    @router.post("/backups", status_code=201)
    def backup():
        return app.state.history.create_backup()

    @router.get("/backups")
    def backups():
        return app.state.history.backups()

    @router.get("/backups/{backup_id}/download")
    def download(backup_id: UUID):
        path = app.state.history.backup_path(str(backup_id))
        return FileResponse(path, filename=f"graph-stock-backup-{backup_id}.zip", media_type="application/zip")

    @router.post("/backups/{backup_id}/restore")
    def restore(backup_id: UUID):
        return app.state.history.restore(str(backup_id))

    app.include_router(router)
