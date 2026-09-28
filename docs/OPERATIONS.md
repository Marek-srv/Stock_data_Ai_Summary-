# graph_stock V1 operations

This guide covers the local V1 handoff. The application serves one user on localhost and stores its research in SQLite plus a chosen Obsidian-compatible folder. It has no broker connection or order-submission path.

## Supported local runtime

The verified environment is macOS with Python 3.10, Node.js 24.19.0, pnpm 11.19.0 and Codex CLI 0.153.4. Python packages are pinned in `requirements.lock`; React and Vite versions are pinned in `frontend/pnpm-lock.yaml`. The implementation also targets Linux where its POSIX process, file-lock and directory operations are available.

## Install and build

From the project root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
```

The frontend must be rebuilt after editing `frontend/src/`. Dependency installation needs normal access to the configured Python and pnpm package registries.

## Choose state and vault folders

The defaults are `.state` for SQLite/runtime state and `.state/fixture-vault` for Markdown/PDF artifacts. To use a dedicated Obsidian folder, set values before startup:

```sh
export GRAPH_STOCK_STATE_DIR="$PWD/.state"
export GRAPH_STOCK_VAULT="$HOME/Documents/graph-stock-vault"
```

Open `GRAPH_STOCK_VAULT` as a vault in Obsidian if desired. The application creates its own `Graph Stock/` subtree. It never discovers or changes another vault automatically. A record keeps its original vault destination, so moving a configured vault does not rewrite older database references.

## Authentication

Deterministic research, calculation, validation, paper accounting, scheduling and recovery do not need an OpenAI API key. The optional connection diagnostic and optional financial interpretation use the installed Codex client with ChatGPT sign-in:

```sh
codex login status
```

If signed out, run `codex login` and choose ChatGPT. If the executable is outside `PATH`, set `GRAPH_STOCK_CODEX` to its absolute path. Authentication expiry is shown separately from usage, connectivity, timeout and invalid-output failures. Retry explicitly after restoring sign-in; do not add an API key to application configuration.

## Start and stop

Build the frontend, then start one process for a state directory:

```sh
.venv/bin/python -m uvicorn graph_stock.app:app --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/`. Stop cleanly with Ctrl+C in that terminal. Startup recovers interrupted jobs, reconciles paper ledgers and coalesces due scheduled work. A file lock rejects a second process using the same state directory.

Keep the server bound to localhost. V1 has no remote-user authentication and must not be exposed on a public interface. Scheduled jobs run only while this process and the laptop are awake; wake/restart performs the defined catch-up.

## Optional macOS login startup

The normal manual start remains the default. On macOS, stop the manually running server and opt in with:

```sh
.venv/bin/python -m graph_stock.startup install
```

This writes `~/Library/LaunchAgents/com.graphstock.local.plist`, loads it with the current user's `launchd` domain and starts the same localhost FastAPI process. The definition fixes the working directory, virtual-environment Python, localhost address, port 8765, `.state` database and `.state/fixture-vault`. It contains no API key, ChatGPT token or other credential. Use the default folders when enabling this integration; custom manual environment overrides are not copied into the startup file.

Check service state and local log locations with:

```sh
.venv/bin/python -m graph_stock.startup status
```

The scheduler panel also shows whether a valid startup definition exists and whether the current process says it was launched by macOS. Startup stdout and errors are saved under `.state/startup/`. If launch fails, inspect `stderr.log`, run the status command, remove the integration, then use the manual start command while correcting the issue.

Disable and remove login startup with:

```sh
.venv/bin/python -m graph_stock.startup uninstall
```

Install and removal are idempotent. Removal only deletes the expected `com.graphstock.local` definition and refuses an unreadable, symbolic-link or foreign-labelled file. Restart opens the existing SQLite state; the scheduler's leases, unique due keys and recovery pass prevent duplicate scheduled work. A sleeping or powered-off Mac executes nothing. On wake, login or process restart, the existing persisted catch-up coalesces missed due work according to GS-18.

## Routine use

1. Collect the supported BEL public filing or import another company PDF with explicit identity/date limitations.
2. Calculate financials locally, then run the dependency-aware research refresh.
3. Add ownership, event and market evidence when supported; inspect missing or partial coverage rather than treating it as zero.
4. Build a point-in-time snapshot before a historical decision time.
5. Run backtesting and bounded validation. Only an all-gates-passed frozen candidate can enter a paper book.
6. Inspect alerts, scheduled jobs, corrections and proposal history in the dashboard.

Paper books are simulations. They create database ledger events only. There is no broker adapter, credential field, live order endpoint or order submission operation.

## Backup and restore rehearsal

Use **Create verified backup** in the Corrections & Recovery panel. The ZIP contains online SQLite snapshots, every vault artifact referenced by the frozen database and a SHA-256 manifest. Download it and store it separately from the working state directory.

Use **Rehearse restore** to extract and verify a backup in a new `.state/restores/<id>/` folder. This does not replace the running database. To recover manually after a failure:

1. Stop the server.
2. Preserve the damaged state directory for diagnosis.
3. Verify/rehearse the selected backup.
4. Copy the verified database and vault tree into newly chosen state/vault locations.
5. Start the server against those new locations and inspect reconciliation status before any paper processing.

Do not overwrite a live state directory while its server is running.

## Source and product limits

- V1 is NSE-only. Automatic filing coverage is the measured BEL 2024–25 annual-report sample; other tickers rely on manual PDF import.
- Financial extraction supports the measured BEL-style consolidated annual statements. Unsupported layouts remain stored with a visible coverage gap.
- Current automatic market coverage is a first-party NSE current-session row plus recent corporate actions. Historical bars used for PIT, validation and paper demonstrations are clearly labelled imported fixtures.
- Ownership history uses measured BEL annual-report rows for March 2024 and March 2025. Named-holder and pledge coverage is incomplete.
- News coverage is bounded and not a comprehensive feed. Scheduling cannot run while the device sleeps.
- Strategy validation is single-security and deliberately bounded. Successful fixture tests do not show profitability, forecast skill or NSE-wide performance.
- The upstream-improvement workflow journals candidates and approval evidence; it never fetches and applies source code automatically.
- V1 provides no broker execution, live order routing, tax accounting, multi-user access or cloud deployment. Optional login startup is macOS-only and remains disabled until explicitly installed.

## Verify a release

Run the offline tests and frontend build, then generate a fresh read-only acceptance manifest from a consistent SQLite snapshot:

```sh
.venv/bin/python -m pytest -q
cd frontend && pnpm build && cd ..
.venv/bin/python scripts/gs22_release_audit.py \
  --python-tests "<passed count>" \
  --frontend-build "passed; 16 modules"
```

The script writes `docs/GS-22-release-manifest.json`, verifies the stored BEL source hash and vault references, records live-versus-fixture classifications, inventories the S15 scenarios and fails if required evidence is missing.
