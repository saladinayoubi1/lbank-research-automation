# NEXUS — existing portfolio rotation engine, original Bybit source and real 500-USDT fixed economic diagnostic (2026-10-18)

## Direct finding

**Do not build another BTC/ETH shared-capital rotation engine.** NEXUS already contains `bybit_portfolio_search_v3.py`, a substantial three-family portfolio research system:

1. `dual_rotation`: multiple lagged horizons scored across BTC and ETH, optional absolute momentum and EMA regime checks, winner or inverse-volatility allocation.
2. `trend_risk_parity`: multi-horizon causal directional voting, volatility weighting, risk overlay.
3. `relative_breakout`: prior daily-window price breakout/breakdown state and risk-allocated BTC/ETH weights.

The original `construct_weights` uses shared nonnegative weights summing to at most one. The canonical `exact_backtest` sells first, prorates new buys against **one common cash book including costs**, fills only at the **next 4-hour open after the previous closed decision**, uses a global scheduled rebalance mask, and liquidates at the end of the fixed experiment interval. These capabilities existed in the repo before this analysis and must be reused, not rebuilt as an alleged new portfolio Strategy Finder family.

**Two material discrepancies explain why this prior engine cannot simply replace a verified Demo system**:

- The old production **research manifest** `experiments/bybit_portfolio_search_v3.json` defaults to `initial_cash=10000` USDT for both normal/stress modes. The intended NEXUS paper reference is **500** USDT; old 10k P/L is not 500-paper proof. An old test `tests/test_bybit_portfolio_independent_accounting.py` does exercise **500** synthetic cash oracles but does *not* establish a 500-USDT real-source archived economic study.
- The original `load_market` verifies column/schema/symbols and matching timestamps but **does not physically pin raw source hashes**, and the old manifest's semantic archive claim `5f1173467c2296201940c3b7786b7cc3e5442244e07289769ab4867ace41d668` **DIFFERS** from the newer canonical Bybit research archive semantic identity `2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422`. This audit does not silently reconcile the two or claim historical old-v3 reports had today's locked source. Instead it verifies all six real raw-file SHA256 checks **before** passing actual original BTC/ETH 4h source into the unchanged legacy engine, then additionally checks 4h UTC cadence and physically valid OHLC.

## Exactly frozen old candidate and cost protocol

The one *pre-existing* `dual_rotation` candidate was frozen **before** running the evidence test, with all values members of the old archived original experiment search vocabulary:

- Existing original engine candidate ID `b4e4a2c33304aec1`; not a new ID family. Original `lookbacks=[30,90,180]` days, `absolute_days=90`, `ma_filter_days=0`, `minimum_absolute_return=0`, `allocation=winner`, `vol_days=30`, `target_vol=0.30`, `rebalance_days=7`, `quantum=0.25`. No optimizer, no rank-after-view, no parameter sweep. No minimum-trade-count qualification threshold.
- Shared initial Spot cash **500 USDT**, one BTC+ETH wallet across each physical 4-hour study. Conservative `10bps fee + 5bps slippage` per side; old-v3 `stress = 15bps fee + 10bps slippage` per side; independently declared `severe = 25bps fee + 15bps slippage` per side.
- Originally archived **2025-01-01 00:00 through 2025-04-01 00:00 UTC** source window on the six exact-original SHA-attested Parquet BTC/ETH minute15/hour1/hour4 market files. Original 4h source begins well before 2023 to support causal 180-day/multi-timeframe lookbacks. Historical source has already been inspected; *this is NOT fresh OOS/independent future validation*.
- Each monthly row **resets** a separate 500-USDT wallet, while the whole 2025Q1 row is **one continuous 500-USDT wallet**. Monthly P/L values must **NOT be arithmetically added** to claim the continuous outcome. All figures are actual old-v3 Spot cash execution-cost simulations, not live fills. Closed round-trip position counts, average profit per closed position and original exchange depth are **not available** from old-v3 aggregate logs; fills represent execution events (buys/sells), not round trips.
- Original code does not impose a physical ATR hard stop. Equity gap/drawdown risk cannot be treated as bounded by the 2.5-USDT risk envelope from the **separate** 15m sidecar. This is why even a positive 500-USDT historical Q1 result is only a diagnostic.

## First authenticated fixed Q1 result

| Historical source interval | Conservative P/L USDT | Old stress P/L USDT | Severe P/L USDT | Conservative buy/sell fill events |
|---|---:|---:|---:|---:|
| Jan 2025, own 500 restart | **+21.95447081** | +21.41930095 | +20.61658671 | 7 |
| Feb 2025, own 500 restart | **−13.38485559** | −13.88278306 | −14.62874674 | 4 |
| Mar 2025, own 500 restart | **0.00000000** | 0.00000000 | 0.00000000 | 0 |
| **Entire Q1, uninterrupted 500** | **+8.43707258** | **+7.90278653** | **+7.10143040** | **9** |

Normal quarterly historical mark-to-liquidated close equivalent `+1.687414516%` on its starting 500 USDT, *not* a forecast return. Cost-stress kept sign positive for this one reviewed window. Do not overstate this as alpha: one preinspected interval, sparse execution, old configuration, no explicitly priced gap stop, no genuinely untouched future holdout and no independent prospective QA of forward fills. Any conclusion that this NEXUS strategy is a permanently profitable trading system would be unjustified.

## New additive research-only materials

- `research/portfolio_existing_engine_shared500_calibration_v1.json`: frozen original v3 dual-rotation candidate, source mismatch flag, exact UTC window, 500 cash and conservative/stress/severe fee/slippage profiles. The source values were fixed **before** running market data; edits to the candidate, cost profiles, source claim, Live/Paper authority or historical interval fail closed.
- `scripts/nexus_existing_portfolio_shared500_diagnostic.py`: an explicitly *opt-in* read-only wrapper; first validates the original six raw SHA pins from #2716, original 4h UTC same-grid OHLC invariants, frozen original-v3 config and old manifest membership. It then calls original `bybit_portfolio_search_v3.build_structural_state`, `realized_vol`, `construct_weights`, `_candidate_rebalance_mask` and `exact_backtest` **without any rewritten execution model or backtested parameter search**. Write-once, digest-bearing factual output, no trading keys, no strategy qualification or runtime subscriptions.
- `docs/evidence/portfolio-v3-original-500-calibration-20261018/fixed-dual-rotation-2025q1-original.json`: entire actual original-source Q1 plus monthly-reset conservative/stress/severe diagnostics, per-asset fills, total fees, cash floor, realized returns, drawdown, turnover, original engine source SHA and immutable six original market-file SHA values. **Canonical result digest** `67c3817359fb4b9a225cc89c6abcd5a405b5602c4e3f20d822056fa1515ad746`; local native output and exact GitHub uploaded raw JSON file SHA256 `d8ad8e7424c0d0bc48e3333a6d6d257a121aa06267df054eb35fc32c16c5826e` (exact byte-identical independently verified on Laptop2).
- `tests/test_nexus_existing_portfolio_shared500_diagnostic.py`: **15/15 native isolated Laptop2 QA PASS**. Covers attempted mutation of source, capital, Live authority, cost assumptions, selected candidate or study period; guard before any physical market read; UTC-grid/OHLC corruption rejection; exact receipt digest and six source pins; quarter/monthly book separation and financial conservation; and no order, optimizer or model rewrite. Hosted GitHub multi-platform tests are separate mandatory gates.

## Actual Strategy Finder diagnosis and next decision

The existing portfolio code is more sophisticated than adding another Elliott/Butterfly conditional entry or a duplicate `BTC_vs_ETH_winner` implementation. But its original stand-alone 10k manifest, source identity gap and missing integration into the current exact reviewed Strategy Finder policy are material reasons it cannot be treated as already eligible for NEXUS Demo.

**No mechanism in this PR is approved for Paper or Demo.** No automatic strategy promotion, no personal live-account authority, `Live=false` unchanged. Existing installed Laptop1 and Laptop2 apps/keys/journals and the protected V117 future study remain untouched. A fully integrated trading system would additionally require an independently registered causal portfolio hypothesis versus this already existent v3, an exact source/500-sized consistent risk and account model, hard loss/gap/cash constraints if they become part of its contract, rigorous costed rolling validation, and a genuinely unseen prospective data interval. The Q1 positive is only historical calibration, not a reason to start trading or tune more variants on the same data.
