import json
import threading
import time
import uuid
from collections import Counter

from fastapi.testclient import TestClient

from graph_stock.app import create_app
from graph_stock.filings import FilingService
from graph_stock.orchestration import NODE_NAMES, UpdateService
from graph_stock.research import ResearchService
from graph_stock.store import Store
from test_financials import SOURCE, golden_facts
from test_specialists import golden_evidence

HEADERS = {"X-Graph-Stock": "local-research"}


def source_copy(marker="a"):
    value = dict(SOURCE)
    value["id"] = marker * 64
    value["sha256"] = chr(ord(marker) + 1) * 64
    return value


def services(tmp_path, hooks=None):
    store = Store(tmp_path / "graph_stock.sqlite3")
    ResearchService(store, tmp_path / "vault")
    filings = FilingService(store, tmp_path / "vault", fetch=lambda url: None)
    service = UpdateService(store, filings, tmp_path / "vault", extractor=golden_facts,
                            specialist_extractor=golden_evidence, hooks=hooks)
    return store, filings, service


def insert_source(store, source):
    with store.connect() as db:
        db.execute("INSERT INTO filing_sources VALUES (?,?,?,?,?)",
                   (source["id"], source["symbol"], source["sha256"], json.dumps(source), b"fixture"))


class Instrument:
    def __init__(self, fail_once=None):
        self.counts, self.fail_once = Counter(), fail_once
        self.running = self.peak = 0
        self.lock = threading.Lock()

    def hook(self, name):
        def record(stage, run_id):
            if stage == "before":
                with self.lock:
                    self.counts[name] += 1
                    self.running += 1
                    self.peak = max(self.peak, self.running)
                    should_fail = self.fail_once == name
                    if should_fail:
                        self.fail_once = None
                if name in ("extract_facts", "research_context", "business_quality", "industry", "competitor"):
                    time.sleep(.04)
                if should_fail:
                    with self.lock:
                        self.running -= 1
                    raise RuntimeError("injected node failure")
            else:
                with self.lock:
                    self.running -= 1
        return record

    @property
    def hooks(self):
        return {name: self.hook(name) for name in NODE_NAMES}


def run(service, source_id):
    run_id, _ = service.submit(source_id, str(uuid.uuid4()))
    service.execute(run_id)
    return service.get(run_id)


def test_graph_dependencies_parallelism_reuse_and_changed_evidence(tmp_path):
    instrument = Instrument()
    store, _, service = services(tmp_path, instrument.hooks)
    first_source = source_copy("a")
    insert_source(store, first_source)
    first = run(service, first_source["id"])
    assert first["status"] == "completed"
    assert [node["status"] for node in first["nodes"]] == ["completed"] * len(NODE_NAMES)
    assert instrument.peak >= 2
    assert first["result"]["manifest"]["versions"] == {
        "extractor": "bel-annual-report/v1", "formula": "baseline-financials/v1",
        "schema": "financial-snapshot/v1", "report": "research-update-note/v5",
        "prompt": "financial-analysis-prompt/v1", "model": "signed-in-client-default",
        "policy": "research-refresh-policy/v1",
    }
    assert first["result"]["manifest"]["specialist_versions"] == {
        "evidence": "bel-qualitative-evidence/v4", "schema": "specialist-report/v2",
        "policy": "evidence-gated-specialists/v1",
    }
    assert first["result"]["manifest"]["event_research_versions"] == {
        "schema": "event-specialist-report/v2", "earnings": "compatible-annual-earnings/v1",
        "claims": "management-claim-status/v1", "valuation": "earnings-multiple-scenarios/v2",
        "risk": "material-risk-baseline/v1",
    }
    assert first["result"]["manifest"]["news_catalyst"] == {
        "descriptor": {"schema_version": "news-catalyst/v1", "event_count": 0,
                       "material_event_count": 0,
                       "digest": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
                       "events": []},
        "schema": "news-catalyst/v1", "policy": "material-events/v1",
    }
    assert first["result"]["manifest"]["synthesis_versions"] == {
        "debate": "independent-debate/v1", "score": "equal-category-score/v1",
        "confidence": "evidence-sufficiency/v1",
    }
    node_times = {node["name"]: node for node in first["nodes"]}
    assert node_times["moat"]["started_at"] >= max(
        node_times[name]["finished_at"] for name in ("business_quality", "industry", "competitor")
    )
    assert node_times["valuation"]["started_at"] >= node_times["earnings"]["finished_at"]
    assert node_times["management"]["started_at"] >= node_times["management_claims"]["finished_at"]
    assert node_times["risk"]["started_at"] >= node_times["valuation"]["finished_at"]
    assert node_times["bull"]["started_at"] >= node_times["risk"]["finished_at"]
    assert node_times["bear"]["started_at"] >= node_times["risk"]["finished_at"]
    assert node_times["judge"]["started_at"] >= max(node_times["bull"]["finished_at"], node_times["bear"]["finished_at"])
    assert len(first["result"]["snapshot"]["specialists"]) == 4
    assert len(first["result"]["snapshot"]["event_research"]) == 5
    assert first["result"]["snapshot"]["news_catalyst"]["coverage"] == "missing-current-events"
    assert first["result"]["debate"]["bull"]["input_manifest_hash"] == first["result"]["debate"]["bear"]["input_manifest_hash"]
    assert first["result"]["complete_snapshot"]["swing_status"]["state"] == "unavailable"
    assert first["result"]["complete_snapshot"]["validation_status"]["state"] == "pending"
    assert len(first["result"]["management_claim_history"]) == 2

    before = instrument.counts.copy()
    repeated = run(service, first_source["id"])
    assert all(node["status"] == "reused" for node in repeated["nodes"])
    assert instrument.counts == before
    assert repeated["result"]["report"] == first["result"]["report"]
    assert repeated["predecessor_id"] == first["id"]

    changed_source = source_copy("c")
    insert_source(store, changed_source)
    changed = run(service, changed_source["id"])
    states = {node["name"]: node["status"] for node in changed["nodes"]}
    assert states == {"manifest": "completed", "extract_facts": "completed",
                      "research_context": "reused", "qualitative_evidence": "completed",
                      "calculate_metrics": "completed", "business_quality": "completed",
                      "industry": "completed", "competitor": "completed", "moat": "completed",
                      "earnings": "completed", "management_claims": "completed",
                      "valuation": "completed", "management": "completed", "risk": "completed",
                      "ownership_intelligence": "reused", "news_catalyst": "reused",
                      "bull": "completed", "bear": "completed", "judge": "completed",
                      "investment_thesis": "completed", "score_snapshot": "completed",
                      "publish_report": "completed"}
    assert changed["predecessor_id"] == repeated["id"]
    assert first["result"]["report"]["path"] != changed["result"]["report"]["path"]
    assert len(changed["result"]["management_claim_history"]) == 6


def test_concurrent_matching_runs_compute_each_fingerprint_once(tmp_path):
    instrument = Instrument()
    store, _, service = services(tmp_path, instrument.hooks)
    source = source_copy("b")
    insert_source(store, source)
    ids = [service.submit(source["id"], str(uuid.uuid4()))[0] for _ in range(2)]
    threads = [threading.Thread(target=service.execute, args=(run_id,)) for run_id in ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert all(service.get(run_id)["status"] == "completed" for run_id in ids)
    assert instrument.counts == Counter({name: 1 for name in NODE_NAMES})


def test_failed_node_resumes_without_repeating_completed_work(tmp_path):
    instrument = Instrument(fail_once="calculate_metrics")
    store, _, service = services(tmp_path, instrument.hooks)
    source = source_copy("d")
    insert_source(store, source)
    run_id, _ = service.submit(source["id"], str(uuid.uuid4()))
    service.execute(run_id)
    failed = service.get(run_id)
    assert failed["status"] == "failed"
    states = {node["name"]: node["status"] for node in failed["nodes"]}
    assert states["manifest"] == states["extract_facts"] == states["research_context"] == "completed"
    assert states["calculate_metrics"] == "failed" and states["publish_report"] == "queued"

    assert service.resume(run_id) is True
    service.execute(run_id)
    completed = service.get(run_id)
    assert completed["status"] == "completed" and completed["resume_count"] == 1
    assert instrument.counts["manifest"] == 1
    assert instrument.counts["extract_facts"] == 1
    assert instrument.counts["research_context"] == 1
    assert instrument.counts["calculate_metrics"] == 2
    assert instrument.counts["publish_report"] == 1


def test_process_interruption_is_recovered_from_sqlite_checkpoint(tmp_path):
    class ProcessStopped(BaseException):
        pass

    stopped = {"value": False}
    def stop_once(stage, run_id):
        if stage == "before" and not stopped["value"]:
            stopped["value"] = True
            raise ProcessStopped()

    store, filings, service = services(tmp_path, {"calculate_metrics": stop_once})
    source = source_copy("f")
    insert_source(store, source)
    run_id, _ = service.submit(source["id"], str(uuid.uuid4()))
    try:
        service.execute(run_id)
    except ProcessStopped:
        pass
    assert service.get(run_id)["status"] == "running"

    recovered = UpdateService(store, filings, tmp_path / "vault", extractor=golden_facts,
                              specialist_extractor=golden_evidence)
    assert recovered.pending() == [run_id]
    recovered.execute(run_id)
    result = recovered.get(run_id)
    assert result["status"] == "completed" and result["resume_count"] == 1
    statuses = {node["name"]: node["status"] for node in result["nodes"]}
    assert statuses["manifest"] == statuses["extract_facts"] == statuses["research_context"] == "completed"
    assert statuses["calculate_metrics"] == statuses["publish_report"] == "completed"


def test_api_cancel_resume_partial_status_and_idempotency(tmp_path):
    app = create_app(tmp_path, vault_dir=tmp_path / "vault", financial_extractor=golden_facts,
                     specialist_extractor=golden_evidence)
    with TestClient(app, base_url="http://localhost") as client:
        source = source_copy("e")
        insert_source(app.state.store, source)
        key = str(uuid.uuid4())
        # Submit directly so cancellation is deterministic before the app schedules execution.
        run_id, _ = app.state.updates.submit(source["id"], key)
        cancelled = client.post(f"/api/v1/updates/{run_id}/cancel", headers=HEADERS).json()
        assert cancelled["status"] == "cancelled"
        resumed = client.post(f"/api/v1/updates/{run_id}/resume", headers=HEADERS).json()
        assert resumed["id"] == run_id
        for _ in range(100):
            result = client.get(f"/api/v1/updates/{run_id}").json()
            if result["status"] not in ("queued", "running"):
                break
            time.sleep(.01)
        assert result["status"] == "completed"
        assert len(result["nodes"]) == len(NODE_NAMES) and result["result"]["snapshot"]["metrics"]
        report = client.get(f"/api/v1/updates/{run_id}/report")
        assert report.status_code == 200 and "Specialist research" in report.text
        specialist = client.get(f"/api/v1/updates/{run_id}/specialists/moat")
        assert specialist.status_code == 200 and "Declared inputs" in specialist.text
        valuation = client.get(f"/api/v1/updates/{run_id}/research/valuation")
        assert valuation.status_code == 200 and "Valuation scenarios" in valuation.text
        bull = client.get(f"/api/v1/updates/{run_id}/synthesis/bull")
        assert bull.status_code == 200 and "Locked input manifest" in bull.text
        scorecard = client.get(f"/api/v1/updates/{run_id}/synthesis/scorecard")
        assert scorecard.status_code == 200 and "Overall:" in scorecard.text
        snapshot = result["result"]["complete_snapshot"]
        assert snapshot["swing_status"]["state"] == "unavailable"
        assert snapshot["validation_status"]["state"] == "pending"
        duplicate = client.post("/api/v1/updates", headers=HEADERS,
                                json={"source_id": source["id"], "request_key": key}).json()
        assert duplicate["id"] == run_id
