# GS-23 verification — explainable NSE candidate discovery

Completed 11 September 2026. Verification used deterministic local fixtures and made no model or network calls.

## Dated coverage and policy

- Universe `bounded-nse-fixture/2026-09-10` contains exactly BEL, HAL, BHEL and the delisted OLDCO fixture as of 10 September 2026.
- Policy `fundamental-accumulation-momentum/v1` records thresholds and fixed weights: fundamentals 40%, accumulation 30% and momentum 30%.
- BEL is eligible. HAL is excluded for momentum threshold failures, BHEL is excluded because institutional accumulation is missing, and OLDCO is excluded because it is delisted.
- Missing metrics remain missing and never become zero or silently pass a filter.

## Evidence, queue and safety

- Every candidate exposes raw metrics, threshold results, component scores, total score, failures and missing-data reasons in the API, dashboard and immutable Markdown report.
- Screen requests are content-addressed and idempotent. Repeating the same policy and universe reuses the existing run.
- Queueing an eligible candidate calls the existing persistent `ResearchService`; repeat selections reuse the recorded queue entry and fixture company/watchlist identity.
- Discovery has no route to a paper book or broker. The dashboard labels queueing as research-only.
- The report states the four-security fixture boundary and prohibits NSE-wide coverage, ranking-performance or return claims.

## Public paths

- `GET /api/v1/discovery` and `POST /api/v1/discovery` list or create a screen.
- `GET /api/v1/discovery/{run_id}` returns candidate details.
- `GET /api/v1/discovery/{run_id}/report` serves the immutable report.
- `POST /api/v1/discovery/{run_id}/candidates/{security_id}/queue` performs an idempotent eligible-candidate handoff to research.

## Final checks

- Focused discovery checks: **4 passed**.
- Frontend production build: passed with Vite 8.2.2 and 17 transformed modules.
- Full Python regression suite: **142 passed** with one existing Starlette/AnyIO alias deprecation warning.

This ticket demonstrates the screening and queue contract against a deliberately small fixture. It does not claim current full-market NSE coverage, historical screening performance or investment profitability.
