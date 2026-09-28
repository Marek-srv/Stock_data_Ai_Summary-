# GS-08 verification — dated ownership history

GS-08 adds a deterministic, point-in-time ownership path for BEL. It stores normalized disclosure sources and holdings in SQLite, builds conservative comparisons, publishes immutable Shareholding and Institutional Flow notes, and shows raw values plus source coverage in the local dashboard.

## Source coverage

- Current period: BEL Integrated Annual Report 2024–25, as of 31 March 2025. The locally acquired primary PDF contains the category table on PDF page 107 and the top-ten non-promoter table on PDF page 108.
- Prior period: BEL Integrated Annual Report 2023–24, as of 31 March 2024. Aggregate coverage is complete; the bounded named-holder fixture includes the two schemes needed for a like-for-like comparison and is marked partial.
- The 2024 issuer URL identifies the publication month but not an exact day. The record stores month precision and does not present the first day as an exact publication day.
- Pledge data is absent from this bounded evidence set and remains visibly missing.

## Deterministic behavior checked

- The unchanged share denominator and ISIN basis permit direct comparisons for the two periods.
- Promoter, FII and DII raw shares and percentages are retained.
- HDFC Pension Scheme E Tier I is classified as observed accumulation; Canara Robeco Emerging Equities as observed reduction.
- A new 2025 scheme stays unknown because the prior named-holder fixture is partial.
- Scheme display-name changes remain comparable only when the stable holder ID is preserved.
- Ambiguous identity, absent holder coverage, and denominator/corporate-action changes return unknown rather than entry, exit, accumulation or reduction.
- Reports state that periodic changes do not identify exact trade execution.

## Validation

- Focused ownership tests: 3 passed.
- Primary-source smoke check: the saved 2024–25 PDF exposed the expected 31 March 2025 category and top-ten holder tables.
- Frontend production build completed.
- Full regression: 80 tests passed. The only warning is Starlette's existing TestClient type-alias deprecation.

No model or external data credits are used by ownership calculation, storage, report generation, or tests.
