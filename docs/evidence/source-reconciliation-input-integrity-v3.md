# Source reconciliation input-integrity v3 evidence

Scope: issue #131 only. Public-data research path. No credentials, synthetic candles, silent source substitution, canonical dataset mutation, live trading, signing, billing, or deployment.

## Before

`missing_timestamps()` normalized the canonical timestamp series with `drop_duplicates().sort_values()` before computing gaps. That could hide duplicate and out-of-order canonical rows. Off-grid timestamps were also not rejected at this boundary. Those conditions violate the fail-closed source-reconciliation contract because invalid canonical input could be normalized into an apparently valid reconciliation window.

`max_candidates` was also caller-controlled without an immutable library-side upper bound. Because each candidate can fan out to both Bybit and Binance, a pathological value could amplify a single local call into excessive public-API requests, causing avoidable resource exhaustion, rate-limit failures or exchange-side temporary bans.

## After

- Timestamp column must exist and parse completely as UTC.
- Duplicate timestamps are rejected with `duplicate_timestamp`.
- Out-of-order timestamps are rejected with `out_of_order_timestamp`.
- Timestamps not aligned to the exact UTC epoch grid for the requested timeframe are rejected with `off_grid_timestamp`.
- Unsupported timeframes are rejected before reconciliation.
- Invalid input is rejected before any Bybit or Binance fetch is attempted.
- Library and CLI share a hard `MAX_CANDIDATES = 50` bound.
- `max_candidates` outside `1..MAX_CANDIDATES`, including zero, negative, oversized and pathological values, is rejected before source fetch.
- The exact upper boundary remains accepted.
- The deterministic source policy records the immutable candidate cap.
- Existing deterministic input Parquet SHA-256 and per-source candle SHA-256 bindings remain unchanged.

## Regression evidence

`tests/test_cross_source_gap_reconciliation.py` adds duplicate, out-of-order, off-grid and pre-fetch blocking regressions; invalid `max_candidates` cases for `0`, negative, `MAX_CANDIDATES + 1` and a pathological large value with proof that neither source fetch is called; and a positive exact-boundary test. Existing internal-gap, mapping, source identity, OHLC disagreement and deterministic digest coverage remains.

## Determinism / provenance

For valid input, the input Parquet byte SHA-256 continues to bind the canonical source file and `reconciliation_sha256` continues to exclude wall-clock metadata. Invalid input or invalid fan-out requests produce no reconciliation candidate artifact, so no ambiguous, normalized or unbounded request state can be promoted.

## Abuse case / residual risk

The hard cap reduces local amplification but does not replace exchange-side rate limiting, retry budgets or broader scheduler concurrency controls. Even bounded requests can fail because public endpoints are unavailable or rate-limited; those outcomes remain blocked and must not be converted into eligible data.

Obsolescence trigger: re-review `MAX_CANDIDATES` whenever exchange request-weight/rate-limit semantics, source fan-out count, retry policy, scheduler concurrency or reconciliation endpoint behavior changes. Increasing the cap requires fresh deterministic regression evidence and must not be done merely to accelerate gap closure.

## Rollback / recovery

Rollback: revert this slice as one commit/PR tuple. No canonical data is modified by this change.

Recovery exercise: replay a fixed valid input and confirm its deterministic reconciliation digest is unchanged under the accepted bound; replay duplicate, out-of-order and off-grid variants and confirm each is rejected before source fetch; replay invalid candidate limits and confirm zero Bybit/Binance calls; replay exactly `MAX_CANDIDATES` and confirm the boundary remains accepted. Any unexpected acceptance remains fail-closed and blocks downstream use.
