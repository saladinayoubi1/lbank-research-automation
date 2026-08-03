# Cached Full Gap Quality Inventory

`gap_inventory.py` extends the read-only public gap probe without increasing API traffic.

The existing probe selects one missing timestamp per gap-containing series and requests three adjacent anchors. Each response can contain many candles. The inventory reuses those exact response bodies and extracts every row whose timestamp matches any currently missing canonical candle in the same symbol/timeframe.

## API boundary

The runner uses `CachedKlineFetcher`:

1. `gap_probe.py` makes the bounded public requests through the cache wrapper;
2. each successful response is retained in memory;
3. the sample-target Probe reports are written normally;
4. the Inventory scans the cached response rows against all known missing timestamps;
5. no second request is made for Inventory or Severity Audit.

With the current default of one sampled target per 17 gap-containing series and three anchors per target, the maximum successful request count remains 51.

## Inventory semantics

A raw response row is included only when:

- its timestamp is parseable as UTC seconds;
- the timestamp is currently missing from the canonical Parquet series;
- the row belongs to the same symbol/timeframe as the cached response.

Rows are deduplicated by:

- symbol;
- timeframe;
- timestamp;
- raw open, high, low, close, and volume values.

Repeated appearances across anchor responses are retained as one row with:

- `observed_request_times_utc`;
- `observation_count`.

## Validation fields

Each row records the raw OHLCV values and the same canonical rejection reasons used by the Collector contract:

- `short_row`;
- `non_numeric_or_missing_ohlcv`;
- `high_below_ohlc_max`;
- `low_above_ohlc_min`;
- `negative_volume`.

`canonical_valid` is true only when no rejection reason is present.

The Inventory does not write valid raw rows into canonical Parquet. It reports evidence only.

## Coverage metrics

The summary records:

- cached API response count;
- total missing timestamps in canonical source series;
- unique missing timestamps observed in raw responses;
- observed timestamps with invalid raw rows;
- observed timestamps with no invalid raw variant;
- percentage of all missing timestamps visible in the cached responses;
- total unique raw rows.

The coverage percentage is observational. Uncovered missing timestamps were not necessarily absent from the API; they may simply fall outside the returned windows.

## Outputs

```text
build/gap_probe/
├── _gap_inventory.csv
├── _gap_inventory.json
└── _gap_inventory.md
```

The updated workflow also retains:

- three sample-target Probe reports;
- three Inventory reports;
- three Severity Audit reports calculated from all invalid Inventory rows.

## Local run

```bash
python gap_inventory.py \
  --input-root data/market \
  --output-root build/gap_probe \
  --samples-per-series 1 \
  --request-pause 0.15 \
  --clean

python inventory_quality_audit.py \
  --inventory-json build/gap_probe/_gap_inventory.json \
  --output-root build/gap_probe
```

## Safety boundary

The Inventory must not:

- make additional API calls beyond the bounded Probe;
- alter canonical Parquet;
- normalize or clamp OHLCV;
- create synthetic candles;
- change integrity or readiness status;
- imply that uncovered gaps are absent from the public source.

Its purpose is to increase evidence coverage at zero additional request cost and quantify the full set of invalid missing rows already visible in bounded public responses.
