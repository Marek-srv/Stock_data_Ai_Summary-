"""Point-in-time feature snapshots with conservative availability boundaries."""

from __future__ import annotations

import calendar
import hashlib
import json
import sqlite3
import uuid
from datetime import date, datetime, time, timedelta, timezone

from .vault import Vault
from .financials import calculate_metrics
from .history import apply_fact_corrections

SCHEMA_VERSION = "point-in-time-features/v1"
POLICY_VERSION = "public-availability-cutoff/v1"
IST = timezone(timedelta(hours=5, minutes=30))
FEATURE_FAMILIES = ("market", "benchmark", "financial", "ownership", "event", "reasoning")


class FeatureError(Exception):
    def __init__(self, message, code="invalid"):
        self.message, self.code = message, code
        super().__init__(message)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parse_decision_time(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise FeatureError("Decision time must be an ISO timestamp with a timezone.") from None
    if parsed.tzinfo is None:
        raise FeatureError("Decision time must include a timezone.")
    return parsed


def conservative_time(value, precision="timestamp"):
    """Resolve imprecise disclosure dates to the latest plausible instant."""
    if not value:
        return None
    try:
        if precision == "month":
            day = date.fromisoformat(str(value)[:10])
            last = calendar.monthrange(day.year, day.month)[1]
            return datetime.combine(date(day.year, day.month, last), time.max, IST)
        if precision == "date" or len(str(value)) == 10:
            return datetime.combine(date.fromisoformat(str(value)), time.max, IST)
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def _candidate(candidate):
    required = {"feature_id", "selection_key", "family", "name", "value", "unit", "effective_time",
                "public_available_at", "ingested_at", "public_precision", "source_id", "transform_version", "lineage"}
    if not required.issubset(candidate):
        raise FeatureError("Feature candidate is missing required lineage fields.")
    return candidate


def build_point_in_time(symbol, decision_time, candidates, aliases=None):
    decision = parse_decision_time(decision_time)
    eligible, excluded = [], []
    for raw in candidates:
        item = _candidate(dict(raw))
        effective = conservative_time(item["effective_time"], "date" if len(str(item["effective_time"])) == 10 else "timestamp")
        available = conservative_time(item["public_available_at"], item["public_precision"])
        ingested = conservative_time(item["ingested_at"], "timestamp")
        reason = item.pop("always_exclude", None)
        if reason is None and item["value"] is None:
            reason = "missing-value"
        if reason is None and effective is None:
            reason = "invalid-effective-time"
        if reason is None and available is None:
            reason = "missing-or-imprecise-public-availability"
        if reason is None and effective > decision:
            reason = "effective-after-decision"
        if reason is None and available > decision:
            reason = "published-after-decision"
        if reason is None and item.pop("revision_without_new_availability", False) and ingested and ingested > decision:
            reason = "revision-availability-unproven"
        item["data_vintage"] = {
            "effective_time": effective.isoformat() if effective else item["effective_time"],
            "public_available_at": available.isoformat() if available else item["public_available_at"],
            "ingested_at": ingested.isoformat() if ingested else item["ingested_at"],
            "ingested_after_decision": bool(ingested and ingested > decision),
        }
        if reason:
            item["exclusion_reason"] = reason
            excluded.append(item)
        else:
            eligible.append(item)

    selected = []
    by_key = {}
    for item in eligible:
        by_key.setdefault(item["selection_key"], []).append(item)
    for key, rows in by_key.items():
        rows.sort(key=lambda item: (item["data_vintage"]["public_available_at"], item["data_vintage"]["effective_time"], item["feature_id"]))
        selected.append(rows[-1])
        for old in rows[:-1]:
            old["exclusion_reason"] = "superseded-at-cutoff"
            excluded.append(old)
    selected.sort(key=lambda item: (item["family"], item["name"], item["feature_id"]))
    excluded.sort(key=lambda item: (item["family"], item["name"], item["feature_id"]))

    aliases = aliases or []
    decision_day = decision.astimezone(IST).date().isoformat()
    active_aliases = [item for item in aliases if item["effective_from"] <= decision_day and
                      (item.get("effective_to") is None or item["effective_to"] >= decision_day)]
    listing = {
        "decision_date": decision_day, "active_aliases": active_aliases,
        "status": "active" if active_aliases else "unknown",
        "limitation": "Single-security, currently known listing history; no NSE-wide or delisted-security coverage.",
    }
    manifest_inputs = [{key: item[key] for key in ("feature_id", "family", "source_id", "transform_version", "data_vintage")}
                       for item in selected]
    manifest = {
        "policy_version": POLICY_VERSION, "symbol": symbol, "decision_time": decision.isoformat(),
        "feature_inputs": manifest_inputs, "active_aliases": active_aliases,
    }
    coverage = {family: {"included": sum(item["family"] == family for item in selected),
                         "excluded": sum(item["family"] == family for item in excluded)} for family in FEATURE_FAMILIES}
    return {
        "schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION, "symbol": symbol,
        "decision_time": decision.isoformat(), "knowledge_basis": "public availability at or before the decision time",
        "precision_policy": {
            "timestamp": "use the recorded timezone-aware instant",
            "date": "eligible only after 23:59:59.999999 Asia/Kolkata on the stated date",
            "month": "eligible only after the final calendar day of the stated month",
        },
        "included": selected, "excluded": excluded, "coverage": coverage, "universe": listing,
        "dataset_manifest": {**manifest, "hash": _hash(manifest)},
        "limitations": [
            "Ingestion after the decision is allowed only for deterministic reconstruction of evidence proven publicly available by then.",
            "Retrospective reasoning narratives are excluded even when their underlying filing predates the decision.",
            "This snapshot does not claim survivorship-safe NSE-wide universe coverage.",
        ],
    }


def _financial_candidates(db, symbol):
    rows = db.execute("""SELECT j.id,j.source_id,j.use_reasoning,j.snapshot,j.interpretation,s.metadata
                         FROM financial_jobs j JOIN filing_sources s ON s.id=j.source_id
                         WHERE s.symbol=? AND j.status='completed' AND j.snapshot IS NOT NULL""", (symbol,)).fetchall()
    result = []
    for row in rows:
        snapshot, metadata = json.loads(row["snapshot"]), json.loads(row["metadata"])
        correction_ids = []
        if snapshot.get("facts"):
            snapshot["facts"], correction_ids = apply_fact_corrections(db, snapshot["facts"])
            if correction_ids: snapshot["metrics"] = calculate_metrics(snapshot["facts"])
        source = metadata
        available = source.get("public_available_at")
        precision = "date" if available and len(available) == 10 else "timestamp"
        security = source.get("security") or {}
        eligible = bool(available and str(source.get("origin", "")).startswith("https://") and
                        security.get("verification") == "NSE directory")
        for metric in snapshot["metrics"]:
            result.append({
                "feature_id": f"financial:{row['id']}:{metric['id']}", "selection_key": f"financial:{metric['id']}",
                "family": "financial", "name": metric["label"], "value": metric["value"], "unit": metric["unit"],
                "effective_time": metric["period_end"], "public_available_at": available,
                "ingested_at": source.get("retrieved_at"), "public_precision": precision,
                "source_id": row["source_id"], "transform_version": metric["formula_version"] + (
                    ":corrections:" + _hash(correction_ids)[:12] if correction_ids else ""),
                "lineage": {"metric_id": metric["id"], "input_fact_ids": metric["input_fact_ids"],
                            "evidence_ids": metric["evidence_ids"], "input_restated": metric["input_restated"],
                            "scope": metric["scope"], "period": metric["period"],
                            "eligibility_rule": "verified NSE origin with recorded public availability",
                            "legacy_source_flag": source.get("historical_feature_eligible")},
                **({"always_exclude": "source-not-historically-eligible"} if not eligible else {}),
            })
        if row["use_reasoning"]:
            result.append({
                "feature_id": f"reasoning:{row['id']}", "selection_key": "reasoning:financial-interpretation",
                "family": "reasoning", "name": "Retrospective financial interpretation", "value": "present", "unit": "narrative",
                "effective_time": snapshot["period"][-4:] + "-03-31", "public_available_at": available,
                "ingested_at": snapshot["created_at"], "public_precision": precision, "source_id": row["source_id"],
                "transform_version": "reasoning-output", "lineage": {"financial_run_id": row["id"]},
                "always_exclude": "retrospective-reasoning-not-historical",
            })
    return result


def _ownership_candidates(db, symbol):
    precision = {}
    for row in db.execute("SELECT result FROM ownership_runs WHERE symbol=?", (symbol,)).fetchall():
        for source in json.loads(row["result"])["sources"]:
            precision[source["source_id"]] = source.get("publication_precision", "timestamp")
    sources = db.execute("SELECT * FROM ownership_sources WHERE symbol=?", (symbol,)).fetchall()
    result = []
    for source in sources:
        for holding in db.execute("SELECT * FROM ownership_holdings WHERE source_id=?", (source["source_id"],)).fetchall():
            value = json.loads(json.dumps(dict(holding)))
            result.append({
                "feature_id": f"ownership:{source['source_id']}:{holding['holder_id']}",
                "selection_key": f"ownership:{holding['holder_id']}", "family": "ownership",
                "name": holding["name"], "value": holding["shares"], "unit": "shares",
                "effective_time": source["period"], "public_available_at": source["published_at"],
                "ingested_at": source["ingested_at"], "public_precision": precision.get(source["source_id"], "timestamp"),
                "source_id": source["source_id"], "transform_version": "ownership-disclosure/v1",
                "lineage": {"holder_id": holding["holder_id"], "kind": holding["kind"],
                            "percent": holding["percent"], "coverage": holding["coverage"],
                            "denominator_shares": source["denominator_shares"]},
            })
    return result


def _news_candidates(db, symbol):
    result = []
    for row in db.execute("SELECT version_id,version,created_at,payload FROM news_events WHERE symbol=?", (symbol,)).fetchall():
        event = json.loads(row["payload"])
        result.append({
            "feature_id": f"news:{row['version_id']}", "selection_key": f"news:{event['canonical_key']}",
            "family": "event", "name": event["event_type"],
            "value": {"severity": event["severity"], "material": event["material"], "fact": event["facts"][0]["text"]},
            "unit": "event", "effective_time": event["event_date"], "public_available_at": event["first_available_at"],
            "ingested_at": event["retrieved_at"], "public_precision": "timestamp",
            "source_id": event["sources"][0]["source_id"], "transform_version": "news-catalyst/v1",
            "lineage": {"event_id": event["event_id"], "version_id": row["version_id"],
                        "evidence_ids": [source["source_id"] for source in event["sources"]]},
            "revision_without_new_availability": row["version"] > 1,
        })
    return result


def _market_candidates(db, symbol):
    result, aliases = [], []
    for row in db.execute("SELECT id,result FROM market_runs WHERE symbol=?", (symbol,)).fetchall():
        run = json.loads(row["result"])
        aliases.extend(run["aliases"])
        source = run["source"]
        for bar in run["adjusted_bars"]:
            base = {"effective_time": bar["session"] + "T15:30:00+05:30", "public_available_at": source["available_at"],
                    "ingested_at": source["retrieved_at"], "public_precision": "timestamp",
                    "source_id": source["source_id"], "transform_version": run["adjustment_version"],
                    "lineage": {"market_run_id": row["id"], "session": bar["session"], "raw_row": bar["row"],
                                "price_factor": bar["price_factor"], "share_factor": bar["share_factor"],
                                "adjustment_status": bar["adjustment_status"]}}
            reason = "incomplete-market-session" if bar["status"] == "intraday" else (
                "blocked-corporate-action-adjustment" if bar["adjustment_status"] == "blocked" else None)
            for key, label, unit in (("adjusted_close", "Adjusted close", "INR"), ("adjusted_volume", "Adjusted volume", "shares")):
                result.append({"feature_id": f"market:{row['id']}:{bar['session']}:{key}",
                               "selection_key": f"market:{bar['session']}:{key}", "family": "market",
                               "name": f"{label} {bar['session']}", "value": bar[key], "unit": unit, **base,
                               **({"always_exclude": reason} if reason else {})})
        for bar in run["benchmark"]["bars"]:
            result.append({
                "feature_id": f"benchmark:{row['id']}:{bar['session']}", "selection_key": f"benchmark:{bar['session']}",
                "family": "benchmark", "name": f"{run['benchmark']['symbol']} close {bar['session']}",
                "value": bar["close"], "unit": "index points", "effective_time": bar["session"] + "T15:30:00+05:30",
                "public_available_at": source["available_at"], "ingested_at": source["retrieved_at"],
                "public_precision": "timestamp", "source_id": source["source_id"], "transform_version": "raw-market-bar/v1",
                "lineage": {"market_run_id": row["id"], "session": bar["session"], "raw_row": bar["row"]},
                **({"always_exclude": "incomplete-market-session"} if bar["status"] == "intraday" else {}),
            })
    unique_aliases = {(item["symbol"], item["effective_from"]): item for item in aliases}
    return result, list(unique_aliases.values())


def collect_candidates(store, symbol):
    with store.connect() as db:
        candidates = _financial_candidates(db, symbol)
        candidates += _ownership_candidates(db, symbol)
        candidates += _news_candidates(db, symbol)
        market, aliases = _market_candidates(db, symbol)
        candidates += market
    return candidates, aliases


def _render(result):
    lines = [f"# Point-in-Time Features — {result['symbol']}", "", f"Snapshot: `{result['id']}`",
             f"Decision time: `{result['decision_time']}`", f"Policy: `{POLICY_VERSION}`",
             f"Dataset manifest: `{result['dataset_manifest']['hash']}`", "", "## Included features", ""]
    if not result["included"]:
        lines.append("- None")
    for item in result["included"]:
        lines.append(f"- **{item['family']} · {item['name']}**: `{item['value']} {item['unit']}` — public `{item['data_vintage']['public_available_at']}`; source `{item['source_id']}`")
    lines += ["", "## Excluded candidates", ""]
    if not result["excluded"]:
        lines.append("- None")
    for item in result["excluded"]:
        lines.append(f"- **{item['family']} · {item['name']}** — `{item['exclusion_reason']}`; effective `{item['data_vintage']['effective_time']}`; public `{item['data_vintage']['public_available_at']}`")
    lines += ["", "## Universe and listing limits", "", result["universe"]["limitation"], "",
              "## Precision policy", "", *[f"- **{key}:** {value}" for key, value in result["precision_policy"].items()],
              "", "## Limitations", "", *[f"- {item}" for item in result["limitations"]], ""]
    return "\n".join(lines)


class FeatureService:
    def __init__(self, store, vault_dir):
        self.store, self.vault = store, Vault(vault_dir)
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS feature_snapshots (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
                    symbol TEXT NOT NULL, decision_time TEXT NOT NULL, created_at TEXT NOT NULL,
                    result TEXT NOT NULL
                );
            """)

    def submit(self, symbol, decision_time, request_key):
        symbol = symbol.strip().upper()
        decision = parse_decision_time(decision_time).isoformat()
        fingerprint = _hash({"symbol": symbol, "decision_time": decision, "policy": POLICY_VERSION})
        with self.store.connect() as db:
            prior = db.execute("SELECT id,fingerprint FROM feature_snapshots WHERE request_key=?", (request_key,)).fetchone()
        if prior:
            if prior["fingerprint"] != fingerprint:
                raise FeatureError("Request key already belongs to another feature snapshot.", "conflict")
            return self.get(prior["id"]), False
        candidates, aliases = collect_candidates(self.store, symbol)
        result = build_point_in_time(symbol, decision, candidates, aliases)
        result.update({"id": str(uuid.uuid4()), "created_at": _now(), "report": None})
        content = _render(result)
        path = f"Graph Stock/Features/{symbol}/{result['id']}.md"
        self.vault.publish(path, content)
        result["report"] = {"path": path, "sha256": hashlib.sha256(content.encode()).hexdigest()}
        with self.store.connect() as db:
            db.execute("INSERT INTO feature_snapshots VALUES (?,?,?,?,?,?,?)", (
                result["id"], request_key, fingerprint, symbol, decision, result["created_at"], json.dumps(result, sort_keys=True)))
        return result, True

    def get(self, run_id):
        with self.store.connect() as db:
            row = db.execute("SELECT result FROM feature_snapshots WHERE id=?", (str(run_id),)).fetchone()
        if not row:
            raise KeyError(run_id)
        return json.loads(row["result"])

    def recent(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT result FROM feature_snapshots ORDER BY created_at DESC LIMIT 30").fetchall()
        return [json.loads(row["result"]) for row in rows]

    def read_report(self, run_id):
        return self.vault.read(self.get(run_id)["report"]["path"])
