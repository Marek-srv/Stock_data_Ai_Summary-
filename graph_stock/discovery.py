"""Dated, explainable NSE candidate screening with research-only queueing."""

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from .filings import DIRECTORIES, FilingError, download, parse_directory
from .vault import Vault, digest

SCHEMA_VERSION = "nse-candidate-screen/v2"
POLICY_VERSION = "fundamental-accumulation-momentum/v1"
UNIVERSE_VERSION = "bounded-nse-fixture/2026-09-10"
WEIGHTS = {"fundamentals": Decimal("0.40"), "accumulation": Decimal("0.30"), "momentum": Decimal("0.30")}
THRESHOLDS = {"revenue_growth_percent": Decimal("10"), "operating_margin_percent": Decimal("12"),
              "institutional_change_pp": Decimal("0.25"), "return_63d_percent": Decimal("8"),
              "relative_strength_63d_pp": Decimal("2")}


def now(): return datetime.now(timezone.utc).isoformat()


def ist_date(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()


class DiscoveryError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def _metric(name, value, unit, as_of, source, missing_reason=None, evidence_id=None):
    return {"name": name, "value": value, "unit": unit, "as_of_date": as_of,
            "source_id": source, "evidence_id": evidence_id or f"{source}:{name}", "missing_reason": missing_reason}


def fixture_universe():
    """A small coverage fixture; values are synthetic and make no market-wide claim."""
    return {
        "version": UNIVERSE_VERSION, "exchange": "NSE", "as_of_date": "2026-09-10",
        "available_at": "2026-09-10T20:00:00+05:30", "source_id": "fixture:nse-screen:2026-09-10",
        "source_kind": "synthetic-fixture", "coverage": "Four explicit test securities; not the NSE market.",
        "securities": [
            {"security_id": "NSE:BEL", "symbol": "BEL", "name": "Bharat Electronics Limited", "listing_status": "active",
             "metrics": [_metric("revenue_growth_percent", "17.27", "%", "2025-03-31", "fixture:bel:fundamentals"),
                         _metric("operating_margin_percent", "26.78", "%", "2025-03-31", "fixture:bel:fundamentals"),
                         _metric("institutional_change_pp", "0.35", "percentage points", "2025-03-31", "fixture:bel:ownership"),
                         _metric("return_63d_percent", "12.00", "%", "2026-09-10", "fixture:bel:market"),
                         _metric("relative_strength_63d_pp", "4.00", "percentage points", "2026-09-10", "fixture:bel:market")]},
            {"security_id": "NSE:HAL", "symbol": "HAL", "name": "Hindustan Aeronautics Limited", "listing_status": "active",
             "metrics": [_metric("revenue_growth_percent", "14", "%", "2025-03-31", "fixture:hal:fundamentals"),
                         _metric("operating_margin_percent", "22", "%", "2025-03-31", "fixture:hal:fundamentals"),
                         _metric("institutional_change_pp", "0.40", "percentage points", "2025-03-31", "fixture:hal:ownership"),
                         _metric("return_63d_percent", "4", "%", "2026-09-10", "fixture:hal:market"),
                         _metric("relative_strength_63d_pp", "-1", "percentage points", "2026-09-10", "fixture:hal:market")]},
            {"security_id": "NSE:BHEL", "symbol": "BHEL", "name": "Bharat Heavy Electricals Limited", "listing_status": "active",
             "metrics": [_metric("revenue_growth_percent", "11", "%", "2025-03-31", "fixture:bhel:fundamentals"),
                         _metric("operating_margin_percent", "13", "%", "2025-03-31", "fixture:bhel:fundamentals"),
                         _metric("institutional_change_pp", None, "percentage points", "2025-03-31", "fixture:bhel:ownership", "comparable-period ownership unavailable"),
                         _metric("return_63d_percent", "10", "%", "2026-09-10", "fixture:bhel:market"),
                         _metric("relative_strength_63d_pp", "3", "percentage points", "2026-09-10", "fixture:bhel:market")]},
            {"security_id": "NSE:OLDCO", "symbol": "OLDCO", "name": "Old Company Limited", "listing_status": "delisted",
             "metrics": [_metric(name, "99", "%" if name != "institutional_change_pp" else "percentage points", "2026-09-10", "fixture:oldco") for name in THRESHOLDS]},
        ],
    }


class NseDirectoryUniverse:
    """Official NSE identity coverage joined only to traceable local metrics."""
    def __init__(self, store, fetch=download, clock=now):
        self.store, self.fetch, self.clock = store, fetch, clock
        with self.store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS filing_directory (
                id INTEGER PRIMARY KEY CHECK(id=1), content BLOB NOT NULL,
                url TEXT NOT NULL, retrieved_at TEXT NOT NULL)""")

    def _directory(self):
        observed = self.clock()
        with self.store.connect() as db:
            cached = db.execute("SELECT * FROM filing_directory WHERE id=1").fetchone()
        if cached and ist_date(cached["retrieved_at"]) == ist_date(observed):
            return cached["content"], cached["url"], cached["retrieved_at"], False
        attempts = []
        for url in DIRECTORIES:
            try:
                response = self.fetch(url)
                parse_directory(response.content)
                with self.store.connect() as db:
                    db.execute("INSERT OR REPLACE INTO filing_directory VALUES (1,?,?,?)",
                               (response.content, response.url, response.retrieved_at))
                return response.content, response.url, response.retrieved_at, False
            except FilingError as error:
                attempts.append({"url": url, "status": error.status})
        if cached:
            return cached["content"], cached["url"], cached["retrieved_at"], True
        raise DiscoveryError("unavailable", "The official NSE equity directory is unavailable; retry later.")

    def _financial_metrics(self):
        found = {}
        try:
            with self.store.connect() as db:
                rows = db.execute("""SELECT f.id,f.created_at,s.symbol,m.id AS metric_id,m.payload
                    FROM financial_jobs f JOIN filing_sources s ON s.id=f.source_id
                    JOIN financial_metrics m ON m.run_id=f.id
                    WHERE f.status='completed' ORDER BY f.created_at DESC,m.id""").fetchall()
        except sqlite3.OperationalError:
            return found
        selected = {}
        for row in rows:
            selected.setdefault(row["symbol"], row["id"])
            if selected[row["symbol"]] != row["id"] or row["metric_id"] not in ("metric:revenue-growth", "metric:operating-margin"):
                continue
            value = json.loads(row["payload"])
            name = "revenue_growth_percent" if row["metric_id"] == "metric:revenue-growth" else "operating_margin_percent"
            found.setdefault(row["symbol"], []).append(_metric(
                name, value.get("value") if value.get("availability") == "available" else None,
                value.get("unit", "%"), value.get("period_end"), f"financial:{row['id']}",
                value.get("reason"), "|".join(value.get("evidence_ids") or []) or f"financial:{row['id']}:{name}"))
        try:
            with self.store.connect() as db:
                bulk = db.execute("SELECT symbol,as_of_date,fingerprint,payload FROM bulk_screening_metrics").fetchall()
            for row in bulk:
                saved_period = max((item.get("as_of_date") or "" for item in found.get(row["symbol"], [])), default="")
                if saved_period >= row["as_of_date"]: continue
                payload = json.loads(row["payload"]); values = payload["metrics"]
                source = f"nse-xbrl:{row['fingerprint']}"
                found[row["symbol"]] = [
                    _metric("revenue_growth_percent", values["revenue_growth_percent"], "%", row["as_of_date"], source,
                            evidence_id=f"{source}:revenue"),
                    _metric("operating_margin_percent", values["operating_margin_percent"], "%", row["as_of_date"], source,
                            evidence_id=f"{source}:operating-margin"),
                ]
        except sqlite3.OperationalError:
            pass
        return found

    def _ownership_metrics(self):
        found = {}
        try:
            with self.store.connect() as db:
                rows = db.execute("SELECT id,symbol,created_at,result FROM ownership_runs ORDER BY created_at DESC").fetchall()
        except sqlite3.OperationalError:
            return found
        for row in rows:
            if row["symbol"] in found:
                continue
            result = json.loads(row["result"]); comparison = result.get("comparison") or {}
            aggregates = {item.get("kind"): item for item in comparison.get("comparisons", []) if item.get("kind") in ("fii", "dii")}
            values = [aggregates.get(kind, {}).get("percentage_point_change") for kind in ("fii", "dii")]
            complete = comparison.get("comparable") and all(value is not None for value in values)
            value = str(sum((Decimal(item) for item in values), Decimal("0"))) if complete else None
            reason = None if complete else "comparable aggregate FII and DII periods are unavailable"
            found[row["symbol"]] = [_metric(
                "institutional_change_pp", value, "percentage points", comparison.get("current_period"),
                f"ownership:{row['id']}", reason,
                f"ownership:{row['id']}:aggregate:fii+dii")]
        try:
            with self.store.connect() as db:
                bulk = db.execute("SELECT symbol,as_of_date,fingerprint,payload FROM bulk_screening_metrics").fetchall()
            for row in bulk:
                payload = json.loads(row["payload"]); period = payload.get("ownership_as_of_date") or row["as_of_date"]
                existing_period = found.get(row["symbol"], [{}])[0].get("as_of_date", "") if found.get(row["symbol"]) else ""
                if existing_period >= period: continue
                source = f"nse-xbrl:{row['fingerprint']}"
                found[row["symbol"]] = [_metric(
                    "institutional_change_pp", payload["metrics"]["institutional_change_pp"], "percentage points", period,
                    source, evidence_id=f"{source}:aggregate:fii+dii")]
        except sqlite3.OperationalError:
            pass
        return found

    def _market_metrics(self):
        found, complete, partial = {}, set(), {}
        try:
            with self.store.connect() as db:
                rows = db.execute("SELECT id,symbol,created_at,result FROM market_runs ORDER BY created_at DESC").fetchall()
        except sqlite3.OperationalError:
            return found
        for row in rows:
            symbol = row["symbol"]
            if symbol in complete:
                continue
            result = json.loads(row["result"]); source = result.get("source") or {}
            if source.get("provider") != "National Stock Exchange of India" or not str(source.get("url", "")).startswith("https://"):
                continue
            bars, benchmark = result.get("adjusted_bars") or [], (result.get("benchmark") or {}).get("bars") or []
            benchmark_by_session = {item.get("session"): item for item in benchmark}
            usable = [item for item in bars if item.get("adjusted_close") is not None and item.get("session") in benchmark_by_session]
            if len(usable) < 64:
                partial.setdefault(symbol, [
                    _metric("return_63d_percent", None, "%", usable[-1].get("session") if usable else None,
                            f"market:{row['id']}", "at least 64 aligned adjusted NSE sessions are required"),
                    _metric("relative_strength_63d_pp", None, "percentage points", usable[-1].get("session") if usable else None,
                            f"market:{row['id']}", "at least 64 aligned adjusted NSE and benchmark sessions are required"),
                ])
                continue
            window = usable[-64:]; first, last = window[0], window[-1]
            benchmark_first, benchmark_last = benchmark_by_session[first["session"]], benchmark_by_session[last["session"]]
            security_return = (Decimal(str(last["adjusted_close"])) / Decimal(str(first["adjusted_close"])) - 1) * 100
            benchmark_return = (Decimal(str(benchmark_last["close"])) / Decimal(str(benchmark_first["close"])) - 1) * 100
            found[symbol] = [
                _metric("return_63d_percent", str(security_return), "%", last["session"], f"market:{row['id']}",
                        evidence_id=f"market:{row['id']}:{first['session']}:{last['session']}:security"),
                _metric("relative_strength_63d_pp", str(security_return - benchmark_return), "percentage points", last["session"],
                        f"market:{row['id']}", evidence_id=f"market:{row['id']}:{first['session']}:{last['session']}:benchmark"),
            ]
            complete.add(symbol)
        for symbol, metrics in partial.items():
            found.setdefault(symbol, metrics)
        return found

    def __call__(self):
        content, url, retrieved_at, stale = self._directory()
        directory = parse_directory(content); directory_hash = hashlib.sha256(content).hexdigest()
        financial, ownership, market = self._financial_metrics(), self._ownership_metrics(), self._market_metrics()
        local_symbols = sorted((set(financial) | set(ownership) | set(market)) & set(directory))
        securities = []
        for symbol in local_symbols:
            identity = directory[symbol]
            securities.append({"security_id": f"NSE:{symbol}", "symbol": symbol, "name": identity["name"],
                               "isin": identity["isin"], "listing_status": "active",
                               "metrics": financial.get(symbol, []) + ownership.get(symbol, []) + market.get(symbol, [])})
        observed = ist_date(retrieved_at)
        return {
            "version": f"nse-equity-directory/{observed}/{directory_hash[:12]}", "exchange": "NSE",
            "as_of_date": observed, "available_at": retrieved_at,
            "source_id": f"nse-equity-directory:{directory_hash}", "source_url": url,
            "source_sha256": directory_hash, "source_kind": "validated-public-stale" if stale else "validated-public",
            "coverage": (f"Official NSE equity directory: {len(directory)} active securities; "
                         f"{len(securities)} with locally saved screening evidence."),
            "security_count": len(directory), "assessed_security_count": len(securities),
            "unassessed_security_count": len(directory) - len(securities),
            "securities": securities,
        }


def _decimal(metric):
    return None if metric.get("value") is None else Decimal(str(metric["value"]))


def _bounded(value, maximum):
    return max(Decimal("0"), min(Decimal("100"), value / maximum * Decimal("100")))


def evaluate(security):
    metrics = {item["name"]: item for item in security["metrics"]}
    failures, missing = [], []
    for name, threshold in THRESHOLDS.items():
        metric = metrics.get(name)
        value = _decimal(metric) if metric else None
        if value is None:
            reason = metric.get("missing_reason") if metric else "metric absent from covered dataset"
            missing.append({"metric": name, "reason": reason})
        elif value < threshold:
            failures.append({"metric": name, "value": str(value), "threshold": str(threshold)})
    if security["listing_status"] != "active": failures.append({"metric": "listing_status", "value": security["listing_status"], "threshold": "active"})
    components = {"fundamentals": None, "accumulation": None, "momentum": None}
    values = {name: _decimal(metrics.get(name)) if metrics.get(name) else None for name in THRESHOLDS}
    if values["revenue_growth_percent"] is not None and values["operating_margin_percent"] is not None:
        components["fundamentals"] = (_bounded(values["revenue_growth_percent"], Decimal("30")) +
                                       _bounded(values["operating_margin_percent"], Decimal("30"))) / 2
    if values["institutional_change_pp"] is not None:
        components["accumulation"] = _bounded(values["institutional_change_pp"], Decimal("2"))
    if values["return_63d_percent"] is not None and values["relative_strength_63d_pp"] is not None:
        components["momentum"] = (_bounded(values["return_63d_percent"], Decimal("30")) +
                                  _bounded(values["relative_strength_63d_pp"], Decimal("15"))) / 2
    score = None if any(value is None for value in components.values()) else sum(components[key] * WEIGHTS[key] for key in components)
    render = lambda value: None if value is None else str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    eligible = not failures and not missing
    return {"security_id": security["security_id"], "symbol": security["symbol"], "name": security["name"],
            "listing_status": security["listing_status"], "eligible": eligible, "rank": None,
            "score": render(score), "components": {key: render(value) for key, value in components.items()},
            "metrics": security["metrics"], "failed_rules": failures, "missing_metrics": missing,
            "reason": "All required rules passed." if eligible else "Excluded because required evidence or thresholds did not pass."}


class DiscoveryService:
    def __init__(self, store, vault_dir, research, provider=None):
        self.store, self.vault, self.research = store, Vault(vault_dir), research
        self.provider = provider or fixture_universe
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS discovery_runs (
                    id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, schema_version TEXT NOT NULL,
                    policy_version TEXT NOT NULL, created_at TEXT NOT NULL, result TEXT NOT NULL,
                    note_path TEXT NOT NULL, note_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS discovery_requests (
                    request_key TEXT PRIMARY KEY, run_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS discovery_queue (
                    run_id TEXT NOT NULL, security_id TEXT NOT NULL, request_key TEXT UNIQUE NOT NULL,
                    research_run_id TEXT NOT NULL, queued_at TEXT NOT NULL,
                    PRIMARY KEY(run_id,security_id)
                );
            """)

    def screen(self, request_key):
        universe = self.provider()
        if universe.get("exchange") != "NSE" or universe.get("source_kind") not in ("synthetic-fixture", "validated-public", "validated-public-stale"):
            raise DiscoveryError("invalid", "Universe identity or source classification is invalid.")
        fingerprint = hashlib.sha256(json.dumps({"policy": POLICY_VERSION, "universe": universe}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self.store.connect() as db:
            request = db.execute("SELECT run_id FROM discovery_requests WHERE request_key=?", (request_key,)).fetchone()
            if request: return self.get(request["run_id"]), False
            existing = db.execute("SELECT id FROM discovery_runs WHERE fingerprint=?", (fingerprint,)).fetchone()
            if existing:
                db.execute("INSERT INTO discovery_requests VALUES (?,?)", (request_key, existing["id"]))
                return self.get(existing["id"]), False
        rows = [evaluate(item) for item in universe["securities"]]
        ranked = sorted((row for row in rows if row["eligible"]), key=lambda row: (-Decimal(row["score"]), row["symbol"]))
        for index, row in enumerate(ranked, 1): row["rank"] = index
        result = {"schema_version": SCHEMA_VERSION, "policy": {"version": POLICY_VERSION,
                  "thresholds": {key: str(value) for key, value in THRESHOLDS.items()},
                  "weights": {key: str(value) for key, value in WEIGHTS.items()}, "broker_execution": False,
                  "queue_destination": "persistent-research"}, "universe": {key: universe[key] for key in
                  ("version", "exchange", "as_of_date", "available_at", "source_id", "source_kind", "coverage",
                   "source_url", "source_sha256", "security_count", "assessed_security_count", "unassessed_security_count") if key in universe},
                  "candidate_count": len(ranked), "candidates": ranked,
                  "excluded": sorted((row for row in rows if not row["eligible"]), key=lambda row: row["symbol"]),
                  "limitations": (["Coverage is exactly the listed securities, not the whole NSE market.",
                                   "Fixture values demonstrate screening mechanics and are not investment conclusions."]
                                  if universe["source_kind"] == "synthetic-fixture" else
                                  ["Identity coverage comes from the official NSE equity directory; metric coverage is limited to saved local evidence.",
                                   "Securities without local screening evidence are counted as unassessed and never ranked.",
                                   "This cross-sectional coverage does not establish historical screening performance or investment returns."])
                                 + ["Missing required metrics exclude a security; they are never treated as zero.",
                                    "Discovery queues research only and cannot create paper or broker orders."]}
        run_id = str(uuid.uuid4()); created = now(); path = f"Graph Stock/Discovery/{universe['as_of_date']}/{fingerprint}.md"
        note = self._render(result)
        self.vault.publish(path, note)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO discovery_runs VALUES (?,?,?,?,?,?,?,?)",
                       (run_id, fingerprint, SCHEMA_VERSION, POLICY_VERSION, created, json.dumps(result, sort_keys=True), path, digest(note)))
            saved = db.execute("SELECT id FROM discovery_runs WHERE fingerprint=?", (fingerprint,)).fetchone()["id"]
            db.execute("INSERT INTO discovery_requests VALUES (?,?)", (request_key, saved))
        return self.get(saved), saved == run_id

    def queue(self, run_id, security_id, request_key):
        run = self.get(run_id)
        candidate = next((item for item in run["candidates"] if item["security_id"] == security_id), None)
        if not candidate: raise DiscoveryError("not-eligible", "Only an eligible candidate from this saved screen can be queued.")
        with self.store.connect() as db:
            existing = db.execute("SELECT * FROM discovery_queue WHERE run_id=? AND security_id=?", (run_id, security_id)).fetchone()
            if existing: return {**dict(existing), "research": self.research.get(existing["research_run_id"]), "created": False}
            reused = db.execute("SELECT * FROM discovery_queue WHERE request_key=?", (request_key,)).fetchone()
            if reused: raise DiscoveryError("conflict", "Request key already belongs to another candidate.")
        research_id, created = self.research.submit(candidate["symbol"], request_key)
        queued_at = now()
        with self.store.connect() as db:
            db.execute("INSERT INTO discovery_queue VALUES (?,?,?,?,?)", (run_id, security_id, request_key, research_id, queued_at))
        return {"run_id": run_id, "security_id": security_id, "research_run_id": research_id,
                "queued_at": queued_at, "research": self.research.get(research_id), "created": created}

    def get(self, run_id):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM discovery_runs WHERE id=?", (run_id,)).fetchone()
            if not row: raise DiscoveryError("not-found", "Discovery screen not found.")
            result = json.loads(row["result"]); result.update({key: row[key] for key in ("id", "fingerprint", "created_at", "note_path", "note_sha256")})
            queued = {item["security_id"]: dict(item) for item in db.execute("SELECT * FROM discovery_queue WHERE run_id=?", (run_id,))}
        for item in result["candidates"]: item["queued"] = queued.get(item["security_id"])
        return result

    def recent(self):
        with self.store.connect() as db: ids = [row[0] for row in db.execute("SELECT id FROM discovery_runs ORDER BY created_at DESC LIMIT 20")]
        return [self.get(run_id) for run_id in ids]

    def read_report(self, run_id): return self.vault.read(self.get(run_id)["note_path"])

    @staticmethod
    def _render(result):
        lines = ["# NSE candidate discovery", "", f"As of: **{result['universe']['as_of_date']}**  ",
                 f"Coverage: {result['universe']['coverage']}  ", f"Source kind: `{result['universe']['source_kind']}`  ",
                 f"Policy: `{POLICY_VERSION}`", "", "## Eligible candidates", ""]
        if result["universe"].get("source_url"):
            lines[5:5] = [f"Source: [{result['universe']['source_id']}]({result['universe']['source_url']})  ",
                          f"SHA-256: `{result['universe']['source_sha256']}`  "]
        if not result["candidates"]: lines.append("No security passed every required rule.")
        for item in result["candidates"]:
            lines += [f"### {item['rank']}. {item['symbol']} — score {item['score']}", "",
                      f"Fundamentals {item['components']['fundamentals']} · accumulation {item['components']['accumulation']} · momentum {item['components']['momentum']}", ""]
        lines += ["## Excluded", ""]
        for item in result["excluded"]:
            reasons = [entry["metric"] for entry in item["failed_rules"]] + [entry["metric"] for entry in item["missing_metrics"]]
            lines.append(f"- **{item['symbol']}** — {', '.join(reasons)}")
        lines += ["", "## Limits", ""] + [f"- {item}" for item in result["limitations"]]
        return "\n".join(lines) + "\n"
