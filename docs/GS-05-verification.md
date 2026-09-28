# GS-05 verification

Completed 6 September 2026 (Asia/Kolkata). This ticket establishes reusable orchestration behavior around the existing filing-to-financials slice. It does not implement the later specialist research agents.

## Delivered behavior

- A real LangGraph state graph with SQLite checkpoints and a stable run/thread ID.
- Five dependency-aware nodes: manifest, fact extraction, retained research context, metric calculation and report publication.
- Extraction and context run in parallel after the manifest; metrics wait for extraction, and report publication waits for both branches. Graph concurrency is bounded to two nodes.
- Immutable input manifests fingerprint the evidence/source hash and graph, extractor, formula, schema, report, prompt, model-identity and policy versions.
- A cross-run node cache stores only accepted JSON outputs. Exact matches show `reused` with the producing run ID; changed inputs run normally.
- New runs link to the previous company run as successors. Changed filing evidence reruns manifest, extraction, metrics and reporting while an unchanged research-context branch is reused.
- LangGraph checkpoints recover a process stop. Failed nodes can resume without repeating completed nodes or accepted file side effects.
- Cooperative cancellation is persisted and resumable. Queued, running, failed, partial, cancelled and completed run states are exposed together with queued, running, interrupted, failed, completed and reused node states.
- Refresh reports use content-addressed immutable vault paths under `Graph Stock/Updates/<symbol>/`.
- Versioned `/api/v1/updates` operations and dashboard controls expose update history, predecessor, status, fingerprints, reuse, partial/final metric availability, cancellation, resume and report access.

## Live local evidence

Run `60cd5dc6-05c4-415a-882f-e44d75fadc59` processed the saved BEL source `efb2b6691ade11bf748ff9f6fc867e8bcc7cdd3f69d54730f8051f95ba08a216`. It recorded manifest hash `d941ae2b97bc5b9cb7bdb58876c525f6ee2dd26a25e9ffa63d8d233e2f01db9f`, completed every node and published `Graph Stock/Updates/BEL/c964ebb007af1476c143e4b2776afeed7b6c69b2531080b0469e83d1b9b9fefc.md` with content SHA-256 `ef0d13f3af4084a925ef3719b297bd9dc0210314162f49e9953a29d57206cbe7`.

Successor run `7ec1beaf-ab8f-41cb-95c8-81d055318d81` used the same source and completed in under one tenth of a second. All five nodes were marked `reused` from the first run, and the immutable report path/hash remained identical. The first run took about eighteen seconds because it scanned the real 236-page PDF.

No reasoning request was made during either run.

## Focused validation

- Full Python suite: **72 passed** with one upstream AnyIO deprecation warning.
- Update suite: **5 passed**. It verifies the graph topology, parallel prerequisite execution, maximum concurrency, concurrent same-fingerprint deduplication, all-node reuse, changed-source invalidation, predecessor links, checkpoint recovery after a simulated process stop, failed-node resume, cancellation/resume, stable idempotency and report reuse.
- React/Vite production build passed with 16 transformed modules.
- Dependencies are pinned in `requirements.lock`, including LangGraph 1.2.11 and the SQLite checkpointer 3.1.1.

## Limits

The graph currently operates on the GS-04 financial slice and retained fixture-context identity. Later tickets register real specialist nodes and their own dependency fingerprints. Cancellation is cooperative between nodes; an active PDF page extraction finishes before cancellation takes effect. The model identity is recorded as the signed-in client default because no reasoning node runs in this refresh.

The next ticket in number order is GS-06.
