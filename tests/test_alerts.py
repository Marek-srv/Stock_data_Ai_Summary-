import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from graph_stock.alerts import AlertService
from graph_stock.app import create_app
from graph_stock.store import Store


HEADERS = {"X-Graph-Stock": "local-research"}


def candidate(version="event-1", severity="medium", material=True):
    return {
        "symbol": "BEL", "category": "thesis", "severity": severity, "material": material,
        "event_version": version, "as_of": "2026-09-08T10:00:00+00:00",
        "summary": "The evidence-backed thesis changed from its saved baseline.",
        "source": {"type": "update-run", "id": "run-2", "evidence_ids": ["evidence-1", "evidence-2"]},
        "comparison": {"baseline_score": "60", "current_score": "68", "score_change": "8"},
        "next_action": "Review the changed thesis and its cited evidence.",
    }


def test_versioned_filter_dedup_revision_and_persisted_acknowledgement(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    service = AlertService(store, tmp_path / "vault")
    assert service.config()["minimum_severity"] == "medium"
    assert service.create(candidate("low", "low", False))[0]["filtered"] is True

    first, created = service.create(candidate())
    repeated, repeated_created = service.create(candidate())
    changed, changed_created = service.create(candidate("event-2"))
    assert created and not repeated_created and changed_created
    assert repeated["alert"]["id"] == first["alert"]["id"]
    assert changed["alert"]["id"] != first["alert"]["id"]

    config = service.configure("high", True)
    assert config["policy_version"] == "alert-materiality/v1"
    assert service.create(candidate("event-3"))[0]["filtered"] is True
    acknowledged = service.acknowledge(first["alert"]["id"], "Reviewed against the source filing.")
    restarted = AlertService(store, tmp_path / "vault").get(acknowledged["id"])
    assert restarted["acknowledged_at"] and restarted["acknowledgement"].startswith("Reviewed")


def test_interrupted_note_publication_recovers_and_preserves_user_text(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.sqlite3")
    service = AlertService(store, tmp_path / "vault")
    original_publish = service.vault.publish
    monkeypatch.setattr(service.vault, "publish", lambda path, content: (_ for _ in ()).throw(OSError("disk busy")))
    outcome, created = service.create(candidate())
    assert created and outcome["alert"]["publication_status"] == "publication-failed"

    monkeypatch.setattr(service.vault, "publish", original_publish)
    service.recover()
    alert = service.get(outcome["alert"]["id"])
    assert alert["publication_status"] == "published" and alert["note"]["integrity"] == "verified"
    note_file = tmp_path / "vault" / alert["note"]["path"]
    note_file.write_text(note_file.read_text() + "\n## My note\nKeep this observation.\n")
    with store.connect() as db:
        db.execute("UPDATE alerts SET publication_status='publication-failed' WHERE id=?", (alert["id"],))
    service.recover()
    preserved = service.get(alert["id"])
    assert preserved["publication_status"] == "preserved-user-text"
    assert preserved["note"]["integrity"] == "modified"
    assert "Keep this observation" in service.read_note(alert["id"])
    assert [item["status"] for item in preserved["deliveries"]] == ["publication-failed", "published", "preserved-user-text"]


def test_scan_emits_three_material_categories_then_stays_silent(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    with store.connect() as db:
        db.executescript("""
            CREATE TABLE paper_books (id TEXT, symbol TEXT);
            CREATE TABLE paper_monitor_runs (book_id TEXT, created_at TEXT, result TEXT);
            CREATE TABLE ownership_runs (symbol TEXT, created_at TEXT, result TEXT);
            CREATE TABLE update_runs (id TEXT, symbol TEXT, status TEXT, updated_at TEXT, result TEXT);
        """)
        monitor = {"id": "monitor-1", "book_id": "book-1", "status": "degraded", "policy_version": "policy-1",
                   "created_at": "2026-09-08T10:00:00+00:00", "reasons": ["drawdown"],
                   "paper": {"max_drawdown_percent": "22"},
                   "backtest": {"validation_id": "validation-1", "max_drawdown_percent": "12"}}
        ownership = {"id": "ownership-1", "comparison": {"current_period": "2026-Q2", "prior_period": "2026-Q1",
                     "comparisons": [{"holder_id": "fii", "percentage_point_change": "-1.2", "status": "reduced"}]},
                     "sources": [{"source_id": "holding-1", "published_at": "2026-07-20T00:00:00+00:00"}]}
        old = {"investment_thesis": {"thesis_id": "thesis-old"}, "scorecard": {"overall_score": "60"}}
        new = {"investment_thesis": {"thesis_id": "thesis-new"}, "scorecard": {"overall_score": "68"},
               "complete_snapshot": {"as_of_time": "2026-09-08T10:00:00+00:00"}}
        db.execute("INSERT INTO paper_books VALUES (?,?)", ("book-1", "BEL"))
        db.execute("INSERT INTO paper_monitor_runs VALUES (?,?,?)", ("book-1", monitor["created_at"], json.dumps(monitor)))
        db.execute("INSERT INTO ownership_runs VALUES (?,?,?)", ("BEL", "2026-07-20", json.dumps(ownership)))
        db.execute("INSERT INTO update_runs VALUES (?,?,?,?,?)", ("old", "BEL", "completed", "2026-08-01", json.dumps(old)))
        db.execute("INSERT INTO update_runs VALUES (?,?,?,?,?)", ("new", "BEL", "completed", "2026-09-08", json.dumps(new)))
    service = AlertService(store, tmp_path / "vault")
    first = service.scan("BEL", str(uuid.uuid4()))
    repeated = service.scan("BEL", str(uuid.uuid4()))
    assert {item["category"] for item in first["created"]} == {"paper-risk", "ownership", "thesis"}
    assert repeated["created"] == [] and len(repeated["deduplicated"]) == 3
    assert len(service.recent("BEL")) == 3


def test_alert_api_lists_configures_acknowledges_and_reads_note(tmp_path):
    with TestClient(create_app(tmp_path, vault_dir=tmp_path / "vault", scheduler_runner=lambda job, key: {"status": "unchanged"}), base_url="http://localhost") as client:
        alert = client.app.state.alerts.create(candidate())[0]["alert"]
        listed = client.get("/api/v1/alerts?symbol=BEL").json()
        assert listed[0]["id"] == alert["id"]
        configured = client.put("/api/v1/alerts/config", headers=HEADERS,
                                json={"minimum_severity": "high", "material_only": True})
        assert configured.status_code == 200 and configured.json()["minimum_severity"] == "high"
        ack = client.post(f"/api/v1/alerts/{alert['id']}/acknowledge", headers=HEADERS,
                          json={"note": "Checked"}).json()
        assert ack["acknowledgement"] == "Checked"
        note = client.get(f"/api/v1/alerts/{alert['id']}/note")
        assert note.status_code == 200 and "Comparison baseline" in note.text and "Next action" in note.text
