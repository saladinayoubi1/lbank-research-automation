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

Local mode is strictly loopback-only. A non-loopback `--host`, non-loopback client, missing or foreign `Host`, and unapproved browser `Origin` fail closed. Do not expose local mode through `0.0.0.0`, a LAN address, a hostname, port forwarding, or a reverse proxy.

Remote mode is a separate opt-in boundary and will not start unless TLS certificate/key paths, a strong runtime bearer token, exact allowed hosts, and exact HTTPS origins are configured. See [`docs/architecture/ADR-019-secure-gateway-delivery.md`](architecture/ADR-019-secure-gateway-delivery.md). Remote mode does not make this API a production or live-trading service.

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

The accepted query schema is exactly `symbol`, `timeframe`, `limit`, and `offset`. Unknown, repeated, empty, oversized, or out-of-range parameters fail closed. Query input cannot select a path or filename; responses are explicitly paginated and bounded.

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
- responses use `Cache-Control: no-store`, `nosniff`, frame denial, no-referrer, a restrictive permissions policy, same-origin resource policy, and a restrictive CSP;
- oversized request targets, reports, static assets, or responses fail closed;
- only exact allowlisted UI assets are served and symlinks are rejected;
- rate-limited requests return HTTP `429` with `Retry-After`.

## Tests

```bash
python -m pytest -q tests/test_web_dashboard.py
```

The dashboard and secure-gateway tests cover health, valid and invalid reports, exact query schemas, pagination and size bounds, fixed paths, loopback binding, Host/Origin authorization, DNS-rebinding variants, remote TLS/token requirements, security headers, method denial, rate limiting, symlink rejection, native-client route allowlists, and unknown routes.
