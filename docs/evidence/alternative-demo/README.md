# Actual secondary-device public data audit, 2026-10-03 UTC

Device: `DESKTOP-F4SA4VL` (authorized RDC ID
`c569416a-305a-49f8-8104-0f8971dd817f`). The native Python processes completed
with exit code 0: Bitget PID 6768 (20.53s), KuCoin PID 9536 (11.67s).
Neither process opened an exchange account or a Paper runtime.

Both receipts bind to audit source SHA-256
`c3bc79c2b83f2afd3e4187d3fefa94a34e470d7da349cb4fcdd6251071f984f4`
and the exclusive 4h boundary `1791057600` (2026-10-03 20:00 UTC).
Warmup starts `1765137600` (2025-12-07 20:00 UTC). Each spot pair requires
exactly 1,800 closed 4h bars; this is data-grid coverage, not a strategy trade-count
gate. Public HTTP receipts include URLs, observation timestamps and body digests.
The checked-in manifests preserve the producer output; raw bodies are retained
under the secondary device's isolated `NEXUS-public-audits/20261004-tv-demo`
cache (`bitget-v2/public-http` and `kucoin-v2/public-http`).

| Provider/pair | Spot warmup | Trade/mark, each | Funding, 24h | Execution, 5m | Lot/fee fields; risk tiers | Collection |
| --- | --- | --- | --- | --- | --- | --- |
| Bitget BTC | 1800/1800 | 6/6 | 3/3 | 5/5 | present; 12 | pass |
| Bitget ETH | 1800/1800 | 6/6 | 3/3 | 5/5 | present; 15 | pass |
| KuCoin BTC | 1800/1800 | 6/6 | 3/3 | 4/5 | present; 12 | fail |
| KuCoin ETH | 1800/1800 | 6/6 | 3/3 | 5/5 | present; 12 | pass |

Bitget is the first **collection candidate**, not an approved Demo replacement.
Its native BTC minimum/step is 0.0001 base coin, unlike the frozen Bybit account's
specification. KuCoin uses contract lots (BTC multiplier 0.001, ETH 0.01), so
its quantities cannot be passed through an unmodified Bybit adapter.

KuCoin BTC is missing the execution minute at `1791043440`. A targeted official
public follow-up extended the same UTA query through `1791043560`:
`/api/ua/v1/market/kline?symbol=XBTUSDTM&tradeType=FUTURES&interval=1min&startAt=1791043200&endAt=1791043560`.
It returned starts 1791043200, 1791043260, 1791043320, 1791043380, 1791043500,
1791043560, still omitting 1791043440. This is an observed missing bar;
the cause is not proven. No synthetic minute or price was inserted.

The first Bitget diagnostic exposed a client-pagination error: subtracting 1ms
from a native end boundary skipped one candle per page because the API floors
and excludes the end boundary. The corrected client uses exact boundaries.
Its regression test reproduces that behavior and verifies the entire 300-day
grid. The final receipts above come from the corrected source and a new cache,
not from editing the initial failed result.

For promotion/replacement, still required: provider-native adapter, complete
historical validation with conservative/stress costs, independent numerical QA,
isolated account reconciliation and persistent/restart feed proof. The existing
Bybit account, position and journal remain untouched. Live/L4 stays off.
