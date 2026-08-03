# Bybit Spot Archive Collector

This collector builds a separate research dataset from official public Bybit Spot trade archives. It does not modify or combine with the canonical LBank dataset.

## Source

- official public archive: `https://public.bybit.com/spot/`;
- daily trade files;
- supported initial symbols: `BTCUSDT`, `ETHUSDT`;
- canonical output symbols: `btc_usdt`, `eth_usdt`.

## Output

The collector writes a separate root with six Parquet files:

```text
bybit_market/
├── btc_usdt/
│   ├── minute15.parquet
│   ├── hour1.parquet
│   └── hour4.parquet
├── eth_usdt/
│   ├── minute15.parquet
│   ├── hour1.parquet
│   └── hour4.parquet
├── _backfill_status.csv
├── _collection_report.json
├── _collection_report.md
├── _source_manifest.csv
└── _source_manifest.json
```

Each Parquet uses the established research schema:

- `timestamp`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `symbol`
- `timeframe`

## Integrity gate

A series is `ready` only when the full requested UTC date range has:

- all expected candles;
- zero missing candles and gap groups;
- zero duplicates;
- zero off-grid and unexpected timestamps;
- valid OHLC relationships;
- non-negative volume;
- correct symbol and timeframe identity.

The overall collector succeeds only when every expected daily archive passes raw-trade validation and all six candle series are ready.

## Pilot

The pull-request workflow runs a bounded pilot from `2026-07-30` through `2026-08-01` inclusive. This requires six official daily archives and produces:

- 288 fifteen-minute candles per symbol;
- 72 hourly candles per symbol;
- 18 four-hour candles per symbol.

The Pilot is an implementation and data-quality check. It is not yet the full historical backfill and is not sufficient by itself for strategy conclusions.

## Safety boundary

- public archives only;
- no API key or private endpoint;
- no order placement or withdrawals;
- no synthetic candles;
- no automatic live-trading promotion;
- no changes to the LBank canonical dataset.
