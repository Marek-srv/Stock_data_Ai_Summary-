# GS-26 verification — official NSE bulk market history

Verified 12 September 2026 without a reasoning-model call.

## Delivered behavior

- The service downloads the official NSE CM UDiFF bhavcopy ZIP and official all-index daily close CSV for candidate trading days.
- It validates archive shape, exact filenames and dates, required columns, CM/STK/EQ identity, ISIN, OHLCV constraints and duplicate symbols before committing a session.
- Each validated session is cached with its two source URLs, retrieval time and separate SHA-256 hashes. A stopped run resumes from saved sessions.
- Only symbols with completed local financial and ownership evidence are considered. Materialization also requires current official directory identity and saved official corporate-action coverage for the entire window.
- The resulting bundle passes through the existing GS-11 adjustment and quality engine. Repeated unchanged refreshes reuse the same market result.
- The discovery dashboard starts the refresh, follows progress and reruns the screen after completion. Immutable coverage notes are saved below `Graph Stock/Market Coverage/`.

## Live official-source evidence

The first live run `4cd38b61-649c-4637-817d-f3012136aeab` completed against NSE archives with:

- 64 aligned sessions from 15 June 2026 through 11 September 2026.
- 158,614 validated EQ rows.
- BEL materialized as a complete 64-session adjusted market history.
- No collection or materialization gaps.
- Coverage report `Graph Stock/Market Coverage/4cd38b61-649c-4637-817d-f3012136aeab.md`, SHA-256 `78af904e9c23ce77130cb3c0f3dd4045e9ac9a550bc5426cf8b4c9d8183e55a0`.

The canonical-cache verification runs `473ded00-4fab-4a3d-96ff-c3a0ad3d7092` and `b0bfa73d-e21d-4f19-ac9b-00c5dc242378` completed from the saved 64 sessions. Both resolved BEL to market run `d966cf80-2760-4d3a-84bc-56e4874b149e`, confirming unchanged data does not create another normalized market result.

The post-import discovery run `fa5d81d1-fc19-478e-8aac-dea1aeabf67e` used the real history. BEL's 63-session return was -1.1356% and relative strength was +0.7752 percentage points. BEL remained excluded because those values missed the 8% and 2-point rules and institutional ownership change remained -1.76 percentage points versus the +0.25 rule. This is a valid zero-candidate result.

Official source entry points:

- NSE All Reports: <https://www.nseindia.com/all-reports>
- NSE historical daily/monthly archives: <https://www.nseindia.com/resources/historical-reports-capital-market-daily-monthly-archives>
- Daily bhavcopy archive pattern: `https://archives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip`
- Daily all-index close pattern: `https://archives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv`

## Verification

- Focused market/discovery suite: 16 passed.
- Frontend production build: passed, 17 modules transformed.
- Full project suite: 152 passed in 10.82 seconds.

The only observed warning is Starlette's existing AnyIO `BlockingPortal` alias deprecation. It does not affect behavior.
