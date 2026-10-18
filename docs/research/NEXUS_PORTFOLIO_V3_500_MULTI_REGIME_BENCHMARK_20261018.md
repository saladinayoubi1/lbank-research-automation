# NEXUS Strategy Finder — no new rotation engine: fixed Bybit Spot portfolio v3 against passive baselines, six previously inspected regimes

**2026-10-18 | Research, not Paper/Live admission.**

## Verified engineering conclusion

NEXUS already has an operational research implementation of three BTC/ETH portfolio families and physically accounts for one shared long-only Spot wallet in `bybit_portfolio_search_v3.exact_backtest`. PR #2720 merged the bounded fixed existing `dual_rotation` test on source-attested original Bybit bars with true **500 USDT** rather than the original 10,000-USDT research baseline. Its historical 2025Q1 cash result was **+8.43707258 USDT** at normal fees, positive at both previously declared stress levels.

One quarter of historical profit is insufficient to establish a robust strategy. This research reproduces **the identical pre-existing candidate, risk weights, fixed schedule and physical cash engine**, with no further parameter search, on a longer set of overlapping and independent-reset intervals and against price/cost-consistent passive BTC, passive ETH, 50/50 BTC/ETH and cash-only alternatives. **No new strategy discovered, no market credentials, no order placements, no owner Demo changes.**

## Original frozen candidate and physical data source

- Reviewed original `dual_rotation` ID **`b4e4a2c33304aec1`**; lookbacks [30,90,180] days, 90-day absolute regime, no MA, nonnegative BTC/ETH winner allocation, 30-day realized volatility estimator, target 0.30, scheduled 7-day reviews, and pre-existing weight quantum 0.25. These were selected **before** the source-bound 2025Q1 diagnostic; this new project did not optimize anything after observing recent results. That does not mean the original historic vocabulary was free from earlier selection bias.
- Source: the **six raw-SHA-verified** original Bybit Spot BTC/ETH 15m, 1h and 4h Parquet files, using original `scripts.nexus_strategy_finder_shared_cash_eval.verify_pinned_market_files` prior to all market loading. `nexus_existing_portfolio_shared500_diagnostic._validate_source` checks strict continuous 4h UTC cadence, exact two-peer column order and physical OHLC bounds.
- Execution: existing physical `build_structural_state`, `realized_vol`, `construct_weights`, global schedule `_candidate_rebalance_mask`, and unchanged `exact_backtest`. Prior closed 4h decision → next open buy/sell, sells first, proportionate buys within remaining Spot cash, explicit costs, no borrowed money. End-of-historical-partition flat liquidation. Original old engine **has no per-position hard stop or guaranteed gap cap**.
- Capital: one BTC/ETH shared **500 USDT** wallet within each evaluated period. Separate half-year intervals are **independently reset** at 500, not an accumulated investment. A **single continuous** Sept-2023 through July-2026 reference account is separately evaluated. The historical 2025Q1 replay is a deliberately **overlapping cross-check** against the earlier #2720 evidence.
- Physical synthetic cost assumptions per side: `conservative` fee10bps+slippage5bps, `stress` fee15bps+slippage10bps, `severe` fee25bps+slippage15bps. They are modeled assumptions, **not authenticated actual order-book spreads/fees**. For exact parity, passive baselines use the original `exact_backtest` too, entered on next open and liquidated at the study's final close with the same fees/slippage.

### Independently restarted half-year/historical windows, conservative cost

| Market interval (UTC, end exclusive) | Existing rotation P/L, USDT | Fills (not round trips) | Rotation max DD | Buy-and-hold BTC P/L | Passive 50/50 P/L |
|---|---:|---:|---:|---:|---:|
| Sep 2023–Mar 2024 | **+230.86441467** | 26 | 14.10% | +668.58805839 | +588.14400961 |
| Mar–Sep 2024 | **−60.31238593** | 27 | 26.96% | −18.83369756 | −73.41164065 |
| Sep 2024–Mar 2025 | **+184.72124778** | 22 | 8.87% | +218.36493535 | +83.23310211 |
| Mar–Oct 2025 | **+158.98838602** | 24 | 12.55% | +166.10035857 | +289.64248754 |
| Oct 2025–Apr 2026 | **−46.45442647** | 7 | 20.15% | −201.88622998 | −223.83641993 |
| Apr–Aug 2026 | **−99.58193912** | 4 | 20.99% | −40.13107715 | −49.32152397 |

All series use the same local trusted historical price data and original 4h next-open Spot accounting. Separate period results **cannot be added** to infer the profitability of a continuous account. **Three positive, three negative** rotations across these six contiguous differently trending eras. The old strategy performed worse than passive BTC in five of these six eras (underperformed in Sep2023, Mar2024, Sep2024, Mar2025 and Apr2026; outperformed in Oct2025–Apr2026). This is not an independently selected untouched future validation set.

### One continuous portfolio account, Sept 1 2023–Aug 1 2026 exclusive

| Fixed reference / cost profile | Net P/L, USDT | Final simulated cash, USDT |
|---|---:|---:|
| **Original rotation**, conservative | **+343.66115005** | 843.66115005 |
| Original rotation, stress | +320.11394615 | 820.11394615 |
| Original rotation, severe | +285.97596337 | 785.97596337 |
| Passive BTC-only, conservative | +702.11337634 | 1,202.11337634 |
| Passive 50/50 BTC–ETH, conservative | +382.01406091 | 882.01406091 |
| Passive ETH-only, conservative | +61.91474547 | 561.91474547 |
| Cash-only | 0 | 500.00 |

Original rotation's maximum mark-to-market simulated drawdown was **34.43365449%**, with **106 separate buy/sell fill events**, original modeled fees **21.59696755 USDT**, and total trading turnover **43.19×** initial 500-USDT cash. This is a serious exposed downside on a 500-USDT account, even though no borrowing occurs. The original portfolio simulator does **not** include per-trade hard stops or exchange risk controls. There is also no per-position journal to claim the average net gain/loss per closed position.

The original portfolio underperformed BTC-only by **358.45222629 USDT** and passive 50/50 by **38.35291086 USDT** in the *same* continuous period under matching cost assumptions. A positive terminal equity line, without this comparison, would have been misleading. The severe stress still has positive terminal P/L but is not evidence of robustness against market gaps/latency or live fills.

### Previous fixed Q1 evidence reproducibility

The Q1-2025 cross-check from the current larger archive study reproduced the earlier fixed evidence exactly at **+8.43707258 USDT** conservative, **+7.90278653** stress and **+7.10143040** severe, and 9 buy/sell fill events. This explicit overlap is a **deterministic reproducibility check**, not an independent second successful backtest.

## Repo evidence and QA

- Additive, opt-in reproducible runner: `scripts/nexus_existing_portfolio_fixed_multiregime.py`. CLI `--archive-root` and `--output`, one frozen original candidate/old engine, all six raw SHA checked, no optimizer called.
- Source result: `docs/evidence/portfolio-v3-original-500-calibration-20261018/fixed-dual-rotation-2023-2026-six-regimes-vs-passive.json`. Eight scopes × five predeclared strategies × three fixed physical cost profiles, original-source hashes, exact frozen config and source receipts, P/L/turnover/fill/cash/drawdown values. **Canonical digest:** `63afc60f7e35fbe456a4a43b3dc061e6b253d33d46e60b0fa95725ca29050077`.
- On isolated Laptop2 the original frozen script and the repo-portable CLI both returned **the same original result digest** on the same six SHA-checked sources and original engine, exit 0, including all six half-year periods and the Q1 cross-check. The original raw local evidence SHA was `c921c816d2696b1cb5dcc040faf9a0e9e5844ae21aa7796661b180d2f5c93d71`; checked-in GitHub representation retains exact data/digest, line endings may be normalized by file transport.
- `tests/test_nexus_existing_portfolio_fixed_multiregime.py`: **10/10 independent isolated QA tests pass** on the repo-checked-in evidence, original 500-USDT model contract, six source hashes and six-era P/L/cash invariants; tests check that the candidate/period is not selected after seeing results, that 2025Q1 equals prior exact fixed evidence, source verification precedes market load, no order adapter and no Demo/Live promotion. Original `bybit_portfolio_search_v3.py`, its search cursor and the installed Windows owner apps have not been modified.

## Decision

**`DO_NOT_PROMOTE__POSITIVE_HISTORICAL_RETURN_BUT_NONROBUST_BENCHMARK_AND_UNBOUNDED_STOP_RISK`**.

This fixed old portfolio strategy is better evidence of a real multi-asset engine than unexecuted descriptions or a new redundant rotation implementation. Nevertheless, **three of six time regimes were losing, there is no per-position protective stop, maximum three-year simulated drawdown exceeds 34%, and the strategy lagged passive BTC and even 50/50 on the same period**. Its source is also historical/preinspected, with no immutable untouched prospective Bybit sample since the data snapshot through July 2026. These gaps block any promotion to even paper-demo on the owner's reference account. Live trading stays off.

The concrete next engineering objective is **additive, independently validated per-fill journal and causal risk-state enforcement for the existing original engine**, with a strictly opt-in research-only policy that leaves old historical results unchanged until an explicit, separately reviewed contract is approved. A new sim, an invented strategy name or threshold retuning on already-visible Q1/2023–2026 returns is not an acceptable substitute.
