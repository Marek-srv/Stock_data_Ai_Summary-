import copy
import uuid

import pytest
from fastapi.testclient import TestClient

from graph_stock.app import create_app
from graph_stock.backtest import simulate_daily_trend
from graph_stock.market_data import normalize_market_bundle
from test_market_data import bundle

HEADERS = {"X-Graph-Stock": "local-research"}


def bar(session, open_, high, low, close, *, status="regular", volume=1000):
    return {"session": session, "open": str(open_), "high": str(high), "low": str(low),
            "close": str(close), "volume": volume, "status": status, "series": "EQ",
            "source_id": "source:fixture"}


def backtest_market(rows, *, expected=None, actions=None):
    value = bundle()
    value["bars"] = rows
    value["expected_sessions"] = expected or [row["session"] for row in rows]
    value["actions"] = actions or []
    value["benchmark"]["bars"] = [
        {**bar(row["session"], 100 + index, 101 + index, 99 + index, 100 + index),
         "volume": None, "series": "INDEX"}
        for index, row in enumerate(rows) if row["status"] != "suspended"
    ]
    value["source"]["coverage"] = "hand-worked backtest sessions"
    result = normalize_market_bundle(value)
    result["id"] = "market-fixture"
    return result


def config(**changes):
    return {"family": "trend-following", "lookback_sessions": 1, "initial_cash": "1000",
            "allocation_percent": "100", "stop_loss_percent": "10", "target_percent": "20",
            "commission_bps": "100", "slippage_bps": "0", "cost_effective_from": "2025-01-01",
            "cost_source": "Hand-worked fixture assumption", **changes}


def test_independent_golden_cash_ledger_and_next_session_timing():
    market = backtest_market([
        bar("2025-01-02", 100, 102, 99, 100),
        bar("2025-01-03", 105, 112, 104, 110),
        bar("2025-01-06", 120, 125, 115, 122),
        bar("2025-01-07", 109, 112, 100, 105),
    ])
    result = simulate_daily_trend("BEL", market, config())

    # Independent arithmetic: buy 8 @ 120 + 1% cost = 969.60; sell at stop 108
    # less 1% cost = 855.36. Cash ends at 30.40 + 855.36 = 885.76.
    assert [(item["type"], item.get("side"), item["session"]) for item in result["ledger"]] == [
        ("signal", "buy", "2025-01-03"), ("fill", "buy", "2025-01-06"),
        ("fill", "sell", "2025-01-07")]
    trade = result["trades"][0]
    assert (trade["quantity"], trade["entry_price"], trade["exit_price"], trade["net_pnl"]) == ("8", "120", "108", "-114.24")
    assert trade["exit_reason"] == "stop-touch"
    assert result["metrics"]["ending_equity"] == "885.76"
    assert result["metrics"]["total_return_percent"] == "-11.424"
    assert result["metrics"]["trade_count"] == 1
    assert result["metrics"]["exposure_percent"] == "50"
    assert result["benchmark"]["return_percent"] == "3"


def test_gap_and_simultaneous_stop_target_use_documented_conservative_prices():
    prefix = [bar("2025-01-02", 100, 102, 99, 100), bar("2025-01-03", 105, 112, 104, 110),
              bar("2025-01-06", 120, 125, 115, 122)]
    gap = simulate_daily_trend("BEL", backtest_market(prefix + [bar("2025-01-07", 100, 105, 95, 101)]),
                               config(commission_bps="0"))
    assert gap["trades"][0]["exit_reason"] == "stop-gap-open"
    assert gap["trades"][0]["exit_price"] == "100"

    ambiguous = simulate_daily_trend("BEL", backtest_market(prefix + [bar("2025-01-07", 120, 150, 100, 125)]),
                                     config(commission_bps="0"))
    assert ambiguous["trades"][0]["exit_reason"] == "stop-before-target-conservative"
    assert ambiguous["trades"][0]["exit_price"] == "108"
    assert ambiguous["trades"][0]["ambiguity"] is True


@pytest.mark.parametrize(("last_row", "reason"), [
    (None, "missing-bar"),
    (bar("2025-01-06", 110, 110, 110, 110, status="suspended", volume=0), "suspended-or-unusable-bar"),
])
def test_order_due_on_missing_or_suspended_session_is_cancelled(last_row, reason):
    rows = [bar("2025-01-02", 100, 102, 99, 100), bar("2025-01-03", 105, 112, 104, 110)]
    if last_row:
        rows.append(last_row)
    market = backtest_market(rows, expected=["2025-01-02", "2025-01-03", "2025-01-06"])
    result = simulate_daily_trend("BEL", market, config())
    cancelled = next(item for item in result["ledger"] if item["type"] == "order-cancelled")
    assert cancelled["reason"] == reason
    assert result["trades"] == [] and result["ending_position"]["quantity"] == "0"


def test_split_changes_position_and_dividend_credits_cash_without_false_stop():
    split = {"action_id": "BEL:split:2025-01-07", "type": "split", "ex_date": "2025-01-07",
             "record_date": "2025-01-06", "terms": {"old_shares": "1", "new_shares": "2"},
             "source_id": "source:fixture"}
    dividend = {"action_id": "BEL:dividend:2025-01-08", "type": "dividend", "ex_date": "2025-01-08",
                "record_date": "2025-01-09", "terms": {"cash_per_share": "2"},
                "source_id": "source:fixture"}
    market = backtest_market([
        bar("2025-01-02", 100, 102, 99, 100), bar("2025-01-03", 105, 112, 104, 110),
        bar("2025-01-06", 110, 115, 105, 112), bar("2025-01-07", 56, 60, 55, 58),
        bar("2025-01-08", 56, 60, 55, 57),
    ], actions=[split, dividend])
    result = simulate_daily_trend("BEL", market, config(commission_bps="0", stop_loss_percent="20", target_percent="50"))
    actions = [item for item in result["ledger"] if item["type"] == "corporate-action"]
    assert [(item["action_type"], item["quantity"]) for item in actions] == [("split", "18"), ("dividend", "18")]
    assert actions[1]["cash_credit"] == "36"
    assert result["ending_position"]["quantity"] == "18"
    assert result["metrics"]["ending_equity"] == "1072"
    assert result["benchmark"]["return_percent"] is None
    assert "total-return-series-is-unavailable" in result["benchmark"]["reason"]


def test_backtest_api_is_idempotent_and_publishes_detailed_report(tmp_path):
    value = bundle()
    value["bars"] = [
        bar("2025-01-02", 100, 102, 99, 100), bar("2025-01-03", 101, 104, 100, 103),
        bar("2025-01-06", 103, 107, 102, 106), bar("2025-01-07", 106, 110, 105, 109),
        bar("2025-01-08", 110, 114, 108, 112),
    ]
    value["expected_sessions"] = [item["session"] for item in value["bars"]]
    value["benchmark"]["bars"] = [{**item, "volume": None, "series": "INDEX"} for item in value["bars"]]
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        market = client.post("/api/v1/market-data/import", headers=HEADERS, json={
            "symbol": "BEL", "request_key": str(uuid.uuid4()), "bundle": copy.deepcopy(value)}).json()
        key = str(uuid.uuid4())
        response = client.post("/api/v1/backtests", headers=HEADERS, json={
            "symbol": "BEL", "market_run_id": market["id"], "request_key": key})
        assert response.status_code == 201
        result = response.json()
        assert result["strategy"]["family"] == "trend-following"
        assert result["data_manifest"]["market_run_id"] == market["id"]
        assert result["strategy"]["parameter_search_history"] == []
        assert result["ending_position"]["quantity"] != "0"
        assert result["metrics"]["profit_factor"] is None
        assert result["metrics"]["profit_factor_reason"] == "undefined-without-losing-trades"
        report = client.get(f"/api/v1/backtests/{result['id']}/report")
        assert report.status_code == 200 and "Cash and position ledger" in report.text and "Engine and license" in report.text
        repeated = client.post("/api/v1/backtests", headers=HEADERS, json={
            "symbol": "BEL", "market_run_id": market["id"], "request_key": key}).json()
        assert repeated["id"] == result["id"]
