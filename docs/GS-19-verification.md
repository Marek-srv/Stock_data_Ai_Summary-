# GS-19 verification — material alerts

GS-19 delivers versioned, traceable alerts for saved thesis, ownership and paper-risk changes to the local dashboard and the configured Obsidian vault. It adds no external push channel and uses no model allowance.

## Materiality and alert contents

- Policy `alert-materiality/v1` orders low, medium, high and critical severity and records category-specific thresholds.
- Delivery defaults to material events at medium severity or above. The dashboard and API expose the minimum severity and material-only setting.
- Thesis alerts compare the two latest completed research updates. Ownership alerts require a comparable change of at least 0.5 percentage points or a supported entry/exit. Paper-risk alerts use a degraded GS-17 monitor result.
- Every accepted alert stores the source record, evidence IDs, comparison baseline, event time, summary, next action, schema version and rule version.

## Deduplication, recovery and user text

- The symbol, category, rule version and event revision form the deduplication identity. Repeated scheduler scans do not create another alert, while a changed event revision receives a new immutable alert ID.
- Acknowledgement time and optional note are persisted in SQLite and survive service restart.
- SQLite acceptance makes the alert immediately available to the dashboard. Obsidian publication has an independent attempt journal and retries pending or failed writes at startup.
- Each alert has a unique immutable note below `Graph Stock/Alerts/<symbol>/`. If the note differs on retry, publication records `preserved-user-text` and leaves the existing file untouched.
- Scheduler success is not rolled back by an alert scan or vault failure. The scheduler result records the alert failure, while durable alert recovery remains available.

## Checks

- Focused alert and scheduler suites: 10 tests passed.
- Full regression: 130 tests passed. The only warning is Starlette's existing TestClient type-alias deprecation.
- React/Vite production build passed with 16 transformed modules.

The checks cover default severity filtering, repeated and changed events, thesis/ownership/paper-risk detection, request idempotency, restart-safe acknowledgement, scheduler invocation, independent failure handling, interrupted note publication, user-edited note preservation, API controls, alert listing and note output.
