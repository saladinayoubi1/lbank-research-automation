# Contiguous Segment Analysis

`contiguous_segments.py` identifies maximal timestamp-contiguous blocks inside each canonical OHLCV series.

It is a diagnostic and planning tool. It does not change the strict series-level integrity gate, mark blocked series ready, fill gaps, or allow a backtest to bridge missing candles.

## Why segments are reported

A series with one or more missing candles is invalid as a complete continuous history. It can still contain long blocks where every adjacent timestamp is exactly one timeframe step apart.

Reporting those blocks answers limited planning questions:

- How fragmented is each series?
- What is the largest internally continuous block?
- What fraction of canonical rows belongs to that block?
- Which blocks exceed a configurable row threshold?
- How many candles are missing before and after each block?

The answers support later review of a segment-specific research contract. They do not constitute approval.

## Canonical checks

Before segmentation, the analyzer requires:

- exact canonical column order;
- non-empty series;
- parseable UTC timestamps;
- correct symbol and timeframe identity;
- non-null OHLCV values;
- a supported timeframe.

It separately records:

- duplicate timestamps;
- off-grid timestamps;
- expected rows;
- missing candles.

Segmentation uses unique sorted timestamps. A break occurs whenever the delta between adjacent timestamps is not exactly the configured timeframe interval.

## Segment fields

Each maximal block records:

- symbol and timeframe;
- 1-based segment index;
- row count;
- first and last candle UTC;
- calendar span hours;
- covered candle hours;
- share of the series' unique rows;
- missing candles immediately before and after the block;
- whether it meets the configured minimum-row threshold.

A `None` gap count means the boundary is off-grid rather than an integer number of missing timeframe intervals.

## Series summary

For every series, the report includes:

- total and unique rows;
- expected and missing rows;
- duplicate and off-grid counts;
- segment count;
- number of segments meeting the threshold;
- largest segment row count, share, and date range;
- whether duplicates and off-grid timestamps are absent.

## Outputs

```text
build/contiguous_segments/
├── _contiguous_segments.json
├── _contiguous_segments.md
├── _contiguous_series.csv
└── _contiguous_segments.csv
```

## Local run

```bash
python contiguous_segments.py \
  --input-root data/market \
  --output-root build/contiguous_segments \
  --minimum-segment-rows 1000 \
  --clean
```

The GitHub Actions workflow uses 1,000 candles as a reporting threshold only. It is not a readiness threshold and has no effect on the guarded research loader.

## Research boundary

A future segment-specific loader would require a separate reviewed change with all of these controls:

- exact symbol, timeframe, first timestamp, and last timestamp pinned;
- canonical schema and identity revalidation;
- strict continuity inside the selected range;
- no returns calculated across segment boundaries;
- provenance linking the result to a snapshot manifest and source revision;
- explicit statement that the full series remains integrity-invalid;
- no automatic promotion to live trading.

Until that separate contract exists, this report is informational only.
