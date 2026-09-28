# GS-20 verification — corrections and consistent recovery

GS-20 adds immutable fact-correction history, current-view reconstruction, explicit downstream impact records and verified local backup/restore. It leaves earlier reports, point-in-time snapshots and paper fills unchanged.

## Superseding corrections

- Schema `research-history/v1` records the original full fact payload, its evidence, corrected payload and evidence, local author, reason, timestamp, version and predecessor correction.
- Repeating an identical request key returns the same correction. Reusing it with different content is rejected.
- Current financial comparison recalculates deterministic metrics from the latest fact revisions without changing the stored extraction or old note.
- New dependency-aware research runs include the correction digest in their manifest and apply corrected facts. New point-in-time feature transformations include correction identity. Existing feature vintages remain reconstructable.
- Impact records mark affected current financial and research artifacts stale. Historical feature snapshots are recorded as preserved rather than rewritten; no correction path mutates backtest, validation or paper ledgers.

## Vault publication safety

- Each correction publishes an immutable audit note below `Graph Stock/Corrections/<symbol>/`.
- The current correction index owns only content between explicit generated markers. Personal text outside those markers survives later revisions.
- If the generated section itself changed, graph_stock preserves the file and publishes the intended update under `Graph Stock/Corrections/<symbol>/Conflicts/`.
- A correction is committed before publication. Pending or failed publications retry at service startup.

## Backup and restore

- Backup uses SQLite's online snapshot operation for every state database, then discovers all `Graph Stock/` vault paths referenced by the frozen main snapshot.
- Every database and referenced artifact is copied into a ZIP with path, size and SHA-256 in `graph-stock-backup/v1`.
- Missing referenced artifacts fail backup rather than producing an incomplete archive.
- Restore rejects unsafe archive paths, extracts into a new isolated `restores/` folder, verifies every hash and confirms the restored database has no missing vault references.

## Checks

- Focused correction/update/feature suites: 14 tests passed across the final focused checks.
- Full regression: 135 tests passed. The only warning is Starlette's existing TestClient type-alias deprecation.
- React/Vite production build passed with 16 transformed modules.

The tests include correction-to-current-view and correction-to-new-research propagation, unchanged old note reconstruction, request conflicts, multiple correction versions, personal-text preservation, generated-section conflict publication, interrupted publication recovery, verified ZIP creation, download and actual temporary restore.

The saved local workspace rehearsal created backup `471ba1e8-ecbe-4642-ba09-4041605c7196` and restored it into an isolated folder. Verification passed for two SQLite databases and 69 referenced vault artifacts.
