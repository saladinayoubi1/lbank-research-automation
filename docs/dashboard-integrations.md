# Dashboard integrations

## Scope

The local dashboard reads generated Zotero metadata and Research evidence reports from `data/integrations`. It exposes summarized, read-only status through `/api/integrations/zotero` and `/api/integrations/research`.

No endpoint performs network access, writes to Zotero, handles credentials, places orders, or claims production readiness.

## Ownership

- `dashboard_integrations.py`: schema and safety-boundary validation for generated integration reports.
- `web_dashboard.py`: approved read-only HTTP routes.
- `web_ui/`: presentation only; no domain validation.
- `tests/test_dashboard_integrations.py`: adapter failure modes.
- `tests/test_web_ui.py`: browser/API integration contract.

## Failure behavior

Missing, malformed, incomplete, unsupported-schema, or unsafe-boundary reports return HTTP 503 with `report_unavailable`. The browser hides integration cards and displays an error rather than rendering partial success.

Research summaries surface overdue review dates as stale. Zotero summaries expose counts only and do not include item metadata.

## Rollback

Revert the Issue #88 merge commit. This removes both integration routes, adapters, cards, and tests without changing generated source reports. Existing readiness endpoints remain independent.

For a temporary operational rollback before reverting code, remove or rename `data/integrations`; the service fails closed for integration routes and performs no fallback network access.

## Residual risk

- Report producers may evolve schemas; unsupported versions remain unavailable until explicitly reviewed.
- Filesystem modification times are not treated as trusted freshness evidence.
- The dashboard is intended for local research use and has no authentication boundary for remote deployment.
