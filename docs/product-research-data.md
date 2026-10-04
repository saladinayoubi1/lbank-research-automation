# Research data in the desktop app

The Data & Market view now has a separate Bitget public-data panel. BTCUSDT and
ETHUSDT have 120 closed Spot bars in each of 15m, 1h and 4h. Source-native
timestamps, OHLCV strings and provider identity are retained. Every stored
dataset has a canonical digest. The existing Bybit canonical vault, registry,
qualification path and Paper journal remain separate.

Polling starts only after the local polling API is enabled. It survives a
restart through its own settings file, checks every 60 seconds after a completed
cycle, and pauses after two failed cycles. GET endpoints perform no network
collection. Public transport uses HTTPS to the fixed Bitget Spot history
endpoint, with no redirects, proxies, credentials or exchange orders. Missing,
duplicate, malformed or open-window data cannot replace previous valid bytes.
A cache is fresh only when its observation is recent and its latest closed
boundary equals the current timeframe boundary.

The previously collected Bitget audit can be loaded using
AlternativeMarketStore.import_audit. HTTP receipts, body digests, normalized
historical candle digests and exact 300-day coverage are verified. This imports
two 1,800-bar historical Spot datasets and checks the already-reviewed native
contract quantity, price, public fee, funding and risk-tier semantics. Unit/fee
examples use the provider's closed Futures trade price. They place no orders,
mutate no Paper wallet and grant no Demo replacement or strategy qualification.

The Research view includes the reviewed A7 and A9 artifact reports. Report
schemas, original producer SHA and canonical report digests are pinned to the
verified runs. Numerical rows, original source evidence and original negative
qualification results are kept intact. The research normalization is 10,000
USDT. Independent cost profiles and A9's historically inspected test partition
remain explicit; no result is projected as a pristine future holdout or the
owner's 500-USDT Paper return.

Routes:

| Route | Meaning |
|---|---|
| GET /api/product/alternative-market | Cache and current collection health |
| POST /api/product/alternative-market/refresh, {} | One asynchronous bounded refresh |
| POST /api/product/alternative-market/polling, {"enabled": true/false} | Start/stop public-data collection |
| GET /api/product/research/reports | Read-only reviewed reports; rejected artifacts are excluded |

Bitget data availability is research evidence only. It does not convert
Bybit-priced positions, enable Paper execution, qualify a strategy or enable
Live. Existing default authentication, localhost/Origin guards and JSON request
bounds apply to the new routes.
