# UTC-slot volume v7 — frozen exploratory hypothesis

Status: implemented and locally tested; no native producer, market backtest, independent QA, profitability or Demo qualification is claimed.

## Mechanism

Candidate: `factory_utc_slot_volume_breakout`. One fixed configuration, risk variant 0, existing closed-4h/1h/15m next-open execution model. No parameter search, risk sweep or validation/test selection.

At decision bar i, the event is the prior closed bar j=i-1. Its baseline consists of volume at j-96*k for k=1..7, the exact same UTC 15-minute slot on each previous day. The event is excluded from its baseline.

- Seasonal ratio: V[j] / mean(V[j-96], ..., V[j-672]).
- Seasonal dispersion: population standard deviation of those seven observations / their mean.
- Context: completed h4_up=1 and h1_vol_ok=1; lagged seasonal ratio >=1.5 and dispersion <=0.75.
- Separate current closed-bar confirmation: close > prior_hi, close > open, close_location >=0.65.
- Existing risk, fill timing, daily pause, drawdown halt, stop ordering and fees/slippage remain unchanged.

Seven-day history and a positive baseline are feature availability requirements, not a minimum trade-count gate. NaN history or zero baseline cannot emit a signal. Timestamp data must be aware, aligned and contiguous on the UTC 15m grid; local timezone and DST representations are converted to UTC before matching daily slots.

## Material distinction and prior work

The old relative-volume statistic uses a contiguous 20-bar baseline. The new primitive uses seven nonadjacent, exact daily clock matches over one week and their dispersion. This is not a renamed jump threshold or a parameter change to the v6 shock proxy. A regression counterexample changes one seven-day-old clock observation while preserving the current 20-bar relative-volume value; the new statistic changes.

The terminal v6 ledger binds 23 evaluated mechanisms and 107 screened mechanisms (overlapping sets). Its digest is `18675234ad8c981be8f8c5e348c1a39737a9c3fc4ca09ba0ae9532c8a59b567a`. The ledger is not reset or mutated by this preparation. Routing it through the appended factory produces only the new candidate. All 91 prior factory specs, all 118 prior mechanism IDs/order and prior frontier configs remain exact.

Frozen assumptions are deliberately simple and unoptimized. One-week clock normalization may be unstable or irrelevant to returns; candle volume is not authenticated order flow, order-book depth or executable liquidity. The hypothesis can fail after costs.

## Literature boundary

Hansen, Kim and Kimbrough, [Periodicity in Cryptocurrency Volatility and Liquidity](https://arxiv.org/abs/2109.12142), arXiv:2109.12142v2, study periodic volume and volatility on other venues. Those observations motivate normalizing activity by time of day. They do not validate this Bybit Spot candidate, the seven-day lookback, fixed thresholds or positive net returns. This proposal is an inference, not a replication of a directional trading result or a futures funding strategy.

## Frozen study and execution boundary

Use only the existing independently checksum-verified Bybit Spot BTC/ETH 15m/1h/4h archive, digest `2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422`. Its historical partitions have already been inspected. Further archived execution is exploratory and cannot provide a pristine holdout.

Reuse the terminal v6 ledger as `--previous-ledger`; do not replay v5/v6 producers or completed accounting/comparison units. Training alone screens the one new candidate at conservative and stress costs, followed by the existing selected 12-row diagnostic grid. Do not revise parameters after any training/validation/test result is observed. Freeze-file metadata binds the new topology/config and local source bytes before market-data execution.

Conservative fee/slippage: 10/5 bps per leg; stress: 25/15. Simulated initial capital remains 10000 USDT per cell, separate from owner 500 USDT. Report actual date windows, closed trade count, aggregate net PNL, mean trade result, drawdown and costs. No monthly-return inference from whole-partition metrics.

Laptop2 remains the research primary. At preparation both RDC devices were Offline; no native workload, failover, task, runner restart or infrastructure change was performed. Native tests, one bounded producer run and independent distinct-host numeric/Decimal/leakage evidence are subsequent gates. Before any later qualification, independently authenticated unseen prospective data is required.

## Verification

Local scratch tests with NumPy 2.3.5 / Pandas 2.2.3 passed 25 tests: 13 new clock-volume/contract/integration cases and 12 prior jump/Research cases. Cases cover a time-indexed scalar oracle, no-current/future dependence, exact event lag/baseline exclusion, units, UTC/DST equivalence, warmup/zero baseline, malformed grid and volume, reviewed grammar/authority denial, prior-generation preservation, terminal-ledger routing and actual build_features integration.

The existing jump regression originally asserted the v6 configs remained the final two configs. With v7 appended, it now selects the v6 configs by their immutable mechanism IDs and verifies their exact content/order. The first failed local result is retained; after this test update the combined suite passed. This is not native Windows or independent QA evidence.

Research-only; Demo admission=false; automatic Demo=false; Live=false; official Coordinator advancement=false. No owner profile, install, journal, registry or Paper writer change.
