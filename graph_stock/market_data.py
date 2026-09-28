"""Validated NSE market bars and versioned corporate-action adjustments."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import ssl
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener

import certifi

from .vault import Vault

SCHEMA_VERSION = "market-data/v1"
ADJUSTMENT_VERSION = "corporate-action-adjustment/v1"
PROVIDER_VERSION = "nse-current-session/v1"


class MarketDataError(Exception):
    def __init__(self, message, code="invalid"):
        self.message, self.code = message, code
        super().__init__(message)


class MarketProviderError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _decimal(value, label, *, allow_zero=False):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise MarketDataError(f"{label} must be a decimal number.") from None
    if not result.is_finite() or result < 0 or (not allow_zero and result == 0):
        raise MarketDataError(f"{label} must be {'non-negative' if allow_zero else 'positive'}.")
    return result


def _number(value):
    return format(Decimal(value).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP).normalize(), "f")


def _iso_day(value, label):
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise MarketDataError(f"{label} must be an ISO date.") from None


def _iso_time(value, label):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise MarketDataError(f"{label} must be an ISO timestamp.") from None
    if parsed.tzinfo is None:
        raise MarketDataError(f"{label} must include a timezone.")
    return parsed.isoformat()


def _validate_bars(rows, dataset):
    if not isinstance(rows, list) or not rows:
        raise MarketDataError(f"{dataset} bars are required.")
    result = []
    for index, raw in enumerate(rows):
        allowed = {"session", "open", "high", "low", "close", "volume", "status", "series", "source_id"}
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise MarketDataError(f"{dataset} bar {index + 1} has unsupported fields.")
        session = _iso_day(raw.get("session"), f"{dataset} session")
        values = {key: _decimal(raw.get(key), f"{dataset} {key}") for key in ("open", "high", "low", "close")}
        if values["low"] > min(values["open"], values["close"]) or values["high"] < max(values["open"], values["close"]) or values["low"] > values["high"]:
            raise MarketDataError(f"{dataset} OHLC is inconsistent for {session}.")
        volume = raw.get("volume")
        if volume is not None:
            if isinstance(volume, bool) or int(volume) != volume or int(volume) < 0:
                raise MarketDataError(f"{dataset} volume must be a non-negative integer or null.")
            volume = int(volume)
        elif dataset == "security":
            raise MarketDataError("Security volume is required.")
        status = raw.get("status", "regular")
        if status not in ("regular", "intraday", "suspended"):
            raise MarketDataError("Bar status must be regular, intraday or suspended.")
        result.append({"row": index + 1, "session": session, **{k: _number(v) for k, v in values.items()},
                       "volume": volume, "status": status, "series": raw.get("series", "EQ"),
                       "source_id": raw.get("source_id")})
    return result


def _prior_close(bars, ex_date):
    eligible = [row for row in bars if row["session"] < ex_date]
    if not eligible:
        return None
    latest = max(row["session"] for row in eligible)
    matches = [row for row in eligible if row["session"] == latest]
    return Decimal(matches[0]["close"]) if len(matches) == 1 else None


def _action_factor(action, bars):
    kind, terms = action["type"], action["terms"]
    try:
        if kind == "split":
            old, new = _decimal(terms["old_shares"], "split old_shares"), _decimal(terms["new_shares"], "split new_shares")
            return old / new, new / old, None
        if kind == "bonus":
            held, bonus = _decimal(terms["held_shares"], "bonus held_shares"), _decimal(terms["bonus_shares"], "bonus bonus_shares")
            return held / (held + bonus), (held + bonus) / held, None
        if kind == "dividend":
            cash = _decimal(terms["cash_per_share"], "dividend cash_per_share", allow_zero=True)
            prior = _prior_close(bars, action["ex_date"])
            if prior is None or cash >= prior:
                return None, None, "missing-valid-prior-close"
            return (prior - cash) / prior, Decimal("1"), None
        if kind == "rights":
            held = _decimal(terms["held_shares"], "rights held_shares")
            rights = _decimal(terms["rights_shares"], "rights rights_shares")
            price = _decimal(terms["subscription_price"], "rights subscription_price", allow_zero=True)
            prior = _prior_close(bars, action["ex_date"])
            if prior is None:
                return None, None, "missing-valid-prior-close"
            return (prior * held + price * rights) / (prior * (held + rights)), (held + rights) / held, None
        if kind in ("merger", "demerger"):
            factor = _decimal(terms["price_factor"], f"{kind} price_factor")
            volume = _decimal(terms.get("share_factor", "1"), f"{kind} share_factor")
            return factor, volume, None
    except (KeyError, MarketDataError):
        return None, None, "incomplete-action-terms"
    return None, None, "unsupported-action"


def normalize_market_bundle(bundle):
    """Validate raw data and produce a backward-adjusted, auditable series."""
    required = {"symbol", "name", "exchange", "isin", "aliases", "bars", "benchmark", "actions", "expected_sessions", "source"}
    if not isinstance(bundle, dict) or set(bundle) - required or not required.issubset(bundle):
        raise MarketDataError("Market bundle does not match the versioned import schema.")
    symbol = str(bundle["symbol"]).strip().upper()
    if not re.fullmatch(r"[A-Z0-9&-]{1,30}", symbol) or bundle["exchange"] != "NSE":
        raise MarketDataError("A valid NSE symbol is required.")
    bars = _validate_bars(bundle["bars"], "security")
    benchmark_input = bundle["benchmark"]
    if set(benchmark_input) != {"symbol", "bars"}:
        raise MarketDataError("Benchmark must contain only symbol and bars.")
    benchmark = _validate_bars(benchmark_input["bars"], "benchmark")
    expected = sorted({_iso_day(item, "expected session") for item in bundle["expected_sessions"]})
    aliases = []
    for alias in bundle["aliases"]:
        if set(alias) != {"symbol", "isin", "effective_from", "effective_to"}:
            raise MarketDataError("Security alias does not match the versioned schema.")
        aliases.append({"symbol": alias["symbol"].upper(), "isin": alias["isin"],
                        "effective_from": _iso_day(alias["effective_from"], "alias effective_from"),
                        "effective_to": _iso_day(alias["effective_to"], "alias effective_to") if alias["effective_to"] else None})
    actions = []
    seen_actions = set()
    for raw in bundle["actions"]:
        if set(raw) != {"action_id", "type", "ex_date", "record_date", "terms", "source_id"}:
            raise MarketDataError("Corporate action does not match the versioned schema.")
        if raw["action_id"] in seen_actions or raw["type"] not in ("split", "bonus", "dividend", "rights", "merger", "demerger"):
            raise MarketDataError("Corporate action ID must be unique and type supported.")
        seen_actions.add(raw["action_id"])
        action = {**raw, "ex_date": _iso_day(raw["ex_date"], "action ex_date"),
                  "record_date": _iso_day(raw["record_date"], "action record_date") if raw["record_date"] else None}
        price_factor, share_factor, reason = _action_factor(action, bars)
        action.update({"price_factor": _number(price_factor) if price_factor is not None else None,
                       "share_factor": _number(share_factor) if share_factor is not None else None,
                       "adjustment_status": "applicable" if reason is None else "blocked", "reason": reason})
        actions.append(action)
    sessions = [row["session"] for row in bars]
    duplicates = sorted({item for item in sessions if sessions.count(item) > 1})
    adjusted = []
    for row in bars:
        relevant = [a for a in actions if row["session"] < a["ex_date"]]
        blocked = [a for a in relevant if a["adjustment_status"] == "blocked"]
        if row["session"] in duplicates:
            blocked_reason = "duplicate-session"
        elif blocked:
            blocked_reason = "incomplete-action:" + blocked[0]["action_id"]
        else:
            blocked_reason = None
        if blocked_reason:
            adjusted.append({**row, "adjusted_open": None, "adjusted_high": None, "adjusted_low": None,
                             "adjusted_close": None, "adjusted_volume": None, "price_factor": None,
                             "share_factor": None, "adjustment_status": "blocked", "reason": blocked_reason})
            continue
        price_factor = Decimal("1")
        share_factor = Decimal("1")
        for action in relevant:
            price_factor *= Decimal(action["price_factor"])
            share_factor *= Decimal(action["share_factor"])
        adjusted.append({**row, **{f"adjusted_{key}": _number(Decimal(row[key]) * price_factor)
                                    for key in ("open", "high", "low", "close")},
                         "adjusted_volume": int((Decimal(row["volume"]) * share_factor).quantize(Decimal("1"))) if row["volume"] is not None else None,
                         "price_factor": _number(price_factor), "share_factor": _number(share_factor),
                         "adjustment_status": "adjusted" if relevant else "raw-equals-adjusted", "reason": None})
    benchmark_sessions = [row["session"] for row in benchmark]
    gaps = sorted(set(expected) - set(sessions))
    benchmark_gaps = sorted(set(expected) - set(benchmark_sessions))
    source = bundle["source"]
    source_required = {"source_id", "provider", "title", "url", "available_at", "retrieved_at", "content_sha256", "coverage"}
    if (set(source) != source_required or not re.fullmatch(r"[a-f0-9]{64}", source["content_sha256"])
            or not re.fullmatch(r"[A-Za-z0-9:._-]{1,120}", source["source_id"])
            or not (source["url"].startswith("https://") or source["url"].startswith("manual:"))):
        raise MarketDataError("Raw source evidence metadata is invalid.")
    source = {**source, "available_at": _iso_time(source["available_at"], "source available_at"),
              "retrieved_at": _iso_time(source["retrieved_at"], "source retrieved_at")}
    return {
        "schema_version": SCHEMA_VERSION, "adjustment_version": ADJUSTMENT_VERSION,
        "symbol": symbol, "name": bundle["name"], "exchange": "NSE", "isin": bundle["isin"],
        "aliases": aliases, "identity_conflicts": [], "source": source, "raw_bars": bars, "adjusted_bars": adjusted,
        "benchmark": {"symbol": benchmark_input["symbol"], "bars": benchmark}, "actions": actions,
        "quality": {"expected_sessions": expected, "missing_sessions": gaps,
                    "benchmark_missing_sessions": benchmark_gaps, "duplicate_sessions": duplicates,
                    "suspensions": [row["session"] for row in bars if row["status"] == "suspended"],
                    "provisional_sessions": [row["session"] for row in bars if row["status"] == "intraday"],
                    "listing_coverage": {"first_session": min(sessions), "last_session": max(sessions),
                                         "bar_count": len(bars), "coverage": source["coverage"]},
                    "blocked_segments": sorted({row["reason"] for row in adjusted if row["reason"]}),
                    "status": "partial" if gaps or benchmark_gaps or duplicates or any(row["status"] == "intraday" for row in bars) or any(a["adjustment_status"] == "blocked" for a in actions) else "complete"},
        "normalization_scope": "prices, volumes, share counts, positions and per-share history only; total financial statement values are never adjusted",
    }


class NseCurrentSessionProvider:
    """Small public NSE adapter for the latest quoted session and current action list."""
    def __init__(self, timeout=12):
        self.timeout = timeout

    def _json(self, opener, url):
        request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": "https://www.nseindia.com/"})
        with opener.open(request, timeout=self.timeout) as response:
            return json.loads(response.read())

    def __call__(self, symbol):
        symbol = symbol.upper()
        context = ssl.create_default_context(cafile=certifi.where())
        opener = build_opener(HTTPCookieProcessor(CookieJar()), HTTPSHandler(context=context))
        try:
            market_url = "https://www.nseindia.com/api/NextApi/apiClient/marketWatchApi?" + urlencode({
                "functionName": "getIndicesData", "symbol": "NIFTY 50"})
            today, start = date.today(), date.today() - timedelta(days=370)
            action_url = "https://www.nseindia.com/api/corporates-corporateActions?" + urlencode({
                "index": "equities", "from_date": start.strftime("%d-%m-%Y"),
                "to_date": today.strftime("%d-%m-%Y"), "symbol": symbol})
            market, action_rows = self._json(opener, market_url), self._json(opener, action_url)
        except Exception as error:
            raise MarketProviderError("NSE current-session data is unavailable; use the manual JSON import.") from error
        payload = market.get("data", {})
        rows = payload.get("data", [])
        security = next((row for row in rows if row.get("symbol") == symbol), None)
        index = next((row for row in rows if row.get("symbol") == "NIFTY 50"), None)
        if not security or not index:
            raise MarketProviderError("The symbol is outside current NIFTY 50 market-watch coverage; use the manual JSON import.")
        timestamp = security.get("lastUpdateTime") or payload.get("timestamp")
        try:
            quoted_at = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            try:
                quoted_at = datetime.strptime(timestamp, "%d-%b-%Y %H:%M:%S")
            except (TypeError, ValueError):
                raise MarketProviderError("NSE market watch did not provide a valid session timestamp.") from None
        session = quoted_at.date().isoformat()
        available_at = quoted_at.replace(tzinfo=timezone(timedelta(hours=5, minutes=30))).isoformat()
        raw = {"market_watch": market, "actions": action_rows}
        digest = _hash(raw)
        source_id = "nse-current-" + digest[:20]
        actions = []
        for row in action_rows if isinstance(action_rows, list) else action_rows.get("data", []):
            purpose = row.get("subject") or row.get("purpose") or ""
            parsed = _parse_nse_action(symbol, purpose, row.get("exDate") or row.get("ex_date"), row.get("recordDate") or row.get("recDate") or row.get("record_date"), source_id)
            if parsed:
                actions.append(parsed)
        phase = json.dumps(payload.get("marketStatus", "")).lower()
        bar_status = "regular" if "closed" in phase else "intraday"
        day = {"session": session, "open": security.get("open"), "high": security.get("dayHigh"), "low": security.get("dayLow"),
               "close": security.get("lastPrice"), "volume": security.get("totalTradedVolume"),
               "status": bar_status, "series": security.get("series", "EQ"), "source_id": source_id}
        benchmark = {"session": session, "open": index.get("open"), "high": index.get("dayHigh"), "low": index.get("dayLow"),
                     "close": index.get("lastPrice"), "volume": index.get("totalTradedVolume"), "status": bar_status, "series": "INDEX", "source_id": source_id}
        isin = next((row.get("isin") for row in action_rows if row.get("isin")), "unknown")
        return {"symbol": symbol, "name": security.get("companyName") or symbol, "exchange": "NSE", "isin": isin,
                "aliases": [{"symbol": symbol, "isin": isin, "effective_from": "1900-01-01", "effective_to": None}],
                "bars": [day], "benchmark": {"symbol": "NIFTY 50", "bars": [benchmark]},
                "actions": actions, "expected_sessions": [session],
                "source": {"source_id": source_id, "provider": "National Stock Exchange of India",
                           "title": "NSE NIFTY 50 market watch and corporate actions", "url": market_url,
                           "available_at": available_at, "retrieved_at": _now(), "content_sha256": digest,
                           "coverage": "current intraday quote; corporate actions trailing 370 days"},
                "_raw": raw}


def _nse_day(value):
    for pattern in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except (TypeError, ValueError):
            pass
    return None


def _parse_nse_action(symbol, purpose, ex_date, record_date, source_id):
    ex_day = _nse_day(ex_date)
    if not ex_day:
        return None
    text = purpose.lower().replace("₹", "rs ")
    kind, terms = None, {}
    if "bonus" in text:
        match = re.search(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", text)
        kind, terms = "bonus", ({"bonus_shares": match.group(1), "held_shares": match.group(2)} if match else {})
    elif "split" in text or "sub-division" in text:
        values = re.findall(r"(?:rs\.?\s*)?(\d+(?:\.\d+)?)", text)
        kind, terms = "split", ({"old_shares": "1", "new_shares": str(Decimal(values[0]) / Decimal(values[1]))} if len(values) >= 2 and Decimal(values[1]) else {})
    elif "dividend" in text:
        values = re.findall(r"(?:rs\.?|re)\s*(\d+(?:\.\d+)?)", text)
        kind, terms = "dividend", ({"cash_per_share": values[-1]} if values else {})
    elif "rights" in text:
        kind = "rights"
    elif "merger" in text or "amalgamation" in text:
        kind = "merger"
    elif "demerger" in text:
        kind = "demerger"
    if not kind:
        return None
    return {"action_id": f"{symbol}:{kind}:{ex_day}:{_hash(purpose)[:8]}", "type": kind, "ex_date": ex_day,
            "record_date": _nse_day(record_date) if record_date and record_date != "-" else None,
            "terms": terms, "source_id": source_id}


def _render(result):
    q = result["quality"]
    lines = [f"# Market Data & Corporate Actions — {result['symbol']}", "", f"Run: `{result['id']}`",
             f"Schema: `{SCHEMA_VERSION}` · adjustments: `{ADJUSTMENT_VERSION}`", "",
             f"Source: [{result['source']['title']}]({result['source']['url']})  ",
             f"Retrieved: `{result['source']['retrieved_at']}` · coverage: {result['source']['coverage']}", "",
             "## Quality", "", f"Status: **{q['status']}**", f"Missing sessions: `{q['missing_sessions']}`",
             f"Benchmark gaps: `{q['benchmark_missing_sessions']}`", f"Duplicate sessions: `{q['duplicate_sessions']}`",
             f"Suspensions: `{q['suspensions']}`", f"Blocked segments: `{q['blocked_segments']}`", "",
             "## Raw and adjusted series", "", "| Session | Raw close | Adjusted close | Price factor | Volume | Adjusted volume | State |",
             "|---|---:|---:|---:|---:|---:|---|"]
    for row in result["adjusted_bars"]:
        lines.append(f"| {row['session']} | {row['close']} | {row['adjusted_close'] or '—'} | {row['price_factor'] or '—'} | {row['volume']} | {row['adjusted_volume'] if row['adjusted_volume'] is not None else '—'} | {row['adjustment_status']}{' · ' + row['reason'] if row['reason'] else ''} |")
    lines += ["", "## Corporate actions", ""]
    for action in result["actions"]:
        lines.append(f"- **{action['ex_date']} · {action['type']}** — `{json.dumps(action['terms'], sort_keys=True)}`; factor `{action['price_factor']}`; {action['adjustment_status']}{' · ' + action['reason'] if action['reason'] else ''}")
    lines += ["", "## Normalization boundary", "", result["normalization_scope"], ""]
    return "\n".join(lines)


class MarketDataService:
    def __init__(self, store, vault_dir, provider=None):
        self.store, self.vault, self.provider = store, Vault(vault_dir), provider or NseCurrentSessionProvider()
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS market_runs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, symbol TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, result TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS market_sources (
                    source_id TEXT PRIMARY KEY, provider TEXT NOT NULL, url TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL, content_sha256 TEXT NOT NULL, raw_payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS market_bars (
                    run_id TEXT NOT NULL, dataset TEXT NOT NULL, row_number INTEGER NOT NULL,
                    session TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id,dataset,row_number)
                );
                CREATE TABLE IF NOT EXISTS corporate_actions (
                    run_id TEXT NOT NULL, action_id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(run_id,action_id)
                );
                CREATE TABLE IF NOT EXISTS security_aliases (
                    run_id TEXT NOT NULL, symbol TEXT NOT NULL, effective_from TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(run_id,symbol,effective_from)
                );
            """)

    def submit(self, symbol, request_key, bundle=None):
        symbol = symbol.strip().upper()
        with self.store.connect() as db:
            prior = db.execute("SELECT id,symbol FROM market_runs WHERE request_key=?", (request_key,)).fetchone()
        if prior:
            if prior["symbol"] != symbol:
                raise MarketDataError("Request key already belongs to another symbol.", "conflict")
            return self.get(prior["id"]), False
        raw_payload = bundle
        try:
            if raw_payload is None:
                raw_payload = self.provider(symbol)
        except MarketProviderError:
            raise
        provider_raw = raw_payload.pop("_raw", raw_payload)
        result = normalize_market_bundle(raw_payload)
        if result["symbol"] != symbol:
            raise MarketDataError("Requested symbol does not match the imported bundle.")
        try:
            with self.store.connect() as db:
                row = db.execute("SELECT metadata FROM filing_sources WHERE symbol=? ORDER BY rowid DESC LIMIT 1", (symbol,)).fetchone()
            directory_isin = (json.loads(row["metadata"]).get("security") or {}).get("isin") if row else None
        except (sqlite3.OperationalError, TypeError, ValueError):
            directory_isin = None
        if directory_isin and result["isin"] not in ("unknown", directory_isin):
            result["identity_conflicts"].append({
                "field": "isin", "market_source_value": result["isin"], "directory_value": directory_isin,
                "selection": "unresolved", "reason": "Official NSE sources currently disagree; both candidates are retained.",
            })
        result.update({"id": str(uuid.uuid4()), "created_at": _now(), "status": result["quality"]["status"], "report": None})
        content = _render(result)
        path = f"Graph Stock/Market Data/{symbol}/{result['id']}.md"
        self.vault.publish(path, content)
        result["report"] = {"path": path, "sha256": _hash(content.encode())}
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            source = result["source"]
            db.execute("INSERT OR IGNORE INTO market_sources VALUES (?,?,?,?,?,?)", (
                source["source_id"], source["provider"], source["url"], source["retrieved_at"],
                source["content_sha256"], json.dumps(provider_raw, sort_keys=True)))
            db.execute("INSERT INTO market_runs VALUES (?,?,?,?,?,?)", (
                result["id"], request_key, symbol, result["status"], result["created_at"], json.dumps(result, sort_keys=True)))
            for dataset, rows in (("security", result["adjusted_bars"]), ("benchmark", result["benchmark"]["bars"])):
                for row in rows:
                    db.execute("INSERT INTO market_bars VALUES (?,?,?,?,?)", (result["id"], dataset, row["row"], row["session"], json.dumps(row, sort_keys=True)))
            for action in result["actions"]:
                db.execute("INSERT INTO corporate_actions VALUES (?,?,?)", (result["id"], action["action_id"], json.dumps(action, sort_keys=True)))
            for alias in result["aliases"]:
                db.execute("INSERT INTO security_aliases VALUES (?,?,?,?)", (result["id"], alias["symbol"], alias["effective_from"], json.dumps(alias, sort_keys=True)))
        return result, True

    def get(self, run_id):
        with self.store.connect() as db:
            row = db.execute("SELECT result FROM market_runs WHERE id=?", (str(run_id),)).fetchone()
        if not row:
            raise KeyError(run_id)
        return json.loads(row["result"])

    def recent(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT result FROM market_runs ORDER BY created_at DESC LIMIT 20").fetchall()
        return [json.loads(row["result"]) for row in rows]

    def read_report(self, run_id):
        result = self.get(run_id)
        return self.vault.read(result["report"]["path"])
