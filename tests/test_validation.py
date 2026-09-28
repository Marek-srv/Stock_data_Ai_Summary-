import copy
import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from graph_stock.app import create_app
from graph_stock.validation import FAMILY_REGISTRY, validate_market
from test_backtest import bar, backtest_market
from test_market_data import bundle

HEADERS = {"X-Graph-Stock": "local-research"}


def forty_session_market():
    rows = []
    for index in range(40):
        day = f"2025-02-{index + 1:02d}" if index < 28 else f"2025-03-{index - 27:02d}"
        price = Decimal(100 + index)
        rows.append(bar(day, price, price + 2, price - 2, price + 1))
    return backtest_market(rows)


def passing_engine_market():
    days, current = [], date(2025, 1, 1)
    while len(days) < 60:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    pattern, rows = [100, 101, 102, 103, 115], []
    for index, day in enumerate(days):
        close = pattern[index % 5]
        opening = 104 if index % 5 == 4 else close
        high = 120 if index % 5 == 4 else max(opening, close) + 1
        rows.append(bar(day, opening, high, min(opening, close) - 1, close))
    return backtest_market(rows)


def fake_simulator(failed_gate=None, calls=None):
    calls = calls if calls is not None else []

    def simulate(symbol, market, config):
        calls.append({"market_id": market["id"], "sessions": list(market["quality"]["expected_sessions"]),
                      "lookback": config["lookback_sessions"]})
        name = market["id"].split(":")[-1]
        value = Decimal(config["lookback_sessions"])
        if name == "cost-stress-oos" and failed_gate == "cost-stress":
            value = Decimal("-1")
        metrics = {"total_return_percent": str(value), "max_drawdown_percent": "10",
                   "trade_count": 2, "excess_return_percent": "1"}
        return {"metrics": metrics}
    return simulate


def test_all_families_registered_and_missing_features_make_family_ineligible():
    result = validate_market("BEL", forty_session_market(), ["market"], simulator=fake_simulator())
    assert set(result["family_registry"]) == set(FAMILY_REGISTRY) == {
        "momentum", "breakout", "pullback", "relative-strength", "volume-expansion",
        "earnings-momentum", "institutional-accumulation", "trend-following"}
    assert result["family_registry"]["trend-following"]["eligible"] is True
    assert result["family_registry"]["earnings-momentum"]["missing_features"] == ["financial"]
    assert result["family_registry"]["relative-strength"]["missing_features"] == ["benchmark"]
    assert all(set(item["config"]) == set(result["search"]["experiments"][0]["config"])
               for item in result["search"]["experiments"])


def test_holdout_is_never_used_for_selection_and_all_bounded_experiments_are_recorded():
    calls = []
    result = validate_market("BEL", forty_session_market(), simulator=fake_simulator(calls=calls))
    experiments = result["search"]["experiments"]
    assert result["search"]["budget"] == result["search"]["used"] == len(experiments) == 6
    assert all(item["holdout_accessed"] is False for item in experiments)
    assert all("untouched-oos" not in call["market_id"] for call in calls[:12])
    assert {name: window["sessions"] for name, window in result["windows"].items()} == {
        "train": 20, "tuning": 10, "untouched_oos": 10}
    assert result["search"]["selected_candidate_version"] in {item["candidate_version"] for item in experiments}
    assert len({item["candidate_version"] for item in experiments}) == 6


def test_passing_fixture_requires_every_gate_and_rule_change_has_new_version():
    passed = validate_market("BEL", passing_engine_market())
    assert passed["promotion"]["status"] == "passed" and passed["promotion"]["paper_eligible"] is True
    assert all(gate["status"] == "pass" for gate in passed["gates"])
    assert passed["oos_result"]["metrics"]["trade_count"] == 5
    assert Decimal(passed["cost_stress_result"]["metrics"]["total_return_percent"]) > 0
    assert passed["promotion"]["invalidated_by_rule_change"] is True
    versions = {item["candidate_version"] for item in passed["search"]["experiments"]}
    assert len(versions) == 6

    failed = validate_market("BEL", forty_session_market(), simulator=fake_simulator("cost-stress"))
    assert failed["promotion"]["status"] == "rejected" and failed["promotion"]["paper_eligible"] is False
    statuses = {item["name"]: item["status"] for item in failed["gates"]}
    assert statuses["cost-stress"] == "fail"
    assert sum(value == "fail" for value in statuses.values()) == 1


def test_short_real_engine_fixture_is_insufficient_and_api_persists_every_experiment(tmp_path):
    value = bundle()
    value["bars"] = [
        bar("2025-01-02", 100, 102, 99, 100), bar("2025-01-03", 101, 104, 100, 103),
        bar("2025-01-06", 103, 107, 102, 106), bar("2025-01-07", 106, 110, 105, 109),
        bar("2025-01-08", 110, 114, 108, 112), bar("2025-01-09", 112, 114, 109, 110),
        bar("2025-01-10", 109, 111, 100, 102),
    ]
    value["expected_sessions"] = [item["session"] for item in value["bars"]]
    value["benchmark"]["bars"] = [{**item, "volume": None, "series": "INDEX"} for item in value["bars"]]
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        market = client.post("/api/v1/market-data/import", headers=HEADERS, json={
            "symbol": "BEL", "request_key": str(uuid.uuid4()), "bundle": copy.deepcopy(value)}).json()
        key = str(uuid.uuid4())
        response = client.post("/api/v1/validations", headers=HEADERS, json={
            "symbol": "BEL", "market_run_id": market["id"], "request_key": key})
        assert response.status_code == 201
        result = response.json()
        assert result["promotion"]["status"] == "insufficient-evidence"
        assert result["promotion"]["paper_eligible"] is False
        assert next(gate for gate in result["gates"] if gate["name"] == "minimum-sample")["status"] == "fail"
        assert len(result["search"]["experiments"]) == 6
        with app.state.store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM validation_experiments WHERE run_id=?", (result["id"],)).fetchone()[0] == 6
        report = client.get(f"/api/v1/validations/{result['id']}/report")
        assert report.status_code == 200 and "Required gates" in report.text
        repeat = client.post("/api/v1/validations", headers=HEADERS, json={
            "symbol": "BEL", "market_run_id": market["id"], "request_key": key}).json()
        assert repeat["id"] == result["id"]
