# GS-21 verification — upstream improvement review

Verified locally on 11 September 2026 without model calls or live GitHub requests.

## Delivered behavior

- `bounded-github-review/v1` stores a configurable repository whitelist and a discovery batch limit from 1 to 10.
- Proposals retain the GitHub repository and source links, exact commit, release, license, relevance, change summary, compatibility, expected benefit and SHA-256 change identity.
- The proposal fingerprint binds repository, revision and exact change hash. Duplicate events return the original proposal.
- The persisted lifecycle covers discovered, assessed, sandbox-tested, awaiting-approval, approved/rejected, superseded and integrated audit states.
- Pass/fail test evidence records the exact fingerprint and isolated profile. Approval and rejection require that same fingerprint.
- New content at the same revision creates a successor, marks the earlier proposal superseded and invalidates its decision.
- Integration acknowledgement is rejected without matching passed test evidence and a non-invalidated approval. The service contains no patch, checkout, copy or project-source write operation.
- Each state transition publishes an immutable Markdown report below `Graph Stock/Improvements/<proposal-id>/`.
- The dashboard lists proposal status, identity, evidence and decisions, and supports candidate recording, assessment, configured isolated testing, approval and rejection. It deliberately exposes no apply-code action.

## Validation evidence

- Focused tests: `3 passed`.
- Full offline suite: `138 passed` with one existing Starlette/AnyIO alias deprecation warning.
- Frontend production build: passed; Vite transformed 16 modules.
- Lifecycle fixture covered allowlisted monitoring, duplicate delivery, assessment, isolated passing evidence, awaiting approval and exact approval.
- Failure fixtures covered bounded discovery rejection, retained failed test evidence, changed-diff invalidation, mismatched approval and attempted unapproved integration.

The representative proposal is a deterministic fixture. It proves the review and control workflow and does not claim that an upstream change is production-safe or integrated.
