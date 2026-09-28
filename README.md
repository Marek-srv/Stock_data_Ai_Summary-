# graph_stock

A local NSE research OS with **GS-01 through GS-27 complete:** authenticated connection diagnostics, persisted research, bounded real-filing acquisition, traceable financial extraction, checkpointed specialist research, dated ownership and news, independent debate and scoring, market-data adjustments, point-in-time features, deterministic backtesting, bounded validation, reconciled paper books, chronological replay, degradation monitoring, persisted local scheduling, material alerts, reconstructable corrections, verified local backup/restore, approval-gated upstream improvement review, release acceptance, explainable discovery, optional macOS startup, official NSE identity coverage, validated bulk market history and bounded official XBRL evidence coverage.

The original HAL, BEL and BHEL research snapshots remain explicitly **fixture mode**. Real filing financials and specialist reports are separate and visibly labelled by source, fiscal period and evidence type. The implemented LangGraph slice orchestrates filing extraction, retained context, deterministic metrics, qualitative evidence, specialist reports, independent Bull/Bear cases, judging, thesis, scoring and publication. Filing acquisition, deterministic financial analysis, synthesis, refresh, backtesting, validation, paper accounting and degradation monitoring do not invoke the LLM. Financial interpretation is a separate, optional action that uses the signed-in reasoning allowance only when selected.

## Run locally

Requirements: Python 3.10+, Node.js compatible with Vite (20.19+ or 22.12+), pnpm, and a supported Codex CLI signed in with ChatGPT for the connection diagnostic. This version targets macOS/Linux, using process-group timeouts, POSIX directory operations and a file lock. Verified with Python 3.10, Node 24.19.0, pnpm 11.19.0 and Codex CLI 0.153.4 on macOS.

From this project directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
```

Build the frontend once (and again after frontend edits):

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
```

Start the local backend, which also serves the built React dashboard:

```sh
codex login status
.venv/bin/python -m uvicorn graph_stock.app:app --host 127.0.0.1 --port 8765
```

Open [the research dashboard](http://127.0.0.1:8765). The [connection diagnostic](http://127.0.0.1:8765/diagnostic) remains available separately. If the CLI is not signed in, use its normal `codex login` flow and choose ChatGPT. Do not configure an API key for this application. Stop the server with Ctrl+C in its terminal.

If `codex` is not on the terminal's PATH, set `GRAPH_STOCK_CODEX` to the installed executable's absolute path before starting the server. `GRAPH_STOCK_STATE_DIR` optionally selects a different application-state directory. Neither setting is a credential. Runtime versions used for verification are pinned in `requirements.lock`, including test dependencies.

Frontend versions are recorded in `frontend/pnpm-lock.yaml` (React 19.2.8 and Vite 8.2.2 in this build). During frontend development, keep the backend running and use `pnpm dev` from `frontend`; Vite proxies API calls to port 8765. Normal use needs only the built frontend and the one Python server.

## Fixture research and the test vault

Enter `HAL`, `BEL`, `BHEL` or a matching company name. `Bharat` deliberately returns two candidates so you can choose; unknown queries do not add watchlist entries. Successfully resolved requests add one persistent watchlist item and a dated snapshot. Additional explicit research requests create new snapshots without duplicating the company.

The default test vault is `.state/fixture-vault`. Set `GRAPH_STOCK_VAULT` before starting the server to use another dedicated test folder. The API does not accept arbitrary vault paths. Open that folder as an Obsidian vault if you want the dashboard's **Open in Obsidian** link to work; **Read research note** and **Download .md** work without Obsidian installed. This app does not change Obsidian's registration or settings.

Generated notes live under `Graph Stock/Fixtures/<symbol>/<run-id>.md` inside the configured vault. Publication uses an atomic create-without-replacement operation; existing different content is never overwritten. Each record stores its original vault destination and note hash. Changing vault configuration does not relocate older notes. A changed note is labelled modified; the original database snapshot remains immutable. Missing or inaccessible notes are shown as unavailable.

If the server stops between saving the record and publishing its note, pending publication is retried on startup. Identical already-published content is reused. Filesystem failures keep the saved snapshot available and expose a same-run retry. Symbolic-link directories and notes are rejected instead of followed outside the vault.

## Real filing collection

The dashboard's **Collect a company filing** section uses the current NSE equity directory to verify an exact ticker. Automatic document coverage is deliberately narrow: the measured sample is BEL's NSE-hosted integrated annual report for 2024–25, with a company-hosted copy as fallback. Other verified NSE equity tickers return a visible coverage gap and a manual PDF action.

Manual imports accept a PDF up to 25 MB and pass through the same validation, hashing, deduplication, SQLite storage and vault publication pipeline. When NSE identity lookup is unavailable, a manual import can continue with a clearly labelled user-asserted identity. A manually entered public date is also labelled unverified. Neither is eligible for historical signals.

Original PDFs and source metadata notes are saved below `Graph Stock/Sources/<symbol>/` in the configured vault. Metadata includes the security identity, source URL or manual origin, retrieval time, content hash, page count, parser version, availability basis and current gaps.

For a supported result layout, **Calculate financials locally** locates the consolidated balance sheet, profit-and-loss statement and cash-flow statement. It records each reported lakh value, normalized crore value, fiscal period, scope, source ID, PDF page, statement row and extractor version. The baseline catalogue calculates revenue growth, a derived operating margin, net profit margin, total borrowings to equity, operating cash conversion and free cash flow. Missing inputs, reported dashes, zero denominators and incompatible scopes, periods or units remain unavailable with a reason.

Financial snapshots and Markdown notes are saved separately below `Graph Stock/Financials/<symbol>/`. The optional interpretation button clearly indicates that it uses signed-in allowance. The adapter cannot browse or use tools, receives only validated metrics, must cite accepted metric/evidence IDs, and cannot put numbers in prose; all displayed numbers continue to come from deterministic calculations. Current measured extraction coverage is the BEL-style consolidated annual-statement layout. Unsupported manual PDFs remain preserved and return a visible coverage result.

## Dependency-aware refresh

**Run research refresh** creates an immutable input manifest and executes a LangGraph workflow. Financial extraction, retained context and qualitative evidence start after the manifest. Business Quality, Industry and Competitor run independently from the same evidence bundle; Moat waits for all three. Final publication waits for deterministic metrics, context and Moat. SQLite checkpoints use the run ID as the durable thread ID. The graph allows at most two nodes to execute concurrently.

GS-06 uses a measured historical BEL FY2025 evidence set from annual-report pages 45, 46, 48, 50 and 90. Every specialist claim must cite a permitted evidence ID and carry an evidence type and confidence label. Issuer market-position and outlook statements remain management claims. HAL and BDL peer filings are absent from this bounded run, so the Competitor report marks coverage missing and the Moat assessment remains provisional. Versioned reports are stored in SQLite and as immutable notes below `Graph Stock/Specialists/BEL/`; condensed cards appear in the refresh snapshot.

GS-07 extends the measured evidence set through PDF page 92 and adds five reports. Earnings compares compatible consolidated FY2025/FY2024 periods and marks consensus unavailable when no estimate source exists. Management Claim Tracker stores dated states per run; claims can be pending, met, missed, partial or unverifiable, and prior states remain readable. Valuation applies explicit illustrative 20x/25x/30x P/E assumptions to reported profit after tax, publishes a 3×3 earnings/multiple sensitivity, and marks per-share upside and DCF not-applicable because required inputs are absent. Management records the issuer's Board-level risk governance disclosure. Risk combines filing risks, financial metrics and valuation limitations. These reports are stored below `Graph Stock/Research/BEL/` and shown in the refresh snapshot.

GS-08 imports measured BEL ownership rows for 31 March 2024 and 31 March 2025 from issuer annual reports. It preserves disclosure, publication and ingestion dates; raw shares and percentages; stable holder and fund-house IDs; source coverage; and the share denominator. Aggregate promoter/FII/DII and matched schemes compare locally. Entry and exit stay unknown when named-holder coverage is incomplete, identity ambiguity blocks classification, and denominator or corporate-action changes make periods non-comparable. Pledge coverage is explicitly missing. Linked Shareholding and Institutional Flow notes are stored below `Graph Stock/Ownership/BEL/`.

GS-09 adds current-event coverage using a measured BEL contract example backed by an NSE announcement and a dated Ministry of Defence PIB release. Multiple sources for one canonical event are linked without merging distinct events. Changed content creates a superseding event version; outages retain earlier current events and expose a gap. Every event displays facts, source assertions and limited-confidence research inferences separately. New material versions invalidate the News/Catalyst, Risk and final-report graph outputs while independent nodes remain reusable. A manual JSON fallback and immutable notes below `Graph Stock/News/BEL/` are available. Historical event features remain deferred to GS-12.

GS-10 gives Bull and Bear the same locked evidence manifest and runs them as sibling graph nodes; Judge receives both cases afterward, followed by the Investment Thesis and score snapshot. Eight categories use a versioned equal-weight policy because no preference weights have been approved. Missing categories remain unscored and reduce the displayed denominator rather than becoming zero. Evidence completeness and research confidence are shown separately, and confidence is defined as an evidence-sufficiency index rather than a forecast probability. Immutable synthesis notes live below `Graph Stock/Synthesis/<symbol>/`. The complete dashboard snapshot includes the thesis, risks, metrics, valuation, institutional trend, missing evidence and detailed-report links, while market signal and validation fields remain explicitly unavailable or pending.

GS-11 adds an official NSE current-market adapter and a manual JSON path through the same validator. Security and NIFTY 50 OHLCV rows retain their raw values, session, source ID and evidence hash. A versioned adjustment policy handles splits, bonuses, cash dividends and complete rights terms, while mergers, demergers, rights or other actions with incomplete terms block only affected historical segments. Raw and adjusted series remain side by side; factors never alter total financial-statement values. The dashboard shows missing and duplicate sessions, suspensions, provisional intraday bars, benchmark gaps, listing coverage, aliases, unresolved identity conflicts and linked immutable notes below `Graph Stock/Market Data/<symbol>/`.

GS-12 reconstructs the feature set available at a selected historical decision time. Every candidate carries separate effective, public-availability and ingestion timestamps plus source and transformation lineage. Timestamped evidence uses its recorded instant; date-only evidence becomes eligible only after that date ends in Asia/Kolkata; month-only disclosures become eligible only after the month ends. Verified NSE filings can support deterministic historical financial metrics even when an older source record carries the pre-GS-12 deferred flag. Manual or unverified sources remain excluded. Retrospective reasoning, intraday bars and revisions without proven new availability cannot become historical features. Each immutable snapshot stores included and excluded candidates, reasons, data vintage, single-security listing limits and a reproducible dataset-manifest hash below `Graph Stock/Features/<symbol>/`.

GS-13 adds one fixed `trend-following-close-above-sma/v1` template and an in-project deterministic daily event loop. Decisions occur after close and fill only at the immediately next expected eligible session open. Missing, suspended, intraday and unusable bars cancel rather than defer an order; gap opens use the open; simultaneous stop/target touches use the stop and retain an ambiguity flag. Raw OHLC drives fills while adjusted closes drive signals. Splits/bonuses change position quantity and anchors, and dividends credit cash. Every run stores fixed cost/slippage assumptions, strategy/engine/data versions, the complete market manifest, trades, cash/position events, equity, benchmark and defined performance measures. Immutable reports live below `Graph Stock/Backtests/<symbol>/`. GS-13 performs no parameter search and grants no paper-trading eligibility.

GS-14 registers all eight approved families with required features and allowlisted parameters. The implemented trend-following family explores exactly six candidates under `bounded-grid/v1`; other families remain visibly ineligible when data or a simulator is absent. Train, tuning and untouched OOS periods have separate hashes, and candidate selection cannot access the holdout. Policy `candidate-acceptance/v1` requires sample/trade minimums, positive OOS and benchmark-relative results, drawdown control, doubled-cost survival, neighboring-parameter sensitivity, walk-forward evidence, feature support and search-budget compliance. Every gate must pass. All experiments and failed/insufficient outcomes remain in SQLite and immutable notes below `Graph Stock/Validation/<symbol>/`; changing a rule creates a new candidate and invalidates its earlier promotion basis.

GS-15 activates only an all-gates-passed frozen candidate into a separately funded paper book. Policy `independent-paper-book/v1` defines INR 100,000 starting cash, one-position and exposure limits, whole-share sizing, next-session fills and no broker execution. Decisions, pending orders, fills, fees, cash changes, marks and actions use stable event IDs and per-session transactions. Duplicate sessions cannot create extra fills; an injected mid-session crash rolls back completely; startup reconstructs cash and holdings from the ledger. Missing or stale prices block fills, splits/bonuses update shares and anchors, dividends credit cash, and uncertain actions pause the affected book. The dashboard shows cash, holdings, pending state, reconciliation and ledger detail; Markdown reports live below `Graph Stock/Paper/<symbol>/`.

GS-16 creates a separately capitalized combined paper book from at least two independent member books. Policy `equal-allocation-exit-first/v1` versions starting capital, member allocations, the shared 100% exposure ceiling, whole-share sizing and conflict precedence. Pending exits execute before entries, and any member exit rejects same-symbol entries for that decision session with an explicit reason. Fills and fees carry member attribution while cash, equity and drawdown belong only to the combined ledger. Startup compares materialized cash and positions with the combined book's own last mark and pauses a mismatch. The dashboard shows shared cash, equity, drawdown, holdings, attribution, policy assumptions and ledger details; reports live below `Graph Stock/Combined Paper/<symbol>/`.

GS-17 replays unseen historical sessions in date order for independent and combined books. Replay payloads identify the processing mode, market run and source hash; independent decisions also retain their exact adjusted-price history and frozen candidate version, while combined decisions link back to the member decision event. The catch-up API has no thesis input and rejects unknown fields. Policy `paper-degradation/v1` waits for three observed sessions, then compares paper return and drawdown with the original untouched-OOS validation metrics and sample sizes. A 10% paper drawdown or return shortfall above 15 percentage points pauses only new entries, cancels a pending entry with an audit record, keeps exits available and queues one durable revalidation request. Monitoring runs and previous validation results remain immutable and survive restart.

GS-18 runs six persisted job types under `local-persisted-scheduler/v1`: daily market, news and material checks; monthly mutual-fund checks; and quarterly results and shareholding checks. Due instants are stored as timezone-aware UTC values and displayed in Asia/Kolkata. Atomic 30-minute leases prevent overlap, manual “Run now” actions use the same pipeline, and request keys make manual retries idempotent. Disclosure jobs poll through the filing pipeline before downstream processing; unavailable releases retry after six hours. Restart marks interrupted attempts, schedules one coalesced catch-up, and daily market jobs replay independent and combined paper books. Auth, rate-limit, offline, source-wait and failure states remain separate, so one waiting job cannot block other deterministic work. The scheduler runs only while the local application process is awake.

GS-19 evaluates saved thesis revisions, comparable ownership changes and paper degradation under `alert-materiality/v1`. Material alerts at medium severity or above are delivered by default; the dashboard exposes minimum severity and material-only controls. Every alert keeps its evidence IDs, source record, comparison baseline, event time and next action. The event revision and rule version deduplicate repeated scheduler work while distinct revisions remain separate. Acknowledgements survive restart. Dashboard delivery is durable as soon as SQLite accepts the alert; immutable notes publish below `Graph Stock/Alerts/<symbol>/`. Failed note writes retry on startup, and an edited note is preserved rather than replaced.

GS-20 records extracted-number corrections as immutable superseding overlays under `research-history/v1`. Each revision retains the prior payload and evidence, corrected value and evidence, author, reason, timestamp and affected-artifact dispositions. Existing reports and historical feature vintages remain unchanged; new research and feature builds include the correction digest and apply the latest value. Current generated correction indexes preserve personal text outside managed markers and publish a conflict copy if their generated section was edited. Verified backup ZIPs contain SQLite snapshots, every vault artifact referenced by the frozen database, and a SHA-256 manifest. Restore rehearsals extract only into an isolated state folder and verify every database, artifact and restored reference.

GS-21 records allowlisted or bounded-discovery GitHub candidates under `bounded-github-review/v1`. Repository URL, exact revision, license, relevance, compatibility, expected benefit, source links and change hash form a durable proposal. The lifecycle retains isolated pass/fail evidence and explicit approval or rejection. Approval binds to the exact tested fingerprint; changed content supersedes the proposal and invalidates its decision. The service can record an integration acknowledgement only after matching test and approval records. It has no path that copies or edits project source, and every state publishes an immutable report below `Graph Stock/Improvements/`.

GS-22 completes V1 acceptance without overstating source coverage. The saved BEL public filing supports traceable financials, specialist research, institutional history, independent debate and a compact snapshot. A fresh incremental run reused unaffected nodes and reran ownership-dependent synthesis. Current NSE market coverage remains partial, so PIT, passing validation and independent/combined paper demonstrations remain explicitly labelled deterministic fixtures. The read-only release audit verifies the source hash, vault references, S15 scenario evidence and absence of broker submission routes. See [V1 acceptance](docs/GS-22-acceptance.md), the [machine-readable manifest](docs/GS-22-release-manifest.json) and [operations guide](docs/OPERATIONS.md).

GS-23 adds an explainable discovery panel and API using a dated four-security NSE fixture. Policy `fundamental-accumulation-momentum/v1` ranks complete active securities from visible fundamental, institutional-accumulation and momentum components. Missing required metrics and delisted securities are explicitly excluded. Every run records its exact universe, source, as-of date, evidence, thresholds and limitations; this fixture cannot support claims about the whole NSE market or investment performance. Eligible selections enter the existing persistent research queue idempotently and cannot create broker or paper orders. Reports publish below `Graph Stock/Discovery/`.

GS-24 adds an optional macOS LaunchAgent around the same local service. It is disabled by default, contains no credentials, preserves the existing `.state` scheduler database, writes failures below `.state/startup/`, and can be removed idempotently. The dashboard exposes read-only startup status. See [operations](docs/OPERATIONS.md#optional-macos-login-startup) before enabling it; scheduled work still cannot execute while the Mac sleeps.

GS-25 makes the official NSE equity directory the default discovery identity universe. A run records the observed date, source URL, SHA-256 and total active identities, then joins only saved traceable financial, ownership and real adjusted-market evidence. Securities lacking local inputs are counted as unassessed rather than expanded into thousands of empty cards. Synthetic price histories never satisfy the real screen. If directory refresh fails, the previous validated directory can be used only with a visible stale classification. The bundled four-security screen remains an injected offline test fixture.

GS-26 loads 64 aligned end-of-day sessions from the official NSE CM UDiFF bhavcopy and all-index daily close archives. ZIP/CSV structure, session dates, CM/STK/EQ identity, ISIN, OHLCV and duplicates are validated before each session is cached with source hashes. Only companies with completed local financial and ownership evidence are materialized, and official corporate-action coverage is required before the existing GS-11 adjustment pipeline runs. The discovery panel can start and follow the refresh; repeat runs reuse saved sessions and the same canonical market result. Immutable coverage reports live below `Graph Stock/Market Coverage/`.

GS-27 adds a bounded official XBRL evidence refresh for up to ten explicit NSE symbols; the dashboard starts with BEL, HAL and BHEL. It validates the current directory identity and linked NSE XBRL before comparing revenue with the same quarter one year earlier, calculating the current consolidated operating margin, and comparing consecutive-quarter aggregate FII plus DII ownership. Unsupported layouts and missing periods remain visible gaps. New evidence joins discovery immediately, while missing adjusted-price coverage still prevents eligibility. Reports live below `Graph Stock/Evidence Coverage/`.

Each node fingerprints the exact inputs that affect it. The manifest records evidence hash and retrieval identity plus graph, extractor, formula, schema, report, prompt, model and policy versions. Matching completed nodes are shown as `reused`. A new source reruns extraction, metrics and report publication while unrelated unchanged context can be reused. Every later run links to its predecessor as a successor manifest.

Running work can be cancelled between nodes. Failed, partial or cancelled work can resume from its existing checkpoint. A process stop changes the run back to queued at startup and continues it automatically; accepted side effects use content-addressed immutable paths, so resume cannot publish the same report twice. LangGraph's SQLite checkpoint file is `.state/langgraph-checkpoints.sqlite3`; application manifests, node state, cache entries and outputs remain in `.state/graph_stock.sqlite3`.

### Command-line research

The CLI calls the same running localhost API as the React dashboard:

```sh
.venv/bin/python -m graph_stock search Bharat
.venv/bin/python -m graph_stock research HAL
.venv/bin/python -m graph_stock watchlist
.venv/bin/python -m graph_stock show <run-id>
```

Research prints a request key before submission. Reuse it with `--request-key <uuid>` if an interrupted connection leaves the result uncertain. Repeating the same key and company returns the same run; using the key for a different company is rejected. `--no-wait` returns the accepted operation immediately. The default waits up to 30 seconds for note publication. Use the global `--server http://127.0.0.1:<port>` option before the subcommand for another local port.

Run one server process per state directory. A file lock rejects a second process to avoid corrupting run recovery. Use an authorized local terminal: a restrictive outer sandbox can prevent the client from initializing or the server from binding its port. The subprocess itself always requests Codex's read-only sandbox.

## What the check verifies

- CLI reports ChatGPT authentication; API-key authentication is rejected.
- A fixed synthetic revenue sample and a schema are sent to the CLI. The application passes no user-supplied prompt.
- The CLI runs with user configuration excluded, ChatGPT authentication required, read-only permissions and ephemeral sessions. The model is the installed client's default, not a pinned project model.
- JSON event progress is separated from the final message. Source ID, direction, precomputed growth, required fields and extra-field restrictions are validated.
- One request runs at a time, with an eight-request queue limit. A repeated request key returns the same operation; retry preserves the run ID and adds an attempt. Successful results cannot be retried into a second accepted result.
- Auth failure, usage limit, client absence, sandbox blocking, timeout, connectivity failure and invalid output have distinct safe messages. Retry is explicit rather than automatically spending more reasoning allowance.
- Interrupted work stays visible after restart and can be retried. Timeouts/cancellation terminate the child process group.

The check uses the account's Codex allowance; “no API key” does not mean unlimited or offline reasoning. The synthetic numerical growth is precomputed locally and copied by the model. This verifies the integration contract, not general financial accuracy.

## State and access

`.state/graph_stock.sqlite3` holds run ID, timestamps, safe status, attempt history, client version, auth-method label, validated synthetic result, allowed usage counters and event count. Raw stdout/stderr, credentials, reasoning text and environment secrets are not written to application storage. Codex manages its own authentication and runtime records separately.

The server binds to localhost. Host validation, same-origin write checks and a required custom header prevent ordinary cross-origin browser submissions. There is no remote-user authentication; do not expose this diagnostic on a public interface. The API accepts only UUID request keys and the fixed check operation, not executable paths or arbitrary prompts.

Fixture research adds separate `fixture_securities`, `fixture_watchlist` and `fixture_research_runs` tables in the same SQLite database. The run stores the complete fixture snapshot/evidence, generated note text and publication manifest. Fixture records are segregated from future live-source data. No personal research vault is discovered or modified automatically.

## API

| Operation | Purpose |
|---|---|
| GET /api/diagnostics | Most recent 30 checks |
| GET /api/diagnostics/{id} | Saved status, result and attempts |
| POST /api/diagnostics | Start check with JSON `request_key` UUID |
| POST /api/diagnostics/{id}/retry | Retry a failed/interrupted check |
| GET /api/securities?query=... | Resolve fixture identity or list ambiguous candidates |
| GET /api/watchlist | Companies and recent saved fixture snapshots |
| POST /api/research | Save fixture research with `query` and `request_key` |
| GET /api/research/{id} | Retrieve the persisted snapshot and note integrity |
| GET /api/research/{id}/note | Read the saved Markdown as plain text |
| GET /api/research/{id}/note?download=true | Download the note |
| POST /api/research/{id}/retry | Retry pending note publication after failure |
| GET /api/v1/startup | Read supported platform, installation state, process origin, log paths and recovery limit |
| GET/POST /api/v1/discovery | List or create a dated candidate screen |
| GET /api/v1/discovery/{id} | Inspect rankings, evidence, exclusions and limitations |
| GET /api/v1/discovery/{id}/report | Read or download the immutable discovery report |
| POST /api/v1/discovery/{id}/candidates/{security_id}/queue | Queue an eligible candidate for persistent research idempotently |
| GET /api/v1/filings | Recent filing acquisition requests |
| POST /api/v1/filings | Acquire the configured public filing for an exact NSE symbol |
| POST /api/v1/filings/import | Import a PDF through the same provenance pipeline |
| GET /api/v1/filings/{id} | Retrieve filing request state and source metadata |
| POST /api/v1/filings/{id}/retry | Retry acquisition or vault publication |
| GET /api/v1/filings/sources/{id}/pdf | Download the preserved original PDF |
| GET /api/v1/filings/sources/{id}/note | Read the generated source-evidence note |
| GET /api/v1/financials | List recent financial extraction runs |
| POST /api/v1/financials | Extract and calculate from a saved `source_id`; reasoning defaults off |
| GET /api/v1/financials/{id} | Retrieve located facts, metrics, lineage and interpretation state |
| GET /api/v1/financials/{id}/note | Read or download the immutable financial note |
| POST /api/v1/financials/{id}/retry | Retry an interrupted extraction or note publication |
| GET /api/v1/updates | List dependency-aware update runs and node states |
| POST /api/v1/updates | Start a refresh for a saved source with an idempotency key |
| GET /api/v1/updates/{id} | Inspect manifest, predecessor, nodes and partial/final outputs |
| GET /api/v1/updates/{id}/report | Read or download the immutable refresh report |
| GET /api/v1/updates/{id}/specialists/{kind} | Read or download a Business Quality, Industry, Competitor or Moat note |
| GET /api/v1/updates/{id}/research/{kind} | Read or download an Earnings, Management Claims, Valuation, Management or Risk note |
| GET /api/v1/updates/{id}/synthesis/{kind} | Read or download a Bull, Bear, Judge, Investment Thesis or Scorecard note |
| GET /api/v1/market-data | List recent market-data runs |
| POST /api/v1/market-data | Collect the current NSE market-watch row, NIFTY 50 row and recent corporate actions |
| POST /api/v1/market-data/import | Import a validated historical market-data JSON bundle |
| GET /api/v1/market-data/{id} | Inspect raw/adjusted bars, action factors and quality diagnostics |
| GET /api/v1/market-data/{id}/report | Read or download the immutable market-data report |
| GET /api/v1/bulk-market-history | List recent official NSE bulk-history refreshes |
| POST /api/v1/bulk-market-history | Load or reuse 64 validated official market sessions |
| GET /api/v1/bulk-market-history/{id} | Inspect session coverage, row counts, materialized symbols and gaps |
| GET /api/v1/bulk-market-history/{id}/report | Read the immutable bulk-history coverage report |
| GET /api/v1/bulk-evidence | List recent official financial/ownership refreshes |
| POST /api/v1/bulk-evidence | Refresh one to ten explicit NSE symbols from official XBRL filings |
| GET /api/v1/bulk-evidence/{id} | Inspect completed symbols, metrics and explicit coverage gaps |
| GET /api/v1/bulk-evidence/{id}/report | Read the immutable evidence-coverage report |
| GET /api/v1/features | List recent point-in-time feature snapshots |
| POST /api/v1/features | Build an immutable feature snapshot for a timezone-aware decision time |
| GET /api/v1/features/{id} | Inspect included/excluded features, lineage and dataset manifest |
| GET /api/v1/features/{id}/report | Read or download the immutable point-in-time report |
| GET /api/v1/backtests | List recent immutable strategy experiments |
| POST /api/v1/backtests | Run the fixed GS-13 trend-following template against a saved market run |
| GET /api/v1/backtests/{id} | Inspect assumptions, ledger, trades, equity and benchmark measures |
| GET /api/v1/backtests/{id}/report | Read or download the immutable backtest report |
| GET /api/v1/validations | List recent bounded validation runs |
| POST /api/v1/validations | Search and validate allowlisted candidates against a saved market run |
| GET /api/v1/validations/{id} | Inspect registry, windows, experiments, gates and promotion state |
| GET /api/v1/validations/{id}/report | Read or download the immutable validation report |
| GET /api/v1/paper-books | List independent paper books and reconciled state |
| POST /api/v1/paper-books | Activate an all-gates-passed frozen validation |
| GET /api/v1/paper-books/{id} | Inspect cash, holdings, pending order and event ledger |
| POST /api/v1/paper-books/{id}/process | Process unseen eligible sessions from a saved market run |
| GET /api/v1/paper-books/{id}/report | Read or download the reconciled paper ledger |
| POST /api/v1/paper-books/{id}/catch-up | Replay unseen historical sessions and run degradation monitoring |
| GET /api/v1/paper-books/{id}/monitoring | Inspect immutable paper-versus-validation monitoring history |
| GET /api/v1/combined-books | List separately funded combined paper books |
| POST /api/v1/combined-books | Activate a combined book from at least two independent member books |
| GET /api/v1/combined-books/{id} | Inspect shared cash, holdings, drawdown, attribution and ledger |
| POST /api/v1/combined-books/{id}/process | Process unseen sessions from member decisions under the shared policy |
| GET /api/v1/combined-books/{id}/report | Read or download the combined book's own reconciled ledger |
| POST /api/v1/combined-books/{id}/catch-up | Replay unseen combined sessions with member-decision lineage |
| GET /api/v1/scheduler/jobs | List persisted jobs, next checks, attempts and wait states |
| GET /api/v1/scheduler/runs | List durable scheduled/manual run history |
| GET /api/v1/scheduler/jobs/{id}/runs | List one job's run history |
| POST /api/v1/scheduler/jobs/{id}/run | Run one job immediately through its normal pipeline |
| POST /api/v1/scheduler/sync | Register schedules for newly tracked securities |
| GET /api/v1/alerts | List material alerts, optionally filtered by symbol |
| POST /api/v1/alerts/scan | Evaluate the latest saved thesis, ownership and paper-risk records |
| GET /api/v1/alerts/config | Inspect versioned severity and materiality rules |
| PUT /api/v1/alerts/config | Change minimum severity and material-only delivery |
| POST /api/v1/alerts/{id}/acknowledge | Persist a local review acknowledgement |
| GET /api/v1/alerts/{id}/note | Read the immutable Obsidian alert note |
| GET /api/v1/history/corrections | List immutable fact-correction revisions and impacts |
| POST /api/v1/history/corrections | Record a superseding financial-fact correction |
| GET /api/v1/history/corrections/{id}/note | Read a correction audit note |
| GET /api/v1/history/financial/{id}/current | Compare original and correction-adjusted financial views |
| POST /api/v1/history/backups | Create a verified SQLite-plus-vault backup ZIP |
| GET /api/v1/history/backups | List verified backup manifests |
| GET /api/v1/history/backups/{id}/download | Download a verified backup ZIP |
| POST /api/v1/history/backups/{id}/restore | Rehearse and verify restore in an isolated folder |
| GET /api/v1/improvements | List upstream improvement proposals and evidence |
| GET /api/v1/improvements/config | Inspect repository whitelist and discovery bound |
| PUT /api/v1/improvements/config | Configure allowlisted GitHub repositories and candidate bound |
| POST /api/v1/improvements/monitor | Deduplicate and record a bounded candidate batch |
| POST /api/v1/improvements/{id}/assess | Record metadata and license assessment |
| POST /api/v1/improvements/{id}/test | Run the configured isolated test profile |
| POST /api/v1/improvements/{id}/decision | Approve or reject the exact tested fingerprint |
| POST /api/v1/improvements/{id}/integrated | Record integration only after exact approval; applies no code |
| GET /api/v1/improvements/{id}/report | Read the immutable local proposal report |
| POST /api/v1/updates/{id}/cancel | Request cooperative cancellation between graph nodes |
| POST /api/v1/updates/{id}/resume | Resume failed, partial or cancelled work from its checkpoint |

Writes require `X-Graph-Stock: local-research` or the existing `local-diagnostic` value. Requests that include an Origin must match the local server origin. Asynchronous operations return 202 and a run ID for polling; synchronous immutable builders return 201 with their completed result. Completed/running/queued diagnostic retries return the existing run without invoking the client again. Completed/publishing research retries likewise do not create a new run.

## Verify

```sh
.venv/bin/python -m pytest -q
```

Offline tests use fake transports and deterministic golden inputs. They exercise authentication, schema/evidence rejection, safe error mapping, child termination, queue bounds, concurrency, duplicate requests, retry histories, restart recovery, local write protection and the single-server lock. Live evidence is recorded separately under `docs/`.

Detailed subsystem evidence is recorded under `docs/`. Market and backtest tests hand-check adjustments, gaps, costs, missing sessions, ambiguity and cash/P&L. Validation tests cover registry allowlists, holdout isolation, pass/reject/insufficient outcomes and experiment persistence. Paper tests cover frozen activation, decisions/orders/fills/fees/cash/marks, duplicate events, crash rollback, restart reconciliation, split/dividend accounting, unavailable prices, insufficient cash and uncertain-action pause. Combined-book tests cover independent accounting, shared-cash sizing, attribution, exit-first conflicts, idempotency, policy changes and own-ledger restart reconciliation. Replay tests cover chronological catch-up, source/signal lineage, late-field rejection, duplicate replay, degradation thresholds, pending-entry cancellation and restart persistence. Alert tests cover severity filters, repeated and changed events, all three material categories, scheduler delivery, persistent acknowledgement, failed publication recovery and preservation of user-edited notes. History tests cover correction revisions, recomputed current views, unchanged prior reports, future-run propagation, stale/preserved impact records, safe generated sections, conflict copies, publication recovery and an actual hashed backup/restore rehearsal. Improvement tests cover bounded discovery, deduplication, pass/fail evidence, exact-fingerprint decisions, changed-content invalidation and unapproved-integration rejection.

The installed Starlette test client currently emits one upstream AnyIO deprecation warning; tests pass. No warning is suppressed in the project.

## Project plan

See [the specification](to-spec.md), [the dependency-aware tickets](to-tickets.md) and [the compact checkpoint](docs/PROJECT-CHECKPOINT.md). Sources under `sources/` remain read-only. GS-01 through GS-27 are complete. The compact checkpoint was refreshed after GS-27 and is next due after GS-30.
