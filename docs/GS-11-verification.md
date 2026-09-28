# GS-11 verification — market data and corporate-action adjustments

GS-11 adds validated NSE security and benchmark OHLCV, raw-source preservation, effective symbol aliases, versioned corporate-action factors, quality diagnostics, immutable reports and a raw/adjusted dashboard comparison.

## Data and provenance

- The automatic adapter reads BEL and NIFTY 50 from NSE's first-party NIFTY 50 market-watch response and reads BEL corporate actions from NSE's corporate-action response.
- The live source response is stored once with its content SHA-256, source URL, availability label and retrieval time. Every normalized bar and action retains its source ID.
- Manual historical JSON bundles pass through the same validation, normalization, persistence and report pipeline.
- Security aliases retain effective dates and ISINs. When the live corporate-action response and the previously saved NSE equity-directory source disagree on BEL's ISIN, both values remain stored and the selection is `unresolved`.

## Adjustment policy and diagnostics

- `corporate-action-adjustment/v1` computes backward price and share/volume factors for splits, bonuses, dividends and complete rights terms.
- Merger and demerger records accept explicit supported factors. Incomplete rights, merger or demerger terms mark prior affected rows unavailable instead of inventing an adjustment.
- Raw OHLCV is immutable and remains visible beside adjusted values and factors.
- Impossible OHLC, invalid volumes and malformed dates are rejected. Missing sessions, benchmark gaps, duplicates, explicit suspensions, provisional intraday bars and listing coverage are reported separately.
- The normalization scope explicitly excludes total revenue, profit and other total financial-statement values.

## Validation

- Hand-worked split, 1-for-4 bonus, cash-dividend and complete-rights cases match independently expected price and volume factors.
- Incomplete rights, merger and demerger cases block only affected history; invalid OHLCV is rejected.
- API validation covers idempotency, raw evidence, benchmark rows, aliases, unresolved identity conflicts, normalized persistence and immutable report retrieval.
- Production frontend build passed.
- Full regression: 96 tests passed. The only warning is Starlette's existing TestClient type-alias deprecation.
- Representative live run: `91233206-947a-4860-9885-b93dbc298c33`.
- The live run retrieved BEL and NIFTY 50 for 7 September 2026 and two BEL dividend records. It is correctly `partial` because the market-watch row was intraday and prior bars needed to calculate historical dividend factors were outside this current-session source's coverage.

No model calls are used by collection, validation, adjustment, diagnostics, persistence, report generation or tests.
