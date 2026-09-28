# GS-09 verification — dated news and material catalysts

GS-09 adds a deterministic current-event service, versioned SQLite records, an immutable News & Catalyst note, dashboard cards, manual JSON fallback, and dependency-aware refresh invalidation.

## Representative sources

- Primary filing index: the NSE BEL announcement listing records an “Awarding of order(s)/contract(s)” disclosure received on 25 July 2025 at 14:24:37 IST.
- Supporting source: Ministry of Defence PIB release 2148334, published on 25 July 2025 at 15:16 IST, reports the approximately INR 2,000 crore Air Defence Fire Control Radar contract with BEL.
- The two records share one explicit canonical event key and remain separately linked evidence sources. The exchange time is retained as first public availability; each retrieval time is also retained.
- The bounded collector covers BEL. Other companies receive a visible coverage gap and can use the manual structured-event fallback.

## Evidence semantics and safety

- Facts, source assertions, reported relevance and limited-confidence research inference occupy separate fields and report sections.
- Materiality follows a versioned deterministic policy. Contract values of at least INR 1,000 crore are high severity; values of at least INR 100 crore are medium.
- Source text is stored only as evidence data. A fixture containing “ignore previous instructions” remains quoted in the source-assertion field and cannot change the generated inference or trigger an action.
- Current-event coverage is explicit. No historical point-in-time feature eligibility is claimed before GS-12.

## Deduplication, revisions and failures

- Duplicate/syndicated records with the same canonical key and factual payload become one event with multiple source links.
- Similar records with different canonical keys remain distinct events.
- Changed factual content creates a new version with a `supersedes` link; the prior version remains stored.
- Provider failure publishes a partial run with a coverage gap while retaining the last current events.

## Incremental graph behavior

A new material event changes the material-event digest. The next refresh recomputes `manifest`, `news_catalyst`, `risk`, and `publish_report`; unchanged extraction, calculations, qualitative specialists, earnings, valuation and management outputs are reused.

## Validation

- Focused News/Catalyst and graph tests: 9 passed.
- Production frontend build passed.
- Full regression: 84 tests passed. The only warning is Starlette's existing TestClient type-alias deprecation.
- Live BEL News/Catalyst run: `d23abdf5-613c-4c74-a346-851186105484`.
- Live dependency refresh: `52d66e14-b7af-493c-9ab0-deb0b1000d43`; `news_catalyst`, `risk`, and `publish_report` completed with the material-event digest while unaffected nodes reused prior results.

No model calls are used by collection fixtures, normalization, deduplication, materiality, report generation, invalidation or tests.
