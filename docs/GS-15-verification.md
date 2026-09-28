# GS-15 verification — independent paper book

GS-15 activates only a frozen all-gates-passed candidate and processes later daily market sessions into an independent, transactional paper portfolio. It submits no broker orders.

## Activation and policy

- A validation must have both `promotion.status: passed` and `paper_eligible: true`. Rejected and insufficient validations return 422.
- The book freezes the candidate version, exact strategy configuration and validation-manifest hash.
- Policy `independent-paper-book/v1` starts with INR 100,000, permits one long cash-equity position, caps exposure at 100%, uses whole-share sizing and applies the frozen commission/slippage assumptions.
- Actual sizing uses the lower of the strategy allocation and the book exposure cap, and never exceeds available cash.

## Durable session processing

- Every decision, pending order, fill, fee, cash movement, closing mark and corporate action is a separate SQLite event with a stable semantic event ID.
- A `(book, session)` uniqueness boundary prevents a repeated market bundle or a new request key from producing another decision or fill.
- Each session and its book-state update commit in one `BEGIN IMMEDIATE` transaction. An injected crash after the first event rolls the session back completely; retry produces one ledger sequence.
- Startup reconstructs cash and quantity from the event ledger. A match is recorded; a mismatch pauses the book.
- Missing, intraday, suspended, duplicate or blocked price rows cannot fill. A due order is cancelled and the unavailable decision/mark remain visible.
- Applicable splits and bonuses adjust quantity and per-share anchors. Dividends credit cash. An incomplete or unsupported action pauses the book before its affected fill.

## Independent ledger evidence

The focused multi-session fixture proves an after-close ENTRY creates a pending order, the next eligible open creates one buy fill plus fee/cash records, a duplicate market event adds no fill, and restart reconciliation returns `matched`. Later split and dividend sessions double the shares and credit exactly `shares × cash_per_share`.

Separate fixtures prove:

- failed validation cannot activate;
- a simulated crash leaves no partial event/session/state mutation;
- retry after the crash processes the session once;
- a share price above available capital records `insufficient-cash` and no fill;
- a missing due-session price cancels the pending fill;
- an uncertain merger pauses the affected book with its pending order intact.

## Persisted local smoke book

- Validation: `5e8d9053-37b6-4cd3-bdde-5413f700a38a` (`passed`, synthetic mechanics fixture).
- Book: `5721c0ec-5b87-431b-8f57-c25315d1844a`.
- Later market run: `3abd8221-a4ba-4d88-8503-e1ba43674e33`.
- Five later sessions produced 18 records across decision, pending-order, fill, fee, cash and mark kinds.
- The bounded book closed with INR 114,713.29 cash and zero shares. This is synthetic accounting evidence, not a live strategy claim.

## Checks

- Focused GS-15 suite: 4 tests passed.
- Related market/backtest/validation/paper checks: 23 tests passed.
- Full regression: 114 tests passed. The only warning is Starlette's existing TestClient type-alias deprecation.
- React/Vite production build passed with 16 transformed modules.

No model calls are used by activation, decisions, fills, accounting, reconciliation, reporting, APIs or tests.
