# Spring v12 — first frozen Bybit historical research result

**Date:** 2026-10-15 UTC. **Decision:** **NOT APPROVED FOR DEMO**. This is one pre-registered diagnostic using an **already researched, non-pristine historical archive**, not a forward holdout, a performance promise or a Paper account trade.

## Frozen execution provenance

- Evaluated **source head**, not the subsequently added documentation commits: `d9b179cf2c3b8ed5369c16cb36e17d802e0877b3` on Draft PR #2666 (stacked on Draft ABC PR #2662).
- Bybit Spot, BTCUSDT / ETHUSDT, 15-minute decision bars with previously closed one-hour and four-hour context; fixed 60/20/20 chronological split; conservative **10 bps fee + 5 bps slippage per leg**, stress **25 bps fee + 15 bps slippage per leg**.
- **Separate 10,000 USDT simulated research cash per fold/cost cell**. NEXUS owner's reference Paper balance of 500 USDT was **not** touched; sums below are not compounded account equity.
- Source binding: **60 file hashes**, including six Spring additions matched to GitHub blob IDs; immutable Bybit archive manifest and six raw price parquet hashes and previous v9 ledger verified; new preregistration matches its stored Git blob.
- Native research host **DESKTOP-F4SA4VL** (Laptop2), **132 tests PASS**, zero errors/failures on exact staged source. GitHub head CI **Test / Research Evidence Refresh / Workflow Permissions Policy all SUCCESS** across required platforms.
- One owned frozen native child process **PID 2840**, exit **0**, duration **76.532 s**, no timeout/retry; immutable invocation SHA-256 `4a6cce98a58d5dc21cb3632e61a85cc1a6dec42cecb92ecf902a358ee3d4f668`.
- Frozen market result SHA-256 `9f1d95e5e36590eb2ae1b011200e6e0e1b7778198254620a9cafcdaec046231e`; full original trace SHA-256 `c856e4744268ada84788ff562e18fdabadbd01fca94f95f3c929c60bc4a0d7b8`.
- The original complete provenance, producer, invocation, trace, native exit receipt, audit scripts and locks are retained read-only on Laptop2 under `E:\NEXUS-QA\spring-v12-first-market-20261015\`.

## Twelve exact original research cells

Amounts in **USDT**. No trade-count floor. Price-event counts below are independent fresh first closed-candle support reclaims, not accepted trades.

| Symbol | Historical fold | Closed round trips | Conservative net | Stress net | Unique price events |
|---|---|---:|---:|---:|---:|
| BTCUSDT | Train 60% | 1 | −9.41809576 | −13.36662347 | 9 |
| BTCUSDT | Validation 20% | 2 | +6.39781965 | −1.62599821 | 4 |
| BTCUSDT | Already inspected last 20% | 6 | −2.92427537 | −43.21658159 | 8 |
| ETHUSDT | Train 60% | 4 | −30.23614854 | −46.02187975 | 16 |
| ETHUSDT | Validation 20% | 1 | +9.74017392 | +5.69609372 | 1 |
| ETHUSDT | Already inspected last 20% | 3 | −10.50590325 | −22.42683464 | 3 |

### Sums of separately reset research folds, not a compounded equity curve

| Symbol | Closed trades | Conservative net | Stress net | Conservative mean/trade |
|---|---:|---:|---:|---:|
| BTCUSDT | 9 | −5.94455149 | −58.20920327 | −0.66050572 |
| ETHUSDT | 8 | −31.00187787 | −62.75262068 | −3.87523473 |
| **Total distinct trade histories** | **17** | **−36.94642935** | **−120.96182395** | — |

The small positive validation result is **not an edge**: BTC has only 2 validation trades and becomes negative with stress costs; ETH has only 1 validation trade, a sample too small for meaningful robustness. Both symbols are losing overall; each symbol also has losses in the train fold and the last previously inspected fold.

## Independent source-grounded audits

- [`market-results.json`](./market-results.json): complete summary of 12 original market cells, source-bound.
- [`independent-decimal-qa.json`](./independent-decimal-qa.json): external-to-engine Decimal accounting verifies all 12 P/L summaries, **34 profile trade records** (17 distinct trade decisions observed under each fee profile), next-open entry, fees and slipped fill prices. **PASS**.
- [`independent-raw-spring-qa.json`](./independent-raw-spring-qa.json): independent original 15m Bybit parquet chronology audit, right-three-bar pivot latency, `L0 < H1` and `L2 < L0`, 96-bar span and 16-bar eligibility, first close reclaim, interim raw candle invalidation, independently computed fixed stress cost, raw next-bar opening fills, same-bar stop-first exits. **PASS**, evidence SHA-256 `7a6c1cb59f513dde41382a457049b8e49e9b2d565228f1f12ea09690267e10fe`.
- Funnel: **41 unique first reclaim events** (82 event records across the two cost profiles); per profile **17 scheduled next-open entries and 24 denied signals**. Denial-field occurrences across both profiles were `h4_up=30`, `h1_vol_ok=12`, `spring_stress_cost_feasible=20`. Reasons **overlap** and must not be added as exclusive counts. `h1_vol_ok` is a closed-hour normalized **volatility/range** filter, not trade volume.
- The independent audit does **not** claim proof that every parent higher-timeframe feature was line-by-line independently reimplemented; original parent source and causal-asof tests and unchanged-source binding were separately checked.
- The monthly derived report is now delivered as [`MONTHLY_UTC_REALIZED.csv`](./MONTHLY_UTC_REALIZED.csv), with a separate [`monthly-aggregation-proof.json`](./monthly-aggregation-proof.json). It includes **176 monthly rows** = 44 UTC months (2022-12 through 2026-07) × BTC/ETH × two cost profiles, including months with zero trades. Each row reports the number of closed positions, realized net USDT, and mean net per closed trade (blank when zero). Attribution is by **UTC month of the exit decision close**. Every partition's count and net reconcile to the original 12 cells to within 0.00001 USDT. CSV SHA-256: `131e697d99af9939a5db7ad7747fb2c7a03f151aa1694a541cb8ade3224ec1e5`. **No market backtest was rerun** for this report. Historical test remains previously inspected, and totals combine independent reset research cash cells, not a continuously compounded account.

## Independent trade-economics follow-up

[Detailed accepted-trade diagnosis](./TRADE_ECONOMICS_REVIEW.md) and [machine-readable Decimal proof](./TRADE_ECONOMICS_QA.json) are published as **derived analyses only**, with no additional market replay. For 17 unique trades (34 fee-profile records), BTC conservative observed pre-slip reference gross was +21.05 USDT versus 26.99 USDT in fees/slippage (net −5.94); ETH conservative reference gross was −7.07 versus 23.93 in friction (net −31.00). ETH train stopped out on all 4 accepted trades. Stress costs changed 8 of 17 trade exit bars. This further supports **no Demo promotion**; the inspected history is not an independent new holdout.

## Disposition

**Reject Spring v12 as a Demo candidate.** No retrospective retuning on the previously inspected final fold, no bypassing cost/context gates and no automated promotion. Further candidate research requires a separately preregistered rationale and a genuinely future unseen diagnostic window. Keep installed NEXUS and Laptop1 sole Paper writer unchanged; no Live trades, no VPS operations (owner-paused). PR remains **Draft**, not merged.
