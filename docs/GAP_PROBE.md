# Public Kline Gap Probe

`gap_probe.py` is a read-only diagnostic for known timestamp gaps in the canonical LBank OHLCV dataset.

It answers a narrow question before any repair policy is changed:

> Does the public `/v2/kline.do` response return the exact missing timestamp when queried immediately before, at, and immediately after that timestamp?

The probe never writes to `data/market`, never creates synthetic candles, and never changes readiness status.

## Probe method

For each source series that contains at least one internal timestamp gap, the default run selects one deterministic missing timestamp. For that target it makes three bounded public API requests:

1. one timeframe step before the target;
2. exactly at the target;
3. one timeframe step after the target.

Each observation records:

- requested anchor time;
- returned row count;
- first and last returned timestamps;
- whether the exact target appeared;
- nearest returned timestamp before the target;
- nearest returned timestamp after the target;
- any request or conversion error.

A manual run can increase `--samples-per-series` to select spread-out samples across each series' missing timestamps.

## Classifications

### `recoverable`

At least one response contains the exact missing timestamp. This is evidence that the current bounded repair query or merge path should be investigated.

### `absent_from_public_kline_response`

Successful responses contain candles on both sides of the target but never the target itself. This is evidence that the sampled candle is absent from the public kline response for those anchors.

This classification does **not** authorize creation of a synthetic candle. The series remains integrity-invalid under the current canonical continuity contract.

### `inconclusive_unbracketed`

Requests succeeded, but returned timestamps did not bracket the target. The API's returned window did not provide enough evidence.

### `inconclusive_empty_response`

All successful requests returned no usable candles.

### `inconclusive_api_failure`

All three anchor requests failed. The probe should be repeated later.

## Outputs

The default output directory is `build/gap_probe`:

```text
build/gap_probe/
├── _gap_probe.csv
├── _gap_probe.json
└── _gap_probe.md
```

The JSON file contains full per-anchor evidence. CSV and Markdown provide compact review views.

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
- If samples are `recoverable`, inspect and adjust only the bounded repair request semantics.
- If samples are consistently `absent_from_public_kline_response`, preserve raw source truth and decide separately whether research should use contiguous subranges rather than a synthetic full series.
- If results are inconclusive, repeat the probe before changing code or data policy.
