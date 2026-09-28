# GS-24 verification — optional macOS login startup

Completed 11 September 2026. Login startup remains opt-in and was not enabled in the user's account during implementation.

## Host integration

- `python -m graph_stock.startup install` writes and loads a user LaunchAgent named `com.graphstock.local` using the project's virtual-environment Python, fixed localhost binding and existing default state/vault folders.
- `status` reports platform support, saved-definition validity, loaded state, current process origin and stdout/stderr locations.
- `uninstall` unloads and removes the definition. Repeated install and removal are safe, while symbolic links, unreadable definitions and foreign labels are refused.
- The generated plist contains only paths and non-secret application settings. Process environment credentials and custom Codex configuration are not copied.

## Persistence and recovery

- The launched process uses the existing `.state/graph_stock.sqlite3`; no startup-specific scheduler database is created.
- Existing GS-18 recovery resets interrupted leases, preserves unique `(job_id, scheduled_for)` runs and performs one coalesced restart catch-up.
- Launch failures write to `.state/startup/stderr.log`. The dashboard and `GET /api/v1/startup` expose configuration and recovery information while the app is running.
- The UI and operations guide state that no work executes while the Mac is asleep or powered off.

## Verification

- Focused startup and scheduler tests cover definition contents, credential exclusion, repeat install, forced restart command, status, repeat removal, unsupported platforms, foreign-file protection, API visibility and persisted scheduler deduplication.
- The generated definition passes the host macOS plist validator.
- Frontend production build passed with Vite 8.2.2 and 17 transformed modules.
- Full Python regression suite: **146 passed** with one existing Starlette/AnyIO alias deprecation warning.

The test harness uses an isolated temporary home and a recorded `launchctl` runner. It verifies host-specific commands and filesystem behavior without changing the user's actual `~/Library/LaunchAgents` configuration.
