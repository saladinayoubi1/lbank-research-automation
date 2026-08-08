# Source reconciliation provenance binding v5

Refs #131.

## Before

`cross_source_gap_reconciliation.py` emitted deterministic per-source candle SHA-256 values for eligible Bybit-primary/Binance-secondary candidates, while `market_data_provenance_manifest.py` independently provided strict source/window/candle provenance manifests. The two controls were not cryptographically bound to each other.

## After

`cross_source_reconciliation_provenance.py` binds an eligible candidate to validated Bybit and Binance provenance manifests and emits a deterministic binding SHA-256. Binding is fail-closed unless the candidate is eligible, Bybit remains selected primary, both source roles and spot semantics are exact, timestamps match, candles are closed, and the source-row digests exactly match the candidate digests.

The binding does not mutate canonical LBank Parquet, synthesize candles, promote Binance/LBank to primary, use credentials, or authorize live trading.

## Regression evidence

Tests cover deterministic replay, manifest digest binding, primary-row tampering, blocked-candidate rejection, open-candle rejection, and source-role substitution.

## Checksum / provenance

The deterministic binding includes the complete candidate payload, canonical symbol, manifest timeframe, mapping policy version, and both validated manifest SHA-256 values. Each manifest separately binds source identity, market type, source/canonical symbol, endpoint contract, mapping policy version, exact retrieval window, candle count, candle SHA-256 and metadata.

## Rollback

Revert the three files in this slice. Existing candidate generation and existing provenance-manifest behavior remain unchanged because this slice adds a separate binding layer and does not mutate canonical datasets.

## Replay note

This v5 branch replays the previously reviewed v4 slice onto exact `main` `86acd23044943f7dfa03792c38fdff5836a9c251` after intervening changes were verified to touch only market-data snapshots plus the bounded exhaustive-repair runner/tests, with no overlap in this slice.
