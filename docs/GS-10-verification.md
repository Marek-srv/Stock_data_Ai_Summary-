# GS-10 verification — independent debate, scoring and complete snapshot

GS-10 extends the checkpointed research graph with evidence-locked Bull and Bear cases, ordered judging, an adjudicated Investment Thesis, transparent category scoring, immutable synthesis notes and a complete baseline dashboard snapshot.

## Independent debate and evidence control

- Bull and Bear are sibling graph nodes built from the same underlying financial, specialist, ownership and news evidence bundle.
- Their persisted input-manifest hashes are identical. Neither input includes a prior thesis or the other case.
- Judge requires both validated cases and their expected IDs before adjudication. Investment Thesis accepts only the resulting Judge record.
- Every debate claim must cite an allowed evidence ID. Unsupported references fail schema/evidence validation before publication.

## Scoring and confidence policy

- `equal-category-score/v1` gives each of eight categories an explicit 12.50% weight because no investment-preference weights were approved.
- Missing categories are `unscored`; they are omitted from the score denominator and remain visible with a reason.
- `evidence-sufficiency/v1` publishes evidence completeness, agent-report support and a separate research-confidence index.
- Research confidence measures evidence sufficiency. It is explicitly not a probability of investment success or forecast accuracy.

## Published snapshot

The complete snapshot contains ticker and company name, as-of time, overall and category scores, fundamental view, valuation scenarios, institutional trend, principal risks, thesis and monitoring conditions, key metrics, missing evidence, refresh status, and links to every detailed research note. Swing status is `unavailable` and validation is `pending` until the market-data, feature and backtest tickets are implemented.

Bull, Bear, Judge, Investment Thesis and Scorecard notes are stored immutably below `Graph Stock/Synthesis/<symbol>/` and are readable through `/api/v1/updates/{run_id}/synthesis/{kind}`.

## Validation

- Focused debate tests independently verify expected aggregation values, unscored missing categories, same-manifest debate inputs and unsupported-citation rejection.
- The public API test reads Bull and Scorecard artifacts and verifies explicit incomplete trading states.
- Production frontend build passed.
- Full regression: 87 tests passed. The only warning is Starlette's existing TestClient type-alias deprecation.
- Live BEL refresh: `f8fd986a-6b1f-4190-bbcf-b3327289be62`.
- The live Bull and Bear manifest hash is `6f715e8beeb3022a66b10ab0ac21b5e162088857f0cfbd7b3bb57d132a2d67b1` for both cases.
- The live snapshot reports an overall score of `51.43` over a `87.50%` scored denominator, `59.09%` evidence completeness and moderate research confidence (`58.12`). It links 17 detailed reports and preserves unavailable/pending trading states.

No model calls are used by debate, judging, thesis generation, scoring, publication or tests.
