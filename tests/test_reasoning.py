import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from graph_stock.reasoning import CodexDiagnostic, ProcessResult, run_process


GOOD = {"evidence_id": "fixture-001", "direction": "increased", "growth_display": "20%", "summary": "Synthetic revenue increased by 20%."}


def events(result=GOOD):
    return "\n".join(json.dumps(e) for e in [
        {"type": "thread.started", "thread_id": "test-thread"},
        {"type": "item.completed", "item": {"type": "reasoning", "text": "private progress"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(result)}},
        {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20, "secret": "never store"}},
    ])


class FakeRunner:
    def __init__(self, response=None, auth="Logged in using ChatGPT", error=None):
        self.response = response or ProcessResult(0, events(), "")
        self.auth, self.error, self.calls = auth, error, []

    async def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if "--version" in argv:
            return ProcessResult(0, "codex-cli 0.153.4", "")
        if "login" in argv:
            return ProcessResult(0, "", self.auth)
        if self.error:
            raise self.error
        return self.response


def test_validates_fixed_evidence_and_separates_progress(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-api-key")
    monkeypatch.setenv("CODEX_API_KEY", "another-secret")
    monkeypatch.setenv("PRIVATE_PASSWORD", "do-not-pass")
    runner = FakeRunner()
    result = asyncio.run(CodexDiagnostic(runner=runner).run())
    assert result.status == "completed"
    assert result.result == GOOD
    assert result.usage == {"input_tokens": 100, "output_tokens": 20}
    assert result.version == "0.153.4" and result.auth_method == "chatgpt"
    argv, options = runner.calls[-1]
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert '--ignore-user-config' in argv and '--ephemeral' in argv
    assert 'forced_login_method="chatgpt"' in argv
    assert argv[-1] == "-" and "fixture-001" in options["stdin"]
    assert not any(k in options["env"] for k in ("OPENAI_API_KEY", "CODEX_API_KEY", "PRIVATE_PASSWORD"))
    assert not options["cwd"].exists()  # Temporary evidence/schema cleaned up.


@pytest.mark.parametrize("auth", ["Not logged in", "Logged in using an API key", "Token expired"])
def test_missing_or_wrong_auth_never_invokes_reasoning(auth):
    runner = FakeRunner(auth=auth)
    result = asyncio.run(CodexDiagnostic(runner=runner).run())
    assert result.status == "waiting-for-auth"
    assert len(runner.calls) == 2


@pytest.mark.parametrize("error,status", [
    ("401 unauthorized: token expired secret", "waiting-for-auth"),
    ("429 usage limit reached secret", "rate-limited"),
    ("error sending request: network failed", "connection-error"),
    ("unspecified failure", "failed"),
    ("failed to initialize in-process app-server client: Operation not permitted", "client-blocked"),
])
def test_safe_failure_mapping(error, status):
    result = asyncio.run(CodexDiagnostic(runner=FakeRunner(ProcessResult(1, "", error))).run())
    assert result.status == status
    assert "secret" not in repr(result)


@pytest.mark.parametrize("payload", [
    {**GOOD, "growth_display": "90%"},
    {**GOOD, "evidence_id": "invented-source"},
    {**GOOD, "extra": True},
    {**GOOD, "summary": ""},
])
def test_rejects_invalid_schema_or_evidence(payload):
    result = asyncio.run(CodexDiagnostic(runner=FakeRunner(ProcessResult(0, events(payload), ""))).run())
    assert result.status == "invalid-output" and result.result is None


@pytest.mark.parametrize("stdout", ["not json", "{}", "[]", "", '{"type":"turn.completed"}',
    '{"type":"item.completed","item":{"type":"command_execution","command":"echo bad"}}'])
def test_incomplete_or_unexpected_events_are_not_success(stdout):
    result = asyncio.run(CodexDiagnostic(runner=FakeRunner(ProcessResult(0, stdout, ""))).run())
    assert result.status == "invalid-output"


def test_zero_exit_failure_event_is_not_success():
    response = ProcessResult(0, json.dumps({"type": "turn.failed", "error": {"message": "usage limit reached"}}), "")
    assert asyncio.run(CodexDiagnostic(runner=FakeRunner(response)).run()).status == "rate-limited"


@pytest.mark.parametrize("error,status", [(asyncio.TimeoutError(), "timed-out"), (FileNotFoundError(), "client-unavailable")])
def test_client_exceptions(error, status):
    assert asyncio.run(CodexDiagnostic(runner=FakeRunner(error=error)).run()).status == status


def test_real_subprocess_timeout_kills_child(tmp_path):
    pid_file = tmp_path / "pid"
    script = "import os,time,pathlib; pathlib.Path('pid').write_text(str(os.getpid())); time.sleep(30)"
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(run_process([sys.executable, "-c", script], cwd=tmp_path, env=dict(os.environ), timeout=.2))
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_real_subprocess_output_is_bounded(tmp_path):
    with pytest.raises(ValueError, match="output limit"):
        asyncio.run(run_process([sys.executable, "-c", "print('x' * 1100000)"], cwd=tmp_path, env=dict(os.environ), timeout=5))
