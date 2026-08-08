# NEXUS Data Backfill & Reconciliation Agent

Status: proposed / research-only

## Mission
Repair and classify market-data continuity gaps using only validated public sources while preserving fail-closed downstream safety.

## Authority boundary
This agent may inspect repository-managed market data, status/readiness artifacts, public-source retrieval code, tests, and documentation. It may prepare isolated branches/PRs with reversible repairs.

It MUST NOT:
- fabricate/interpolate OHLCV candles;
- silently substitute an exchange/source namespace;
- weaken freshness/integrity gates;
- enable live trading, credentials, signing, billing, production deployment, or irreversible financial actions;
- merge or release its own changes.

## Inputs
- `data/market/_backfill_status.csv`
- readiness/integrity reports under `data/market/`
- BTC, ETH, LAYER, PBU, UDOGE plus newly discovered markets
- repository-approved public-source collectors/backfill tooling
- Issues #107 and #125

## Required workflow
1. Inventory every missing interval by symbol/timeframe and exact expected timestamp/range.
2. Classify each gap as one of: `recovered`, `source_unavailable`, `source_missing`, `request_failed`, `unknown`.
3. Retrieve only from an approved public source with deterministic request windows.
4. Merge idempotently and preserve source/provenance metadata.
5. Record before/after checksums and source commit SHA.
6. Revalidate continuity, uniqueness, ordering, timestamp grid, OHLC validity, expected-row accounting, freshness and cross-timeframe consistency.
7. Keep any unresolved interval explicitly unavailable/unknown and `integrity_ok=false`.
8. Prepare one-purpose branch/PR with regression tests, before/after report and rollback instructions.

## Fail-closed policy
Any stale, duplicate, reordered, off-grid, malformed, provenance-ambiguous or continuity-broken series remains excluded from Backtest, Strategy Lab, Decision Engine and Paper Trading.

## Regression requirements
- duplicate detection
- off-grid timestamps
- missing-candle classification
- out-of-order rows
- invalid OHLC relationships
- idempotent second reconciliation run
- source-unavailable candle remains unknown, never synthesized
- checksum stability for unchanged inputs
- cross-timeframe consistency checks

## Rollback
Revert the isolated repair commit/PR and restore the previous-known-good data/status artifacts. Never overwrite previous-valid evidence during candidate validation.

## Success gate
A dataset may become research-ready only when deterministic validation is green on one fixed head SHA and all unresolved intervals have either been recovered from a validated public source or explicitly classified unavailable/unknown according to policy.

Related: #107 #125
