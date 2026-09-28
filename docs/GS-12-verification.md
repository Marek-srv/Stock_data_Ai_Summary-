# GS-12 verification — point-in-time feature snapshots

GS-12 adds immutable, availability-aware historical feature snapshots across deterministic financial metrics, ownership disclosures, dated events, adjusted market bars and benchmark bars.

## Eligibility and time semantics

- Every candidate stores effective time, public-availability time and ingestion time separately.
- `public-availability-cutoff/v1` includes evidence only when its effective and public times are at or before the selected decision time.
- Timestamped evidence uses its recorded timezone-aware instant. Date-only evidence becomes eligible at the end of the stated date in Asia/Kolkata; month-only disclosure evidence becomes eligible at the end of the final calendar day of that month.
- Ingestion after a historical decision is visible in the data vintage. It is allowed only for deterministic reconstruction when the evidence has a proven earlier public time.
- Verified NSE sources with recorded public availability qualify under the GS-12 evidence policy even if a legacy GS-03 record says historical eligibility was deferred. Manual or unverified source dates remain excluded.

## Look-ahead controls

- Future-dated financial results, ownership disclosures and events are excluded and cannot change the earlier dataset-manifest hash.
- A restated financial value replaces its prior value only after the restating source becomes public.
- Retrospective reasoning output is always excluded from historical features.
- A revised event with no newly proven availability time is excluded until its revision boundary is known.
- Intraday market rows, unavailable values and rows blocked by incomplete corporate-action terms remain excluded with explicit reasons.

## Reproducibility and inspection

- Included features record source IDs, transformation versions, input/evidence lineage and normalized data-vintage timestamps.
- Excluded candidates remain visible with their exact reason.
- The manifest hashes only included feature inputs, the decision time, active aliases and the eligibility policy version.
- Universe scope is explicitly one currently known security. The snapshot does not claim delisted-security or survivorship-safe NSE-wide coverage.
- The dashboard displays family coverage, included and excluded features, cutoff reasons, precision policy, listing state and immutable report links.

## Validation

- Boundary fixtures verify future financial, ownership and event exclusion; same-day date-only cutoffs; month-only cutoffs; restatement switching; retrospective reasoning exclusion; and unproven revision rejection.
- API integration verifies a legacy-deferred but fully verified NSE filing becomes eligible, a reasoning narrative remains excluded, market and benchmark rows join correctly, idempotency holds and the immutable report is readable.
- Production frontend build passed.
- Full regression: 100 tests passed. The only warning is Starlette's existing TestClient type-alias deprecation.
- Current live snapshot: `a42db598-4461-4421-9adb-92eba6f7d9e5`, manifest `bb04d358761c70edda48854e396691e78359e9f4da63d5d13a64f642d0fa0210`. It includes five deterministic financial metrics, six current ownership observations and one dated event. Intraday market/benchmark rows, a missing debt metric, superseded records and retrospective reasoning are excluded.
- Earlier live cutoff: `d11823ab-7d54-4955-a8f2-971351adf8ad`, manifest `a3e4c4ffaf3de316f5779e7c0a0a6f0cc48ad7421eb6ac129c7087b0365f9f69`. At 26 July 2025 it includes the prior ownership disclosure and event, with zero FY2025 financial metrics and zero 2025 ownership observations.

No model calls are used by candidate collection, availability joins, manifest generation, report publication or tests.
