import json
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from graph_stock.app import create_app
from graph_stock.scheduler import IST, SchedulerPipeline, SchedulerService, iso, next_due
from graph_stock.store import Store

HEADERS = {"X-Graph-Stock": "local-research"}


class Clock:
    def __init__(self, value): self.value = value
    def __call__(self): return self.value


def job(service, kind): return next(item for item in service.jobs() if item["kind"] == kind)


def set_only_due(service, kind, due):
    with service.store.connect() as db:
        db.execute("UPDATE scheduled_jobs SET next_due='2099-01-01T00:00:00+00:00',status='scheduled'")
        db.execute("UPDATE scheduled_jobs SET next_due=? WHERE kind=?", (iso(due), kind))


def test_timezone_boundaries_cover_daily_monthly_and_quarterly_jobs(tmp_path):
    after = datetime(2026, 1, 31, 20, 0, tzinfo=IST)
    service = SchedulerService(Store(tmp_path / "state.sqlite3"), lambda *_: {"status": "completed"}, Clock(after))
    service.register("BEL")
    jobs = {item["kind"]: item for item in service.jobs()}
    assert len(jobs) == 6 and all(item["timezone"] == "Asia/Kolkata" for item in jobs.values())
    assert datetime.fromisoformat(jobs["daily-market"]["next_due"]).astimezone(IST).isoformat() == "2026-02-01T18:30:00+05:30"
    assert datetime.fromisoformat(jobs["monthly-mf"]["next_due"]).astimezone(IST).isoformat() == "2026-02-10T10:00:00+05:30"
    assert datetime.fromisoformat(jobs["quarterly-results"]["next_due"]).astimezone(IST).isoformat() == "2026-04-15T10:00:00+05:30"
    assert datetime.fromisoformat(jobs["quarterly-shareholding"]["next_due"]).astimezone(IST).isoformat() == "2026-04-21T10:00:00+05:30"


def test_restart_recovers_one_missed_run_and_coalesces_overlap(tmp_path):
    clock = Clock(datetime(2026, 4, 16, 5, 0, tzinfo=timezone.utc)); calls = []
    service = SchedulerService(Store(tmp_path / "state.sqlite3"), lambda current, key: calls.append(current["kind"]) or {"status": "completed"}, clock)
    service.register("BEL", "source-1", datetime(2026, 4, 1, tzinfo=timezone.utc))
    due = datetime(2026, 4, 15, 4, 30, tzinfo=timezone.utc)
    set_only_due(service, "quarterly-results", due)
    with service.store.connect() as db:
        db.execute("UPDATE scheduled_jobs SET status='running',lease_until=? WHERE kind='quarterly-results'", (iso(clock.value),))
        current = job(service, "quarterly-results")
        db.execute("INSERT INTO scheduler_runs VALUES (?,?,?,?,?,?,?,?,?)", (
            str(uuid.uuid4()), current["id"], iso(due), "scheduled", "running", None,
            iso(due), None, "{}"))
    service.recover()
    results = service.run_due("restart")
    assert calls == ["quarterly-results"] and len(results) == 1
    assert results[0]["trigger"] == "restart" and results[0]["status"] == "completed"
    assert service.run_due("restart") == []
    assert [item.get("status") for item in service.history(current["id"])] == ["completed", "failed"]

    nested = []
    def overlapping(current_job, key):
        nested.append(service.run(current_job["id"], "manual", now=clock.value)[0])
        return {"status": "completed"}
    service.runner = overlapping
    result, created = service.run(current["id"], "manual", scheduled_for="manual:overlap", now=clock.value)
    assert created and result["status"] == "completed"
    assert nested == [{"coalesced": True, "job_id": current["id"], "status": "running"}]


def test_wait_states_retry_and_do_not_stop_other_due_work(tmp_path):
    clock = Clock(datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)); seen = []
    def runner(current, key):
        seen.append(current["kind"])
        if current["kind"] == "daily-material": raise RuntimeError("authentication required")
        if current["kind"] == "daily-news": raise RuntimeError("rate limit")
        if current["kind"] == "monthly-mf": raise RuntimeError("network offline")
        if current["kind"] == "quarterly-results": return {"status": "waiting-for-source", "reason": "disclosure unavailable"}
        return {"status": "completed"}
    service = SchedulerService(Store(tmp_path / "state.sqlite3"), runner, clock)
    service.register("BEL", "source-1", datetime(2026, 6, 1, tzinfo=timezone.utc))
    with service.store.connect() as db:
        db.execute("UPDATE scheduled_jobs SET next_due=?", (iso(clock.value),))
    results = service.run_due()
    statuses = {job(service, kind)["status"] for kind in seen}
    assert len(results) == 6 and set(seen) == {item["kind"] for item in service.jobs()}
    assert {"waiting-for-auth", "rate-limited", "offline", "waiting-for-source", "scheduled"} <= statuses
    assert job(service, "daily-market")["last_success"] is not None
    assert job(service, "daily-material")["waiting_reason"]


def test_manual_api_syncs_watchlist_and_reuses_request_key(tmp_path):
    clock = Clock(datetime(2026, 9, 8, 6, 0, tzinfo=timezone.utc)); calls = []
    def runner(current, key):
        calls.append((current["kind"], key)); return {"status": "completed", "mode": "fixture-runner"}
    app = create_app(tmp_path, scheduler_runner=runner, scheduler_clock=clock)
    with TestClient(app, base_url="http://localhost") as client:
        research = client.post("/api/research", headers=HEADERS, json={
            "query": "BEL", "request_key": str(uuid.uuid4())
        })
        assert research.status_code == 202
        synced = client.post("/api/v1/scheduler/sync", headers=HEADERS)
        assert synced.status_code == 200 and len(synced.json()) == 6
        market = next(item for item in synced.json() if item["kind"] == "daily-market")
        key = str(uuid.uuid4())
        first = client.post(f"/api/v1/scheduler/jobs/{market['id']}/run", headers=HEADERS, json={"request_key": key})
        repeated = client.post(f"/api/v1/scheduler/jobs/{market['id']}/run", headers=HEADERS, json={"request_key": key})
        assert first.status_code == repeated.status_code == 200
        assert first.json()["id"] == repeated.json()["id"] and len(calls) == 1
        assert client.get(f"/api/v1/scheduler/jobs/{market['id']}/runs").json()[0]["trigger"] == "manual"


def test_pipeline_polls_disclosure_and_daily_market_invokes_paper_catchup():
    calls = []
    class Filings:
        status = "success"
        def submit(self, symbol, key): calls.append("poll"); return "filing", True
        def execute(self, run_id): calls.append("filing-execute")
        def get(self, run_id): return {"status": self.status, "result": {"message": "not released"}, "source": {"id": "new-source"}}
    class Market:
        def submit(self, symbol, key): calls.append("market"); return {"id": "market-1"}, True
    class Books:
        def recent(self): return [{"id": "book-1", "symbol": "BEL", "state": {"status": "active"}}]
        def catch_up(self, book_id, market_id, key): calls.append(("catch-up", book_id, market_id)); return {}, True
    class Financials:
        def submit(self, source, key, use_reasoning): calls.append(("financial", source, use_reasoning)); return "financial-1", True
        def execute(self, run_id): calls.append("financial-execute")
        def get(self, run_id): return {"status": "completed"}
    unused = object(); filings = Filings(); books = Books()
    pipeline = SchedulerPipeline(filings, Market(), unused, unused, unused, Financials(), books, books)
    market = pipeline({"kind": "daily-market", "symbol": "BEL", "source_id": None}, str(uuid.uuid4()))
    assert market == {"status": "completed", "market_run_id": "market-1", "paper_books": 1, "combined_books": 1}
    assert calls.count(("catch-up", "book-1", "market-1")) == 2
    result = pipeline({"kind": "quarterly-results", "symbol": "BEL", "source_id": "old-source"}, str(uuid.uuid4()))
    assert result["status"] == "completed" and ("financial", "new-source", False) in calls
    filings.status = "unavailable"
    waiting = pipeline({"kind": "quarterly-results", "symbol": "BEL", "source_id": "old-source"}, str(uuid.uuid4()))
    assert waiting["status"] == "waiting-for-source" and waiting["reason"] == "not released"


def test_successful_run_invokes_alert_scan_without_coupling_failure(tmp_path):
    now = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
    scans = []
    service = SchedulerService(Store(tmp_path / "scheduler.sqlite3"), lambda job, key: {"status": "unchanged"},
                               clock=lambda: now, after_run=lambda job, outcome, key: scans.append((job["symbol"], key)) or {"created": []})
    service.register("BEL", now=now)
    result, created = service.run_manual(service.jobs()[0]["id"], str(uuid.uuid4()), now=now)
    assert created and result["status"] == "unchanged" and result["pipeline"]["alerts"] == {"created": []}
    assert scans[0][0] == "BEL"

    failing = SchedulerService(Store(tmp_path / "failure.sqlite3"), lambda job, key: {"status": "completed"},
                               clock=lambda: now, after_run=lambda *args: (_ for _ in ()).throw(OSError("vault busy")))
    failing.register("BEL", now=now)
    result, _ = failing.run_manual(failing.jobs()[0]["id"], str(uuid.uuid4()), now=now)
    assert result["status"] == "completed" and result["pipeline"]["alert_delivery"]["status"] == "failed"
