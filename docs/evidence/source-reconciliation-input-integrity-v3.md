# Source reconciliation input-integrity v3 evidence

Scope: issue #131 only. Public-data research path. No credentials, synthetic candles, silent source substitution, canonical dataset mutation, live trading, signing, billing, or deployment.

## Before

`missing_timestamps()` normalized the canonical timestamp series with `drop_duplicates().sort_values()` before computing gaps. That could hide duplicate and out-of-order canonical rows. Off-grid timestamps were also not rejected at this boundary. Those conditions violate the fail-closed source-reconciliation contract because invalid canonical input could be normalized into an apparently valid reconciliation window.

## After

- Timestamp column must exist and parse completely as UTC.
- Duplicate timestamps are rejected with `duplicate_timestamp`.
- Out-of-order timestamps are rejected with `out_of_order_timestamp`.
- Timestamps not aligned to the exact UTC epoch grid for the requested timeframe are rejected with `off_grid_timestamp`.
- Unsupported timeframes are rejected before reconciliation.
- Invalid input is rejected before any Bybit or Binance fetch is attempted.
- Existing deterministic input Parquet SHA-256 and per-source candle SHA-256 bindings remain unchanged.

## Regression evidence

`tests/test_cross_source_gap_reconciliation.py` adds duplicate, out-of-order, off-grid and pre-fetch blocking regressions while retaining internal-gap, mapping, source identity, OHLC disagreement and deterministic digest coverage.

## Determinism / provenance

For valid input, the input Parquet byte SHA-256 continues to bind the canonical source file and `reconciliation_sha256` continues to exclude wall-clock metadata. Invalid input produces no reconciliation candidate artifact, so no ambiguous or normalized provenance can be promoted.

## Rollback / recovery

Rollback: revert this slice as one commit/PR tuple. No canonical data is modified by this change.

Recovery exercise: replay a fixed valid input and confirm its deterministic reconciliation digest is unchanged; replay duplicate, out-of-order and off-grid variants and confirm each is rejected before source fetch. Any unexpected acceptance remains fail-closed and blocks downstream use.
