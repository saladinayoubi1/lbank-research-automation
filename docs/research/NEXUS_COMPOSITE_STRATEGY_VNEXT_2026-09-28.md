# NEXUS composite strategy research vNext — audited first milestone

**Status:** design / source audit only. **Not implemented, backtested or Demo-approved.**
**Owner decision:** the July 36 basic-family tests and 120 parameter variants are
benchmark/ablation evidence only. They are **not** ten distinct deployable strategies.
Track implementation, independent validation and owner table in #1985.

## What exists at source SHA d60c063a

| Surface | Verified in source | Missing boundary |
|---|---|---|
| `config/nexus-demo-strategy-matrix-v2.json` | Four canonical Bybit pairs, 15m/1h/4h, momentum/breakout/reversion, Paper-only flags | Only three basic generators; not 10 complete strategies |
| `nexus_monthly_ten_variant_pre_demo.py` | Three momentum + three breakout + four reversion *parameter variants*, 120 research-only July trials | No unique new entry/exit mechanisms; no new forward qualification |
| `bybit_regime_search_v6.structural_signal` | Multi-lookback return votes, EMA filter, broad bullish/bearish/transition regimes | Composite of existing indicators, may output **negative/short** exposures; cannot send those to long-only Spot Paper |
| `bybit_strategy_search_v2` | EMA, time-series momentum, breakout and hysteresis candidates; realized-volatility-based exposure sizing | Need independently verified novel structures, own datasets, causal bridge to Product Research |
| `nexus_regime_strategy_selector.select_strategy_mix` | Source-bound regime proposal, cash-preserve conditions on low confidence/thin liquidity, degraded-health haircut | Allocation proposals depend on the same three allowed families; selector does not create a new edge |
| `phase5_strategy_factory.ALLOWED_FAMILIES` | Immutable preregistration and kill gates for exactly the three approved families | Extend via a separate explicit schema/migration; do not silently reinterpret previous experiments |
| `deterministic_risk.evaluate_risk` | Deterministic downstream authority boundary | Preserve final deny authority for every new research->Paper handoff |
| `nexus_strategy_discovery_rotation` / #1811 | Bounded rotation, prior independent Paper gate and explicit quarantined failure | A workflow's success cannot establish an eligible strategy; old failed candidate stays quarantined |

Do not mutate any of the above legacy results or lower historical qualification gates
to make a new proposal seem more successful.

## Capabilities must be proved BEFORE each experiment

| Feature / data | Current provenance boundary | Allowed candidate use |
|---|---|---|
| Complete July 2026 Bybit Spot OHLCV, 4 pairs x 15m/1h/4h | 12 official May-July archives, July full-month tables and source/dataset digest | Baseline or exploratory features. Repeatedly inspected July holdout is **not a fresh test** for newly designed candidates. |
| 4h/1h structural bias and realized volatility | Calculate from validated CLOSED historical bars with `available_at = open_time + interval` | Causal multi-timeframe regime and exit filters; all as-of joins must use `available_at <= 15m_decision_time` |
| Relative volume, historical price-level structure, cross-pair returns/correlation | Derive from provenance-verified historical Spot OHLCV only | Cross-asset rotation and true observed-volume proxies, not order-book “liquidity” |
| Raw Spot trade-time, trade-price, trade-size and buy/sell side | `bybit_spot_backfill.validate_trade_range` validates Buy/Sell and `trades_to_range_candles` aggregates them; current exported OHLCV **loses** intra-bar order flow | Only after a new time-ordered side-aware feature export is built BEFORE source cleanup, verified for each archive and its as-of timing |
| Historic best bid/ask, full L2 depth, queue position, executable spread | Not established by current official trade archives or existing July reports | **UNAVAILABLE** for order-book strategies. Must not synthesize from candle wick or turnover |
| Bybit perpetual funding, OI, index/mark/basis | Separate **derivatives** products and historical sources; not contained in Spot OHLCV | **BLOCKED** until independently acquired, time-aligned, source-bound and product/category-verified; advisory inputs do not authorize a two-leg derivatives trade |

Source links for separate official derivatives market products:
https://bybit-exchange.github.io/docs/v5/market/history-fund-rate
and https://bybit-exchange.github.io/docs/v5/market/open-interest .
Do not label unavailable historic market depth as an actual feature.

## First complete candidate protocol: closed-bar structural-pullback/volatility context

This is a **proposed falsifiable hypothesis, not known profitable code**. Pilot one
source-bound BTC/ETH/SOL/XRP Spot long/flat family; keep all new candidates
`research_only=true`, `automatic_strategy_promotion=false`, `live_trading_authority=false`.

1. **Causal context:** From *fully completed* 4h candles only, identify a predeclared
higher-high/higher-low or lower-structure state and its invalidation level. Independently
estimate recent realized volatility and normal/thin observed trading-volume regime on
completed 1h data. All derived features include closed/available UTC time.
2. **Tradeable setup:** Allow a 15m decision only in a verified 4h directional
state with 1h volatility inside predeclared risk band; price must pull back into
a previously established structural zone and reclaim it after a completed 15m bar,
with observed relative-volume confirmation. Unknown/mixed/thin state = **cash**.
Do not enter on indicator crossings alone, form a zone retrospectively, or use
a candle's own close before it occurred.
3. **Execution and exits:** Enter at earliest eligible NEXT tradable open,
apply bounded fee + adverse slippage, conservative spread/latency **stress
assumptions explicitly marked modeled**, hard structure/volatility stop,
minimum risk/reward criterion frozen before selection, time exit and regime-flip
exit. Never assume stopped positions exit at an untraded intrabar price.
Long/flat Spot only. Position size is bounded by verified volatility, actual
simulated available capital, correlated open positions and final deterministic
risk deny. No martingale or automatic leverage.
4. **Controls and falsification:** Compare against unchanged momentum,
breakout, mean-reversion and buy/hold under EXACT same data and fills; also
ablate 4h context, 1h volatility and 15m volume checks one at a time. A
candidate is scientifically interesting only if positive results are incremental
and robust in genuinely later untouched data rather than July-tuned rules.
5. **Independent validation:** Preregister features, windows and parameters
from training-only data; use purged chronological walk-forward, multiple-testing
report and an entirely new later date interval that was not inspected when
designing the candidate. For each eligible cell show net/stress return,
closed round-trip trades (NOT fills), win rate, profit factor, max drawdown,
exposure, turnover, cost sensitivity, source/data digests, drift, kill reasons
and bars/calendar days. Never manufacture missing metrics or claim a July
split already explored is a new untouched holdout.
6. **Runtime handoff:** No new Demo position until the actual user-facing
cross-pair/cross-timeframe table is delivered and reviewed; require independent
source-exact runtime qualification and separate genuinely prospective Paper
observation, including minimum five genuinely **closed** Paper trades and
deterministic risk/drift gates. Preserve existing owner 500-USDT Paper journal.
**Never** enable Live/L4 or execute derivatives.

## Research backlog by genuine mechanism — not parameter sweep

First candidate above; then separately falsifiable and source-capability-gated:
volatility compression+structural expansion; real-trade-VWAP range reclaim;
cross-pair relative-strength rotation with correlation cap; structure-filtered
volatility breakout; authenticated signed-taker-flow response; market-range
failure/reversal; and independently verified regime-conditional signal ensemble.
Derivatives OI/funding divergence and basis/rate mechanisms require separate
verified data and separate product semantics, and are **not** eligible to be
represented as completed spot strategies until those dependencies pass.

## Required next implementation PR (not accomplished by this specification)

- Build a separate **feature provenance/as-of-time schema** and 4h/1h/15m
multi-timeframe feature generator with regression tests: timezone differences,
closed-bar lag, missing data, gap/duplicate/corrupt bars, forward leakage,
cross-pair misalignment, and no-trade on missing required inputs.
- Build the complete first candidate/ablation suite on new research-only
source/dataset contracts without silently widening old `phase5` ALLOWED_FAMILIES
or modifying owner Paper authority.
- Validate deterministic historical fills plus strict reason-coded
out-of-period reports and publish complete table **before** seeking any
separate permission or independent gating for a new Demo lane.

Existing base results and all 120 variants must remain available in the
owner's historical reporting as honestly labeled BASELINES.
