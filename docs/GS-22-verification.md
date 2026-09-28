# GS-22 verification — V1 release acceptance and handoff

Completed 11 September 2026. V1 acceptance used saved public-source evidence and deterministic offline fixtures; no model call was made.

## Public-source path

- The preserved NSE-hosted BEL 2024–25 integrated annual report passed its saved SHA-256 check.
- Real-source financial extraction retains 22 located facts, six deterministic metrics, fiscal scope/units and PDF page evidence.
- Complete run `814bc3b5-5fba-469c-945f-7619c4a7fa96` retains four base specialists, five event/management specialists, Bull, Bear, Judge, Investment Thesis, scorecard and institutional history.
- GS-22 incremental run `d66d4b12-af1f-44c0-ae65-8ef80828ab9a` completed with manifest `7421fe8c8950674f276af1462fe2fe29c34d257b5d6aa4669642f824349306df`. Fourteen of 22 nodes reused accepted work; a changed ownership descriptor reran ownership and dependent synthesis/publication only.
- A current first-party NSE market run remains correctly `partial`, since current-session coverage cannot support historical strategy validation.

## Honest strategy boundary

- PIT timing, action adjustments, ambiguous-bar handling and hand-worked ledgers are covered by golden fixtures.
- The retained insufficient validation remains rejected. The passing validation and independent paper book are labelled mechanics fixtures.
- Combined-book behavior is demonstrated by the hermetic two-member fixture, including attribution, shared cash and exit-first conflict handling.
- No live-data candidate was forced through promotion. No V1 API route submits broker orders.

## Acceptance and recovery

- `scripts/gs22_release_audit.py` takes a consistent read-only SQLite snapshot and writes `docs/GS-22-release-manifest.json`.
- All ten S15 scenario groups passed. Two consecutive runs against the same saved state produced the same manifest SHA-256: `29cf2c493fa911a53a8adc2de3318fa341d98680a89e74f538d1649ffe653c0a`.
- The audit verified the real filing content hash, all 100 referenced vault artifacts, the saved verified-backup record and an empty broker/order-submission route inventory.
- The production dashboard loaded from the running FastAPI service in the in-app browser. The source history and upstream-review controls rendered successfully.
- Install, build, start/stop, vault selection, authentication recovery, backup/restore, coverage and known limits are documented in `docs/OPERATIONS.md`.

## Final checks

- Python: **138 passed** with one existing Starlette/AnyIO alias deprecation warning.
- Frontend: production build passed with Vite 8.2.2 and 16 transformed modules.
- Local dashboard: running on `http://127.0.0.1:8765/`.

Successful release checks verify V1 behavior and reconstruction controls. They do not claim investment profitability, NSE-wide strategy validity or unattended operation while the device sleeps.
