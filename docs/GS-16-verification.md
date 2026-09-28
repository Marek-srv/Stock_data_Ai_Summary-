# GS-16 verification — combined strategy book

GS-16 combines decisions from at least two independent paper books inside a new, separately capitalized simulated account. It does not add member balances together and submits no broker orders.

## Shared policy and accounting

- Policy `equal-allocation-exit-first/v1` freezes initial cash, member allocation percentages, a 100% shared exposure ceiling, whole-share sizing and conflict precedence. Its content hash forms the policy ID.
- Each member has an attributed position and cost basis, while cash, equity, peak equity and drawdown belong to the combined account.
- A changed allocation creates another book and policy ID. The previous book retains its original allocation policy.
- Buy fills disclose cash before/after, the member allocation cap and the sizing reason. Rejections identify missing prices, exhausted shared cash, an existing attributed position or exit precedence.

## Ordering, attribution and reconciliation

- Orders created at a decision close execute at the next usable open. Pending exits execute before pending entries.
- Any member EXIT blocks all same-symbol ENTRY decisions for that session with `exit-precedence-conflict`.
- Every decision, fill, fee, rejection and mark has a stable semantic ID. Fill and fee payloads identify the member book.
- A unique combined session boundary and idempotent request result prevent duplicate processing.
- Closing marks store combined cash and attributed positions. Startup compares the materialized state with the latest mark from this combined ledger; mismatch pauses the book.
- Independent member state is read for identity and decisions but is never mutated by combined fills.

## Golden checks

The two-strategy fixture queues two entries, sizes both inside equal 50% allocation caps and available shared cash, and creates exactly two attributed fills and fee records. A later member EXIT and competing member ENTRY records an explicit conflict rejection; the exit fills at the following open. The fixture verifies non-negative cash, total entry cost within the INR 100,000 account, unchanged independent member states and matched reconciliation after restart.

A second fixture creates equal and 70/30 policies, verifies distinct policy IDs and confirms the first book remains 50/50. Invalid duplicate membership and allocations above 100% are rejected.

## Checks

- Focused combined and independent paper suites: 7 tests passed.
- React/Vite production build passed with 16 transformed modules.
- Full regression: 117 tests passed. The only warning is Starlette's existing TestClient type-alias deprecation.

No model calls are used by activation, combined decisions, sizing, fills, accounting, reconciliation, reporting, APIs or tests.
