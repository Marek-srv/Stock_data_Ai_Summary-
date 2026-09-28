import json
import uuid

import pytest
from fastapi.testclient import TestClient

from graph_stock.app import create_app
from graph_stock.bulk_evidence import (BulkEvidenceError, BulkEvidenceService,
                                       _select_periods, parse_financial_xbrl, parse_ownership_xbrl)


HEADERS = {"X-Graph-Stock": "local-research"}
DIRECTORY = ("SYMBOL,NAME OF COMPANY,ISIN NUMBER\n"
             "BEL,Bharat Electronics Limited,INE263A01024\n"
             "HAL,Hindustan Aeronautics Limited,INE066F01020\n").encode()


def xbrl(symbol="BEL", isin="INE263A01024", period="2026-03-31", *, ownership=False):
    contexts = ["<context id='OneD'><period><startDate>2025-04-01</startDate><endDate>2026-03-31</endDate></period></context>"]
    facts = [f"<f:Symbol contextRef='OneD'>{symbol}</f:Symbol>", f"<f:ISIN contextRef='OneD'>{isin}</f:ISIN>"]
    if ownership:
        contexts = []
        fields = {"ShareholdingOfPromoterAndPromoterGroup_ContextI": (510, "0.51"),
                  "InstitutionsDomestic_ContextI": (200, "0.20"),
                  "InstitutionsForeign_ContextI": (150, "0.15"),
                  "ShareholdingPattern_ContextI": (1000, "1")}
        for context, (shares, percent) in fields.items():
            contexts.append(f"<context id='{context}'><period><instant>{period}</instant></period></context>")
            facts += [f"<f:NumberOfShares contextRef='{context}'>{shares}</f:NumberOfShares>",
                      f"<f:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef='{context}'>{percent}</f:ShareholdingAsAPercentageOfTotalNumberOfShares>"]
        facts += [f"<f:Symbol contextRef='ShareholdingPattern_ContextI'>{symbol}</f:Symbol>",
                  f"<f:ISIN contextRef='ShareholdingPattern_ContextI'>{isin}</f:ISIN>",
                  "<f:WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged contextRef='ShareholdingPattern_ContextI'>false</f:WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged>"]
    else:
        facts += ["<f:RevenueFromOperations contextRef='OneD'>1000000000</f:RevenueFromOperations>",
                  "<f:OtherIncome contextRef='OneD'>50000000</f:OtherIncome>",
                  "<f:FinanceCosts contextRef='OneD'>10000000</f:FinanceCosts>",
                  "<f:ProfitBeforeTax contextRef='OneD'>240000000</f:ProfitBeforeTax>"]
    return ("<xbrl xmlns='http://www.xbrl.org/2003/instance' xmlns:f='urn:test'>" + "".join(contexts + facts) + "</xbrl>").encode()


def test_xbrl_parsers_validate_identity_period_and_calculate_metrics():
    financial = parse_financial_xbrl(xbrl(), "BEL", "INE263A01024", "2026-03-31")
    assert financial["operating_margin_percent"] == "20.0"
    ownership = parse_ownership_xbrl(xbrl(ownership=True), "BEL", "INE263A01024", "2026-03-31")
    assert ownership["dii"]["percent"] == "20.00" and ownership["fii"]["shares"] == 150
    assert ownership["promoter_pledged"] is False
    with pytest.raises(BulkEvidenceError, match="identity"):
        parse_financial_xbrl(xbrl(symbol="HAL"), "BEL", "INE263A01024", "2026-03-31")
    with pytest.raises(BulkEvidenceError, match="unsafe"):
        parse_financial_xbrl(b"<!DOCTYPE x><xbrl/>", "BEL", "INE263A01024", "2026-03-31")


def test_financial_catalog_selects_same_quarter_prior_year():
    rows = [{"type": "Integrated Filing- Financials", "consolidated": "Consolidated", "qe_Date": period,
             "xbrl": f"https://nsearchives.nseindia.com/{period}", "broadcast_Date": period}
            for period in ("30-JUN-2026", "31-MAR-2026", "30-JUN-2025")]
    assert [item["period_end"] for item in _select_periods(rows, financial=True)] == ["2026-06-30", "2025-06-30"]


class Provider:
    def __init__(self): self.calls = []
    def __call__(self, symbol, identity):
        self.calls.append(symbol)
        if symbol == "HAL": raise BulkEvidenceError("Unsupported bank-style layout.", "coverage")
        financial = [
            {"period_end": "2026-03-31", "revenue_rupees": "120", "operating_profit_rupees": "30",
             "operating_margin_percent": "25", "sha256": "a" * 64, "url": "https://nsearchives.nseindia.com/f1", "retrieved_at": "2026-09-28"},
            {"period_end": "2025-03-31", "revenue_rupees": "100", "operating_profit_rupees": "20",
             "operating_margin_percent": "20", "sha256": "b" * 64, "url": "https://nsearchives.nseindia.com/f0", "retrieved_at": "2026-09-28"},
        ]
        ownership = [
            {"period_end": "2026-06-30", "dii": {"percent": "22"}, "fii": {"percent": "18"}, "sha256": "c" * 64, "url": "https://nsearchives.nseindia.com/o1", "retrieved_at": "2026-09-28"},
            {"period_end": "2026-03-31", "dii": {"percent": "20"}, "fii": {"percent": "17"}, "sha256": "d" * 64, "url": "https://nsearchives.nseindia.com/o0", "retrieved_at": "2026-09-28"},
        ]
        return {"symbol": symbol, "name": identity["name"], "isin": identity["isin"],
                "financial_periods": financial, "ownership_periods": ownership,
                "metrics": {"revenue_growth_percent": "20", "operating_margin_percent": "25", "institutional_change_pp": "3"},
                "catalogs": {"financial": {"sha256": "e" * 64}, "ownership": {"sha256": "f" * 64}}}


def seed_directory(store):
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO filing_directory VALUES (1,?,?,?)",
                   (DIRECTORY, "https://archives.nseindia.com/content/equities/EQUITY_L.csv", "2026-09-28T10:00:00+05:30"))


def test_bounded_refresh_persists_complete_evidence_and_explicit_gaps(tmp_path):
    provider = Provider(); app = create_app(tmp_path / "state", vault_dir=tmp_path / "vault", bulk_evidence_provider=provider)
    with TestClient(app, base_url="http://localhost"):
        seed_directory(app.state.store)
        service = BulkEvidenceService(app.state.store, tmp_path / "vault", provider)
        run, created = service.submit(str(uuid.uuid4()), ["BEL", "HAL"]); assert created
        service.execute(run["id"]); result = service.get(run["id"])
        assert result["status"] == "partial" and result["completed"][0]["symbol"] == "BEL"
        assert result["gaps"] == [{"code": "coverage", "reason": "Unsupported bank-style layout.", "symbol": "HAL"}]
        universe = app.state.discovery.provider()
        bel = next(item for item in universe["securities"] if item["symbol"] == "BEL")
        metrics = {item["name"]: item["value"] for item in bel["metrics"]}
        assert metrics["revenue_growth_percent"] == "20" and metrics["institutional_change_pp"] == "3"
        assert "BEL" in service.read_report(run["id"])


def test_bulk_evidence_api_deduplicates_and_rejects_invalid_payload(tmp_path):
    app = create_app(tmp_path, bulk_evidence_provider=Provider())
    with TestClient(app, base_url="http://localhost") as client:
        seed_directory(app.state.store); key = str(uuid.uuid4())
        first = client.post("/api/v1/bulk-evidence", headers=HEADERS, json={"request_key": key, "symbols": ["BEL"]})
        repeated = client.post("/api/v1/bulk-evidence", headers=HEADERS, json={"request_key": key, "symbols": ["BEL"]})
        invalid = client.post("/api/v1/bulk-evidence", headers=HEADERS, json={"request_key": str(uuid.uuid4()), "limit": 100})
        assert first.status_code == repeated.status_code == 202
        assert first.json()["id"] == repeated.json()["id"] and invalid.status_code == 422
