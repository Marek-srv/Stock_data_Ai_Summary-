# GS-02 verification

Completed 6 September 2026 (Asia/Kolkata). All financial values in this ticket are synthetic fixture data.

## Delivered behavior

- React/Vite research library served by the local FastAPI application; connection diagnostic preserved at `/diagnostic`.
- Fixture security resolution for HAL, BEL and BHEL, explicit unknown-query feedback and an ambiguous `Bharat` choice between BEL and BHEL.
- Persistent watchlist, immutable dated snapshots, evidence IDs, timestamps, deterministic metric lineage and null real-research scores/confidence.
- A test-vault note for each run, accessible as an in-app plain-text preview, Markdown download and encoded Obsidian open link.
- CLI research/search/watchlist/show operations call the same HTTP contracts used by the dashboard.
- Idempotency keys prevent duplicate runs; explicit new requests retain older snapshots. Filesystem failures preserve the snapshot and allow note-publication retry.

## Verification

**Automated:** `.venv/bin/python -m pytest -q` → **53 passed**, with the two previously documented upstream test-client deprecation warnings.

**Frontend:** Vite production build passed, with React 19.2.8, Vite 8.2.2 and Node 24.19.0. Bundled assets load from the same origin under `/dashboard/assets/`.

**Browser:** Inspected empty library, fixture notice, unknown query, ambiguous company choices, populated snapshots, saved-snapshot selection, watchlist and the complete saved research note. Read-note preview showed the fixture evidence and formula lineage. The populated snapshot layout was visually inspected.

**Actual server restart and CLI duplicate-request proof:**

- Request key: `3ba39070-7f80-4cbd-a29e-9fecc254d9e3`.
- Fixture: BHEL; run ID: `d6fed82f-4986-40bd-aa24-05494c472496`.
- Status: completed; note integrity: verified.
- Expected synthetic metrics: revenue ₹1,200 crore; growth 20%; operating margin 15%.
- Note SHA-256: `7030c4796a1b16fc600e7373ea5a0fb93713736e160288ce91c9e7854336163a`.
- Shut down the actual server and started a new process with the same database and test-vault configuration.
- Repeated the CLI request with the original request key. The returned JSON was identical: same run, snapshot, evidence, timestamps and note hash. The watchlist still had one BHEL snapshot.
- Opened the CLI-created snapshot in the browser after restart and verified the persisted values and note link.

Evidence: [before restart](GS-02-live-result.json), [after restart and repeat request](GS-02-after-restart.json).

## Correctness boundaries tested

- Independent golden expectations for the three numerical metrics; every metric references the persisted fixture evidence.
- Exact ticker/name aliases, ambiguity, unknown/blank queries and no watchlist mutation on failed identity resolution.
- Same key/same company returns one run; same key/different company fails.
- New snapshots preserve prior notes and deliberate user edits.
- Existing conflicting content is not overwritten; symbolic-link directories/files cannot redirect note publication or reading.
- Crash window after filesystem publication but before database completion safely reuses identical content.
- Startup recovers pending publications; injected write failure retains the snapshot and succeeds on same-run retry after recovery.
- Changing the configured vault cannot silently relocate an old pending publication.
- API fixed-field validation, custom write header, origin checks, queue bounds, safe Markdown content type and CLI/API equivalence.

## Scope and limitations

No live NSE data or company assessment is claimed. Real company names are only fixture labels. There is no inferred research confidence or trade signal. The full future source/provider schemas remain separate from these explicitly named fixture tables.

Obsidian itself was not opened or configured. The supported encoded URI is generated, and the actual Markdown file was verified through the dashboard and filesystem. Open the configured test folder as a vault in Obsidian to use its native link. Personal notes are not imported or modified.

The test suite checks service and HTTP behavior; browser inspection is recorded above rather than represented as a reusable browser-automation suite. GS-03 will add genuine filing acquisition and its corresponding provider fixtures.
