# GS-14 verification — bounded strategy validation

GS-14 registers the eight approved strategy families, performs a bounded allowlisted search for the implemented trend-following family, separates train/tuning/untouched data, persists every candidate and requires every validation gate before paper eligibility.

## Registry and search boundary

- Registry `approved-strategy-families/v1` contains momentum, breakout, pullback, relative strength, volume expansion, earnings momentum, institutional accumulation and trend following.
- Each family declares required feature families and allowlisted parameter values. Missing required data makes it ineligible. Families without an implemented simulator are also visibly ineligible rather than silently approximated.
- GS-14 explores six immutable trend-following candidates: lookbacks 2, 3 and 5 crossed with the fixed 5%/10% and 8%/15% stop/target pairs.
- Search policy `bounded-grid/v1` has a hard six-experiment budget. Every candidate, configuration, train metrics, tuning metrics, window hashes and error is stored in `validation_experiments` and the immutable validation result.
- Selection uses the highest tuning return. Every candidate records `holdout_accessed: false`; untouched evaluation starts only after selection.

## Versioned acceptance policy

Policy `candidate-acceptance/v1` reserves 50% of sessions for train, 25% for tuning and 25% for untouched out-of-sample evaluation. It requires:

- at least 40 total and 10 untouched sessions;
- at least one closed untouched trade;
- positive untouched return and return no worse than the available benchmark;
- no more than 35% untouched maximum drawdown;
- positive return with modeled commission and slippage doubled;
- at least half of allowlisted neighboring lookbacks non-negative;
- at least half of two chronological pre-holdout walk-forward folds non-negative;
- required feature support, proven holdout isolation and search-budget compliance.

These deliberately modest numbers prove the validation and leakage-control machinery. They do not establish production robustness, NSE-wide validity or a forecast. A rule/configuration change creates a new candidate version and invalidates the prior promotion basis.

## Validation fixtures

- A 60-session price path runs through the real GS-13 simulator. It produces five untouched closed trades, stays profitable with doubled modeled costs, passes sensitivity and walk-forward checks, and passes all eleven required gates.
- A deterministic control fixture makes only cost stress fail. The candidate is rejected, proving one failed mandatory gate blocks promotion.
- A seven-session real-engine/API fixture is marked `insufficient-evidence`, persists all six experiments and remains paper-ineligible.
- Call tracing proves the first twelve train/tuning simulations contain no untouched session. OOS, stress and sensitivity evaluation occur only after the selected candidate is frozen.

## Persisted local result

Run `f4844f6a-8026-45ea-8d6a-fa23daa0fac3` validates market fixture `04973d6c-9efe-46bd-9943-98b20eb83a7c`. Its manifest is `8aac72844dcc0848d47d870fee4ee9761ad02766e1a15adde3ce0f024a1408eb`.

The result is correctly `insufficient-evidence`: only seven sessions exist, no untouched trade closes, and OOS/benchmark/cost gates lack sufficient support. Paper eligibility is false. The failure is retained as an immutable report below `Graph Stock/Validation/BEL/`.

## Checks

- Focused GS-14 suite: 4 tests passed.
- Combined feature/market/backtest/validation checks: 23 tests passed.
- Full regression: 110 tests passed. The only warning is Starlette's existing TestClient type-alias deprecation.
- React/Vite production build passed with 16 transformed modules.

No model calls are used by registry checks, candidate search, simulation, validation gates, persistence, reporting, API handling or tests.
