# NEXUS Strategy Finder — first proposal's complete executable-frontier behavioral overlap (2026-10-18)

## Research decision

**Do not add an independent-review permit and do not initiate an economic replay or Demo for `factory_prior_day_sweep_peer_resilience` yet.** Its exact *closed-bar trading intent* is demonstrably not identical to the legacy `failed_range_break_reversal` signal, but the broader original Strategy Finder factory/frontend covers **10 of its 15 observed Q1-2025 signals** on identical BTC/ETH 15m candles. Only **5 of 15** did not overlap with **any** of the 114 pre-existing executable mechanisms. This is neither proof that the five events have a profitable edge nor proof that the condition topology is globally original. **A different ID, narrative or threshold does not qualify as a distinct economically useful strategy.** The permit registry remains empty.

## Exact source and experiment boundary

1. NEXUS GitHub `main` after merged PR #2717 / commit `5afad5d908cb97d163def8ff8b3b1d38fa6e00e8`. Original candidate DSL `research/intake_candidates/factory_prior_day_sweep_peer_resilience_v1.json`, raw SHA256 `ad20bb4b3d18da4b601793c6bdccdf42623187803df7389ffb2b6da3e75be92d`. **No change** to the candidate, preset physical cost model, source archive, previous research ledger or approval permit.
2. Original source: six exact byte-verified cached Bybit Spot BTC/ETH `minute15`, `hour1`, `hour4` Parquet files, as attested by existing `verify_pinned_market_files`. These hashes bind the observed local representations; the original archive's independent upstream provenance remains a separate issue and is not recertified here.
3. Warmup: Dec 1–31 2024 UTC. Observed **already-inspected** source window: Jan 1–Mar 31, 2025 UTC, **8,640 completed 15-minute decision bars per symbol** (17,280 paired symbol-decision slots). This is **not** untouched prospective or independent future out-of-sample evidence, and no model fitting or thresholds were changed based on it.
4. Signal-only replay: original `nexus_composite_strategy_research.build_features` with 15m/1h/4h completed as-of, exact synchronized 15m peer history, and the original `factory_signal` interpreter for the frozen candidate. For every original `ALL_MECHANISMS` candidate, the existing exact `signal_for` was invoked with its unchanged fixed original `risk_variant=0` reviewed/factory config and compared on the **same candle UTC-close**. The original 114 mechanisms comprise legacy, fixed frontier and declarative generated factory. This is **not a 500-USDT economic P/L backtest** and does not imply any trades were placed.
5. The separate initial comparison with six nearest mechanism families and gate funnel is included alongside the full 114-fingerprint comparison; no benchmark family was chosen based on outcomes from a new profit study.

## Observed original-source facts

| Metric | BTCUSDT | ETHUSDT | Combined |
|---|---:|---:|---:|
| Closed 15m source decisions | 8,640 | 8,640 | 17,280 |
| New candidate signal decisions | 7 | 8 | **15** |
| Covered on exact bar by one or more of 114 pre-existing executables | 3 | 7 | **10** |
| Not covered on exact bar by any old executable | 4 | 1 | **5** |
| Same-bar match with legacy `failed_range_break_reversal` | 0 | 2 | **2** |
| Existing original executable mechanism types compared | 114 | 114 | 114 distinct types |

Candidate observed month distribution: BTC Jan/Feb/Mar = **1 / 3 / 3**, ETH = **6 / 1 / 1**. The exact six-neighbor audit recorded BTC **7** and ETH **8** candidate signals, matched first 5 event timestamps, sequential condition funnel, baseline counts and same-bar old-family intersections. Full original-frontier audit covers **114 exact original executable configurations** for each symbol and counts union coverage rather than summing overlapping baseline signals.

Candidate's strongest old-family same-bar matches included BTC `factory_gen_wick_pressure_range_vwap_reclaim` and `factory_gen_wick_pressure_range_local_breakout` (2 each); ETH `range_midpoint_reclaim` and `factory_gen_wick_range_midpoint_reclaim` (3 each); ETH `failed_range_break_reversal`, `cross_pair_relative_reclaim`, `factory_peer_volatility_midpoint_catchup`, `factory_gen_wick_range_local_breakout` and `regime_conditional_composite` (2 each). One candidate candle can match more than one old family. **The union is the measure of economic-behavioral duplication, not a naive sum of intersections**.

## Mechanism difference, not automatic permission

- Historical generic `failed_range_break_reversal`: `h4_range`, observed 15m low below preceding **18-bar rolling prior low**, then bullish close back above that local prior low and relative volume.
- New proposal: prior **fully completed UTC calendar-day low** (independent of local preceding 18-bar level), `h4_range` and `h1_vol_ok`, positive **lagged** BTC/ETH peer-beta residual, prior-downside variance share above half, bullish current-bar reclaim with close-location and observed volume.
- `peer_beta_residual_reclaim`: requires **negative** lagged peer residual with a prior-range-midpoint reclaim, not the same exact relation as the new proposal's positive residual plus completed-day-low sweep.
- `prior_day_breakout_continuation`: bullish close above the **previous UTC-day high**, in an uptrend, opposite geometric edge from the proposed previous-day-low failure.

These source-level facts distinguish the exact rule strings; observed 10/15 old-frontier behavioral overlap, unverified long-horizon invariance, parameter/data-mining exposure and no realized costed P/L preclude any economic-uniqueness or robustness claims. The remaining five distinct events are not five *proven* new alpha occurrences. Do not invent or enforce a minimum trade-count qualification criterion: scarcity is evidence of uncertainty, not an arbitrary kill gate.

## Source files and independent QA boundaries

- `docs/evidence/strategy-finder-priorday-semantic-20261018/2025q1-original-source-signal-overlap.json` — original **six-neighbor** causal gate funnel, source SHA values, monthly counts and before/after per-family signal comparisons; canonical report digest `72e4cbe1c03f4582d16385a189f6f18b6cd8ed154576043e68dd2c7641fc8eaf`, local QA file SHA256 `7ffa2e28fbe5ceabf04c2f7520b64a06f3a179a3b4b858780c0dee5a32aca2d2`.
- `docs/evidence/strategy-finder-priorday-semantic-20261018/2025q1-all-114-original-signal-overlap.json` — expanded exact **114 old mechanism** match table per BTC/ETH, overlap union, five unmatched events; canonical report digest `212b5e6e73b83639a017ad412c4889791f684d5965dec259b63944acc57fd1c4`, local QA file SHA256 `abc138f9df53777e1af6654ceb22cce3f068737b1a8adb320855b73f2333da88`. Original local QA scripts and full loaded source frames stay isolated to Laptop2, not installed in the owner app.
- The source audit code was run **after** original candidate definition and exact SHA froze. Original source archived historical dates are long known/inspected, so the result is **behavioral diagnostic only**, not genuine independent economic OOS.
- Both audit executions on isolated Laptop2 completed natively exit 0. All six original physical raw-source locks matched, original closed-bar and peer timeframes validated; **no trade replay**, no realized profits, no 500-USDT equity simulation or risk qualification was attempted.

## Decision and next bounded gate

**Classification:** `PARTIALLY_DISTINCT_EVENTS__SEMANTIC_REVIEW_STILL_REQUIRED`. The full observed exact source sample makes the duplicate-risk argument stronger than the earlier six-neighbor comparison. No automatic approval record is added to `research/strategy_finder_executable_intake_allowlist_v1.json`, which stays **empty**. The project should not begin a second generic historical retry or re-tune cutoffs to force a positive number of events.

The next actual research decision is to independently inspect economic hypothesis **topology**, especially whether the proposed previous full-day auction failure plus positive lagged peer resilience is mechanistically different from generic range-rejection/mean-reversion, using externally justified sources and a precommitted hypothesis (not this source window's profit). If judged a semantic alias, reject without an economic backtest and seek a fundamentally different producer (such as shared-collateral portfolio ranking, previously raised as a distinct but unproven topology); if separately approved as materially distinct, research the exact frozen candidate with 500-USDT shared-cash physical fills and fees, label historical 2025Q1 as inspected and **withhold Demo until future untouched forward data**. Live always disabled; owner Laptop1 and existing Paper journals untouched.
