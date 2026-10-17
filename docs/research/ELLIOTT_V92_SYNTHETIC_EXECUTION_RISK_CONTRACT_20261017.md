# NEXUS Elliott V92 — research-only execution semantics and risk-failure gate

**Scope:** additive **offline synthetic execution scenario tests** and source-bound denial verification; no model optimization, no new market-data period, no historical trade backtest. Bybit Demo/Paper only for any future deployment; **LIVE remains disabled**. V52 forward protocol (15m/3m/1m, Oct 18–Nov 15 2026 UTC scored) unchanged. Laptop1 Demo, existing runner, trade journal, VPS, GitHub PR merge state untouched.

## Source chain / historical denial

The stage replays *only* the immutable V91 eight-candidate research admission evidence, SHA-256 `d4401a5606dee6a0842d1ee3752375dc95de732b9189eb3e65983640ec1715c0`, Git commit `1fa94b9432be9d13782f3f76c0bb48737c3bc445`. Original V91 records came from pre-registered July 2024 14-day Binance historical data. For each case, V92 checks Git blob byte-for-byte, the historical decision timestamp, absence of retrospective pivot-center entry, missing policy evidence, and explicit `order_admission=DENY`.

| Frozen case disposition | BTCUSDT | ETHUSDT | Total |
|---|---:|---:|---:|
| Actual V91 five-leg hypotheses | 6 | 2 | **8** |
| Explicit `DENY` / structurally unproven | 6 | 2 | **8** |
| Real entries, orders or fills | **0** | **0** | **0** |
| Actual net P/L | *not evaluated* | *not evaluated* | *not evaluated* |

Research admission cannot be overridden by synthetic profitable illustrative fills. **No adapter is wired into the Demo runner**: the research code is not an assurance that all external execution paths are safe.

## Specific chronology and fill-risk invariants

The source-confirmation event `asof_ms` is the **end of a fully known 1-minute candle**. Only the immediately following new one-minute candle opening at the **same UTC millisecond** can be an illustrative market-entry candidate. A backtest can inspect that candle's high/low/close only **after** its own close; no intra-bar prediction or early use of its future extrema.

Synthetic-only `DiagnosticPlan` uses typed `Decimal` prices and explicit side, quantity, protective stop, take-profit, *per-side fees in basis points*, full bid/ask spread in basis points, adverse slippage per side, nominal risk ceiling and gross notional ceiling. All numeric values in unit tests are **fictional software fixtures**, not NEXUS recommended/optimized parameters and not measured Bybit quotes.

Execution risk rules:
- Opening fill is adverse against the synthetic midpoint by **half full spread plus assumed slippage**; both entry and exit pay separate fees. Negative fees, nonfinite prices, wrong stop/target direction, high less than low, missing 1m candle closure and binary floats fail closed.
- A stop and take-profit both touched within one OHLC minute resolves to the **stop**, because intraminute event ordering is not observed. A trade lacking a known exit remains **unresolved**, not silently valued as a winning position.
- At a later synthetic bar, a gap through the stop fills at the **worse opening price** plus adverse exit friction, not at the unachievable stale stop. A favorable target gap is **not improved optimistically** above/below the declared target.
- `max_nominal_risk_including_fees` is only a **nominal pre-fill scenario ceiling**. A real stop-gap can exceed it; this is **not** a risk guarantee. Additional paper-order and market-data certification would be mandatory.
- Entry and follow-up bars must be exactly chronological, UTC-aligned and fully closed before their OHLC is analyzed. No real network, Bybit secrets, order methods, balances or user profile are read.

## Research status

`research/elliott_v92_execution_semantics/execution_v92.py` is a pure scenario calculator, plus an eight-case deny auditor; it does not generate a trading strategy, target ratio, valid Elliott count, paper position or historical P/L. Every synthetic return is marked `synthetic_only=true` and `not_historical_pnl=true`; all actual-case financial outputs remain `null`.

Source-traced V92 receipt: `docs/evidence/elliott-v92-synthetic-execution-gate-20261017/V92_EXECUTION_CONTRACT_AUDIT.json`, SHA-256 `490b283bbf0cc218eec1e417df49f854fe4e4646e142a4d98b7bb244a097324a`. Historical V91 source bytes unchanged.

## Next independent gate

Before opening any previously unseen sample, preregister a fully *falsifiable* multi-degree recursive Elliott classifier and a truly executable **post-confirmation** entry/stop/target/timeout rule. Verify bid/ask quote and fill chronology (including funding/fees, spread, slippage and gap loss) on separate held-out research data. **No promotion to Bybit Demo** until source, causal timestamps, observed cost-inclusive net performance and safety gates pass. Live never enabled.

## Verified execution receipt

- Dedicated V92 synthetic adverse-fills and immutable-deny tests: **21/21 PASS**, `V92_DEDICATED_EXIT=0`, covering first eligible minute, right-closed OHLC, nonfinite data, bid/ask adverse execution, separate fees, long/short SL/TP collisions, stop-gap-through worse price, nominal risk/notional filters and no invented P/L.
- Full Elliott-focused regression on Laptop2: **716/716 PASS**, `Ran 716 tests in 50.053s`, `OK`, native `V92_FULL_EXIT=0`. Local test log at `E:\NEXUS-QA\elliott-v92-synthetic-fill-gate-20261017\V92_FULL_REGRESSION.txt`, SHA-256 `49860ce5b6fa12d769f3c7ed91b1d4912eaf871af9398400981c1ca901983df8`.
- Source-bound real-case denial receipt SHA256: `490b283bbf0cc218eec1e417df49f854fe4e4646e142a4d98b7bb244a097324a`. Local evidence and the future Git-tracked JSON must be identical.
- GitHub CI state after this new commit is **not claimed passed** until independently verified.
