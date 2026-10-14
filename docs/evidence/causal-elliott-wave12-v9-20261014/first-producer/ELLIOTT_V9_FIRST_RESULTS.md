# Elliott v9 first market results

The one frozen Elliott-inspired wave 1–2 candidate lost money after costs in every one of the twelve locked diagnostic cells. It is not selected for Demo. This finding applies to this preregistered proxy and simulator contract, not to every possible Elliott method.

Exact computational source: `8c06ca692a06611431730e4aeb822b1d9f47f30d`. Prospective market invocation frozen at `7841567d81e466b428eafecd35d8d32fd334362e`; it ran once. Native producer PID 6308 and wrapper PID 6604 both have actual OS exit 0 captured by their owning parents. Outer parent PID 9160 completed its durable checkpoint at 2026-10-14T16:24:08.542914Z. No producer replay occurred.

Bybit Spot BTC/ETH long-only, 15m closed decisions with completed 1h/4h context. Each asset/partition/cost cell has separate 10000 USDT simulated cash; owner reference remains 500 USDT. Monetary results below are exact USDT quote-unit outputs rounded only for display; no fiat conversion is made.

Cost assumptions per leg: conservative 10 bps fee + 5 bps slippage; stress 25 bps fee + 15 bps slippage. Both use the same next-open/stop-first/1.5ATR/2R/64-bar, 10% cash cap, 0.1% stop-risk, 5% daily loss and 10% drawdown guards. There is no minimum-trade or maximum-trades filter.

| Partition | Closed UTC coverage | Bars |
|---|---|---:|
| Training | 2022-12-01 00:15 → 2025-02-11 09:30 | 77126 |
| Validation | 2025-02-11 09:45 → 2025-11-06 04:45 | 25709 |
| Previously inspected final fold | 2025-11-06 05:00 → 2026-08-01 00:00 | 25709 |

These are fixed historical folds, not monthly returns or pristine prospective holdouts. Four Training cells screened exactly one preregistered candidate; Validation and the previously inspected final fold did not select or retune it.

| Asset | Partition | Costs | Closed round trips | Net P/L (USDT) | Mean closed P/L (USDT) | Return (%) | Max drawdown (%) | Profit factor |
|---|---|---|---:|---:|---:|---:|---:|---:|
| ETHUSDT | validation | stress | 83 | -610.62 | -7.36 | -6.1062 | 6.1429 | 0.1833824 |
| ETHUSDT | validation | conservative | 84 | -195.33 | -2.33 | -1.9533 | 2.3095 | 0.5861774 |
| ETHUSDT | train | stress | 129 | -996.29 | -7.72 | -9.9629 | 10.0149 | 0.0672321 |
| ETHUSDT | train | conservative | 236 | -674.11 | -2.86 | -6.7411 | 6.8618 | 0.4035337 |
| ETHUSDT | historically_inspected_test | stress | 72 | -553.35 | -7.69 | -5.5335 | 5.5335 | 0.0923014 |
| ETHUSDT | historically_inspected_test | conservative | 71 | -217.51 | -3.06 | -2.1751 | 2.1957 | 0.3983280 |
| BTCUSDT | validation | stress | 72 | -525.96 | -7.30 | -5.2596 | 5.2596 | 0.0342582 |
| BTCUSDT | validation | conservative | 70 | -179.01 | -2.56 | -1.7901 | 1.7901 | 0.3113087 |
| BTCUSDT | train | stress | 143 | -1011.25 | -7.07 | -10.1125 | 10.1125 | 0.0667408 |
| BTCUSDT | train | conservative | 257 | -790.07 | -3.07 | -7.9007 | 7.9007 | 0.2995747 |
| BTCUSDT | historically_inspected_test | stress | 65 | -517.45 | -7.96 | -5.1745 | 5.1745 | 0.0285364 |
| BTCUSDT | historically_inspected_test | conservative | 64 | -184.33 | -2.88 | -1.8433 | 1.9077 | 0.3128782 |

All twelve net returns are negative and all twelve realized profit factors are below 1. Stress runs are independent simulations; costs affect execution and risk guards, so their trade counts need not equal the conservative cells. Training stress hit the drawdown guard in the fixed engine; no trade-count threshold was imposed.

Existing result reconciliation verified eleven exact native artifact byte identities, both canonical receipts, report/ledger digests, the twelve-cell grid, candidate/risk/cost/coverage bindings, four Training-screen/full-replay metric matches and complete predecessor history. A separate bounded read-only native collection rechecked 53 source/gate/raw/predecessor/invocation byte bindings unchanged. The ledger adds only the Elliott fingerprint and evaluated/screened identity; its screening-version tag advances from v8 to the exact v9 constant in the frozen source. Original predecessor bytes remain unchanged.

Aggregate net cash reconciles with reported net returns; mean closed P/L is net P/L divided by closed round trips. The shared engine liquidates terminal positions, so no open mark-to-market position is mixed into this mean. This is artifact and aggregate reconciliation, not an independent trade-ledger Decimal/numeric/market leakage audit. Those QA gates remain incomplete.

Report digest: `979f39c6848f946deb8765885849c86da2c26702f2789b7b56c62534ed832e0b`. New terminal ledger digest: `b784b409c16b77fa5d6dd5d65b7f8ed67e13e65aa6d230a74e843f9e63720e8f`; exact file SHA256 `14cc329d8acd02fbc3a13268826446f44d05dcf9eb299a6c13738558342f401c`. This terminal ledger is the next hypothesis predecessor; never reset it or replay v9 to refresh evidence.

Research-only: no Demo selection/admission, automatic Demo promotion, official Coordinator advancement or Live action. Laptop1 remains sole Paper writer; failover disabled. Owner installation/profile/journal/checkpoint/authentication, Windows recovery and VPS were not changed. System Map: DATA-21 / RES-30 / RES-31 / RES-32 / VAL-40 / QA-41.

Next: diagnose economic and causal failure modes from Training-only evidence before preregistering a genuinely new hypothesis. Do not use observed Validation/final-fold results to tune this version; do not replay the completed Butterfly or Elliott producer.
