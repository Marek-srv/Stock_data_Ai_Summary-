# GS-07 verification

Verified on 6 September 2026 against the preserved BEL Integrated Annual Report 2024–25. The workflow is deterministic and made no signed-in reasoning call.

## Implemented contract

- Earnings compares consolidated FY2025 with FY2024 only after checking metric identity, scope, unit and period order. Revenue growth is 17.27% and profit-after-tax growth is 33.56% for the measured filing. Consensus is explicitly `unavailable` with reason `missing-consensus-source`.
- Management Claim Tracker records claim date, target period, metric, baseline, target, direction, evidence IDs and each observed state. The policy supports pending, met, missed, partial and unverifiable outcomes.
- BEL's qualitative order-inflow claim is pending through its FY2028 target period. The non-defence share goal is unverifiable because management says “coming years” without a dated target.
- Claim states are saved by run in `management_claim_states` and returned as historical state records. Reusing a report adds a new run observation without replacing earlier states.
- Valuation policy `earnings-multiple-scenarios/v2` applies illustrative 20x, 25x and 30x P/E assumptions to FY2025 reported profit after tax. Implied equity values are INR 106,453.60 crore, INR 133,067.00 crore and INR 159,680.40 crore. A nine-point sensitivity combines -10%, 0% and +10% earnings changes with all three multiples.
- Per-share value/upside is not-applicable because current price and diluted share count are absent. DCF is not-applicable because forecast cash flows and discount assumptions are absent.
- Management records the issuer's Board-level enterprise-risk oversight disclosure. Risk prioritizes defence concentration, technology/sourcing, FY2025 cash conversion and valuation-input uncertainty.
- All five `event-specialist-report/v2` outputs validate their required payload and allowed evidence references, print evidence IDs in their immutable notes, persist in `advanced_reports`, publish below `Graph Stock/Research/BEL/`, appear in the snapshot and link from the dashboard.

## Validation

The focused event-research and graph suite passed **8 tests in 1.70 seconds**. It covers hand-checked earnings growth, absent consensus, golden valuation scenarios, the full claim-state transition set, unsupported evidence rejection, risk propagation, dependency ordering, source invalidation, persistence, history and cache reuse.

The complete Python suite passed **77 tests in 3.28 seconds** with the existing upstream AnyIO deprecation warning. The React/Vite production build passed with 16 modules transformed.

## Real local run

Run `a77d0d62-c509-421e-898e-8f715e3c52f5` completed from `2026-09-06T14:23:02.213127+00:00` to `2026-09-06T14:23:02.298483+00:00`.

The manifest recorded graph `filing-refresh/v3`, report `research-update-note/v3`, evidence `bel-qualitative-evidence/v4`, event schema `event-specialist-report/v2`, and versioned earnings, claim, valuation and risk policies. Five advanced reports and two claim states were persisted.

| Report | Assessment |
|---|---|
| Earnings | supported |
| Management Claims | insufficient |
| Valuation | provisional |
| Management | provisional |
| Risk | mixed |

The combined immutable report is `Graph Stock/Updates/BEL/714ddffde41143eaf61c2328b33ee615175144012292452b95a74e8dcef1c048.md` in the configured vault.

Successor run `bbf13596-3213-443d-a0ba-d3bccdcf3fe5` completed with all fifteen nodes marked `reused`. Its returned management history contained twelve state records, retaining both claims from all completed GS-07 runs.

## Scope boundary

The valuation multiples are transparent analyst assumptions rather than target prices. The system does not invent consensus, forecasts, prices, share counts or DCF inputs. Current claim outcomes cannot be promoted beyond pending or unverifiable until later compatible evidence is ingested.

The next ticket in number order is GS-08.
