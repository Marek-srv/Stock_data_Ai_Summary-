# GS-04 verification

Completed 6 September 2026 (Asia/Kolkata). This ticket extracts a bounded set of financial facts and deterministic metrics. It does not add valuation, a complete company thesis or a trading conclusion.

## Delivered behavior

- A versioned financial service and `/api/v1/financials` operations for extraction, status, retry, note reading and note download.
- Consolidated statement-page discovery for the measured BEL annual-report layout, followed by strict row extraction rather than an unbounded document summary.
- Twenty-two normalized annual facts covering assets, equity, current and non-current borrowings, revenue, other income, finance costs, pre-tax profit, profit for the year, operating cash flow and capital expenditure for FY2025 and FY2024.
- Every fact retains its source ID, evidence ID, reported text and lakh unit, normalized crore value, fiscal period/end date, consolidated scope, restatement state, PDF page, statement, row and extractor version.
- Deterministic revenue growth, derived operating margin, net profit margin, total borrowings/equity, operating cash conversion and free cash flow with formula version and exact input/evidence IDs.
- Explicit unavailable states for dashes, nulls, zero denominators, incompatible periods, incompatible account scope and incompatible units. A dash is never fabricated as zero.
- SQLite facts, metrics and idempotent job state plus immutable Markdown publication under `Graph Stock/Financials/<symbol>/`.
- A dashboard action whose default performs only local extraction and formulas. Optional AI interpretation is a separate labelled action.
- The optional signed-in adapter runs read-only and without tools, accepts only a fixed validated metric bundle, validates its schema and evidence references, and rejects numeric prose or unsupported metric IDs.

## Real filing evidence

Local run `26711f09-a85a-40ed-8a4a-a02e76421f33` processed saved source `efb2b6691ade11bf748ff9f6fc867e8bcc7cdd3f69d54730f8051f95ba08a216`, the 236-page BEL Integrated Annual Report 2024–25 collected in GS-03. The extractor located the consolidated balance sheet on PDF page 188, profit and loss on page 189 and cash flows on page 191.

The run normalized FY2025 revenue of `23,76,875` lakh to `23,768.75` crore and FY2024 revenue of `20,26,824` lakh to `20,268.24` crore. Independently checked outputs were revenue growth `17.27%`, derived operating margin `26.78%`, net profit margin `22.39%`, operating cash conversion `11.02%` and free cash flow `-424.66` crore. Total borrowings/equity remained unavailable because both borrowings rows contain reported dashes. FY2024 cash-flow facts retain the report's regrouped/reclassified warning.

The completed snapshot and its note hash are persisted in `.state/graph_stock.sqlite3`. The note was published at `Graph Stock/Financials/BEL/26711f09-a85a-40ed-8a4a-a02e76421f33.md` with SHA-256 `34823917d11fdb7958712c723a892874d9968502eff3b57912eef3f20c7dcd00`.

## Focused validation

- Full Python suite: **67 passed**. The two recorded upstream Starlette/AnyIO deprecation warnings remain.
- Financial suite: **5 passed**, covering the hand-checked golden, lakh/crore scaling, negatives, dashes, restatement metadata, zero denominator, period/scope incompatibility, strict reasoning output and the no-credit default API flow.
- React/Vite production build passed with 16 transformed modules.
- The real BEL extraction used no Codex reasoning request. The optional adapter was not live-run, preserving the user's remaining allowance; its authentication and process contract reuse the already verified GS-01 path, and its financial schema/evidence rejection is tested offline.

## Measured limits

Extraction currently targets the BEL-style consolidated annual-statement layout and searches for three exact statement families. Other layouts return `unsupported` and remain safely stored for future parser expansion. Standalone and consolidated facts carry explicit scope, while this first real snapshot publishes consolidated figures only. The operating-margin figure is labelled as a derived proxy. Borrowings/equity excludes lease liabilities and remains unavailable when the statement reports dashes.

The next ticket, GS-05, adds dependency fingerprints, selective invalidation, resumable node execution and visible reuse around this filing-to-financials path.
