import copy
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from graph_stock.app import create_app
from test_backtest import bar
from test_market_data import bundle

HEADERS = {"X-Graph-Stock": "local-research"}


def market_bundle(rows, marker, actions=None):
    value = bundle()
    value["bars"] = rows
    value["expected_sessions"] = [item["session"] for item in rows]
    value["actions"] = actions or []
    value["benchmark"]["bars"] = [{**item, "volume": None, "series": "INDEX"} for item in rows]
    value["source"].update({"source_id": f"source:paper-{marker}", "content_sha256": marker * 64,
                            "available_at": rows[-1]["session"] + "T18:00:00+05:30",
                            "coverage": f"paper fixture through {rows[-1]['session']}"})
    return value


def import_market(client, rows, marker, actions=None):
    response = client.post("/api/v1/market-data/import", headers=HEADERS, json={
        "symbol": "BEL", "request_key": str(uuid.uuid4()),
        "bundle": copy.deepcopy(market_bundle(rows, marker, actions))})
    assert response.status_code == 201, response.text
    return response.json()


def insert_validation(app, market_id, *, eligible=True, config=None):
    validation_id = str(uuid.uuid4())
    selected = config or {"family": "trend-following", "lookback_sessions": 2, "initial_cash": "100000",
                          "allocation_percent": "100", "stop_loss_percent": "20", "target_percent": "50",
                          "commission_bps": "10", "slippage_bps": "5", "cost_effective_from": "2000-01-01",
                          "cost_source": "paper golden fixture"}
    result = {"id": validation_id, "symbol": "BEL",
              "promotion": {"paper_eligible": eligible, "status": "passed" if eligible else "rejected"},
              "search": {"selected_candidate_version": "trend-following/frozen-paper-fixture", "selected_config": selected},
              "validation_manifest": {"hash": "e" * 64, "market_run_id": market_id},
              "windows": {"untouched_oos": {"end": "2025-01-06"}}}
    with app.state.store.connect() as db:
        db.execute("INSERT INTO validation_runs VALUES (?,?,?,?,?,?,?)", (
            validation_id, str(uuid.uuid4()), "fingerprint", "BEL", market_id,
            "2025-01-06T18:00:00+05:30", json.dumps(result)))
    return validation_id


BASE = [bar("2025-01-02", 100, 102, 99, 100), bar("2025-01-03", 104, 107, 103, 105),
        bar("2025-01-06", 108, 112, 107, 110)]
DAY4 = bar("2025-01-07", 112, 122, 111, 120)
DAY5 = bar("2025-01-08", 121, 125, 118, 123)


def activate(client, validation_id):
    response = client.post("/api/v1/paper-books", headers=HEADERS, json={
        "symbol": "BEL", "validation_id": validation_id, "request_key": str(uuid.uuid4())})
    assert response.status_code == 201, response.text
    return response.json()


def process(client, book_id, market_id, key=None):
    return client.post(f"/api/v1/paper-books/{book_id}/process", headers=HEADERS, json={
        "market_run_id": market_id, "request_key": key or str(uuid.uuid4())})


def test_only_all_gate_passed_frozen_validation_can_activate(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        market = import_market(client, BASE, "a")
        validation_id = insert_validation(app, market["id"], eligible=False)
        response = client.post("/api/v1/paper-books", headers=HEADERS, json={
            "symbol": "BEL", "validation_id": validation_id, "request_key": str(uuid.uuid4())})
        assert response.status_code == 422
        assert "passed every validation gate" in response.json()["detail"]


def test_multisession_book_restarts_reconciled_and_deduplicates_fills_and_actions(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        baseline = import_market(client, BASE, "a")
        validation_id = insert_validation(app, baseline["id"])
        book = activate(client, validation_id)
        day4 = import_market(client, BASE + [DAY4], "b")
        first = process(client, book["id"], day4["id"]).json()
        assert first["state"]["pending_order"]["side"] == "buy"
        assert [e["payload"]["signal"] for e in first["events"] if e["kind"] == "decision"] == ["ENTRY"]

        day5 = import_market(client, BASE + [DAY4, DAY5], "c")
        filled = process(client, book["id"], day5["id"]).json()
        buys = [e for e in filled["events"] if e["kind"] == "fill" and e["payload"]["side"] == "buy"]
        assert len(buys) == 1 and DecimalString(buys[0]["payload"]["cash_after"]) < 100000
        duplicate = process(client, book["id"], day5["id"]).json()
        assert len([e for e in duplicate["events"] if e["kind"] == "fill"]) == 1
        assert duplicate["process"]["processed_sessions"] == 0

    # Opening the same state directory performs ledger/state reconciliation before serving the book.
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        reopened = client.get(f"/api/v1/paper-books/{book['id']}").json()
        assert reopened["state"]["reconciliation"]["status"] == "matched"
        initial_quantity = DecimalString(reopened["state"]["quantity"])
        split = {"action_id": "BEL:split:2025-01-09", "type": "split", "ex_date": "2025-01-09",
                 "record_date": "2025-01-09", "terms": {"old_shares": "1", "new_shares": "2"}, "source_id": "source:paper-d"}
        day6row = bar("2025-01-09", 62, 66, 60, 64)
        day6 = import_market(client, BASE + [DAY4, DAY5, day6row], "d", [split])
        split_result = process(client, book["id"], day6["id"]).json()
        assert DecimalString(split_result["state"]["quantity"]) == initial_quantity * 2

        dividend = {"action_id": "BEL:dividend:2025-01-10", "type": "dividend", "ex_date": "2025-01-10",
                    "record_date": "2025-01-10", "terms": {"cash_per_share": "2"}, "source_id": "source:paper-e"}
        day7row = bar("2025-01-10", 62, 66, 61, 63)
        day7 = import_market(client, BASE + [DAY4, DAY5, day6row, day7row], "e", [split, dividend])
        before_cash = DecimalString(split_result["state"]["cash"])
        paid = process(client, book["id"], day7["id"]).json()
        assert DecimalString(paid["state"]["cash"]) == before_cash + initial_quantity * 2 * 2
        assert len([e for e in paid["events"] if e["kind"] == "corporate-action"]) == 2
        assert client.get(f"/api/v1/paper-books/{book['id']}/report").status_code == 200


def DecimalString(value):
    from decimal import Decimal
    return Decimal(str(value))


def test_session_transaction_rolls_back_on_crash_and_insufficient_cash_never_fills(tmp_path):
    expensive_config = {"family": "trend-following", "lookback_sessions": 2, "initial_cash": "100000",
                        "allocation_percent": "100", "stop_loss_percent": "20", "target_percent": "50",
                        "commission_bps": "10", "slippage_bps": "5", "cost_effective_from": "2000-01-01",
                        "cost_source": "paper golden fixture"}
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        baseline = import_market(client, BASE, "a")
        validation_id = insert_validation(app, baseline["id"], config=expensive_config)
        book = activate(client, validation_id)
        day4 = import_market(client, BASE + [DAY4], "b")
        process(client, book["id"], day4["id"])
        expensive = bar("2025-01-08", 200000, 201000, 199000, 200000)
        day5 = import_market(client, BASE + [DAY4, expensive], "c")

        with pytest.raises(RuntimeError, match="injected-paper-session-crash"):
            app.state.paper.process(book["id"], day5["id"], str(uuid.uuid4()), fail_after_events=1)
        after_crash = app.state.paper.get(book["id"])
        assert after_crash["state"]["last_session"] == "2025-01-07"
        assert not any(e["session"] == "2025-01-08" for e in after_crash["events"])

        retried = process(client, book["id"], day5["id"]).json()
        assert retried["state"]["quantity"] == "0"
        rejected = [e for e in retried["events"] if e["kind"] == "pending-order" and e["payload"].get("status") == "rejected"]
        assert len(rejected) == 1 and rejected[0]["payload"]["reason"] == "insufficient-cash"


def test_missing_price_cancels_fill_and_uncertain_action_pauses_book(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        baseline = import_market(client, BASE, "a")
        validation_id = insert_validation(app, baseline["id"])
        book = activate(client, validation_id)
        day4 = import_market(client, BASE + [DAY4], "b")
        process(client, book["id"], day4["id"])
        missing_bundle = market_bundle(BASE + [DAY4], "c")
        missing_bundle["expected_sessions"].append("2025-01-08")
        missing = client.post("/api/v1/market-data/import", headers=HEADERS, json={
            "symbol": "BEL", "request_key": str(uuid.uuid4()), "bundle": missing_bundle}).json()
        result = process(client, book["id"], missing["id"]).json()
        assert result["state"]["pending_order"] is None and result["state"]["quantity"] == "0"
        assert any(e["kind"] == "mark" and e["payload"]["status"] == "unavailable" for e in result["events"])

        # A separate active book reaches an incomplete merger before its pending entry can fill.
        book2 = activate(client, validation_id)
        process(client, book2["id"], day4["id"])
        merger = {"action_id": "BEL:merger:2025-01-08", "type": "merger", "ex_date": "2025-01-08",
                  "record_date": None, "terms": {}, "source_id": "source:paper-d"}
        affected = import_market(client, BASE + [DAY4, DAY5], "d", [merger])
        paused = process(client, book2["id"], affected["id"]).json()
        assert paused["state"]["status"] == "paused" and paused["state"]["quantity"] == "0"
        assert paused["state"]["pending_order"] is not None
        assert any(e["kind"] == "pause" for e in paused["events"])
