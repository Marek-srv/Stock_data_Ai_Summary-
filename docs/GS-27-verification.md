# GS-27 verification — official financial and ownership evidence

Verified 28 September 2026 without a reasoning-model call.

## Delivered behavior

- A refresh accepts one to ten explicit current NSE-directory symbols and uses at most two workers. The dashboard default is BEL, HAL and BHEL.
- The provider reads NSE's Integrated Filing Financials and Shareholding Pattern catalogs, then follows only allowlisted HTTPS XBRL links.
- XBRL validation rejects malformed XML, DTD/entity declarations, oversized documents, symbol/ISIN mismatches, period mismatches and layouts lacking the required comparable facts.
- Revenue growth compares the latest consolidated quarter with the same quarter one year earlier. Operating margin is calculated from current-period revenue, profit before tax, finance cost and other income. Institutional change compares aggregate domestic plus foreign institutional ownership in consecutive disclosed quarters.
- Complete periods, catalog metadata, URLs, retrieval times and content hashes are stored in SQLite. Discovery uses the newer metrics while leaving absent momentum fields missing.
- Queued work recovers after restart, request keys are idempotent, progress is visible through the API/dashboard, and immutable reports publish below `Graph Stock/Evidence Coverage/`.

## Live official-source evidence

Corrected live run `c88a69bd-7151-48ea-8143-3a982fcc9aea` completed all three symbols with no gaps:

| Symbol | Q1 FY27 revenue growth YoY | Operating margin | FII + DII change QoQ |
|---|---:|---:|---:|
| BEL | 24.9393% | 22.1355% | -0.45 pp |
| HAL | 14.4461% | 22.1721% | +0.62 pp |
| BHEL | 40.2924% | 5.4819% | +0.74 pp |

The report is `Graph Stock/Evidence Coverage/c88a69bd-7151-48ea-8143-3a982fcc9aea.md`, SHA-256 `518056fe250f5a2f0468e807f4e9359c2bdb3872d96fcebe6291a01cdbe67c4b`.

An initial live pass exposed and prevented a quarter-versus-annual comparison. The selector now has a regression test requiring the same month/day in the prior year. The incorrect intermediate metrics were overwritten by the corrected source-period records and are not used by discovery.

Discovery run `98be8668-2143-444e-976c-5f606ee354cb` assessed three of 2,601 current directory securities. HAL passes all three available fundamental/ownership rules but remains excluded because real adjusted momentum is absent. BHEL also misses the 12% margin rule. BEL remains excluded by institutional accumulation and momentum. The valid result is zero candidates.

Official source pages:

- <https://www.nseindia.com/companies-listing/corporate-integrated-filing>
- <https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern>

## Verification

- Focused evidence/market/discovery suite: 11 passed.
- Frontend production build: passed, 17 modules transformed.
- Full project suite: 156 passed in 12.41 seconds.

The only observed warning is Starlette's existing AnyIO `BlockingPortal` alias deprecation. It does not affect behavior.
