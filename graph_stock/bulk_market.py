"""Official NSE bulk daily history with cached sessions and bounded materialization."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import ssl
import sqlite3
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

import certifi

from .filings import parse_directory
from .vault import Vault, digest


SCHEMA_VERSION = "nse-bulk-market-history/v1"
PROVIDER_VERSION = "nse-cm-udiff-bhavcopy/v1"
ARCHIVE_HOST = "archives.nseindia.com"
REPORT_PAGE = "https://www.nseindia.com/all-reports"
MAX_ZIP_BYTES = 5_000_000
MAX_CSV_BYTES = 12_000_000


class BulkMarketError(RuntimeError):
    def __init__(self, message, code="invalid"):
        self.message, self.code = message, code
        super().__init__(message)


@dataclass(frozen=True)
class Payload:
    content: bytes
    url: str
    retrieved_at: str


def _now(): return datetime.now(timezone.utc).isoformat()
def _sha(value): return hashlib.sha256(value).hexdigest()


def _positive(value, field):
    try: parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError): raise BulkMarketError(f"{field} is not a decimal.") from None
    if not parsed.is_finite() or parsed <= 0: raise BulkMarketError(f"{field} must be positive.")
    return format(parsed, "f")


def _volume(value):
    try: parsed = int(value)
    except (TypeError, ValueError): raise BulkMarketError("Bhavcopy volume is invalid.") from None
    if parsed < 0: raise BulkMarketError("Bhavcopy volume is invalid.")
    return parsed


def parse_bhavcopy(content, session):
    expected_name = f"BhavCopy_NSE_CM_0_0_0_{session.replace('-', '')}_F_0000.csv"
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            if len(files) != 1 or files[0].filename != expected_name or files[0].file_size > MAX_CSV_BYTES:
                raise BulkMarketError("Bhavcopy archive shape is invalid.")
            raw = archive.read(files[0])
    except (zipfile.BadZipFile, RuntimeError):
        raise BulkMarketError("Bhavcopy archive is invalid.") from None
    required = {"TradDt", "Sgmt", "Src", "FinInstrmTp", "ISIN", "TckrSymb", "SctySrs",
                "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol"}
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if not reader.fieldnames or not required <= set(reader.fieldnames): raise BulkMarketError("Bhavcopy columns are invalid.")
        result = {}
        for source in reader:
            if source.get("Sgmt") != "CM" or source.get("Src") != "NSE" or source.get("FinInstrmTp") != "STK" or source.get("SctySrs") != "EQ":
                continue
            symbol, isin = source.get("TckrSymb", ""), source.get("ISIN", "")
            if source.get("TradDt") != session or not re.fullmatch(r"[A-Z0-9&_-]{1,30}", symbol) or not re.fullmatch(r"IN[A-Z0-9]{10}", isin):
                raise BulkMarketError("Bhavcopy identity or session is invalid.")
            values = {key: _positive(source.get(field), field) for key, field in
                      (("open", "OpnPric"), ("high", "HghPric"), ("low", "LwPric"), ("close", "ClsPric"))}
            if Decimal(values["low"]) > min(Decimal(values["open"]), Decimal(values["close"])) or Decimal(values["high"]) < max(Decimal(values["open"]), Decimal(values["close"])):
                raise BulkMarketError("Bhavcopy OHLC values are inconsistent.")
            if symbol in result: raise BulkMarketError("Bhavcopy contains a duplicate EQ symbol.")
            result[symbol] = {"session": session, "symbol": symbol, "isin": isin, **values,
                              "volume": _volume(source.get("TtlTradgVol")), "series": "EQ"}
        if not result: raise BulkMarketError("Bhavcopy contains no validated EQ rows.")
        return result
    except (UnicodeError, csv.Error):
        raise BulkMarketError("Bhavcopy CSV is invalid.") from None


def parse_index_close(content, session):
    required = {"Index Name", "Index Date", "Open Index Value", "High Index Value", "Low Index Value", "Closing Index Value"}
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        if not reader.fieldnames or not required <= set(reader.fieldnames): raise BulkMarketError("Index columns are invalid.")
        matches = [row for row in reader if row.get("Index Name", "").strip().casefold() == "nifty 50"]
        if len(matches) != 1: raise BulkMarketError("Index file must contain one NIFTY 50 row.")
        row = matches[0]
        if datetime.strptime(row["Index Date"], "%d-%m-%Y").date().isoformat() != session:
            raise BulkMarketError("Index session does not match the requested day.")
        values = {key: _positive(row.get(field), field) for key, field in
                  (("open", "Open Index Value"), ("high", "High Index Value"),
                   ("low", "Low Index Value"), ("close", "Closing Index Value"))}
        return {"session": session, "symbol": "NIFTY 50", **values, "volume": None, "series": "INDEX"}
    except (UnicodeError, csv.Error, ValueError):
        raise BulkMarketError("Index CSV is invalid.") from None


class NseBulkProvider:
    def __init__(self, timeout=15): self.timeout = timeout

    def _get(self, url, maximum):
        request = Request(url, headers={"User-Agent": "graph_stock/0.26 public-research", "Accept-Encoding": "identity"})
        try:
            opener = build_opener(HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
            with opener.open(request, timeout=self.timeout) as response:
                if response.url.split("/", 3)[2] != ARCHIVE_HOST: raise BulkMarketError("NSE archive redirected outside the allowlist.")
                content = response.read(maximum + 1)
                if len(content) > maximum: raise BulkMarketError("NSE archive exceeds its size limit.")
                return Payload(content, response.url, _now())
        except HTTPError as error:
            raise BulkMarketError("NSE session report is unavailable.", "unavailable" if error.code != 429 else "throttled") from None
        except (URLError, TimeoutError, OSError):
            raise BulkMarketError("NSE archive is temporarily unavailable.", "unavailable") from None

    def __call__(self, day):
        compact, display = day.strftime("%Y%m%d"), day.strftime("%d%m%Y")
        bhav_url = f"https://{ARCHIVE_HOST}/content/cm/BhavCopy_NSE_CM_0_0_0_{compact}_F_0000.csv.zip"
        index_url = f"https://{ARCHIVE_HOST}/content/indices/ind_close_all_{display}.csv"
        bhav, index = self._get(bhav_url, MAX_ZIP_BYTES), self._get(index_url, 1_000_000)
        session = day.isoformat()
        return {"session": session, "equities": parse_bhavcopy(bhav.content, session),
                "benchmark": parse_index_close(index.content, session),
                "bhavcopy": {"url": bhav.url, "sha256": _sha(bhav.content)},
                "index": {"url": index.url, "sha256": _sha(index.content)},
                "retrieved_at": max(bhav.retrieved_at, index.retrieved_at)}


class BulkMarketService:
    def __init__(self, store, market_service, vault_dir, provider=None, clock=None):
        self.store, self.market, self.vault = store, market_service, Vault(vault_dir)
        self.provider, self.clock = provider or NseBulkProvider(), clock or (lambda: datetime.now(timezone.utc))
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS bulk_market_sessions (
                    session TEXT PRIMARY KEY, status TEXT NOT NULL, bhavcopy_url TEXT, index_url TEXT,
                    bhavcopy_sha256 TEXT, index_sha256 TEXT, retrieved_at TEXT, row_count INTEGER,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS bulk_equity_daily (
                    session TEXT NOT NULL, symbol TEXT NOT NULL, isin TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(session,symbol)
                );
                CREATE TABLE IF NOT EXISTS bulk_index_daily (
                    session TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bulk_history_runs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, result TEXT NOT NULL,
                    note_path TEXT, note_sha256 TEXT
                );
            """)
            db.execute("UPDATE bulk_history_runs SET status='queued',updated_at=? WHERE status='running'", (_now(),))

    def submit(self, request_key):
        with self.store.connect() as db:
            prior = db.execute("SELECT id FROM bulk_history_runs WHERE request_key=?", (request_key,)).fetchone()
            if prior: return self.get(prior["id"]), False
            run_id, timestamp = str(uuid.uuid4()), _now()
            db.execute("INSERT INTO bulk_history_runs VALUES (?,?,'queued',?,?,?,NULL,NULL)",
                       (run_id, request_key, timestamp, timestamp, json.dumps({"message": "Queued official NSE history refresh."})))
        return self.get(run_id), True

    def pending(self):
        with self.store.connect() as db: return [row[0] for row in db.execute("SELECT id FROM bulk_history_runs WHERE status='queued'")]

    def _saved_sessions(self, as_of):
        with self.store.connect() as db:
            return [row[0] for row in db.execute("SELECT session FROM bulk_market_sessions WHERE status='complete' AND session<=? ORDER BY session DESC", (as_of,))]

    def _persist_day(self, value):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR REPLACE INTO bulk_market_sessions VALUES (?,'complete',?,?,?,?,?,?,NULL)",
                       (value["session"], value["bhavcopy"]["url"], value["index"]["url"],
                        value["bhavcopy"]["sha256"], value["index"]["sha256"], value["retrieved_at"], len(value["equities"])))
            db.execute("DELETE FROM bulk_equity_daily WHERE session=?", (value["session"],))
            for symbol, row in value["equities"].items():
                db.execute("INSERT INTO bulk_equity_daily VALUES (?,?,?,?)", (value["session"], symbol, row["isin"], json.dumps(row, sort_keys=True)))
            db.execute("INSERT OR REPLACE INTO bulk_index_daily VALUES (?,?)", (value["session"], json.dumps(value["benchmark"], sort_keys=True)))

    def _targets(self):
        try:
            with self.store.connect() as db:
                financial = {row[0] for row in db.execute("""SELECT DISTINCT s.symbol FROM financial_jobs f
                    JOIN filing_sources s ON s.id=f.source_id WHERE f.status='completed'""")}
                ownership = {row[0] for row in db.execute("SELECT DISTINCT symbol FROM ownership_runs")}
                financial.update(row[0] for row in db.execute("SELECT DISTINCT symbol FROM bulk_financial_evidence"))
                ownership.update(row[0] for row in db.execute("SELECT DISTINCT symbol FROM bulk_ownership_evidence"))
            return sorted(financial & ownership)
        except sqlite3.OperationalError:
            return []

    def _actions(self, symbol, first, last):
        try:
            with self.store.connect() as db:
                rows = db.execute("SELECT result FROM market_runs WHERE symbol=? ORDER BY created_at DESC", (symbol,)).fetchall()
            for row in rows:
                result = json.loads(row[0]); source = result.get("source") or {}
                if (source.get("provider") == "National Stock Exchange of India"
                        and not source.get("source_id", "").startswith("nse-bulk-")
                        and "corporate actions" in source.get("coverage", "")):
                    return [item for item in result.get("actions", []) if first <= item["ex_date"] <= last], source
        except Exception:
            pass
        return None, None

    def _materialize(self, sessions, run_id):
        outcomes, gaps = [], []
        with self.store.connect() as db:
            directory_row = db.execute("SELECT content FROM filing_directory WHERE id=1").fetchone()
            directory = parse_directory(directory_row[0]) if directory_row else {}
        for symbol in self._targets():
            with self.store.connect() as db:
                equities = [json.loads(row[0]) for row in db.execute(
                    "SELECT payload FROM bulk_equity_daily WHERE symbol=? AND session IN (%s) ORDER BY session" % ",".join("?" * len(sessions)),
                    (symbol, *sessions)).fetchall()]
                benchmark = [json.loads(row[0]) for row in db.execute(
                    "SELECT payload FROM bulk_index_daily WHERE session IN (%s) ORDER BY session" % ",".join("?" * len(sessions)), sessions).fetchall()]
                sources = [dict(row) for row in db.execute(
                    "SELECT * FROM bulk_market_sessions WHERE session IN (%s) ORDER BY session" % ",".join("?" * len(sessions)), sessions).fetchall()]
            if len(equities) < 64 or len(benchmark) < 64:
                gaps.append({"symbol": symbol, "reason": "64 aligned official sessions are unavailable"}); continue
            first, last = equities[-64]["session"], equities[-1]["session"]
            actions, action_source = self._actions(symbol, first, last)
            if actions is None:
                gaps.append({"symbol": symbol, "reason": "official corporate-action coverage is unavailable"}); continue
            identity = directory.get(symbol)
            if not identity:
                gaps.append({"symbol": symbol, "reason": "current NSE directory identity is unavailable"}); continue
            hashes = [{"session": item["session"], "bhavcopy_sha256": item["bhavcopy_sha256"], "index_sha256": item["index_sha256"]} for item in sources[-64:]]
            source_hash = hashlib.sha256(json.dumps({"daily": hashes, "actions": action_source["source_id"]}, sort_keys=True).encode()).hexdigest()
            bundle = {"symbol": symbol, "name": identity["name"], "exchange": "NSE", "isin": identity["isin"],
                      "aliases": [{"symbol": symbol, "isin": identity["isin"], "effective_from": first, "effective_to": None}],
                      "bars": [{**{key: row[key] for key in ("session", "open", "high", "low", "close", "volume", "series")},
                                "status": "regular", "source_id": f"nse-bulk:{row['session']}"} for row in equities[-64:]],
                      "benchmark": {"symbol": "NIFTY 50", "bars": [{**{key: row[key] for key in ("session", "open", "high", "low", "close", "volume", "series")},
                                                                         "status": "regular", "source_id": f"nse-index:{row['session']}"} for row in benchmark[-64:]]},
                      "actions": [{key: item[key] for key in ("action_id", "type", "ex_date", "record_date", "terms", "source_id")} for item in actions],
                      "expected_sessions": [row["session"] for row in equities[-64:]],
                      "source": {"source_id": f"nse-bulk-{source_hash[:20]}", "provider": "National Stock Exchange of India",
                                 "title": "NSE CM UDiFF bhavcopy and all-index daily close", "url": REPORT_PAGE,
                                 "available_at": f"{last}T18:30:00+05:30", "retrieved_at": _now(), "content_sha256": source_hash,
                                 "coverage": f"64 official aligned sessions {first} to {last}; corporate actions from {action_source['source_id']}"},
                      "_raw": {"sessions": hashes, "corporate_action_source": action_source["source_id"]}}
            request_key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"bulk-market:{symbol}:{source_hash}"))
            market, _ = self.market.submit(symbol, request_key, bundle)
            outcomes.append({"symbol": symbol, "market_run_id": market["id"], "status": market["status"], "first_session": first, "last_session": last})
        return outcomes, gaps

    def execute(self, run_id, target_sessions=64, lookback_days=110):
        with self.store.connect() as db:
            changed = db.execute("UPDATE bulk_history_runs SET status='running',updated_at=? WHERE id=? AND status='queued'", (_now(), run_id)).rowcount
        if not changed: return
        as_of = self.clock().date(); candidates = [as_of - timedelta(days=offset) for offset in range(lookback_days) if (as_of - timedelta(days=offset)).weekday() < 5]
        try:
            saved = self._saved_sessions(as_of.isoformat())
            for start in range(0, len(candidates), 8):
                if len(saved) >= target_sessions: break
                batch = []
                with self.store.connect() as db:
                    known = {row[0] for row in db.execute("SELECT session FROM bulk_market_sessions WHERE session IN (%s)" % ",".join("?" * len(candidates[start:start+8])), tuple(day.isoformat() for day in candidates[start:start+8]))}
                wanted = [day for day in candidates[start:start+8] if day.isoformat() not in known]
                with ThreadPoolExecutor(max_workers=4) as pool:
                    futures = {pool.submit(self.provider, day): day for day in wanted}
                    for future in as_completed(futures):
                        try: batch.append(future.result())
                        except BulkMarketError: pass
                for value in batch: self._persist_day(value)
                saved = self._saved_sessions(as_of.isoformat())
                with self.store.connect() as db:
                    db.execute("UPDATE bulk_history_runs SET updated_at=?,result=? WHERE id=?", (_now(), json.dumps({
                        "message": "Collecting official sessions.", "sessions_available": len(saved), "target_sessions": target_sessions}), run_id))
            selected = sorted(saved[:target_sessions])
            if len(selected) < target_sessions: raise BulkMarketError(f"Only {len(selected)} of {target_sessions} official sessions are available.", "partial")
            materialized, gaps = self._materialize(selected, run_id)
            with self.store.connect() as db:
                equity_rows = db.execute("SELECT COUNT(*) FROM bulk_equity_daily WHERE session IN (%s)" % ",".join("?" * len(selected)), selected).fetchone()[0]
            result = {"schema_version": SCHEMA_VERSION, "provider_version": PROVIDER_VERSION, "status": "completed" if materialized else "partial",
                      "target_sessions": target_sessions, "sessions": selected, "first_session": selected[0], "last_session": selected[-1],
                      "equity_rows": equity_rows, "materialized": materialized, "gaps": gaps,
                      "source_page": REPORT_PAGE, "message": "Official history saved." if materialized else "History saved; no eligible local target could be materialized."}
            note = self._render(result); path = f"Graph Stock/Market Coverage/{run_id}.md"; self.vault.publish(path, note)
            with self.store.connect() as db:
                db.execute("UPDATE bulk_history_runs SET status=?,updated_at=?,result=?,note_path=?,note_sha256=? WHERE id=?",
                           (result["status"], _now(), json.dumps(result, sort_keys=True), path, digest(note), run_id))
        except BulkMarketError as error:
            result = {"schema_version": SCHEMA_VERSION, "status": error.code, "message": error.message}
            with self.store.connect() as db:
                db.execute("UPDATE bulk_history_runs SET status=?,updated_at=?,result=? WHERE id=?", (error.code, _now(), json.dumps(result), run_id))
        except Exception:
            result = {"schema_version": SCHEMA_VERSION, "status": "failed", "message": "Bulk history processing failed; retry with the same request key after checking local logs."}
            with self.store.connect() as db:
                db.execute("UPDATE bulk_history_runs SET status='failed',updated_at=?,result=? WHERE id=?", (_now(), json.dumps(result), run_id))

    def get(self, run_id):
        with self.store.connect() as db: row = db.execute("SELECT * FROM bulk_history_runs WHERE id=?", (run_id,)).fetchone()
        if not row: raise BulkMarketError("Bulk market-history run not found.", "not-found")
        result = json.loads(row["result"]); result.update({"id": row["id"], "status": row["status"], "created_at": row["created_at"],
                                                           "updated_at": row["updated_at"], "note_path": row["note_path"], "note_sha256": row["note_sha256"]})
        return result

    def recent(self):
        with self.store.connect() as db: ids = [row[0] for row in db.execute("SELECT id FROM bulk_history_runs ORDER BY created_at DESC LIMIT 20")]
        return [self.get(run_id) for run_id in ids]

    def read_report(self, run_id):
        run = self.get(run_id)
        if not run["note_path"]: raise BulkMarketError("Bulk history report is not available.", "not-found")
        return self.vault.read(run["note_path"])

    @staticmethod
    def _render(result):
        lines = ["# NSE bulk market-history coverage", "", f"Status: **{result['status']}**  ",
                 f"Sessions: **{result['first_session']} → {result['last_session']}** ({len(result['sessions'])})  ",
                 f"Validated EQ rows: **{result['equity_rows']}**  ", f"Source: [{REPORT_PAGE}]({REPORT_PAGE})", "",
                 "## Materialized histories", ""]
        lines += [f"- **{item['symbol']}** — {item['first_session']} to {item['last_session']}; `{item['market_run_id']}`; {item['status']}" for item in result["materialized"]] or ["No local target was materialized."]
        lines += ["", "## Gaps", ""] + ([f"- **{item['symbol']}** — {item['reason']}" for item in result["gaps"]] or ["- None"])
        lines += ["", "Daily ZIP and index hashes are retained in SQLite. Raw prices become adjusted only through the existing corporate-action engine.", ""]
        return "\n".join(lines)
