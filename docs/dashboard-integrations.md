# Dashboard integrations

## Scope

The local dashboard reads generated Zotero metadata and Research evidence reports from `data/integrations`. It exposes summarized, read-only status through `/api/integrations/zotero` and `/api/integrations/research`.

No endpoint performs network access, writes to Zotero, handles credentials, places orders, or claims production readiness.

## Ownership

- `integration_report_provenance.py`: canonical SHA-256 provenance envelope and freshness policy.
- `dashboard_integrations.py`: bounded schema, identity, binding and privacy validation.
- `web_dashboard.py`: approved read-only HTTP routes.
- `web_ui/`: presentation only; no domain validation.
- `tests/test_dashboard_integrations.py`: adapter failure modes.
- `tests/test_web_ui.py`: browser/API integration contract.

## Failure behavior

Missing, malformed, stale/future, unbound, digest-modified, oversized, linked, incomplete, unsupported-schema, unknown-field, or unsafe-boundary reports return HTTP 503 with `report_unavailable`. The browser hides integration cards and displays an error rather than rendering partial success.

Research summaries require provenance-bound claim/evidence identifiers and a bounded review date. Zotero summaries expose counts only. Titles, creators, DOIs, notes, tags, paths, prompts and raw evidence are never emitted. See ADR-027.

## Rollback

Revert the Issue #88 merge commit. This removes both integration routes, adapters, cards, and tests without changing generated source reports. Existing readiness endpoints remain independent.

For a temporary operational rollback before reverting code, remove or rename `data/integrations`; the service fails closed for integration routes and performs no fallback network access.

## Residual risk

- Report producers may evolve schemas; unsupported versions remain unavailable until explicitly reviewed.
- Filesystem modification times are not freshness evidence; the bounded UTC `generated_at` value is.
- Local SHA-256 binding does not replace external signatures or transparency-log attestations.
- Local access is protected by ADR-019. Remote mode additionally requires its TLS/token policy and does not imply production approval.
