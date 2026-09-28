import json
import sqlite3
import uuid
import zipfile

from fastapi.testclient import TestClient

from graph_stock.app import create_app
from graph_stock.history import HistoryService, referenced_paths
from graph_stock.store import Store
from test_financials import SOURCE, golden_facts, wait
from test_specialists import golden_evidence


HEADERS = {"X-Graph-Stock": "local-research"}


def prepared_app(tmp_path):
    return create_app(tmp_path, vault_dir=tmp_path / "vault", financial_extractor=golden_facts,
                      specialist_extractor=golden_evidence,
                      scheduler_runner=lambda job, key: {"status": "unchanged"})


def financial_run(client):
    metadata = {**SOURCE, "public_available_at": "2025-08-05T20:38:33+05:30",
                "security": {"verification": "NSE directory"}}
    with client.app.state.store.connect() as db:
        db.execute("INSERT INTO filing_sources VALUES (?,?,?,?,?)",
                   (SOURCE["id"], "BEL", SOURCE["sha256"], json.dumps(metadata), b"fixture"))
    submitted = client.post("/api/v1/financials", headers=HEADERS,
                            json={"source_id": SOURCE["id"], "request_key": str(uuid.uuid4())}).json()
    return wait(client, submitted["id"])


def correction_payload(fact_id, value, key=None):
    return {"target_id": fact_id, "corrected_value": value,
            "evidence_id": "manual-review:annual-report-page-189",
            "reason": "Transcription checked against the published statement.",
            "request_key": key or str(uuid.uuid4())}


def test_correction_preserves_original_recomputes_current_and_marks_impacts(tmp_path):
    with TestClient(prepared_app(tmp_path), base_url="http://localhost") as client:
        run = financial_run(client)
        fact = next(item for item in run["snapshot"]["facts"] if item["key"] == "revenue" and item["period"] == "FY2025")
        old_note = client.get(f"/api/v1/financials/{run['id']}/note").text
        response = client.post("/api/v1/history/corrections", headers=HEADERS,
                               json=correction_payload(fact["id"], "25000.00"))
        assert response.status_code == 201
        correction = response.json()
        assert correction["previous"]["value"] == "23768.75" and correction["corrected"]["value"] == "25000.00"
        assert correction["previous"]["evidence_id"] != correction["corrected"]["evidence_id"]
        assert any(item["record_type"] == "financial-report" and item["disposition"] == "stale" for item in correction["impacts"])
        current = client.get(f"/api/v1/history/financial/{run['id']}/current").json()
        current_growth = next(item for item in current["current"]["metrics"] if item["id"] == "metric:revenue-growth")
        original_growth = next(item for item in current["original"]["metrics"] if item["id"] == "metric:revenue-growth")
        assert current_growth["value"] != original_growth["value"]
        assert client.get(f"/api/v1/financials/{run['id']}/note").text == old_note


def test_correction_revisions_are_idempotent_and_preserve_user_text(tmp_path):
    with TestClient(prepared_app(tmp_path), base_url="http://localhost") as client:
        run = financial_run(client)
        fact = next(item for item in run["snapshot"]["facts"] if item["key"] == "revenue" and item["period"] == "FY2025")
        key = str(uuid.uuid4()); body = correction_payload(fact["id"], "24000", key)
        first = client.post("/api/v1/history/corrections", headers=HEADERS, json=body).json()
        assert client.post("/api/v1/history/corrections", headers=HEADERS, json=body).json()["id"] == first["id"]
        assert client.post("/api/v1/history/corrections", headers=HEADERS,
                           json={**body, "corrected_value": "24001"}).status_code == 409
        note = client.get(f"/api/v1/history/corrections/{first['id']}/note")
        assert note.status_code == 200 and "Previous evidence" in note.text
        index = tmp_path / "vault" / "Graph Stock/Corrections/BEL/Current corrections.md"
        index.write_text(index.read_text() + "\n## My assessment\nKeep this text.\n")
        second = client.post("/api/v1/history/corrections", headers=HEADERS,
                             json=correction_payload(fact["id"], "24500")).json()
        assert second["version"] == 2 and second["supersedes_id"] == first["id"]
        assert "Keep this text" in index.read_text()

        index.write_text(index.read_text().replace("Current generated corrections", "My edited generated corrections"))
        third = client.post("/api/v1/history/corrections", headers=HEADERS,
                            json=correction_payload(fact["id"], "24750")).json()
        assert third["publication_status"] == "conflict-copy"
        conflict = tmp_path / "vault" / f"Graph Stock/Corrections/BEL/Conflicts/{third['id']}.md"
        assert conflict.is_file() and "generated section was edited" in conflict.read_text()
        assert "My edited generated corrections" in index.read_text()


def test_interrupted_correction_publication_recovers(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.sqlite3")
    with store.connect() as db:
        db.executescript("""
            CREATE TABLE filing_sources (id TEXT PRIMARY KEY, symbol TEXT, hash TEXT, metadata TEXT, content BLOB);
            CREATE TABLE financial_facts (id TEXT PRIMARY KEY, source_id TEXT, payload TEXT);
            CREATE TABLE financial_jobs (id TEXT, source_id TEXT, snapshot TEXT);
        """)
        fact = golden_facts()[0]
        db.execute("INSERT INTO filing_sources VALUES (?,?,?,?,?)", (SOURCE["id"], "BEL", "hash", "{}", b""))
        db.execute("INSERT INTO financial_facts VALUES (?,?,?)", (fact["id"], SOURCE["id"], json.dumps(fact)))
    service = HistoryService(store, tmp_path / "vault", tmp_path)
    original = service.vault.publish
    monkeypatch.setattr(service.vault, "publish", lambda *args: (_ for _ in ()).throw(OSError("interrupted")))
    correction, _ = service.correct_fact(fact["id"], "999", "manual:evidence", "Verified correction", str(uuid.uuid4()))
    assert correction["publication_status"] == "publication-failed"
    monkeypatch.setattr(service.vault, "publish", original)
    service.recover()
    recovered = service.get_correction(correction["id"])
    assert recovered["publication_status"] == "published" and recovered["note"]["integrity"] == "verified"


def test_new_research_run_uses_correction_while_old_output_stays_reconstructable(tmp_path):
    with TestClient(prepared_app(tmp_path), base_url="http://localhost") as client:
        financial = financial_run(client)
        fact = next(item for item in financial["snapshot"]["facts"] if item["key"] == "revenue" and item["period"] == "FY2025")
        correction = client.post("/api/v1/history/corrections", headers=HEADERS,
                                 json=correction_payload(fact["id"], "25000")).json()
        run_id, _ = client.app.state.updates.submit(SOURCE["id"], str(uuid.uuid4()))
        client.app.state.updates.execute(run_id)
        update = client.app.state.updates.get(run_id)
        corrected = next(item for item in update["result"]["snapshot"]["facts"] if item["id"] == fact["id"])
        assert update["status"] == "completed" and corrected["value"] == "25000"
        assert update["result"]["manifest"]["corrections"]["corrections"][0]["id"] == correction["id"]
        assert financial["snapshot"]["facts"] != update["result"]["snapshot"]["facts"]


def test_consistent_backup_and_actual_temporary_restore(tmp_path):
    with TestClient(prepared_app(tmp_path), base_url="http://localhost") as client:
        run = financial_run(client)
        fact = next(item for item in run["snapshot"]["facts"] if item["key"] == "revenue" and item["period"] == "FY2025")
        client.post("/api/v1/history/corrections", headers=HEADERS, json=correction_payload(fact["id"], "25000"))
        backup = client.post("/api/v1/history/backups", headers=HEADERS)
        assert backup.status_code == 201 and backup.json()["status"] == "verified"
        backup_id = backup.json()["id"]
        archive = client.app.state.history.backup_path(backup_id)
        assert zipfile.is_zipfile(archive)
        restore = client.post(f"/api/v1/history/backups/{backup_id}/restore", headers=HEADERS)
        assert restore.status_code == 200 and restore.json()["status"] == "verified"
        restored = restore.json()
        assert restored["database_count"] >= 1 and restored["artifact_count"] >= 3
        restored_db = tmp_path / "restores" / restored["restore_path"].split("/")[-1] / "graph_stock.sqlite3"
        assert referenced_paths(restored_db)
        with sqlite3.connect(restored_db) as db:
            assert db.execute("SELECT COUNT(*) FROM fact_corrections").fetchone()[0] == 1
        download = client.get(f"/api/v1/history/backups/{backup_id}/download")
        assert download.status_code == 200 and download.headers["content-type"] == "application/zip"
