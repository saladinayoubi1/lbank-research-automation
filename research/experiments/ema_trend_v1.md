# EMA Trend-Following Experiment v1

Status: research/backtest/paper-only. This document does not authorize live trading.

## Evidence binding

This experiment is bound to `research/evidence/ema_crossover_evidence_matrix.md`. Generic trend and time-series-momentum evidence motivates testing; it does not establish that EMA 20/50 is profitable or optimal.

## Primary hypothesis

For a fixed market series, a long/flat EMA(20,50) crossover rule, computed only from completed bars and executed at the next bar open, has positive out-of-sample net risk-adjusted performance and exceeds its predefined benchmark after explicit costs.

Primary null / kill condition: the median out-of-sample Sharpe is non-positive, or the strategy fails to exceed the predefined benchmark net of costs. Historical in-sample performance cannot override this condition.

## Deterministic rule

1. Input is a chronologically sorted OHLC series with unique timestamps.
2. Compute `EMA_fast = EWM(close, span=20, adjust=False, min_periods=20)`.
3. Compute `EMA_slow = EWM(close, span=50, adjust=False, min_periods=50)`.
4. Target exposure is 1.0 only when both EMAs are defined and `EMA_fast > EMA_slow`; otherwise target exposure is 0.0.
5. A target produced on bar `t` is eligible for execution no earlier than bar `t+1` open. The repository `backtest_engine.run_target_exposure_backtest` owns this execution lag.
6. No shorting, leverage, pyramiding, future-data regime labels, or discretionary overrides are allowed in v1.

## Data and semantic requirements

Required columns: `timestamp`, `open`, `high`, `low`, `close`. Timestamps must be UTC-normalizable, unique and ascending. Prices must be positive and OHLC-consistent. Venue, symbol convention, timeframe, missing bars, delistings/contract changes, and survivorship treatment must be recorded by the dataset manifest used in an actual run.

## Execution assumptions

The experiment must report `fee_bps` and `slippage_bps` explicitly and must run at least a zero-cost diagnostic plus realistic base and stressed cost cases. Spot tests must not include funding or liquidation. Derivatives tests are out of scope for v1 unless funding, leverage, maintenance margin and liquidation semantics are modeled explicitly in a separate version.

Cost stress grid for an eligible run: base estimate, 1.5x base, and 2.0x base. A zero-cost run is diagnostic only and cannot establish eligibility.

## Validation design

Use chronological train/validation/test or rolling/anchored walk-forward splits. Random shuffling is prohibited. The primary EMA(20,50) result must be reported before any alternative parameter results. Secondary pairs such as 10/50 or 50/200 form a multiple-testing family and cannot replace a failed primary test.

Minimum robustness checks: multiple symbols, at least two timeframes where data quality permits, cost stress, one-bar extra execution delay, start-date perturbation, and EMA-length perturbation around the primary pair. Report failure regions and window-level dispersion, not only aggregate performance.

## OOS activity eligibility

A strategy may show attractive return statistics while producing too few independent out-of-sample decisions to support a useful Phase 3 research conclusion. Therefore every OOS or walk-forward evaluation window must also pass the repository strategy-activity eligibility gate before the candidate can be considered eligible for paper-forward promotion.

The activity check must use the exact timezone-aware half-open OOS interval `[window_start, window_end)` and the actual entry timestamps produced inside that interval. Duplicate timestamps, equivalent instants represented with different UTC offsets, naive timestamps, or entries outside the declared OOS window are invalid evidence and must fail closed. Evaluation duration and calendar-month coverage must be derived from the OOS window itself rather than supplied as caller-controlled denominators.

The experiment report must preserve both outcomes independently:
- statistical/performance result for the strategy;
- activity-eligibility result and reason codes.

A profitable but activity-ineligible EMA candidate remains research evidence only and cannot be promoted by relaxing the activity policy after observing results. Conversely, high activity cannot rescue a strategy that fails the primary performance/null or robustness criteria.

## Benchmarks and uncertainty

Compare against cash and, where economically meaningful, buy-and-hold. Also compare against a simple return-sign/time-series-momentum baseline when implemented. Report net return/CAGR, Sharpe or Sortino with stated annualization, maximum drawdown, Calmar, turnover, exposure, hit rate, tail loss, number of trades/fills, and walk-forward window distribution.

Any search over symbols, timeframes, filters or parameter pairs must disclose the tested family. Multiple-testing control or a genuinely untouched holdout is required before claiming evidence beyond exploratory status.

## Invalidation and paper-forward gate

The strategy is invalidated for promotion if results depend on look-ahead, unsorted/duplicate timestamps, impossible fills, hidden zero-cost assumptions, one narrow regime/symbol/timeframe, or parameter selection that does not survive held-out evaluation. It is also invalidated if realistic cost stress removes the effect or if materially small data changes reverse the conclusion.

Paper-forward eligibility additionally requires that the relevant OOS/walk-forward windows pass the strategy-activity gate under its predeclared policy. Sparse activity may be reported as an empirical result, but it cannot be reclassified as sufficient after the fact solely because returns look favorable.

Passing historical verification permits only a separate paper-forward evaluation. Live trading, production deployment and personal financial recommendations remain outside authority.
