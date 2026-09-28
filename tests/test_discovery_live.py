import json
import uuid
from datetime import date, timedelta

from graph_stock.discovery import DiscoveryService, NseDirectoryUniverse
from graph_stock.filings import Download, FilingError
from graph_stock.research import ResearchService
from graph_stock.store import Store


CSV = ("SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
       "BEL,Bharat Electronics Limited,EQ,01-Jan-2000,1,1,INE263A01024,1\n"
       "HAL,Hindustan Aeronautics Limited,EQ,28-Mar-2018,5,1,INE066F01020,5\n").encode()


class Fetch:
    def __init__(self): self.calls = 0
    def __call__(self, url):
        self.calls += 1
        return Download(CSV, url, "2026-09-11T06:00:00+00:00")


def test_official_directory_is_dated_cached_and_counts_unassessed_securities(tmp_path):
    store = Store(tmp_path / "state.sqlite3"); fetch = Fetch()
    provider = NseDirectoryUniverse(store, fetch, lambda: "2026-09-11T07:00:00+00:00")
    first, second = provider(), provider()
    assert first == second and fetch.calls == 1
    assert first["source_kind"] == "validated-public"
    assert first["security_count"] == 2 and first["assessed_security_count"] == 0
    assert first["unassessed_security_count"] == 2 and first["securities"] == []
    assert first["source_sha256"] and first["version"].startswith("nse-equity-directory/2026-09-11/")


def test_saved_real_evidence_builds_a_candidate_without_treating_absent_companies_as_zero(tmp_path):
    store = Store(tmp_path / "state.sqlite3"); fetch = Fetch()
    provider = NseDirectoryUniverse(store, fetch, lambda: "2026-09-11T07:00:00+00:00")
    provider()  # Save the dated directory before adding local evidence.
    financial = {
        "metric:revenue-growth": {"availability": "available", "value": "17.27", "unit": "%", "period_end": "2025-03-31", "evidence_ids": ["evidence:revenue"]},
        "metric:operating-margin": {"availability": "available", "value": "26.78", "unit": "%", "period_end": "2025-03-31", "evidence_ids": ["evidence:margin"]},
    }
    ownership = {"comparison": {"comparable": True, "current_period": "2025-03-31", "comparisons": [
        {"kind": "fii", "percentage_point_change": "0.10"},
        {"kind": "dii", "percentage_point_change": "0.25"},
    ]}}
    sessions = [(date(2026, 1, 1) + timedelta(days=index)).isoformat() for index in range(64)]
    bars = [{"session": session, "adjusted_close": "112" if index == 63 else "100"} for index, session in enumerate(sessions)]
    benchmark = [{"session": session, "close": "108" if index == 63 else "100"} for index, session in enumerate(sessions)]
    market = {"source": {"provider": "National Stock Exchange of India", "url": "https://www.nseindia.com/api/example"},
              "adjusted_bars": bars, "benchmark": {"bars": benchmark}}
    with store.connect() as db:
        db.executescript("""
            CREATE TABLE filing_sources(id TEXT PRIMARY KEY,symbol TEXT);
            CREATE TABLE financial_jobs(id TEXT PRIMARY KEY,source_id TEXT,status TEXT,created_at TEXT);
            CREATE TABLE financial_metrics(run_id TEXT,id TEXT,payload TEXT);
            CREATE TABLE ownership_runs(id TEXT,symbol TEXT,created_at TEXT,result TEXT);
            CREATE TABLE market_runs(id TEXT,symbol TEXT,created_at TEXT,result TEXT);
        """)
        db.execute("INSERT INTO filing_sources VALUES ('source-1','BEL')")
        db.execute("INSERT INTO financial_jobs VALUES ('financial-1','source-1','completed','2026-09-11T01:00:00Z')")
        for metric_id, payload in financial.items():
            db.execute("INSERT INTO financial_metrics VALUES (?,?,?)", ("financial-1", metric_id, json.dumps(payload)))
        db.execute("INSERT INTO ownership_runs VALUES ('ownership-1','BEL','2026-09-11T02:00:00Z',?)", (json.dumps(ownership),))
        db.execute("INSERT INTO market_runs VALUES ('market-1','BEL','2026-09-11T03:00:00Z',?)", (json.dumps(market),))
    research = ResearchService(store, tmp_path / "vault")
    discovery = DiscoveryService(store, tmp_path / "vault", research, provider)
    run, created = discovery.screen(str(uuid.uuid4()))
    assert created and run["universe"]["security_count"] == 2
    assert run["universe"]["assessed_security_count"] == 1 and run["universe"]["unassessed_security_count"] == 1
    assert [(item["symbol"], item["rank"]) for item in run["candidates"]] == [("BEL", 1)]
    assert all(metric["source_id"].split(":")[0] in {"financial", "ownership", "market"} for metric in run["candidates"][0]["metrics"])
    assert "Official NSE equity directory" in discovery.read_report(run["id"])
    queued = discovery.queue(run["id"], "NSE:BEL", str(uuid.uuid4()))
    assert queued["created"] and queued["research"]["snapshot"]["security"]["security_id"] == "NSE:BEL"


def test_stale_validated_directory_is_explicit_when_refresh_is_unavailable(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    with store.connect() as db:
        db.execute("""CREATE TABLE filing_directory (
            id INTEGER PRIMARY KEY CHECK(id=1),content BLOB,url TEXT,retrieved_at TEXT)""")
        db.execute("INSERT INTO filing_directory VALUES (1,?,?,?)",
                   (CSV, "https://archives.nseindia.com/content/equities/EQUITY_L.csv", "2026-09-10T06:00:00+00:00"))
    def unavailable(url): raise FilingError("unavailable", "offline")
    universe = NseDirectoryUniverse(store, unavailable, lambda: "2026-09-11T07:00:00+00:00")()
    assert universe["source_kind"] == "validated-public-stale"
    assert universe["as_of_date"] == "2026-09-10" and universe["security_count"] == 2
