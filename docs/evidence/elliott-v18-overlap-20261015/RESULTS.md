# NEXUS Elliott V18 — raw-source overlap conflict and quarantine

**Date:** 2026-10-15. **Disposition: BLOCKED_UNRESOLVED_OBSERVED_SOURCE_CONFLICT.** No market orders, backtest replay, archive modification, Demo/Live changes, or VPS work.

## Evidence actually obtained

1. Laptop2 `DESKTOP-F4SA4VL` holds previously audited, byte-frozen 15m historical Bybit source parquets through **2026-07-31 23:45:00 UTC**, with BTC SHA-256 `c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226` and ETH SHA-256 `ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1`.
2. Two remote `curl.exe` invocations of the unauthenticated Bybit V5 **spot** `/v5/market/kline` endpoint requesting the eight 15m candles with OPEN times **2026-07-31 22:00–23:45 UTC** returned `retCode: 0`. Raw stdout was directly visible in the conversation, but raw HTTP response bytes were **not retained**. Values in [OBSERVED_PUBLIC_API_TRANSCRIPTION.json](OBSERVED_PUBLIC_API_TRANSCRIPTION.json) are explicitly **human/assistant-transcribed observations**, not a cryptographically attested exchange record.
3. Subsequent same public endpoint retrieval attempts from Laptop2 returned **HTTP 403**. The first one of these was recorded by `curl.exe --fail`, so the response content was not available. We did not attempt to bypass or repeatedly hammer the restriction.
4. Against the original hash-bound archive, the read-only [audit](audit_transcribed_overlap.py) reconciled each 15m OPEN timestamp and the five OHLCV fields, with fixed `1e-8` absolute comparison tolerance. Native [machine receipt](OVERLAP_CONFLICT_QA.json) reports **14 field discrepancies among 16 sampled candles**:

| Field | BTCUSDT | ETHUSDT |
|---|---:|---:|
| Open | **6** | **7** |
| High | 0 | 0 |
| Low | 0 | **1** |
| Close | 0 | 0 |
| Volume | 0 | 0 |
| Total | **6** | **8** |

The snapshot is a *small, already inspected, July 2026* overlap, and the values are unauthenticated transcription; it is **insufficient evidence to declare the archived source wrong or the public source canonical**. It is sufficient to raise an unresolved provenance conflict, particularly for **next-open execution arithmetic**. Do not use either side to rewrite the other by fiat.

## Engineering QA

- The isolated V18 ingress module `nexus_elliott_forward_bridge_v18.py` requires a byte-hash-pinned frozen archive and a *complete, contiguous* next-file bridge starting **2026-08-01 00:00 UTC**; it rejects a missing, overlapping, future, forming, gapped or malformed source. It derives seven-pivot and higher timeframe research observations from complete 15m source values; no provider-authenticity or recursive Elliott wave-degree claim is made.
- Native V18 synthetic tests **18/18 PASS**. A separate **10/10** quarantined overlap test suite checks 8-bar timestamp integrity, response-format/OHLC sanity, no automatic repair, hash mismatch rejection and conflict detection.
- On Laptop2 actual archive **without a continuation file**, V18 yielded `BLOCKED_NO_VERIFIED_CONTINUATION_FILE` (deliberate nonzero exit status 2). Therefore no new future Bybit evaluation or V17 net outcome was attempted.
- PR #2673 remains Draft. Its V17 future-only study contract does not possess an independently authenticated 1 Aug–15 Oct candle bridge. The existing V16 frozen study remains structurally verified but economically unqualified.

## Resolution prerequisites

1. Obtain **fresh, separately captured source evidence** from a permitted and supported Bybit market-data endpoint once reachable, with original raw response files, capture time, source metadata, hashes, and exact spot pair/timeframe. Do not route around access restrictions or assume a forbidden network location is available.
2. Independently reconcile the last frozen original OHLCV candles, especially OPEN and the one ETH LOW, against the newly retained evidence. Investigate whether the old archive was transformed, corrected, or originated from a different field/source. Preserve the original files and forensic trace unchanged.
3. Establish a **complete 15m continuation from 2026-08-01 00:00 UTC**, with UTC-aligned, nonduplicated, closed candles and independently checked source provenance for both BTC/ETH. Only then can any prospective V15/V14 source proof and V17 paperless, hypothetical next-open/stop-first study proceed.
4. Keep no-profit/no-Demo/no-Live gates intact until an independent unseen forward result exists, with uncertainty and trade count reported rather than retrospectively tuned.

This forensic step does **not** prove the Elliott strategy is profitable. **Live=false**, no use of the 500-USDT Paper balance, Laptop1 installation and journal intact, VPS work paused. GitHub source of truth, Laptop2 research only.
