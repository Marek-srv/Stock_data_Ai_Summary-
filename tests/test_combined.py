import json
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient

from graph_stock.app import create_app
from test_paper import BASE, HEADERS, activate, import_market, insert_validation
from test_backtest import bar


def decision(app, book_id, session, signal):
    with app.state.store.connect() as db:
        sequence = db.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM paper_events WHERE book_id=?", (book_id,)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO paper_events VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4()), book_id, sequence, session, "decision", json.dumps({"signal": signal})),
        )


def create_members(app, client):
    baseline = import_market(client, BASE, "a")
    validation_id = insert_validation(app, baseline["id"])
    return baseline, activate(client, validation_id), activate(client, validation_id)


def activate_combined(client, members, allocations=None, key=None):
    payload = {
        "symbol": "BEL",
        "member_book_ids": [member["id"] for member in members],
        "request_key": key or str(uuid.uuid4()),
        "initial_cash": "100000",
    }
    if allocations is not None:
        payload["allocations_percent"] = allocations
    response = client.post("/api/v1/combined-books", headers=HEADERS, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def process(client, book_id, market_id, key=None):
    return client.post(
        f"/api/v1/combined-books/{book_id}/process",
        headers=HEADERS,
        json={"market_run_id": market_id, "request_key": key or str(uuid.uuid4())},
    )


def test_shared_cash_conflicts_attribution_and_own_ledger_reconcile(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        _, member1, member2 = create_members(app, client)
        original_member_states = [member1["state"], member2["state"]]
        combined = activate_combined(client, [member1, member2])

        day7 = bar("2025-01-07", 100, 104, 99, 102)
        decision(app, member1["id"], "2025-01-07", "ENTRY")
        decision(app, member2["id"], "2025-01-07", "ENTRY")
        market7 = import_market(client, BASE + [day7], "b")
        queued_response = client.post(f"/api/v1/combined-books/{combined['id']}/catch-up", headers=HEADERS, json={
            "market_run_id": market7["id"], "request_key": str(uuid.uuid4())
        })
        assert queued_response.status_code == 200
        queued = queued_response.json()
        assert queued["process"]["mode"] == "replay"
        assert len(queued["state"]["pending_orders"]) == 2
        replay_decisions = [event for event in queued["events"] if event["kind"] == "decision"]
        assert all(event["payload"]["processing_mode"] == "replay" for event in replay_decisions)
        assert all(event["payload"]["member_decision_event_id"] for event in replay_decisions)

        day8 = bar("2025-01-08", 101, 105, 100, 103)
        decision(app, member1["id"], "2025-01-08", "HOLD")
        decision(app, member2["id"], "2025-01-08", "HOLD")
        market8 = import_market(client, BASE + [day7, day8], "c")
        request_key = str(uuid.uuid4())
        filled = process(client, combined["id"], market8["id"], request_key).json()
        duplicate = process(client, combined["id"], market8["id"], request_key).json()
        assert duplicate["process"]["processed_sessions"] == 1
        assert len([event for event in filled["events"] if event["kind"] == "fill"]) == 2
        assert len([event for event in filled["events"] if event["kind"] == "fee"]) == 2
        assert Decimal(filled["state"]["cash"]) >= 0
        assert sum(Decimal(position["cost_basis"]) for position in filled["state"]["positions"].values()) <= Decimal("100000")

        day9 = bar("2025-01-09", 104, 107, 102, 105)
        decision(app, member1["id"], "2025-01-09", "EXIT")
        decision(app, member2["id"], "2025-01-09", "ENTRY")
        market9 = import_market(client, BASE + [day7, day8, day9], "d")
        conflicted = process(client, combined["id"], market9["id"]).json()
        rejected = [event for event in conflicted["events"] if event["kind"] == "order-rejected"]
        assert rejected[-1]["payload"]["reason"] == "exit-precedence-conflict"
        assert conflicted["state"]["pending_orders"] == [{
            "created_session": "2025-01-09", "member_book_id": member1["id"], "side": "sell"
        }]

        day10 = bar("2025-01-10", 106, 109, 104, 108)
        decision(app, member1["id"], "2025-01-10", "WATCH")
        decision(app, member2["id"], "2025-01-10", "WATCH")
        market10 = import_market(client, BASE + [day7, day8, day9, day10], "e")
        exited = process(client, combined["id"], market10["id"]).json()
        member1_fills = [event for event in exited["events"] if event["kind"] == "fill" and event["payload"]["member_book_id"] == member1["id"]]
        assert [event["payload"]["side"] for event in member1_fills] == ["buy", "sell"]
        assert exited["state"]["positions"][member1["id"]]["quantity"] == "0"

        # Combined fills never mutate either independently capitalized member book.
        assert app.state.paper.get(member1["id"])["state"] == original_member_states[0]
        assert app.state.paper.get(member2["id"])["state"] == original_member_states[1]
        assert client.get(f"/api/v1/combined-books/{combined['id']}/report").status_code == 200

    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        reopened = client.get(f"/api/v1/combined-books/{combined['id']}").json()
        assert reopened["state"]["reconciliation"]["status"] == "matched"


def test_allocation_change_creates_new_policy_and_preserves_old_book(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        _, member1, member2 = create_members(app, client)
        members = [member1, member2]
        first = activate_combined(client, members)
        changed = activate_combined(client, members, {
            member1["id"]: "70", member2["id"]: "30"
        })
        assert first["id"] != changed["id"]
        assert first["state"]["policy_id"] != changed["state"]["policy_id"]
        preserved = client.get(f"/api/v1/combined-books/{first['id']}").json()
        assert list(preserved["state"]["policy"]["allocations_percent"].values()) == ["50", "50"]
        assert changed["state"]["policy"]["allocations_percent"][member1["id"]] == "70"


def test_combined_activation_validates_members_and_shared_policy(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        _, member1, member2 = create_members(app, client)
        one = client.post("/api/v1/combined-books", headers=HEADERS, json={
            "symbol": "BEL", "member_book_ids": [member1["id"], member1["id"]],
            "request_key": str(uuid.uuid4()), "initial_cash": "100000"
        })
        assert one.status_code == 422
        too_much = client.post("/api/v1/combined-books", headers=HEADERS, json={
            "symbol": "BEL", "member_book_ids": [member1["id"], member2["id"]],
            "request_key": str(uuid.uuid4()), "initial_cash": "100000",
            "allocations_percent": {member1["id"]: "60", member2["id"]: "60"}
        })
        assert too_much.status_code == 422
