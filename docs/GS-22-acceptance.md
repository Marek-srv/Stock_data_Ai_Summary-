# GS-22 V1 release acceptance

Acceptance run: 11 September 2026. Machine-readable evidence is in `GS-22-release-manifest.json`; operating instructions are in `OPERATIONS.md`.

## Evidence boundary

The saved public-source path uses Bharat Electronics Limited (`BEL`) and the NSE-hosted 2024–25 integrated annual report. The source record is a 236-page PDF with SHA-256 `db47a73b477737b5c5241d6c62bfba08446a734fb8b59972b6a6577e0fe7867d`, source ID `efb2b6691ade11bf748ff9f6fc867e8bcc7cdd3f69d54730f8051f95ba08a216`, and a recorded public-availability basis. Financial metrics, specialist research, institutional comparison, Bull/Bear/Judge synthesis and the compact snapshot derive from that preserved public source.

The automatic NSE market adapter has current-session and recent-action coverage only. It correctly returns `partial`; it does not provide enough history for a real point-in-time strategy validation. Historical PIT, golden backtest, passing validation, independent paper and combined paper demonstrations therefore use deterministic imported fixtures and are labelled as mechanics evidence. The real-data validation outcome is never forced to pass.

## End-to-end and incremental evidence

The complete public-source research report is retained in run `814bc3b5-5fba-469c-945f-7619c4a7fa96`. It contains all nine specialist responsibilities, the independent Bull and Bear cases, Judge, Investment Thesis and scorecard, traceable financial facts and the March 2024/March 2025 institutional comparison.

GS-22 submitted a fresh local-only refresh against the same preserved filing. Run `d66d4b12-af1f-44c0-ae65-8ef80828ab9a` completed in about 0.2 seconds with manifest `7421fe8c8950674f276af1462fe2fe29c34d257b5d6aa4669642f824349306df`. Fourteen of 22 nodes reused accepted outputs. A newer ownership record changed its descriptor, so ownership and the dependent Bull, Bear, Judge, thesis, score and publication nodes reran; extraction, metrics, Business Quality, Industry, Competitor, Moat, Earnings, Management Claims, Valuation, Management, News and Risk reused prior accepted work. This proves affected-graph refresh while preserving unrelated research.

The source PDF, all 100 vault artifacts referenced by the consistent release snapshot and the latest verified backup record were present when the acceptance manifest was produced. Earlier backup `471ba1e8-ecbe-4642-ba09-4041605c7196` had already completed an isolated restore rehearsal with two databases and 69 artifacts at its frozen point in time.

## S15 scenario result

All ten release-scenario groups pass with explicit evidence classification:

1. Saved real NSE filing to traceable metrics, specialist research, complete snapshot and detailed artifacts.
2. Duplicate/incremental input reuse without duplicate facts, reports or fills.
3. A changed disclosure descriptor reruns affected research while unrelated nodes remain reused.
4. Partial sources and authentication expiry retain distinct wait/failure states and resume paths in adapter integration tests.
5. Fact correction retains original values, evidence and earlier reconstruction.
6. PIT and backtest golden tests exclude future disclosures and cover corporate actions and ambiguous bars.
7. Validation rejects a failed/insufficient candidate and promotes only a clearly labelled passing mechanics fixture.
8. Independent and combined paper fixtures prove transactional decision-to-fill recovery and attribution.
9. Scheduler catch-up, alert deduplication, edited-vault preservation and verified restore pass.
10. Exact-change approval guards block upstream integration; the route audit finds no V1 broker/order-submission endpoint.

The production React build was inspected in the local in-app browser. The real-source collection flow, source status history and upstream-review panel rendered from the running FastAPI service. The application remains bound to `127.0.0.1:8765`.

Passing release checks establish the specified behavior and reconstruction controls. They do not establish investment performance, a profitable live strategy or suitability for unattended trading.
