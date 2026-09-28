# GS-13 verification — reproducible strategy backtest

GS-13 adds one approved trend-following strategy, a deterministic daily event loop, an immutable cash/trade ledger, benchmark measures, a dashboard view and an Obsidian experiment report.

## Frozen strategy and engine

- Strategy `trend-following-close-above-sma/v1` decides after each close. It requests a long position when the adjusted close is above the prior three eligible-session simple moving average and otherwise requests an exit.
- Orders can fill only at the immediately next expected eligible session open. They are cancelled on a missing, suspended, intraday or unusable bar and are never shifted to a later session.
- Engine `graph-stock-daily-event-loop/v1` is an in-project deterministic event loop. It introduces no third-party simulation runtime or license; the repository currently has no declared distribution license. VectorBT was not selected because its vectorized execution does not define this project's ledger, missing-bar and ambiguity policies; it may remain a comparison tool later.
- The fixed GS-13 assumptions are INR 100,000 initial cash, 100% allocation, 5% stop, 10% target, 10 bps commission and 5 bps slippage. They are a versioned simulation assumption, not a claim about current broker or statutory charges. GS-14 must stress and validate costs before any promotion.
- No parameter search occurs in GS-13; the stored search history is empty.

## Execution semantics

- A buy applies adverse slippage to the next eligible open, then sizes whole shares after estimated cost. A sell applies adverse slippage and records its own cost.
- If the opening gap crosses a stop or target, the open is used. If the daily high and low touch both, the stop executes first and the trade is marked ambiguous.
- Raw OHLC drives execution. Adjusted closes drive the scale-invariant signal. Splits and bonuses update held quantity and protective-price anchors; dividends credit cash and update the anchors. Unsupported or incomplete actions reject the run.
- The benchmark uses close-to-close price return over common sessions. When security dividend cash is included but no benchmark total-return series exists, comparison is explicitly unavailable.
- Undefined win rate, profit factor, expectancy, Sharpe or benchmark measures stay null with a reason instead of becoming zero.

## Reproducibility

Each result stores the strategy, engine, corporate-action, cost and market-data versions; fixed configuration; complete input bars/actions/benchmark; source ID and source hash; expected sessions; period; universe limitations; and a SHA-256 data-manifest hash. The report is immutable below `Graph Stock/Backtests/<symbol>/`.

## Independent golden ledger

The core ledger test uses INR 1,000 cash, 1% commission and no slippage. A 3 January after-close signal fills 8 shares at INR 120 on 6 January:

- Entry gross INR 960.00 + INR 9.60 cost leaves INR 30.40 cash.
- The 7 January low touches the INR 108.00 stop.
- Exit gross INR 864.00 − INR 8.64 cost yields INR 855.36.
- Final cash is INR 885.76 and trade P&L is −INR 114.24, exactly matching the independent arithmetic.

Separate fixtures verify gap-open exits, simultaneous stop/target conservative ordering, missing and suspended fill cancellation, split quantity/anchor changes, dividend cash credit, unavailable measures and idempotent API/report retrieval.

## Validation

- Focused GS-13 suite: 6 tests passed.
- Related backend checks: 29 tests passed.
- Full regression: 106 tests passed. The only warning is Starlette's existing TestClient type-alias deprecation.
- React/Vite production build passed with 16 transformed modules.
- Persisted local smoke run: `2884b69d-1801-4fcc-a084-8f9ac7c37822` against market fixture `04973d6c-9efe-46bd-9943-98b20eb83a7c`.
- Smoke-run data manifest: `7c0ad1b498d0137a30cabd438327313a06769b10d46aa86f35d38b434e67a09b`.
- The smoke run records one next-session entry and a later stop-gap-open exit, INR 90,639.76 ending equity, −9.36024% return, 10.840081% maximum drawdown and a 6% benchmark return. The poor result is retained as evidence; it is not promoted or described as predictive.

No model calls are used by rule evaluation, simulation, accounting, reporting, API handling or tests.
