"""Dependency-aware LangGraph refresh runs with SQLite checkpoints and node reuse."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from decimal import Decimal
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from .event_research import (
    ADVANCED_SCHEMA_VERSION, CLAIM_POLICY_VERSION, EARNINGS_POLICY_VERSION,
    RISK_POLICY_VERSION, VALUATION_POLICY_VERSION, build_earnings, build_management,
    build_management_claims, build_risk, build_valuation, condensed_advanced,
    render_advanced_note, validate_advanced_report,
)
from .financial_reasoning import PROMPT_VERSION
from .financials import EXTRACTOR_VERSION, FORMULA_VERSION, SCHEMA_VERSION, calculate_metrics, render_note
from .specialists import (
    EVIDENCE_VERSION, SPECIALIST_POLICY_VERSION, SPECIALIST_SCHEMA_VERSION,
    build_business_quality, build_competitor, build_industry, build_moat, condensed,
    extract_bel_evidence, render_specialist_note, validate_evidence_bundle, validate_report,
)
from .store import now
from .vault import NoteConflict, Vault, digest
from .news import NEWS_POLICY_VERSION, NEWS_SCHEMA_VERSION, current_news, news_descriptor
from .news import latest_news_run
from .ownership import SCHEMA_VERSION as OWNERSHIP_SCHEMA_VERSION
from .ownership import latest_ownership, ownership_descriptor
from .debate import (
    CONFIDENCE_POLICY_VERSION, DEBATE_SCHEMA_VERSION, SCORE_POLICY_VERSION,
    build_case, build_judge, build_thesis, evidence_ids as debate_evidence_ids,
    input_manifest as debate_input_manifest, render_agent_note, score_research, validate_scores,
)
from .history import apply_fact_corrections, correction_descriptor

GRAPH_VERSION = "filing-refresh/v5"
POLICY_VERSION = "research-refresh-policy/v1"
REPORT_VERSION = "research-update-note/v5"
MODEL_IDENTITY = "signed-in-client-default"
NODE_NAMES = (
    "manifest", "extract_facts", "research_context", "qualitative_evidence",
    "calculate_metrics", "business_quality", "industry", "competitor", "moat",
    "earnings", "management_claims", "valuation", "management", "ownership_intelligence",
    "news_catalyst", "risk", "bull", "bear", "judge", "investment_thesis", "score_snapshot", "publish_report",
)


class UpdateError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


class Cancelled(Exception):
    pass


class GraphState(TypedDict, total=False):
    run_id: str
    source_id: str
    manifest: dict
    facts: list[dict]
    context: dict
    qualitative_evidence: dict
    business_quality: dict
    industry: dict
    competitor: dict
    moat: dict
    earnings: dict
    management_claims: dict
    valuation: dict
    management: dict
    ownership_intelligence: dict
    news_catalyst: dict
    risk: dict
    bull: dict
    bear: dict
    judge: dict
    investment_thesis: dict
    score_snapshot: dict
    snapshot: dict
    report: dict


def stable_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class UpdateService:
    def __init__(self, store, filings, vault_dir: Path, *, extractor,
                 specialist_extractor=extract_bel_evidence, hooks=None, max_concurrency=2):
        self.store, self.filings, self.vault = store, filings, Vault(vault_dir)
        self.extractor, self.specialist_extractor, self.hooks = extractor, specialist_extractor, hooks or {}
        self.max_concurrency = max(1, min(int(max_concurrency), 4))
        self._cache_guard = threading.Lock()
        self._cache_locks = {}
        self.checkpoint_path = store.path.parent / "langgraph-checkpoints.sqlite3"
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS update_runs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                    source_id TEXT NOT NULL, symbol TEXT NOT NULL, status TEXT NOT NULL,
                    predecessor_id TEXT, manifest_hash TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
                    resume_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    result TEXT NOT NULL DEFAULT '{}', error TEXT
                );
                CREATE TABLE IF NOT EXISTS update_nodes (
                    run_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL,
                    fingerprint TEXT, started_at TEXT, finished_at TEXT,
                    reused_from TEXT, output TEXT, error TEXT,
                    PRIMARY KEY(run_id,name)
                );
                CREATE TABLE IF NOT EXISTS update_node_cache (
                    name TEXT NOT NULL, fingerprint TEXT NOT NULL, output TEXT NOT NULL,
                    producer_run_id TEXT NOT NULL, completed_at TEXT NOT NULL,
                    PRIMARY KEY(name,fingerprint)
                );
                CREATE TABLE IF NOT EXISTS specialist_reports (
                    run_id TEXT NOT NULL, kind TEXT NOT NULL, report_id TEXT NOT NULL,
                    schema_version TEXT NOT NULL, payload TEXT NOT NULL,
                    note_path TEXT NOT NULL, note_sha256 TEXT NOT NULL,
                    PRIMARY KEY(run_id,kind)
                );
                CREATE TABLE IF NOT EXISTS advanced_reports (
                    run_id TEXT NOT NULL, kind TEXT NOT NULL, report_id TEXT NOT NULL,
                    schema_version TEXT NOT NULL, payload TEXT NOT NULL,
                    note_path TEXT NOT NULL, note_sha256 TEXT NOT NULL,
                    PRIMARY KEY(run_id,kind)
                );
                CREATE TABLE IF NOT EXISTS management_claim_states (
                    run_id TEXT NOT NULL, claim_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    observed_period TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(run_id,claim_id)
                );
                CREATE TABLE IF NOT EXISTS synthesis_reports (
                    run_id TEXT NOT NULL, kind TEXT NOT NULL, report_id TEXT NOT NULL,
                    schema_version TEXT NOT NULL, payload TEXT NOT NULL,
                    note_path TEXT NOT NULL, note_sha256 TEXT NOT NULL,
                    PRIMARY KEY(run_id,kind)
                );
            """)
            interrupted = [row[0] for row in db.execute("SELECT id FROM update_runs WHERE status='running'")]
            for run_id in interrupted:
                db.execute("UPDATE update_runs SET status='queued',resume_count=resume_count+1,updated_at=?,error=NULL WHERE id=?",
                           (now(), run_id))
                db.execute("UPDATE update_nodes SET status='interrupted',finished_at=? WHERE run_id=? AND status='running'",
                           (now(), run_id))

    def submit(self, source_id: str, request_key: str):
        try:
            source, _ = self.filings.source(source_id)
        except KeyError:
            raise UpdateError("not-found", "Saved filing source not found.") from None
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT id,source_id FROM update_runs WHERE request_key=?", (request_key,)).fetchone()
            if old:
                if old["source_id"] != source_id:
                    raise UpdateError("conflict", "This request key belongs to another source.")
                return old["id"], False
            if db.execute("SELECT COUNT(*) FROM update_runs WHERE status IN ('queued','running')").fetchone()[0] >= 8:
                raise UpdateError("queue-full", "Research update queue is full.")
            predecessor = db.execute("SELECT id FROM update_runs WHERE symbol=? ORDER BY created_at DESC LIMIT 1",
                                     (source["symbol"],)).fetchone()
            run_id, timestamp = str(uuid.uuid4()), now()
            db.execute("""INSERT INTO update_runs
                (id,request_key,source_id,symbol,status,predecessor_id,created_at,updated_at)
                VALUES (?,?,?,?,'queued',?,?,?)""",
                (run_id, request_key, source_id, source["symbol"], predecessor[0] if predecessor else None,
                 timestamp, timestamp))
            for name in NODE_NAMES:
                db.execute("INSERT INTO update_nodes(run_id,name,status) VALUES (?,?,'queued')", (run_id, name))
        return run_id, True

    def pending(self):
        with self.store.connect() as db:
            return [row[0] for row in db.execute("SELECT id FROM update_runs WHERE status='queued'")]

    def _cancelled(self, run_id):
        with self.store.connect() as db:
            row = db.execute("SELECT cancel_requested FROM update_runs WHERE id=?", (run_id,)).fetchone()
        return not row or bool(row[0])

    def _node(self, run_id: str, name: str, fingerprint: str, compute):
        with self._cache_guard:
            lock = self._cache_locks.setdefault((name, fingerprint), threading.Lock())
        with lock:
            return self._run_node(run_id, name, fingerprint, compute)

    def _run_node(self, run_id: str, name: str, fingerprint: str, compute):
        if self._cancelled(run_id):
            raise Cancelled()
        timestamp = now()
        with self.store.connect() as db:
            cached = db.execute("SELECT output,producer_run_id FROM update_node_cache WHERE name=? AND fingerprint=?",
                                (name, fingerprint)).fetchone()
            if cached:
                output = json.loads(cached["output"])
                db.execute("""UPDATE update_nodes SET status='reused',fingerprint=?,started_at=?,finished_at=?,
                           reused_from=?,output=?,error=NULL WHERE run_id=? AND name=?""",
                           (fingerprint, timestamp, timestamp, cached["producer_run_id"], cached["output"], run_id, name))
                return output
            db.execute("""UPDATE update_nodes SET status='running',fingerprint=?,started_at=?,finished_at=NULL,
                       reused_from=NULL,error=NULL WHERE run_id=? AND name=?""", (fingerprint, timestamp, run_id, name))
        hook = self.hooks.get(name)
        try:
            if hook:
                hook("before", run_id)
            output = compute()
            if hook:
                hook("after", run_id)
            encoded = json.dumps(output, sort_keys=True)
            with self.store.connect() as db:
                db.execute("INSERT OR IGNORE INTO update_node_cache VALUES (?,?,?,?,?)",
                           (name, fingerprint, encoded, run_id, now()))
                cache = db.execute("SELECT output,producer_run_id FROM update_node_cache WHERE name=? AND fingerprint=?",
                                   (name, fingerprint)).fetchone()
                reused_from = cache["producer_run_id"] if cache["producer_run_id"] != run_id else None
                status = "reused" if reused_from else "completed"
                db.execute("""UPDATE update_nodes SET status=?,finished_at=?,reused_from=?,output=?,error=NULL
                           WHERE run_id=? AND name=?""", (status, now(), reused_from, cache["output"], run_id, name))
            return json.loads(cache["output"])
        except Cancelled:
            raise
        except Exception:
            with self.store.connect() as db:
                db.execute("UPDATE update_nodes SET status='failed',finished_at=?,error=? WHERE run_id=? AND name=?",
                           (now(), "Node execution failed; resume to retry.", run_id, name))
            raise

    def _context_descriptor(self, symbol):
        with self.store.connect() as db:
            row = db.execute("""SELECT r.id,r.snapshot FROM fixture_research_runs r
                JOIN fixture_securities s ON s.id=r.security_id
                WHERE s.symbol=? AND r.status='completed' ORDER BY r.created_at DESC LIMIT 1""", (symbol,)).fetchone()
        if not row:
            return {"status": "not-available", "fixture_run_id": None, "snapshot_hash": None}
        return {"status": "available", "fixture_run_id": row["id"], "snapshot_hash": hashlib.sha256(row["snapshot"].encode()).hexdigest()}

    def _specialist_output(self, run_id, name, fingerprint, builder, bundle):
        evidence_ids = {item["id"] for item in bundle["evidence"]}
        def compute():
            report = validate_report(builder(), evidence_ids)
            content = render_specialist_note(report, bundle)
            path = f"Graph Stock/Specialists/{report['symbol']}/{name}-{report['report_id'].split(':')[-1]}.md"
            self.vault.publish(path, content)
            return {"report": report, "note": {"path": path, "sha256": digest(content)}}
        output = self._node(run_id, name, fingerprint, compute)
        report, note = output["report"], output["note"]
        with self.store.connect() as db:
            db.execute("""INSERT OR REPLACE INTO specialist_reports
                (run_id,kind,report_id,schema_version,payload,note_path,note_sha256)
                VALUES (?,?,?,?,?,?,?)""", (run_id, name, report["report_id"], report["schema_version"],
                json.dumps(report, sort_keys=True), note["path"], note["sha256"]))
        return output

    def _advanced_output(self, run_id, name, fingerprint, builder, evidence_ids):
        def compute():
            report = validate_advanced_report(builder(), evidence_ids)
            content = render_advanced_note(report)
            path = f"Graph Stock/Research/{report['symbol']}/{name}-{report['report_id'].split(':')[-1]}.md"
            self.vault.publish(path, content)
            return {"report": report, "note": {"path": path, "sha256": digest(content)}}
        output = self._node(run_id, name, fingerprint, compute)
        report, note = output["report"], output["note"]
        with self.store.connect() as db:
            db.execute("""INSERT OR REPLACE INTO advanced_reports
                (run_id,kind,report_id,schema_version,payload,note_path,note_sha256)
                VALUES (?,?,?,?,?,?,?)""", (run_id, name, report["report_id"], report["schema_version"],
                json.dumps(report, sort_keys=True), note["path"], note["sha256"]))
            if name == "management_claims":
                states = {item["claim_id"]: item for item in report["claim_states"]}
                for claim in report["management_claims"]:
                    state = states[claim["claim_id"]]
                    db.execute("""INSERT OR REPLACE INTO management_claim_states
                        (run_id,claim_id,symbol,observed_period,status,payload) VALUES (?,?,?,?,?,?)""",
                        (run_id, claim["claim_id"], report["symbol"], state["observed_period"], state["status"],
                         json.dumps({"claim": claim, "state": state}, sort_keys=True)))
        return output

    def _claim_history(self, symbol):
        with self.store.connect() as db:
            rows = db.execute("""SELECT run_id,payload FROM management_claim_states
                WHERE symbol=? ORDER BY rowid""", (symbol,)).fetchall()
        return [{"run_id": row["run_id"], **json.loads(row["payload"])} for row in rows]

    def _builder(self):
        builder = StateGraph(GraphState)

        def manifest_node(state):
            source, _ = self.filings.source(state["source_id"])
            news = news_descriptor(self.store, source["symbol"])
            ownership = ownership_descriptor(self.store, source["symbol"])
            corrections = correction_descriptor(self.store, source["id"])
            value = {
                "graph_version": GRAPH_VERSION,
                "evidence": {"source_id": source["id"], "sha256": source["sha256"],
                             "retrieved_at": source["retrieved_at"]},
                "versions": {"extractor": EXTRACTOR_VERSION, "formula": FORMULA_VERSION,
                             "schema": SCHEMA_VERSION, "report": REPORT_VERSION,
                             "prompt": PROMPT_VERSION, "model": MODEL_IDENTITY, "policy": POLICY_VERSION},
                "specialist_versions": {"evidence": EVIDENCE_VERSION, "schema": SPECIALIST_SCHEMA_VERSION,
                                        "policy": SPECIALIST_POLICY_VERSION},
                "event_research_versions": {
                    "schema": ADVANCED_SCHEMA_VERSION, "earnings": EARNINGS_POLICY_VERSION,
                    "claims": CLAIM_POLICY_VERSION, "valuation": VALUATION_POLICY_VERSION,
                    "risk": RISK_POLICY_VERSION,
                },
                "news_catalyst": {"descriptor": news, "schema": NEWS_SCHEMA_VERSION,
                                  "policy": NEWS_POLICY_VERSION},
                "ownership_intelligence": {"descriptor": ownership, "schema": OWNERSHIP_SCHEMA_VERSION},
                "corrections": corrections,
                "synthesis_versions": {"debate": DEBATE_SCHEMA_VERSION, "score": SCORE_POLICY_VERSION,
                                       "confidence": CONFIDENCE_POLICY_VERSION},
                "reasoning_enabled": False,
            }
            fingerprint = stable_hash(value)
            output = self._node(state["run_id"], "manifest", fingerprint, lambda: value)
            with self.store.connect() as db:
                db.execute("UPDATE update_runs SET manifest_hash=?,updated_at=? WHERE id=?", (fingerprint, now(), state["run_id"]))
            return {"manifest": output}

        def extract_node(state):
            evidence = state["manifest"]["evidence"]
            fingerprint = stable_hash({"source_sha256": evidence["sha256"], "extractor": EXTRACTOR_VERSION,
                                       "corrections": state["manifest"]["corrections"]["digest"]})
            def compute():
                source, content = self.filings.source(state["source_id"])
                facts = self.extractor(source, content)
                with self.store.connect() as db: facts, _ = apply_fact_corrections(db, facts)
                return facts
            return {"facts": self._node(state["run_id"], "extract_facts", fingerprint, compute)}

        def context_node(state):
            source, _ = self.filings.source(state["source_id"])
            descriptor = self._context_descriptor(source["symbol"])
            fingerprint = stable_hash({"symbol": source["symbol"], "context": descriptor, "policy": POLICY_VERSION})
            return {"context": self._node(state["run_id"], "research_context", fingerprint, lambda: descriptor)}

        def qualitative_node(state):
            evidence = state["manifest"]["evidence"]
            fingerprint = stable_hash({"source_sha256": evidence["sha256"], "extractor": EVIDENCE_VERSION})
            def compute():
                source, content = self.filings.source(state["source_id"])
                return validate_evidence_bundle(self.specialist_extractor(source, content))
            return {"qualitative_evidence": self._node(
                state["run_id"], "qualitative_evidence", fingerprint, compute
            )}

        def metric_node(state):
            fingerprint = stable_hash({"facts": state["facts"], "formula": FORMULA_VERSION, "schema": SCHEMA_VERSION})
            def compute():
                source, _ = self.filings.source(state["source_id"])
                return {"schema_version": SCHEMA_VERSION, "extractor_version": EXTRACTOR_VERSION,
                        "formula_version": FORMULA_VERSION,
                        "source": {key: source.get(key) for key in ("id", "symbol", "title", "sha256", "origin", "retrieved_at")},
                        "scope": "consolidated", "period": "FY2025", "facts": state["facts"],
                        "metrics": calculate_metrics(state["facts"]),
                        "limitations": ["Refresh output uses the measured consolidated statement extractor.",
                                        "A reported dash remains missing rather than being converted to zero."]}
            return {"snapshot": self._node(state["run_id"], "calculate_metrics", fingerprint, compute)}

        def specialist_node(name, builder):
            def run(state):
                bundle = state["qualitative_evidence"]
                fingerprint = stable_hash({"kind": name, "evidence": bundle,
                                           "schema": SPECIALIST_SCHEMA_VERSION,
                                           "policy": SPECIALIST_POLICY_VERSION})
                output = self._specialist_output(
                    state["run_id"], name, fingerprint, lambda: builder(bundle), bundle
                )
                return {name: output}
            return run

        def moat_node(state):
            bundle = state["qualitative_evidence"]
            inputs = [state[name]["report"] for name in ("business_quality", "industry", "competitor")]
            fingerprint = stable_hash({"kind": "moat", "inputs": [item["report_id"] for item in inputs],
                                       "schema": SPECIALIST_SCHEMA_VERSION,
                                       "policy": SPECIALIST_POLICY_VERSION})
            output = self._specialist_output(
                state["run_id"], "moat", fingerprint, lambda: build_moat(bundle, inputs), bundle
            )
            return {"moat": output}

        def earnings_node(state):
            snapshot = state["snapshot"]
            evidence_ids = {item["evidence_id"] for item in snapshot["facts"]}
            fingerprint = stable_hash({"snapshot": snapshot, "schema": ADVANCED_SCHEMA_VERSION,
                                       "policy": EARNINGS_POLICY_VERSION})
            output = self._advanced_output(state["run_id"], "earnings", fingerprint,
                                           lambda: build_earnings(snapshot), evidence_ids)
            return {"earnings": output}

        def claim_node(state):
            bundle = state["qualitative_evidence"]
            evidence_ids = {item["id"] for item in bundle["evidence"]}
            fingerprint = stable_hash({"evidence": bundle, "schema": ADVANCED_SCHEMA_VERSION,
                                       "policy": CLAIM_POLICY_VERSION})
            output = self._advanced_output(state["run_id"], "management_claims", fingerprint,
                                           lambda: build_management_claims(bundle), evidence_ids)
            return {"management_claims": output}

        def valuation_node(state):
            earnings = state["earnings"]["report"]
            evidence_ids = {item["evidence_id"] for item in state["snapshot"]["facts"]}
            fingerprint = stable_hash({"earnings": earnings["report_id"], "schema": ADVANCED_SCHEMA_VERSION,
                                       "policy": VALUATION_POLICY_VERSION})
            output = self._advanced_output(state["run_id"], "valuation", fingerprint,
                                           lambda: build_valuation(earnings), evidence_ids)
            return {"valuation": output}

        def management_node(state):
            bundle, tracker = state["qualitative_evidence"], state["management_claims"]["report"]
            evidence_ids = {item["id"] for item in bundle["evidence"]}
            fingerprint = stable_hash({"tracker": tracker["report_id"], "governance": bundle,
                                       "schema": ADVANCED_SCHEMA_VERSION, "policy": CLAIM_POLICY_VERSION})
            output = self._advanced_output(state["run_id"], "management", fingerprint,
                                           lambda: build_management(bundle, tracker), evidence_ids)
            return {"management": output}

        def news_node(state):
            source, _ = self.filings.source(state["source_id"])
            descriptor = state["manifest"]["news_catalyst"]["descriptor"]
            fingerprint = stable_hash({"descriptor": descriptor, "schema": NEWS_SCHEMA_VERSION,
                                       "policy": NEWS_POLICY_VERSION})
            def compute():
                events = current_news(self.store, source["symbol"])
                return {"schema_version": NEWS_SCHEMA_VERSION, "policy_version": NEWS_POLICY_VERSION,
                        "kind": "news_catalyst", "symbol": source["symbol"], "events": events,
                        "rating": "supported" if events else "insufficient",
                        "summary": (f"{len(events)} current event(s), including "
                                    f"{sum(1 for event in events if event['material'])} material event(s)."
                                    if events else "No current event source has been collected."),
                        "coverage": "current-events" if events else "missing-current-events",
                        "limitations": ["Historical event features require GS-12 eligibility."]}
            return {"news_catalyst": self._node(state["run_id"], "news_catalyst", fingerprint, compute)}

        def ownership_node(state):
            source, _ = self.filings.source(state["source_id"])
            descriptor = state["manifest"]["ownership_intelligence"]["descriptor"]
            fingerprint = stable_hash({"descriptor": descriptor, "schema": OWNERSHIP_SCHEMA_VERSION})
            return {"ownership_intelligence": self._node(
                state["run_id"], "ownership_intelligence", fingerprint,
                lambda: latest_ownership(self.store, source["symbol"]) or {},
            )}

        def synthesis_inputs(state):
            return {
                "financial": state["snapshot"],
                "specialists": {name: state[name]["report"] for name in
                                ("business_quality", "industry", "competitor", "moat")},
                "advanced": {name: state[name]["report"] for name in
                             ("earnings", "management_claims", "valuation", "management", "risk")},
                "ownership": state["ownership_intelligence"] or None,
                "news": state["news_catalyst"],
            }

        def risk_node(state):
            bundle, snapshot = state["qualitative_evidence"], state["snapshot"]
            earnings, valuation = state["earnings"]["report"], state["valuation"]["report"]
            evidence_ids = {item["id"] for item in bundle["evidence"]} | {
                item["evidence_id"] for item in snapshot["facts"]}
            fingerprint = stable_hash({"evidence": bundle, "metrics": snapshot["metrics"],
                                       "earnings": earnings["report_id"], "valuation": valuation["report_id"],
                                       "news_digest": state["manifest"]["news_catalyst"]["descriptor"]["digest"],
                                       "schema": ADVANCED_SCHEMA_VERSION, "policy": RISK_POLICY_VERSION})
            output = self._advanced_output(state["run_id"], "risk", fingerprint,
                lambda: build_risk(bundle, snapshot, earnings, valuation), evidence_ids)
            return {"risk": output}

        def case_node(kind):
            def run(state):
                inputs = synthesis_inputs(state)
                locked = debate_input_manifest(inputs)
                fingerprint = stable_hash({"kind": kind, "input_manifest": locked,
                                           "schema": DEBATE_SCHEMA_VERSION})
                return {kind: self._node(state["run_id"], kind, fingerprint,
                                         lambda: build_case(kind, inputs))}
            return run

        def judge_node(state):
            inputs = synthesis_inputs(state)
            fingerprint = stable_hash({"bull": state["bull"]["case_id"], "bear": state["bear"]["case_id"],
                                       "manifest": debate_input_manifest(inputs), "schema": DEBATE_SCHEMA_VERSION})
            return {"judge": self._node(state["run_id"], "judge", fingerprint,
                                         lambda: build_judge(state["bull"], state["bear"], inputs))}

        def thesis_node(state):
            fingerprint = stable_hash({"judge": state["judge"]["judge_id"],
                                       "bull": state["bull"]["case_id"], "bear": state["bear"]["case_id"],
                                       "schema": DEBATE_SCHEMA_VERSION})
            return {"investment_thesis": self._node(
                state["run_id"], "investment_thesis", fingerprint,
                lambda: build_thesis(state["judge"], state["bull"], state["bear"]),
            )}

        def score_node(state):
            inputs = synthesis_inputs(state)
            fingerprint = stable_hash({"input_manifest": debate_input_manifest(inputs),
                                       "thesis": state["investment_thesis"]["thesis_id"],
                                       "score": SCORE_POLICY_VERSION, "confidence": CONFIDENCE_POLICY_VERSION})
            return {"score_snapshot": self._node(
                state["run_id"], "score_snapshot", fingerprint,
                lambda: validate_scores(score_research(inputs), debate_evidence_ids(inputs)),
            )}

        def report_node(state):
            specialist_outputs = [state[name] for name in ("business_quality", "industry", "competitor", "moat")]
            advanced_outputs = [state[name] for name in
                                ("earnings", "management_claims", "valuation", "management", "risk")]
            fingerprint = stable_hash({"snapshot": state["snapshot"], "context": state["context"],
                                       "specialists": [item["report"]["report_id"] for item in specialist_outputs],
                                       "event_research": [item["report"]["report_id"] for item in advanced_outputs],
                                       "news_catalyst": state["news_catalyst"],
                                       "ownership": state["manifest"]["ownership_intelligence"]["descriptor"],
                                       "bull": state["bull"]["case_id"], "bear": state["bear"]["case_id"],
                                       "judge": state["judge"]["judge_id"],
                                       "thesis": state["investment_thesis"]["thesis_id"],
                                       "score": state["score_snapshot"]["score_id"],
                                       "manifest_hash": stable_hash(state["manifest"]), "report": REPORT_VERSION})
            def compute():
                source, _ = self.filings.source(state["source_id"])
                synthesis = {"bull": state["bull"], "bear": state["bear"], "judge": state["judge"],
                             "investment_thesis": state["investment_thesis"]}
                artifacts = {}
                for kind, report in synthesis.items():
                    report_id = report.get("case_id") or report.get("judge_id") or report.get("thesis_id")
                    agent_content = render_agent_note(report)
                    agent_path = f"Graph Stock/Synthesis/{source['symbol']}/{kind}-{report_id.split(':')[-1]}.md"
                    self.vault.publish(agent_path, agent_content)
                    artifacts[kind] = {"path": agent_path, "sha256": digest(agent_content), "report_id": report_id}
                score_lines = [f"# Scorecard — {source['symbol']}", "", f"Policy: `{SCORE_POLICY_VERSION}`", "",
                               f"Overall: **{state['score_snapshot']['overall_score']} / 100**",
                               f"Research confidence: **{state['score_snapshot']['research_confidence']}** "
                               f"({state['score_snapshot']['research_confidence_index']})", ""]
                for category in state["score_snapshot"]["categories"]:
                    score_lines.append(f"- **{category['name'].replace('_', ' ').title()}:** "
                                       f"{category['score'] if category['score'] is not None else 'unscored'} — "
                                       f"{category['rationale']} Evidence: `{', '.join(category['evidence_ids']) or 'missing'}`")
                score_lines += ["", state["score_snapshot"]["confidence_meaning"], ""]
                score_content = "\n".join(score_lines)
                score_path = f"Graph Stock/Synthesis/{source['symbol']}/scorecard-{state['score_snapshot']['score_id'].split(':')[-1]}.md"
                self.vault.publish(score_path, score_content)
                artifacts["scorecard"] = {"path": score_path, "sha256": digest(score_content),
                                          "report_id": state["score_snapshot"]["score_id"]}
                ownership = state["ownership_intelligence"] or None
                ownership_rows = ownership["comparison"]["comparisons"] if ownership else []
                institutional = ({"status": "available", "periods": [ownership["comparison"]["prior_period"], ownership["comparison"]["current_period"]],
                                  "observations": [{key: row[key] for key in ("holder_id", "name", "kind", "status", "reason", "share_change", "percentage_point_change")}
                                                   for row in ownership_rows]}
                                 if ownership else {"status": "unavailable", "reason": "No ownership comparison is attached."})
                missing = [key for key, value in state["score_snapshot"]["evidence_coverage"].items() if Decimal(value) < 1]
                links = []
                for output in specialist_outputs + advanced_outputs:
                    links.append({"kind": output["report"]["kind"], "path": output["note"]["path"]})
                links += [{"kind": kind, "path": item["path"]} for kind, item in artifacts.items()]
                if ownership:
                    links += [{"kind": kind, "path": item["path"]} for kind, item in ownership["reports"].items()]
                news_run = latest_news_run(self.store, source["symbol"])
                if news_run and news_run.get("report"):
                    links.append({"kind": "news_catalyst", "path": news_run["report"]["path"]})
                availability_times = [source["retrieved_at"]]
                availability_times += [event["retrieved_at"] for event in state["news_catalyst"]["events"]]
                if ownership:
                    availability_times += [item["ingested_at"] for item in ownership["sources"]]
                complete = {
                    "schema_version": "complete-research-snapshot/v1", "ticker": source["symbol"],
                    "name": source.get("security", {}).get("name") or source["title"],
                    "as_of_time": max(availability_times), "overall_score": state["score_snapshot"]["overall_score"],
                    "category_scores": state["score_snapshot"]["categories"],
                    "evidence_completeness_percent": state["score_snapshot"]["evidence_completeness_percent"],
                    "research_confidence": state["score_snapshot"]["research_confidence"],
                    "research_confidence_index": state["score_snapshot"]["research_confidence_index"],
                    "confidence_meaning": state["score_snapshot"]["confidence_meaning"],
                    "fundamental_view": state["investment_thesis"]["fundamental_view"],
                    "valuation": {"summary": state["valuation"]["report"]["summary"],
                                  "scenarios": state["valuation"]["report"]["valuation_scenarios"],
                                  "applicability": state["valuation"]["report"]["applicability"]},
                    "institutional_trend": institutional,
                    "principal_risks": state["risk"]["report"]["risks"],
                    "thesis_points": state["investment_thesis"]["thesis_points"],
                    "support_conditions": state["investment_thesis"]["support_conditions"],
                    "weaken_conditions": state["investment_thesis"]["weaken_conditions"],
                    "key_metrics": state["snapshot"]["metrics"],
                    "swing_status": {"state": "unavailable", "reason": "Daily market features start at GS-11 and GS-12."},
                    "validation_status": {"state": "pending", "confidence": "unavailable", "reason": "Backtesting and validation start after point-in-time features."},
                    "missing_evidence": missing, "refresh_status": "completed",
                    "debate": {"bull_case_id": state["bull"]["case_id"], "bear_case_id": state["bear"]["case_id"],
                               "judge_id": state["judge"]["judge_id"], "adjudication": state["judge"]["adjudication"]},
                    "full_research_links": links,
                }
                interpretation = {"status": "skipped", "message": "No reasoning was requested during this refresh."}
                content = render_note(state["snapshot"], interpretation)
                content += "\n## Refresh context\n\n" + json.dumps(state["context"], indent=2) + "\n"
                content += "\n## Specialist research\n\n"
                for output in specialist_outputs:
                    report, note = output["report"], output["note"]
                    content += f"### {report['kind'].replace('_', ' ').title()} — {report['rating']}\n\n"
                    content += report["summary"] + f"\n\nFull note: `{note['path']}`\n\n"
                content += "\n## Earnings, management, valuation and risk\n\n"
                for output in advanced_outputs:
                    report, note = output["report"], output["note"]
                    content += f"### {report['kind'].replace('_', ' ').title()} — {report['rating']}\n\n"
                    content += report["summary"] + f"\n\nFull note: `{note['path']}`\n\n"
                news = state["news_catalyst"]
                content += f"\n## News & catalysts — {news['rating']}\n\n{news['summary']}\n\n"
                for event in news["events"]:
                    content += f"- {event['event_date']}: {event['facts'][0]['text']} ({event['severity']})\n"
                content += f"\n## Independent debate\n\n{state['judge']['adjudication']}\n\n"
                content += f"Overall score: **{state['score_snapshot']['overall_score']} / 100** over a "
                content += f"{state['score_snapshot']['provisional_denominator_percent']}% provisional denominator.\n\n"
                content += f"Evidence completeness: **{state['score_snapshot']['evidence_completeness_percent']}%**; "
                content += f"research confidence: **{state['score_snapshot']['research_confidence']}**.\n\n"
                content += "Detailed synthesis notes:\n" + "\n".join(f"- {kind}: `{item['path']}`" for kind, item in artifacts.items()) + "\n"
                path = f"Graph Stock/Updates/{state['snapshot']['source']['symbol']}/{fingerprint}.md"
                self.vault.publish(path, content)
                return {"path": path, "sha256": digest(content), "report_version": REPORT_VERSION,
                        "synthesis_artifacts": artifacts, "complete_snapshot": complete}
            return {"report": self._node(state["run_id"], "publish_report", fingerprint, compute)}

        builder.add_node("manifest", manifest_node)
        builder.add_node("extract_facts", extract_node)
        builder.add_node("research_context", context_node)
        builder.add_node("qualitative_evidence", qualitative_node)
        builder.add_node("calculate_metrics", metric_node)
        builder.add_node("business_quality", specialist_node("business_quality", build_business_quality))
        builder.add_node("industry", specialist_node("industry", build_industry))
        builder.add_node("competitor", specialist_node("competitor", build_competitor))
        builder.add_node("moat", moat_node)
        builder.add_node("earnings", earnings_node)
        builder.add_node("management_claims", claim_node)
        builder.add_node("valuation", valuation_node)
        builder.add_node("management", management_node)
        builder.add_node("ownership_intelligence", ownership_node)
        builder.add_node("news_catalyst", news_node)
        builder.add_node("risk", risk_node)
        builder.add_node("bull", case_node("bull"))
        builder.add_node("bear", case_node("bear"))
        builder.add_node("judge", judge_node)
        builder.add_node("investment_thesis", thesis_node)
        builder.add_node("score_snapshot", score_node)
        builder.add_node("publish_report", report_node)
        builder.add_edge(START, "manifest")
        builder.add_edge("manifest", "extract_facts")
        builder.add_edge("manifest", "research_context")
        builder.add_edge("manifest", "qualitative_evidence")
        builder.add_edge("extract_facts", "calculate_metrics")
        builder.add_edge("qualitative_evidence", "business_quality")
        builder.add_edge("qualitative_evidence", "industry")
        builder.add_edge("qualitative_evidence", "competitor")
        builder.add_edge(["business_quality", "industry", "competitor"], "moat")
        builder.add_edge("calculate_metrics", "earnings")
        builder.add_edge("qualitative_evidence", "management_claims")
        builder.add_edge("earnings", "valuation")
        builder.add_edge("management_claims", "management")
        builder.add_edge("manifest", "ownership_intelligence")
        builder.add_edge("manifest", "news_catalyst")
        builder.add_edge(["qualitative_evidence", "earnings", "valuation", "news_catalyst"], "risk")
        debate_inputs = ["calculate_metrics", "moat", "management", "valuation", "ownership_intelligence", "news_catalyst", "risk"]
        builder.add_edge(debate_inputs, "bull")
        builder.add_edge(debate_inputs, "bear")
        builder.add_edge(["bull", "bear"], "judge")
        builder.add_edge("judge", "investment_thesis")
        builder.add_edge(["investment_thesis", "ownership_intelligence"], "score_snapshot")
        builder.add_edge(["research_context", "score_snapshot"], "publish_report")
        builder.add_edge("publish_report", END)
        return builder

    def execute(self, run_id: str):
        with self.store.connect() as db:
            changed = db.execute("UPDATE update_runs SET status='running',updated_at=?,error=NULL WHERE id=? AND status='queued'",
                                 (now(), run_id)).rowcount
            row = db.execute("SELECT * FROM update_runs WHERE id=?", (run_id,)).fetchone()
            prior_work = db.execute("SELECT COUNT(*) FROM update_nodes WHERE run_id=? AND status!='queued'", (run_id,)).fetchone()[0]
        if not changed:
            return
        connection = sqlite3.connect(self.checkpoint_path, check_same_thread=False)
        try:
            saver = SqliteSaver(connection, serde=JsonPlusSerializer(allowed_msgpack_modules=[]))
            saver.setup()
            graph = self._builder().compile(checkpointer=saver)
            config = {"configurable": {"thread_id": run_id}, "max_concurrency": self.max_concurrency}
            initial = None if prior_work else {"run_id": run_id, "source_id": row["source_id"]}
            state = graph.invoke(initial, config=config)
            specialist_outputs = [state[name] for name in ("business_quality", "industry", "competitor", "moat")]
            advanced_outputs = [state[name] for name in
                                ("earnings", "management_claims", "valuation", "management", "risk")]
            snapshot = dict(state["snapshot"])
            snapshot["specialists"] = [condensed(item["report"], item["note"]) for item in specialist_outputs]
            snapshot["event_research"] = [condensed_advanced(item["report"], item["note"])
                                          for item in advanced_outputs]
            snapshot["news_catalyst"] = state["news_catalyst"]
            snapshot["complete_research"] = state["report"]["complete_snapshot"]
            result = {"manifest": state["manifest"], "snapshot": snapshot, "context": state["context"],
                      "specialists": {item["report"]["kind"]: item for item in specialist_outputs},
                      "event_research": {item["report"]["kind"]: item for item in advanced_outputs},
                      "ownership_intelligence": state["ownership_intelligence"],
                      "news_catalyst": state["news_catalyst"],
                      "debate": {"bull": state["bull"], "bear": state["bear"], "judge": state["judge"]},
                      "investment_thesis": state["investment_thesis"],
                      "scorecard": state["score_snapshot"],
                      "complete_snapshot": state["report"]["complete_snapshot"],
                      "report": state["report"]}
            with self.store.connect() as db:
                payloads = {**result["debate"], "investment_thesis": result["investment_thesis"],
                            "scorecard": result["scorecard"]}
                for kind, artifact in state["report"]["synthesis_artifacts"].items():
                    payload = payloads[kind]
                    db.execute("""INSERT OR REPLACE INTO synthesis_reports
                        (run_id,kind,report_id,schema_version,payload,note_path,note_sha256)
                        VALUES (?,?,?,?,?,?,?)""", (run_id, kind, artifact["report_id"],
                        payload.get("schema_version", SCORE_POLICY_VERSION), json.dumps(payload, sort_keys=True),
                        artifact["path"], artifact["sha256"]))
                db.execute("UPDATE update_runs SET status='completed',updated_at=?,result=?,error=NULL WHERE id=?",
                           (now(), json.dumps(result), run_id))
        except Cancelled:
            with self.store.connect() as db:
                db.execute("UPDATE update_runs SET status='cancelled',updated_at=?,error=NULL WHERE id=?", (now(), run_id))
        except NoteConflict:
            with self.store.connect() as db:
                db.execute("UPDATE update_runs SET status='partial',updated_at=?,error=? WHERE id=?",
                           (now(), "An existing generated report differs and was preserved.", run_id))
        except Exception:
            with self.store.connect() as db:
                db.execute("UPDATE update_runs SET status='failed',updated_at=?,error=? WHERE id=?",
                           (now(), "A graph node failed. Resume retries from the durable checkpoint.", run_id))
        finally:
            connection.close()

    def resume(self, run_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM update_runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            if row["status"] in ("queued", "running", "completed"):
                return False
            db.execute("UPDATE update_runs SET status='queued',cancel_requested=0,resume_count=resume_count+1,updated_at=?,error=NULL WHERE id=?",
                       (now(), run_id))
            db.execute("UPDATE update_nodes SET status='queued',error=NULL WHERE run_id=? AND status IN ('failed','interrupted')", (run_id,))
        return True

    def cancel(self, run_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM update_runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            if row["status"] in ("completed", "cancelled"):
                return False
            if row["status"] == "queued":
                db.execute("UPDATE update_runs SET status='cancelled',cancel_requested=1,updated_at=? WHERE id=?", (now(), run_id))
            else:
                db.execute("UPDATE update_runs SET cancel_requested=1,updated_at=? WHERE id=?", (now(), run_id))
        return True

    def get(self, run_id):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM update_runs WHERE id=?", (run_id,)).fetchone()
            nodes = [dict(item) for item in db.execute("SELECT * FROM update_nodes WHERE run_id=? ORDER BY rowid", (run_id,))]
        if not row:
            raise KeyError(run_id)
        value = dict(row)
        value.pop("request_key")
        value["cancel_requested"] = bool(value["cancel_requested"])
        value["result"] = json.loads(value["result"])
        if value["result"]:
            value["result"]["management_claim_history"] = self._claim_history(value["symbol"])
        for node in nodes:
            node["output"] = json.loads(node["output"]) if node["output"] else None
        value["nodes"] = nodes
        value["message"] = {
            "queued": "Update is queued.", "running": "Dependency graph is running.",
            "completed": "Update completed with a durable manifest.",
            "failed": value["error"] or "A node failed; resume from the checkpoint.",
            "partial": value["error"] or "Partial results are available.",
            "cancelled": "Update was cancelled; completed node outputs remain reusable.",
        }.get(value["status"], "Update needs attention.")
        return value

    def recent(self):
        with self.store.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM update_runs ORDER BY created_at DESC LIMIT 30")]
        return [self.get(run_id) for run_id in ids]

    def read_report(self, run_id):
        run = self.get(run_id)
        path = run["result"].get("report", {}).get("path")
        if not path:
            raise KeyError(run_id)
        return self.vault.read(path)

    def read_specialist(self, run_id, kind):
        if kind not in ("business_quality", "industry", "competitor", "moat"):
            raise KeyError(kind)
        run = self.get(run_id)
        path = run["result"].get("specialists", {}).get(kind, {}).get("note", {}).get("path")
        if not path:
            raise KeyError(kind)
        return self.vault.read(path)

    def read_event_research(self, run_id, kind):
        if kind not in ("earnings", "management_claims", "valuation", "management", "risk"):
            raise KeyError(kind)
        run = self.get(run_id)
        path = run["result"].get("event_research", {}).get(kind, {}).get("note", {}).get("path")
        if not path:
            raise KeyError(kind)
        return self.vault.read(path)

    def read_synthesis(self, run_id, kind):
        if kind not in ("bull", "bear", "judge", "investment_thesis", "scorecard"):
            raise KeyError(kind)
        run = self.get(run_id)
        path = run["result"].get("report", {}).get("synthesis_artifacts", {}).get(kind, {}).get("path")
        if not path:
            raise KeyError(kind)
        return self.vault.read(path)
