"""Fixture research service shared by HTTP UI and CLI; durable note publication."""

import json
import uuid
from pathlib import Path
from urllib.parse import quote

from .fixtures import fixture_snapshot, search
from .store import Store, now
from .vault import NoteConflict, Vault, digest


class ResearchError(Exception):
    def __init__(self, code, message, candidates=None):
        self.code, self.message, self.candidates = code, message, candidates or []
        super().__init__(message)


def note_content(snapshot):
    security = snapshot["security"]
    lines = ["---", 'mode: "fixture"', f'symbol: "{security["symbol"]}"',
             f'run_id: "{snapshot["run_id"]}"', f'saved_at: "{snapshot["saved_at"]}"', "---", "",
             f'# {security["symbol"]} — fixture research snapshot', "", f'> {snapshot["notice"]}', "",
             f'**Company identity:** {security["name"]} ({security["exchange"]})',
             f'**Demo period:** {snapshot["period"]}', "", snapshot["summary"], "",
             "## Synthetic metrics", "", "| Metric | Value | Unit |", "|---|---|---|"]
    for metric in snapshot["metrics"]:
        lines.append(f'| {metric["label"]} | {metric["value"]} | {metric["unit"]} |')
    lines += ["", "## Evidence", ""]
    for evidence in snapshot["evidence"]:
        lines += [f'- **{evidence["id"]}** — {evidence["title"]}',
                  f'  - Location: {evidence["locator"]}',
                  f'  - Facts: {json.dumps(evidence["facts"], sort_keys=True)}']
    lines += ["", "## Calculation lineage", ""]
    lines += [f'- {m["label"]}: {m["formula"]}; evidence: {m["evidence_id"]}' for m in snapshot["metrics"]]
    lines += ["", "## Not yet available", ""] + [f'- {item}' for item in snapshot["missing"]]
    lines += ["", "No research score, confidence estimate or trading recommendation is assigned to this fixture.", "",
              "This is a dated generated snapshot. New runs create new files; existing notes are not overwritten.", ""]
    return "\n".join(lines)


class ResearchService:
    def __init__(self, store: Store, vault_dir: Path):
        self.store, self.vault = store, Vault(vault_dir)
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS fixture_securities (
                    id TEXT PRIMARY KEY, symbol TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                    exchange TEXT NOT NULL CHECK(exchange='NSE')
                );
                CREATE TABLE IF NOT EXISTS fixture_watchlist (
                    security_id TEXT PRIMARY KEY REFERENCES fixture_securities(id), added_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fixture_research_runs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                    security_id TEXT NOT NULL REFERENCES fixture_securities(id),
                    status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    snapshot TEXT NOT NULL, note_text TEXT NOT NULL, note_path TEXT NOT NULL,
                    note_hash TEXT NOT NULL, vault_root TEXT NOT NULL
                );
            """)

    def submit(self, query: str, request_key: str):
        resolution = search(query)
        if resolution["status"] != "resolved":
            ambiguous = resolution["status"] == "ambiguous"
            raise ResearchError("ambiguous" if ambiguous else "not-found",
                                "Choose a company from the matching fixtures." if ambiguous else
                                "No matching fixture. Try HAL, BEL or BHEL; live NSE search comes next.", resolution["candidates"])
        security = resolution["candidates"][0]
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT id,security_id FROM fixture_research_runs WHERE request_key=?", (request_key,)).fetchone()
            if old:
                if old["security_id"] != security["security_id"]:
                    raise ResearchError("key-conflict", "This request key was already used for another company.")
                return old["id"], False
            if db.execute("SELECT COUNT(*) FROM fixture_research_runs WHERE status='publishing'").fetchone()[0] >= 8:
                raise ResearchError("queue-full", "The local research queue is full. Try again shortly.")
            run_id, timestamp = str(uuid.uuid4()), now()
            snapshot = fixture_snapshot(security, run_id, timestamp)
            content = note_content(snapshot)
            note_path = f'Graph Stock/Fixtures/{security["symbol"]}/{run_id}.md'
            db.execute("INSERT OR IGNORE INTO fixture_securities VALUES (?,?,?,?)",
                       (security["security_id"], security["symbol"], security["name"], security["exchange"]))
            db.execute("INSERT OR IGNORE INTO fixture_watchlist VALUES (?,?)", (security["security_id"], timestamp))
            db.execute("INSERT INTO fixture_research_runs VALUES (?,?,?,'publishing',?,?,?,?,?,?,?)",
                       (run_id, request_key, security["security_id"], timestamp, timestamp, json.dumps(snapshot),
                        content, note_path, digest(content), str(self.vault.root)))
        return run_id, True

    def pending(self):
        with self.store.connect() as db:
            return [r[0] for r in db.execute("SELECT id FROM fixture_research_runs WHERE status='publishing'")]

    def publish(self, run_id):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM fixture_research_runs WHERE id=?", (run_id,)).fetchone()
        if not row or row["status"] != "publishing":
            return
        try:
            if row["vault_root"] != str(self.vault.root):
                raise OSError("Vault configuration changed; original destination is required")
            self.vault.publish(row["note_path"], row["note_text"])
            status = "completed"
        except NoteConflict:
            status = "note-conflict"
        except (OSError, ValueError, UnicodeError):
            status = "publication-failed"
        with self.store.connect() as db:
            db.execute("UPDATE fixture_research_runs SET status=?,updated_at=? WHERE id=? AND status='publishing'",
                       (status, now(), run_id))

    def retry(self, run_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM fixture_research_runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            if row[0] in ("publishing", "completed"):
                return False
            if db.execute("SELECT COUNT(*) FROM fixture_research_runs WHERE status='publishing'").fetchone()[0] >= 8:
                raise ResearchError("queue-full", "The local research queue is full. Try again shortly.")
            db.execute("UPDATE fixture_research_runs SET status='publishing',updated_at=? WHERE id=?", (now(), run_id))
            return True

    def get(self, run_id):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM fixture_research_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise KeyError(run_id)
        messages = {
            "publishing": "Saving the fixture snapshot and research note…",
            "completed": "Fixture snapshot saved. Reopen it from your watchlist at any time.",
            "note-conflict": "An existing note has different content. It was preserved. Move it aside yourself before retrying, or create a new snapshot.",
            "publication-failed": "The snapshot is saved, but its note could not be published. Check the configured test vault, then retry.",
        }
        integrity = "unavailable"
        if row["vault_root"] == str(self.vault.root):
            try:
                integrity = "verified" if digest(self.vault.read(row["note_path"])) == row["note_hash"] else "modified"
            except (OSError, ValueError, UnicodeError):
                pass
        return {"id": row["id"], "status": row["status"], "created_at": row["created_at"],
                "updated_at": row["updated_at"], "message": messages[row["status"]],
                "snapshot": json.loads(row["snapshot"]),
                "note": {"relative_path": row["note_path"], "sha256": row["note_hash"], "integrity": integrity,
                         "obsidian_uri": "obsidian://open?path=" + quote(str(self.vault.root / row["note_path"]), safe="")
                         if integrity in ("verified", "modified") else None}}

    def read_note(self, run_id):
        run = self.get(run_id)
        if run["note"]["integrity"] == "unavailable":
            raise FileNotFoundError("Note unavailable in the configured vault")
        return self.vault.read(run["note"]["relative_path"])

    def watchlist(self):
        with self.store.connect() as db:
            rows = db.execute("""SELECT s.*,w.added_at FROM fixture_watchlist w
                                 JOIN fixture_securities s ON s.id=w.security_id ORDER BY w.added_at DESC""").fetchall()
            result = []
            for row in rows:
                runs = [dict(r) for r in db.execute("""SELECT id,status,created_at FROM fixture_research_runs
                    WHERE security_id=? ORDER BY created_at DESC, rowid DESC LIMIT 30""", (row["id"],))]
                result.append({**dict(row), "mode": "fixture", "runs": runs})
            return result
