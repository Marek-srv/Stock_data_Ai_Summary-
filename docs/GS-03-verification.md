# GS-03 verification

Completed 6 September 2026 (Asia/Kolkata). This ticket collects source documents and provenance. It does not produce financial analysis or a trading conclusion.

## Delivered behavior

- Versioned filing service and `/api/v1/filings` operations for automatic acquisition, manual PDF import, status/retry, evidence-note reading and original-PDF download.
- Current NSE equity-directory lookup with exact ticker, company name, ISIN, retrieval time and content hash.
- A deliberately bounded automatic sample: BEL's NSE-hosted integrated annual report for 2024–25, followed by a company-hosted fallback.
- Explicit `success`, `unchanged`, `partial`, `unavailable`, `throttled` and `invalid` provider outcomes.
- PDF validation before storage, a 25 MB limit, page-count validation, allowlisted HTTPS providers and validated redirects.
- Immutable content-addressed source records in SQLite plus original PDF and an evidence metadata note in the configured Obsidian vault.
- Manual imports use the same source table and hash deduplication. Offline identity and manually supplied public dates remain labelled user assertions and are excluded from historical features.
- Dashboard controls show acquisition state, attempted providers, source gaps, hash, origin, parser state, time fields, PDF download, evidence note, retry and manual import.

## Real public-source evidence

The NSE equity directory and both configured BEL documents were retrieved from their public hosts on 6 September 2026. The primary NSE document is a 15,543,216-byte, 236-page PDF with SHA-256 `db47a73b477737b5c5241d6c62bfba08446a734fb8b59972b6a6577e0fe7867d`. Its first page identifies BEL and the 5 August 2025 filing date. The directory resolved BEL to Bharat Electronics Limited and ISIN `INE263A01024`.

The running localhost API performed the live directory and filing retrieval and passed the responses through CSV/PDF validation, identity resolution, hashing, SQLite insertion/deduplication, original-PDF publication and evidence-note publication. Run `d3509a2a-1f12-439f-9458-cffd7db68bc7` completed successfully. The resulting source ID was `efb2b6691ade11bf748ff9f6fc867e8bcc7cdd3f69d54730f8051f95ba08a216`. Machine-readable evidence is in [GS-03-live-result.json](GS-03-live-result.json).

The NSE archive timestamp encoded in the primary URL is stored as the availability basis. A source is still ineligible for point-in-time features until GS-04 extracts and validates located facts. The company fallback does not inherit the primary archive timestamp.

The application transport uses the `certifi` trust store because the host Python installation's default trust store could not validate the NSE certificate. The final localhost request exercised this transport against the real NSE hosts. Deterministic adapter tests cover the same contracts without repeating public downloads.

## Focused validation

- Full Python suite: **62 passed**. The two previously recorded upstream Starlette/AnyIO deprecation warnings remain.
- New filing suite: **9 passed**, covering success, unchanged content, partial coverage, provider unavailability, throttling with fallback, invalid identity/document data, idempotency conflict, manual import, duplicate hashes, restart recovery, interrupted jobs, failed vault publication and local write protection.
- React/Vite production build passed with 16 transformed modules.
- No Codex reasoning request or live AI test was made for GS-03.

## Measured coverage and limits

Automatic filing coverage is one historical filing type for BEL. Identity lookup covers securities present in the retrieved NSE equity directory. HAL and other verified tickers display a partial result and manual-import action because no automatic document map is claimed for them yet.

The PDF validator records document-level pages and source location. Page/table fact extraction, financial-unit normalization and metric calculations belong to GS-04. Manual imports are not treated as official merely because the file is valid. Provider retrieval can still fail because of connectivity, throttling, changed URLs or host policy; the saved status keeps retry/manual recovery visible.
