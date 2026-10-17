# NEXUS Strategy Finder — 500 USDT shared BTC/ETH physical accounting gate

Date: 2026-10-18. Scope: research infrastructure correction, **not a newly profitable trading strategy**.

## Reproduced architecture discrepancy

The existing autonomous composite generator in `nexus_composite_strategy_research.py` creates and screens reviewed declarative mechanisms, but its research `backtest` starts with `SIM_CASH=10_000` **independently on every symbol**, separately on train/validation/already-inspected historical test and separately for conservative/stress. A green workflow means research completed, not a new executable or profitable edge. Strategy Finder's reviewed frontier can be **terminal** when exact candidate fingerprints are exhausted. It is incorrect to interpret those isolated 10k BTC and ETH portfolio simulations as evidence that a **single shared 500 USDT BTC/ETH spot wallet** can execute the same positions.

Recent isolated Elliott investigations V118 and V119 have also been measured negative on physically replayed market history, reinforcing why selection without shared-collateral economics is misleading. V119: 77 costed hypothetical Bybit Spot trades across three independent historical partitions, net negative across all. V118: four original physically stopped historical Binance trades. Neither is a Demo qualification or a newly implementable Strategy Finder signal.

## Change — one reusable physical **sidecar**, not a new signal/fake rotation

New files:

- `research/strategy_finder_shared_cash_physical.py`: pure, 15-minute BTCUSDT/ETHUSDT **single-wallet** simulator for already computed strictly boolean reviewed strategy signals and physical OHLC+ATR.
- `scripts/nexus_strategy_finder_shared_cash_eval.py`: manual opt-in research CLI mapping the **existing** Strategy Finder reviewed grammar and exact config fingerprint into the original pinned and authenticated multi-timeframe Bybit archive adapter, deriving signals without user-supplied scripts and passing only those signals into the new shared-wallet engine.
- `tests/test_nexus_strategy_finder_shared_cash_physical.py`, `tests/test_nexus_strategy_finder_shared_cash_eval_adapter.py`: 28 separate tests.

**Boundaries:** no modifications to `nexus_composite_strategy_research.py`, running scheduler, existing historical evidence/ledger cursor, Agent Manager, order adapter, V52/Elliott preregistered rules, actual owner Laptop1 Demo, risk profile, account keys or Live state. Both components return `paper_eligible=false`, `qualified=false`, `live_enabled=false`, `orders=0` even if simulated test data makes money.

### Physically causal book/QA properties

- Two exact source identities, shared UTC-completed 15m decision timestamps, continuous/no-duplicate physical OHLC and peer grid; nonfinite price or impossible candle rejected.
- Existing Strategy Finder can compute multitimeframe context from source-complete 1h/4h bars and aligned peer Spot observations; its pinned archive loader authenticates original inputs; this new pure evaluator itself **does not authenticate source market origin**. CLI binds research-source archive SHA and reviewed original `config_fingerprint` before fetching source.
- Every qualifying signal from closed bar `j` can fill only at the physical *OPEN* of bar `j+1`, whose timestamp equals the signal's `decision_at[j]`; this distinction is independently tested. **No pivot-center fill** or current-bar future-high exploit.
- Initial 500 USDT research cash, max 250 gross exposure, at most one long position across BTC and ETH; no borrow, leverage, spot short or hedge. 2.5 USDT **nominal gapless** stop-loss capacity including entry/exit fees/slippage; worse gap-loss may exceed this and is not guaranteed away. Quantity rounded down to 1e-8 *for simulation only*, not asserted as real Bybit lot step.
- Frozen **1.5 ATR stop, 2.0R target, 64 bars hold**, normal assumed `10bps fee + 5bps adverse slippage` and stress `25bps + 15bps`, each per side. No after-result tuning. Same-bar dual-high/low is stop-first. Gap-through-stop uses the **worse open**, never idealized stop. Timeout exits at physical open; partition-end position exits at last fully completed close with explicit exit code. No extra next-partition market data borrowed.
- Deterministic same-time BTC-first tie resolution and counted peer denial. Already open BTC blocks new ETH intent until that position is disposed; cash stays encumbered. Every explicit denial reason and historical signal-at-next-open count are retained.
- P&L, trade count, risk, fees, time, realized exit reasons, positive trades, max drawdown, monthly trade count and mean/net P&L per each 60/20/20 partition and both profiles. Each partition starts from an independently reset **same-size** 500 USDT book. Monthly totals are checked against physical ledger and equity/account conservation.
- All already-inspected historical train/validation/test rows remain **diagnostic**, not pristine, regardless of hypothetical positive P/L. Unknown prior ATR is denied at entry rather than receiving a fictional fill.

### Current verified result and limit

- **28/28 native tests PASS on isolated Laptop2** using new PR modules and independently fetched current GitHub `main` Strategy Finder dependencies, after catching and correcting one typed-missing-ATR fixture incompatibility.
- These are ***synthetic acceptance tests*** of the new cross-asset research execution model and its original reviewed-contract adapter, NOT an observed profitability evaluation for a new strategy. No new real-market replay, no candidate qualification and no approval of a live/Demo order resulted.
- Laptop2 has approximately **3.89 GB total RAM, ~1.1 GB free** at the guarded source audit; do not force a full multiyear two-symbol feature build there without separate resource limits or streaming implementation. A full genuine candidate research replay is a distinct verified next step, not something we claim occurred during these tests.
- A manual CLI `--mechanism`, `--exact-fingerprint`, `--source-archive-sha256`, `--archive-root`, `--output` is deliberately explicit. It accepts only a known reviewed Strategy Finder mechanism under an exact dataset-bound fingerprint and **frozen risk_variant=0** (1.5ATR/2R); a legacy risk_variant=1 contract is refused rather than silently evaluated with different stops/targets. It writes its output once. It does **not** restart exhausted workflow frontiers or create a new tradeable mechanism automatically.

### Research acceptance / rollout

This is a prerequisite diagnostic to ensure future candidate decisions are evaluated against the intended shared-capital reference. It **must not be presented as the autonomous Strategy Finder recovery being solved**: generation of distinct independently reviewed hypotheses, quantitative market edge, fresh pristine holdout and Demo risk safeguards remain separate unsatisfied gates.

Safe next connection point: after a genuinely new original contract is reviewed, explicitly run this CLI against independently verified source on an adequately resourced isolated research executor; compare shared 500-USDT cost-adjusted equity, monthly trades, splits, drawdown and stress to the old independent 10k/cell report; label the entire historical test as already inspected, and require a *future untouched* holdout before any strategy qualification. **Live remains disabled permanently.**
