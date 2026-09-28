# GS-17 verification — catch-up and degradation monitoring

GS-17 replays sessions missed while the local application was stopped and records whether an active paper strategy has degraded relative to its frozen validation evidence. It does not claim continuous operation while the laptop sleeps.

## Chronological, leakage-safe replay

- Independent and combined catch-up endpoints process only unseen historical sessions in sorted order. Current/future dates are deferred.
- Each replayed decision, order, fill, fee, cash record, action and mark carries `processing_mode: replay`, the saved market-run ID and its source hash.
- Independent decisions preserve the frozen candidate version, adjusted close and exact historical lookback values used by the signal.
- Combined decisions preserve the source member decision's event ID and processing mode.
- Catch-up request schemas accept only the market run and idempotency key. Late thesis or research fields are rejected before domain processing, and the paper engine has no research/thesis dependency.
- Existing session and event uniqueness constraints preserve an original signal on repeated replay or a later data bundle.

## Versioned monitoring action

Policy `paper-degradation/v1` persists these small V1 diagnostic thresholds:

- wait for three available paper marks;
- flag paper maximum drawdown above 10%;
- flag paper return more than 15 percentage points below the original untouched-OOS validation return;
- pause new entries and queue revalidation while continuing risk-reducing exits.

The immutable monitor includes paper and validation returns, drawdowns, observed sessions and closed-trade samples. A trigger never rewrites the validation or prior paper ledger. It sets an entry-only pause, records reasons and creates one durable revalidation queue row. A pending buy is cancelled with a monitoring ledger record; an existing or pending exit remains available.

## Golden checks

- A three-session downtime fixture replays January 7–9 in order, enters at the next session open, records frozen signal/source lineage, detects drawdown and backtest shortfall, retains its EXIT, and queues revalidation.
- A late `thesis` request field returns 422 and produces no paper event.
- Repeating the catch-up key returns the same monitor and event count; restart retains the entry pause, queue state and monitoring history.
- A one-session fixture remains `insufficient-sample` and takes no degradation action.
- A separate degraded fixture cancels a just-created pending entry exactly once and remains idempotent.
- The combined-book fixture marks replay and links each combined decision to its original member decision event.

## Checks

- Focused paper, combined and monitoring suites: 10 tests passed.
- React/Vite production build passed with 16 transformed modules.
- Full regression: 120 tests passed. The only warning is Starlette's existing TestClient type-alias deprecation.

No model calls are used by replay, degradation comparison, revalidation queueing, APIs, reports or tests.
