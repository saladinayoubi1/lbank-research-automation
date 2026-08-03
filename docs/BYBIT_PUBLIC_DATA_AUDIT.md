# Bybit Public Data Audit

This stage evaluates whether Bybit is a viable candidate for a full historical backfill after LBank failed the primary-venue readiness threshold.

## Scope

- public V5 REST API only;
- Spot category;
- `BTCUSDT` and `ETHUSDT`;
- intervals `15`, `60`, and `240`;
- 1,000 most recent fully closed candles per series;
- two instrument-info requests and six kline requests.

The audit uses:

- `GET /v5/market/instruments-info`
- `GET /v5/market/kline`

## Candidate gate

Bybit is promoted only to the full-backfill implementation stage when:

- both instruments exist and report `Trading`;
- all six kline requests complete;
- each series contains 1,000 rows;
- missing candles, gaps, duplicates, and off-grid timestamps are zero;
- raw OHLC relationships are valid;
- volume is non-negative and all fields are numeric.

Passing this audit does not approve live trading. It only authorizes building a separate Bybit historical collector and then repeating the full readiness and benchmark process.

## Safety boundary

- no API key;
- no private endpoints;
- no canonical LBank data changes;
- no orders or withdrawals;
- no synthetic candles;
- no automatic live-trading promotion.
