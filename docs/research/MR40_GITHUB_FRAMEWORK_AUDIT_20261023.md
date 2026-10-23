# NEXUS MR40 — third-party GitHub framework audit (2026-10-23)

**Status:** EVALUATED; NO_ADOPT; NO_MERGE; NO_PROMOTE. Roadmap [#2799](../../issues/2799), option register [#2832](../../issues/2832). Based on existing research PR #2808.

## Scope and truth labels

- **Actually executed:** only QuantDinger's unmodified, Python-stdlib robustness modules (`statistics.py`, `walk_forward.py`), loaded directly from an isolated sparse GitHub checkout on physical Windows Laptop2 (`DESKTOP-F4SA4VL`), pinned at `d7642d7`. Also executed NEXUS's SHA-locked existing MR40 input loader as the source oracle.
- **Code/docs/license reviewed, not executed:** Freqtrade, NautilusTrader, VectorBT. No performance benchmark, installation, broker-connector test, data live feed, or parity assertion for these three should be inferred.
- **Data:** Bybit BTCUSDT Spot 4h, 8,514 previously seen candles with canonical OHLC digest `a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a`; 47 frozen BASELINE historical positions (25 train, 22 seen evaluation); stress cost 25bp fee + 15bp slippage, 500-USDT research reference. These are **not** independent prospective observations.

## Audit results

| Component | Grounded behavior | MR40 implication | Decision |
|---|---|---|---|
| [QuantDinger](https://github.com/OpenByteInc/QuantDinger) Apache-2.0 | Strategy evolution engine imports PBO, Deflated Sharpe, block-bootstrap and walk-forward plan. Separate `strategy_ai_generation.py` and strategy V2 generation contracts **do** provide a prompt-oriented strategy generation layer, but the AI generation/runtime itself was **not** tested. | Extract narrow statistical diagnostics as an independent reviewer; no full-stack backend, Celery, trading execution, credentials or SaaS integration. Cannot claim the AI automatically discovers economic edge. | Research methods **worth testing**, no platform adoption |
| [Freqtrade](https://github.com/freqtrade/freqtrade) GPL-3.0 | Actual `IStrategy`, backtesting, and `lookahead-analysis` implementation; official exchange table confirms Bybit **Spot** has no stoploss-on-exchange support through Freqtrade. Its `dry_run` is an internal simulated wallet, **not** a real Bybit Demo account. | Independent research benchmark or future lookahead checker only. Porting MR40 requires exact next-open, episode veto, fee/slip and stop/gap parity; potential GPL license obligations. | **Do not install** into active NEXUS |
| [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) LGPL-3.0 | Official Bybit adapter supports `MAINNET`, `DEMO`, `TESTNET` explicitly; SPOT venue has no position-level native trailing-stop in Nautilus; generic trailing-stop-market requests are denied by adapter. Event-driven fills/order testing possible in isolation. | Most promising **future execution-parity** tool if a specific simulator gap is demonstrated. Must hard fail-closed on environment `DEMO` / no live key and perform first tests without execution client. | **Read-only benchmark candidate**, no connectivity test |
| [VectorBT](https://github.com/polakowo/vectorbt) Apache-2.0 **with Commons Clause** (`LICENSE.md`) | Vectorized `Portfolio.from_signals`, stops, `from_order_func` for advanced logic. `portfolio/nb.py` warns of rounding drift; vectorization alone does not simulate exact Bybit execution or unknown intrabar order. Commons Clause restricts selling software-derived services. | Good for sensitivity/exploratory parameter plots; MR40 already has event-driven reference and preserving parity is nontrivial. Need license review before commercial use. | **Low priority / optional** |

Official documentary verification: Freqtrade `docs/lookahead-analysis.md`, exchange support [docs.freqtrade.io/en/latest/exchanges](https://docs.freqtrade.io/en/latest/exchanges/); Nautilus Bybit integration `docs/integrations/bybit.md`; VectorBT `LICENSE.md`; QuantDinger `backend_api_python/app/services/strategy_evolution/*` and `strategy_ai_generation.py`.

## Actual QuantDinger numerical smoke

Executed untouched source functions `build_walk_forward_plan()`, `monte_carlo_bootstrap()`, `deflated_sharpe()`, `sample_sharpe()`, `probability_of_backtest_overfitting()`. Source checkout `d7642d7`; isolated in `E:\NEXUS-Research-Sandboxes\quantdinger-stdlib-20261023`. The Python script and machine output are included in this draft PR.

- Chronological plan: **3 folds**, **one 4h embargo bar** per fold, 20% tail reserved from **historically seen 2023–2026 records** (`blind_start=2026-01-09T08:00:00Z`), so blind is only a mechanical name, **not true blind OOS**.
- Bootstrap from 47 realized historical, stress-cost **per-position returns**, 400 resampled block paths (effective block length 3, seed 19): modeled `lossProbability=0.115`, median modeled path drawdown `-12.2791%`. Same seed reproduces exact output. **Not a calibrated forecast or actual future loss probability.**
- Approximate DSR on **per-trade**, not daily time-indexed portfolio returns: `probability=0.536497`. Do **not** use as decision evidence; small historical n, dependence, selection bias, annualization/timing convention mismatch.
- PBO: `available=false`, `samples=0`, `reason=insufficientCandidates` with only two independent chronological windows. **Zero is NOT a measured PBO probability**; fee variants must not be invented as independent data folds.
- No strategic edge validated. No new backtest candidate, optimization, position sizing, broker order, pipeline automation or Paper change.

## Acceptance, follow-up, and cost

1. Prioritize **actual new, authenticated, fully CLOSED future Bybit Spot trade observations** under existing immutable MR40 protocols. Do not recycle or select on the seen 47 entries. A single post-day archive is a data-integrity step, not 12 trades.
2. If NEXUS fails an identified statistical guard, create a minimal **independent diagnostics adapter** (maybe code concepts from QuantDinger, respecting Apache-2.0 attribution) and require deterministic seed, genuine independent fold evidence and ledger parity. No bulk import of external code.
3. Freqtrade `lookahead-analysis` is a useful later **independent code-bias checker** if a separately versioned lightweight environment can run and exact next-open/fees parity is possible.
4. NautilusTrader isolated deterministic execution simulator only after a concrete event/fill mismatch appears; **never live connectivity by default**. Don't add VectorBT for routine MR40 experiments absent a measured research-speed bottleneck.

### Safety

No private Bybit API, credentials, order placement, live trading, changes to 500 USDT Paper account, existing Windows NEXUS installations, journal or profile. No merge, strategy promotion, scheduler or background task. All results above are offline historical exploratory evidence.
