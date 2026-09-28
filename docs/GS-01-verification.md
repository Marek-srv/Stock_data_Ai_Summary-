# GS-01 verification

Completed 6 September 2026 (Asia/Kolkata). This is a connection proof using synthetic data, not a stock-research result.

## Live evidence

- Installed client: Codex CLI 0.153.4.
- Authentication: CLI reported ChatGPT sign-in. The application subprocess received no OpenAI/Codex API-key environment variables and required ChatGPT authentication.
- A direct adapter smoke run completed successfully. A second check launched from the local browser page exercised UI → FastAPI → signed-in Codex → schema validation → SQLite → UI.
- Browser-triggered run: `8bf7c32f-4c28-4a37-8ebb-b3cac13784dd`.
- Saved status: completed, one attempt, four client events.
- Response: evidence `fixture-001`, direction `increased`, precomputed growth `20%`, summary “Synthetic revenue increased from 100 to 120, a 20% increase.”
- Client-reported usage for the browser check: 14,889 input tokens and 49 output tokens. Client/system context contributes substantial overhead even for a small evidence sample; this proof does not establish cost efficiency for the future agent graph.
- The browser visibly showed “Connection verified” and the validated response. Layout was visually inspected.
- Machine-readable, redacted application result: [GS-01-live-result.json](GS-01-live-result.json).

The initial attempt inside the outer workspace sandbox could not initialize the client. Running the authorized local process outside that outer restriction succeeded. The Codex child itself still used read-only permissions. This condition now maps to a distinct `client-blocked` message; no sandbox bypass flag is part of the application.

## Automated checks

Command: `.venv/bin/python -m pytest -q`

Result: **34 passed**. Two upstream Starlette/AnyIO test-client deprecation warnings remain visible; no failing tests.

Coverage includes:

- Valid structured response, progress separation and allowed usage-counter filtering.
- Absent/expired/wrong authentication, runtime auth rejection, usage limit, connectivity failure, timeout and sandbox startup block.
- Invalid JSON, incomplete event streams, unexpected tool events, fabricated evidence IDs, wrong growth values and extra fields.
- API-key/environment-secret exclusion and temporary workspace cleanup.
- Actual subprocess timeout termination and bounded stdout capture.
- Stable request identity, duplicate submission, immutable successful result and retry attempt history.
- One-at-a-time execution and bounded queue capacity.
- Restart recovery, single-server ownership, fixed request contract, localhost Host validation and cross-origin write rejection.

## Implementation boundaries

This ticket supplies the FastAPI diagnostic page, CLI adapter, SQLite run journal, tests and startup documentation. The page is a small temporary server-served UI; GS-02 adds the frozen React/Vite research dashboard. There are no real research agents, LangGraph execution, live market providers or broker connections yet.

Usage/auth failures were exercised with controlled transport fixtures rather than intentionally exhausting the account or changing its credentials. Successful live account-backed execution was tested separately. Check retries can spend additional reasoning allowance; there is no automatic retry loop. An interrupted external request cannot be resumed by the application mid-generation; the same application run ID is retried with a new attempt, and only one result can be accepted.

No model version was pinned: this isolated diagnostic uses the installed client's default model with user configuration excluded. Model/prompt fingerprints and the full agent execution graph belong to later tickets. The saved result contains no account identifier, credential, raw client log or private reasoning text.

## Sources

The adapter follows the documented [Codex non-interactive workflow](https://learn.chatgpt.com/docs/non-interactive-mode) and [ChatGPT authentication](https://learn.chatgpt.com/docs/auth). Actual flags and authentication status were additionally checked against the installed CLI's help and status output.
