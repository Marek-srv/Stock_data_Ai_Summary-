# GS-06 verification

Verified on 6 September 2026 against the preserved BEL Integrated Annual Report 2024–25. The source is a historical issuer filing and is labelled stale for current-decision use.

## Implemented contract

- The qualitative extractor checks the supported BEL content hash and measured anchors on PDF pages 45, 46, 48, 50 and 90.
- Business Quality records the business model, turnover mix, product/service economics, portfolio breadth and order-book driver with evidence IDs.
- Industry separates issuer outlook from reported risks and states that independent market-size and procurement evidence is absent.
- Competitor records BEL's market-leadership statement as an issuer claim, marks HAL and BDL primary coverage missing, and withholds a peer ranking.
- Business Quality, Industry and Competitor fan out from one versioned evidence bundle. Moat joins only after all three reports and records their three report IDs.
- Every claim must cite an allowed evidence ID. Reports reject unknown evidence, unknown schema fields and incomplete moat dependencies.
- `specialist-report/v2` includes the evidence version in both the schema and content-addressed report identity. This prevents changed evidence rendering from colliding with an older immutable note.
- Four reports per run are stored in `specialist_reports`, published below `Graph Stock/Specialists/BEL/`, condensed into the refresh snapshot and linked from the dashboard and combined update note.

## Focused and full validation

The specialist and orchestration suite passed 7 tests. It covers a bounded BEL/HAL/BDL company-peer fixture, source periods, missing peer coverage, unsupported-evidence rejection, the three-input moat contract, parallel fan-out, invalidation, reuse, cancellation and checkpoint recovery.

The complete Python suite passed **74 tests in 3.08 seconds** with the existing upstream AnyIO deprecation warning. The React/Vite production build also passed with 16 modules transformed. No signed-in reasoning call was made.

## Real local run

Final run `3d7b7b3d-edb8-47eb-b3aa-ffceb69ccb49` completed from `2026-09-06T13:56:30.033870+00:00` to `2026-09-06T13:56:30.104463+00:00`.

The manifest recorded:

- graph `filing-refresh/v2`
- qualitative evidence `bel-qualitative-evidence/v2`
- specialist schema `specialist-report/v2`
- specialist policy `evidence-gated-specialists/v1`
- reasoning disabled

Existing financial extraction, context, qualitative extraction and metrics were reused. The final schema change caused Business Quality, Industry, Competitor, Moat and the combined report to run. Four specialist rows were persisted. Results were:

| Report | Assessment |
|---|---|
| Business Quality | supported |
| Industry | mixed |
| Competitor | insufficient |
| Moat | provisional |

The combined immutable report is `Graph Stock/Updates/BEL/ebdd808f81f4883e731483083ee74b2084ccefa2a81fda953e17a6713cf3e88a.md` in the configured vault.

Successor run `e2a41d52-df77-4a08-89df-8ddb3b838a9c` completed with all ten nodes marked `reused`, confirming final-version cache reuse and idempotent publication.

## Scope boundary

This is deliberately bounded historical coverage for one issuer. It does not crawl the market, treat management claims as independent facts, or infer absent peer data. Adding HAL and BDL primary filings is required before the competitor and moat reports can support a relative ranking.

The next ticket in number order is GS-07.
