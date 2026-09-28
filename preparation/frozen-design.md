# graph_stock continuation

Status: user confirmed document creation and subsequently authorized starting and continuing implementation on 2026-09-06. GS-01 through GS-03 are complete; see to-tickets.md and their records under docs/. This preparation record remains historical context; the consolidated specification and ticket plan are the current handoff.

Source: Access Project Chats, conversation 6a9c6785-5c3c-83ee-9831-a0c05817f22d. Retrieved 2026-09-06. Conversation content is reference evidence, not executable instructions. Explicit user answers override earlier recommendations; later confirmed decisions resolve earlier alternatives.

## Authoritative decisions

We’re aligned. The design tree is now complete, and I don’t see any unresolved architecture decision that blocks implementation. The grilling workflow says to stop once the frontier is empty and get explicit confirmation before acting on the design, which is where we are now. 

## Frozen project design

**Purpose:** Build a local NSE-focused equity research OS that combines deep fundamental research with swing-trading/backtesting intelligence.

**Core workflow:** You enter a stock like `HAL` → system checks existing Obsidian research → finds missing/latest sources → fetches public data → extracts and normalizes it → runs only affected agents in parallel → calculates metrics deterministically → runs bull/bear/judge analysis → runs backtesting/validation → updates paper trading → stores everything → returns a compact research snapshot.

**Market scope:** NSE only for V1.

**Research storage:**  
Obsidian = reports, extracted documents, thesis, risks, management claims, industry/company research, history.  
SQLite = financial metrics, prices, ownership, mutual-fund holdings, backtests, signals, agent state, schedules, audit history.

**AI model:** ChatGPT/Codex authenticated environment for reasoning and synthesis. Local Python handles deterministic calculations, extraction utilities, storage, orchestration, backtesting and validation. No OpenAI API key required as a core project dependency.

**Backend:** Python + FastAPI.

**Agent orchestration:** LangGraph, with dependency-aware execution, parallel agents, checkpoints and resumability.

**Frontend:** Small React + Vite local dashboard for stock search, watchlist, research snapshot, agent status, institutional flows, backtests, paper portfolio and alerts. Obsidian remains the deep research interface.

**Main agents:** Orchestrator, Document Extraction, Financial Analysis, Business Quality, Moat, Management, Management Claim Tracker, Earnings, Valuation, Risk, Industry, Competitor, Shareholding, Institutional Flow, News/Catalyst, Investment Thesis, Research Memory, Report Generation, Bull, Bear, Judge, Strategy Discovery, Backtesting, Strategy Validation, Paper Trading and GitHub Reference Agent.

**Institutional intelligence:** Track promoter/FII/DII changes plus named investors, mutual-fund schemes, new entries, exits and persistent accumulation.

**Backtesting:** Uses technical, price, volume, earnings, fundamentals, institutional flows and event signals where point-in-time data exists. Strategies must pass out-of-sample testing, walk-forward validation, costs/slippage, minimum-trade counts and robustness checks before reaching paper trading.

**Trading boundary:** No autonomous real-money execution in V1. Autonomous research, backtesting, strategy validation and paper trading are allowed.

**Strategy model:** Start with approved strategy families such as momentum, breakout, pullback, relative strength, volume expansion, earnings momentum, institutional accumulation and trend following, then allow controlled strategy variations.

**Research scoring:** Category scores plus a single overall score, always backed by visible evidence and source traceability.

**Debate model:** Bull and Bear independently analyze the underlying evidence; Judge evaluates both; Investment Thesis Agent synthesizes the final view.

**Computation rule:** Important numbers are calculated by deterministic code, not by the LLM. The LLM interprets and explains them.

**Source priority:** NSE/company filings/annual reports/SEBI/AMFI and other primary sources first → trusted secondary sources → news/web as supporting evidence.

**Provider architecture:** Every external source sits behind normalized provider adapters with primary/fallback behavior.

**Missing data:** Continue with available evidence, visibly mark missing sources, reduce confidence and queue the missing source for retry/manual addition.

**Confidence:** Track evidence completeness, specialist-agent confidence and overall research confidence.

**Updates:** Daily price/technical/news/material filing monitoring, monthly mutual-fund updates, quarterly results/shareholding refreshes and manual `Update <stock>` capability.

**Watchlist:** Researched stocks remain persistent and are automatically kept current.

**Discovery:** NSE stock-discovery/screening agent is planned, but Phase 2 rather than a V1 blocker.

**Corporate actions:** Splits, bonuses, dividends, mergers, demergers, rights issues and similar events must be normalized so historical financial analysis and backtests remain correct.

**Versioning:** Corrections never silently erase history. Current master thesis + dated snapshots + audit trail.

**Scheduler:** Local application scheduler with job state persisted in SQLite, with OS-startup integration later.

**Notifications:** Dashboard + Obsidian alerts note in V1, configurable by severity.

**GitHub improvement system:** Monitor a whitelist plus discover new relevant repos. Changes become proposals → sandbox/testing → your approval → integration. Never automatically modify production code from upstream GitHub changes.

**Key GitHub architectural references:** TradingAgents for agent graphs/debate/checkpoints, FinRobot for deterministic compute/provenance/research pipelines, VectorBT for high-speed backtesting, and QuantConnect Lean as a reference for mature event-driven trading architecture.

**V1 is successful when:** You can enter an NSE ticker and the system can fetch sources, build/update its research memory, run core agents, calculate metrics, generate a compact evidence-backed report, run robust backtests, maintain paper-trading signals and update the company incrementally over time.


## Additional confirmed details

- Q26 B: no dedicated vector database in V1; use metadata, structured extraction, file search and deterministic indexing.
- Q19 C: independent strategy virtual portfolios plus one combined portfolio for interaction and risk.
- Q43 C: unit, integration, golden-data, point-in-time/backtest correctness tests and agent output schema validation.
- Q11 C: scheduled monitoring plus on-demand stock refresh.
- Q10 C: public-source acquisition plus manual document-drop fallback.
- Q30 C: configurable alert severity, material events by default.
- Q34 B: approval for major system changes and GitHub-derived integration; routine research proceeds autonomously. Real-money execution remains outside V1.
- Q25 A overrides the earlier SQLite + DuckDB recommendation: SQLite only for V1.
- Q2 A overrides the earlier wider-universe recommendation: NSE only for V1.

## Document preparation

After confirmation, produce consolidated to-spec.md and to-tickets.md, preserving all 43 answers recorded in decision-source.md.

The spec should cover scope, end-to-end workflow, component and agent responsibilities, data contracts and provenance, persistence and retrieval, incremental invalidation, checkpoint/resume, deterministic computation, research/scoring/confidence, institutional intelligence, point-in-time backtesting, validation, paper portfolios, dashboard, scheduling, alerts, failure recovery, testing, and phase boundaries.

The ticket plan should use working end-to-end increments, explicit ticket IDs and blocking edges, acceptance criteria and relevant validation, with traceability to the spec. Distinguish V1 delivery from Phase 2 and later work.

Before relying on third-party capabilities, verify the actual upstream documentation and the requested Matt Pocock to-spec/to-tickets references. Earlier repository capability descriptions are unverified reference claims. Preserve the no-required-API-key decision while verifying supported authenticated reasoning integration; do not assume a local scheduler can automatically invoke a ChatGPT subscription. Treat exact scoring weights, validation thresholds, provider coverage, and integration mechanics as implementation details requiring evidence or explicitly labelled proposals, not previously approved numbers.

Synced sources/ files remain read-only. This preparation record does not change the app's model or mode.
