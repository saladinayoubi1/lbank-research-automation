# Acceptance checks

- Hosted acquisition uses the canonical public Bybit REST path already approved by the market-data registry.
- Exact surface: 4 symbols × 3 timeframes = 12 cells, 240 closed candles per cell.
- Snapshot schema and frame digests independently verify before packing and after transport.
- Snapshot `source_sha` equals the exact workflow source SHA.
- Transport age is bounded to 20 minutes at physical consumption.
- Every cell's latest closed candle remains within the canonical two-candle freshness rule.
- Runtime snapshot digest must differ from the historical Discovery snapshot digest.
- Physical requalification re-binds transported frames to the canonical Bybit primary mapping and deterministically replays Strategy Factory qualification.
- Maximum result is `QUALIFIED_FOR_REVIEW`; no Candidate state, Paper execution start, automatic promotion, private credentials, real exchange orders or Live/L4 authority.
- Deterministic Risk remains final authority.
- #984 state remains untouched and GitHub remains transport/CI only, not a runtime database.
