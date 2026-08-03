# Bybit Public Data Audit

This stage evaluates whether Bybit is a viable candidate for a full historical backfill after LBank failed the primary-venue readiness threshold.

## Authoritative source

The candidate decision uses the official public Spot trade archive at `https://public.bybit.com/spot/`.

The direct V5 REST API is not used as the authoritative CI gate because Bybit restricts requests from United States IP addresses and GitHub-hosted runners may execute in a restricted region. That limitation is environmental and is not interpreted as a market-data quality failure.

## Fixed audit scope

- Spot market only;
- `BTCUSDT` and `ETHUSDT`;
- official daily trade files for `2026-08-01`;
- deterministic UTC aggregation into `minute15`, `hour1`, and `hour4` candles;
- raw archive SHA-256, byte size, schema, trade count, and validation results;
- six complete candle-series checks.

Official archive schema observed and supported:

```text
id,timestamp,price,volume,side,rpi
```

## Candidate gate

Bybit advances to the full Spot archive-backfill implementation stage only when:

- both archives download and parse successfully;
- all trade timestamps, prices, sizes, and sides are valid;
- trade IDs are unique within each daily archive;
- all trades belong to the selected UTC day;
- each symbol produces exactly 96 fifteen-minute, 24 hourly, and 6 four-hour candles;
- missing candles, gap groups, duplicates, off-grid timestamps, unexpected timestamps, invalid OHLC rows, and negative volumes are all zero.

## Verified result

For `2026-08-01`:

- BTCUSDT raw trades: `221,151`;
- ETHUSDT raw trades: `89,507`;
- archives passed: `2 / 2`;
- candle series passed: `6 / 6`;
- missing candles: `0`;
- duplicate timestamps: `0`;
- off-grid timestamps: `0`;
- invalid OHLC candles: `0`;
- download or parse errors: `0`.

The candidate gate passed. This authorizes development of a separate Bybit Spot historical collector and full readiness evaluation. It does not approve live trading.

## Safety boundary

- no API key;
- no private endpoints;
- no canonical LBank data changes;
- no orders or withdrawals;
- no synthetic candles;
- no automatic live-trading promotion.
