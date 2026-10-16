# NEXUS Elliott V76 — Frozen historical candidate funnel, gross-to-net attribution and break-even hurdle

**Date:** 2026-10-16 UTC. **Mode:** isolated Laptop2 retrospective research, Draft PR #2673, Bybit BTCUSDT/ETHUSDT. **Never** promotes Demo/Paper or enables Live. This is the **previously inspected legacy five-swing** version, not the distinct frozen future V52 15m/3m classifier.

## Question and immutable evidence

V70 independently verified the old ten-trade legacy model: conservative historical simulated net **−16.6141 USDT**, stress **−56.4680 USDT**, with training-positive but validation/test-negative net. V71–V74 found no 15m next-open mismatch, physical stop/target exit discrepancy, or future-suffix reliance at the ten observed decisions in original 15m Elliott features, H1/H4 as-of joins, and 83 combined original-engine feature columns. Those results **do not** establish profitability.

V76 asks: how often were completed five-swing price events blocked before entry, and how much of the surviving candidate trades' historical net returns was consumed by *reference-price movement versus modeled execution slippage and fees*? It does **not** optimize a signal threshold, propose using denied events as trades, or fit the historical validation loss away.

Inputs are the **unchanged original** legacy `actual-fill-trace.json` SHA256 `c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c`, `market-results.json` SHA256 `02f96ca942091d882be7ba87547cd0b6f9c2e3e440fe4cc6e98b3e010332d2fc`, and the V37 receipt SHA256 `96d0322e416e1e7eb5587e08af8dff8b2e8590b677869808ff56d50b6548a024`. The receipt cryptographically binds the source files. `research/elliott_v76_frozen_economic_funnel/funnel_v76.py` reopens them, parses decimal JSON values using exact `Decimal`, independently recomputes each trade's price-based gross, slipped-price gross, adverse modeled slippage, explicit fees and net P/L, and checks per-partition and overall totals against V37 within 1e-8 USDT numerical tolerance. Both paired cost scenarios must have identical source events, admission statuses, decision timestamps and exit labels; any source change or mismatch rejects.

## Fixed historical six-cell signal admission funnel

Each BTC/ETH × train/validation/previously-inspected-test cell is counted only **once**, not once per fee scenario.

| Legacy market and split | Price-event count | Scheduled next-open simulated entry | Denied |
|---|---:|---:|---:|
| BTCUSDT training | 6 | 1 | 5 |
| BTCUSDT validation | 5 | 1 | 4 |
| BTCUSDT previously inspected test | 0 | 0 | 0 |
| ETHUSDT training | 6 | 4 | 2 |
| ETHUSDT validation | 4 | 3 | 1 |
| ETHUSDT previously inspected test | 3 | 1 | 2 |
| **Total** | **24** | **10** | **14** |

Reasons are **overlapping denial-field hits**, not mutually exclusive numbers of rejected events. Across the 14 unique rejections: `h1_vol_ok` was listed **9** times; `elliott5_cost_feasible` **8** times; `h4_up` **1** time. A single rejected event can name two reasons. No conclusion about hypothetical returns on denied events is possible: those transactions **were not simulated as filled orders**. The funnel only measures *admission*, not performance improvement by the filters.

## Gross-to-net decomposition of the ten accepted historical simulated trades

All numbers below are **USDT modeled on the old 10-trade simulation**, not actual exchange-executed P/L.

| Item | Conservative | Higher-cost stress |
|---|---:|---:|
| Reference-price movement gross P/L | +13.3648 | +23.2874 |
| Adverse entry+exit modeled slippage | −9.9930 | −29.9083 |
| Explicit modeled entry+exit fees | −19.9859 | −49.8471 |
| **Recalculated net P/L** | **−16.6141** | **−56.4680** |
| Win/loss count | 4 / 6 | 4 / 6 |
| Historical observed win fraction | 40% | 40% |
| Descriptive break-even win fraction using realized per-win/per-loss amounts | 50.7155% | 76.6118% |

**Interpretation:** the admitted legacy sample's reference-price gross gain was **insufficient to pay modeled fees and slippage**, yielding a loss. This was not an unexpected extra deducted exchange charge: it is exactly the frozen cost model used to produce V37. The two profile gross values differ because the frozen risk budget/model uses different simulated quantities; they should not be compared as the same-position gross P/L. The break-even fractions are algebra computed from the ten **already-observed** wins and losses; they are **not** a calibrated forecast, not confidence bounds, and cannot justify changing cost screens or targets after seeing old results.

The conservative train had +7.9633 USDT net but validation had −17.6745 and the previously inspected test −6.9029. The market signal also did not generalize across held-back historical partitions. The stronger scientific conclusion is **lack of demonstrated robust net profitability** due to adverse validation/sample outcome plus costs—not proof that one revised ATR multiple will recover losses.

## Physical reproducibility and safeguards

- Independent read-only physical study on Laptop2 wrote immutable `E:\NEXUS-QA\elliott-v76-frozen-loss-funnel-20261016\V76_FROZEN_LOSS_FUNNEL.json`, SHA256 `4d9141feaa7c025c7fa6988f8dc9f1e48b013571ffa78598d89484c63610851c`; exit `0`. Original research source, previous journals, frozen protocol and runtime were not touched.
- **10/10 local V76 deterministic regressions PASS**, `research/elliott_v76_frozen_economic_funnel/test_funnel_v76.py`, enrolled in native `tests/test_nexus_elliott_v76_economic_funnel.py`. Tests cover exact economic decomposition, losing stop, net manipulation, modeled slippage sign, zero quantity, 24/10/14 funnel, missing denial metadata, omitted simulated fill, duplicate decision and no-execution flags.
- The test source contains no live Bybit clients, order endpoints or execution integration. Positive or negative historical P/L **never** becomes an entry signal.
- Exact new-HEAD native full suite and hosted Windows/macOS/Ubuntu CI must be checked before asserting V76 is fully green. PR is **Draft and not merged**.

## Prospective boundary

Frozen V52 original SHA256 `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4`, Spot 15m-parent/3m-child, remains unchanged. Oct16–17 UTC are warmup source days, first scored day is Oct18 UTC and its **complete daily source cannot exist before Oct19 00:00 UTC**, potentially later if not yet officially published. V75 actual-clock first-day preflight rejected both early capture and ingestion as required. The separate public top-of-book availability diagnostic proves only transport at its timestamp. Never claim new wave profitability, Demo order, source-backed quote-to-signal fill, or real forward score from legacy results.

**Research decision:** `VALIDATION_AND_TEST_NEGATIVE_LEGACY_EXPECTANCY`; retain V70 `REJECT_PROMOTION_OUT_OF_SAMPLE_HISTORICAL_LOSSES` and Live disabled. Further future research should test a **separately preregistered**, source-verifiable Elliott hypothesis without retrospective alteration of this already-inspected dataset.
