"""Traceable, deduplicated dashboard and Obsidian material alerts."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .vault import NoteConflict, Vault, digest

SCHEMA_VERSION = "material-alert/v1"
POLICY_VERSION = "alert-materiality/v1"
SEVERITIES = {"low": 1, "medium": 2, "high": 3, "critical": 4}
DEFAULT_CONFIG = {"minimum_severity": "medium", "material_only": True}
POLICY = {
    "version": POLICY_VERSION,
    "severity_order": list(SEVERITIES),
    "thesis": {"medium": "changed thesis or score change from 5 points", "high": "score change from 15 points"},
    "ownership": {"medium": "comparable change from 0.5 percentage points", "high": "change from 1 percentage point"},
    "paper_risk": {"medium": "degradation policy trigger", "high": "paper drawdown from 20 percent"},
    "default_delivery": "material events at or above configured severity",
}


class AlertError(Exception):
    def __init__(self, message, code="invalid"):
        self.message, self.code = message, code
        super().__init__(message)


def _now(): return datetime.now(timezone.utc).isoformat()
def _hash(value): return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _render(alert):
    comparison = json.dumps(alert["comparison"], indent=2, sort_keys=True)
    sources = "\n".join(f"- `{item}`" for item in alert["source"]["evidence_ids"]) or "- No evidence IDs"
    return (f"# {alert['severity'].title()} alert — {alert['symbol']}\n\n"
            f"Alert: `{alert['id']}`  \nRule: `{alert['rule_version']}`  \n"
            f"Category: `{alert['category']}`  \nAs of: `{alert['as_of']}`\n\n"
            f"## Change\n\n{alert['summary']}\n\n## Evidence\n\n{sources}\n\n"
            f"Source record: `{alert['source']['type']}:{alert['source']['id']}`\n\n"
            f"## Comparison baseline\n\n```json\n{comparison}\n```\n\n"
            f"## Next action\n\n{alert['next_action']}\n\n"
            "This generated alert is immutable. Add personal notes anywhere in this file; graph_stock will preserve them.\n")


class AlertService:
    def __init__(self, store, vault_dir):
        self.store, self.vault = store, Vault(vault_dir)
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS alert_config (
                    id INTEGER PRIMARY KEY CHECK(id=1), policy_version TEXT NOT NULL,
                    minimum_severity TEXT NOT NULL, material_only INTEGER NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY, dedup_key TEXT UNIQUE NOT NULL, symbol TEXT NOT NULL,
                    category TEXT NOT NULL, severity TEXT NOT NULL, material INTEGER NOT NULL,
                    created_at TEXT NOT NULL, as_of TEXT NOT NULL, payload TEXT NOT NULL,
                    publication_status TEXT NOT NULL, note_path TEXT NOT NULL, note_hash TEXT NOT NULL,
                    acknowledged_at TEXT, acknowledgement TEXT
                );
                CREATE TABLE IF NOT EXISTS alert_deliveries (
                    alert_id TEXT NOT NULL, attempt INTEGER NOT NULL, destination TEXT NOT NULL,
                    status TEXT NOT NULL, attempted_at TEXT NOT NULL, detail TEXT,
                    PRIMARY KEY(alert_id,attempt,destination)
                );
                CREATE TABLE IF NOT EXISTS alert_scan_requests (
                    request_key TEXT PRIMARY KEY, symbol TEXT NOT NULL, result TEXT NOT NULL
                );
            """)
            db.execute("INSERT OR IGNORE INTO alert_config VALUES (1,?,?,?,?)",
                       (POLICY_VERSION, DEFAULT_CONFIG["minimum_severity"], int(DEFAULT_CONFIG["material_only"]), _now()))
        self.recover()

    def config(self):
        with self.store.connect() as db: row = db.execute("SELECT * FROM alert_config WHERE id=1").fetchone()
        return {"policy_version": row["policy_version"], "minimum_severity": row["minimum_severity"],
                "material_only": bool(row["material_only"]), "updated_at": row["updated_at"], "rules": POLICY}

    def configure(self, minimum_severity, material_only):
        if minimum_severity not in SEVERITIES: raise AlertError("Unknown alert severity.")
        with self.store.connect() as db:
            db.execute("UPDATE alert_config SET policy_version=?,minimum_severity=?,material_only=?,updated_at=? WHERE id=1",
                       (POLICY_VERSION, minimum_severity, int(material_only), _now()))
        return self.config()

    def _publish(self, alert_id):
        alert = self.get(alert_id, check_note=False); content = _render(alert)
        with self.store.connect() as db:
            attempt = db.execute("SELECT COALESCE(MAX(attempt),0)+1 FROM alert_deliveries WHERE alert_id=?", (alert_id,)).fetchone()[0]
        try:
            self.vault.publish(alert["note"]["path"], content); status, detail = "published", None
        except NoteConflict:
            status, detail = "preserved-user-text", "Existing alert note differs and was not overwritten."
        except (OSError, ValueError, UnicodeError):
            status, detail = "publication-failed", "Alert remains in SQLite and publication will retry."
        with self.store.connect() as db:
            db.execute("UPDATE alerts SET publication_status=? WHERE id=?", (status, alert_id))
            db.execute("INSERT INTO alert_deliveries VALUES (?,?,?,?,?,?)",
                       (alert_id, attempt, "obsidian", status, _now(), detail))
        return status

    def recover(self):
        with self.store.connect() as db:
            pending = [row[0] for row in db.execute(
                "SELECT id FROM alerts WHERE publication_status IN ('pending','publication-failed') ORDER BY created_at")]
        for alert_id in pending: self._publish(alert_id)

    def create(self, candidate):
        required = {"symbol", "category", "severity", "material", "event_version", "as_of",
                    "summary", "source", "comparison", "next_action"}
        if set(candidate) != required or candidate["severity"] not in SEVERITIES:
            raise AlertError("Alert candidate does not match the versioned schema.")
        config = self.config()
        if (config["material_only"] and not candidate["material"]) or SEVERITIES[candidate["severity"]] < SEVERITIES[config["minimum_severity"]]:
            return {"alert": None, "filtered": True, "reason": "below-configured-materiality"}, False
        dedup_key = _hash({"symbol": candidate["symbol"], "category": candidate["category"], "rule": POLICY_VERSION,
                           "event_version": candidate["event_version"]})
        with self.store.connect() as db:
            prior = db.execute("SELECT id FROM alerts WHERE dedup_key=?", (dedup_key,)).fetchone()
        if prior: return {"alert": self.get(prior["id"]), "filtered": False, "deduplicated": True}, False
        alert_id, created = str(uuid.uuid4()), _now()
        payload = {"id": alert_id, "schema_version": SCHEMA_VERSION, "rule_version": POLICY_VERSION,
                   **candidate, "created_at": created}
        path = f"Graph Stock/Alerts/{candidate['symbol']}/{alert_id}.md"; content = _render(payload)
        with self.store.connect() as db:
            try:
                db.execute("INSERT INTO alerts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)", (
                    alert_id, dedup_key, candidate["symbol"], candidate["category"], candidate["severity"],
                    int(candidate["material"]), created, candidate["as_of"], json.dumps(payload, sort_keys=True),
                    "pending", path, digest(content)))
            except sqlite3.IntegrityError:
                prior = db.execute("SELECT id FROM alerts WHERE dedup_key=?", (dedup_key,)).fetchone()
                return {"alert": self.get(prior["id"]), "filtered": False, "deduplicated": True}, False
        self._publish(alert_id)
        return {"alert": self.get(alert_id), "filtered": False, "deduplicated": False}, True

    def _candidate(self, symbol, category, severity, event_version, as_of, summary, source, comparison, next_action):
        return {"symbol": symbol, "category": category, "severity": severity, "material": severity in ("medium", "high", "critical"),
                "event_version": event_version, "as_of": as_of, "summary": summary, "source": source,
                "comparison": comparison, "next_action": next_action}

    def scan(self, symbol, request_key=None):
        symbol = symbol.upper()
        if request_key:
            with self.store.connect() as db:
                prior = db.execute("SELECT symbol,result FROM alert_scan_requests WHERE request_key=?", (request_key,)).fetchone()
            if prior:
                if prior["symbol"] != symbol: raise AlertError("Request key already belongs to another alert scan.", "conflict")
                return json.loads(prior["result"])
        candidates = []
        with self.store.connect() as db:
            try:
                rows = db.execute("""SELECT p.symbol,m.result FROM paper_monitor_runs m JOIN paper_books p ON p.id=m.book_id
                    WHERE p.symbol=? ORDER BY m.created_at DESC""", (symbol,)).fetchall()
                seen = set()
                for row in rows:
                    monitor = json.loads(row["result"]); book_id = monitor["book_id"]
                    if book_id in seen: continue
                    seen.add(book_id)
                    if monitor["status"] != "degraded": continue
                    drawdown = Decimal(monitor["paper"]["max_drawdown_percent"])
                    version = _hash({"book": book_id, "policy": monitor["policy_version"], "reasons": monitor["reasons"]})
                    candidates.append(self._candidate(symbol, "paper-risk", "high" if drawdown >= 20 else "medium", version,
                        monitor["created_at"], "Paper performance crossed a frozen degradation threshold.",
                        {"type": "paper-monitor", "id": monitor["id"], "evidence_ids": [book_id, monitor["backtest"]["validation_id"]]},
                        {"paper": monitor["paper"], "validation": monitor["backtest"], "reasons": monitor["reasons"]},
                        "Review the paper ledger and queued revalidation before allowing new entries."))
            except sqlite3.OperationalError: pass
            try:
                row = db.execute("SELECT result FROM ownership_runs WHERE symbol=? ORDER BY created_at DESC LIMIT 1", (symbol,)).fetchone()
                if row:
                    ownership = json.loads(row["result"]); material_rows = []
                    for item in ownership["comparison"]["comparisons"]:
                        change = abs(Decimal(item["percentage_point_change"])) if item.get("percentage_point_change") is not None else Decimal("0")
                        if change >= Decimal("0.5") or item["status"] in ("entry", "exit"): material_rows.append(item)
                    if material_rows:
                        high = any(abs(Decimal(item["percentage_point_change"] or "0")) >= 1 for item in material_rows)
                        version = _hash({"period": ownership["comparison"]["current_period"], "rows": material_rows})
                        candidates.append(self._candidate(symbol, "ownership", "high" if high else "medium", version,
                            max(item["published_at"] for item in ownership["sources"]), "A comparable disclosed ownership change crossed the materiality threshold.",
                            {"type": "ownership-run", "id": ownership["id"], "evidence_ids": [item["source_id"] for item in ownership["sources"]]},
                            {"baseline_period": ownership["comparison"]["prior_period"], "current_period": ownership["comparison"]["current_period"], "changes": material_rows},
                            "Inspect holder coverage and the share denominator before changing the thesis."))
            except sqlite3.OperationalError: pass
            try:
                rows = db.execute("SELECT id,updated_at,result FROM update_runs WHERE symbol=? AND status='completed' ORDER BY updated_at DESC LIMIT 2", (symbol,)).fetchall()
                if len(rows) == 2:
                    current, baseline = [dict(row) for row in rows]; current_result, baseline_result = json.loads(current["result"]), json.loads(baseline["result"])
                    thesis, old_thesis = current_result.get("investment_thesis", {}), baseline_result.get("investment_thesis", {})
                    if thesis.get("thesis_id") and thesis.get("thesis_id") != old_thesis.get("thesis_id"):
                        score = Decimal(current_result["scorecard"]["overall_score"]); old_score = Decimal(baseline_result["scorecard"]["overall_score"]); delta = score-old_score
                        candidates.append(self._candidate(symbol, "thesis", "high" if abs(delta) >= 15 else "medium", thesis["thesis_id"],
                            current_result.get("complete_snapshot", {}).get("as_of_time") or current["updated_at"], "The evidence-backed investment thesis changed from its prior completed baseline.",
                            {"type": "update-run", "id": current["id"], "evidence_ids": [old_thesis["thesis_id"], thesis["thesis_id"]]},
                            {"baseline_run_id": baseline["id"], "baseline_score": str(old_score), "current_score": str(score), "score_change": str(delta)},
                            "Review the changed thesis, weakening conditions and cited evidence."))
            except (sqlite3.OperationalError, KeyError, TypeError, InvalidOperation): pass
        created, deduplicated, filtered = [], [], []
        for candidate in candidates:
            outcome, is_new = self.create(candidate)
            if outcome["filtered"]: filtered.append({"category": candidate["category"], "reason": outcome["reason"]})
            elif is_new: created.append(outcome["alert"])
            else: deduplicated.append(outcome["alert"])
        result = {"symbol": symbol, "created": created, "deduplicated": deduplicated, "filtered": filtered,
                  "candidate_count": len(candidates), "policy_version": POLICY_VERSION}
        if request_key:
            with self.store.connect() as db: db.execute("INSERT INTO alert_scan_requests VALUES (?,?,?)", (request_key, symbol, json.dumps(result, sort_keys=True)))
        return result

    def acknowledge(self, alert_id, note=None):
        timestamp = _now()
        with self.store.connect() as db:
            if not db.execute("SELECT 1 FROM alerts WHERE id=?", (alert_id,)).fetchone(): raise AlertError("Alert not found.", "not-found")
            db.execute("UPDATE alerts SET acknowledged_at=COALESCE(acknowledged_at,?),acknowledgement=COALESCE(acknowledgement,?) WHERE id=?",
                       (timestamp, note, alert_id))
        return self.get(alert_id)

    def get(self, alert_id, check_note=True):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
            deliveries = [dict(item) for item in db.execute("SELECT * FROM alert_deliveries WHERE alert_id=? ORDER BY attempt", (alert_id,))]
        if not row: raise AlertError("Alert not found.", "not-found")
        result = json.loads(row["payload"]); integrity = "unavailable"
        if check_note:
            try: integrity = "verified" if digest(self.vault.read(row["note_path"])) == row["note_hash"] else "modified"
            except (OSError, ValueError, UnicodeError): pass
        result.update({"publication_status": row["publication_status"], "acknowledged_at": row["acknowledged_at"],
                       "acknowledgement": row["acknowledgement"], "deliveries": deliveries,
                       "note": {"path": row["note_path"], "sha256": row["note_hash"], "integrity": integrity}})
        return result

    def recent(self, symbol=None):
        with self.store.connect() as db:
            rows = db.execute("SELECT id FROM alerts" + (" WHERE symbol=?" if symbol else "") + " ORDER BY created_at DESC LIMIT 100",
                              (symbol.upper(),) if symbol else ()).fetchall()
        return [self.get(row[0]) for row in rows]

    def read_note(self, alert_id):
        alert = self.get(alert_id)
        return self.vault.read(alert["note"]["path"])
