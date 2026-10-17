# Elliott V58 — direct TLS Bybit Spot archive capture with provenance receipt

**Date:** 2026-10-16 UTC. **Scope:** BTCUSDT/ETHUSDT public Spot, Research-only, Draft PR #2673. No orders, Live, automatic Demo or VPS changes. The existing frozen V52 research score window still starts Oct 18 UTC; the day of Oct 16 is incomplete at the time of this implementation.

## Gap

V55/V57 accurately verify a physically supplied gzip archive against complete one-minute data, but a *declared* `https://public.bybit.com/spot/{SYMBOL}/{SYMBOL}_{YYYY-MM-DD}.csv.gz` URL alone does not prove where the bytes were obtained.

## V58 proof layer

`research/elliott_v58_tls_source_capture/capture_tls_v58.py` makes a **direct HTTPS GET only to exactly `public.bybit.com:443`** with an exact symbol/date path. It uses Python's default trusted CA context with certificate and hostname verification enabled. Connections use TLS 1.2/1.3 only; missing verified peer certificate, unexpected HTTP status (including any redirect), expired/incomplete day, wrong date, illegal symbol, unexpected gzip CSV header, corrupt/unfinished gzip, oversized HTTP body/decompression, transfer failure or an existing output all **fail closed**.

The returned receipt preserves the **actual requested host/path**, HTTP 200, certificate/hostname-check status, TLS version, transferred size, gzip CRC completeness, raw compressed SHA-256, physical archive location and whether the record represents a synthetic mocked-network test. Request redirects and use of unrelated hosts are not supported. The archive and capture receipt are staged in a sibling temporary directory and only published together via same-parent directory rename after all checks pass. No archive is overwritten and no credentials or exchange API keys are used.

For real operation `fixture_mode=False`, time comes from the machine's UTC clock; a partial day's archive cannot be requested. Tests simulate the network and UTC time only in `fixture_mode=True` with an OS-temp target; these explicitly produce `SYNTHETIC_TRANSPORT_TEST_ONLY` and set `remote_origin_tls_verified=false`.

This is a **transport-level proof** against the machine's OS certificate trust store, not exchange cryptographic signing, legal ownership certification, quote accuracy or proof that a feed was tradable. Proxies are not configured by this direct HTTP client. It cannot guarantee all network paths are reachable from an arbitrary device. It does not verify every trade-row price; V55/V52 do that independently. Do not treat a synthetic fixture capture as real exchange data.

## Tests

**14/14 local isolated V58 tests passed, exit 0.** They mock the transport and check pinned HTTPS host/path, verified SSL configuration, atomically published synthetic gzip/receipt/hash, not-yet-complete UTC date rejection, 302 redirect/403 denial, absent peer certificate, weak TLS, truncated HTTP body, bogus gzip, bad CSV header, bounded size, interrupted transfer, output non-overwrite, OS-temp restriction and historical date rejection.

Local isolated log: `E:\NEXUS-QA\elliott-v58-tls-source-capture-20261016\ISOLATED_V58_TLS_TESTS_FIXED.txt`. Native GitHub enrollment: `tests/test_nexus_elliott_v58_tls_source.py`.

## Operational next gate

Wait for **the actual complete October 16 UTC day**. Only after a genuine HTTPS capture with `remote_origin_tls_verified=true`, pair its raw archive SHA/receipt with the V55 1m converter, V52 independent trade-stream oracle and V57 reattested daily scan. Do not score Oct16/17 warm-up data, silently re-fit Elliott pivots or claim positive positions. Production final-source eligibility should require **both** this TLS capture receipt and V57's physical fresh source reattestation; V57 currently reports remote-origin-unauthenticated from its own offline receipt and cannot upgrade that claim merely from a declared URL.

Safety invariant: Bybit only, Demo/Paper not activated, Live disabled, `entry_signal=false`, `new_pnl=null`.
