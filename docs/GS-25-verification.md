# GS-25 verification — official NSE identity coverage

Completed 12 September 2026. The implementation is deterministic and made no model calls.

## Default discovery source

- Production discovery now reads the NSE equity directory from the existing allowlisted official archive adapter and shares its SQLite same-day cache with filing identity verification.
- Every universe records source URL, retrieval timestamp, SHA-256, observed date, active-security count and assessed/unassessed counts.
- A failed refresh can reuse a previously validated directory only as `validated-public-stale`, retaining its earlier observation date.
- The synthetic four-security universe is still available only through explicit dependency injection for offline tests.

## Conservative metric join

- Revenue growth and operating margin come from the latest completed traceable financial run.
- Institutional change is the comparable aggregate FII plus DII percentage-point change from the latest ownership run.
- Momentum requires 64 aligned adjusted security and benchmark sessions from an HTTPS source identified as the National Stock Exchange of India. Synthetic/manual price histories are ignored.
- Directory companies without any local evidence are counted as unassessed. Assessed companies missing one required metric are excluded with a specific reason.

## Live result

- Saved run: `50abf944-3556-4da7-8efc-15b3e6d19385`, observed 12 September 2026 IST.
- Official source: `https://archives.nseindia.com/content/equities/EQUITY_L.csv`.
- Saved directory SHA-256: `cba7cbaa0b2320d1d3fda70f3339f05d457ae71276658ee9eae5e9a1f39dc851`.
- Directory identities: **2,568**. Locally assessed: **1**. Unassessed: **2,567**. Eligible: **0**.
- BEL has evidenced FY2025 revenue growth and operating margin, but aggregate institutional ownership changed by **-1.76 percentage points** and real market coverage has only one aligned session. It was correctly excluded.

## Verification

- Focused discovery/provider checks cover validated directory parsing, same-day cache reuse, explicit stale fallback, complete real-shaped evidence ranking, research queue handoff, missing metrics and fixture separation.
- Frontend production build passed with Vite 8.2.2 and 17 transformed modules.
- Full Python regression suite: **149 passed** with one existing Starlette/AnyIO alias deprecation warning.

This proves directory-wide identity coverage and a conservative evidence join. It does not claim directory-wide financial, ownership or historical-price coverage, and it provides no evidence of screening performance or investment returns.
