import copy
import uuid

from fastapi.testclient import TestClient

from graph_stock.app import create_app
from graph_stock.ownership import bel_disclosures, compare_periods
from test_filings import Provider


def disclosures():
    source = {"id": "a" * 64, "symbol": "BEL", "title": "BEL Integrated Annual Report 2024-25",
              "origin": "https://bel-india.in/report.pdf", "public_available_at": "2025-08-06T00:00:00+00:00",
              "retrieved_at": "2025-08-07T00:00:00+00:00"}
    return bel_disclosures(source)


def test_two_period_golden_aggregate_and_scheme_comparison():
    result = compare_periods(*disclosures())
    rows = {row["holder_id"]: row for row in result["comparisons"]}
    assert result["comparable"] is True
    assert rows["aggregate:promoter"]["status"] == "unchanged"
    assert rows["aggregate:dii"]["share_change"] == -128_928_933
    assert rows["scheme:hdfc-pension-e-tier1"]["status"] == "accumulation"
    assert rows["scheme:canara-robeco-emerging-equities"]["status"] == "reduction"
    assert rows["scheme:kotak-flexicap"]["status"] == "unknown"


def test_missing_report_ambiguous_identity_and_corporate_action_are_unknown():
    prior, current = disclosures()
    ambiguous = copy.deepcopy(current)
    ambiguous["holdings"][3]["identity"] = "ambiguous"
    rows = {r["holder_id"]: r for r in compare_periods(prior, ambiguous)["comparisons"]}
    assert rows["scheme:hdfc-pension-e-tier1"]["reason"] == "holder-identity-ambiguous"
    renamed = copy.deepcopy(current)
    renamed["holdings"][3]["name"] = "HDFC Pension Scheme E Tier 1 (renamed display)"
    rows = {r["holder_id"]: r for r in compare_periods(prior, renamed)["comparisons"]}
    assert rows["scheme:hdfc-pension-e-tier1"]["status"] == "accumulation"
    action = copy.deepcopy(current)
    action["denominator_shares"] *= 2
    compared = compare_periods(prior, action)
    assert compared["comparable"] is False
    assert {r["status"] for r in compared["comparisons"]} == {"unknown"}
    absent = copy.deepcopy(current)
    absent["coverage"]["named_holders"] = "missing"
    absent["holdings"] = absent["holdings"][:3]
    rows = {r["holder_id"]: r for r in compare_periods(prior, absent)["comparisons"]}
    assert rows["scheme:hdfc-pension-e-tier1"]["status"] == "unknown"


def test_service_api_persists_sources_and_linked_reports(tmp_path):
    with TestClient(create_app(tmp_path, filing_fetch=Provider()), base_url="http://localhost") as client:
        filing = client.post("/api/v1/filings", headers={"X-Graph-Stock": "local-research"},
                             json={"symbol": "BEL", "request_key": str(uuid.uuid4())}).json()
        import time
        for _ in range(100):
            filing = client.get(f"/api/v1/filings/{filing['id']}").json()
            if filing["status"] not in ("queued", "running"):
                break
            time.sleep(.01)
        source_id = filing["source"]["id"]
        key = str(uuid.uuid4())
        response = client.post("/api/v1/ownership", headers={"X-Graph-Stock": "local-research"},
                               json={"source_id": source_id, "request_key": key})
        assert response.status_code == 201
        result = response.json()
        assert result["sources"][0]["coverage"]["named_holders"] == "partial"
        assert result["sources"][1]["published_at"]
        for kind in ("shareholding", "institutional-flow"):
            report = client.get(f"/api/v1/ownership/{result['id']}/reports/{kind}")
            assert report.status_code == 200 and "Periodic ownership changes" in report.text
        repeat = client.post("/api/v1/ownership", headers={"X-Graph-Stock": "local-research"},
                             json={"source_id": source_id, "request_key": key}).json()
        assert repeat["id"] == result["id"]
        with client.app.state.store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM ownership_sources").fetchone()[0] == 2
            assert db.execute("SELECT COUNT(*) FROM ownership_holdings").fetchone()[0] == 11
