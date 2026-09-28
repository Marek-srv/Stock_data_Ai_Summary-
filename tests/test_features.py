import copy
import json
import uuid

from fastapi.testclient import TestClient

from graph_stock.app import create_app
from graph_stock.features import build_point_in_time
from test_market_data import bundle

HEADERS = {"X-Graph-Stock": "local-research"}


def candidate(feature_id, family, effective, available, ingested, *, selection=None, value="1",
              precision="timestamp", lineage=None, **extra):
    return {
        "feature_id": feature_id, "selection_key": selection or feature_id, "family": family,
        "name": feature_id, "value": value, "unit": "fixture", "effective_time": effective,
        "public_available_at": available, "ingested_at": ingested, "public_precision": precision,
        "source_id": "fixture-source", "transform_version": "fixture/v1", "lineage": lineage or {}, **extra,
    }


def test_future_financial_holding_and_event_do_not_change_earlier_manifest():
    base = [candidate("market:close", "market", "2025-01-02", "2025-01-02T16:00:00+05:30",
                      "2026-01-01T00:00:00+00:00")]
    future = [
        candidate("financial:earnings", "financial", "2024-12-31", "2025-02-01T18:00:00+05:30", "2025-02-02T00:00:00+00:00"),
        candidate("ownership:fii", "ownership", "2024-12-31", "2025-03-01T00:00:00+05:30", "2025-04-02T00:00:00+00:00", precision="month"),
        candidate("event:contract", "event", "2025-01-05", "2025-01-20T10:00:00+05:30", "2025-01-20T11:00:00+05:30"),
    ]
    before = build_point_in_time("BEL", "2025-01-15T16:00:00+05:30", base)
    with_future = build_point_in_time("BEL", "2025-01-15T16:00:00+05:30", base + future)
    assert [item["feature_id"] for item in with_future["included"]] == ["market:close"]
    assert with_future["dataset_manifest"]["hash"] == before["dataset_manifest"]["hash"]
    reasons = {item["feature_id"]: item["exclusion_reason"] for item in with_future["excluded"]}
    assert reasons == {"event:contract": "published-after-decision", "financial:earnings": "published-after-decision",
                       "ownership:fii": "published-after-decision"}
    assert with_future["included"][0]["data_vintage"]["ingested_after_decision"] is True


def test_same_day_date_only_release_is_conservative_and_restated_value_changes_only_after_release():
    original = candidate("metric:original", "financial", "2024-12-31", "2025-01-01T18:00:00+05:30",
                         "2025-01-02T00:00:00+00:00", selection="financial:profit", value="10",
                         lineage={"input_restated": False})
    restated = candidate("metric:restated", "financial", "2024-12-31", "2025-01-15",
                         "2025-01-16T00:00:00+00:00", selection="financial:profit", value="12",
                         precision="date", lineage={"input_restated": True})
    same_day = build_point_in_time("BEL", "2025-01-15T20:00:00+05:30", [original, restated])
    next_day = build_point_in_time("BEL", "2025-01-16T00:01:00+05:30", [original, restated])
    assert same_day["included"][0]["value"] == "10"
    assert {item["feature_id"]: item["exclusion_reason"] for item in same_day["excluded"]}["metric:restated"] == "published-after-decision"
    assert next_day["included"][0]["value"] == "12"
    assert next_day["excluded"][0]["exclusion_reason"] == "superseded-at-cutoff"


def test_retrospective_reasoning_and_unproven_revision_are_never_backfilled():
    rows = [
        candidate("reasoning:today", "reasoning", "2024-03-31", "2024-08-01T18:00:00+05:30",
                  "2025-02-01T00:00:00+00:00", always_exclude="retrospective-reasoning-not-historical"),
        candidate("event:v2", "event", "2025-01-01", "2025-01-01T10:00:00+05:30",
                  "2025-02-01T00:00:00+00:00", revision_without_new_availability=True),
    ]
    result = build_point_in_time("BEL", "2025-01-15T16:00:00+05:30", rows)
    assert result["included"] == []
    assert {item["exclusion_reason"] for item in result["excluded"]} == {
        "retrospective-reasoning-not-historical", "revision-availability-unproven"}


def test_api_builds_reproducible_snapshot_from_saved_market_rows(tmp_path):
    market = bundle()
    market["source"]["available_at"] = "2025-01-03T16:00:00+05:30"
    market["source"]["retrieved_at"] = "2026-01-01T00:00:00+00:00"
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        source_id, financial_id = "b" * 64, str(uuid.uuid4())
        metadata = {"origin": "https://archives.nseindia.com/verified.pdf",
                    "public_available_at": "2025-01-03T18:00:00+05:30",
                    "retrieved_at": "2026-01-01T00:00:00+00:00",
                    "historical_feature_eligible": False,
                    "security": {"verification": "NSE directory"}}
        snapshot = {"created_at": "2026-01-01T00:00:00+00:00", "period": "FY2025", "metrics": [{
            "id": "metric:revenue-growth", "label": "Revenue growth", "value": "12.5", "unit": "%",
            "period_end": "2024-12-31", "formula_version": "fixture-formula/v1",
            "input_fact_ids": ["fact:revenue-current", "fact:revenue-prior"], "evidence_ids": ["evidence:revenue"],
            "input_restated": False, "scope": "consolidated", "period": "FY2025"}]}
        with app.state.store.connect() as db:
            db.execute("INSERT INTO filing_sources VALUES (?,?,?,?,?)",
                       (source_id, "BEL", source_id, json.dumps(metadata), b"fixture"))
            db.execute("""INSERT INTO financial_jobs
                (id,request_key,fingerprint,source_id,use_reasoning,status,created_at,updated_at,snapshot,interpretation,vault_root)
                VALUES (?,?,?,?,?,'completed',?,?,?,?,?)""",
                (financial_id, str(uuid.uuid4()), "fingerprint", source_id, 1,
                 "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
                 json.dumps(snapshot), json.dumps({"status": "completed"}), str(tmp_path / "vault")))
        imported = client.post("/api/v1/market-data/import", headers=HEADERS, json={
            "symbol": "BEL", "request_key": str(uuid.uuid4()), "bundle": copy.deepcopy(market)}).json()
        assert imported["status"] == "complete"
        request_key = str(uuid.uuid4())
        response = client.post("/api/v1/features", headers=HEADERS, json={
            "symbol": "BEL", "decision_time": "2025-01-04T16:00:00+05:30", "request_key": request_key})
        assert response.status_code == 201
        result = response.json()
        assert {item["family"] for item in result["included"]} == {"market", "benchmark", "financial"}
        assert next(item for item in result["included"] if item["family"] == "financial")["lineage"]["legacy_source_flag"] is False
        assert next(item for item in result["excluded"] if item["family"] == "reasoning")["exclusion_reason"] == "retrospective-reasoning-not-historical"
        assert result["universe"]["status"] == "active"
        assert len(result["dataset_manifest"]["hash"]) == 64
        report = client.get(f"/api/v1/features/{result['id']}/report")
        assert report.status_code == 200 and "Excluded candidates" in report.text
        repeat = client.post("/api/v1/features", headers=HEADERS, json={
            "symbol": "BEL", "decision_time": "2025-01-04T16:00:00+05:30", "request_key": request_key}).json()
        assert repeat["id"] == result["id"]
