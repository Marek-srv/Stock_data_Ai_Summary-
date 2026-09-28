import asyncio
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from graph_stock.app import create_app
from graph_stock.reasoning import Outcome
from graph_stock.store import Store
from test_reasoning import GOOD


HEADERS = {"X-Graph-Stock": "local-diagnostic"}


class Adapter:
    def __init__(self, statuses=None, delay=.01):
        self.statuses = list(statuses or ["completed"])
        self.calls, self.running, self.peak, self.delay = 0, 0, 0, delay

    async def run(self):
        self.calls += 1
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await asyncio.sleep(self.delay)
            status = self.statuses.pop(0) if self.statuses else "completed"
            return Outcome(status, "test-client", "chatgpt", GOOD if status == "completed" else None)
        finally:
            self.running -= 1


def start(client, key=None):
    response = client.post("/api/diagnostics", headers=HEADERS, json={"request_key": key or str(uuid.uuid4())})
    assert response.status_code == 202, response.text
    return response.json()


def wait(client, run_id):
    for _ in range(100):
        result = client.get(f"/api/diagnostics/{run_id}").json()
        if result["status"] not in ("queued", "running"):
            return result
        time.sleep(.01)
    pytest.fail("Diagnostic did not finish")


def test_idempotency_completed_retry_and_restart(tmp_path):
    adapter = Adapter()
    key = str(uuid.uuid4())
    with TestClient(create_app(tmp_path, adapter), base_url="http://localhost") as client:
        run = start(client, key)
        assert start(client, key)["id"] == run["id"]
        result = wait(client, run["id"])
        assert result["result"] == GOOD and result["attempt"] == 1
        client.post(f'/api/diagnostics/{run["id"]}/retry', headers=HEADERS)
        assert adapter.calls == 1
        assert len(client.get("/api/diagnostics").json()) == 1
    with TestClient(create_app(tmp_path, Adapter()), base_url="http://localhost") as client:
        result = client.get(f'/api/diagnostics/{run["id"]}').json()
        assert result["status"] == "completed" and result["result"] == GOOD


@pytest.mark.parametrize("failure", ["waiting-for-auth", "rate-limited", "timed-out", "invalid-output"])
def test_failure_retry_preserves_id_and_attempt_history(tmp_path, failure):
    with TestClient(create_app(tmp_path, Adapter([failure, "completed"])), base_url="http://localhost") as client:
        run = start(client)
        assert wait(client, run["id"])["status"] == failure
        retry = client.post(f'/api/diagnostics/{run["id"]}/retry', headers=HEADERS).json()
        assert retry["id"] == run["id"]
        result = wait(client, run["id"])
        assert result["status"] == "completed" and result["attempt"] == 2
        assert [a["status"] for a in result["attempts"]] == [failure, "completed"]


def test_concurrency_is_bounded(tmp_path):
    adapter = Adapter(delay=.04)
    with TestClient(create_app(tmp_path, adapter), base_url="http://localhost") as client:
        runs = [start(client) for _ in range(4)]
        assert all(wait(client, r["id"])["status"] == "completed" for r in runs)
        assert adapter.calls == 4 and adapter.peak == 1


def test_interruption_recovered_and_retryable(tmp_path):
    store = Store(tmp_path / "graph_stock.sqlite3")
    run_id, _ = store.create(str(uuid.uuid4()))
    assert store.claim(run_id)
    with TestClient(create_app(tmp_path, Adapter()), base_url="http://localhost") as client:
        old = client.get(f"/api/diagnostics/{run_id}").json()
        assert old["status"] == "interrupted" and old["attempts"][0]["status"] == "interrupted"
        client.post(f"/api/diagnostics/{run_id}/retry", headers=HEADERS)
        assert wait(client, run_id)["status"] == "completed"


def test_local_write_guard_and_fixed_contract(tmp_path):
    with TestClient(create_app(tmp_path, Adapter()), base_url="http://localhost") as client:
        payload = {"request_key": str(uuid.uuid4())}
        assert client.post("/api/diagnostics", json=payload).status_code == 403
        assert client.post("/api/diagnostics", json=payload, headers={**HEADERS, "Origin": "https://example.com"}).status_code == 403
        assert client.post("/api/diagnostics", json={**payload, "prompt": "run something"}, headers=HEADERS).status_code == 422
        assert client.get("/", headers={"Host": "attacker.example"}).status_code == 400
        page = client.get("/diagnostic")
        assert page.status_code == 200 and "synthetic" in page.text
        assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/assets/secrets.txt").status_code == 404


def test_two_servers_cannot_recover_each_others_jobs(tmp_path):
    with TestClient(create_app(tmp_path, Adapter()), base_url="http://localhost"):
        with pytest.raises(RuntimeError, match="Another graph_stock server"):
            with TestClient(create_app(tmp_path, Adapter()), base_url="http://localhost"):
                pass


def test_queue_is_bounded_and_duplicate_key_still_works(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    keys = [str(uuid.uuid4()) for _ in range(8)]
    ids = [store.create(key)[0] for key in keys]
    with pytest.raises(OverflowError):
        store.create(str(uuid.uuid4()))
    assert store.create(keys[0]) == (ids[0], False)
