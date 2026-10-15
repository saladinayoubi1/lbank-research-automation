# Spring v12 | Trade economics review

**2026-10-15 UTC — Research only. Decision: DO NOT PROMOTE TO DEMO.**

This is an analysis of the already-completed one-shot Bybit historical research trace, **not another market backtest**. Original evaluated commit: `d9b179cf2c3b8ed5369c16cb36e17d802e0877b3`. The 12 original cells, 34 fee-profile trade records, and 17 distinct decisions were reconciled with Decimal arithmetic. See [full source-bound audit](./TRADE_ECONOMICS_QA.json) (SHA-256 `91d1bac9a2c51e1bdef6e54c9da30c7073ac52274a43d4f4f0df5c99eeaf0cd0`).

| Asset/cost | Trades | Observed gross reference, USDT | Fees + slippage, USDT | Net USDT | Stops / targets / other |
|---|---:|---:|---:|---:|---|
| BTC conservative | 9 | +21.05 | 26.99 | **−5.94** | 5 / 3 / 1 |
| BTC stress | 9 | +13.44 | 71.65 | **−58.21** | 6 / 3 / 0 |
| ETH conservative | 8 | −7.07 | 23.93 | **−31.00** | 6 / 2 / 0 |
| ETH stress | 8 | +0.91 | 63.67 | **−62.75** | 6 / 2 / 0 |

Costs per leg: conservative **10 bps fee + 5 bps slippage**; stress **25 bps fee + 15 bps slippage**. All figures aggregate **independent 10,000 USDT research fold accounts**, not a compounded portfolio or the 500 USDT Demo reference. Gross is *conditional on the observed fills and exit path*, **not** a cost-free counterfactual replay.

**Structural findings:** All **4 ETH training entries** hit the stop (−30.24 USDT conservative). BTC validation had 2 trades and changed from +6.40 USDT conservative to −1.63 stress. ETH validation's +9.74 conservative/+5.70 stress came from **one target trade only**. Of 17 trade identities, **8 exit bars differed** under stress; one time-64-bar exit became a stop. This precludes extrapolating a no-cost strategy from the observed gross reference.

The original 41 unique first support-reclaim events yielded 17 accepted and 24 denied entries per profile; denial fields overlap. Neither bypassing gates nor retrospective sweep-depth/ATR tuning has been tested or is authorized. The already-inspected final fold is **not a pristine holdout**. New inference requires separately preregistered research and genuinely future unseen observations.

Evidence: [market result](./market-results.json), [independent Decimal audit](./independent-decimal-qa.json), [independent Bybit raw-bar chronology](./independent-raw-spring-qa.json), [monthly 176-row report](./MONTHLY_UTC_REALIZED.csv). Live trading, automatic Demo admission, installed NEXUS, Laptop1 Paper writer and paused VPS remain unchanged.
