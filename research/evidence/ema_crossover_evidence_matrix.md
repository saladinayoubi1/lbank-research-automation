# EMA Crossover Evidence Matrix for Crypto and FX

**Status:** research-only / paper-trading-only  
**Tracking issue:** #71  
**Parent research program:** #45

## Scope and decision boundary

This note evaluates EMA crossover as a bounded trend-following research hypothesis in cryptocurrency and foreign-exchange markets. It does not claim that EMA 20/50 is optimal, profitable, production-ready, or suitable for live trading. Parameter values below are pre-registered starting points for falsifiable backtests.

## Evidence grading

- **High:** peer-reviewed or broadly replicated evidence directly relevant to trend/time-series momentum, with explicit out-of-sample or robustness analysis.
- **Moderate:** relevant empirical evidence with narrower market coverage, working-paper status, or indirect mapping from momentum/trend rules to EMA crossover.
- **Low:** practitioner or implementation evidence useful for hypothesis formation but insufficient for causal or profitability claims.

## Evidence matrix

| ID | Claim | Market | Evidence | Grade | Applicability to EMA crossover | Main limitation / opposing evidence | Backtest implication |
|---|---|---|---|---|---|---|---|
| E1 | Trend and time-series momentum can exist across liquid futures, including currencies, over intermediate horizons. | Multi-asset, including FX futures | Moskowitz, Ooi, and Pedersen (2012), *Time Series Momentum* | High | Supports testing directional trend rules, but not any specific EMA pair. | Evidence is portfolio-level and horizon-specific; it does not establish persistence at intraday horizons or in spot crypto. | Test multiple holding horizons and avoid inferring EMA 20/50 superiority from generic momentum evidence. |
| E2 | Moving-average rules and time-series momentum are related but not equivalent; signal timing can materially differ. | Primarily equities in the cited comparison | Marshall, Nguyen, and Visaltanachoti (2014/2015), *Time-Series Momentum versus Moving Average Trading Rules* | Moderate | Directly supports treating EMA crossover as a separate rule family rather than a proxy with assumed equivalence. | Reported gains are market-dependent and do not directly cover crypto or spot FX. | Record exact signal convention, execution lag, and crossover timing; compare against a simple return-sign momentum baseline. |
| E3 | Currency momentum implementations commonly use mixtures of exponential moving averages, and results vary across G10, emerging-market currencies, and cryptocurrencies. | FX and crypto | Rohrbach, Suremann, and Osterrieder (2017/2019), *Momentum and Trend Following Trading Strategies for Currencies Revisited* | Moderate | Directly relevant to EMA-based signals across both target asset classes. | Working-paper evidence; portfolio construction and volatility scaling differ from a simple EMA 20/50 rule. | Evaluate crypto and FX separately; include volatility scaling as an explicit variant, not an unreported adjustment. |
| E4 | FX technical-rule profitability is episodic rather than consistently stable, which is more consistent with adaptive/regime-dependent behavior. | FX | *FX technical trading rules can be profitable sometimes!* (Research in International Business and Finance) | Moderate | Supports regime-aware interpretation of crossover results. | Positive short periods can be selected by chance; persistence is weak. | Predefine walk-forward windows and report the fraction of profitable windows, not only aggregate Sharpe. |
| E5 | Return persistence and volatility can drive trend-rule profitability, while market development and frictions can reduce it. | Global equity indices; indirect mechanism evidence | *Drivers of technical trend-following rules' profitability in world stock markets* | Moderate | Supports ATR/volatility-regime hypotheses, but only indirectly for FX and crypto. | Different asset class and market structure; volatility can also increase turnover, slippage, and liquidation risk. | Test ATR filters and volatility scaling with net returns, turnover, and drawdown reported jointly. |
| E6 | Some FX rule predictability is concentrated around central-bank intervention periods. | FX | LeBaron (1999), *Technical trading rule profitability and foreign exchange intervention* | Moderate | Shows that apparent trend profitability may be event/regime dependent. | Historical intervention regime and data may not generalize to current electronic FX markets. | Add event/regime annotations where available; do not pool all FX periods without stability tests. |
| E7 | Crypto momentum conclusions can reverse after realistic liquidation and return-distribution assumptions; mean return alone is inadequate. | Crypto | Han, Kang, and Ryu (2023; revised 2026), *Momentum in the Cryptocurrency Market: A Comprehensive Analysis under Realistic Assumptions* | Moderate | Strong warning against interpreting gross EMA backtests as deployable profitability. | Momentum formulation is broader than EMA crossover and includes leverage/liquidation settings not present in spot-only tests. | Report arithmetic and compounded return, tail loss, drawdown, skew, turnover, and liquidation/funding assumptions where derivatives are used. |
| E8 | Data snooping and multiple-rule searches can create false technical-trading discoveries. | General technical-rule research | Sullivan, Timmermann, and White (1999), *Data-Snooping, Technical Trading Rule Performance, and the Bootstrap* | High | Directly limits parameter mining over EMA pairs, filters, assets, and timeframes. | Statistical corrections do not repair poor data, unrealistic execution, or regime leakage. | Pre-register the primary EMA 20/50 test; treat alternative pairs as a family and apply multiple-testing controls or a held-out test set. |

## Pre-registered hypotheses

### H1 — Baseline directional effect

For each asset and timeframe, a long/flat EMA 20/50 crossover strategy has higher **net risk-adjusted return** than a matched always-long or cash benchmark in out-of-sample windows.

**Falsification:** median out-of-sample Sharpe is not positive, or net performance is not better than the predefined benchmark after costs.

### H2 — Regime dependence

EMA 20/50 performs better during high-persistence/trending regimes than during range-bound regimes.

**Operationalization:** classify regimes using a rule fixed before testing, such as ADX or a return-autocorrelation/trend-strength measure calculated without future data.

**Falsification:** no stable difference exists across walk-forward windows, or the effect disappears after costs and multiple-testing adjustment.

### H3 — ATR filter

A pre-specified ATR-based entry filter reduces false crossovers and maximum drawdown without materially degrading net return.

**Falsification:** drawdown reduction is absent or offset by lower net return, worse tail loss, or unstable parameter sensitivity.

### H4 — Volume filter in crypto

For crypto venues with defensible volume data, a pre-specified relative-volume filter improves signal quality versus the unfiltered baseline.

**Falsification:** improvement is not robust across venues/assets or disappears after turnover and slippage.

**FX boundary:** spot FX lacks a centralized consolidated volume series; tick volume or futures volume must be labeled as a proxy and tested separately.

### H5 — Cross-market portability

The same fixed EMA 20/50 rule does not have equal efficacy in crypto and FX because session structure, volatility, carry/funding, market fragmentation, and trading costs differ.

**Falsification:** standardized out-of-sample effect sizes and failure rates are statistically and economically indistinguishable across the two market groups.

## Minimum backtest contract

1. **Signal timing:** compute indicators using completed bars only; execute no earlier than the next tradable observation.
2. **Primary parameters:** EMA fast = 20, EMA slow = 50. Alternative pairs are secondary and must not replace the primary result.
3. **Costs:** include explicit spread, commission, slippage, and turnover assumptions. For FX, include carry/roll where positions cross the relevant boundary. For crypto derivatives, include funding and liquidation mechanics; spot tests must not silently inherit derivative assumptions.
4. **Data integrity:** document venue, symbol definition, timezone, missing bars, delistings, contract changes, and survivorship handling.
5. **Validation:** use chronological train/validation/test or walk-forward evaluation. No random shuffling of time-series observations.
6. **Multiple testing:** disclose the number of assets, timeframes, EMA pairs, filters, and regime definitions tried.
7. **Metrics:** net CAGR/return, Sharpe or Sortino with stated annualization, maximum drawdown, Calmar, profit factor, hit rate, turnover, exposure, tail loss, and window-level stability.
8. **Robustness:** perturb costs, execution delay, EMA lengths, start dates, and venue/data source. Report failure regions, not only the best configuration.
9. **Benchmarking:** compare against cash, buy-and-hold where meaningful, and a simple return-sign/time-series-momentum baseline.
10. **No promotion:** passing a historical backtest permits only further paper-forward evaluation; it is not authorization for live trading.

## Initial test grid

| Dimension | Primary | Secondary sensitivity |
|---|---|---|
| Markets | BTC/USD or BTC/USDT spot; EUR/USD spot | ETH, GBP/USD, USD/JPY |
| Timeframes | 1h, 4h, 1d | 15m only if cost data is credible |
| Rule | EMA 20/50 long/flat | EMA 10/50 and 50/200, controlled as secondary tests |
| Execution | next-bar open or next observable quote | +1 bar delay stress test |
| Cost stress | venue/pair-specific base estimate | 0.5x, 1.5x, 2.0x base cost |
| Validation | anchored or rolling walk-forward | alternate window lengths fixed before inspection |

## Source registry

1. Moskowitz, Tobias J.; Ooi, Yao Hua; Pedersen, Lasse Heje. “Time Series Momentum.” *Journal of Financial Economics* 104(2), 2012. DOI: `10.1016/j.jfineco.2011.11.003`.
2. Marshall, Ben R.; Nguyen, Nhut H.; Visaltanachoti, Nuttawat. “Time-Series Momentum versus Moving Average Trading Rules.” SSRN abstract `2225551`.
3. Rohrbach, Janick; Suremann, Silvan; Osterrieder, Joerg. “Momentum and Trend Following Trading Strategies for Currencies Revisited — Combining Academia and Industry.” SSRN abstract `2949379`.
4. Sullivan, Ryan; Timmermann, Allan; White, Halbert. “Data-Snooping, Technical Trading Rule Performance, and the Bootstrap.” *Journal of Finance* 54(5), 1999. DOI: `10.1111/0022-1082.00163`.
5. LeBaron, Blake. “Technical Trading Rule Profitability and Foreign Exchange Intervention.” *Journal of International Economics* 49(1), 1999. DOI: `10.1016/S0022-1996(98)00061-0`.
6. Han, Chulwoo; Kang, Byeongguk; Ryu, Jehyeon. “Momentum in the Cryptocurrency Market: A Comprehensive Analysis under Realistic Assumptions.” SSRN abstract `4675565`, revised 2026.
7. “FX technical trading rules can be profitable sometimes!” *Research in International Business and Finance*. DOI/link to be normalized in the parent bibliography before promotion beyond this scoped matrix.
8. “Drivers of technical trend-following rules' profitability in world stock markets.” *Research in International Business and Finance*. DOI/link to be normalized in the parent bibliography before promotion beyond this scoped matrix.

## Residual uncertainty and next evidence step

The evidence supports testing trend-following and EMA-derived hypotheses, not claiming a durable EMA 20/50 edge. The next bounded step is to bind each source to the repository bibliography/evidence registry, normalize DOI metadata, and implement a reproducible paper backtest under the contract above in a separate Issue and PR.
