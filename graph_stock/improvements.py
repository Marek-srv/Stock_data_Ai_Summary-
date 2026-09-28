"""Auditable upstream-improvement proposals; this module never applies source changes."""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from .vault import Vault, digest

SCHEMA_VERSION = "improvement-proposal/v1"
POLICY_VERSION = "bounded-github-review/v1"
STATES = ("discovered", "assessed", "sandbox-tested", "awaiting-approval",
          "approved", "rejected", "integrated", "superseded")


def now():
    return datetime.now(timezone.utc).isoformat()


class ImprovementError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def _canonical_url(value):
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        raise ImprovementError("invalid", "Repository links must be HTTPS github.com URLs.")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2 or any(part in (".", "..") for part in parts):
        raise ImprovementError("invalid", "Use a GitHub repository root URL.")
    return f"https://github.com/{parts[0]}/{parts[1].removesuffix('.git')}"


def _fingerprint(repo_url, revision, change_sha256):
    payload = json.dumps({"repository_url": repo_url, "revision": revision.lower(),
                          "change_sha256": change_sha256.lower()}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


class ImprovementService:
    def __init__(self, store, vault_dir, tester=None):
        self.store, self.vault = store, Vault(vault_dir)
        self.tester = tester or self._unconfigured_test
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS improvement_config (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), policy_version TEXT NOT NULL,
                    whitelist TEXT NOT NULL, discovery_limit INTEGER NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS improvement_proposals (
                    id TEXT PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, repository_url TEXT NOT NULL,
                    revision TEXT NOT NULL, release TEXT, license TEXT NOT NULL, relevance TEXT NOT NULL,
                    change_summary TEXT NOT NULL, compatibility TEXT NOT NULL, expected_benefit TEXT NOT NULL,
                    source_links TEXT NOT NULL, source_kind TEXT NOT NULL, change_sha256 TEXT NOT NULL,
                    fingerprint TEXT UNIQUE NOT NULL, state TEXT NOT NULL, supersedes_id TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, note_path TEXT, note_sha256 TEXT
                );
                CREATE TABLE IF NOT EXISTS improvement_tests (
                    id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    profile TEXT NOT NULL, passed INTEGER NOT NULL, summary TEXT NOT NULL,
                    evidence TEXT NOT NULL, tested_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS improvement_decisions (
                    id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    decision TEXT NOT NULL, reason TEXT NOT NULL, decided_at TEXT NOT NULL,
                    invalidated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS improvement_audit (
                    id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, action TEXT NOT NULL,
                    details TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
            db.execute("""INSERT OR IGNORE INTO improvement_config
                VALUES (1,?,?,?,?)""", (POLICY_VERSION, json.dumps([]), 5, now()))

    @staticmethod
    def _unconfigured_test(proposal, profile):
        return {"passed": False, "summary": "No isolated test adapter is configured.",
                "evidence": {"profile": profile, "isolated": True, "network": "disabled"}}

    def config(self):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM improvement_config WHERE singleton=1").fetchone()
        result = dict(row); result["whitelist"] = json.loads(result["whitelist"])
        return result

    def configure(self, whitelist, discovery_limit):
        urls = sorted({_canonical_url(item) for item in whitelist})
        if len(urls) > 25 or not 1 <= discovery_limit <= 10:
            raise ImprovementError("invalid", "Use at most 25 repositories and a discovery limit from 1 to 10.")
        with self.store.connect() as db:
            db.execute("UPDATE improvement_config SET whitelist=?, discovery_limit=?, updated_at=? WHERE singleton=1",
                       (json.dumps(urls), discovery_limit, now()))
        return self.config()

    def monitor(self, candidates):
        config = self.config()
        if len(candidates) > config["discovery_limit"]:
            raise ImprovementError("bounded", "Candidate batch exceeds the configured discovery limit.")
        outcomes = []
        for item in candidates:
            repo = _canonical_url(item["repository_url"])
            source_kind = "whitelist" if repo in config["whitelist"] else "discovered"
            outcomes.append(self.propose({**item, "repository_url": repo, "source_kind": source_kind}))
        return {"policy_version": POLICY_VERSION, "checked": len(candidates), "proposals": outcomes}

    def propose(self, item):
        repo = _canonical_url(item["repository_url"])
        revision, change_hash = item["revision"].lower(), item["change_sha256"].lower()
        if not (7 <= len(revision) <= 64 and all(c in "0123456789abcdef" for c in revision)):
            raise ImprovementError("invalid", "Revision must be a 7–64 character hexadecimal commit ID.")
        if len(change_hash) != 64 or any(c not in "0123456789abcdef" for c in change_hash):
            raise ImprovementError("invalid", "Change SHA-256 must be exactly 64 hexadecimal characters.")
        links = sorted({_canonical_source_link(link) for link in item["source_links"]})
        fingerprint = _fingerprint(repo, revision, change_hash)
        event_key = f"{repo}@{revision}:{change_hash}"
        timestamp = now()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT id FROM improvement_proposals WHERE event_key=?", (event_key,)).fetchone()
            if existing:
                return {"proposal": self.get(existing["id"]), "created": False}
            previous = db.execute("""SELECT id FROM improvement_proposals
                WHERE repository_url=? AND revision=? ORDER BY created_at DESC LIMIT 1""", (repo, revision)).fetchone()
            proposal_id = str(uuid.uuid4())
            db.execute("""INSERT INTO improvement_proposals VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (proposal_id, event_key, repo, revision, item.get("release"), item["license"], item["relevance"],
                 item["change_summary"], item["compatibility"], item["expected_benefit"], json.dumps(links),
                 item.get("source_kind", "discovered"), change_hash, fingerprint, "discovered",
                 previous["id"] if previous else None, timestamp, timestamp, None, None))
            if previous:
                db.execute("UPDATE improvement_decisions SET invalidated_at=? WHERE proposal_id=? AND invalidated_at IS NULL",
                           (timestamp, previous["id"]))
                db.execute("UPDATE improvement_proposals SET state='superseded', updated_at=? WHERE id=?",
                           (timestamp, previous["id"]))
                self._audit(db, previous["id"], "approval-invalidated", {"replacement_id": proposal_id})
            self._audit(db, proposal_id, "discovered", {"event_key": event_key})
        self._publish(proposal_id)
        return {"proposal": self.get(proposal_id), "created": True}

    def assess(self, proposal_id):
        proposal = self.get(proposal_id)
        if proposal["state"] != "discovered":
            raise ImprovementError("conflict", "Only a discovered proposal can be assessed.")
        self._transition(proposal_id, "assessed", "assessed", {"license": proposal["license"]})
        return self.get(proposal_id)

    def test(self, proposal_id, profile):
        proposal = self.get(proposal_id)
        if proposal["state"] != "assessed":
            raise ImprovementError("conflict", "Assess the proposal before isolated testing.")
        outcome = self.tester(proposal, profile)
        passed, timestamp, test_id = bool(outcome["passed"]), now(), str(uuid.uuid4())
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO improvement_tests VALUES (?,?,?,?,?,?,?,?)",
                       (test_id, proposal_id, proposal["fingerprint"], profile, int(passed), outcome["summary"],
                        json.dumps(outcome.get("evidence", {}), sort_keys=True), timestamp))
            state = "awaiting-approval" if passed else "sandbox-tested"
            db.execute("UPDATE improvement_proposals SET state=?, updated_at=? WHERE id=?", (state, timestamp, proposal_id))
            self._audit(db, proposal_id, "sandbox-test-passed" if passed else "sandbox-test-failed",
                        {"test_id": test_id, "fingerprint": proposal["fingerprint"]})
        self._publish(proposal_id)
        return self.get(proposal_id)

    def decide(self, proposal_id, fingerprint, decision, reason):
        proposal = self.get(proposal_id)
        if proposal["state"] != "awaiting-approval":
            raise ImprovementError("conflict", "Only a tested proposal awaiting approval can be decided.")
        if fingerprint != proposal["fingerprint"]:
            raise ImprovementError("changed", "Approval fingerprint does not match the exact tested change.")
        timestamp, decision_id = now(), str(uuid.uuid4())
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO improvement_decisions VALUES (?,?,?,?,?,?,NULL)",
                       (decision_id, proposal_id, fingerprint, decision, reason, timestamp))
            db.execute("UPDATE improvement_proposals SET state=?, updated_at=? WHERE id=?",
                       ("approved" if decision == "approved" else "rejected", timestamp, proposal_id))
            self._audit(db, proposal_id, decision, {"decision_id": decision_id, "fingerprint": fingerprint})
        self._publish(proposal_id)
        return self.get(proposal_id)

    def mark_integrated(self, proposal_id, fingerprint):
        proposal = self.get(proposal_id)
        if proposal["state"] != "approved" or fingerprint != proposal["fingerprint"]:
            raise ImprovementError("unapproved", "Integration is blocked without approval for the exact tested change.")
        with self.store.connect() as db:
            decision = db.execute("""SELECT 1 FROM improvement_decisions WHERE proposal_id=? AND fingerprint=?
                AND decision='approved' AND invalidated_at IS NULL""", (proposal_id, fingerprint)).fetchone()
            tested = db.execute("""SELECT 1 FROM improvement_tests WHERE proposal_id=? AND fingerprint=? AND passed=1""",
                                (proposal_id, fingerprint)).fetchone()
        if not decision or not tested:
            raise ImprovementError("unapproved", "Integration is blocked without matching approval and test evidence.")
        # This is an audit acknowledgement only. There is deliberately no filesystem/code application path here.
        self._transition(proposal_id, "integrated", "integration-recorded", {"fingerprint": fingerprint})
        return self.get(proposal_id)

    def recent(self):
        with self.store.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM improvement_proposals ORDER BY created_at DESC LIMIT 50")]
        return [self.get(item) for item in ids]

    def get(self, proposal_id):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM improvement_proposals WHERE id=?", (proposal_id,)).fetchone()
            if not row:
                raise ImprovementError("not-found", "Improvement proposal not found.")
            result = dict(row)
            result["source_links"] = json.loads(result["source_links"])
            result["tests"] = [self._test_row(item) for item in db.execute(
                "SELECT * FROM improvement_tests WHERE proposal_id=? ORDER BY tested_at", (proposal_id,))]
            result["decisions"] = [dict(item) for item in db.execute(
                "SELECT * FROM improvement_decisions WHERE proposal_id=? ORDER BY decided_at", (proposal_id,))]
            result["audit"] = [{**dict(item), "details": json.loads(item["details"])} for item in db.execute(
                "SELECT * FROM improvement_audit WHERE proposal_id=? ORDER BY created_at", (proposal_id,))]
        return result

    @staticmethod
    def _test_row(row):
        value = dict(row); value["passed"] = bool(value["passed"]); value["evidence"] = json.loads(value["evidence"])
        return value

    def read_report(self, proposal_id):
        proposal = self.get(proposal_id)
        if not proposal["note_path"]:
            raise ImprovementError("not-found", "Proposal report is unavailable.")
        return self.vault.read(proposal["note_path"])

    def _transition(self, proposal_id, state, action, details):
        if state not in STATES:
            raise ValueError(state)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE improvement_proposals SET state=?, updated_at=? WHERE id=?", (state, now(), proposal_id))
            self._audit(db, proposal_id, action, details)
        self._publish(proposal_id)

    @staticmethod
    def _audit(db, proposal_id, action, details):
        db.execute("INSERT INTO improvement_audit VALUES (?,?,?,?,?)",
                   (str(uuid.uuid4()), proposal_id, action, json.dumps(details, sort_keys=True), now()))

    def _publish(self, proposal_id):
        proposal = self.get(proposal_id)
        event_id = proposal["audit"][-1]["id"]
        path = f"Graph Stock/Improvements/{proposal_id}/{event_id}.md"
        tests = "\n".join(f"- `{item['profile']}`: {'passed' if item['passed'] else 'failed'} — {item['summary']}"
                          for item in proposal["tests"]) or "- Not tested"
        decisions = "\n".join(f"- {item['decision']} at {item['decided_at']} — {item['reason']}"
                              + (" (invalidated)" if item["invalidated_at"] else "") for item in proposal["decisions"]) or "- None"
        content = f"""# Upstream improvement proposal\n\n- State: **{proposal['state']}**\n- Repository: {proposal['repository_url']}\n- Revision: `{proposal['revision']}`\n- Change SHA-256: `{proposal['change_sha256']}`\n- Exact fingerprint: `{proposal['fingerprint']}`\n- License: {proposal['license']}\n- Source kind: {proposal['source_kind']}\n- Policy: `{POLICY_VERSION}`\n- Schema: `{SCHEMA_VERSION}`\n\n## Relevance\n\n{proposal['relevance']}\n\n## Change\n\n{proposal['change_summary']}\n\n## Compatibility\n\n{proposal['compatibility']}\n\n## Expected benefit\n\n{proposal['expected_benefit']}\n\n## Source links\n\n""" + "\n".join(f"- {link}" for link in proposal["source_links"]) + f"\n\n## Isolated test evidence\n\n{tests}\n\n## Decisions\n\n{decisions}\n\nNo upstream code is applied by this report workflow.\n"
        self.vault.publish(path, content)
        with self.store.connect() as db:
            db.execute("UPDATE improvement_proposals SET note_path=?, note_sha256=? WHERE id=?",
                       (path, digest(content), proposal_id))


def _canonical_source_link(value):
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        raise ImprovementError("invalid", "Source links must be HTTPS github.com URLs.")
    return value.strip()
