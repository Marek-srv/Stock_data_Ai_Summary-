import copy
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from graph_stock.app import create_app
from graph_stock.market_data import MarketDataError, normalize_market_bundle

HEADERS = {"X-Graph-Stock": "local-research"}


def bundle(action=None):
    actions = [action] if action else []
    return {
        "symbol": "BEL", "name": "Bharat Electronics Limited", "exchange": "NSE",
        "isin": "INE263A01024",
        "aliases": [{"symbol": "BEL", "isin": "INE263A01024", "effective_from": "2000-01-01", "effective_to": None}],
        "bars": [
            {"session": "2025-01-02", "open": "96", "high": "105", "low": "95", "close": "100", "volume": 1000,
             "status": "regular", "series": "EQ", "source_id": "source:fixture"},
            {"session": "2025-01-03", "open": "51", "high": "54", "low": "50", "close": "52", "volume": 2200,
             "status": "regular", "series": "EQ", "source_id": "source:fixture"},
        ],
        "benchmark": {"symbol": "NIFTY 50", "bars": [
            {"session": "2025-01-02", "open": "24000", "high": "24200", "low": "23900", "close": "24100", "volume": None,
             "status": "regular", "series": "INDEX", "source_id": "source:fixture"},
            {"session": "2025-01-03", "open": "24100", "high": "24300", "low": "24000", "close": "24200", "volume": None,
             "status": "regular", "series": "INDEX", "source_id": "source:fixture"},
        ]},
        "actions": actions, "expected_sessions": ["2025-01-02", "2025-01-03"],
        "source": {"source_id": "source:fixture", "provider": "fixture", "title": "Hand-worked market fixture",
                   "url": "manual:market.json", "available_at": "2025-01-03T18:00:00+05:30",
                   "retrieved_at": "2025-01-04T00:00:00+00:00", "content_sha256": "a" * 64,
                   "coverage": "two expected NSE sessions"},
    }


def action(kind, terms):
    return {"action_id": f"BEL:{kind}:2025-01-03", "type": kind, "ex_date": "2025-01-03",
            "record_date": "2025-01-03", "terms": terms, "source_id": "source:fixture"}


@pytest.mark.parametrize(("item", "price_factor", "share_factor", "adjusted_close", "adjusted_volume"), [
    (action("split", {"old_shares": "1", "new_shares": "2"}), "0.5", "2", "50", 2000),
    (action("bonus", {"held_shares": "4", "bonus_shares": "1"}), "0.8", "1.25", "80", 1250),
    (action("dividend", {"cash_per_share": "10"}), "0.9", "1", "90", 1000),
    (action("rights", {"held_shares": "4", "rights_shares": "1", "subscription_price": "60"}), "0.92", "1.25", "92", 1250),
])
def test_hand_worked_adjustment_factors(item, price_factor, share_factor, adjusted_close, adjusted_volume):
    result = normalize_market_bundle(bundle(item))
    prior, ex_day = result["adjusted_bars"]
    assert result["actions"][0]["price_factor"] == price_factor
    assert prior["price_factor"] == price_factor and prior["share_factor"] == share_factor
    assert prior["adjusted_close"] == adjusted_close and prior["adjusted_volume"] == adjusted_volume
    assert ex_day["adjusted_close"] == ex_day["close"] and ex_day["price_factor"] == "1"
    assert result["normalization_scope"].endswith("total financial statement values are never adjusted")


@pytest.mark.parametrize("kind", ["rights", "merger", "demerger"])
def test_complex_incomplete_action_blocks_only_affected_history_and_diagnostics_are_visible(kind):
    value = bundle(action(kind, {"rights_shares": "1"} if kind == "rights" else {}))
    value["expected_sessions"].append("2025-01-06")
    value["bars"].append({**value["bars"][1], "status": "suspended"})
    result = normalize_market_bundle(value)
    assert result["actions"][0]["adjustment_status"] == "blocked"
    assert result["adjusted_bars"][0]["reason"].startswith("incomplete-action:")
    assert result["adjusted_bars"][1]["reason"] == "duplicate-session"
    assert result["quality"] == {
        **result["quality"], "missing_sessions": ["2025-01-06"],
        "duplicate_sessions": ["2025-01-03"], "suspensions": ["2025-01-03"], "status": "partial"
    }


def test_invalid_ohlcv_is_rejected():
    value = bundle()
    value["bars"][0]["low"] = "101"
    with pytest.raises(MarketDataError, match="OHLC is inconsistent"):
        normalize_market_bundle(value)


def test_api_persists_raw_evidence_aliases_benchmark_and_report(tmp_path):
    fixture = bundle(action("split", {"old_shares": "1", "new_shares": "2"}))
    fixture["isin"] = fixture["aliases"][0]["isin"] = "INE263A01016"
    app = create_app(tmp_path, market_provider=lambda symbol: copy.deepcopy(fixture))
    with TestClient(app, base_url="http://localhost") as client:
        with app.state.store.connect() as db:
            db.execute("INSERT INTO filing_sources VALUES (?,?,?,?,?)", (
                "f" * 64, "BEL", "f" * 64,
                json.dumps({"security": {"isin": "INE263A01024"}}), b"fixture"))
        key = str(uuid.uuid4())
        response = client.post("/api/v1/market-data", headers=HEADERS,
                               json={"symbol": "BEL", "request_key": key})
        assert response.status_code == 201
        result = response.json()
        assert result["benchmark"]["symbol"] == "NIFTY 50"
        assert result["aliases"][0]["isin"] == "INE263A01016"
        assert result["identity_conflicts"][0]["selection"] == "unresolved"
        assert result["quality"]["status"] == "complete"
        report = client.get(f"/api/v1/market-data/{result['id']}/report")
        assert report.status_code == 200 and "Raw and adjusted series" in report.text
        repeated = client.post("/api/v1/market-data", headers=HEADERS,
                               json={"symbol": "BEL", "request_key": key}).json()
        assert repeated["id"] == result["id"]
        with app.state.store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM market_sources").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM market_bars").fetchone()[0] == 4
            assert db.execute("SELECT COUNT(*) FROM corporate_actions").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM security_aliases").fetchone()[0] == 1
