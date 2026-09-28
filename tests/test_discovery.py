import uuid

import pytest
from fastapi.testclient import TestClient

from graph_stock.app import create_app
from graph_stock.discovery import DiscoveryError, DiscoveryService, fixture_universe
from graph_stock.research import ResearchService
from graph_stock.store import Store


HEADERS = {"X-Graph-Stock": "local-research"}


def service(tmp_path, provider=None):
    store = Store(tmp_path / "state.sqlite3")
    research = ResearchService(store, tmp_path / "vault")
    return DiscoveryService(store, tmp_path / "vault", research, provider), research, store


def test_dated_screen_explains_ranking_missing_metrics_and_delisting(tmp_path):
    discovery, _, _ = service(tmp_path)
    run, created = discovery.screen(str(uuid.uuid4()))
    assert created and run["universe"]["as_of_date"] == "2026-09-10"
    assert run["universe"]["source_kind"] == "synthetic-fixture"
    assert run["policy"]["broker_execution"] is False
    assert [(item["symbol"], item["rank"]) for item in run["candidates"]] == [("BEL", 1)]
    bel = run["candidates"][0]
    assert set(bel["components"]) == {"fundamentals", "accumulation", "momentum"}
    assert all(item["evidence_id"] and item["as_of_date"] for item in bel["metrics"])
    excluded = {item["symbol"]: item for item in run["excluded"]}
    assert {item["metric"] for item in excluded["HAL"]["failed_rules"]} == {"return_63d_percent", "relative_strength_63d_pp"}
    assert excluded["BHEL"]["score"] is None
    assert excluded["BHEL"]["missing_metrics"] == [{"metric": "institutional_change_pp", "reason": "comparable-period ownership unavailable"}]
    assert excluded["OLDCO"]["failed_rules"][-1]["metric"] == "listing_status"
    assert "not the whole NSE market" in " ".join(run["limitations"])
    assert "Fixture values" in discovery.read_report(run["id"])


def test_screen_and_queue_deduplicate_and_use_existing_research_service(tmp_path):
    discovery, research, store = service(tmp_path)
    key1, key2 = str(uuid.uuid4()), str(uuid.uuid4())
    first, created = discovery.screen(key1)
    repeated, repeated_created = discovery.screen(key2)
    assert created and not repeated_created and repeated["id"] == first["id"]

    candidate = first["candidates"][0]
    queued = discovery.queue(first["id"], candidate["security_id"], str(uuid.uuid4()))
    duplicate = discovery.queue(first["id"], candidate["security_id"], str(uuid.uuid4()))
    assert queued["created"] and not duplicate["created"]
    assert duplicate["research_run_id"] == queued["research_run_id"]
    research.publish(queued["research_run_id"])
    assert research.get(queued["research_run_id"])["status"] == "completed"
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM fixture_watchlist WHERE security_id=?", (candidate["security_id"],)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM discovery_queue").fetchone()[0] == 1
    excluded = next(item for item in first["excluded"] if item["symbol"] == "HAL")
    with pytest.raises(DiscoveryError, match="eligible"):
        discovery.queue(first["id"], excluded["security_id"], str(uuid.uuid4()))


def test_discovery_api_queues_research_and_rejects_unknown_fields(tmp_path):
    with TestClient(create_app(tmp_path, vault_dir=tmp_path / "vault", discovery_provider=fixture_universe), base_url="http://localhost") as client:
        created = client.post("/api/v1/discovery", headers=HEADERS, json={"request_key": str(uuid.uuid4())})
        assert created.status_code == 201
        run = created.json(); candidate = run["candidates"][0]
        bad = client.post("/api/v1/discovery", headers=HEADERS,
                          json={"request_key": str(uuid.uuid4()), "whole_market": True})
        assert bad.status_code == 422
        queued = client.post(f"/api/v1/discovery/{run['id']}/candidates/{candidate['security_id']}/queue",
                             headers=HEADERS, json={"request_key": str(uuid.uuid4())})
        assert queued.status_code == 202 and queued.json()["research"]["status"] in ("publishing", "completed")
        saved = client.get(f"/api/v1/discovery/{run['id']}").json()
        assert saved["candidates"][0]["queued"]["research_run_id"] == queued.json()["research_run_id"]
        assert client.get(f"/api/v1/discovery/{run['id']}/report").status_code == 200


def test_invalid_universe_classification_is_rejected(tmp_path):
    bad = fixture_universe(); bad["exchange"] = "UNKNOWN"
    discovery, _, _ = service(tmp_path, lambda: bad)
    with pytest.raises(DiscoveryError, match="classification"):
        discovery.screen(str(uuid.uuid4()))
