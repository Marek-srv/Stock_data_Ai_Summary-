# graph_stock compact project checkpoint

Updated after GS-27 on 28 September 2026. Refresh this file after every three further completed builds.

## Frozen design

- Local NSE-only equity research OS with no broker execution.
- Python/FastAPI backend, React/Vite dashboard and LangGraph research orchestration.
- SQLite stores structured facts, source hashes, checkpoints, experiments, paper portfolios, schedules, alerts, history and discovery. Obsidian-compatible Markdown stores detailed immutable research.
- Deterministic Python owns material calculations, point-in-time joins, simulation, validation, accounting and gates. Signed-in Codex reasoning is optional and explicit; no API key is a core dependency.
- Official-directory coverage, saved metrics and candidate eligibility are separate counts. Missing evidence never becomes zero or a fixture value.
- `sources/` remains read-only. Fixture results demonstrate mechanics and do not establish investment performance.

## Completed frontier

GS-01 through GS-27 are implemented and locally verified. Current project version is 0.27.0.

- GS-01–GS-10: authenticated diagnostic, persistent research, public filing collection, traceable financials, resumable graph, specialists, ownership/news, debate, judging and scoring.
- GS-11–GS-17: market/action normalization, point-in-time features, deterministic backtesting, bounded validation, independent/combined paper books and degradation controls.
- GS-18–GS-24: persisted scheduling, alerts, corrections, backup/restore, approval-gated improvements, V1 acceptance, explainable discovery and optional macOS startup.
- GS-25: official NSE equity directory with 2,601 active securities in the latest saved refresh.
- GS-26: 64 official CM UDiFF/NIFTY sessions cached; 158,614 validated EQ rows in the verified window.
- GS-27: bounded official financial/shareholding XBRL refresh; BEL, HAL and BHEL have validated Q1 FY27 metrics and quarterly institutional changes.

## Current runtime boundaries

- Directory identity coverage is broad; current complete financial/ownership screening evidence covers three symbols.
- BEL has a real adjusted 64-session market history. HAL and BHEL remain without materialized momentum because official corporate-action coverage for their price window has not been acquired.
- The structured financial parser supports comparable consolidated non-bank layouts. Unsupported taxonomies, missing periods and identity mismatches become explicit gaps.
- Discovery currently returns zero eligible candidates. It makes no profitability or whole-market screening-performance claim.
- Scheduler jobs run only while the local FastAPI process and Mac are awake. Optional login startup remains macOS-only and disabled until installed.
- Paper books remain simulated and have no broker adapter or order-submission route.

## Important modules

- `graph_stock/app.py`: app assembly, recovery, localhost write guard and routes.
- `graph_stock/orchestration.py`: dependency-aware LangGraph workflow and reuse/resume.
- `graph_stock/bulk_market.py`: official daily price/index cache and adjusted materialization.
- `graph_stock/bulk_evidence.py`: bounded official financial/shareholding catalog and XBRL validation.
- `graph_stock/discovery.py`: official-directory join, evidence ranking and research queue.
- `graph_stock/market_data.py`, `features.py`, `backtest.py`, `validation.py`: normalization through promotion.
- `graph_stock/paper.py`, `combined.py`: independent/combined accounting and reconciliation.
- `frontend/src/Discovery.jsx`: directory, evidence and market-history coverage controls.

## Verification state

- GS-26 live run saved 64 sessions from 15 June through 11 September 2026 and reused its canonical BEL market result.
- GS-27 live run `c88a69bd-7151-48ea-8143-3a982fcc9aea` completed BEL, HAL and BHEL with no gaps after the same-quarter comparison correction.
- Latest discovery assessed 3 of 2,601 active identities and excluded each with exact rule or missing-momentum evidence.
- Frontend production build passed with 17 transformed modules.
- Full Python suite result is recorded in `docs/GS-27-verification.md`.

## Next dependency

Define GS-28 for official corporate-action coverage for newly assessed symbols. It should reuse GS-11 adjustment semantics and GS-26 cached bars, block ambiguous events, and materialize HAL/BHEL momentum only after the complete 64-session window is covered.
