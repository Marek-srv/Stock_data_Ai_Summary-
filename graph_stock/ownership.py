"""Point-in-time ownership comparisons with conservative disclosure semantics."""

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone

from .vault import Vault

SCHEMA_VERSION = "ownership-v1"
BEL_TOTAL_SHARES = 7_309_778_829


class OwnershipError(Exception):
    def __init__(self, message, code="invalid"):
        self.message, self.code = message, code
        super().__init__(message)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _row(holder_id, name, kind, shares, percent, *, fund_house=None, coverage="complete",
         identity="exact"):
    return {"holder_id": holder_id, "name": name, "kind": kind, "shares": shares,
            "percent": percent, "fund_house": fund_house, "coverage": coverage,
            "identity": identity}


def bel_disclosures(current_source):
    """Measured rows from BEL's FY2024 and FY2025 issuer annual reports."""
    periods = [
        {
            "period": "2024-03-31", "published_at": "2024-08-01T00:00:00+00:00",
            "publication_precision": "month", "publication_basis": "month encoded in issuer URL; day unresolved",
            "ingested_at": _now(), "source_id": "bel-annual-report-2023-24",
            "title": "BEL Integrated Annual Report 2023-24",
            "origin": "https://bel-india.in/wp-content/uploads/2024/08/Integrated-Annual-Report-2023-24-1.pdf",
            "coverage": {"aggregate": "complete", "named_holders": "partial", "pledge": "missing"},
            "denominator_shares": BEL_TOTAL_SHARES, "corporate_action_basis": "INE263A01024",
            "holdings": [
                _row("aggregate:promoter", "Central Government", "promoter", 3_737_921_934, "51.14"),
                _row("aggregate:fii", "Foreign Portfolio Investors", "fii", 1_283_883_778, "17.56"),
                _row("aggregate:dii", "Domestic institutions", "dii", 1_654_827_356, "22.63"),
                _row("scheme:hdfc-pension-e-tier1", "NPS Trust A/C HDFC Pension Management Company Ltd Scheme E - Tier I", "scheme", 96_025_428, "1.31", fund_house="HDFC Pension Management Company", coverage="partial"),
                _row("scheme:canara-robeco-emerging-equities", "Canara Robeco Emerging Equities", "scheme", 86_229_550, "1.18", fund_house="Canara Robeco Mutual Fund", coverage="partial"),
            ],
        },
        {
            "period": "2025-03-31", "published_at": current_source.get("public_available_at") or "2025-08-01T00:00:00+00:00",
            "publication_precision": "timestamp" if current_source.get("public_available_at") else "month",
            "publication_basis": current_source.get("availability_basis") or "month encoded in issuer URL; day unresolved",
            "ingested_at": current_source.get("retrieved_at") or _now(), "source_id": current_source["id"],
            "title": current_source["title"], "origin": current_source["origin"],
            "coverage": {"aggregate": "complete", "named_holders": "complete-top-10", "pledge": "missing"},
            "denominator_shares": BEL_TOTAL_SHARES, "corporate_action_basis": "INE263A01024",
            "holdings": [
                _row("aggregate:promoter", "Central Government", "promoter", 3_737_921_934, "51.14"),
                _row("aggregate:fii", "Foreign Portfolio Investors", "fii", 1_283_391_147, "17.56"),
                _row("aggregate:dii", "Domestic institutions", "dii", 1_525_898_423, "20.87"),
                _row("scheme:hdfc-pension-e-tier1", "NPS Trust A/C HDFC Pension Management Company Ltd Scheme E - Tier I", "scheme", 106_713_025, "1.46", fund_house="HDFC Pension Management Company"),
                _row("scheme:canara-robeco-emerging-equities", "Canara Robeco Emerging Equities", "scheme", 79_371_005, "1.09", fund_house="Canara Robeco Mutual Fund"),
                _row("scheme:kotak-flexicap", "Kotak Flexicap Fund", "scheme", 183_651_617, "2.51", fund_house="Kotak Mutual Fund"),
            ],
        },
    ]
    return periods


def compare_periods(prior, current):
    """Compare disclosure snapshots without inventing trades or unsupported exits."""
    comparable = (prior["denominator_shares"] == current["denominator_shares"] and
                  prior.get("corporate_action_basis") == current.get("corporate_action_basis"))
    prior_rows = {row["holder_id"]: row for row in prior["holdings"]}
    current_rows = {row["holder_id"]: row for row in current["holdings"]}
    comparisons = []
    for holder_id in sorted(prior_rows.keys() | current_rows.keys()):
        old, new = prior_rows.get(holder_id), current_rows.get(holder_id)
        row = new or old
        status, reason = "unknown", None
        if row["identity"] != "exact":
            reason = "holder-identity-ambiguous"
        elif not comparable:
            reason = "denominator-or-corporate-action-change"
        elif old and new:
            delta = new["shares"] - old["shares"]
            status = "accumulation" if delta > 0 else "reduction" if delta < 0 else "unchanged"
        elif new and prior["coverage"]["named_holders"] == "complete":
            status = "entry"
        elif old and current["coverage"]["named_holders"] == "complete":
            status = "exit"
        else:
            reason = "incomplete-comparable-holder-coverage"
        comparisons.append({
            "holder_id": holder_id, "name": row["name"], "kind": row["kind"],
            "fund_house": row.get("fund_house"), "status": status, "reason": reason,
            "prior": ({"shares": old["shares"], "percent": old["percent"]} if old else None),
            "current": ({"shares": new["shares"], "percent": new["percent"]} if new else None),
            "share_change": new["shares"] - old["shares"] if comparable and old and new else None,
            "percentage_point_change": (f"{float(new['percent']) - float(old['percent']):.2f}"
                                        if comparable and old and new else None),
        })
    return {"comparable": comparable, "prior_period": prior["period"], "current_period": current["period"],
            "comparisons": comparisons,
            "limitations": ["Periodic ownership changes do not identify exact trade execution.",
                            "Entry and exit require complete comparable holder coverage."]}


def latest_ownership(store, symbol):
    try:
        with store.connect() as db:
            row = db.execute("SELECT result FROM ownership_runs WHERE symbol=? ORDER BY created_at DESC LIMIT 1",
                             (symbol,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return json.loads(row["result"]) if row else None


def ownership_descriptor(store, symbol):
    result = latest_ownership(store, symbol)
    if not result:
        return {"schema_version": SCHEMA_VERSION, "run_id": None, "digest": hashlib.sha256(b"null").hexdigest()}
    value = {"run_id": result["id"], "comparison": result["comparison"], "sources": result["sources"]}
    return {"schema_version": SCHEMA_VERSION, "run_id": result["id"],
            "digest": hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def _markdown(kind, result):
    comparison = result["comparison"]
    rows = comparison["comparisons"]
    selected = [r for r in rows if (r["kind"] in ("promoter", "fii", "dii")) == (kind == "shareholding")]
    title = "Shareholding" if kind == "shareholding" else "Institutional Flow"
    lines = [f"# {title} — {result['symbol']}", "", f"Run: `{result['id']}`", f"Schema: `{SCHEMA_VERSION}`",
             f"Periods: {comparison['prior_period']} → {comparison['current_period']}", "",
             "| Holder | Previous shares | Previous % | Current shares | Current % | Observed state |", "|---|---:|---:|---:|---:|---|"]
    for row in selected:
        old, new = row["prior"] or {}, row["current"] or {}
        lines.append(f"| {row['name']} | {old.get('shares', '—')} | {old.get('percent', '—')} | {new.get('shares', '—')} | {new.get('percent', '—')} | {row['status']} |")
    lines += ["", "## Sources"]
    for source in result["sources"]:
        lines.append(f"- [{source['title']}]({source['origin']}) — as of {source['period']}; "
                     f"published {source['published_at']} ({source['publication_precision']}; {source['publication_basis']}); "
                     f"ingested {source['ingested_at']}; coverage {json.dumps(source['coverage'], sort_keys=True)}")
    lines += ["", "## Limits", "", *[f"- {item}" for item in comparison["limitations"]]]
    if kind == "shareholding":
        lines.append("- Pledge disclosure was unavailable in both bounded source records.")
    return "\n".join(lines) + "\n"


class OwnershipService:
    def __init__(self, store, filings, vault_dir):
        self.store, self.filings, self.vault = store, filings, Vault(vault_dir)
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS ownership_sources (
                    source_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, period TEXT NOT NULL,
                    published_at TEXT NOT NULL, ingested_at TEXT NOT NULL, origin TEXT NOT NULL,
                    coverage TEXT NOT NULL, denominator_shares INTEGER NOT NULL,
                    corporate_action_basis TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ownership_holdings (
                    source_id TEXT NOT NULL, holder_id TEXT NOT NULL, name TEXT NOT NULL,
                    kind TEXT NOT NULL, fund_house TEXT, shares INTEGER NOT NULL,
                    percent TEXT NOT NULL, identity TEXT NOT NULL, coverage TEXT NOT NULL,
                    PRIMARY KEY(source_id, holder_id),
                    FOREIGN KEY(source_id) REFERENCES ownership_sources(source_id)
                );
                CREATE TABLE IF NOT EXISTS ownership_runs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, source_id TEXT NOT NULL,
                    symbol TEXT NOT NULL, created_at TEXT NOT NULL, result TEXT NOT NULL
                );
            """)

    def submit(self, source_id, request_key):
        try:
            source, _ = self.filings.source(source_id)
        except KeyError:
            raise OwnershipError("Filing source not found", "not-found") from None
        if source["symbol"] != "BEL":
            raise OwnershipError("Measured ownership coverage is currently available for BEL only", "coverage")
        with self.store.connect() as db:
            existing = db.execute("SELECT id FROM ownership_runs WHERE request_key=?", (request_key,)).fetchone()
            if existing:
                row = db.execute("SELECT source_id FROM ownership_runs WHERE id=?", (existing["id"],)).fetchone()
                if row["source_id"] != source_id:
                    raise OwnershipError("Request key already belongs to another source", "conflict")
                return self.get(existing["id"]), False
        periods = bel_disclosures(source)
        comparison = compare_periods(*periods)
        run_id = str(uuid.uuid4())
        sources = [{key: period[key] for key in ("source_id", "title", "origin", "period", "published_at", "publication_precision", "publication_basis", "ingested_at", "coverage", "denominator_shares", "corporate_action_basis")} for period in periods]
        result = {"id": run_id, "schema_version": SCHEMA_VERSION, "symbol": "BEL", "created_at": _now(),
                  "sources": sources, "comparison": comparison, "reports": {}}
        for kind in ("shareholding", "institutional-flow"):
            path = f"Graph Stock/Ownership/BEL/{run_id}-{kind}.md"
            content = _markdown(kind, result)
            self.vault.publish(path, content)
            result["reports"][kind] = {"path": path, "sha256": hashlib.sha256(content.encode()).hexdigest()}
        with self.store.connect() as db:
            for period in periods:
                db.execute("INSERT OR IGNORE INTO ownership_sources VALUES (?,?,?,?,?,?,?,?,?)", (
                    period["source_id"], "BEL", period["period"], period["published_at"],
                    period["ingested_at"], period["origin"], json.dumps(period["coverage"], sort_keys=True),
                    period["denominator_shares"], period["corporate_action_basis"]))
                for holding in period["holdings"]:
                    db.execute("INSERT OR IGNORE INTO ownership_holdings VALUES (?,?,?,?,?,?,?,?,?)", (
                        period["source_id"], holding["holder_id"], holding["name"], holding["kind"],
                        holding.get("fund_house"), holding["shares"], holding["percent"],
                        holding["identity"], holding["coverage"]))
            db.execute("INSERT INTO ownership_runs VALUES (?,?,?,?,?,?)",
                       (run_id, request_key, source_id, "BEL", result["created_at"], json.dumps(result)))
        return result, True

    def get(self, run_id):
        with self.store.connect() as db:
            row = db.execute("SELECT result FROM ownership_runs WHERE id=?", (str(run_id),)).fetchone()
        if not row:
            raise KeyError(run_id)
        return json.loads(row["result"])

    def recent(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT result FROM ownership_runs ORDER BY created_at DESC LIMIT 20").fetchall()
        return [json.loads(row["result"]) for row in rows]

    def read_report(self, run_id, kind):
        if kind not in ("shareholding", "institutional-flow"):
            raise KeyError(kind)
        result = self.get(run_id)
        return self.vault.read(result["reports"][kind]["path"])
