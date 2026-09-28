"""Single-user local research service; one server process per state directory."""

import asyncio
import fcntl
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .reasoning import CodexDiagnostic, Outcome
from .store import Store
from .fixtures import search
from .research import ResearchError, ResearchService
from .filings import FilingService, FilingError
from .filing_api import routes as filing_routes
from .financials import FinancialError, FinancialService
from .financial_reasoning import CodexFinancialAnalyst
from .financial_api import routes as financial_routes
from .orchestration import UpdateError, UpdateService
from .update_api import routes as update_routes
from .ownership import OwnershipError, OwnershipService
from .ownership_api import routes as ownership_routes
from .news import NewsError, NewsService
from .news_api import routes as news_routes
from .market_data import MarketDataError, MarketDataService, MarketProviderError
from .market_api import routes as market_routes
from .features import FeatureError, FeatureService
from .feature_api import routes as feature_routes
from .backtest import BacktestError, BacktestService
from .backtest_api import routes as backtest_routes
from .validation import ValidationError, ValidationService
from .validation_api import routes as validation_routes
from .paper import PaperError, PaperService
from .paper_api import routes as paper_routes
from .combined import CombinedError, CombinedService
from .combined_api import routes as combined_routes
from .scheduler import SchedulerError, SchedulerPipeline, SchedulerService
from .scheduler_api import routes as scheduler_routes
from .alerts import AlertError, AlertService
from .alert_api import routes as alert_routes
from .history import HistoryError, HistoryService
from .history_api import routes as history_routes
from .improvements import ImprovementError, ImprovementService
from .improvement_api import routes as improvement_routes
from .discovery import DiscoveryError, DiscoveryService, NseDirectoryUniverse
from .discovery_api import routes as discovery_routes
from .startup import StartupManager
from .startup_api import routes as startup_routes
from .bulk_market import BulkMarketError, BulkMarketService
from .bulk_market_api import routes as bulk_market_routes
from .bulk_evidence import BulkEvidenceError, BulkEvidenceService
from .bulk_evidence_api import routes as bulk_evidence_routes

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID


class ResearchRequest(CheckRequest):
    query: str = Field(min_length=1, max_length=80)


def create_app(state_dir: Path | None = None, adapter=None, vault_dir: Path | None = None,
               filing_fetch=None, financial_extractor=None, financial_analyst=None,
               specialist_extractor=None, news_provider=None, market_provider=None,
               scheduler_runner=None, scheduler_clock=None, improvement_tester=None, discovery_provider=None,
               startup_home=None, startup_platform=None, bulk_market_provider=None, bulk_evidence_provider=None):
    state_dir = state_dir or Path(os.environ.get("GRAPH_STOCK_STATE_DIR", ".state"))
    vault_dir = vault_dir or Path(os.environ.get("GRAPH_STOCK_VAULT", str(state_dir / "fixture-vault")))
    adapter = adapter or CodexDiagnostic(os.environ.get("GRAPH_STOCK_CODEX", "codex"))
    tasks = set()

    @asynccontextmanager
    async def lifespan(app):
        state_dir.mkdir(parents=True, exist_ok=True)
        with (state_dir / "server.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another graph_stock server is using this state directory") from None
            app.state.store = Store(state_dir / "graph_stock.sqlite3")
            app.state.startup = StartupManager(
                Path(__file__).resolve().parent.parent,
                startup_home,
                startup_platform,
            )
            app.state.store.recover()
            app.state.semaphore = asyncio.Semaphore(1)
            app.state.research = ResearchService(app.state.store, vault_dir)
            app.state.publication_semaphore = asyncio.Semaphore(1)
            app.state.filings = FilingService(app.state.store, vault_dir, **({"fetch": filing_fetch} if filing_fetch else {}))
            app.state.discovery = DiscoveryService(
                app.state.store, vault_dir, app.state.research,
                discovery_provider or NseDirectoryUniverse(app.state.store, app.state.filings.fetch),
            )
            app.state.filing_semaphore = asyncio.Semaphore(1)
            app.state.financials = FinancialService(
                app.state.store, app.state.filings, vault_dir,
                **({"extractor": financial_extractor} if financial_extractor else {}),
                analyst=financial_analyst or CodexFinancialAnalyst(os.environ.get("GRAPH_STOCK_CODEX", "codex")),
            )
            app.state.history = HistoryService(app.state.store, vault_dir, state_dir)
            app.state.financial_semaphore = asyncio.Semaphore(1)
            app.state.updates = UpdateService(
                app.state.store, app.state.filings, vault_dir, extractor=app.state.financials.extractor,
                **({"specialist_extractor": specialist_extractor} if specialist_extractor else {}),
            )
            app.state.update_semaphore = asyncio.Semaphore(2)
            app.state.ownership = OwnershipService(app.state.store, app.state.filings, vault_dir)
            app.state.news = NewsService(
                app.state.store, app.state.filings, vault_dir,
                **({"provider": news_provider} if news_provider else {}),
            )
            app.state.market_data = MarketDataService(app.state.store, vault_dir, market_provider)
            app.state.bulk_market = BulkMarketService(app.state.store, app.state.market_data, vault_dir, bulk_market_provider)
            app.state.bulk_evidence = BulkEvidenceService(app.state.store, vault_dir, bulk_evidence_provider)
            app.state.features = FeatureService(app.state.store, vault_dir)
            app.state.backtests = BacktestService(app.state.store, app.state.market_data, vault_dir)
            app.state.validations = ValidationService(app.state.store, app.state.market_data, vault_dir)
            app.state.paper = PaperService(app.state.store, app.state.market_data, app.state.validations, vault_dir)
            app.state.combined = CombinedService(app.state.store, app.state.market_data, app.state.paper, vault_dir)
            app.state.alerts = AlertService(app.state.store, vault_dir)
            app.state.improvements = ImprovementService(app.state.store, vault_dir, improvement_tester)
            pipeline = scheduler_runner or SchedulerPipeline(
                app.state.filings, app.state.market_data, app.state.news, app.state.updates, app.state.ownership,
                app.state.financials, app.state.paper, app.state.combined)
            scheduler_options = {"clock": scheduler_clock} if scheduler_clock else {}
            app.state.scheduler = SchedulerService(
                app.state.store, pipeline,
                after_run=lambda job, outcome, key: app.state.alerts.scan(job["symbol"], key),
                **scheduler_options,
            )
            app.state.scheduler.sync_targets()
            app.state.scheduler.recover()
            await asyncio.to_thread(app.state.scheduler.run_due, "restart")

            async def scheduler_loop():
                while True:
                    await asyncio.sleep(30)
                    await asyncio.to_thread(app.state.scheduler.sync_targets)
                    await asyncio.to_thread(app.state.scheduler.run_due)

            scheduler_task = asyncio.create_task(scheduler_loop())
            tasks.add(scheduler_task)
            scheduler_task.add_done_callback(tasks.discard)
            for run_id in app.state.updates.pending():
                schedule_update(run_id)
            for run_id in app.state.financials.pending():
                schedule_financial(run_id)
            for run_id in app.state.filings.pending():
                schedule_filing(run_id)
            for run_id in app.state.research.pending():
                schedule_research(run_id)
            for run_id in app.state.bulk_market.pending():
                schedule_bulk_market(run_id)
            for run_id in app.state.bulk_evidence.pending():
                schedule_bulk_evidence(run_id)
            try:
                yield
            finally:
                for task in list(tasks):
                    task.cancel()
                await asyncio.gather(*list(tasks), return_exceptions=True)
                app.state.store.recover()

    app = FastAPI(title="graph_stock local research", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])
    app.mount("/dashboard", StaticFiles(directory=FRONTEND_DIST, check_dir=False), name="dashboard")

    @app.exception_handler(ResearchError)
    async def research_error(request, error):
        code = {"not-found": 404, "ambiguous": 409, "key-conflict": 409, "queue-full": 429}[error.code]
        return JSONResponse({"detail": {"code": error.code, "message": error.message, "candidates": error.candidates}}, status_code=code)

    @app.exception_handler(BacktestError)
    async def backtest_error(request, error):
        code = {"not-found": 404, "conflict": 409, "coverage": 422}.get(error.code, 422)
        return JSONResponse({"detail": error.message}, status_code=code)

    @app.exception_handler(ValidationError)
    async def validation_error(request, error):
        code = {"not-found": 404, "conflict": 409}.get(error.code, 422)
        return JSONResponse({"detail": error.message}, status_code=code)

    @app.exception_handler(PaperError)
    async def paper_error(request, error):
        code = {"not-found": 404, "conflict": 409, "not-eligible": 422}.get(error.code, 422)
        return JSONResponse({"detail": error.message}, status_code=code)

    @app.exception_handler(CombinedError)
    async def combined_error(request, error):
        code = {"not-found": 404, "conflict": 409}.get(error.code, 422)
        return JSONResponse({"detail": error.message}, status_code=code)

    @app.exception_handler(SchedulerError)
    async def scheduler_error(request, error):
        code = {"not-found": 404, "conflict": 409}.get(error.code, 422)
        return JSONResponse({"detail": error.message}, status_code=code)

    @app.exception_handler(AlertError)
    async def alert_error(request, error):
        code = {"not-found": 404, "conflict": 409}.get(error.code, 422)
        return JSONResponse({"detail": error.message}, status_code=code)

    @app.exception_handler(HistoryError)
    async def history_error(request, error):
        code = {"not-found": 404, "conflict": 409, "incomplete": 409,
                "invalid-backup": 422, "backup-failed": 503}.get(error.code, 422)
        return JSONResponse({"detail": error.message}, status_code=code)

    @app.exception_handler(ImprovementError)
    async def improvement_error(request, error):
        code = {"not-found": 404, "conflict": 409, "changed": 409, "unapproved": 409,
                "bounded": 422, "invalid": 422}.get(error.code, 422)
        return JSONResponse({"detail": error.message}, status_code=code)

    @app.exception_handler(DiscoveryError)
    async def discovery_error(request, error):
        code = {"not-found": 404, "conflict": 409, "not-eligible": 422, "invalid": 422, "unavailable": 503}.get(error.code, 422)
        return JSONResponse({"detail": error.message}, status_code=code)

    @app.exception_handler(BulkMarketError)
    async def bulk_market_error(request, error):
        code = {"not-found": 404, "partial": 422, "throttled": 429, "unavailable": 503}.get(error.code, 422)
        return JSONResponse({"detail": error.message}, status_code=code)

    @app.exception_handler(BulkEvidenceError)
    async def bulk_evidence_error(request, error):
        code = {"not-found": 404, "conflict": 409, "coverage": 422, "throttled": 429, "unavailable": 503}.get(error.code, 422)
        return JSONResponse({"detail": error.message}, status_code=code)

    @app.middleware("http")
    async def local_write_guard(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.url.netloc}"
            if request.headers.get("x-graph-stock") not in ("local-diagnostic", "local-research") or (origin and origin != expected):
                return JSONResponse({"detail": "Use the local application to run this action."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'"
        return response

    async def execute(run_id):
        async with app.state.semaphore:
            if not app.state.store.claim(run_id):
                return
            try:
                outcome = await adapter.run()
            except asyncio.CancelledError:
                app.state.store.finish(run_id, Outcome("interrupted"))
                raise
            except Exception:
                # Raw client errors can contain sensitive context. Persist only a safe status.
                outcome = Outcome("failed")
            app.state.store.finish(run_id, outcome)

    def schedule(run_id):
        task = asyncio.create_task(execute(run_id))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def execute_research(run_id):
        async with app.state.publication_semaphore:
            publication = asyncio.create_task(asyncio.to_thread(app.state.research.publish, run_id))
            try:
                await asyncio.shield(publication)
            except asyncio.CancelledError:
                # Finish the atomic file operation before releasing server ownership.
                await publication
                raise

    def schedule_research(run_id):
        task = asyncio.create_task(execute_research(run_id))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    @app.get("/", include_in_schema=False)
    def home():
        if not (FRONTEND_DIST / "index.html").is_file():
            raise HTTPException(503, "Build the React dashboard first: run pnpm build in frontend.")
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/diagnostic", include_in_schema=False)
    def diagnostic():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/assets/{filename}", include_in_schema=False)
    def asset(filename: str):
        if filename not in ("app.js", "style.css"):
            raise HTTPException(404)
        return FileResponse(Path(__file__).parent / "static" / filename)

    @app.get("/api/diagnostics")
    def recent():
        return app.state.store.recent()

    @app.get("/api/diagnostics/{run_id}")
    def get(run_id: UUID):
        try:
            return app.state.store.get(str(run_id))
        except KeyError:
            raise HTTPException(404, "Check not found") from None

    @app.post("/api/diagnostics", status_code=202)
    async def start(body: CheckRequest):
        try:
            run_id, created = app.state.store.create(str(body.request_key))
        except OverflowError:
            raise HTTPException(429, "The local check queue is full. Try again shortly.") from None
        if created:
            schedule(run_id)
        return app.state.store.get(run_id)

    @app.post("/api/diagnostics/{run_id}/retry", status_code=202)
    async def retry(run_id: UUID):
        try:
            if app.state.store.retry(str(run_id)):
                schedule(str(run_id))
            return app.state.store.get(str(run_id))
        except KeyError:
            raise HTTPException(404, "Check not found") from None
        except OverflowError:
            raise HTTPException(429, "The local check queue is full. Try again shortly.") from None

    @app.get("/api/securities")
    def securities(query: str = Query(min_length=1, max_length=80)):
        return search(query)

    @app.get("/api/watchlist")
    def watchlist():
        return app.state.research.watchlist()

    @app.post("/api/research", status_code=202)
    async def research(body: ResearchRequest):
        run_id, created = app.state.research.submit(body.query, str(body.request_key))
        if created:
            schedule_research(run_id)
        return app.state.research.get(run_id)

    @app.get("/api/research/{run_id}")
    def research_run(run_id: UUID):
        try:
            return app.state.research.get(str(run_id))
        except KeyError:
            raise HTTPException(404, "Research run not found") from None

    @app.get("/api/research/{run_id}/note")
    def research_note(run_id: UUID, download: bool = False):
        try:
            content = app.state.research.read_note(str(run_id))
            headers = {"Content-Disposition": f'attachment; filename="fixture-{run_id}.md"'} if download else {}
            return PlainTextResponse(content, headers=headers)
        except KeyError:
            raise HTTPException(404, "Research run not found") from None
        except (OSError, ValueError, UnicodeError):
            raise HTTPException(409, "Note unavailable in the configured test vault") from None

    @app.post("/api/research/{run_id}/retry", status_code=202)
    async def retry_research(run_id: UUID):
        try:
            if app.state.research.retry(str(run_id)):
                schedule_research(str(run_id))
            return app.state.research.get(str(run_id))
        except KeyError:
            raise HTTPException(404, "Research run not found") from None

    @app.exception_handler(FilingError)
    async def filing_error(request, error):
        code = {'invalid': 422, 'conflict': 409, 'queue-full': 429}.get(error.status, 503)
        return JSONResponse({'detail': error.message}, status_code=code)

    @app.exception_handler(FinancialError)
    async def financial_error(request, error):
        code = {'not-found': 404, 'conflict': 409, 'queue-full': 429}.get(error.status, 422)
        return JSONResponse({'detail': error.message}, status_code=code)

    @app.exception_handler(UpdateError)
    async def update_error(request, error):
        code = {'not-found': 404, 'conflict': 409, 'queue-full': 429}.get(error.code, 422)
        return JSONResponse({'detail': error.message}, status_code=code)

    @app.exception_handler(OwnershipError)
    async def ownership_error(request, error):
        code = {'not-found': 404, 'conflict': 409, 'coverage': 422}.get(error.code, 422)
        return JSONResponse({'detail': error.message}, status_code=code)

    @app.exception_handler(NewsError)
    async def news_error(request, error):
        code = {'not-found': 404, 'conflict': 409}.get(error.code, 422)
        return JSONResponse({'detail': error.message}, status_code=code)

    @app.exception_handler(MarketDataError)
    async def market_data_error(request, error):
        code = {'conflict': 409}.get(error.code, 422)
        return JSONResponse({'detail': error.message}, status_code=code)

    @app.exception_handler(MarketProviderError)
    async def market_provider_error(request, error):
        return JSONResponse({'detail': str(error)}, status_code=503)

    @app.exception_handler(FeatureError)
    async def feature_error(request, error):
        code = {'conflict': 409}.get(error.code, 422)
        return JSONResponse({'detail': error.message}, status_code=code)

    schedule_filing = filing_routes(app, tasks)
    schedule_financial = financial_routes(app, tasks)
    schedule_update = update_routes(app, tasks)
    ownership_routes(app)
    news_routes(app)
    market_routes(app)
    feature_routes(app)
    backtest_routes(app)
    validation_routes(app)
    paper_routes(app)
    combined_routes(app)
    scheduler_routes(app)
    alert_routes(app)
    history_routes(app)
    improvement_routes(app)
    discovery_routes(app, schedule_research)
    startup_routes(app)
    schedule_bulk_market = bulk_market_routes(app, tasks)
    schedule_bulk_evidence = bulk_evidence_routes(app, tasks)
    return app


app = create_app()
