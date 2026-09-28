"""SQLite run journal; accepted results are immutable and retries retain identity."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .reasoning import MESSAGES, Outcome


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0, version TEXT, auth_method TEXT,
                    result TEXT, usage TEXT NOT NULL DEFAULT '{}', event_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    run_id TEXT NOT NULL, number INTEGER NOT NULL, status TEXT NOT NULL,
                    started_at TEXT NOT NULL, finished_at TEXT,
                    PRIMARY KEY (run_id, number), FOREIGN KEY (run_id) REFERENCES runs(id)
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE attempts SET status='interrupted', finished_at=? WHERE status='running'", (now(),))
            db.execute("UPDATE runs SET status='interrupted', updated_at=? WHERE status IN ('running','queued')", (now(),))

    def create(self, key):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT id FROM runs WHERE request_key=?", (key,)).fetchone()
            if existing:
                return existing["id"], False
            count = db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0]
            if count >= 8:
                raise OverflowError("Queue full")
            run_id, timestamp = str(uuid.uuid4()), now()
            db.execute("INSERT INTO runs(id,request_key,status,created_at,updated_at) VALUES (?,?,'queued',?,?)",
                       (run_id, key, timestamp, timestamp))
            return run_id, True

    def retry(self, run_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            if row["status"] in ("completed", "running", "queued"):
                return False
            count = db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0]
            if count >= 8:
                raise OverflowError("Queue full")
            db.execute("UPDATE runs SET status='queued', updated_at=? WHERE id=?", (now(), run_id))
            return True

    def claim(self, run_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT attempt, status FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row or row["status"] != "queued":
                return False
            attempt, timestamp = row["attempt"] + 1, now()
            db.execute("UPDATE runs SET status='running', attempt=?, updated_at=? WHERE id=?", (attempt, timestamp, run_id))
            db.execute("INSERT INTO attempts VALUES (?,?,'running',?,NULL)", (run_id, attempt, timestamp))
            return True

    def finish(self, run_id, outcome: Outcome):
        if outcome.status not in MESSAGES:
            raise ValueError("Unknown outcome")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT attempt,status FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row or row["status"] != "running":
                return
            timestamp = now()
            db.execute("""UPDATE runs SET status=?, updated_at=?, version=?, auth_method=?,
                       result=?, usage=?, event_count=? WHERE id=?""",
                       (outcome.status, timestamp, outcome.version, outcome.auth_method,
                        json.dumps(outcome.result) if outcome.result else None,
                        json.dumps(outcome.usage), outcome.event_count, run_id))
            db.execute("UPDATE attempts SET status=?, finished_at=? WHERE run_id=? AND number=?",
                       (outcome.status, timestamp, run_id, row["attempt"]))

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            result = dict(row)
            result.pop("request_key")
            result["result"] = json.loads(result["result"]) if result["result"] else None
            result["usage"] = json.loads(result["usage"])
            result["message"] = MESSAGES[result["status"]]
            result["attempts"] = [dict(r) for r in db.execute(
                "SELECT number,status,started_at,finished_at FROM attempts WHERE run_id=? ORDER BY number", (run_id,))]
            return result

    def recent(self):
        with self.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM runs ORDER BY created_at DESC LIMIT 30")]
        return [self.get(run_id) for run_id in ids]
