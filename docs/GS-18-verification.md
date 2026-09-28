# GS-18 verification — persisted local scheduling

GS-18 keeps tracked research and paper books current while the local application process is running. It does not install an OS startup service and cannot execute while the laptop sleeps.

## Persisted schedules and pipeline

- Policy `local-persisted-scheduler/v1` registers daily market, news and material jobs; a monthly mutual-fund job; and quarterly results and shareholding jobs for each tracked symbol.
- SQLite stores each definition, Asia/Kolkata timezone, next due instant, attempt count, lease, last attempt/success, wait reason and immutable run history.
- Daily boundaries are 18:30, 19:00 and 19:15 IST. Monthly MF polling starts on day 10 at 10:00 IST. Quarterly results and shareholding polling starts in January/April/July/October on days 15 and 21 at 10:00 IST.
- Manual “Run now” requests use the same runner and retain idempotency by request key.
- Material, monthly and quarterly jobs first invoke filing acquisition to check for an actual disclosure. Missing releases become `waiting-for-source` and retry in six hours.
- Daily market success invokes GS-17 chronological catch-up for active independent and combined paper books.

## Leases, recovery and wait states

- An atomic 30-minute SQLite lease prevents the same job from overlapping. A concurrent attempt reports `coalesced`.
- Startup changes interrupted attempts to durable failed history, clears their abandoned lease, moves next due to startup time and runs one coalesced restart attempt.
- Successful jobs advance directly to their next cadence boundary rather than replaying every missed polling interval.
- Waiting states remain distinct: `waiting-for-auth`, `rate-limited`, `waiting-for-source`, `offline`, `partial` and `failed`.
- Each due job completes or enters its own retry state before the due loop continues, so reasoning/auth failure cannot stop deterministic market or accounting jobs.

## Golden checks

- Fake-clock assertions cover a January month boundary and the next quarterly April boundaries in Asia/Kolkata.
- An interrupted quarterly run restarts once, preserves the failed attempt and advances to its next cadence; a nested attempt is coalesced under the lease.
- Six simultaneously due jobs produce completed, auth-wait, rate-limited, offline and source-wait outcomes without stopping the successful market job.
- The public API syncs six definitions from a newly added watchlist symbol, runs one immediately and returns the same run for a repeated request key.
- A pipeline fixture verifies quarterly disclosure polling before deterministic financial extraction and verifies that daily market processing invokes both independent and combined catch-up.

## Checks

- Focused scheduler suite: 5 tests passed.
- Related scheduler/app/research/paper suite: 36 tests passed before final integration.
- Full regression: 125 tests passed. The only warning is Starlette's existing TestClient type-alias deprecation.
- React/Vite production build passed with 16 transformed modules.

No model calls are used by the scheduler, disclosure polling orchestration, paper catch-up, APIs or tests.
