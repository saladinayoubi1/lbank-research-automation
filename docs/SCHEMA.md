# LBank Dataset Schema

## Canonical Parquet schema

Every source and partitioned Parquet file must contain these columns in this exact order:

| Column | Logical type | Required | Rules |
|---|---|---:|---|
| `timestamp` | UTC timestamp | yes | Candle open time; normalized to UTC. |
| `open` | numeric | yes | Finite and positive for valid market data. |
| `high` | numeric | yes | Must be greater than or equal to open, close, and low. |
| `low` | numeric | yes | Must be less than or equal to open, close, and high. |
| `close` | numeric | yes | Finite and positive for valid market data. |
| `volume` | numeric | yes | Must be non-negative. |
| `symbol` | string | yes | Must match the parent source directory. |
| `timeframe` | string | yes | Must match the source filename and a supported timeframe. |

Canonical column order:

```text
timestamp, open, high, low, close, volume, symbol, timeframe
```

The Collector writes one canonical file per symbol/timeframe:

```text
data/market/<symbol>/<timeframe>.parquet
```

The partitioned research export preserves the same columns and writes:

```text
symbol=<symbol>/timeframe=<timeframe>/year=<YYYY>/month=<MM>/part-00000.parquet
```

The year and month values are derived from `timestamp` in UTC and are not added as Parquet columns.

## Supported timeframes

| Timeframe | Step |
|---|---:|
| `minute15` | 900 seconds |
| `hour1` | 3,600 seconds |
| `hour4` | 14,400 seconds |

A timestamp is off-grid when its Unix timestamp is not an exact multiple of the timeframe step.

## Backfill status schema

`data/market/_backfill_status.csv` contains one row per symbol/timeframe:

| Column | Meaning |
|---|---|
| `symbol` | LBank market symbol. |
| `timeframe` | Candle timeframe. |
| `rows` | Stored row count. |
| `first_candle_utc` | Earliest stored candle. |
| `last_candle_utc` | Latest stored candle. |
| `hours_behind_now` | Distance from the latest candle to report generation time. |
| `expected_rows` | Inclusive grid size from first through last unique timestamp. |
| `missing_candles` | Number of absent candle slots inside detected gaps. |
| `gap_count` | Number of timestamp intervals larger than one timeframe step. |
| `duplicate_count` | Duplicate timestamp count before deduplication. |
| `off_grid_count` | Timestamps outside the timeframe grid. |
| `integrity_ok` | True only when gaps, duplicates, and off-grid timestamps are absent. |
| `status` | `current`, `backfilling`, `invalid`, `missing`, or `empty`. |

An integrity failure always produces `status=invalid` for populated data, regardless of freshness.

## Data-readiness schema

The readiness reports add a deterministic decision layer. Important fields include:

| Column | Meaning |
|---|---|
| `research_ready` | Whether the series may be consumed by guarded research code. |
| `readiness_reason` | Machine-readable reason for the decision. |
| `minimum_rows` | Optional configured row threshold. |
| `rows_ok` | Whether the row threshold is satisfied. |

Research readiness does not prove historical completeness. It only confirms that the series satisfies the current integrity and policy checks.

## Snapshot manifest

`_snapshot_manifest.json` records source-file provenance and verification data:

- source commit;
- file count and total rows;
- relative paths;
- canonical column list and schema status;
- first/last candle timestamps;
- byte size;
- SHA-256 for every Parquet file.

## Partition manifest

`_partition_manifest.json` records:

- source snapshot-manifest SHA-256 when available;
- source commit when available;
- source files and their integrity metrics;
- every generated partition path;
- partition row count, byte size, timestamp range, and SHA-256;
- source and partition row totals;
- `row_conservation_ok`.

A partition export is valid only when source-row and partition-row totals are identical.

## Compatibility contract

Changes to canonical columns, ordering, meaning, timestamp semantics, or compression expectations require an explicit schema-version migration. Collector changes must not silently rewrite the schema. Research code should load data through `research_data.py` rather than directly calling `pandas.read_parquet`.
