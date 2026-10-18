# NEXUS — Original portfolio-v3 causal closed-4h drawdown guard (2026-10-18)

## Specific completed objective

Introduce an **explicit research-only, default-off** shared-wallet drawdown circuit breaker into the **existing** `bybit_portfolio_search_v3.exact_backtest`. Do **not** invent another portfolio engine or change previously computed v3 earnings, fills or default positions. PR #2722 already provides native original fill tracing and independently reconciled FIFO lot accounting. This change relies on that source truth: the proposed guard sells the *real original 4h Spot positions* through the existing sell-first accounting and the new independent journal proves its economics.

There is **no live risk enforcement or protective order on Bybit**. The protocol is only a historical, optional research experiment to determine how a simple **20% equity high-watermark drawdown** threshold behaves under causally executable, gap-aware fills. The numerical 20% threshold was **fixed before this particular guarded 2025Q1/2023–2026 replay**, not optimized through a new parameter grid. **However, the original strategy's approximately 34.4% drawdown and the whole source history were already known**. Therefore the threshold choice is *not prospective blind*, and the observed research results **cannot be used as independent OOS evidence of benefit**.

## Guard contract and causal timeline

Only the following exact contract is accepted; altered thresholds, policy name, authority or exit timing fail closed:

```json
{
  "schema": "nexus.portfolio-v3-causal-close-dd20-nextopen.v1",
  "max_closed_bar_drawdown_fraction": 0.20,
  "halt_rest_of_research_period": true,
  "exit": "next_4h_open_sell_first_no_reentry",
  "live_authority": false
}
```

- Uses **one 500-USDT cash-funded BTC/ETH Spot wallet**, original long-only next-4h-open fills and the original fee+adverse-slippage profiles. Original v3 weights, original source-traced fills and globally anchored rebalance mask are unchanged.
- At **each completed 4-hour candle close**, compute genuine post-close marked BTC/ETH wallet equity (no future intrabar low or close peek), update current equity high-watermark and observe its drop. If drop is at least 20% from its peak, arm the switch **after that candle is closed**.
- At **the first following 4h bar open**, **sell all currently held BTC/ETH positions using that actual next-open price** with the original sell-side adverse slippage, original fee and original shared-cash accounting, not the earlier trigger candle close or a favorable stop quote. The observed fill source/UTC timestamps are preserved by original v3 optional `fill_trace`.
- Afterwards enter a permanent cash-only **halt for that historical period**. Targets that remain long must not cause re-entry or additional buys. The guard's own event receipt discloses exact close trigger time, actual next-open liquidation time, number of forced sells, post-sale cash and whether the trigger happened only at the final horizon candle (where no future next-open exists and no fictitious forced fill is allowed).
- No guaranteed 20% maximum mark-to-market drawdown: price gapping at the following open, time to observe 4h close, trading frictions and intrabar losses **can exceed the threshold**. This is a causal circuit-breaker, not a limit order, bracket stop or deterministic per-position maximum loss.
- Without explicit `risk_policy`, **the original exact_backtest financial behavior and returned metrics remain identical**; no default research, app, scheduled search or Paper/Demo runtime call opts in.

## Source-verified observed real Bybit Spot historical comparison

Both controls were executed against six **exact pinned raw** Bybit Spot BTC/ETH 15m, 1h and 4h cached archives, independently checked before source market load, using the same existing frozen original `dual_rotation` candidate `b4e4a2c33304aec1`. Two independent 500-USDT start-of-scope historical studies were run; within each study BTC and ETH share exactly **one wallet**. The unguarded original and guarded candidate start with the same 500 USDT and original weights, 4h timestamps, normal/stress/severe cost schedules.

| Inspected period and modeled cost | Old normal v3 net USDT | Opt-in 20% causal guard net USDT | Guard max drawdown | Did guard trigger? |
|---|---:|---:|---:|---|
| 2025 Q1 conservative (10bps fee + 5bps slippage/side) | **+8.43707258** | **+8.43707258** | 6.74354902% | No |
| 2025 Q1 stress (15+10 bps/side) | +7.90278653 | +7.90278653 | 6.74675724% | No |
| 2025 Q1 severe (25+15 bps/side) | +7.10143040 | +7.10143040 | 6.75157584% | No |
| **Sep 2023–Jul 2026 conservative** | **+343.66115005** | **+152.86318294** | **20.16420603%** | Yes, Aug 5 2024 UTC |
| Sep 2023–Jul 2026 stress | +320.11394615 | +142.16458950 | 20.86786870% | Yes, Aug 5 2024 UTC |
| Sep 2023–Jul 2026 severe | +285.97596337 | +133.67674702 | 21.00827844% | Yes, Aug 4 2024 UTC |

**Actual finding:** compared with the historical unguarded original max drawdown **34.43365449%** under conservative cost, this guard observed max drawdown **20.16420603%**, **not** a guaranteed 20.000% cap, but also gave up **190.79796711 USDT** of old modeled net P/L in the entire historical period after it exited in 2024 and stayed cash. This is an explicit risk-vs-return tradeoff, **not** a proven profitable "improvement" and not a prospective validated risk policy.

The conservative risk trigger was observed at `2024-08-05T00:00:00+00:00`, the **closed 4h decision boundary**, with actual sells made at the next open according to the matching original 4h UTC market timestamps. Absolute trigger timestamp equality with next candle opening timestamp does **not** allow a simulated fill earlier than the candle close—only a physically priced next-open sale with fee and slippage.

## Reconciliation and tests

- Changed original `bybit_portfolio_search_v3.py` adds the optional `risk_policy=None` keyword and new `causal_risk_audit` return fields **only when explicitly opted in**. It is integrated inside the original execution loop, not in a duplicate simulator. Original native fill tracing and independent FIFO remain intact and reconcile all actual fills/cash/fees/DD of the guarded path.
- New `scripts/nexus_portfolio_v3_causal_dd20_diagnostic.py` source-hashes all six original Bybit BTC/ETH raw files, loads the original 4h causal source, executes only the *existing* fixed candidate and predeclared exact two scoped intervals with three locked cost profiles, compares old unmodified vs risk-on financial outcomes, and never re-optimizes.
- `docs/evidence/portfolio-v3-original-500-calibration-20261018/fixed-causal-dd20-vs-unchanged-2025q1-2023to2026.json` contains exact historical risk audit receipt, separate profile/source dates, FIFO/accounting digests, old vs new P/L/fills/DD, raw original source SHA values and research no-promotion authority. **Canonical digest:** `22f723c4ef707cbb51f903593ba0510d3c5a21e2ca2659c4ae6f1b376481ad46`; original Laptop2 raw artifact SHA256 `ee218919e3176dea28329347dd8f21117856d5c6824f6e935267a94dea78e4ba`.
- `tests/test_nexus_portfolio_v3_causal_dd20_policy.py`: 14 synthetic tests, including original-on/off **metric equality**, trigger only after closed 4h, true next-open gap to a significantly worse price (20% close threshold breached at ~40% realized loss), both assets forced sold at the same next open before any future buys, no trigger falsely manufactured, final-horizon trigger without a next-open **not** executed as fictitious exit, risk schema/threshold/Live/authority tamper failures, and FIFO journal integration.
- `tests/test_nexus_portfolio_v3_causal_dd20_real_evidence.py`: 5 actual-source evidence/digest, old-original-baseline P/L parity, Q1 no-trigger parity, 2024 risk threshold exceedance and negative future-qualifications tests.
- 9 original baseline native tracing/FIFO tests from merged PR #2722 also re-run, with total **28/28 isolated Laptop2 native tests PASS**. Actual source-bound causal vs default experiment ran exit 0; all three fee profiles original and guarded reconcile actual modeled cash/fills/fees/mark-to-market drawdown. Hosted GitHub Windows, Ubuntu, macOS CI and System Map gates are separate mandatory approval requirements.

## Limits and what must not happen

This is **a risk research diagnostic, not a released risk control**. Source history through July 2026 was already inspected and 20% was chosen after historical drawdown was known; observed reduced drawdown cannot justify an OOS claim. No actual Bybit Spot lot-step, exchange execution matching, real order book impact or latent bid/ask depth has been certified. The original risk policy is still default **off** and **nothing has been installed/activated** on owner Laptop1 or the second laptop's NEXUS product. The future Elliott V117 external lock remains untouched. NEXUS maintains `Live=false`, no paper promotion and zero real exchange orders.

The next independent substantive validation must freeze one risk contract **before future untouched Bybit bars arrive**, collect those new bytes and cost evidence independently, and assess outcomes without repeatedly retuning the 20% threshold on already inspected archives. Even if it works prospectively, separate paper-only operational and QA gates are required.
