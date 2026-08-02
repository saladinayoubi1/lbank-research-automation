# LBank Research Automation

A public-market-data research pipeline for collecting, validating, repairing, archiving, and safely loading LBank OHLCV candles.

This repository is research infrastructure only. It does **not** place orders, use private LBank APIs, withdraw funds, or contain real-trading credentials.

## Pipeline

```text
LBank public kline API
        ↓
Incremental Collector
        ↓
Timestamp Integrity Validation
        ↓
Bounded Gap Repair
        ↓
Data Readiness Gate
        ↓
Snapshot Manifest / Partitioned Export
        ↓
Guarded Research Loader
        ↓
Backtest research — future stage
```

## Current universe

Symbols:

- `btc_usdt`
- `eth_usdt`
- `aero_usdt`
- `agt_usdt`
- `layer_usdt`
- `pbu_usdt`
- `udoge_usdt`

Timeframes:

- `minute15`
- `hour1`
- `hour4`

The Collector runs through GitHub Actions every 15 minutes and advances each symbol/timeframe incrementally. Existing pagination, request size, page limits, and canonical Parquet schema are intentionally bounded.

## Canonical dataset layout

```text
data/market/
├── _backfill_status.csv
├── _backfill_status.md
├── _data_readiness.csv
├── _data_readiness.json
├── _data_readiness.md
├── _snapshot_manifest.json
├── _snapshot_manifest.md
└── <symbol>/
    ├── minute15.parquet
    ├── hour1.parquet
    └── hour4.parquet
```

Each Parquet file uses the exact column order documented in [`docs/SCHEMA.md`](docs/SCHEMA.md).

## Integrity rules

A series is invalid when any of these conditions is detected:

- missing candle intervals;
- duplicate timestamps;
- timestamps outside the timeframe grid.

The status report records:

- `expected_rows`
- `missing_candles`
- `gap_count`
- `duplicate_count`
- `off_grid_count`
- `integrity_ok`

Integrity failure takes precedence over freshness. An invalid series cannot be marked `current`.

## Research-readiness rules

`data_readiness.py` converts integrity status into deterministic research decisions. Only integrity-valid `current` or `backfilling` series can be marked ready. An optional minimum-row threshold may be applied by research jobs.

`research_data.py` is the approved loader for future analyses and backtests. It rejects blocked series before reading Parquet and then revalidates:

- canonical schema and column order;
- symbol/timeframe identity;
- timestamp continuity at load time;
- optional minimum rows.

## Gap repair

`gap_repair.py` repairs only known missing candle windows. It is bounded to a small number of API requests per series per run, merges only timestamps that are currently missing, and does not change Collector pagination or storage schema.

## Verifiable snapshots

`snapshot_manifest.py` inventories every canonical Parquet file and records:

- relative path;
- symbol and timeframe;
- row count and byte size;
- first and last candle;
- canonical schema status;
- SHA-256 digest.

The manual **Export dataset snapshot** workflow packages `data/market` as a short-lived GitHub Actions artifact. No Google Drive credentials are stored in GitHub.

## Partitioned research export

`partition_dataset.py` creates a separate, lossless year/month-partitioned copy:

```text
build/partitioned_market/
└── symbol=<symbol>/
    └── timeframe=<timeframe>/
        └── year=<YYYY>/
            └── month=<MM>/
                └── part-00000.parquet
```

The partitioner preserves the canonical columns and all source rows. It does not silently repair, remove, or reinterpret gaps. Integrity metrics and SHA-256 values are recorded in `_partition_manifest.json` and `_partition_manifest.md`.

## Dependency policy

Python 3.12 is used in GitHub Actions.

- `requirements.txt` defines supported direct-dependency ranges for development and planned upgrades.
- `requirements.lock` pins the complete runtime environment used by Collector and export workflows.
- `requirements-dev.lock` pins the runtime environment plus the test toolchain.
- Lock updates must use a pull request and pass the complete repository test suite plus `pip check`.

Install the exact runtime environment:

```bash
python -m pip install -r requirements.lock
python -m pip check
```

Install the exact test environment:

```bash
python -m pip install -r requirements-dev.lock
python -m pip check
python -m pytest -q
```

For dependency-upgrade exploration only, install the supported ranges:

```bash
python -m pip install -r requirements.txt
```

## Local commands

Run the Collector:

```bash
python main.py
```

Run bounded Gap Repair:

```bash
python gap_repair.py
```

Generate readiness and snapshot reports:

```bash
python data_readiness.py
python snapshot_manifest.py
```

Build the partitioned research copy:

```bash
python partition_dataset.py \
  --input-root data/market \
  --output-root build/partitioned_market \
  --clean
```

## Data limitations

The repository dataset is preliminary research data. A series must pass the readiness gate and guarded loader before it is used. Historical completeness may continue to improve over multiple scheduled runs. No result should be treated as production-grade trading evidence until the selected dataset is complete, integrity-valid, reproducible, and independently reviewed.

## Safety boundaries

- Public market data only.
- No private API keys.
- No order placement.
- No withdrawals.
- No real-money execution logic.
- No automatic promotion from research to live trading.
