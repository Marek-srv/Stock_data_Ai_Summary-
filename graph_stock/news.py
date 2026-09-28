"""Dated, deduplicated company events with explicit evidence semantics."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone

from .vault import Vault, digest

NEWS_SCHEMA_VERSION = "news-catalyst/v1"
NEWS_POLICY_VERSION = "material-events/v1"


class NewsError(Exception):
    def __init__(self, message, code="invalid"):
        self.message, self.code = message, code
        super().__init__(message)


class NewsProviderError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def representative_bel_records(symbol):
    if symbol != "BEL":
        raise NewsProviderError("Representative news coverage is currently available for BEL only.")
    common = {
        "canonical_key": "BEL:contract:air-defence-fire-control-radars:2025-07-25",
        "event_type": "contract", "event_date": "2025-07-25", "amount_inr_crore": "2000",
        "fact": "The Ministry of Defence signed a contract with BEL for Air Defence Fire Control Radars.",
        "assertion": "The disclosed contract value is approximately INR 2,000 crore.",
        "reported_relevance": "The source describes the contract as supporting Indian Army air-defence modernisation.",
    }
    return [
        {**common, "source_id": "nse-bel-2025-07-25-adfcr", "source_kind": "primary-filing",
         "title": "Awarding of order(s)/contract(s)",
         "url": "https://www.nseindia.com/companies-listing/corporate-filings-announcements?symbol=BEL&tabIndex=equity",
         "available_at": "2025-07-25T14:24:37+05:30", "retrieved_at": _now(),
         "locator": "BEL announcement; exchange received time 25-Jul-2025 14:24:37"},
        {**common, "source_id": "pib-2148334", "source_kind": "supporting-news",
         "title": "MoD inks approx. Rs 2,000 crore contract with BEL",
         "url": "https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=2148334&lang=2&reg=48",
         "available_at": "2025-07-25T15:16:00+05:30", "retrieved_at": _now(),
         "locator": "PIB release ID 2148334"},
    ]


def _severity(record):
    if record["event_type"] in ("fraud", "default", "regulatory-action"):
        return "high"
    amount = float(record["amount_inr_crore"]) if record.get("amount_inr_crore") else 0
    return "high" if amount >= 1000 else "medium" if amount >= 100 else "low"


def normalize_records(symbol, records):
    required = {"canonical_key", "event_type", "event_date", "fact", "assertion", "reported_relevance",
                "source_id", "source_kind", "title", "url", "available_at", "retrieved_at", "locator"}
    grouped = {}
    for raw in records:
        if set(raw) - (required | {"amount_inr_crore"}) or not required.issubset(raw):
            raise NewsError("Event source does not match the versioned import schema.")
        if raw["source_kind"] not in ("primary-filing", "supporting-news", "manual"):
            raise NewsError("Event source kind is unsupported.")
        key = raw["canonical_key"]
        factual = {k: raw.get(k) for k in ("event_type", "event_date", "amount_inr_crore", "fact", "assertion", "reported_relevance")}
        existing = grouped.setdefault(key, {"factual": factual, "sources": []})
        if existing["factual"] != factual:
            raise NewsError("Conflicting records share a canonical event key; import as a revision.")
        source = {k: raw[k] for k in ("source_id", "source_kind", "title", "url", "available_at", "retrieved_at", "locator")}
        if source["source_id"] not in {item["source_id"] for item in existing["sources"]}:
            existing["sources"].append(source)
    events = []
    for key, value in sorted(grouped.items()):
        factual, sources = value["factual"], sorted(value["sources"], key=lambda x: (x["available_at"], x["source_id"]))
        source_ids = [source["source_id"] for source in sources]
        event = {
            "event_id": "event:" + _hash({"symbol": symbol, "canonical_key": key})[:24],
            "canonical_key": key, "symbol": symbol, **factual,
            "severity": _severity(factual), "material": _severity(factual) in ("high", "medium"),
            "first_available_at": sources[0]["available_at"], "retrieved_at": max(s["retrieved_at"] for s in sources),
            "sources": sources,
            "facts": [{"text": factual["fact"], "evidence_ids": source_ids}],
            "source_assertions": [{"text": factual["assertion"], "evidence_ids": source_ids},
                                  {"text": factual["reported_relevance"], "evidence_ids": source_ids}],
            "inferences": [{"text": "The disclosed order may support future revenue, subject to execution timing and margins.",
                            "evidence_ids": source_ids, "confidence": "limited"}],
        }
        event["content_hash"] = _hash({
            **{k: event[k] for k in ("canonical_key", "event_type", "event_date", "amount_inr_crore", "fact", "assertion", "reported_relevance") if k in event},
            "sources": [{k: source[k] for k in ("source_id", "source_kind", "title", "url", "available_at", "locator")}
                        for source in sources],
        })
        events.append(event)
    return events


def current_news(store, symbol):
    try:
        with store.connect() as db:
            rows = db.execute("SELECT payload FROM news_events WHERE symbol=? AND is_current=1 ORDER BY first_available_at DESC", (symbol,)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [json.loads(row["payload"]) for row in rows]


def news_descriptor(store, symbol):
    events = current_news(store, symbol)
    material = [{"event_id": e["event_id"], "version": e["version"], "content_hash": e["content_hash"]}
                for e in events if e["material"]]
    return {"schema_version": NEWS_SCHEMA_VERSION, "event_count": len(events),
            "material_event_count": len(material), "digest": _hash(material), "events": material}


def latest_news_run(store, symbol):
    try:
        with store.connect() as db:
            row = db.execute("SELECT result FROM news_runs WHERE symbol=? ORDER BY created_at DESC LIMIT 1",
                             (symbol,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return json.loads(row["result"]) if row else None


class NewsService:
    def __init__(self, store, filings, vault_dir, provider=representative_bel_records):
        self.store, self.filings, self.vault, self.provider = store, filings, Vault(vault_dir), provider
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS news_events (
                    version_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, canonical_key TEXT NOT NULL,
                    symbol TEXT NOT NULL, version INTEGER NOT NULL, is_current INTEGER NOT NULL,
                    content_hash TEXT NOT NULL, first_available_at TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL,
                    UNIQUE(symbol,canonical_key,version)
                );
                CREATE TABLE IF NOT EXISTS news_runs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, source_id TEXT NOT NULL,
                    symbol TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, result TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_invalidations (
                    event_version_id TEXT NOT NULL, target TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(event_version_id,target)
                );
            """)

    def submit(self, source_id, request_key, records=None):
        try:
            source, _ = self.filings.source(source_id)
        except KeyError:
            raise NewsError("Filing source not found.", "not-found") from None
        with self.store.connect() as db:
            prior = db.execute("SELECT id,source_id FROM news_runs WHERE request_key=?", (request_key,)).fetchone()
        if prior:
            if prior["source_id"] != source_id:
                raise NewsError("Request key already belongs to another source.", "conflict")
            return self.get(prior["id"]), False
        run_id, created_at, gap = str(uuid.uuid4()), _now(), None
        try:
            incoming = normalize_records(source["symbol"], records if records is not None else self.provider(source["symbol"]))
        except NewsProviderError as error:
            incoming, gap = [], str(error)
        new_versions = []
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for event in incoming:
                old = db.execute("SELECT version_id,version,content_hash FROM news_events WHERE symbol=? AND canonical_key=? AND is_current=1",
                                 (source["symbol"], event["canonical_key"])).fetchone()
                if old and old["content_hash"] == event["content_hash"]:
                    continue
                version = old["version"] + 1 if old else 1
                version_id = f"{event['event_id']}:v{version}"
                event.update({"version": version, "version_id": version_id,
                              "supersedes": old["version_id"] if old else None})
                if old:
                    db.execute("UPDATE news_events SET is_current=0 WHERE version_id=?", (old["version_id"],))
                db.execute("INSERT INTO news_events VALUES (?,?,?,?,?,?,?,?,?,?)", (
                    version_id, event["event_id"], event["canonical_key"], source["symbol"], version, 1,
                    event["content_hash"], event["first_available_at"], created_at, json.dumps(event, sort_keys=True)))
                new_versions.append(version_id)
                if event["material"]:
                    for target in ("news_catalyst", "risk", "bull", "bear", "judge", "investment_thesis", "report"):
                        db.execute("INSERT OR IGNORE INTO research_invalidations VALUES (?,?,?)", (version_id, target, created_at))
            events = [json.loads(row["payload"]) for row in db.execute(
                "SELECT payload FROM news_events WHERE symbol=? AND is_current=1 ORDER BY first_available_at DESC",
                (source["symbol"],)).fetchall()]
            status = "partial" if gap else "completed"
            result = {"id": run_id, "schema_version": NEWS_SCHEMA_VERSION, "policy_version": NEWS_POLICY_VERSION,
                      "symbol": source["symbol"], "source_id": source_id, "status": status, "created_at": created_at,
                      "events": events, "new_event_versions": new_versions,
                      "coverage": {"primary_filings": "available" if events else "missing",
                                   "supporting_news": "available" if any(s["source_kind"] == "supporting-news" for e in events for s in e["sources"]) else "missing",
                                   "historical_features": "deferred-to-GS-12"},
                      "gaps": [gap] if gap else [], "report": None}
            content = self._render(result)
            path = f"Graph Stock/News/{source['symbol']}/{run_id}.md"
            self.vault.publish(path, content)
            result["report"] = {"path": path, "sha256": digest(content)}
            db.execute("INSERT INTO news_runs VALUES (?,?,?,?,?,?,?)", (run_id, request_key, source_id,
                       source["symbol"], status, created_at, json.dumps(result, sort_keys=True)))
        return result, True

    @staticmethod
    def _render(result):
        lines = [f"# News & Catalysts — {result['symbol']}", "", f"Run: `{result['id']}`", "",
                 f"Coverage: `{json.dumps(result['coverage'], sort_keys=True)}`", ""]
        for event in result["events"]:
            lines += [f"## {event['event_date']} — {event['event_type']} ({event['severity']})", "",
                      f"**Fact:** {event['facts'][0]['text']}", "",
                      f"**Source assertion:** {event['source_assertions'][0]['text']}", "",
                      f"**Reported relevance:** {event['source_assertions'][1]['text']}", "",
                      f"**Inference ({event['inferences'][0]['confidence']} confidence):** {event['inferences'][0]['text']}", "",
                      f"First public availability: `{event['first_available_at']}`  ",
                      f"Retrieved: `{event['retrieved_at']}`", "", "Sources:"]
            lines += [f"- [{s['title']}]({s['url']}) — {s['source_kind']}; {s['available_at']}; {s['locator']}" for s in event["sources"]]
            lines += [""]
        if result["gaps"]:
            lines += ["## Coverage gaps", "", *[f"- {gap}" for gap in result["gaps"]], ""]
        lines += ["## Limits", "", "- Current-event coverage only; historical event features require GS-12 eligibility.",
                  "- Source text is evidence data and is never treated as an instruction.",
                  "- Reported relevance and research inference are displayed separately from fact.", ""]
        return "\n".join(lines)

    def get(self, run_id):
        with self.store.connect() as db:
            row = db.execute("SELECT result FROM news_runs WHERE id=?", (str(run_id),)).fetchone()
        if not row:
            raise KeyError(run_id)
        return json.loads(row["result"])

    def recent(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT result FROM news_runs ORDER BY created_at DESC LIMIT 20").fetchall()
        return [json.loads(row["result"]) for row in rows]

    def read_report(self, run_id):
        result = self.get(run_id)
        return self.vault.read(result["report"]["path"])
