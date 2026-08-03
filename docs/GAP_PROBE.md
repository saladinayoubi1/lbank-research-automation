# Public Kline Gap Probe

`gap_probe.py` is a read-only diagnostic for known timestamp gaps in the canonical LBank OHLCV dataset.

It answers two separate questions before any repair policy is changed:

1. Did the public `/v2/kline.do` response contain the exact missing timestamp in its raw rows?
2. If present, did that row survive the canonical numeric, OHLC, and volume validation used by the Collector and Gap Repair?

The distinction matters because a timestamp can exist in the public response but be intentionally excluded from canonical Parquet when its OHLCV values violate the schema contract.

The probe never writes to `data/market`, never creates synthetic candles, and never changes readiness status.

## Probe method

For each source series that contains at least one internal timestamp gap, the default run selects one deterministic missing timestamp. For that target it makes three bounded public API requests:

1. one timeframe step before the target;
2. exactly at the target;
3. one timeframe step after the target.

Each observation records both raw and validated evidence:

- requested anchor time;
- raw and validated row counts;
- first and last raw and validated timestamps;
- whether the exact target appeared in raw rows;
- whether the exact target survived canonical validation;
- nearest raw timestamps before and after the target;
- raw target OHLCV values;
- validation-rejection reasons for raw target rows;
- request or validation errors.

A manual run can increase `--samples-per-series` to select spread-out samples across each series' missing timestamps.

## Classifications

### `recoverable_validated`

At least one response contains the exact missing timestamp and the row survives canonical validation. This is evidence that bounded repair request or merge semantics should be investigated.

### `present_but_rejected_by_validation`

The raw API contains the target timestamp, but canonical validation removes it. The JSON report records the raw OHLCV values and rejection reasons, such as:

- `high_below_ohlc_max`;
- `low_above_ohlc_min`;
- `negative_volume`;
- `non_numeric_or_missing_ohlcv`;
- `short_row`.

This is not a pagination failure. It is a source-quality or interpretation issue and must not be repaired by silently accepting invalid OHLCV.

### `present_but_validation_inconclusive`

The raw API contains the target, but the validation pass itself failed before the result could be determined.

### `absent_from_raw_public_kline_response`

Successful raw responses contain timestamps on both sides of the target but never the target itself.

This classification does **not** authorize creation of a synthetic candle. The series remains integrity-invalid under the current canonical continuity contract.

### Inconclusive classifications

- `inconclusive_unbracketed_raw_response`: raw responses did not bracket the target.
- `inconclusive_empty_raw_response`: successful requests contained no parseable raw timestamps.
- `inconclusive_api_failure`: all three anchor requests failed.

## Outputs

The default output directory is `build/gap_probe`:

```text
build/gap_probe/
├── _gap_probe.csv
├── _gap_probe.json
└── _gap_probe.md
```

The JSON file contains full per-anchor and raw-row evidence. CSV and Markdown provide compact review views.

## Local run

```bash
python gap_probe.py \
  --input-root data/market \
  --output-root build/gap_probe \
  --samples-per-series 1 \
  --clean
```

The **Probe public kline gaps** GitHub Actions workflow performs the same diagnostic and uploads a short-lived Artifact. It uses no private API or external storage credentials.

## Decision policy

- Do not weaken the integrity gate based on a single run.
- Do not synthesize OHLCV values from neighboring candles.
- If samples are `recoverable_validated`, inspect and adjust only bounded repair request or merge semantics.
- If samples are `present_but_rejected_by_validation`, preserve the raw evidence separately and investigate the exchange row format or source-quality defect before changing validation.
- If samples are consistently `absent_from_raw_public_kline_response`, preserve raw source truth and decide separately whether research should use contiguous subranges rather than a synthetic full series.
- If results are inconclusive, repeat the probe before changing code or data policy.
