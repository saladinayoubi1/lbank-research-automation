# Source reconciliation determinism v2 evidence

Scope: issue #131 only. Public Bybit primary + Binance secondary corroboration for approved BTC/USDT and ETH/USDT spot mappings. LBank remains tertiary/research-only. No canonical dataset mutation, credentials, synthetic candles, silent substitution, or live trading.

## Before

`cross_source_gap_reconciliation.py` compared only close prices and computed `digest_sha256` over a payload containing `generated_at`. Identical source/input evidence generated at different times therefore produced different digests. Candidate evidence also did not bind the exact primary and secondary candle contents by checksum.

## After

- All OHLC fields are compared under the existing explicit 1% relative-deviation ceiling; any material OHLC disagreement is blocked.
- Source identity, spot-market semantics, canonical symbol, exact timestamp, closed-candle finality, finite OHLCV and OHLC bounds are revalidated at the reconciliation boundary even if an adapter is replaced or monkeypatched.
- Each primary and secondary candle is bound to a deterministic SHA-256 digest.
- The input Parquet bytes are bound to SHA-256.
- `reconciliation_sha256` is computed only over deterministic policy/input/candidate evidence. `generated_at` remains audit metadata outside the deterministic digest.
- Replaying the same input and source candles at different generation times must produce the same reconciliation digest.

## Fail-closed regression evidence

Tests cover internal-gap detection, approved-source eligibility, material high-price disagreement with equal closes, source-identity substitution, unknown mapping rejection, per-candle SHA-256 presence, input checksum stability, and deterministic reconciliation digest replay.

## Rollback / recovery

Rollback is atomic and non-destructive because this slice does not mutate canonical market data: revert the squash commit for this PR (or restore the prior `cross_source_gap_reconciliation.py` and its test file), delete any generated `data/market/reconciliation/*.json` candidate artifacts, and regenerate candidates from the unchanged canonical Parquet inputs. Recovery must rerun the full test workflow and confirm unknown mappings and disagreement cases remain blocked before any later promotion/persistence slice is allowed.
