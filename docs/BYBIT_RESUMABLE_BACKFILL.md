# Bybit Spot Resumable Backfill

This pipeline extends the verified Bybit Spot archive collector into a bounded, resumable historical backfill. It keeps Bybit data separate from LBank and treats each period for both symbols as one atomic unit.

## Archive planning

The official symbol directory is inventoried at runtime.

For the requested date range:

- a full calendar month uses the monthly archive when both BTCUSDT and ETHUSDT provide it;
- an incomplete first or last month uses common daily archives;
- a date missing for either symbol is reported as unavailable and blocks execution;
- units are processed oldest first to grow one contiguous research range.

The current official listings provide monthly BTCUSDT and ETHUSDT archives beginning in November 2022, plus daily files.

## Atomic unit

A unit is either:

```text
monthly:YYYY-MM
```

or:

```text
daily:YYYY-MM-DD
```

A unit contains one archive for each selected symbol. Both archives and all six derived candle series must validate before any Parquet is committed. Failure of either symbol leaves the unit incomplete and prevents a partial dataset write.

## Bounded execution

`--max-archives-per-run` caps downloads. With two symbols, the default budget of two archives processes one unit per invocation.

Example:

```bash
python bybit_spot_backfill.py \
  --start-date 2022-11-10 \
  --end-date 2026-07-31 \
  --state-root build/bybit_backfill_state \
  --cache-root build/bybit_backfill_cache \
  --max-archives-per-run 2
```

## Resume contract

The state snapshot contains:

```text
bybit_backfill_state/
├── bybit_market/
│   ├── btc_usdt/
│   │   ├── minute15.parquet
│   │   ├── hour1.parquet
│   │   └── hour4.parquet
│   └── eth_usdt/
│       ├── minute15.parquet
│       ├── hour1.parquet
│       └── hour4.parquet
├── _archive_plan.json
├── _checkpoint.json
├── _source_manifest.json
├── _backfill_status.csv
├── _backfill_report.json
└── _backfill_report.md
```

To resume, restore the previous state snapshot at the same `--state-root` and rerun without `--clean`. Completed unit IDs are skipped. New candle timestamps are rejected if they overlap existing Parquet rows.

## Integrity rules

Every unit and the accumulated contiguous range require:

- all expected UTC candles;
- zero missing candles and gap groups;
- zero duplicate timestamps;
- zero off-grid or unexpected timestamps;
- valid OHLC relationships;
- non-negative volume;
- correct symbol and timeframe identity;
- valid, unique raw trade IDs within each archive.

## Monthly pilot

The pull-request workflow processes December 2022 as one atomic monthly unit:

- two monthly archives;
- 2,976 fifteen-minute candles per symbol;
- 744 hourly candles per symbol;
- 186 four-hour candles per symbol.

A passing pilot proves monthly archive compatibility, checkpoint creation, and full-month integrity. It does not by itself complete the full historical backfill.

## Safety boundary

- official public archives only;
- no API key or private endpoints;
- no order placement or withdrawals;
- no synthetic candles;
- no automatic live-trading promotion;
- no changes to LBank canonical data.
