# Multi-Pair fresh runtime requalification snapshot

This contract transports fresh canonical public Bybit REST closed-candle evidence from a hosted GitHub acquisition job to the physical `nexus-bybit-network` execution plane when the physical network cannot reach the same public REST endpoint directly.

The runtime snapshot is independent of the immutable historical Discovery archive. It contains exactly BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT on `minute15`, `hour1` and `hour4`, with 240 closed candles per cell. Consumption fails closed if the snapshot exceeds its bounded transport freshness budget or if the latest closed candle no longer meets the canonical two-candle freshness rule.

Transport does not change market semantics. On the physical runner the verified frames are re-bound through the canonical Bybit primary mapping before Strategy Factory requalification and deterministic replay. The result can reach `QUALIFIED_FOR_REVIEW` only. Candidate creation, Paper execution start, automatic strategy promotion, private credentials, real exchange orders and Live/L4 authority remain disabled; Deterministic Risk remains final authority.

The GitHub artifact is a bounded digest-pinned transport/evidence object only, never a persistent runtime database. The #984 BTC/ETH prospective Paper state is not read, rewritten or reused by this contract.
