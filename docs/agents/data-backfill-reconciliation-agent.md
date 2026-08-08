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

## Governed source hierarchy
ADR-009 is authoritative for this agent:
- **Bybit = primary** market identity and paper-trading/execution reference.
- **Binance = secondary** compatible public corroboration/backfill evidence.
- **LBank = tertiary** research-only evidence with explicit provenance.

A secondary/tertiary candle is never sufficient by timestamp alone. Cross-source use requires deterministic compatibility for market category, quote/settlement asset, timeframe/timestamp convention, candle finality, listing window, volume/turnover semantics, source endpoint contract and mapping-policy version. If compatibility is not proven, classify the interval `incompatible_source` or `unknown` and keep it blocked.

## Inputs
- `data/market/_backfill_status.csv`
- readiness/integrity reports under `data/market/`
- BTC, ETH, LAYER, PBU, UDOGE plus newly discovered markets
- repository-approved public-source collectors/backfill tooling
- ADR-009
- Issues #107, #125 and #131

## Required workflow
1. Inventory every missing interval by symbol/timeframe and exact expected timestamp/range.
2. Classify each gap as one of: `recovered`, `source_unavailable`, `source_missing`, `request_failed`, `incompatible_source`, `unknown`.
3. Retrieve only from an approved public source with deterministic request windows.
4. Verify the source/market mapping contract before comparing or reconciling cross-exchange data.
5. Merge idempotently and preserve source/provenance metadata; never relabel a source into another exchange namespace.
6. Record before/after checksums, exact source endpoint/archive identifier, mapping-policy version and source commit SHA where repository evidence is involved.
7. Revalidate continuity, uniqueness, ordering, timestamp grid, OHLC validity, expected-row accounting, freshness, source-manifest integrity and cross-timeframe consistency.
8. Keep any unresolved, unavailable or incompatible interval explicitly blocked and `integrity_ok=false`.
9. Prepare one-purpose branch/PR with regression tests, before/after report and rollback instructions.

## Fail-closed policy
Any stale, duplicate, reordered, off-grid, malformed, provenance-ambiguous, source-incompatible or continuity-broken series remains excluded from Backtest, Strategy Lab, Decision Engine and Paper Trading.

Unknown/unsupported mapping, open candle, partial pagination, listing-boundary ambiguity, checksum mismatch, missing provenance or material unexplained cross-source disagreement must never be converted into a recovered candle merely to make readiness green.

## Regression requirements
- duplicate detection
- off-grid timestamps
- missing-candle classification
- out-of-order rows
- invalid OHLC relationships
- exact compatible source mapping positive case
- spot/perpetual/category mismatch rejection
- listing-boundary and source-unavailable classification
- open/incomplete candle rejection
- partial/stale page rejection
- idempotent second reconciliation run
- source-unavailable/incompatible candle remains unknown, never synthesized
- no silent cross-exchange namespace substitution
- checksum stability for unchanged inputs
- cross-timeframe consistency checks
- raw/unvalidated downstream bypass remains rejected

## Rollback
Revert the isolated repair commit/PR and restore the previous-known-good source policy + adapters + mapping registry + validator/tests as one tuple. Never overwrite previous-valid evidence during candidate validation; preserve rejected candidate data and before/after checksums for audit.

## Recovery exercise
Before implementation under #131 is eligible to merge, replay at least one fixed window containing a deliberately invalid or incompatible candidate. Prove deterministic rejection, quarantine, unchanged previous-valid evidence, stable reason code, and successful restoration followed by the full readiness validation suite.

## Success gate
A dataset may become research-ready only when deterministic validation is green on one fixed head SHA and all unresolved intervals have either been recovered from a validated compatible public source or explicitly classified unavailable/unknown/incompatible according to policy.

Documentation alignment alone does not authorize implementation merge. Implementation remains gated by ADR-009, #131, exact-head CI, mergeability and zero unresolved review threads.

Related: #107 #125 #131
