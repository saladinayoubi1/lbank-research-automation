# Candle Quality Severity Audit

`candle_quality_audit.py` converts raw invalid-row evidence from `gap_probe.py` into deterministic magnitude and severity metrics.

It is an evidence layer only. It does not modify OHLCV values, canonical Parquet, integrity status, readiness status, or Gap Repair behavior.

## Why magnitude matters

The public kline API can return a timestamp whose OHLC fields violate the canonical candle relationship:

```text
high >= max(open, close, low)
low  <= min(open, close, high)
volume >= 0
```

Some violations are small precision differences. Others are material source anomalies. A single global tolerance would treat both categories alike and is therefore unsafe.

## Metrics

For every unique raw target row in `_gap_probe.json`, the audit calculates:

- high shortfall: `max(open, close, low) - high`, floored at zero;
- low excess: `low - min(open, close, high)`, floored at zero;
- negative-volume magnitude;
- high-shortfall and low-excess basis points;
- maximum price violation in basis points;
- computed rejection reasons;
- whether computed reasons match the reasons recorded by the probe.

The basis-point denominator is `max(abs(open), abs(close))`. This makes the magnitude explicit without changing the row.

## Severity buckets

- `rounding_le_1_bps`: greater than zero and at most 1 basis point;
- `minor_le_5_bps`: greater than 1 and at most 5 basis points;
- `moderate_le_10_bps`: greater than 5 and at most 10 basis points;
- `material_gt_10_bps`: greater than 10 basis points;
- `none`: no price relationship violation.

The labels are descriptive, not acceptance rules. Even a rounding-level row remains excluded unless a separate reviewed source policy explicitly changes the canonical contract.

## Inputs and outputs

Input:

```text
build/gap_probe/_gap_probe.json
```

Outputs:

```text
build/gap_probe/
├── _candle_quality_audit.csv
├── _candle_quality_audit.json
└── _candle_quality_audit.md
```

The JSON contains full numeric evidence. CSV supports analysis, and Markdown provides a compact review report.

## Local run

```bash
python candle_quality_audit.py \
  --probe-json build/gap_probe/_gap_probe.json \
  --output-root build/gap_probe
```

The **Probe public kline gaps** workflow runs this audit automatically after the public API probe and includes all six reports in the same short-lived Artifact.

## Policy boundary

This audit must not be used to:

- clamp `high` or `low` to open/close values;
- create synthetic candles;
- silently admit invalid rows;
- mark an invalid series ready;
- infer that a small sampled discrepancy applies to every missing candle.

Its purpose is to support a later, explicit decision between preserving strict canonical data, adding a separately quarantined raw layer, or adopting a narrowly specified and independently reviewed normalization policy.
