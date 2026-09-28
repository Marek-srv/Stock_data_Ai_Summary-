import hashlib
import uuid

import pytest
from fastapi.testclient import TestClient

from graph_stock.app import create_app
from graph_stock.improvements import ImprovementError, ImprovementService
from graph_stock.store import Store


HEADERS = {"X-Graph-Stock": "local-research"}
REPO = "https://github.com/example/research-tool"


def candidate(change="safe change"):
    return {
        "repository_url": REPO,
        "revision": "a" * 40,
        "release": "v1.2.3",
        "license": "MIT",
        "relevance": "Improves resumable graph checkpoints.",
        "change_summary": change,
        "compatibility": "Compatible with the pinned local interface.",
        "expected_benefit": "Reduces repeated work after interruption.",
        "source_links": [REPO + "/commit/" + "a" * 40],
        "change_sha256": hashlib.sha256(change.encode()).hexdigest(),
    }


def passing_tester(proposal, profile):
    return {"passed": True, "summary": "Focused regression fixture passed in an isolated temporary tree.",
            "evidence": {"isolated": True, "network": "disabled", "profile": profile,
                         "tested_fingerprint": proposal["fingerprint"], "checks": 3}}


def test_mock_update_lifecycle_dedup_and_exact_approval(tmp_path):
    service = ImprovementService(Store(tmp_path / "state.sqlite3"), tmp_path / "vault", passing_tester)
    assert service.configure([REPO], 2)["whitelist"] == [REPO]
    first = service.monitor([candidate()])["proposals"][0]
    duplicate = service.monitor([candidate()])["proposals"][0]
    assert first["created"] and not duplicate["created"]
    proposal = first["proposal"]
    assert proposal["source_kind"] == "whitelist" and proposal["state"] == "discovered"

    proposal = service.assess(proposal["id"])
    proposal = service.test(proposal["id"], "isolated-regression")
    assert proposal["state"] == "awaiting-approval"
    assert proposal["tests"][0]["evidence"]["tested_fingerprint"] == proposal["fingerprint"]
    with pytest.raises(ImprovementError, match="exact tested change"):
        service.decide(proposal["id"], "0" * 64, "approved", "Reviewed evidence")
    proposal = service.decide(proposal["id"], proposal["fingerprint"], "approved", "Reviewed isolated evidence")
    assert proposal["state"] == "approved"
    assert "No upstream code is applied" in service.read_report(proposal["id"])


def test_changed_content_invalidates_approval_and_unapproved_integration_is_blocked(tmp_path):
    service = ImprovementService(Store(tmp_path / "state.sqlite3"), tmp_path / "vault", passing_tester)
    original = service.propose(candidate())["proposal"]
    service.assess(original["id"])
    tested = service.test(original["id"], "isolated-contract")
    service.decide(original["id"], tested["fingerprint"], "approved", "Exact revision reviewed")

    changed = service.propose(candidate("different upstream bytes"))["proposal"]
    old = service.get(original["id"])
    assert changed["supersedes_id"] == original["id"] and old["state"] == "superseded"
    assert old["decisions"][0]["invalidated_at"]
    with pytest.raises(ImprovementError, match="blocked"):
        service.mark_integrated(changed["id"], changed["fingerprint"])
    with pytest.raises(ImprovementError, match="blocked"):
        service.mark_integrated(original["id"], original["fingerprint"])


def test_failed_test_audit_bounded_discovery_and_api_contract(tmp_path):
    failed = lambda proposal, profile: {"passed": False, "summary": "Regression mismatch", "evidence": {"isolated": True}}
    service = ImprovementService(Store(tmp_path / "direct.sqlite3"), tmp_path / "direct-vault", failed)
    service.configure([], 1)
    with pytest.raises(ImprovementError, match="exceeds"):
        service.monitor([candidate("one"), candidate("two")])
    proposal = service.propose(candidate())["proposal"]
    service.assess(proposal["id"])
    proposal = service.test(proposal["id"], "isolated-contract")
    assert proposal["state"] == "sandbox-tested"
    assert proposal["audit"][-1]["action"] == "sandbox-test-failed"

    app = create_app(tmp_path / "api", vault_dir=tmp_path / "api-vault", improvement_tester=passing_tester)
    with TestClient(app, base_url="http://localhost") as client:
        configured = client.put("/api/v1/improvements/config", headers=HEADERS,
            json={"whitelist": [REPO], "discovery_limit": 2})
        assert configured.status_code == 200
        created = client.post("/api/v1/improvements/monitor", headers=HEADERS,
                              json={"candidates": [candidate()]})
        assert created.status_code == 201
        proposal = created.json()["proposals"][0]["proposal"]
        assert client.post(f"/api/v1/improvements/{proposal['id']}/assess", headers=HEADERS).status_code == 200
        tested = client.post(f"/api/v1/improvements/{proposal['id']}/test", headers=HEADERS,
                             json={"profile": "isolated-regression"}).json()
        blocked = client.post(f"/api/v1/improvements/{proposal['id']}/integrated", headers=HEADERS,
                              json={"fingerprint": tested["fingerprint"]})
        assert blocked.status_code == 409
        report = client.get(f"/api/v1/improvements/{proposal['id']}/report")
        assert report.status_code == 200 and "awaiting-approval" in report.text
