"""Versioned filing API; all work stays in the shared durable service."""
import asyncio
from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from .filings import FilingError, MAX_BYTES


class FilingRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    symbol: str = Field(min_length=1, max_length=30)
    request_key: UUID


def routes(app, tasks):
    router = APIRouter(prefix='/api/v1/filings')

    async def execute(run_id):
        async with app.state.filing_semaphore:
            operation = asyncio.create_task(asyncio.to_thread(app.state.filings.execute, run_id))
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError:
                await operation
                raise

    def schedule(run_id):
        task = asyncio.create_task(execute(run_id))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def get(run_id):
        try:
            return app.state.filings.get(str(run_id))
        except KeyError:
            raise HTTPException(404, 'Filing request not found') from None

    @router.get('')
    def recent():
        return app.state.filings.recent()

    @router.post('', status_code=202)
    async def acquire(body: FilingRequest):
        run_id, created = app.state.filings.submit(body.symbol, str(body.request_key))
        if created:
            schedule(run_id)
        return get(run_id)

    @router.post('/import', status_code=202)
    async def import_pdf(request: Request, symbol: str = Query(min_length=1, max_length=30),
                         request_key: UUID = Query(), filename: str = Query(min_length=1, max_length=124),
                         name: str = Query(default='', max_length=200), available_date: date | None = None):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise HTTPException(413, 'PDF exceeds 25 MB')
        run_id, created = await asyncio.to_thread(app.state.filings.submit, symbol, str(request_key),
                                                  content=bytes(data), filename=filename, name=name,
                                                  available_date=available_date.isoformat() if available_date else None)
        if created:
            schedule(run_id)
        return get(run_id)

    @router.get('/sources/{source_id}/pdf')
    def pdf(source_id: str):
        try:
            meta, data = app.state.filings.source(source_id)
        except KeyError:
            raise HTTPException(404, 'Source not found') from None
        return Response(data, media_type='application/pdf',
                        headers={'Content-Disposition': f'attachment; filename="{meta["symbol"]}-{meta["id"]}.pdf"'})

    @router.get('/sources/{source_id}/note')
    def note(source_id: str):
        try:
            meta, _ = app.state.filings.source(source_id)
            return PlainTextResponse(app.state.filings.vault.read(meta['note_path']))
        except KeyError:
            raise HTTPException(404, 'Source not found') from None
        except (OSError, ValueError, UnicodeError):
            raise HTTPException(409, 'Evidence note unavailable; check the original vault and retry publication') from None

    @router.get('/{run_id}')
    def status(run_id: UUID):
        return get(run_id)

    @router.post('/{run_id}/retry', status_code=202)
    async def retry(run_id: UUID):
        get(run_id)
        if app.state.filings.retry(str(run_id)):
            schedule(str(run_id))
        return get(run_id)

    app.include_router(router)
    return schedule
