# Read-only Web Dashboard API

## Status and boundary

This API is an experimental local interface over generated research-readiness reports. It is **read-only**, **research-only**, and not a production trading service.

It does not:

- call private LBank APIs;
- accept exchange credentials;
- place, modify, or cancel orders;
- read raw Parquet candles;
- change readiness reports or pipeline state;
- prove that a report is current or production-ready.

## Run locally

Generate readiness reports first:

```bash
python data_readiness.py
```

Start the service:

```bash
python web_dashboard.py --host 127.0.0.1 --port 8000
```

Use another report root when required:

```bash
python web_dashboard.py --data-root /path/to/data/market
```

Binding to a non-loopback interface exposes the report API to the surrounding network and should be an explicit operator decision.

## Endpoints

### `GET /health`

Returns service identity and confirms that the process is running. It does not validate report freshness or data readiness.

### `GET /api/readiness/summary`

Reads the fixed file `_data_readiness.json` from the configured data root.

A missing, malformed, unreadable, or non-object JSON report returns HTTP `503` with `report_unavailable`.

### `GET /api/readiness/series`

Reads the fixed file `_data_readiness.csv` and returns rows as JSON.

Optional exact-match filters:

- `symbol`
- `timeframe`

Example:

```text
/api/readiness/series?symbol=btc_usdt&timeframe=hour1
```

Unknown query parameters are ignored. Query input cannot select a path or filename.

## Response metadata

Report responses include:

- `source`: fixed report filename;
- `generated_report_mtime_ns`: filesystem modification timestamp in nanoseconds;
- `stale_possible`: always `true`.

The timestamp is informative filesystem metadata, not trusted evidence that the underlying market data is current.

## Failure behavior

- unknown routes return JSON HTTP `404`;
- unavailable reports return JSON HTTP `503`;
- unsupported write methods return JSON HTTP `405`;
- responses use `Cache-Control: no-store`.

## Tests

```bash
python -m pytest -q tests/test_web_dashboard.py
```

The tests cover health, valid and invalid reports, CSV conversion, filters, empty results, fixed-path behavior, and unknown routes.
