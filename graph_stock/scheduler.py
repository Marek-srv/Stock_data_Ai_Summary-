"""Persisted in-process scheduler for local research and paper catch-up."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
SCHEDULER_VERSION = "local-persisted-scheduler/v1"
JOB_SPECS = {
    "daily-market": {"cadence": "daily", "hour": 18, "minute": 30},
    "daily-news": {"cadence": "daily", "hour": 19, "minute": 0},
    "daily-material": {"cadence": "daily", "hour": 19, "minute": 15},
    "monthly-mf": {"cadence": "monthly", "day": 10, "hour": 10, "minute": 0},
    "quarterly-results": {"cadence": "quarterly", "day": 15, "hour": 10, "minute": 0},
    "quarterly-shareholding": {"cadence": "quarterly", "day": 21, "hour": 10, "minute": 0},
}
RUN_STATUSES = {"completed", "unchanged", "waiting-for-source", "waiting-for-auth",
                "rate-limited", "offline", "partial", "failed"}


class SchedulerError(Exception):
    def __init__(self, message, code="invalid"):
        self.message, self.code = message, code
        super().__init__(message)


def utcnow(): return datetime.now(timezone.utc)
def iso(value): return value.astimezone(timezone.utc).isoformat()


def next_due(kind, after):
    """Return the first cadence boundary strictly after an aware instant."""
    if after.tzinfo is None: raise ValueError("Scheduler times must be timezone aware")
    spec, local = JOB_SPECS[kind], after.astimezone(IST)
    cadence = spec["cadence"]
    if cadence == "daily":
        candidate = local.replace(hour=spec["hour"], minute=spec["minute"], second=0, microsecond=0)
        if candidate <= local: candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)
    months = range(1, 25)
    for offset in months:
        month_index = local.year * 12 + local.month - 1 + (offset - 1)
        year, month = divmod(month_index, 12); month += 1
        if cadence == "quarterly" and month not in (1, 4, 7, 10): continue
        candidate = datetime(year, month, spec["day"], spec["hour"], spec["minute"], tzinfo=IST)
        if candidate > local: return candidate.astimezone(timezone.utc)
    raise RuntimeError("Unable to determine next schedule boundary")


class SchedulerPipeline:
    """Calls the same deterministic services used by manual UI actions."""
    def __init__(self, filings, market, news, updates, ownership, financials, paper, combined):
        self.filings, self.market, self.news, self.updates = filings, market, news, updates
        self.ownership, self.financials, self.paper, self.combined = ownership, financials, paper, combined

    def __call__(self, job, request_key):
        kind, symbol, source_id = job["kind"], job["symbol"], job.get("source_id")
        if kind == "daily-market":
            market, _ = self.market.submit(symbol, request_key)
            paper_runs, combined_runs = [], []
            for book in self.paper.recent():
                if book["symbol"] == symbol and book["state"]["status"] == "active":
                    paper_runs.append(self.paper.catch_up(book["id"], market["id"], str(uuid.uuid5(uuid.NAMESPACE_URL, request_key + book["id"])))[0])
            for book in self.combined.recent():
                if book["symbol"] == symbol and book["state"]["status"] == "active":
                    combined_runs.append(self.combined.catch_up(book["id"], market["id"], str(uuid.uuid5(uuid.NAMESPACE_URL, request_key + book["id"])))[0])
            return {"status": "completed", "market_run_id": market["id"],
                    "paper_books": len(paper_runs), "combined_books": len(combined_runs)}
        if kind in ("daily-material", "monthly-mf", "quarterly-results", "quarterly-shareholding"):
            filing_id, _ = self.filings.submit(symbol, request_key); self.filings.execute(filing_id)
            filing = self.filings.get(filing_id)
            if filing["status"] not in ("success", "unchanged"):
                return {"status": "waiting-for-source", "reason": filing["result"].get("message") or "Disclosure is not published yet.",
                        "poll_run_id": filing_id}
            source_id = filing.get("source", {}).get("id") or source_id
        if not source_id:
            return {"status": "waiting-for-source", "reason": "No saved filing source is available for this symbol."}
        if kind == "daily-news":
            result, _ = self.news.submit(source_id, request_key)
            return {"status": "completed" if result["status"] == "completed" else "waiting-for-source",
                    "run_id": result["id"], "reason": "; ".join(result.get("gaps", [])) or None}
        if kind == "daily-material":
            run_id, _ = self.updates.submit(source_id, request_key); self.updates.execute(run_id); result = self.updates.get(run_id)
            return {"status": result["status"], "run_id": run_id, "reason": result.get("error")}
        if kind in ("monthly-mf", "quarterly-shareholding"):
            result, _ = self.ownership.submit(source_id, request_key)
            return {"status": "completed", "run_id": result["id"]}
        if kind == "quarterly-results":
            run_id, _ = self.financials.submit(source_id, request_key, False); self.financials.execute(run_id); result = self.financials.get(run_id)
            return {"status": "completed" if result["status"] == "completed" else result["status"],
                    "run_id": run_id, "reason": result.get("message")}
        raise SchedulerError("Unknown scheduler job type.")


class SchedulerService:
    def __init__(self, store, runner, clock=utcnow, after_run=None):
        self.store, self.runner, self.clock, self.after_run = store, runner, clock, after_run
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    id TEXT PRIMARY KEY, symbol TEXT NOT NULL, kind TEXT NOT NULL, cadence TEXT NOT NULL,
                    timezone TEXT NOT NULL, source_id TEXT, next_due TEXT NOT NULL, status TEXT NOT NULL,
                    last_success TEXT, last_attempt TEXT, attempts INTEGER NOT NULL, lease_until TEXT,
                    waiting_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(symbol,kind)
                );
                CREATE TABLE IF NOT EXISTS scheduler_runs (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, scheduled_for TEXT NOT NULL, trigger TEXT NOT NULL,
                    status TEXT NOT NULL, reason TEXT, started_at TEXT NOT NULL, finished_at TEXT,
                    result TEXT NOT NULL, UNIQUE(job_id,scheduled_for)
                );
                CREATE TABLE IF NOT EXISTS scheduler_requests (
                    request_key TEXT PRIMARY KEY, job_id TEXT NOT NULL, run_id TEXT NOT NULL
                );
            """)

    def sync_targets(self, now=None):
        now = now or self.clock(); targets = {}
        with self.store.connect() as db:
            try:
                for row in db.execute("SELECT s.symbol FROM fixture_watchlist w JOIN fixture_securities s ON s.id=w.security_id"):
                    targets.setdefault(row["symbol"], None)
            except sqlite3.OperationalError: pass
            try:
                for row in db.execute("SELECT DISTINCT symbol FROM paper_books"):
                    targets.setdefault(row["symbol"], None)
            except sqlite3.OperationalError: pass
            try:
                for row in db.execute("SELECT id,symbol FROM filing_sources ORDER BY rowid"):
                    targets[row["symbol"]] = row["id"]
            except sqlite3.OperationalError: pass
        for symbol, source_id in targets.items(): self.register(symbol, source_id, now)
        return self.jobs()

    def register(self, symbol, source_id=None, now=None):
        now = now or self.clock(); timestamp = iso(now)
        with self.store.connect() as db:
            for kind, spec in JOB_SPECS.items():
                job_id = "schedule:" + hashlib.sha256(f"{symbol}:{kind}".encode()).hexdigest()[:24]
                db.execute("""INSERT INTO scheduled_jobs VALUES (?,?,?,?,?,?,?,?,NULL,NULL,0,NULL,NULL,?,?)
                    ON CONFLICT(symbol,kind) DO UPDATE SET source_id=COALESCE(excluded.source_id,scheduled_jobs.source_id),updated_at=excluded.updated_at""",
                    (job_id, symbol, kind, spec["cadence"], "Asia/Kolkata", source_id,
                     iso(next_due(kind, now)), "scheduled", timestamp, timestamp))

    def recover(self, now=None):
        timestamp = iso(now or self.clock())
        with self.store.connect() as db:
            db.execute("UPDATE scheduled_jobs SET status='scheduled',next_due=?,lease_until=NULL,waiting_reason='interrupted-before-completion',updated_at=? WHERE status='running'", (timestamp, timestamp))
            for row in db.execute("SELECT * FROM scheduler_runs WHERE status='running'").fetchall():
                result = {"id": row["id"], "job_id": row["job_id"], "scheduled_for": row["scheduled_for"],
                          "trigger": row["trigger"], "status": "failed", "reason": "interrupted-before-completion",
                          "started_at": row["started_at"], "finished_at": timestamp,
                          "pipeline": {"status": "failed", "reason": "interrupted-before-completion"}}
                db.execute("UPDATE scheduler_runs SET status='failed',reason=?,finished_at=?,result=? WHERE id=?",
                           (result["reason"], timestamp, json.dumps(result, sort_keys=True), row["id"]))

    def _get(self, db, job_id):
        row = db.execute("SELECT * FROM scheduled_jobs WHERE id=?", (job_id,)).fetchone()
        if not row: raise SchedulerError("Scheduled job not found.", "not-found")
        return dict(row)

    def run(self, job_id, trigger, scheduled_for=None, now=None):
        now = now or self.clock(); timestamp = iso(now); due_key = scheduled_for or timestamp
        run_id = str(uuid.uuid4())
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE"); job = self._get(db, job_id)
            if job["status"] == "running" and job["lease_until"] and job["lease_until"] > timestamp:
                return {"coalesced": True, "job_id": job_id, "status": "running"}, False
            old = db.execute("SELECT result FROM scheduler_runs WHERE job_id=? AND scheduled_for=?", (job_id, due_key)).fetchone()
            if old: return json.loads(old["result"]), False
            lease = iso(now + timedelta(minutes=30))
            db.execute("UPDATE scheduled_jobs SET status='running',lease_until=?,last_attempt=?,attempts=attempts+1,updated_at=? WHERE id=?",
                       (lease, timestamp, timestamp, job_id))
            db.execute("INSERT INTO scheduler_runs VALUES (?,?,?,?,? ,NULL,?,NULL,'{}')",
                       (run_id, job_id, due_key, trigger, "running", timestamp))
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{job_id}:{due_key}"))
        try:
            outcome = self.runner(job, key) or {"status": "completed"}
            status = outcome.get("status", "failed")
            if status not in RUN_STATUSES: status, outcome = "failed", {"status": "failed", "reason": "Pipeline returned an unknown state."}
            if status in ("completed", "unchanged") and self.after_run:
                try:
                    outcome["alerts"] = self.after_run(job, outcome, key)
                except Exception:
                    # The research result remains valid. Alert recovery is independently durable.
                    outcome["alert_delivery"] = {"status": "failed", "reason": "Alert scan is available for retry."}
        except Exception as error:
            message = str(error).lower()
            status = ("waiting-for-auth" if "auth" in message else "rate-limited" if "rate" in message else
                      "offline" if any(word in message for word in ("offline", "network", "connect")) else
                      "waiting-for-source" if any(word in message for word in ("source", "disclosure", "unavailable")) else "failed")
            outcome = {"status": status, "reason": "Scheduled pipeline is temporarily unavailable; retry is preserved."}
        finished = self.clock(); success = status in ("completed", "unchanged")
        retry_hours = {"waiting-for-source": 6, "offline": 2, "rate-limited": 2, "waiting-for-auth": 24,
                       "partial": 6, "failed": 6}
        future = next_due(job["kind"], finished) if success else finished + timedelta(hours=retry_hours.get(status, 6))
        result = {"id": run_id, "job_id": job_id, "scheduled_for": due_key, "trigger": trigger,
                  "status": status, "reason": outcome.get("reason"), "started_at": timestamp,
                  "finished_at": iso(finished), "pipeline": outcome}
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE scheduler_runs SET status=?,reason=?,finished_at=?,result=? WHERE id=?",
                       (status, result["reason"], result["finished_at"], json.dumps(result, sort_keys=True), run_id))
            db.execute("""UPDATE scheduled_jobs SET status=?,next_due=?,last_success=?,lease_until=NULL,
                          waiting_reason=?,updated_at=? WHERE id=?""",
                       ("scheduled" if success else status, iso(future), result["finished_at"] if success else job["last_success"],
                        None if success else result["reason"], result["finished_at"], job_id))
        return result, True

    def run_manual(self, job_id, request_key, now=None):
        with self.store.connect() as db:
            prior = db.execute("SELECT run_id,job_id FROM scheduler_requests WHERE request_key=?", (request_key,)).fetchone()
            if prior:
                if prior["job_id"] != job_id: raise SchedulerError("Request key already belongs to another scheduled job.", "conflict")
                row = db.execute("SELECT result FROM scheduler_runs WHERE id=?", (prior["run_id"],)).fetchone()
                return json.loads(row["result"]), False
        result, created = self.run(job_id, "manual", scheduled_for=f"manual:{request_key}", now=now)
        if created:
            with self.store.connect() as db: db.execute("INSERT INTO scheduler_requests VALUES (?,?,?)", (request_key, job_id, result["id"]))
        return result, created

    def run_due(self, trigger="scheduled", now=None):
        now = now or self.clock(); timestamp = iso(now)
        with self.store.connect() as db:
            due = [(row["id"], row["next_due"]) for row in db.execute(
                "SELECT id,next_due FROM scheduled_jobs WHERE next_due<=? AND status!='running' ORDER BY next_due,id", (timestamp,))]
        return [self.run(job_id, trigger, scheduled_for=scheduled_for, now=now)[0] for job_id, scheduled_for in due]

    def jobs(self):
        with self.store.connect() as db: return [dict(row) for row in db.execute("SELECT * FROM scheduled_jobs ORDER BY symbol,kind")]

    def history(self, job_id=None):
        with self.store.connect() as db:
            rows = db.execute("SELECT result FROM scheduler_runs" + (" WHERE job_id=?" if job_id else "") + " ORDER BY started_at DESC LIMIT 100",
                              (job_id,) if job_id else ()).fetchall()
        return [json.loads(row[0]) for row in rows]
