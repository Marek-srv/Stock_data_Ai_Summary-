import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from graph_stock.app import create_app
from graph_stock.financial_reasoning import validate_interpretation
from graph_stock.financials import (
    FinancialError, calculate_metrics, extract_page_texts, growth_metric,
    parse_amount, ratio_metric,
)

HEADERS = {"X-Graph-Stock": "local-research"}
SOURCE = {
    "id": "a" * 64, "symbol": "BEL", "title": "Golden annual report",
    "sha256": "b" * 64, "origin": "fixture", "retrieved_at": "2025-08-05T00:00:00+00:00",
}
PAGES = {
    "balance_sheet": (188, """Consolidated Balance Sheet (` in Lakhs)
        TOTAL ASSETS 40,83,186 39,52,668
        Total equity 19,99,283 16,34,439
        Borrowings 18 - -
        Current liabilities Borrowings 18 - -"""),
    "profit_loss": (189, """Consolidated Statement of Profit and Loss (` in Lakhs)
        Revenue from operations 23 23,76,875 20,26,824
        Other income 24 74,236 67,014
        Finance costs 27 968 714
        Profit before exceptional items, share of net profit of associate accounted under equity method & tax (III - IV) 7,09,900 5,26,621
        Profit for the year (IX+X) 5,32,268 3,98,524"""),
    "cash_flow": (191, """Consolidated Statement of Cash Flows (` in Lakhs)
        Net Cash from / (used in) Operating Activities 58,662 4,65,949
        Purchase of property, plant and equipment and other intangible assets (1,01,128) (65,253)"""),
}


def golden_facts(source=SOURCE, content=b""):
    return extract_page_texts(source, PAGES)


def wait(client, run_id):
    for _ in range(100):
        result = client.get(f"/api/v1/financials/{run_id}").json()
        if result["status"] not in ("queued", "running"):
            return result
        time.sleep(.01)
    pytest.fail("Financial extraction did not finish")


def test_golden_extraction_scaling_locators_and_metrics():
    facts = golden_facts()
    assert len(facts) == 22
    revenue = next(item for item in facts if item["key"] == "revenue" and item["period"] == "FY2025")
    assert revenue["value"] == "23768.75" and revenue["reported_value"] == "23,76,875"
    assert revenue["reported_unit"] == "INR lakh" and revenue["unit"] == "INR crore"
    assert revenue["scope"] == "consolidated" and revenue["period_end"] == "2025-03-31"
    assert revenue["locator"] == {"pdf_page": 189, "statement": "profit_loss", "row": "Revenue from operations"}
    metrics = {item["id"]: item for item in calculate_metrics(facts)}
    assert metrics["metric:revenue-growth"]["value"] == "17.27"
    assert metrics["metric:operating-margin"]["value"] == "26.78"
    assert metrics["metric:net-profit-margin"]["value"] == "22.39"
    assert metrics["metric:cash-conversion"]["value"] == "11.02"
    assert metrics["metric:free-cash-flow"]["value"] == "-424.66"
    assert metrics["metric:debt-to-equity"]["value"] is None
    assert metrics["metric:debt-to-equity"]["reason"] == "missing-input"
    prior_cash = next(item for item in facts if item["key"] == "cash_from_operations" and item["period"] == "FY2024")
    assert prior_cash["restated"] is True and "regrouped" in prior_cash["restatement_note"]
    assert set(metrics["metric:revenue-growth"]["input_fact_ids"]) == {
        next(f["id"] for f in facts if f["key"] == "revenue" and f["period"] == "FY2025"),
        next(f["id"] for f in facts if f["key"] == "revenue" and f["period"] == "FY2024"),
    }


def test_null_negative_zero_period_scope_and_restatement_are_visible():
    assert parse_amount("-") == (None, "reported-dash")
    assert parse_amount("(1,01,128)") == ("-1011.28", None)
    assert parse_amount("1,011.28", "INR crore") == ("1011.28", None)
    current, prior = golden_facts()[:2]
    zero = {**prior, "value": "0.00"}
    assert growth_metric("g", "Growth", current, zero)["reason"] == "zero-denominator"
    wrong_scope = {**prior, "scope": "standalone", "period_end": current["period_end"]}
    assert ratio_metric("r", "Ratio", current, wrong_scope, formula="a / b")["reason"] == "incompatible-account-scope"
    wrong_period = {**prior, "period_end": "2024-03-31"}
    assert ratio_metric("r", "Ratio", current, wrong_period, formula="a / b")["reason"] == "incompatible-periods"
    facts = golden_facts()
    next(f for f in facts if f["key"] == "revenue" and f["period"] == "FY2024")["restated"] = True
    growth = next(m for m in calculate_metrics(facts) if m["id"] == "metric:revenue-growth")
    assert growth["input_restated"] is True


def test_interpretation_rejects_numbers_unknown_metrics_and_extra_fields():
    facts = golden_facts()
    snapshot = {"facts": facts, "metrics": calculate_metrics(facts)}
    metric = next(item for item in snapshot["metrics"] if item["availability"] == "available")
    evidence = metric["evidence_ids"][0]
    good = {"summary": "Revenue expanded while cash conversion weakened.", "observations": [
        {"text": "Reported growth is positive.", "metric_ids": [metric["id"]], "evidence_ids": [evidence]}],
        "limitations": ["Coverage is limited to the located annual statements."]}
    assert validate_interpretation(good, snapshot)["summary"] == good["summary"]
    with pytest.raises(ValueError):
        validate_interpretation({**good, "summary": "Revenue grew 17 percent."}, snapshot)
    bad_reference = json.loads(json.dumps(good))
    bad_reference["observations"][0]["metric_ids"] = ["metric:invented"]
    with pytest.raises(ValueError):
        validate_interpretation(bad_reference, snapshot)
    with pytest.raises(Exception):
        validate_interpretation({**good, "claim": "extra"}, snapshot)


class NoCreditAnalyst:
    def __init__(self):
        self.calls = 0

    def run(self, snapshot):
        self.calls += 1
        raise AssertionError("Default deterministic requests must not invoke reasoning")


def test_api_persists_traceable_snapshot_without_using_reasoning(tmp_path):
    analyst = NoCreditAnalyst()
    app = create_app(tmp_path, vault_dir=tmp_path / "vault", financial_extractor=golden_facts,
                     financial_analyst=analyst)
    with TestClient(app, base_url="http://localhost") as client:
        with app.state.store.connect() as db:
            db.execute("INSERT INTO filing_sources VALUES (?,?,?,?,?)",
                       (SOURCE["id"], "BEL", SOURCE["sha256"], json.dumps(SOURCE), b"fixture"))
        key = str(uuid.uuid4())
        submitted = client.post("/api/v1/financials", headers=HEADERS,
                                json={"source_id": SOURCE["id"], "request_key": key}).json()
        completed = wait(client, submitted["id"])
        assert completed["status"] == "completed" and completed["snapshot"]["scope"] == "consolidated"
        assert completed["interpretation"]["status"] == "skipped" and analyst.calls == 0
        assert completed["note"]["available"] is True
        note = client.get(f"/api/v1/financials/{completed['id']}/note")
        assert note.status_code == 200 and "PDF p. 189" in note.text and "17.27 %" in note.text
        duplicate = client.post("/api/v1/financials", headers=HEADERS,
                                json={"source_id": SOURCE["id"], "request_key": key}).json()
        assert duplicate["id"] == completed["id"]
        conflict = client.post("/api/v1/financials", headers=HEADERS,
                               json={"source_id": SOURCE["id"], "request_key": key, "use_reasoning": True})
        assert conflict.status_code == 409


def test_unsupported_layout_is_explicit(tmp_path):
    def unsupported(source, content):
        raise FinancialError("unsupported", "Consolidated statement pages were not located.")

    app = create_app(tmp_path, vault_dir=tmp_path / "vault", financial_extractor=unsupported,
                     financial_analyst=NoCreditAnalyst())
    with TestClient(app, base_url="http://localhost") as client:
        with app.state.store.connect() as db:
            db.execute("INSERT INTO filing_sources VALUES (?,?,?,?,?)",
                       (SOURCE["id"], "BEL", SOURCE["sha256"], json.dumps(SOURCE), b"fixture"))
        response = client.post("/api/v1/financials", headers=HEADERS,
                               json={"source_id": SOURCE["id"], "request_key": str(uuid.uuid4())}).json()
        result = wait(client, response["id"])
        assert result["status"] == "unsupported"
        assert "not located" in result["message"]
