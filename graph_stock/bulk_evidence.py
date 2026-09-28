"""Bounded official NSE financial and ownership evidence acquisition."""

from __future__ import annotations

import hashlib
import json
import re
import ssl
import sqlite3
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPSHandler, Request, build_opener

import certifi

from .filings import parse_directory
from .vault import Vault, digest


SCHEMA_VERSION = "nse-bulk-evidence/v1"
PROVIDER_VERSION = "nse-xbrl-financial-ownership/v1"
FINANCIAL_PAGE = "https://www.nseindia.com/companies-listing/corporate-integrated-filing"
OWNERSHIP_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern"
ALLOWED_HOSTS = {"www.nseindia.com", "nsearchives.nseindia.com"}
DEFAULT_SYMBOLS = ("BEL", "HAL", "BHEL")
MAX_SYMBOLS = 10
MAX_JSON_BYTES = 4_000_000
MAX_XBRL_BYTES = 2_000_000


class BulkEvidenceError(RuntimeError):
    def __init__(self, message, code="invalid"):
        self.message, self.code = message, code
        super().__init__(message)


def _now(): return datetime.now(timezone.utc).isoformat()
def _sha(content): return hashlib.sha256(content).hexdigest()
def _local(tag): return tag.rsplit("}", 1)[-1]


def _date(value):
    for pattern in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try: return datetime.strptime(str(value).strip(), pattern).date().isoformat()
        except ValueError: pass
    raise BulkEvidenceError("NSE filing period is invalid.")


def _decimal(value, field):
    try: parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError): raise BulkEvidenceError(f"{field} is invalid.") from None
    if not parsed.is_finite(): raise BulkEvidenceError(f"{field} is invalid.")
    return parsed


def _parse_xml(content):
    if len(content) > MAX_XBRL_BYTES or b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise BulkEvidenceError("NSE XBRL is unsafe or exceeds its size limit.")
    try: root = ET.fromstring(content)
    except ET.ParseError: raise BulkEvidenceError("NSE XBRL is malformed.") from None
    if _local(root.tag).casefold() != "xbrl": raise BulkEvidenceError("NSE file is not an XBRL instance.")
    contexts = {}
    for element in root.iter():
        if _local(element.tag) != "context" or not element.get("id"): continue
        values = {_local(child.tag): (child.text or "").strip() for child in element.iter()}
        contexts[element.get("id")] = {key: values.get(key) for key in ("startDate", "endDate", "instant")}
    facts = []
    for element in root.iter():
        text = (element.text or "").strip()
        if element.get("contextRef") and text:
            facts.append({"name": _local(element.tag), "context": element.get("contextRef"), "value": text})
    return facts, contexts


def _identity(facts, symbol, isin):
    symbols = {item["value"].upper() for item in facts if item["name"] in ("Symbol", "NSESymbol")}
    isins = {item["value"].upper() for item in facts if item["name"] == "ISIN"}
    if symbol not in symbols or isin not in isins:
        raise BulkEvidenceError("NSE XBRL identity does not match the directory.")


def parse_financial_xbrl(content, symbol, isin, period_end):
    facts, contexts = _parse_xml(content); _identity(facts, symbol, isin)
    eligible = []
    for item in facts:
        context = contexts.get(item["context"], {})
        if (context.get("endDate") or context.get("instant")) == period_end:
            start = context.get("startDate") or period_end
            eligible.append((start, item))
    if not eligible: raise BulkEvidenceError("Financial XBRL has no facts for its stated period.")
    earliest = min(start for start, _ in eligible)
    values = {}
    for start, item in eligible:
        if start == earliest: values.setdefault(item["name"], item["value"])
    required = ("RevenueFromOperations", "OtherIncome", "FinanceCosts")
    if any(name not in values for name in required):
        raise BulkEvidenceError("Financial layout lacks comparable non-bank operating fields.", "coverage")
    profit_name = next((name for name in ("ProfitBeforeExceptionalItemsAndTax", "ProfitBeforeTax") if name in values), None)
    if not profit_name: raise BulkEvidenceError("Financial layout lacks profit before tax.", "coverage")
    revenue = _decimal(values["RevenueFromOperations"], "revenue")
    if revenue <= 0: raise BulkEvidenceError("Revenue must be positive.")
    operating_profit = (_decimal(values[profit_name], "profit before tax")
                        + _decimal(values["FinanceCosts"], "finance costs")
                        - _decimal(values["OtherIncome"], "other income"))
    return {"period_end": period_end, "revenue_rupees": format(revenue, "f"),
            "operating_profit_rupees": format(operating_profit, "f"),
            "operating_margin_percent": format(operating_profit / revenue * 100, "f")}


OWNERSHIP_CONTEXTS = {
    "promoter": "ShareholdingOfPromoterAndPromoterGroup_ContextI",
    "dii": "InstitutionsDomestic_ContextI",
    "fii": "InstitutionsForeign_ContextI",
    "total": "ShareholdingPattern_ContextI",
}


def parse_ownership_xbrl(content, symbol, isin, period_end):
    facts, contexts = _parse_xml(content); _identity(facts, symbol, isin)
    output = {"period_end": period_end}
    for kind, context_id in OWNERSHIP_CONTEXTS.items():
        period = contexts.get(context_id, {})
        if period.get("instant") != period_end: raise BulkEvidenceError("Ownership context date does not match the filing.")
        shares = next((item["value"] for item in facts if item["context"] == context_id and item["name"] == "NumberOfShares"), None)
        percent = next((item["value"] for item in facts if item["context"] == context_id and item["name"] == "ShareholdingAsAPercentageOfTotalNumberOfShares"), None)
        if shares is None or percent is None: raise BulkEvidenceError(f"Ownership XBRL lacks {kind} aggregate fields.", "coverage")
        output[kind] = {"shares": int(_decimal(shares, f"{kind} shares")),
                        "percent": format(_decimal(percent, f"{kind} percent") * 100, "f")}
    pledge = next((item["value"].casefold() for item in facts
                   if item["name"] == "WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged"), None)
    output["promoter_pledged"] = None if pledge not in ("true", "false") else pledge == "true"
    return output


def _select_periods(rows, *, financial):
    selected = {}
    for row in rows:
        if financial:
            if row.get("type") != "Integrated Filing- Financials" or row.get("consolidated") != "Consolidated": continue
            period = _date(row.get("qe_Date")); url = row.get("xbrl"); published = row.get("broadcast_Date")
        else:
            period = _date(row.get("date")); url = row.get("xbrl"); published = row.get("broadcastDate")
        if not url or url.endswith("/-"): continue
        selected.setdefault(period, {"period_end": period, "url": url, "published_at": published,
                                     "revision": row.get("type_Sub") or row.get("revisedStatus")})
    ordered = sorted(selected, reverse=True)
    if financial and ordered:
        current = ordered[0]
        comparable = next((period for period in ordered[1:] if period[5:] == current[5:]), None)
        return [selected[current], selected[comparable]] if comparable else [selected[current]]
    return [selected[key] for key in ordered[:2]]


class NseEvidenceProvider:
    def __init__(self, timeout=20): self.timeout = timeout

    def _get(self, url, maximum, referer):
        if urlparse(url).scheme != "https" or urlparse(url).hostname not in ALLOWED_HOSTS:
            raise BulkEvidenceError("NSE source URL is outside the allowlist.")
        request = Request(url, headers={"User-Agent": "graph_stock/0.27 public-research",
                                        "Accept": "application/json, application/xml, text/xml",
                                        "Accept-Encoding": "identity", "Referer": referer})
        try:
            opener = build_opener(HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
            with opener.open(request, timeout=self.timeout) as response:
                if urlparse(response.url).hostname not in ALLOWED_HOSTS:
                    raise BulkEvidenceError("NSE source redirected outside the allowlist.")
                content = response.read(maximum + 1)
                if len(content) > maximum: raise BulkEvidenceError("NSE response exceeds its size limit.")
                return content, response.url, _now()
        except HTTPError as error:
            raise BulkEvidenceError("NSE filing source is unavailable.", "throttled" if error.code == 429 else "unavailable") from None
        except (URLError, TimeoutError, OSError):
            raise BulkEvidenceError("NSE filing source is temporarily unavailable.", "unavailable") from None

    def _json(self, path, params, referer):
        content, url, retrieved = self._get(f"https://www.nseindia.com/api/{path}?{urlencode(params)}", MAX_JSON_BYTES, referer)
        try: payload = json.loads(content)
        except (UnicodeError, json.JSONDecodeError): raise BulkEvidenceError("NSE filing catalog is invalid.") from None
        rows = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(rows, list): raise BulkEvidenceError("NSE filing catalog has an invalid shape.")
        return rows, {"url": url, "retrieved_at": retrieved, "sha256": _sha(content)}

    def __call__(self, symbol, identity):
        financial_rows, financial_catalog = self._json(
            "integrated-filing-results", {"index": "equities", "symbol": symbol, "page": 1, "size": 100}, FINANCIAL_PAGE)
        ownership_rows, ownership_catalog = self._json(
            "corporate-share-holdings-master", {"index": "equities", "symbol": symbol}, OWNERSHIP_PAGE)
        financial_periods, ownership_periods = _select_periods(financial_rows, financial=True), _select_periods(ownership_rows, financial=False)
        if len(financial_periods) < 2 or len(ownership_periods) < 2:
            raise BulkEvidenceError("Two comparable financial and ownership periods are unavailable.", "coverage")
        for item in financial_periods:
            content, url, retrieved = self._get(item["url"], MAX_XBRL_BYTES, FINANCIAL_PAGE)
            item.update(parse_financial_xbrl(content, symbol, identity["isin"], item["period_end"]))
            item.update({"url": url, "retrieved_at": retrieved, "sha256": _sha(content)})
        for item in ownership_periods:
            content, url, retrieved = self._get(item["url"], MAX_XBRL_BYTES, OWNERSHIP_PAGE)
            item.update(parse_ownership_xbrl(content, symbol, identity["isin"], item["period_end"]))
            item.update({"url": url, "retrieved_at": retrieved, "sha256": _sha(content)})
        current, prior = financial_periods[0], financial_periods[1]
        revenue_growth = (_decimal(current["revenue_rupees"], "current revenue") /
                          _decimal(prior["revenue_rupees"], "prior revenue") - 1) * 100
        current_o, prior_o = ownership_periods[0], ownership_periods[1]
        institutional_change = ((_decimal(current_o["dii"]["percent"], "DII") + _decimal(current_o["fii"]["percent"], "FII"))
                                - (_decimal(prior_o["dii"]["percent"], "prior DII") + _decimal(prior_o["fii"]["percent"], "prior FII")))
        return {"symbol": symbol, "name": identity["name"], "isin": identity["isin"],
                "financial_periods": financial_periods, "ownership_periods": ownership_periods,
                "metrics": {"revenue_growth_percent": format(revenue_growth, "f"),
                            "operating_margin_percent": current["operating_margin_percent"],
                            "institutional_change_pp": format(institutional_change, "f")},
                "catalogs": {"financial": financial_catalog, "ownership": ownership_catalog}}


class BulkEvidenceService:
    def __init__(self, store, vault_dir, provider=None):
        self.store, self.vault, self.provider = store, Vault(vault_dir), provider or NseEvidenceProvider()
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS bulk_evidence_runs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, symbols TEXT NOT NULL,
                    result TEXT NOT NULL, note_path TEXT, note_sha256 TEXT
                );
                CREATE TABLE IF NOT EXISTS bulk_financial_evidence (
                    symbol TEXT NOT NULL, period_end TEXT NOT NULL, source_sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(symbol,period_end)
                );
                CREATE TABLE IF NOT EXISTS bulk_ownership_evidence (
                    symbol TEXT NOT NULL, period_end TEXT NOT NULL, source_sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(symbol,period_end)
                );
                CREATE TABLE IF NOT EXISTS bulk_screening_metrics (
                    symbol TEXT PRIMARY KEY, as_of_date TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL
                );
            """)
            db.execute("UPDATE bulk_evidence_runs SET status='queued',updated_at=? WHERE status='running'", (_now(),))

    def submit(self, request_key, symbols=None):
        normalized = tuple(dict.fromkeys(str(item).strip().upper() for item in (symbols or DEFAULT_SYMBOLS)))
        if not normalized or len(normalized) > MAX_SYMBOLS or any(not re.fullmatch(r"[A-Z0-9&_-]{1,30}", item) for item in normalized):
            raise BulkEvidenceError(f"Choose between 1 and {MAX_SYMBOLS} valid NSE symbols.")
        with self.store.connect() as db:
            prior = db.execute("SELECT id,symbols FROM bulk_evidence_runs WHERE request_key=?", (request_key,)).fetchone()
            if prior:
                if json.loads(prior["symbols"]) != list(normalized): raise BulkEvidenceError("Request key belongs to another symbol set.", "conflict")
                return self.get(prior["id"]), False
            run_id, timestamp = str(uuid.uuid4()), _now()
            db.execute("INSERT INTO bulk_evidence_runs VALUES (?,?,'queued',?,?,?,?,NULL,NULL)",
                       (run_id, request_key, timestamp, timestamp, json.dumps(normalized), json.dumps({"message": "Queued official NSE evidence refresh."})))
        return self.get(run_id), True

    def pending(self):
        with self.store.connect() as db: return [row[0] for row in db.execute("SELECT id FROM bulk_evidence_runs WHERE status='queued'")]

    def execute(self, run_id):
        with self.store.connect() as db:
            changed = db.execute("UPDATE bulk_evidence_runs SET status='running',updated_at=? WHERE id=? AND status='queued'", (_now(), run_id)).rowcount
            row = db.execute("SELECT symbols FROM bulk_evidence_runs WHERE id=?", (run_id,)).fetchone()
        if not changed or not row: return
        symbols = json.loads(row["symbols"])
        try:
            with self.store.connect() as db:
                directory_row = db.execute("SELECT content FROM filing_directory WHERE id=1").fetchone()
            if not directory_row: raise BulkEvidenceError("Refresh the official NSE directory first.", "coverage")
            directory = parse_directory(directory_row[0]); invalid = [symbol for symbol in symbols if symbol not in directory]
            if invalid: raise BulkEvidenceError(f"Symbols are absent from the current NSE directory: {', '.join(invalid)}")
            completed, gaps = [], []
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = {pool.submit(self.provider, symbol, directory[symbol]): symbol for symbol in symbols}
                for future in as_completed(futures):
                    symbol = futures[future]
                    try:
                        evidence = future.result(); self._persist(evidence); completed.append(evidence)
                    except BulkEvidenceError as error: gaps.append({"symbol": symbol, "code": error.code, "reason": error.message})
                    except Exception: gaps.append({"symbol": symbol, "code": "failed", "reason": "Evidence refresh failed safely."})
                    with self.store.connect() as db:
                        db.execute("UPDATE bulk_evidence_runs SET updated_at=?,result=? WHERE id=?", (_now(), json.dumps({
                            "schema_version": SCHEMA_VERSION, "provider_version": PROVIDER_VERSION,
                            "status": "running", "requested": symbols, "completed_count": len(completed), "gap_count": len(gaps)}), run_id))
            status = "completed" if completed and not gaps else "partial" if completed else "coverage"
            result = {"schema_version": SCHEMA_VERSION, "provider_version": PROVIDER_VERSION, "status": status,
                      "requested": symbols, "completed": sorted(({"symbol": item["symbol"], "name": item["name"],
                          "as_of_date": item["financial_periods"][0]["period_end"], "metrics": item["metrics"]} for item in completed), key=lambda item: item["symbol"]),
                      "gaps": sorted(gaps, key=lambda item: item["symbol"]), "source_pages": [FINANCIAL_PAGE, OWNERSHIP_PAGE]}
            note = self._render(result); path = f"Graph Stock/Evidence Coverage/{run_id}.md"; self.vault.publish(path, note)
            with self.store.connect() as db:
                db.execute("UPDATE bulk_evidence_runs SET status=?,updated_at=?,result=?,note_path=?,note_sha256=? WHERE id=?",
                           (status, _now(), json.dumps(result, sort_keys=True), path, digest(note), run_id))
        except BulkEvidenceError as error:
            with self.store.connect() as db:
                db.execute("UPDATE bulk_evidence_runs SET status=?,updated_at=?,result=? WHERE id=?",
                           (error.code, _now(), json.dumps({"message": error.message}), run_id))
        except Exception:
            with self.store.connect() as db:
                db.execute("UPDATE bulk_evidence_runs SET status='failed',updated_at=?,result=? WHERE id=?",
                           (_now(), json.dumps({"message": "Official evidence refresh failed safely."}), run_id))

    def _persist(self, evidence):
        financial, ownership = evidence["financial_periods"], evidence["ownership_periods"]
        source_manifest = {"financial": [item["sha256"] for item in financial],
                           "ownership": [item["sha256"] for item in ownership], "metrics": evidence["metrics"]}
        fingerprint = _sha(json.dumps(source_manifest, sort_keys=True).encode())
        payload = {"symbol": evidence["symbol"], "name": evidence["name"], "isin": evidence["isin"],
                   "as_of_date": financial[0]["period_end"], "ownership_as_of_date": ownership[0]["period_end"],
                   "metrics": evidence["metrics"], "sources": evidence["catalogs"], "fingerprint": fingerprint}
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for item in financial:
                db.execute("INSERT OR REPLACE INTO bulk_financial_evidence VALUES (?,?,?,?)",
                           (evidence["symbol"], item["period_end"], item["sha256"], json.dumps(item, sort_keys=True)))
            for item in ownership:
                db.execute("INSERT OR REPLACE INTO bulk_ownership_evidence VALUES (?,?,?,?)",
                           (evidence["symbol"], item["period_end"], item["sha256"], json.dumps(item, sort_keys=True)))
            db.execute("INSERT OR REPLACE INTO bulk_screening_metrics VALUES (?,?,?,?)",
                       (evidence["symbol"], payload["as_of_date"], fingerprint, json.dumps(payload, sort_keys=True)))

    def get(self, run_id):
        with self.store.connect() as db: row = db.execute("SELECT * FROM bulk_evidence_runs WHERE id=?", (run_id,)).fetchone()
        if not row: raise BulkEvidenceError("Evidence refresh not found.", "not-found")
        result = json.loads(row["result"]); result.update({key: row[key] for key in ("id", "status", "created_at", "updated_at", "note_path", "note_sha256")})
        return result

    def recent(self):
        with self.store.connect() as db: ids = [row[0] for row in db.execute("SELECT id FROM bulk_evidence_runs ORDER BY created_at DESC LIMIT 20")]
        return [self.get(run_id) for run_id in ids]

    def read_report(self, run_id): return self.vault.read(self.get(run_id)["note_path"])

    @staticmethod
    def _render(result):
        lines = ["# NSE financial and ownership coverage", "", f"Status: **{result['status']}**  ",
                 f"Provider: `{PROVIDER_VERSION}`", "", "## Completed", ""]
        if not result["completed"]: lines.append("No symbol produced complete comparable evidence.")
        for item in result["completed"]:
            metrics = item["metrics"]
            lines.append(f"- **{item['symbol']}** · {item['as_of_date']} · revenue growth {metrics['revenue_growth_percent']}% · operating margin {metrics['operating_margin_percent']}% · institutional change {metrics['institutional_change_pp']} pp")
        lines += ["", "## Gaps", ""]
        if not result["gaps"]: lines.append("No gaps.")
        for item in result["gaps"]: lines.append(f"- **{item['symbol']}** · `{item['code']}` · {item['reason']}")
        lines += ["", "## Sources", "", f"- [Integrated financial filings]({FINANCIAL_PAGE})", f"- [Shareholding patterns]({OWNERSHIP_PAGE})", "",
                  "Structured filings are issuer submissions disseminated by NSE. Coverage does not imply candidate eligibility or investment performance.", ""]
        return "\n".join(lines)
