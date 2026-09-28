# Recovered decision record

Reference transcript for Q1–Q43; preserve user selections over suggested answers.

[https://github.com/mattpocock/skills](https://github.com/mattpocock/skills) see in this there is grill me, so ask me the questions the important one thatis important for this proeject so that we can get in the same page and after the u creat a documet to-sepc and to-teken refert the github and genteer the documnet and giv em the overall project foprm and we will move forward frpm there

I checked the actual `grill-me` flow. It works exactly the way we need: build a **design tree**, ask only the decisions whose prerequisites are already settled, give a recommended answer for each, then use your answers to unlock the next round. Facts are my job to research; decisions are yours. 

We’ll do this in a few compact rounds. Once the design tree is exhausted and you confirm we’re aligned, I’ll turn it into the final **`to-spec`** and **`to-tickets`** project documents, using the GitHub references we already found where useful.

---

❓ **Q1 — Primary purpose:** What should this system optimize for above everything else?

**A.** Long-term fundamental investing  
**B.** Swing trading / timing  
**C.** Both equally: fundamental research selects quality companies, while swing/backtesting helps with entry/exit timing  
**D.** Full quantitative trading system

➡️ **Recommended: C.** The fundamental system should decide *what is worth owning/researching*, while the quantitative layer helps determine *when conditions are attractive*.

---

❓ **Q2 — Stock universe:** What should the first production version support?

**A.** NSE stocks only  
**B.** NSE + BSE Indian equities  
**C.** Indian equities first, but architecture must support global stocks later  
**D.** Global markets immediately

➡️ **Recommended: C.** Build the actual data adapters for India first, but avoid hard-coding the architecture around NSE so global expansion is possible later.

---

❓ **Q3 — How autonomous should research be?** When you enter something like `HAL`, what should happen?

**A.** System tells you which documents to provide manually  
**B.** System automatically finds public information but asks you before processing  
**C.** System automatically checks existing Obsidian research, identifies missing/latest data, fetches public sources where possible, processes them, runs agents, and produces the report  
**D.** Completely autonomous including trading

➡️ **Recommended: C.** Your input should eventually be almost as simple as `Research HAL`.

---

❓ **Q4 — Source philosophy:** Which source hierarchy should control the system?

**A.** Use whatever source is easiest  
**B.** Prefer commercial financial sites  
**C.** Primary sources first: NSE/BSE/company filings/annual reports/SEBI/AMFI → reliable secondary data → news/web as supporting evidence  
**D.** Let each agent choose independently

➡️ **Recommended: C.** This is essential if the system is supposed to become a serious research archive rather than a summary generator.

---

❓ **Q5 — Obsidian's role:** We previously chose Obsidian as the research knowledge base. How strong should that rule be?

**A.** Obsidian is only for final reports  
**B.** Obsidian stores qualitative research; DuckDB/SQLite stores structured numbers  
**C.** Everything must live only in Obsidian  
**D.** Database is primary; Obsidian is optional

➡️ **Recommended: B.**

I would use:

```text
Obsidian
→ reports
→ extracted documents
→ thesis
→ risks
→ industry notes
→ management claims
→ research history

DuckDB / SQLite
→ financial metrics
→ prices
→ ownership
→ mutual fund holdings
→ backtests
→ signals
→ calculated ratios
→ run metadata
```

---

❓ **Q6 — AI execution:** We have one major constraint from the existing project: you don't want an OpenAI API key and don't want to run a large local model. Which direction should remain authoritative?

**A.** ChatGPT/Codex authenticated environment performs heavy reasoning; local Python handles deterministic computation/storage/orchestration  
**B.** Use a small local Ollama model wherever possible  
**C.** Move to paid APIs eventually  
**D.** Build everything around local models

➡️ **Recommended: A.** Keep Python responsible for calculations and data processing, and use ChatGPT/Codex for reasoning where the authenticated environment supports it.

---

❓ **Q7 — Trading layer boundary:** How far should the autonomous swing/backtesting system go in V1?

**A.** Generate strategies only  
**B.** Generate + backtest  
**C.** Generate + backtest + validate + continuously paper trade and update performance  
**D.** Automatically place real-money trades

➡️ **Recommended: C.** Let the system act autonomously with simulated capital first. Real broker execution should remain a separate future phase.

---

Reply simply like:

```text
1. C
2. C
3. C
4. C
5. B
6. A
7. C
```

Add a sentence beside any answer you want changed or qualified.

Your answers to this round will unlock the next design-tree branch: **agent orchestration, data acquisition, update frequency, research scoring, institutional-flow design, backtesting architecture, and final user experience.**

---

1.C
2.A
3.C
4.C
5.B
6.A
7.C

Good. We’re aligned on the first layer:

- **Goal:** Fundamental research + swing timing
- **Market:** NSE only for V1
- **Automation:** Stock name → retrieve existing research → fetch missing data → run agents → generate report
- **Sources:** Primary sources first
- **Storage:** Obsidian for qualitative knowledge, DuckDB/SQLite for structured data
- **AI:** ChatGPT/Codex reasoning + local deterministic compute
- **Trading V1:** Backtest + validate + continuous paper trading, no live execution

That matches the grill approach: decisions are settled first, then dependent questions move to the frontier. 

## Round 2 — Data, orchestration, and update behavior

❓ **Q8 — Orchestrator behavior:** When you enter `HAL`, should the orchestrator run every agent every time?

**A.** Always run all agents  
**B.** Run only agents affected by new/missing data  
**C.** Ask me which agents to run each time

➡️ **Recommended: B.** Example: a new quarterly result should trigger Earnings, Financial, Management Claim, Risk, Valuation, Thesis, and Backtesting updates—not rebuild five years of industry research.

---

❓ **Q9 — Parallel execution:** How should agents run?

**A.** Sequentially for simplicity  
**B.** Parallel wherever dependencies allow  
**C.** Fully parallel regardless of dependencies

➡️ **Recommended: B.**

Example:

```text
           Document Extraction
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
   Financial   Business   Industry
        │         │         │
        └───── parallel ────┘
                  │
                  ▼
          Bull / Bear / Judge
```

This gives speed without letting an agent work on data that does not exist yet.

---

❓ **Q10 — Data fetching:** How should missing source documents be acquired?

**A.** You manually download everything  
**B.** System fetches everything automatically  
**C.** System automatically fetches stable/public sources, but allows manual document drops when extraction fails or a source is unavailable

➡️ **Recommended: C.** Automatic where reliable, manual fallback when NSE/company websites or PDFs are awkward.

---

❓ **Q11 — Research refresh:** When should stored company research update?

**A.** Only when you manually request it  
**B.** Automatically on a fixed schedule  
**C.** Both: scheduled monitoring plus immediate refresh whenever you request a stock

➡️ **Recommended: C.**

For example:

```text
Daily:
news / price / technical data

Monthly:
mutual fund holdings

Quarterly:
results / shareholding / guidance

Event-driven:
material NSE filings

Manual:
"Update HAL"
```

---

❓ **Q12 — Data correction policy:** Suppose a previously extracted number was wrong.

**A.** Overwrite the old number  
**B.** Keep old and new values without distinction  
**C.** Correct the value but retain an audit/version history showing what changed, when, and why

➡️ **Recommended: C.** This matters because research quality should improve over time without losing traceability.

---

❓ **Q13 — Institutional Flow Agent:** How deep should it go for NSE stocks?

**A.** Only aggregate FII/DII/promoter percentages  
**B.** Aggregate + named major shareholders  
**C.** Aggregate + named investors + mutual-fund scheme-level holdings + accumulation/exit history

➡️ **Recommended: C.** This is where the agent becomes differentiated rather than duplicating a normal stock screener.

---

❓ **Q14 — Backtesting inputs:** Should the swing agent use only price/technical data or combine research signals too?

**A.** Technical indicators only  
**B.** Technical + volume + price action  
**C.** Technical + price/volume + earnings + fundamentals + institutional flow + news/catalysts where historically available

➡️ **Recommended: C**, with one important rule: every feature must use **point-in-time data**. We cannot let a backtest use information that became public after the simulated trade date.

Reply:

```text
8. B
9. B
10. C
11. C
12. C
13. C
14. C
```

After this, the next round will settle the **research scoring system, bull/bear/judge behavior, backtesting validation standards, report format, UI/interaction model, and how GitHub-reference improvements enter the project.**

---

8.B
9.B
10.c
11.c
12.C
13.c
14.c

Great. Round 2 is settled exactly in the direction I’d recommend.

Current decisions now include:

- Dependency-aware orchestration
- Parallel agents where safe
- Automatic public-source fetching with manual fallback
- Scheduled + on-demand updates
- Versioned corrections and audit history
- Deep institutional-flow tracking down to mutual-fund schemes
- Point-in-time backtesting using research + market signals

## Round 3 — Scoring, validation, reports, and system improvement

❓ **Q15 — Final research scoring:** Should every stock receive a single overall score?

**A.** No score; only qualitative thesis  
**B.** One overall score only  
**C.** Category scores + one overall score, with the raw evidence visible

➡️ **Recommended: C.**

Example:

```text
Business Quality     17/20
Growth               12/15
Financial Quality    13/15
Moat                  8/10
Management            8/10
Valuation             11/15
Risk                  7/10
Institutional Flow     4/5

Overall               80/100
```

The score should summarize evidence, never replace it.

---

❓ **Q16 — Bull / Bear / Judge:** How independent should these agents be?

**A.** Bull and Bear see the existing thesis and argue around it  
**B.** Bull and Bear independently analyze the underlying evidence, then Judge compares them  
**C.** Skip debate agents

➡️ **Recommended: B.** This reduces anchoring. The Bear Agent should genuinely try to break the thesis, not just write a “risks” paragraph.

---

❓ **Q17 — Strategy discovery:** How much freedom should the swing system have to create strategies?

**A.** Only strategies manually defined by you  
**B.** Start from approved templates and allow the agent to generate variations/combinations  
**C.** Completely unrestricted strategy generation

➡️ **Recommended: B.**

Use approved building blocks like:

```text
Momentum
Breakout
Pullback
Relative strength
Volume expansion
Earnings momentum
Institutional accumulation
Trend following
```

Then let the agent systematically test combinations.

---

❓ **Q18 — Backtest acceptance standard:** When should a strategy become eligible for paper trading?

**A.** If historical return is positive  
**B.** If it beats the index  
**C.** Only after out-of-sample + walk-forward + costs/slippage + minimum-trade-count + robustness checks pass

➡️ **Recommended: C.**

We should prefer:

```text
15% robust return
```

over:

```text
70% overfit return
```

---

❓ **Q19 — Paper-trading capital:** How should simulated strategies be evaluated?

**A.** Each strategy gets independent virtual capital  
**B.** One combined paper portfolio  
**C.** Both: strategy-level virtual portfolios + one combined portfolio to test interaction and risk

➡️ **Recommended: C.**

This lets us evaluate both:

```text
Does Strategy X actually work?
```

and:

```text
Does combining X + Y improve the portfolio?
```

---

❓ **Q20 — Final stock output:** When you type `HAL`, what should be the default result?

**A.** One huge detailed report  
**B.** A compact decision dashboard only  
**C.** A compact investor summary first, with detailed agent reports and evidence stored underneath in Obsidian

➡️ **Recommended: C.**

Default output could look like:

```text
HAL — Research Snapshot

Overall Score           82/100
Fundamental View        Strong
Valuation               Expensive
Institutional Flow      Accumulating
Risk                    Medium
Swing Setup             Positive
Backtest Confidence     74/100

Thesis
5 concise points

Key Numbers
dense table

Major Risks
3–5 points

Current Swing Signal
WATCH / ENTRY / HOLD / EXIT

Full Research → Obsidian
```

---

❓ **Q21 — Report history:** When research updates, what happens to old reports?

**A.** Replace them  
**B.** Keep every generated report separately  
**C.** Maintain a current master thesis plus dated snapshots/updates

➡️ **Recommended: C.**

Example:

```text
HAL/
├── Investment_Thesis.md      ← current state
└── History/
    ├── 2026-Q1.md
    ├── 2026-Q2.md
    └── 2026-Q3.md
```

---

❓ **Q22 — GitHub Reference Agent:** How should external open-source improvements enter our project?

**A.** Automatically update our code  
**B.** Only manually inspect repositories when required  
**C.** Periodically monitor selected repositories, produce an improvement proposal, test it separately, and require approval before integrating

➡️ **Recommended: C.**

This keeps the system improving without turning upstream GitHub changes into a supply-chain risk.

---

❓ **Q23 — GitHub scope:** Should that agent monitor only the projects we already found?

**A.** Fixed whitelist only  
**B.** Whitelist + discover new relevant open-source projects  
**C.** Search all GitHub constantly

➡️ **Recommended: B.**

Start with:

```text
TradingAgents
FinRobot
vectorbt
QuantConnect/Lean
LangGraph ecosystem
financial-data/extraction projects
```

but allow discovery of better projects later.

---

❓ **Q24 — Primary interface:** How do you ultimately want to operate the system?

**A.** Terminal/CLI only  
**B.** Obsidian only  
**C.** Simple local research dashboard + Obsidian as the detailed knowledge base + CLI/Codex for development/admin work  
**D.** Full complex trading terminal immediately

➡️ **Recommended: C.**

That gives you a clean daily interface without making Obsidian responsible for everything.

Reply like:

```text
15. C
16. B
17. B
18. C
19. C
20. C
21. C
22. C
23. B
24. C
```

After this round, we should only have a smaller final branch left: **exact automation cadence, database choice, source failure behavior, notifications, and V1 boundaries**. Then we’ll be ready to freeze the design and produce `to-spec` + `to-tickets`.

---

15. C
16. B
17. B
18. C
19. C
20. C
21. C
22. C
23. B
24. C

Round 3 is locked in.

We now have a clear system philosophy: evidence-first research, independent bull/bear debate, robust backtesting before paper trading, compact user-facing output, historical research memory, and controlled GitHub-driven improvement.

## Round 4 — Final architecture boundaries

❓ **Q25 — Structured database choice:** For V1, what should hold numeric/structured research data?

**A.** SQLite only  
**B.** DuckDB only  
**C.** SQLite for operational/state data + DuckDB for analytical/time-series data  
**D.** PostgreSQL immediately

➡️ **Recommended: C.** SQLite is excellent for jobs, agent state, metadata, claims, and configuration; DuckDB is stronger for financial history, price data, holdings, and large analytical queries.

---

❓ **Q26 — Vector database / embeddings:** Do we need a dedicated vector DB in V1 for document retrieval?

**A.** Yes, build one immediately  
**B.** No — use Obsidian metadata, structured extraction, file search, and deterministic indexing first  
**C.** Use a cloud vector DB

➡️ **Recommended: B.** We should add embeddings only if ordinary retrieval becomes a real bottleneck. Avoid unnecessary infrastructure early.

---

❓ **Q27 — Source failure behavior:** Suppose the system cannot fetch a quarterly result or a filing.

**A.** Continue silently  
**B.** Abort the entire company analysis  
**C.** Continue with available evidence, clearly flag the missing source, lower confidence, and queue it for retry/manual addition

➡️ **Recommended: C.**

The final report should never pretend the research is complete when evidence is missing.

---

❓ **Q28 — Confidence system:** Should agents explicitly report confidence?

**A.** No  
**B.** One confidence score for the final report only  
**C.** Evidence completeness + agent confidence + final confidence

➡️ **Recommended: C.**

Example:

```text
Evidence completeness     92%
Financial confidence      High
Management confidence     Medium
Valuation confidence      Medium
Final research confidence 84/100
```

This is especially useful when a company has poor disclosure.

---

❓ **Q29 — Automated monitoring cadence:** What should V1 monitor automatically once a stock enters your watchlist?

**A.** Nothing unless requested  
**B.** Only quarterly results  
**C.** Price/technical daily, material filings/news daily, MF holdings monthly, shareholding/results quarterly, plus manual refresh

➡️ **Recommended: C.**

This keeps the research alive without constantly re-running expensive agents.

---

❓ **Q30 — Notifications:** When should the system actively alert you?

**A.** Every update  
**B.** Only major thesis-changing events  
**C.** Configurable severity, but default alerts only for material events

➡️ **Recommended: C.**

Examples:

```text
HIGH
Management guidance cut
Promoter pledge increased materially
Major institutional exit
Strategy stop breached
Thesis score changed significantly

MEDIUM
Large order
MF accumulation
Valuation moved into target range

LOW
Routine filing
Minor news
```

---

❓ **Q31 — Watchlist behavior:** Should the system research only stocks you explicitly request, or maintain a persistent universe?

**A.** Only requested stocks  
**B.** Maintain a watchlist of researched stocks and automatically keep them updated  
**C.** Automatically scan the entire NSE every day

➡️ **Recommended: B.**

Later we can build an NSE-wide discovery/screener agent, but that should not complicate V1.

---

❓ **Q32 — Investment discovery:** Should V1 include an agent that proactively finds new stocks?

**A.** No, only analyze stocks I provide  
**B.** Yes, screen NSE using fundamentals + institutional accumulation + momentum and propose candidates  
**C.** Fully autonomous stock picker

➡️ **Recommended: B**, but as a **Phase 2 feature**, not a core V1 blocker.

It could eventually find patterns such as:

```text
ROCE > 18%
Revenue CAGR > 15%
Debt manageable
MF ownership increasing
Relative strength improving
Valuation reasonable
```

and place those companies into a research queue.

---

❓ **Q33 — Corporate actions:** How should splits, bonuses, dividends, mergers, demergers, rights issues, etc. be handled?

**A.** Ignore initially  
**B.** Adjust only price data  
**C.** Dedicated corporate-action normalization so both financial history and backtesting remain correct

➡️ **Recommended: C.** This is essential for trustworthy historical testing.

---

❓ **Q34 — Human approval points:** Where should you be required to approve something?

**A.** Before every agent runs  
**B.** Only before major system changes, GitHub-derived code changes, and eventually real-money execution  
**C.** No approvals anywhere

➡️ **Recommended: B.**

Routine research should run autonomously. Architecture/code changes should not.

---

❓ **Q35 — V1 completion definition:** What should count as a successful first usable version?

**A.** All 20+ agents and every feature complete  
**B.** Enter an NSE ticker → fetch/read sources → store research → run core analysis → generate compact report → run validated backtest → paper-trade signals → incremental updates work  
**C.** Just document extraction

➡️ **Recommended: B.**

This gives us a genuine working vertical slice rather than dozens of half-connected agents.

---

❓ **Q36 — Deployment:** Keep the system local?

**A.** Entirely local on your laptop  
**B.** Local first but design components so cloud deployment could be added later  
**C.** Cloud-first

➡️ **Recommended: B.** Actual V1 stays local, but we avoid architectural choices that make future migration painful.

Reply with:

```text
25. C
26. B
27. C
28. C
29. C
30. C
31. B
32. B
33. C
34. B
35. B
36. B
```

After this, the design tree should be essentially complete. I’ll do one final consistency pass for any unresolved dependency instead of inventing assumptions, then we can freeze the design and move into the consolidated **to-spec → to-tickets** stage.

---

25. A
26. B
27. C
28. C
29. C
30. C
31. B
32. B
33. C
34. B
35. B
36. B

The design tree is almost complete. One final round remains because these choices directly affect the implementation tickets; after this I should not need another architecture interview. The `to-tickets` reference also emphasizes dependency-aware tracer-bullet tickets with explicit blocking edges, so these implementation boundaries need to be settled before I generate them. 

## Final Round — Implementation architecture

❓ **Q37 — Agent orchestration framework:** How should we implement the multi-agent graph?

**A.** Build our own Python orchestration from scratch  
**B.** Use LangGraph for dependency graphs, parallelism, state and checkpoints  
**C.** Use CrewAI  
**D.** Mix several agent frameworks

➡️ **Recommended: B.** TradingAgents already demonstrates LangGraph successfully for financial multi-agent workflows, including checkpoint/resume. We can still keep our agents loosely coupled so the framework can be replaced later.

---

❓ **Q38 — Backend architecture:** What should run the local application?

**A.** Pure Python scripts only  
**B.** Python + FastAPI service  
**C.** Node.js backend  
**D.** Everything directly through Obsidian

➡️ **Recommended: B.**

```text
FastAPI
   │
   ├── Orchestrator
   ├── Agents
   ├── Compute Engine
   ├── Data collectors
   ├── Backtesting
   ├── SQLite
   └── Obsidian adapter
```

CLI commands can call the same backend services.

---

❓ **Q39 — Local dashboard:** What should V1's user interface look like?

**A.** CLI first; dashboard later  
**B.** React/Vite local dashboard from V1  
**C.** Streamlit  
**D.** Obsidian only

➡️ **Recommended: B**, but keep it deliberately small.

The dashboard only needs:

```text
Search NSE stock
Watchlist
Research status
Research snapshot
Agent run status
Institutional activity
Backtest results
Paper portfolio
Alerts
Open full research in Obsidian
```

No Bloomberg-style giant terminal in V1.

---

❓ **Q40 — Scheduler:** How should automatic updates run locally?

**A.** OS cron only  
**B.** Python scheduler inside the application  
**C.** Both: application scheduler with jobs persisted in SQLite, plus OS startup integration later  
**D.** No scheduler in V1

➡️ **Recommended: C.**

Persisting scheduled-job state means restarting the laptop doesn't destroy our knowledge of what should run.

---

❓ **Q41 — Notifications:** Where should V1 alerts appear?

**A.** Dashboard only  
**B.** Dashboard + Obsidian alerts note  
**C.** Dashboard + Obsidian + email/Telegram from day one  
**D.** Desktop push notifications

➡️ **Recommended: B.**

Keep V1 completely local. Later we can add Telegram/email adapters without changing the alert engine.

---

❓ **Q42 — Data-provider architecture:** NSE endpoints and company sites can fail or change. How should collectors be designed?

**A.** One fixed provider per data type  
**B.** Provider adapters with primary + fallback sources and normalized internal schemas  
**C.** Let agents scrape whatever they find every time

➡️ **Recommended: B.**

For example:

```text
             Shareholding request
                     │
              Provider Router
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
        NSE                  fallback
          │                     │
          └──────────┬──────────┘
                     ▼
           Normalized HoldingRecord
                     │
                   SQLite
```

This prevents external website changes from contaminating the rest of the system.

---

❓ **Q43 — Testing standard:** How strict should the project be before an agent/module becomes trusted?

**A.** Basic unit tests  
**B.** Unit + integration tests  
**C.** Unit + integration + golden-data tests + point-in-time/backtest correctness tests + agent output schema validation

➡️ **Recommended: C.**

Finance systems need stronger testing than an ordinary AI demo. A beautiful report with one incorrectly aligned quarter or future-leaking backtest is useless.

---

Reply:

```text
37. B
38. B
39. B
40. C
41. B
42. B
43. C
```

Once these are settled, the frontier should be empty. I’ll summarize the frozen design for your confirmation; after you confirm, I’ll generate the consolidated **overall project specification (`to-spec`)** and the **dependency-aware implementation ticket plan (`to-tickets`)**, incorporating the useful architectural patterns we found in TradingAgents, FinRobot, VectorBT, Lean, and the Matt Pocock workflow.

---

37. B
38. B
39. B
40. C
41. B
42. B
43. C

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

If this frozen design is correct, reply **`confirmed`**. Then I’ll convert this into the two implementation documents: **`to-spec`** and **`to-tickets`**, with the ticket plan ordered by dependencies and suitable for handing directly to Codex.
