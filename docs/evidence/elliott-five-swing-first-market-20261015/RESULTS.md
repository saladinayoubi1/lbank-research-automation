# Elliott five-swing — first source-bound Bybit historical market evaluation

**Verified on 2026-10-15 UTC.** Research-only; this is **not** a pristine holdout, not qualified for Demo, and not a live run. Source head at evaluation: `5eed07d9aeb1b425fdacb868ee352b8ff36e3345` (PR #2661). One frozen candidate, BTCUSDT and ETHUSDT Spot historical 15m with causally completed 1h/4h. Exact source, fixtures, delivery/archive, prior v9 ledger and native source gate were checked before the evaluated run and rechecked afterward.

## Twelve complete diagnostic rows

The three history partitions use independent 10,000 USDT simulations **per cell**, each with the original shared stop/risk/next-open engine. Costs below are fee/slippage per leg 10/5 basis points (conservative) and 25/15 (stress). This is **not** a 500 USDT owner account performance statement.

| Symbol | Partition | Closed round trips (each profile) | Conservative net USDT | Stress net USDT |
|---|---|---:|---:|---:|
| BTCUSDT | Train | 1 | +6.05848993 | +2.03277225 |
| BTCUSDT | Validation | 1 | -10.02216124 | -13.96767615 |
| BTCUSDT | Historically inspected test | 0 | 0 | 0 |
| ETHUSDT | Train | 4 | +1.90481390 | -14.07933457 |
| ETHUSDT | Validation | 3 | -7.65236534 | -19.58979217 |
| ETHUSDT | Historically inspected test | 1 | -6.90289395 | -10.86396630 |

Independent-partition sum **only as diagnostic arithmetic**, never as a compounded wallet backtest: BTC conservative -3.96367131 / stress -11.93490390 (2 closed trades each); ETH conservative -12.65044539 / stress -44.53309303 (8 trades each). Means across those independent partitions: BTC -1.98183566 / -5.96745195; ETH -1.58130567 / -5.56663663 USDT/trade (conservative / stress). Total simulated round trips **10 per cost profile**. Activity remains sparse; no minimum-trade gate was added.

**Conclusion:** Validation is negative under both cost profiles for both pairs; ETH historically inspected test is negative, and BTC historically inspected test has zero trades. Do **not** promote to Demo/Paper or claim a fresh unseen holdout. The full recursive Elliott count is still unproved.

## Native execution and correction history

- Laptop2 research device: `DESKTOP-F4SA4VL`; unchanged installed owner Paper writer on Laptop1.
- First isolated invocation SHA-256 `613b9691a0d1cfffd82c5ecff2b22b0b15fdb58fc9e978d2fa79ff19aa8c5b97`: native child PID 9640 exited 1 after the first diagnostic cell because the **report-only formatter** attempted `float(None)` for a legitimate no-trades `win_rate_pct`. Permanent failed attempt and logs retained at `E:\NEXUS-QA\elliott-five-swing-market-first-20261015`. No prior v9 replay.
- One correction retry in separate isolated directory `E:\NEXUS-QA\elliott-five-swing-market-correction-20261015`, changing **only** that nullable win-rate formatter. Frozen retry invocation SHA-256 `438cca4195bca3ec173695994d33de83fd257644495c3882afddcdac5c565a73`. Native child PID 5904 exited **0**, without timeout, after 71.031 seconds. No strategy conditions, simulator, fees, risk or archived data changed.
- 12/12 result rows, full actual next-open fill traces, and immutable evidence files retained in corrected stage. Native `stderr.log` is empty.

## Integrity and independent math audit

- Bybit semantic archive: `2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422`; prior v9 terminal ledger digest `b784b409c16b77fa5d6dd5d65b7f8ed67e13e65aa6d230a74e843f9e63720e8f`.
- Native market result file SHA-256 `02f96ca942091d882be7ba87547cd0b6f9c2e3e440fe4cc6e98b3e010332d2fc`; actual fill trace SHA-256 `c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c`.
- Independent **Decimal** read-only audit checked all 12 cells and 20 repeated-profile round-trip traces (10 per cost profile), fee formulas, slippage, exact next-open index/time, per-trade P&L, and aggregate reconciliation. **All passed.** Physical QA artifact: `independent-decimal-qa.json` in the corrected stage.
- Separate **market leakage / fully independent source-data numerical review remains incomplete**. Training and later historical partitions were previously inspected in prior strategy development; no pristine forward-looking qualification claimed.
- `live_enabled=false`, `auto_demo=false`, `research_only=true`, `VPS work owner-paused`, and no owner journal, installed app, credential, runner or Paper deployment changes.

## Next gate

Leave PR as draft; do not merge or admit the candidate. Independently review market-event chronology/leakage and investigate low trade opportunity density with **new preregistration**, without rewriting these immutable findings or retuning on the previously inspected test.
