import csv
import io
import json
import uuid
import zipfile
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from graph_stock.app import create_app
from graph_stock.bulk_market import BulkMarketError, BulkMarketService, parse_bhavcopy, parse_index_close
from graph_stock.market_data import MarketDataService
from graph_stock.store import Store


HEADERS = {"X-Graph-Stock": "local-research"}


def archive(session, rows):
    name = f"BhavCopy_NSE_CM_0_0_0_{session.replace('-', '')}_F_0000.csv"
    fields = ["TradDt", "Sgmt", "Src", "FinInstrmTp", "ISIN", "TckrSymb", "SctySrs",
              "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol"]
    csv_file = io.StringIO(); writer = csv.DictWriter(csv_file, fieldnames=fields); writer.writeheader()
    for row in rows: writer.writerow(row)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zipped: zipped.writestr(name, csv_file.getvalue())
    return output.getvalue()


def equity(session, symbol="BEL", isin="INE263A01024", close="110"):
    return {"TradDt": session, "Sgmt": "CM", "Src": "NSE", "FinInstrmTp": "STK", "ISIN": isin,
            "TckrSymb": symbol, "SctySrs": "EQ", "OpnPric": "100", "HghPric": "112",
            "LwPric": "99", "ClsPric": close, "TtlTradgVol": "1000"}


def index_csv(session, close="105"):
    display = datetime.fromisoformat(session).strftime("%d-%m-%Y")
    return ("Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value\n"
            f"Nifty 50,{display},100,106,99,{close}\n").encode()


def test_udiff_zip_and_index_parsers_validate_identity_session_and_shape():
    session = "2026-09-11"
    parsed = parse_bhavcopy(archive(session, [equity(session)]), session)
    assert parsed["BEL"]["close"] == "110" and parsed["BEL"]["volume"] == 1000
    assert parse_index_close(index_csv(session), session)["close"] == "105"
    with pytest.raises(BulkMarketError, match="archive is invalid"):
        parse_bhavcopy(b"not-a-zip", session)
    wrong = equity(session); wrong["TradDt"] = "2026-09-10"
    with pytest.raises(BulkMarketError, match="identity or session"):
        parse_bhavcopy(archive(session, [wrong]), session)


class Provider:
    def __init__(self): self.calls = []
    def __call__(self, day):
        session = day.isoformat(); self.calls.append(session)
        last = len(self.calls) >= 64
        return {"session": session,
                "equities": {"BEL": {"session": session, "symbol": "BEL", "isin": "INE263A01024",
                                       "open": "100", "high": "112", "low": "99", "close": "112" if last else "100",
                                       "volume": 1000, "series": "EQ"}},
                "benchmark": {"session": session, "symbol": "NIFTY 50", "open": "100", "high": "108", "low": "99",
                              "close": "108" if last else "100", "volume": None, "series": "INDEX"},
                "bhavcopy": {"url": f"https://archives.nseindia.com/bhav/{session}", "sha256": session.replace("-", "").ljust(64, "0")},
                "index": {"url": f"https://archives.nseindia.com/index/{session}", "sha256": session.replace("-", "").ljust(64, "1")},
                "retrieved_at": "2026-09-11T18:30:00+05:30"}


def seed_targets(store):
    directory = ("SYMBOL,NAME OF COMPANY,ISIN NUMBER\nBEL,Bharat Electronics Limited,INE263A01024\n").encode()
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO filing_directory VALUES (1,?,?,?)", (directory, "https://archives.nseindia.com/EQUITY_L.csv", "2026-09-11T12:00:00+05:30"))
        db.execute("INSERT INTO filing_sources(id,symbol,hash,metadata,content) VALUES ('source-1','BEL','hash','{}',X'00')")
        db.execute("INSERT INTO financial_jobs(id,request_key,fingerprint,source_id,use_reasoning,status,created_at,updated_at,vault_root) VALUES ('financial-1','key-f','fp','source-1',0,'completed','2026-09-11','2026-09-11','vault')")
        ownership = {"id": "ownership-1", "comparison": {"comparable": True, "comparisons": []}}
        db.execute("INSERT INTO ownership_runs(id,request_key,source_id,symbol,created_at,result) VALUES ('ownership-1','key-o','source-1','BEL','2026-09-11',?)", (json.dumps(ownership),))
        action_source = {"source": {"source_id": "actions-1", "provider": "National Stock Exchange of India",
                                     "coverage": "corporate actions trailing 370 days"}, "actions": []}
        db.execute("INSERT INTO market_runs VALUES ('actions-run','key-m','BEL','complete','2026-09-11',?)", (json.dumps(action_source),))


def test_bulk_history_caches_sessions_and_materializes_existing_evidence_target(tmp_path):
    app = create_app(tmp_path / "state", vault_dir=tmp_path / "vault", bulk_market_provider=Provider())
    with TestClient(app, base_url="http://localhost"):
        seed_targets(app.state.store)
        service = BulkMarketService(app.state.store, app.state.market_data, tmp_path / "vault", app.state.bulk_market.provider,
                                    clock=lambda: datetime(2026, 9, 11, tzinfo=timezone.utc))
        run, created = service.submit(str(uuid.uuid4())); assert created
        service.execute(run["id"])
        complete = service.get(run["id"])
        assert complete["status"] == "completed" and len(complete["sessions"]) == 64
        assert complete["equity_rows"] == 64 and complete["materialized"][0]["symbol"] == "BEL"
        market = app.state.market_data.get(complete["materialized"][0]["market_run_id"])
        assert len(market["adjusted_bars"]) == 64 and len(market["benchmark"]["bars"]) == 64
        assert market["source"]["provider"] == "National Stock Exchange of India"
        first_call_count = len(service.provider.calls)
        second, _ = service.submit(str(uuid.uuid4())); service.execute(second["id"])
        assert len(service.provider.calls) == first_call_count
        assert service.get(second["id"])["materialized"][0]["market_run_id"] == market["id"]


def test_bulk_history_api_is_idempotent_and_forbids_extra_fields(tmp_path):
    app = create_app(tmp_path, bulk_market_provider=Provider())
    with TestClient(app, base_url="http://localhost") as client:
        key = str(uuid.uuid4())
        first = client.post("/api/v1/bulk-market-history", headers=HEADERS, json={"request_key": key})
        repeated = client.post("/api/v1/bulk-market-history", headers=HEADERS, json={"request_key": key})
        invalid = client.post("/api/v1/bulk-market-history", headers=HEADERS, json={"request_key": str(uuid.uuid4()), "sessions": 1})
        assert first.status_code == repeated.status_code == 202
        assert first.json()["id"] == repeated.json()["id"] and invalid.status_code == 422
