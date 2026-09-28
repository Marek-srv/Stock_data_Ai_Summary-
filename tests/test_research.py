import io
import json
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from graph_stock.__main__ import main
from graph_stock.app import create_app
from graph_stock.fixtures import search
from graph_stock.research import ResearchError, ResearchService
from graph_stock.store import Store
from graph_stock.vault import Vault


HEADERS = {"X-Graph-Stock": "local-research"}


def wait(client, run_id):
    for _ in range(100):
        run = client.get(f"/api/research/{run_id}").json()
        if run["status"] != "publishing":
            return run
        time.sleep(.01)
    pytest.fail("Research publication did not finish")


@pytest.fixture
def service(tmp_path):
    return ResearchService(Store(tmp_path / "state.sqlite3"), tmp_path / "vault")


@pytest.mark.parametrize("query", ["HAL", " hal ", "NSE:HAL", "Hindustan Aeronautics Limited"])
def test_exact_fixture_identity(query):
    resolution = search(query)
    assert resolution["status"] == "resolved"
    assert resolution["mode"] == "fixture"
    assert [c["security_id"] for c in resolution["candidates"]] == ["NSE:HAL"]


def test_ambiguous_and_unknown_queries_have_no_side_effects(service):
    for query, expected in [("Bharat", "ambiguous"), ("unknown", "not-found"), (" ", "not-found")]:
        with pytest.raises(ResearchError) as error:
            service.submit(query, str(uuid.uuid4()))
        assert error.value.code == expected
    assert service.watchlist() == []
    assert not service.vault.root.exists()


def test_end_to_end_snapshot_golden_values_note_and_restart(tmp_path):
    state, vault = tmp_path / "state", tmp_path / "vault"
    vault.mkdir()
    authored = vault / "My thesis.md"
    authored.write_text("User-authored research must remain unchanged.")
    key = str(uuid.uuid4())
    with TestClient(create_app(state, vault_dir=vault), base_url="http://localhost") as client:
        response = client.post("/api/research", headers=HEADERS, json={"query": "HAL", "request_key": key})
        assert response.status_code == 202, response.text
        first = response.json()
        duplicate = client.post("/api/research", headers=HEADERS, json={"query": " hal ", "request_key": key})
        assert duplicate.json()["id"] == first["id"]
        run = wait(client, first["id"])
        assert run["status"] == "completed" and run["note"]["integrity"] == "verified"
        snapshot = run["snapshot"]
        assert snapshot["mode"] == "fixture" and "SYNTHETIC TEST DATA" in snapshot["notice"]
        assert snapshot["research_score"] is None and snapshot["confidence"] is None
        assert {m["id"]: float(m["value"]) for m in snapshot["metrics"]} == {"revenue": 1200, "growth": 20, "margin": 15}
        assert all(m["evidence_id"] == snapshot["evidence"][0]["id"] for m in snapshot["metrics"])
        assert snapshot["run_id"] == run["id"] and snapshot["saved_at"] == run["created_at"]
        note = client.get(f'/api/research/{run["id"]}/note')
        assert note.status_code == 200 and note.headers["content-type"].startswith("text/plain")
        assert "fixture:HAL:financials:v1" in note.text and "1200" in note.text
        assert (vault / run["note"]["relative_path"]).read_text() == note.text
        assert "obsidian://open?path=" in run["note"]["obsidian_uri"] and "%20" in run["note"]["obsidian_uri"]
        rows = client.get("/api/watchlist").json()
        assert len(rows) == 1 and rows[0]["symbol"] == "HAL" and len(rows[0]["runs"]) == 1
        original = run
    with TestClient(create_app(state, vault_dir=vault), base_url="http://localhost") as client:
        restored = client.get(f'/api/research/{original["id"]}').json()
        assert restored == original
        assert client.get(f'/api/research/{original["id"]}/note').text == note.text
    assert authored.read_text() == "User-authored research must remain unchanged."


def test_same_key_different_company_is_conflict(service):
    key = str(uuid.uuid4())
    service.submit("HAL", key)
    with pytest.raises(ResearchError) as error:
        service.submit("BEL", key)
    assert error.value.code == "key-conflict"
    assert len(service.watchlist()) == 1


def test_new_snapshots_keep_old_notes_and_user_edits(service):
    first, _ = service.submit("HAL", str(uuid.uuid4()))
    service.publish(first)
    record = service.get(first)
    path = service.vault.root / record["note"]["relative_path"]
    path.write_text("# My edits\n<script>not executable</script>")
    second, _ = service.submit("HAL", str(uuid.uuid4()))
    service.publish(second)
    assert len(service.watchlist()) == 1 and len(service.watchlist()[0]["runs"]) == 2
    assert service.get(first)["note"]["integrity"] == "modified"
    assert service.read_note(first) == "# My edits\n<script>not executable</script>"
    assert service.get(second)["note"]["integrity"] == "verified"
    assert not service.retry(first)


def test_existing_conflicting_note_is_never_overwritten(service):
    run_id, _ = service.submit("HAL", str(uuid.uuid4()))
    path = service.vault.root / service.get(run_id)["note"]["relative_path"]
    path.parent.mkdir(parents=True)
    path.write_text("Existing human note")
    service.publish(run_id)
    assert service.get(run_id)["status"] == "note-conflict"
    assert path.read_text() == "Existing human note"
    assert service.retry(run_id)
    service.publish(run_id)
    assert path.read_text() == "Existing human note"
    assert service.get(run_id)["status"] == "note-conflict"


def test_pending_publication_recovers_at_startup(tmp_path):
    state, vault = tmp_path / "state", tmp_path / "vault"
    service = ResearchService(Store(state / "graph_stock.sqlite3"), vault)
    run_id, _ = service.submit("HAL", str(uuid.uuid4()))
    with TestClient(create_app(state, vault_dir=vault), base_url="http://localhost") as client:
        assert wait(client, run_id)["status"] == "completed"
    assert len(list(vault.rglob("*.md"))) == 1


def test_crash_after_file_publish_before_database_commit_is_idempotent(service):
    run_id, _ = service.submit("HAL", str(uuid.uuid4()))
    with service.store.connect() as db:
        row = db.execute("SELECT note_path,note_text FROM fixture_research_runs WHERE id=?", (run_id,)).fetchone()
    service.vault.publish(row["note_path"], row["note_text"])
    assert service.get(run_id)["status"] == "publishing"
    service.publish(run_id)
    assert service.get(run_id)["status"] == "completed"
    assert len(list(service.vault.root.rglob("*.md"))) == 1
    assert not list(service.vault.root.rglob("*.tmp"))


def test_symlink_directory_cannot_escape_vault(service, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    service.vault.root.mkdir()
    (service.vault.root / "Graph Stock").symlink_to(outside, target_is_directory=True)
    run_id, _ = service.submit("HAL", str(uuid.uuid4()))
    service.publish(run_id)
    assert service.get(run_id)["status"] == "publication-failed"
    assert list(outside.iterdir()) == []


def test_symlink_note_is_not_read_or_overwritten(service, tmp_path):
    target = tmp_path / "private.md"
    target.write_text("Private note")
    run_id, _ = service.submit("HAL", str(uuid.uuid4()))
    path = service.vault.root / service.get(run_id)["note"]["relative_path"]
    path.parent.mkdir(parents=True)
    path.symlink_to(target)
    service.publish(run_id)
    assert service.get(run_id)["status"] == "publication-failed"
    assert service.get(run_id)["note"]["integrity"] == "unavailable"
    with pytest.raises(FileNotFoundError):
        service.read_note(run_id)
    assert target.read_text() == "Private note"


def test_changed_vault_does_not_relocate_pending_note(service, tmp_path):
    run_id, _ = service.submit("HAL", str(uuid.uuid4()))
    replacement = ResearchService(service.store, tmp_path / "different-vault")
    replacement.publish(run_id)
    assert replacement.get(run_id)["status"] == "publication-failed"
    assert not replacement.vault.root.exists()
    assert service.retry(run_id)
    service.publish(run_id)
    assert service.get(run_id)["status"] == "completed"


def test_note_io_failure_keeps_snapshot_and_retries_same_run(service, monkeypatch):
    run_id, _ = service.submit("HAL", str(uuid.uuid4()))
    original = service.vault.publish
    def fail(*args):
        raise PermissionError("injected failure")
    monkeypatch.setattr(service.vault, "publish", fail)
    service.publish(run_id)
    assert service.get(run_id)["snapshot"]["security"]["symbol"] == "HAL"
    assert service.get(run_id)["status"] == "publication-failed"
    monkeypatch.setattr(service.vault, "publish", original)
    assert service.retry(run_id)
    service.publish(run_id)
    assert service.get(run_id)["status"] == "completed"


def test_api_validation_ambiguity_origin_and_download(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        body = {"query": "Bharat", "request_key": str(uuid.uuid4())}
        response = client.post("/api/research", headers=HEADERS, json=body)
        assert response.status_code == 409
        assert [c["symbol"] for c in response.json()["detail"]["candidates"]] == ["BEL", "BHEL"]
        assert client.post("/api/research", json=body).status_code == 403
        assert client.post("/api/research", headers={**HEADERS, "Origin": "https://attacker.example"}, json=body).status_code == 403
        assert client.post("/api/research", headers=HEADERS, json={**body, "vault_dir": "/tmp"}).status_code == 422
        assert client.get("/api/securities?query=missing").json()["status"] == "not-found"
        assert client.get("/api/watchlist").json() == []
        body["query"] = "HAL"
        run = client.post("/api/research", headers={**HEADERS, "Origin": "http://localhost"}, json=body).json()
        wait(client, run["id"])
        download = client.get(f'/api/research/{run["id"]}/note?download=true')
        assert download.status_code == 200 and 'attachment;' in download.headers["content-disposition"]


def test_cli_calls_same_http_contract(tmp_path, capsys):
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        def send(base, path, body=None):
            response = client.post(path, json=body, headers=HEADERS) if body is not None else client.get(path)
            if response.status_code >= 400:
                raise HTTPError(base + path, response.status_code, "error", {}, io.BytesIO(response.content))
            return response.json()
        key = str(uuid.uuid4())
        assert main(["research", "HAL", "--request-key", key], send=send) == 0
        result = json.loads(capsys.readouterr().out)
        assert client.get(f'/api/research/{result["id"]}').json() == result
        assert main(["research", "hal", "--request-key", key], send=send) == 0
        assert json.loads(capsys.readouterr().out)["id"] == result["id"]
        assert main(["research", "Bharat"], send=send) == 2
        assert "ambiguous" in capsys.readouterr().err


def test_queue_bound(service):
    keys = [str(uuid.uuid4()) for _ in range(8)]
    ids = [service.submit("HAL", key)[0] for key in keys]
    assert service.submit("HAL", keys[0]) == (ids[0], False)
    with pytest.raises(ResearchError) as error:
        service.submit("HAL", str(uuid.uuid4()))
    assert error.value.code == "queue-full"


def test_vault_rejects_absolute_and_parent_traversal(tmp_path):
    for path in ("../outside.md", "/tmp/outside.md"):
        with pytest.raises(ValueError):
            Vault(tmp_path).publish(path, "no")
