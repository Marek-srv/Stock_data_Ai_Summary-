"""Versioned fact corrections and verified local backup/restore."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
import zipfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath

from .financials import FORMULA_VERSION, calculate_metrics
from .vault import NoteConflict, Vault, digest

SCHEMA_VERSION = "research-history/v1"
BACKUP_VERSION = "graph-stock-backup/v1"
START = "<!-- graph-stock:generated:start -->"
END = "<!-- graph-stock:generated:end -->"


class HistoryError(Exception):
    def __init__(self, message, code="invalid"):
        self.message, self.code = message, code
        super().__init__(message)


def _now(): return datetime.now(timezone.utc).isoformat()
def _hash_bytes(value): return hashlib.sha256(value).hexdigest()


def correction_rows(db, target_ids):
    """Return the newest immutable correction for each requested fact ID."""
    if not target_ids:
        return {}
    try:
        placeholders = ",".join("?" for _ in target_ids)
        rows = db.execute(f"""SELECT * FROM fact_corrections WHERE target_id IN ({placeholders})
            ORDER BY target_id,version DESC""", tuple(target_ids)).fetchall()
    except sqlite3.OperationalError:
        return {}
    result = {}
    for row in rows:
        result.setdefault(row["target_id"], dict(row))
    return result


def apply_fact_corrections(db, facts):
    rows = correction_rows(db, [item["id"] for item in facts])
    corrected = []
    for original in facts:
        item = dict(original)
        row = rows.get(item["id"])
        if row:
            payload = json.loads(row["corrected_payload"])
            item.update(payload)
            item["correction"] = {"id": row["id"], "version": row["version"],
                                  "reason": row["reason"], "created_at": row["created_at"],
                                  "supersedes_id": row["supersedes_id"]}
        corrected.append(item)
    return corrected, [row["id"] for row in rows.values()]


def correction_descriptor(store, source_id):
    try:
        with store.connect() as db:
            rows = db.execute("""SELECT id,target_id,version,corrected_payload FROM fact_corrections
                WHERE source_id=? ORDER BY target_id,version""", (source_id,)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    values = [dict(row) for row in rows]
    return {"schema_version": SCHEMA_VERSION, "corrections": values,
            "digest": hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()}


def _paths(value):
    if isinstance(value, dict):
        for item in value.values(): yield from _paths(item)
    elif isinstance(value, list):
        for item in value: yield from _paths(item)
    elif isinstance(value, str) and value.startswith("Graph Stock/"):
        path = PurePosixPath(value)
        if not path.is_absolute() and ".." not in path.parts:
            yield value


def referenced_paths(database):
    """Discover vault references from a frozen SQLite snapshot."""
    result = set()
    db = sqlite3.connect(database); db.row_factory = sqlite3.Row
    try:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            for row in db.execute(f"SELECT * FROM {quoted}"):
                for raw in row:
                    if not isinstance(raw, str): continue
                    result.update(_paths(raw))
                    if raw[:1] in ("{", "["):
                        try: result.update(_paths(json.loads(raw)))
                        except (json.JSONDecodeError, TypeError): pass
    finally:
        db.close()
    return sorted(result)


def _render_correction(correction):
    old, new = correction["previous"], correction["corrected"]
    return (f"# Fact correction — {correction['symbol']}\n\nCorrection: `{correction['id']}`  \n"
            f"Version: `{correction['version']}`  \nCreated: `{correction['created_at']}`  \n"
            f"Author: `{correction['author']}`\n\n## Change\n\n"
            f"**{old['label']} · {old['period']}** changed from `{old.get('value')} {old['unit']}` "
            f"to `{new.get('value')} {new['unit']}`.\n\nReason: {correction['reason']}\n\n"
            f"Previous evidence: `{old['evidence_id']}`  \nCorrection evidence: `{new['evidence_id']}`\n\n"
            "The source fact and earlier reports remain immutable. Current views apply this superseding correction.\n")


def _generated(corrections):
    rows = [START, "", "## Current generated corrections", ""]
    if not corrections: rows.append("No corrections.")
    for item in corrections:
        rows.append(f"- **{item['corrected']['label']} · {item['corrected']['period']}**: "
                    f"`{item['previous'].get('value')}` → `{item['corrected'].get('value')} {item['corrected']['unit']}` "
                    f"— {item['reason']} (`{item['id']}`)")
    rows += ["", END]
    return "\n".join(rows)


class HistoryService:
    def __init__(self, store, vault_dir, state_dir=None):
        self.store, self.vault = store, Vault(vault_dir)
        self.state_dir = Path(state_dir or store.path.parent)
        self.backup_root = self.state_dir / "backups"
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS fact_corrections (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL, source_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    version INTEGER NOT NULL, supersedes_id TEXT, previous_payload TEXT NOT NULL,
                    corrected_payload TEXT NOT NULL, evidence_id TEXT NOT NULL, reason TEXT NOT NULL,
                    author TEXT NOT NULL, created_at TEXT NOT NULL, publication_status TEXT NOT NULL,
                    note_path TEXT NOT NULL, note_hash TEXT NOT NULL,
                    UNIQUE(target_id,version)
                );
                CREATE TABLE IF NOT EXISTS artifact_invalidations (
                    correction_id TEXT NOT NULL, record_type TEXT NOT NULL, record_id TEXT NOT NULL,
                    disposition TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(correction_id,record_type,record_id)
                );
                CREATE TABLE IF NOT EXISTS correction_index_state (
                    symbol TEXT PRIMARY KEY, note_path TEXT NOT NULL, generated_hash TEXT NOT NULL,
                    status TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS backup_runs (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL,
                    path TEXT NOT NULL, manifest TEXT NOT NULL, error TEXT
                );
            """)
        self.recover()

    def _base_fact(self, target_id):
        with self.store.connect() as db:
            row = db.execute("SELECT source_id,payload FROM financial_facts WHERE id=?", (target_id,)).fetchone()
            if not row: raise HistoryError("Financial fact not found.", "not-found")
            source = db.execute("SELECT symbol FROM filing_sources WHERE id=?", (row["source_id"],)).fetchone()
        if not source: raise HistoryError("Fact source not found.", "not-found")
        return row["source_id"], source["symbol"], json.loads(row["payload"])

    def correct_fact(self, target_id, corrected_value, evidence_id, reason, request_key, author="local-user"):
        try: normalized = format(Decimal(corrected_value), "f")
        except (InvalidOperation, TypeError): raise HistoryError("Corrected value must be a finite number.") from None
        if not Decimal(normalized).is_finite(): raise HistoryError("Corrected value must be finite.")
        source_id, symbol, base = self._base_fact(target_id)
        with self.store.connect() as db:
            prior_request = db.execute("SELECT id,target_id,corrected_payload,evidence_id,reason FROM fact_corrections WHERE request_key=?", (request_key,)).fetchone()
            if prior_request:
                prior_value = json.loads(prior_request["corrected_payload"])["value"]
                if (prior_request["target_id"] != target_id or prior_value != normalized or
                        prior_request["evidence_id"] != evidence_id or prior_request["reason"] != reason):
                    raise HistoryError("Request key belongs to another correction.", "conflict")
                return self.get_correction(prior_request["id"]), False
            latest = db.execute("SELECT * FROM fact_corrections WHERE target_id=? ORDER BY version DESC LIMIT 1", (target_id,)).fetchone()
            previous = json.loads(latest["corrected_payload"]) if latest else base
            version, supersedes = (latest["version"] + 1, latest["id"]) if latest else (1, None)
            corrected = dict(previous); corrected.update({"value": normalized, "reported_value": normalized,
                "evidence_id": evidence_id, "corrected_from_evidence_id": previous["evidence_id"]})
            correction_id, created = str(uuid.uuid4()), _now()
            value = {"id": correction_id, "schema_version": SCHEMA_VERSION, "target_type": "financial-fact",
                     "target_id": target_id, "source_id": source_id, "symbol": symbol, "version": version,
                     "supersedes_id": supersedes, "previous": previous, "corrected": corrected,
                     "evidence_id": evidence_id, "reason": reason, "author": author, "created_at": created}
            note_path = f"Graph Stock/Corrections/{symbol}/{correction_id}.md"; content = _render_correction(value)
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO fact_corrections VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                correction_id, request_key, "financial-fact", target_id, source_id, symbol, version, supersedes,
                json.dumps(previous, sort_keys=True), json.dumps(corrected, sort_keys=True), evidence_id, reason,
                author, created, "pending", note_path, digest(content)))
            self._record_impacts(db, value)
        self._publish(correction_id)
        return self.get_correction(correction_id), True

    def _record_impacts(self, db, correction):
        timestamp, target, symbol, source_id = correction["created_at"], correction["target_id"], correction["symbol"], correction["source_id"]
        impacts = []
        for row in db.execute("SELECT id,snapshot FROM financial_jobs WHERE source_id=? AND snapshot IS NOT NULL", (source_id,)):
            if target in [item["id"] for item in json.loads(row["snapshot"])["facts"]]:
                impacts.append(("financial-report", row["id"], "stale", "A source fact now has a superseding correction."))
        try:
            for row in db.execute("SELECT id FROM update_runs WHERE symbol=? AND status='completed'", (symbol,)):
                impacts.append(("research-report", row["id"], "stale", "Rebuild current research with the corrected fact."))
        except sqlite3.OperationalError: pass
        try:
            for row in db.execute("SELECT id,result FROM feature_snapshots WHERE symbol=?", (symbol,)):
                if target in row["result"]:
                    impacts.append(("feature-snapshot", row["id"], "preserved", "Historical vintage remains reconstructable and is not rewritten."))
        except sqlite3.OperationalError: pass
        for kind, record_id, disposition, reason in impacts:
            db.execute("INSERT OR IGNORE INTO artifact_invalidations VALUES (?,?,?,?,?,?)",
                       (correction["id"], kind, record_id, disposition, reason, timestamp))

    def _publish_index(self, symbol, correction_id):
        corrections = self.corrections(symbol); generated = _generated(corrections)
        path = f"Graph Stock/Corrections/{symbol}/Current corrections.md"
        with self.store.connect() as db:
            state = db.execute("SELECT * FROM correction_index_state WHERE symbol=?", (symbol,)).fetchone()
        if not state:
            content = f"# Current corrections — {symbol}\n\n{generated}\n\nAdd personal notes outside the generated markers.\n"
            try: self.vault.publish(path, content)
            except NoteConflict:
                return self._conflict(symbol, correction_id, generated, "Existing index is not managed by graph_stock.")
        else:
            try: existing = self.vault.read(path)
            except (OSError, ValueError, UnicodeError):
                return self._conflict(symbol, correction_id, generated, "Managed index is unavailable.")
            start, end = existing.find(START), existing.find(END)
            if start < 0 or end < start:
                return self._conflict(symbol, correction_id, generated, "Generated markers were removed.")
            end += len(END); actual = existing[start:end]
            if digest(actual) != state["generated_hash"]:
                return self._conflict(symbol, correction_id, generated, "The generated section was edited.")
            content = existing[:start] + generated + existing[end:]
            self._replace(path, content)
        with self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO correction_index_state VALUES (?,?,?,?,?)",
                       (symbol, path, digest(generated), "published", _now()))
        return "published"

    def _replace(self, relative, content):
        with self.vault.parent(relative, create=True) as (parent, name):
            temporary = f".graph-stock-history-{uuid.uuid4()}.tmp"
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(content.encode()); handle.flush(); os.fsync(handle.fileno())
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent); os.fsync(parent)
            finally:
                try: os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError: pass

    def _conflict(self, symbol, correction_id, generated, reason):
        path = f"Graph Stock/Corrections/{symbol}/Conflicts/{correction_id}.md"
        self.vault.publish(path, f"# Correction index conflict — {symbol}\n\n{reason}\n\n{generated}\n")
        with self.store.connect() as db:
            db.execute("UPDATE correction_index_state SET status='conflict',updated_at=? WHERE symbol=?", (_now(), symbol))
        return "conflict-copy"

    def _publish(self, correction_id):
        correction = self.get_correction(correction_id, integrity=False); content = _render_correction(correction)
        try:
            self.vault.publish(correction["note"]["path"], content)
            status = self._publish_index(correction["symbol"], correction_id)
        except (OSError, ValueError, UnicodeError): status = "publication-failed"
        except NoteConflict: status = "preserved-user-text"
        with self.store.connect() as db:
            db.execute("UPDATE fact_corrections SET publication_status=? WHERE id=?", (status, correction_id))
        return status

    def recover(self):
        with self.store.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM fact_corrections WHERE publication_status IN ('pending','publication-failed') ORDER BY created_at")]
        for correction_id in ids: self._publish(correction_id)

    def get_correction(self, correction_id, integrity=True):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM fact_corrections WHERE id=?", (correction_id,)).fetchone()
            impacts = [dict(item) for item in db.execute("SELECT * FROM artifact_invalidations WHERE correction_id=? ORDER BY record_type,record_id", (correction_id,))]
        if not row: raise HistoryError("Correction not found.", "not-found")
        result = {key: row[key] for key in ("id", "target_type", "target_id", "source_id", "symbol", "version", "supersedes_id", "evidence_id", "reason", "author", "created_at", "publication_status")}
        result.update({"schema_version": SCHEMA_VERSION, "previous": json.loads(row["previous_payload"]),
                       "corrected": json.loads(row["corrected_payload"]), "impacts": impacts})
        state = "unavailable"
        if integrity:
            try: state = "verified" if digest(self.vault.read(row["note_path"])) == row["note_hash"] else "modified"
            except (OSError, ValueError, UnicodeError): pass
        result["note"] = {"path": row["note_path"], "sha256": row["note_hash"], "integrity": state}
        return result

    def corrections(self, symbol=None):
        with self.store.connect() as db:
            rows = db.execute("SELECT id FROM fact_corrections" + (" WHERE symbol=?" if symbol else "") + " ORDER BY created_at DESC",
                              (symbol.upper(),) if symbol else ()).fetchall()
        return [self.get_correction(row[0]) for row in rows]

    def current_financial(self, run_id):
        with self.store.connect() as db:
            row = db.execute("SELECT id,snapshot,note_path,note_hash FROM financial_jobs WHERE id=? AND snapshot IS NOT NULL", (run_id,)).fetchone()
            if not row: raise HistoryError("Financial run not found.", "not-found")
            original = json.loads(row["snapshot"]); facts, correction_ids = apply_fact_corrections(db, original["facts"])
        return {"schema_version": SCHEMA_VERSION, "base_run_id": run_id,
                "base_artifact": {"path": row["note_path"], "sha256": row["note_hash"]},
                "original": {"facts": original["facts"], "metrics": original["metrics"]},
                "current": {"facts": facts, "metrics": calculate_metrics(facts), "formula_version": FORMULA_VERSION},
                "correction_ids": correction_ids}

    def read_correction(self, correction_id):
        correction = self.get_correction(correction_id)
        return self.vault.read(correction["note"]["path"])

    def create_backup(self):
        backup_id, created = str(uuid.uuid4()), _now(); final = self.backup_root / backup_id; temporary = self.backup_root / ("." + backup_id)
        self.backup_root.mkdir(parents=True, exist_ok=True); temporary.mkdir()
        try:
            databases = []
            for source in sorted(self.state_dir.glob("*.sqlite3")):
                destination = temporary / source.name
                source_db, destination_db = sqlite3.connect(source), sqlite3.connect(destination)
                try: source_db.backup(destination_db)
                finally: source_db.close(); destination_db.close()
                databases.append({"name": source.name, "sha256": _hash_bytes(destination.read_bytes()), "size": destination.stat().st_size})
            main = temporary / self.store.path.name
            artifacts = []
            for relative in referenced_paths(main):
                try:
                    with self.vault.parent(relative) as (parent, name): data = self.vault.read_at(parent, name, binary=True)
                except (OSError, ValueError, UnicodeError):
                    raise HistoryError(f"Referenced vault artifact is unavailable: {relative}", "incomplete") from None
                target = temporary / "vault" / PurePosixPath(relative); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
                artifacts.append({"path": relative, "sha256": _hash_bytes(data), "size": len(data)})
            manifest = {"schema_version": BACKUP_VERSION, "id": backup_id, "created_at": created,
                        "databases": databases, "artifacts": artifacts}
            (temporary / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
            temporary.rename(final)
            archive = shutil.make_archive(str(final), "zip", root_dir=final)
            with self.store.connect() as db:
                db.execute("INSERT INTO backup_runs VALUES (?,?,?,?,?,NULL)", (backup_id, created, "verified", archive, json.dumps(manifest, sort_keys=True)))
            return {**manifest, "status": "verified", "archive": archive}
        except Exception as error:
            shutil.rmtree(temporary, ignore_errors=True)
            if isinstance(error, HistoryError): raise
            raise HistoryError("Backup could not be completed.", "backup-failed") from error

    def backups(self):
        with self.store.connect() as db: rows = db.execute("SELECT id,created_at,status,path,manifest,error FROM backup_runs ORDER BY created_at DESC").fetchall()
        return [{**dict(row), "manifest": json.loads(row["manifest"])} for row in rows]

    def backup_path(self, backup_id):
        with self.store.connect() as db: row = db.execute("SELECT path FROM backup_runs WHERE id=? AND status='verified'", (backup_id,)).fetchone()
        if not row or not Path(row["path"]).is_file(): raise HistoryError("Verified backup not found.", "not-found")
        return Path(row["path"])

    def restore(self, backup_id):
        archive = self.backup_path(backup_id); destination = self.state_dir / "restores" / str(uuid.uuid4())
        destination.mkdir(parents=True)
        try:
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.infolist():
                    path = PurePosixPath(member.filename)
                    if path.is_absolute() or ".." in path.parts: raise HistoryError("Backup contains an unsafe path.", "invalid-backup")
                bundle.extractall(destination)
            manifest = json.loads((destination / "manifest.json").read_text())
            if manifest.get("schema_version") != BACKUP_VERSION: raise HistoryError("Backup schema is unsupported.", "invalid-backup")
            for item in manifest["databases"]:
                data = (destination / item["name"]).read_bytes()
                if _hash_bytes(data) != item["sha256"]: raise HistoryError("Restored database hash differs.", "invalid-backup")
            for item in manifest["artifacts"]:
                data = (destination / "vault" / PurePosixPath(item["path"])).read_bytes()
                if _hash_bytes(data) != item["sha256"]: raise HistoryError("Restored artifact hash differs.", "invalid-backup")
            missing = set(referenced_paths(destination / self.store.path.name)) - {item["path"] for item in manifest["artifacts"]}
            if missing: raise HistoryError("Restored database has missing artifact references.", "invalid-backup")
            return {"backup_id": backup_id, "status": "verified", "restore_path": str(destination),
                    "database_count": len(manifest["databases"]), "artifact_count": len(manifest["artifacts"])}
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise
