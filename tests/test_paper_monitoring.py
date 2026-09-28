import json
import uuid

from fastapi.testclient import TestClient

from graph_stock.app import create_app
from test_backtest import bar
from test_paper import BASE, DAY4, DAY5, HEADERS, activate, import_market, insert_validation


def add_validation_baseline(app, validation_id):
    with app.state.store.connect() as db:
        row = db.execute("SELECT result FROM validation_runs WHERE id=?", (validation_id,)).fetchone()
        result = json.loads(row["result"])
        result["windows"]["untouched_oos"]["sessions"] = 12
        result["oos_result"] = {"metrics": {
            "total_return_percent": "25", "max_drawdown_percent": "5", "trade_count": 4
        }}
        db.execute("UPDATE validation_runs SET result=? WHERE id=?", (json.dumps(result), validation_id))


def catch_up(client, book_id, market_id, key, extra=None):
    payload = {"market_run_id": market_id, "request_key": key, **(extra or {})}
    return client.post(f"/api/v1/paper-books/{book_id}/catch-up", headers=HEADERS, json=payload)


def test_multiday_replay_is_chronological_leakage_safe_idempotent_and_degrades(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        baseline_market = import_market(client, BASE, "a")
        validation_id = insert_validation(app, baseline_market["id"])
        add_validation_baseline(app, validation_id)
        book = activate(client, validation_id)

        day9 = bar("2025-01-09", 102, 105, 99, 100)
        missed_market = import_market(client, BASE + [DAY4, DAY5, day9], "b")
        key = str(uuid.uuid4())

        # Catch-up has no thesis/research input surface, so a late disclosure cannot enter a past decision.
        rejected = catch_up(client, book["id"], missed_market["id"], key, {"thesis": "late information"})
        assert rejected.status_code == 422
        response = catch_up(client, book["id"], missed_market["id"], key)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["catch_up"]["mode"] == "replay"
        assert result["catch_up"]["processed_sessions"] == 3
        replay_events = result["book"]["events"]
        assert sorted({event["session"] for event in replay_events}) == ["2025-01-07", "2025-01-08", "2025-01-09"]
        assert all(event["payload"]["processing_mode"] == "replay" for event in replay_events)
        assert all(event["payload"]["input_scope"] == "frozen-strategy-market-session" for event in replay_events)
        decisions = [event for event in replay_events if event["kind"] == "decision"]
        assert [event["session"] for event in decisions] == ["2025-01-07", "2025-01-08", "2025-01-09"]
        assert all(event["payload"]["candidate_version"] == result["book"]["state"]["candidate_version"] for event in decisions)
        assert all("history" in event["payload"] for event in decisions)

        monitoring = result["monitoring"]
        assert monitoring["status"] == "degraded"
        assert monitoring["paper"]["sample_sessions"] == 3
        assert monitoring["backtest"]["sample_sessions"] == 12
        assert monitoring["backtest"]["closed_trades"] == 4
        assert "paper-drawdown-threshold-exceeded" in monitoring["reasons"]
        assert result["book"]["state"]["new_entries_paused"] is True
        assert result["book"]["state"]["revalidation"]["status"] == "queued"
        # The already-open position can still queue its risk-reducing EXIT.
        assert result["book"]["state"]["pending_order"]["side"] == "sell"

        repeated = catch_up(client, book["id"], missed_market["id"], key).json()
        assert repeated["monitoring"]["id"] == monitoring["id"]
        assert len(repeated["book"]["events"]) == len(replay_events)
        with app.state.store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM paper_revalidation_queue WHERE book_id=?", (book["id"],)).fetchone()[0] == 1

    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        reopened = client.get(f"/api/v1/paper-books/{book['id']}").json()
        assert reopened["state"]["new_entries_paused"] is True
        assert reopened["monitoring"]["id"] == monitoring["id"]
        history = client.get(f"/api/v1/paper-books/{book['id']}/monitoring").json()
        assert [item["id"] for item in history] == [monitoring["id"]]


def test_monitor_waits_for_minimum_sample_before_degradation_action(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        baseline_market = import_market(client, BASE, "a")
        validation_id = insert_validation(app, baseline_market["id"])
        add_validation_baseline(app, validation_id)
        book = activate(client, validation_id)
        one_day = import_market(client, BASE + [DAY4], "b")
        result = catch_up(client, book["id"], one_day["id"], str(uuid.uuid4())).json()
        assert result["monitoring"]["status"] == "insufficient-sample"
        assert result["monitoring"]["paper"]["sample_sessions"] == 1
        assert result["book"]["state"]["new_entries_paused"] is False
        assert result["book"]["state"]["revalidation"]["status"] == "not-required"


def test_degradation_cancels_a_new_pending_entry_without_duplicate_monitor_event(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        baseline_market = import_market(client, BASE, "a")
        validation_id = insert_validation(app, baseline_market["id"])
        add_validation_baseline(app, validation_id)
        book = activate(client, validation_id)
        rows = BASE + [bar("2025-01-07", 100, 102, 99, 100),
                       bar("2025-01-08", 100, 102, 99, 100),
                       bar("2025-01-09", 118, 122, 117, 120)]
        market = import_market(client, rows, "b")
        key = str(uuid.uuid4())
        result = catch_up(client, book["id"], market["id"], key).json()
        assert result["monitoring"]["status"] == "degraded"
        assert result["monitoring"]["cancelled_pending_entry"] is True
        assert result["book"]["state"]["pending_order"] is None
        monitor_events = [event for event in result["book"]["events"] if event["kind"] == "monitoring"]
        assert len(monitor_events) == 1 and monitor_events[0]["payload"]["action"] == "cancel-pending-entry"
        repeated = catch_up(client, book["id"], market["id"], key)
        assert repeated.status_code == 200
        assert len([event for event in repeated.json()["book"]["events"] if event["kind"] == "monitoring"]) == 1
