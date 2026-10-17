# Elliott — physical public Spot quote transport readiness (2026-10-16)

**Research-only, no entry/exit signal, no orders or P/L.** This is a one-shot source acquisition diagnostic performed on Laptop2 `DESKTOP-F4SA4VL`, in an isolated path. It is **not** a V52 prospective market score and is not connected to an Elliott candidate.

## Source and observations

At approximately **2026-10-16 13:54:48–49 UTC**, the machine fetched one top-of-book snapshot per pair from the **public, unauthenticated** Bybit Spot orderbook endpoint (`api.bybit.com/v5/market/orderbook?category=spot&symbol=...&limit=1`). Responses had HTTP 200, `retCode=0`, and matching symbol; a TLS certificate-validating HTTPS client, no configured proxy, and a no-redirect transport were used.

| Pair | Quoted best bid | Quoted best ask | Quoted bid qty (base units) | Quoted ask qty (base units) | Server quote age at client receipt | Quoted spread |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 81964.3 | 81964.4 | 0.309267 | 1.660164 | 197 ms | 0.0122004 bps |
| ETHUSDT | 2458.65 | 2458.66 | 5.55473 | 3.43595 | 213 ms | 0.0406726 bps |

Both snapshots met the **2-second age screen** as a *transport-level diagnostic*. The apparent age is based on machine wall clock and the provider-supplied quote timestamp; **not an independently exchange-signed proof of timestamp accuracy**. The quantities above are **one top-of-book level only**, not a guaranteed fill quantity or continuous liquidity.

### Physical reproducibility anchor

- Immutable receipt: `E:\NEXUS-QA\elliott-quote-readiness-20261016\PUBLIC_SPOT_QUOTE_READINESS.json`
- On-device SHA256, independently recalculated using Windows CertUtil: `2d6f05e7b9db2fa2e7dd09d14f3ae34f4127cbfecedf696d3c69b4553de795b9`
- Read-only capture script: `E:\NEXUS-QA\elliott-quote-readiness-20261016\capture_public_spot_quote.py`
- Original raw-response SHA256 values and request/receipt clocks for each symbol are in the local receipt.
- One request per symbol, no credentials, no private Bybit API, no retry, no trading capability.

## Scientific and deployment boundaries

**Confirmed:** public spot best bid/ask snapshots can be reached on Laptop2, with noncrossed top-of-book and fresh-enough provider timestamp in these two isolated requests.

**Not confirmed:** contemporaneous source-bound Elliott wave event, post-signal chronology, quote-to-order matching, real buy/sell fill, minimum depth, exchange-signed source provenance, Demo account availability, Bybit private API, strategy expectancy, or any forward V52 score. A transport-only observation cannot pass the V26 signal-specific quote gate without a validated signal; never fabricate one.

The frozen V52 experiment remains **warmup October 16–17 UTC**, and the scored future interval starts **October 18 UTC**; physical full-day archives and V69 as-of gates remain mandatory. This report changes no parameter of V17/V24/V26/V52/V69, no laptop1 installation or Paper ledger, and no VPS. PR remains Draft; **Live=false, auto_demo=false, entry_signal=false, paper_eligible=false, pnl=null, orders=0**.
