# graph_stock — Dependency-aware implementation tickets

Version 3.3 · 28 September 2026 · Local implementation handoff and progress

Parent specification: [to-spec.md](to-spec.md). This plan implements the confirmed design and the authorized real-data coverage extensions. GS-01 through GS-27 are complete. No external tracker issues have been created.

## Delivery approach

Each feature ticket delivers an observable path through the relevant UI/API, persistent state and domain behavior, with its own acceptance evidence. The first ticket is a bounded feasibility slice; the final V1 ticket is release verification. New schemas, UI elements and tests travel with the behavior that needs them.

Use the ticket frontier: start only when every listed blocker is complete. Number order is a valid topological order, but independent branches can proceed separately. Dependencies below are direct blockers; indirect blockers are inherited. Ticket status is recorded below. “Ready” means all blockers have passed, not merely that the ticket text exists.

This is the requested consolidated local ticket document. It applies the vertical-slice and explicit-blocker principles from [Matt Pocock's to-tickets reference](https://github.com/mattpocock/skills/blob/main/skills/engineering/to-tickets/SKILL.md); the delivery format is adapted to the user's two-document request. The confirmed Q43 testing standard supplies the shared validation expectations.

## Milestones and dependency index

| Milestone | Usable outcome |
|---|---|
| M0 | Verified authenticated reasoning path |
| M1 | Real-source financial snapshot with reuse/resume |
| M2 | Complete baseline research and institutional snapshot |
| M3 | Auditable historical strategy evaluation |
| M4 | Independent and combined paper portfolios |
| M5 | Scheduled operation, alerts, history, improvement workflow and V1 acceptance |
| Phase 2 | NSE candidate discovery |
| Later | Optional OS-startup integration |

| Ticket | Delivery | Direct blockers | Milestone |
|---|---|---|---|
| GS-01 | [Prove authenticated reasoning with a visible local diagnostic](#gs-01) | None | M0 |
| GS-02 | [Research a fixture ticker and reopen its saved snapshot](#gs-02) | GS-01 | M1 |
| GS-03 | [Fetch one real filing with fallback and evidence inspection](#gs-03) | GS-02 | M1 |
| GS-04 | [Produce traceable financial metrics from a result document](#gs-04) | GS-03 | M1 |
| GS-05 | [Refresh changed evidence and resume interrupted analysis](#gs-05) | GS-04 | M1 |
| GS-06 | [Add business, industry, competitor and moat research](#gs-06) | GS-05 | M2 |
| GS-07 | [Connect earnings, management claims, valuation and risk](#gs-07) | GS-06 | M2 |
| GS-08 | [Show dated ownership and scheme-level institutional history](#gs-08) | GS-05 | M2 |
| GS-09 | [Add dated news and material catalysts](#gs-09) | GS-05 | M2 |
| GS-10 | [Publish independent debate, scores and the complete snapshot](#gs-10) | GS-07, GS-08, GS-09 | M2 |
| GS-11 | [Inspect daily market data and corporate-action adjustments](#gs-11) | GS-03 | M3 |
| GS-12 | [Build and inspect point-in-time feature snapshots](#gs-12) | GS-04, GS-08, GS-09, GS-11 | M3 |
| GS-13 | [Backtest one approved strategy against an independent ledger](#gs-13) | GS-12 | M3 |
| GS-14 | [Explore controlled strategy variations and validate them](#gs-14) | GS-13 | M3 |
| GS-15 | [Paper trade a validated strategy and reconcile after restart](#gs-15) | GS-14 | M4 |
| GS-16 | [Combine strategy books under a shared capital policy](#gs-16) | GS-15 | M4 |
| GS-17 | [Monitor paper degradation and replay missed sessions](#gs-17) | GS-16 | M4 |
| GS-18 | [Keep watchlist research and paper books current on schedule](#gs-18) | GS-10, GS-17 | M5 |
| GS-19 | [Deliver material alerts to dashboard and Obsidian](#gs-19) | GS-18 | M5 |
| GS-20 | [Inspect corrections and restore consistent research history](#gs-20) | GS-10, GS-19 | M5 |
| GS-21 | [Review GitHub improvements without automatic integration](#gs-21) | GS-19 | M5 |
| GS-22 | [Demonstrate V1 on real sources and complete operational handoff](#gs-22) | GS-20, GS-21 | M5 |
| GS-23 | [Discover NSE candidates and queue explainable research](#gs-23) | GS-22 | Phase 2 |
| GS-24 | [Start the local application automatically when requested](#gs-24) | GS-22 | Later |
| GS-25 | [Replace fixture-first discovery with official NSE identity coverage](#gs-25) | GS-23 | Phase 2 |
| GS-26 | [Load validated official NSE price history](#gs-26) | GS-11, GS-25 | Phase 2 |
| GS-27 | [Load official financial and ownership evidence](#gs-27) | GS-25 | Phase 2 |

The main branch starts GS-01 → GS-02 → GS-03 → GS-04 → GS-05. After GS-05, qualitative research, ownership and news can progress independently. Market data starts from GS-03 and joins financial/ownership/news inputs at GS-12. Research and paper branches join at GS-18. V1 closes at GS-22; GS-23 and GS-24 do not block it. GS-25 extends GS-23 with the authorized official-directory source, GS-26 adds official bulk price history, and GS-27 adds bounded XBRL financial and ownership evidence.

## Common completion contract

- Keep NSE-only, SQLite-only, Obsidian qualitative memory, LangGraph, FastAPI and React/Vite decisions intact.
- Preserve evidence, input manifests, units, timestamps and version history in every feature that creates facts or conclusions.
- Validate agent output schema and evidence references before accepting it; use deterministic services for material numbers.
- Add behaviour-level tests at the public service seam and independent golden expectations where correctness matters.
- Demonstrate success, missing/partial data and relevant failure/retry paths; show truthful UI states.
- Store configuration and its version for choices affecting research, experiments and portfolios.
- Keep sources/ read-only. Do not publish external issues, integrate upstream code or add broker execution as part of routine implementation.
- Record completion evidence and changed contract decisions. If a ticket grows too large, split it into smaller observable slices and update explicit blocking edges before marking anything complete.

<a id="gs-01"></a>

## GS-01 — Prove authenticated reasoning with a visible local diagnostic

**Milestone:** M0  
**Status:** Complete — see [verification evidence](docs/GS-01-verification.md)  
**Blocked by:** None  
**Spec coverage:** S06, S16

**What to build:** A small FastAPI-backed local diagnostic sends a fixed evidence bundle through the installed signed-in Codex client and displays a validated result or a precise resumable failure.

**Acceptance criteria**

- [x] Run successfully without an OpenAI API key using the installed supported ChatGPT-authenticated client; record client version and redacted capability result.
- [x] Validate returned schema, separate progress from result, and persist request ID and state without recording credentials.
- [x] Exercise expired/missing auth, malformed output, timeout and usage-limit responses; retry the same request without duplicate accepted results.
- [x] Bound concurrency and use read-only reasoning permissions; no shell interpolation of source content, browser-token extraction or silent provider switch.

**Validation:** One genuine account-backed smoke run plus adapter contract tests with success/failure fixtures. If this cannot pass, record a concrete blocker to automated reasoning; do not mark dependent research tickets complete.

**Scope boundary:** No research agent suite or strategy work. This is the first feasibility gate, with a user-visible diagnostic rather than an infrastructure-only scaffold.

<a id="gs-02"></a>

## GS-02 — Research a fixture ticker and reopen its saved snapshot

**Milestone:** M1  
**Status:** Complete — see [verification evidence](docs/GS-02-verification.md)  
**Blocked by:** [GS-01](#gs-01)  
**Spec coverage:** S01, S02, S04, S13

**What to build:** Enter a known NSE fixture ticker in a minimal React/Vite screen, launch a FastAPI research run, and reopen its SQLite-backed snapshot and generated Obsidian note after restart.

**Acceptance criteria**

- [x] Resolve a known fixture security and handle ambiguous/unknown input explicitly; successful resolution adds a watchlist item.
- [x] Persist run ID, evidence IDs, timestamps and a clearly labelled fixture snapshot; CLI and UI use the same service operation.
- [x] Write a generated note into a configured test vault and make it accessible from the dashboard; do not touch user-authored content.
- [x] Restart and retrieve the same result; duplicate idempotency keys produce one run; bind locally and validate write origins.

**Validation:** End-to-end fixture flow through UI/API/storage/vault, restart and duplicate submission; inspect empty/loading/error states.

**Scope boundary:** No claim of live financial analysis; fixture labels must be unmistakable. Establish shared domain contracts within this working slice.

<a id="gs-03"></a>

## GS-03 — Fetch one real filing with fallback and evidence inspection

**Milestone:** M1  
**Status:** Complete — see [verification evidence](docs/GS-03-verification.md)  
**Blocked by:** [GS-02](#gs-02)  
**Spec coverage:** S03, S04, S13, S16

**What to build:** Research a real NSE ticker and inspect an automatically fetched public filing, with manual import and visible source gaps when acquisition fails.

**Acceptance criteria**

- [x] Demonstrate an actual primary-source filing and identity lookup, recording source URL, availability/retrieval times and content hash.
- [x] Adapter contract distinguishes unchanged, partial, unavailable, throttled and invalid responses; validate normalized output before storing.
- [x] Manual document import enters the same pipeline; duplicate document hashes do not duplicate evidence.
- [x] Expose source location, parser status and retry/manual-add action in UI and Obsidian; record measured provider coverage and fallback limits.

**Validation:** Golden source fixture, live primary-source smoke retrieval, failed-provider/manual-fallback integration and malformed input checks.

**Scope boundary:** One filing type first; later tickets expand result/market/holding coverage. No unsupported assertion of complete historical data.

<a id="gs-04"></a>

## GS-04 — Produce traceable financial metrics from a result document

**Milestone:** M1  
**Status:** Complete — see [verification evidence](docs/GS-04-verification.md)  
**Blocked by:** [GS-03](#gs-03)  
**Spec coverage:** S03, S05, S07, S16

**What to build:** Open a result document and see normalized financial facts and independently verified growth, margin, leverage and cash-flow metrics in the snapshot and detailed note.

**Acceptance criteria**

- [x] Extract values with page/table locators and versioned units, fiscal periods and consolidated/standalone scope.
- [x] Compute the baseline metric catalogue through deterministic services, preserving formula/input IDs.
- [x] Handle nulls, scaling, zero denominators and incompatible periods visibly; never silently mix account scope.
- [x] Use the authenticated adapter for Financial Analysis interpretation with evidence validation; reject unsupported numeric statements.

**Validation:** Hand-checked financial golden data including lakh/crore scaling, restatement, negative/zero cases, plus schema/evidence checks on agent output.

**Scope boundary:** Baseline ratios and financial interpretation; valuation scenarios are GS-07. Expand formulas as independent tested behaviours, not one unbounded catalogue.

<a id="gs-05"></a>

## GS-05 — Refresh changed evidence and resume interrupted analysis

**Milestone:** M1  
**Status:** Complete — see [verification evidence](docs/GS-05-verification.md)  
**Blocked by:** [GS-04](#gs-04)  
**Spec coverage:** S02, S04, S06, S07

**What to build:** Update a researched ticker, reuse unchanged work and recover an interrupted LangGraph run from persisted SQLite state.

**Acceptance criteria**

- [x] Fingerprint evidence, prompt/model, schema, formula and policy versions; unchanged nodes show reused status.
- [x] A changed filing reruns dependent financial/report work while unrelated stored context remains intact.
- [x] Interrupt after one completed node and resume without repeating accepted side effects; changed input creates a successor manifest.
- [x] Expose node status, retries, cancellation and partial results; enforce bounded dependency-safe parallelism.

**Validation:** Instrumented integration test asserting executed node sets, parallel prerequisites, crash/resume and idempotent report publication.

**Scope boundary:** Establish generic orchestration behaviour using the existing slice; later specialist tickets register their real dependencies.

<a id="gs-06"></a>

## GS-06 — Add business, industry, competitor and moat research

**Milestone:** M2  
**Status:** Complete — see [verification evidence](docs/GS-06-verification.md)  
**Blocked by:** [GS-05](#gs-05)  
**Spec coverage:** S03, S07, S08

**What to build:** A company snapshot links to evidence-backed business, industry and peer analysis, followed by a moat assessment.

**Acceptance criteria**

- [x] Business Quality describes segments, economics and drivers with cited evidence.
- [x] Industry and Competitor outputs identify comparability limits and source periods; missing peer coverage is visible.
- [x] Business/Industry/Competitor run independently where possible; Moat waits for the inputs it declares.
- [x] Persist versioned schema-valid reports and include condensed results in the snapshot and Obsidian.

**Validation:** Evidence-grounded fixtures for one company/peer set, unsupported-claim rejection and dependency/invalidation test.

**Scope boundary:** Baseline specialist depth for a bounded company fixture; no full-market peer crawler.

<a id="gs-07"></a>

## GS-07 — Connect earnings, management claims, valuation and risk

**Milestone:** M2  
**Status:** Complete — see [verification evidence](docs/GS-07-verification.md)  
**Blocked by:** [GS-06](#gs-06)  
**Spec coverage:** S05, S07, S08

**What to build:** A new result refreshes earnings interpretation, management promise tracking, valuation scenarios and the risk section of the company report.

**Acceptance criteria**

- [x] Track dated management claims with target period and pending/met/missed/partial/unverifiable status supported by later evidence.
- [x] Earnings comparisons use compatible periods; absent consensus estimates are labelled unavailable rather than invented.
- [x] Valuation uses deterministic scenario calculations, explicit assumptions and sensitivity; unsuitable metrics are not-applicable.
- [x] Management and Risk report governance and material risks; affected outputs refresh after a result while historical claim states remain available.

**Validation:** Golden valuation scenarios, a promise-to-result fixture spanning two dates, absent-estimate case and a risk propagation integration test.

**Scope boundary:** Baseline versions of four specialist responsibilities; use shared schema and publication services. If implementation exceeds one working context, split by user-visible report section retaining this acceptance contract.

<a id="gs-08"></a>

## GS-08 — Show dated ownership and scheme-level institutional history

**Milestone:** M2  
**Status:** Complete — see [verification evidence](docs/GS-08-verification.md)  
**Blocked by:** [GS-05](#gs-05)  
**Spec coverage:** S03, S07, S09

**What to build:** Open institutional activity for a stock and compare aggregate ownership, named holders and MF schemes across disclosed periods.

**Acceptance criteria**

- [ ] Fetch or import representative primary ownership and scheme disclosures; record coverage, holder IDs, publication times and provenance.
- [ ] Compare promoter/FII/DII, named holders, pledge, scheme shares and percentages across comparable periods.
- [ ] Identify entry/exit/accumulation only when coverage supports it; handle missing disclosure, identity ambiguity and denominator/action changes.
- [ ] Display linked Shareholding and Institutional Flow reports, raw comparison values and missing-source state.

**Validation:** Two-period golden holdings data, scheme rename/absent-report/corporate-action cases and real-source coverage smoke check.

**Scope boundary:** No inference of exact trade execution from periodic holdings; no claim that unavailable named-holder history is complete.

<a id="gs-09"></a>

## GS-09 — Add dated news and material catalysts

**Milestone:** M2  
**Status:** Complete — see [verification evidence](docs/GS-09-verification.md)  
**Blocked by:** [GS-05](#gs-05)  
**Spec coverage:** S03, S07, S08

**What to build:** See deduplicated news and filing events with publication times, evidence links and their reported relevance to the company.

**Acceptance criteria**

- [ ] Acquire primary material filings and a documented supporting news source or manual fallback.
- [ ] Deduplicate syndications without merging distinct events; preserve original availability time and retrieval time.
- [ ] News/Catalyst output distinguishes fact, source assertion and inference.
- [ ] New material events invalidate relevant downstream outputs; source outages show gaps without deleting previous events.

**Validation:** Duplicate and revised-event fixtures, misleading document-instruction fixture, provider failure and incremental-update integration.

**Scope boundary:** Current event coverage first; historical event features require GS-12 eligibility.

<a id="gs-10"></a>

## GS-10 — Publish independent debate, scores and the complete snapshot

**Milestone:** M2  
**Status:** Complete — verified locally ([evidence](docs/GS-10-verification.md))  
**Blocked by:** [GS-07](#gs-07), [GS-08](#gs-08), [GS-09](#gs-09)  
**Spec coverage:** S07, S08, S16

**What to build:** Read a compact company snapshot with independent bull/bear cases, a judged thesis, category scores and transparent confidence.

**Acceptance criteria**

- [ ] Bull and Bear receive the same underlying evidence bundle without prior thesis or the other case; Judge receives both afterward.
- [ ] Investment Thesis synthesizes adjudicated evidence; Report Generation links every material number and claim.
- [ ] Implement a versioned scoring/confidence policy with justified defaults, explicit weights, coverage and missing-category handling.
- [ ] Show all required snapshot fields and links to detailed agent reports, including partial/pending trading state until those features exist.

**Validation:** Inspect actual input manifests for independence; test aggregation against independent expected values, missing categories and unsupported citations; render complete/partial UI states.

**Scope boundary:** Do not treat earlier example score weights as confirmed or confidence as a forecast probability.

<a id="gs-11"></a>

## GS-11 — Inspect daily market data and corporate-action adjustments

**Milestone:** M3  
**Status:** Complete — verified locally ([evidence](docs/GS-11-verification.md))  
**Blocked by:** [GS-03](#gs-03)  
**Spec coverage:** S03, S05, S10

**What to build:** View a stock's raw daily prices, adjusted series and corporate actions with provider coverage and quality diagnostics.

**Acceptance criteria**

- [ ] Acquire/import dated OHLCV and benchmark data with exchange sessions, security aliases and raw-source evidence.
- [ ] Preserve raw values and versioned adjustment factors; cover splits, bonus and dividends with golden expected results.
- [ ] Represent rights/merger/demerger terms and reject affected segments when terms are insufficient; do not apply price factors to total financials.
- [ ] Show gaps, duplicate bars, suspensions, listing coverage and raw/adjusted comparison in the research dashboard.

**Validation:** Hand-worked split/dividend/bonus series, complex-action blocked case, invalid OHLCV and representative live retrieval.

**Scope boundary:** No simulation yet; this slice delivers directly inspectable market evidence.

<a id="gs-12"></a>

## GS-12 — Build and inspect point-in-time feature snapshots

**Milestone:** M3  
**Status:** Complete — verified locally ([evidence](docs/GS-12-verification.md))  
**Blocked by:** [GS-04](#gs-04), [GS-08](#gs-08), [GS-09](#gs-09), [GS-11](#gs-11)  
**Spec coverage:** S04, S10

**What to build:** Select a historical decision time and inspect which market and research features were eligible then.

**Acceptance criteria**

- [ ] Store effective, public-availability and ingestion timestamps separately and use availability-aware joins.
- [ ] Exclude late releases/restatements until available; define conservative handling for date-only publication evidence.
- [ ] Retrospective LLM outputs cannot silently become historical features; feature lineage records transformation and data vintage.
- [ ] Show included/excluded features with reasons, universe/listing limits and reproducible dataset manifest.

**Validation:** Deliberately future-dated earnings/holding/event fixtures must leave earlier features unchanged; same-day cutoff and restatement boundary checks.

**Scope boundary:** Only historically supportable features are eligible. Incomplete coverage cannot be filled with today's knowledge.

<a id="gs-13"></a>

## GS-13 — Backtest one approved strategy against an independent ledger

**Milestone:** M3  
**Status:** Complete — verified locally ([evidence](docs/GS-13-verification.md))  
**Blocked by:** [GS-12](#gs-12)  
**Spec coverage:** S10, S16

**What to build:** Choose one approved template and inspect a reproducible historical trade ledger, costs, performance and benchmark comparison.

**Acceptance criteria**

- [x] Version rule, data manifest, decision/fill timing and cost/slippage policy; choose and document a compatible simulation engine and license.
- [x] Implement the proposed daily-bar next-session-fill semantics with explicit gap, missing-bar and stop/target ambiguity handling.
- [x] Show trades and defined performance measures in UI and a detailed Obsidian experiment report.
- [x] Match a small independently hand-worked trade/cash ledger; record all input assumptions so rerunning reproduces outputs.

**Validation:** Golden ledger with gaps, costs, split/dividend treatment, simultaneous stop/target and unavailable metrics; compare engine output to expected cash/positions.

**Scope boundary:** One template initially; do not assume VectorBT provides the project's validation policy.

<a id="gs-14"></a>

## GS-14 — Explore controlled strategy variations and validate them

**Milestone:** M3  
**Status:** Complete — verified locally ([evidence](docs/GS-14-verification.md))  
**Blocked by:** [GS-13](#gs-13)  
**Spec coverage:** S10, S11, S16

**What to build:** Generate bounded variations of approved strategy families and see each candidate accepted, rejected or marked insufficient evidence.

**Acceptance criteria**

- [x] Register all eight approved families with allowlisted parameter ranges and required feature types; unsupported data makes a candidate ineligible.
- [x] Persist every experiment and search budget; separate train/tuning from untouched out-of-sample evaluation and walk-forward windows.
- [x] Define versioned thresholds for sample size, costs/slippage stress, sensitivity and applicable robustness checks before promotion.
- [x] All required gates must pass; modifying a strategy creates a new version and invalidates its earlier promotion.

**Validation:** Known failing/insufficient/passing fixtures; assert no holdout data enters tuning, all experiments persist and one failed mandatory gate prevents promotion.

**Scope boundary:** Thresholds require justification in the implemented policy. A real-data run may legitimately accept no strategies.

<a id="gs-15"></a>

## GS-15 — Paper trade a validated strategy and reconcile after restart

**Milestone:** M4  
**Status:** Complete — verified locally ([evidence](docs/GS-15-verification.md))  
**Blocked by:** [GS-14](#gs-14)  
**Spec coverage:** S12, S16

**What to build:** An accepted strategy produces simulated decisions and fills in its own virtual portfolio, with cash and holdings visible over successive sessions.

**Acceptance criteria**

- [x] Only a validated frozen version can activate; persist decision, pending order, fill, fee, cash and mark records.
- [x] Define capital, sizing and risk-limit configuration; enforce available cash and position constraints.
- [x] Use idempotent event IDs; duplicate market events and restart do not create extra fills.
- [x] Missing/stale prices prevent fills; corporate actions update the book and uncertain actions pause the affected operation.

**Validation:** Independent multi-session cash/holdings ledger including duplicate event, crash/retry, dividend/split and insufficient-cash cases.

**Scope boundary:** No broker adapter. Passing synthetic validation fixtures demonstrate mechanics without claiming profitable live strategies.

<a id="gs-16"></a>

## GS-16 — Combine strategy books under a shared capital policy

**Milestone:** M4  
**Status:** Complete — verified locally ([evidence](docs/GS-16-verification.md))  
**Blocked by:** [GS-15](#gs-15)  
**Spec coverage:** S12, S16

**What to build:** Compare independent strategy results with a separately capitalized combined portfolio that handles competing signals and risk limits.

**Acceptance criteria**

- [x] Maintain separate capital/accounting for individual books and the combined book.
- [x] Version allocation, shared exposure limits, sizing and conflict precedence; show why an order was reduced or rejected.
- [x] Apply fills and fees to the correct book; combined results reconcile to its own ledger, not a sum of independent returns.
- [x] Display current holdings, cash, drawdown and strategy attribution with their assumptions.

**Validation:** Two-strategy conflicting-signal golden ledger, shared-cash cap and allocation changes with preserved previous policy.

**Scope boundary:** Default allocation policy is an implementation proposal; no portfolio optimization engine is required.

<a id="gs-17"></a>

## GS-17 — Monitor paper degradation and replay missed sessions

**Milestone:** M4  
**Status:** Complete — verified locally ([evidence](docs/GS-17-verification.md))  
**Blocked by:** [GS-16](#gs-16)  
**Spec coverage:** S11, S12

**What to build:** After downtime, paper books catch up in time order and show whether an active strategy needs revalidation.

**Acceptance criteria**

- [x] Replay only eligible historical sessions using frozen strategy/policy and then-available inputs; mark replayed events.
- [x] Do not let fresh thesis information create retrospective fills; preserve original signals and event lineage.
- [x] Persist degradation thresholds and reasons; pause new entries or queue revalidation without rewriting earlier results.
- [x] Show backtest versus paper performance with sample sizes and restart-safe processing.

**Validation:** Multi-day downtime fixture, late-disclosure leakage test, repeated replay and degradation-trigger test.

**Scope boundary:** No guarantee of continuous execution while the laptop is asleep; GS-18 schedules the catch-up.

<a id="gs-18"></a>

## GS-18 — Keep watchlist research and paper books current on schedule

**Milestone:** M5  
**Status:** Complete — verified locally ([evidence](docs/GS-18-verification.md))  
**Blocked by:** [GS-10](#gs-10), [GS-17](#gs-17)  
**Spec coverage:** S02, S06, S13, S16

**What to build:** A persisted local schedule refreshes researched stocks and paper books and shows last success, next check and recoverable failures.

**Acceptance criteria**

- [x] Daily market/news/material checks, monthly MF and quarterly results/shareholding jobs persist in SQLite with timezone-aware times.
- [x] Poll for actual disclosures and retry unavailable releases; manually requested updates use the same pipeline immediately.
- [x] Prevent duplicate/overlapping jobs; restart coalesces research work and invokes chronological paper catch-up.
- [x] Expose auth/rate-limit/source/offline states; deterministic branches continue when reasoning waits and all due work resumes safely.

**Validation:** Fake-clock schedule tests across month/quarter boundaries, missed-job restart, overlap prevention and auth-pause integration.

**Scope boundary:** Application scheduler only; OS-startup service installation is later.

<a id="gs-19"></a>

## GS-19 — Deliver material alerts to dashboard and Obsidian

**Milestone:** M5  
**Status:** Complete — verified locally ([evidence](docs/GS-19-verification.md))  
**Blocked by:** [GS-18](#gs-18)  
**Spec coverage:** S08, S13

**What to build:** Receive one traceable alert for a material thesis, ownership or paper-risk change in both local interfaces.

**Acceptance criteria**

- [x] Version severity and materiality rules, default to material events and expose configuration.
- [x] Include event evidence, comparison baseline, timestamp and next action in each alert.
- [x] Deduplicate repeated jobs while preserving distinct revisions; acknowledgements persist across restart.
- [x] Publish the Obsidian alerts note through the recoverable artifact pipeline and preserve user-authored text.

**Validation:** Repeated-event, changed-event, severity-filter and interrupted dual-destination publication tests; inspect UI and note output.

**Scope boundary:** No email, Telegram or desktop push requirement in V1.

<a id="gs-20"></a>

## GS-20 — Inspect corrections and restore consistent research history

**Milestone:** M5  
**Status:** Complete — verified locally ([evidence](docs/GS-20-verification.md))  
**Blocked by:** [GS-10](#gs-10), [GS-19](#gs-19)  
**Spec coverage:** S04, S15

**What to build:** Correct a fact, compare old and current research, and restore a consistent database/vault backup.

**Acceptance criteria**

- [x] A correction retains previous value, evidence, reason and timestamp and invalidates affected future outputs.
- [x] Old report manifests and historical feature vintages remain reconstructable; corrections do not silently rewrite historical fills.
- [x] Detect user vault edits and use safe generated-section updates/conflict artifacts.
- [x] Export a consistent DB-plus-vault backup manifest and restore to a temporary location with verified source/artifact references.

**Validation:** Correction-to-report integration, user edit conflict, publication crash recovery and actual backup/restore rehearsal.

**Scope boundary:** Use isolated test vaults for destructive restore tests; no migration of synced sources.

<a id="gs-21"></a>

## GS-21 — Review GitHub improvements without automatic integration

**Milestone:** M5  
**Status:** Complete — verified locally ([evidence](docs/GS-21-verification.md))  
**Blocked by:** [GS-19](#gs-19)  
**Spec coverage:** S14

**What to build:** Inspect a proposal from a monitored repository or discovered candidate, its test evidence and an approval decision tied to the exact change.

**Acceptance criteria**

- [x] Monitor configured whitelist and bounded discovery; store revision, license, relevance and source links.
- [x] Persist proposal states through isolated test evidence and awaiting-approval; display in admin UI and a local report.
- [x] Integration requires explicit approval for the exact tested diff/revision; changed content invalidates prior approval.
- [x] Routine research cannot modify production code; failed/rejected proposals stay auditable and duplicate upstream events are deduplicated.

**Validation:** Mock upstream update through proposal lifecycle, changed-diff invalidation and attempted unapproved-integration rejection.

**Scope boundary:** Do not automatically copy upstream code. One representative proposal proves the workflow; baseline operation need not integrate any change.

<a id="gs-22"></a>

## GS-22 — Demonstrate V1 on real sources and complete operational handoff

**Milestone:** M5  
**Status:** Complete — verified locally ([evidence](docs/GS-22-verification.md))  
**Blocked by:** [GS-20](#gs-20), [GS-21](#gs-21)  
**Spec coverage:** S01, S15

**What to build:** Run the complete ticker-to-research-to-validation-to-paper workflow with real-source coverage recorded, then demonstrate update and recovery.

**Acceptance criteria**

- [x] Run the S15 acceptance scenarios and attach reproducible manifests, golden test results and live-source smoke evidence.
- [x] Demonstrate core specialist reports, institutional history, independent debate, point-in-time backtest and incremental update.
- [x] Show paper mechanics with a justified accepted candidate or explicitly labelled passing fixture when real candidates fail; never force real-data promotion.
- [x] Document install/start/stop, supported client/runtime versions, vault setup, auth recovery, source limits, backup/restore and known limitations; confirm no broker submission path.

**Validation:** Full integration run, production UI inspection and required unit/integration/golden/PIT/schema suites. Acceptance records distinguish fixture demonstrations from real outcomes.

**Scope boundary:** Release verification and handoff, not a substitute for tests in earlier tickets. All V1 dependencies must be complete.

<a id="gs-23"></a>

## GS-23 — Discover NSE candidates and queue explainable research

**Milestone:** Phase 2  
**Status:** Complete — see [verification evidence](docs/GS-23-verification.md)  
**Blocked by:** [GS-22](#gs-22)  
**Spec coverage:** S01, S09, S10

**What to build:** Screen an explicitly covered NSE universe using fundamentals, accumulation and momentum, and inspect candidate reasons before queueing research.

**Acceptance criteria**

- [x] Define dated universe coverage and screening policy; missing metrics do not pass filters silently.
- [x] Show candidate evidence and ranking components; discovery does not create real orders.
- [x] Selected candidates enter the existing persistent research queue without duplicate company records.
- [x] Record data/coverage limitations and prohibit unsupported whole-market performance claims.

**Validation:** Small dated-universe fixture with missing/delisted securities, screening thresholds and queue deduplication.

**Scope boundary:** Explicit Phase 2; not a V1 release blocker.

<a id="gs-24"></a>

## GS-24 — Start the local application automatically when requested

**Milestone:** Later  
**Status:** Complete — see [verification evidence](docs/GS-24-verification.md)  
**Blocked by:** [GS-22](#gs-22)  
**Spec coverage:** S13

**What to build:** An optional OS-startup integration launches the local scheduler and dashboard service with visible status.

**Acceptance criteria**

- [x] Provide opt-in setup and reversible removal appropriate to the host OS.
- [x] Restart uses existing persisted jobs without duplication and reports failures locally.
- [x] Do not assume execution while the laptop is asleep; existing catch-up semantics remain in force.
- [x] Document start/stop and recovery without embedding credentials in startup configuration.

**Validation:** Host-specific startup/stop/restart and removal verification in an authorized setup.

**Scope boundary:** Later deployment convenience; not required for V1.

<a id="gs-25"></a>

## GS-25 — Replace fixture-first discovery with official NSE identity coverage

**Milestone:** Phase 2  
**Status:** Complete — see [verification evidence](docs/GS-25-verification.md)  
**Blocked by:** [GS-23](#gs-23)  
**Spec coverage:** S01, S03, S09, S10, S17

**What to build:** Make the dated official NSE equity directory the default discovery universe and join it conservatively to saved local screening evidence.

**Acceptance criteria**

- [x] Record official directory source URL, retrieval time, content hash, active-security count and same-day cache behavior.
- [x] Count companies without saved financial, ownership or real adjusted-market inputs as unassessed; missing inputs never become zero or fixture values.
- [x] Rank only complete locally evidenced companies and preserve evidence IDs, periods, thresholds and research-only queue behavior.
- [x] Label stale fallback and prohibit cross-sectional or historical performance claims unsupported by the collected evidence.

**Validation:** Validated two-security directory fixture, cache/stale paths, complete real-shaped evidence join, queue handoff and live saved-directory smoke run.

**Scope boundary:** Official identity coverage plus local evidence join. Bulk historical market, financial-result and ownership acquisition remain separate data-provider work.

<a id="gs-26"></a>

## GS-26 — Load validated official NSE price history

**Milestone:** Phase 2  
**Status:** Complete — see [verification evidence](docs/GS-26-verification.md)  
**Blocked by:** [GS-11](#gs-11), [GS-25](#gs-25)  
**Spec coverage:** S03, S05, S10, S17, S18

**What to build:** Download, validate and cache official NSE CM UDiFF daily bhavcopies and NIFTY 50 closes, then materialize an adjusted 64-session history for locally evidenced companies.

**Acceptance criteria**

- [x] Validate ZIP and CSV structure, exact session identity, CM/STK/EQ records, OHLCV constraints, ISINs and duplicate symbols before storing a session.
- [x] Retain source URLs, separate content hashes, retrieval times and exact aligned session dates; saved sessions survive restart and are not downloaded twice.
- [x] Materialize only companies with completed financial and ownership evidence, using current official directory identity and explicit official corporate-action coverage.
- [x] Reuse the GS-11 adjustment/quality pipeline, expose gaps instead of assuming clean action history, and reuse an unchanged canonical market result on repeated refreshes.
- [x] Show progress and results in the discovery dashboard and publish an immutable coverage report.

**Validation:** Parser rejection tests, 64-session integration fixture, API idempotency/schema checks, cache and materialization reuse checks, frontend production build and a live official NSE archive run.

**Scope boundary:** End-of-day price and benchmark history for locally evidenced targets. Bulk financial-result and ownership acquisition remain separate provider work.

<a id="gs-27"></a>

## GS-27 — Load official financial and ownership evidence

**Milestone:** Phase 2  
**Status:** Complete — see [verification evidence](docs/GS-27-verification.md)  
**Blocked by:** [GS-25](#gs-25)  
**Spec coverage:** S03, S04, S09, S10, S17, S19

**What to build:** Load a bounded symbol batch from official NSE integrated-financial and shareholding catalogs, validate linked XBRL, and expose traceable screening metrics.

**Acceptance criteria**

- [x] Accept one to ten explicit current-directory symbols and use bounded concurrency; the dashboard defaults to BEL, HAL and BHEL.
- [x] Validate XBRL shape, safety, identity, period and required facts; retain source hashes and explicit per-symbol coverage gaps.
- [x] Compare current-quarter revenue with the same quarter a year earlier, calculate current operating margin, and compare consecutive-quarter aggregate FII plus DII ownership.
- [x] Persist source periods and metrics, join newer evidence into discovery and preserve missing market evidence instead of manufacturing momentum.
- [x] Recover queued work, deduplicate request keys, expose API/dashboard progress and publish an immutable coverage report.

**Validation:** Hand-built XBRL parser cases, same-quarter selector regression, bounded service/API integration, discovery join, frontend production build and a live official NSE run for BEL, HAL and BHEL.

**Scope boundary:** Structured consolidated non-bank layouts and aggregate institutional ownership for an explicit bounded batch. Named-holder identity reconciliation, broad directory crawling and corporate-action coverage for new symbols remain later work.

## Confirmed-decision coverage

| Decisions | Delivery tickets |
|---|---|
| Q1–Q3 | GS-02, GS-03, GS-10, GS-13–GS-17, GS-22 |
| Q4–Q6 | GS-01–GS-04, GS-20 |
| Q7 | GS-13–GS-17 |
| Q8–Q9 | GS-05, GS-10 |
| Q10–Q12 | GS-03, GS-18, GS-20 |
| Q13–Q14 | GS-08, GS-09, GS-12 |
| Q15–Q16 | GS-10 |
| Q17–Q18 | GS-14 |
| Q19 | GS-15, GS-16 |
| Q20–Q21 | GS-10, GS-20 |
| Q22–Q23 | GS-21 |
| Q24–Q26 | GS-02, GS-05, GS-20 |
| Q27–Q28 | GS-03, GS-05, GS-10 |
| Q29–Q31 | GS-02, GS-18, GS-19 |
| Q32 | GS-23, GS-25, GS-26, GS-27 — Phase 2 |
| Q33 | GS-11–GS-13, GS-15 |
| Q34 | GS-21; common completion contract |
| Q35–Q36 | GS-02, GS-22 |
| Q37 | GS-05 |
| Q38–Q39 | GS-01, GS-02; every subsequent UI feature |
| Q40 | GS-18; GS-24 later |
| Q41 | GS-19 |
| Q42 | GS-03, GS-08, GS-09, GS-11 |
| Q43 | Every ticket's validation; GS-22 release acceptance |

## Next implementation action

GS-27 expands current financial and ownership assessment to BEL, HAL and BHEL. The next coverage ticket should acquire official corporate-action evidence for the newly assessed symbols so cached bulk prices can be adjusted and materialized without assuming a clean history.

The user authorized the real NSE data-coverage extension after GS-24. These records claim directory-wide identity coverage and bounded three-symbol metric coverage only; they do not claim directory-wide screening coverage, investment performance, a production deployment or an app model/mode change. `docs/PROJECT-CHECKPOINT.md` was refreshed after GS-27 and is next due after GS-30.
