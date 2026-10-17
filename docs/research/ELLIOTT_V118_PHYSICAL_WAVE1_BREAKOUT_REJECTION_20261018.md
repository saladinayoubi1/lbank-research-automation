# Elliott V118 — Source-bound physical entry/exit bridge (18 October 2026)

## Actual experimental verdict: four stopped trades; negative net P/L. **REJECT this fixed version**

This is an **actual archived OHLC replay** of one preregistered-in-code research hypothesis, not a new Elliott wave certification, not Bybit Demo execution, not an unseen future test, and not a live-trading strategy.

### What was missing and what this implements

The previous V106/V107 screen asks whether a causal **Wave0 → Wave1 → Wave2** partial geometry is necessary-pass, without any trade. V108 observes whether price later touches Wave0/Wave1 but is explicitly **not** a filled trade. V92 checks synthetic protective order execution, separately from the real historical six-event denominator. V117 predeclares alternative fine pivot counts on a **different future Bybit window**, still untouched.

V118 bridges these without altering any original V106/V107 source event, rejection or rule:

1. Original V99 independently observed 1-minute fine/coarse pivots, official archived two-symbol Binance Spot source and V89/V90 source evidence, V115 physical OHLC crosscheck.
2. Every original six-consecutive-coarse window remains in original V107 count; only the original **nine** strict V106 Wave1/2 necessary passes are considered for a hypothetical entry. Necessary-pass is NOT a proven Elliott wave.
3. Bearish cases abstain on Spot (no short). Bullish post-Wave2-confirmation cases observe up to **240 actual closed 1-minute candles**, rejecting any low touching the originally observed **Wave2 center close** before entry, and requiring a FIRST **completed close crossing above the original Wave1 high close** (previous completed close at/below original Wave1).
4. Signal known only after that candle closes; **next one-minute open** used as market entry. Same-bar favorable hindsight is not allowed.
5. One BTC/ETH **shared simulated cash** book, starting 500 USDT with maximum 250 USDT gross position, at most one open position, 2.5 USDT maximum *gapless nominal* stop risk including stress costs. No margin, short, borrowing or repeated risk-variant optimization; denied intents would stay in denominator.
6. Stop at original **Wave2 center-close structure**, target 2R relative to middle opening price and stop; exit uses physical low/high with **stop-first** if both stop and target touch the same 1-minute bar, worse open for a gap through stop, and precommitted 240-minute timeout at opening price. The original pivot center is NOT an executable fill. Limits are hypothetical and a real price gap could exceed nominal reserved risk.
7. Both frozen trading-cost profiles: conservative **10 bps fee + 5 bps adverse slip per side**; stress **25 + 15 bps per side**. Entry and exit both charge costs. Quantity rounds down to 8 decimal units, without claiming this is the exchange's approved tick/lot step.

### Source scope and strict evidence

- **Exchange is BINANCE Spot, NOT Bybit.** Unchanged V89/V90 provenance for original 28 daily archives, July 1 through July 14 2024 inclusive, BTCUSDT and ETHUSDT at physical 1-minute OHLC resolution, preinspected repeatedly in prior NEXUS work. There is **no independent prospective held-out evidence** in this experiment, and original source proof does not automatically make market conditions representative of Bybit Demo.
- Code `research/elliott_v118_entry_exit_bridge/bridge_v118.py`; unit tests `tests/test_nexus_elliott_v118_entry_exit_bridge.py`.
- Final original physical trade and all nine signal-screen records as counts: `docs/evidence/elliott-v118-entry-exit-20261018/V118_MEASURED_PREINSPECTED_PHYSICAL_TRADES.json`.
- Final canonical `result_digest=8f3eee2457530a2f4b08df7b7514b7b27f9a0010e6604311d77d22fae1c03983`. Local read-only physical output `E:\NEXUS-QA\elliott-v118-physical-20261018\final-source-physical-breakout-v118.json`; full physical output SHA256 `a227d2667af7176c712ce80db3e5ba926db846d20c4e38892974b1c8643779f0`.
- Output is source-evidence complete but **does not** include the original 1,212 full rejected candidate row-level ledger, which is still frozen in V107/V116. The original full-denominator count is verified before any economic result is emitted. No user Demo/Live position is changed.

### Exact 1,212-window funnel

| Original source/funnel | Count | Interpretation |
|---|---:|---|
| All six-coarse-window historical candidates | 1,212 | Full V107 denominator, no selection |
| Wave1/Wave2 V106 strict necessary passes | 9 | Not Elliott certifications |
| Bearish Spot-only abstentions | 4 | Never short |
| Physical Wave2 invalidated before an entry | 1 | Abstain, even if subsequent rebound |
| Original Wave1 closed breakout, next-open entry | 4 | All four hypothetically traded |
| Net winning closed positions | **0** | No favorable 2R hit |

### Actual 500-USDT shared-capital historical replay

| Cost profile | Closed trades | Grossly successful | Net P/L | Mean P/L | Ending cash |
|---|---:|---:|---:|---:|---:|
| Conservative (15 bps total per side) | 4 | 0 | **−8.792293 USDT** | −2.198073 | 491.207707 USDT |
| Stress (40 bps total per side) | 4 | 0 | **−9.999996 USDT** | −2.499999 | 490.000004 USDT |

In both profiles the **four recorded exits were `STRUCTURE_STOP_ONLY`**, not take-profit, timeout or ambiguous stop+target. Their unique identities are `ETHUSDT-326`, `BTCUSDT-306`, `ETHUSDT-404`, `ETHUSDT-438`. Final corrected classification does not alter economic P/L.

**Important**: the original first exploratory run had an overly broad diagnostic label that called any stop touch a same-bar stop/target ambiguity; this was corrected to distinguish actual `STRUCTURE_STOP_ONLY` from true dual-hit bars. The original economics never changed. Final output was independently reconstructed from unchanged archived source and SHA-bound as above.

### Engineering and economic gates

- Native Laptop2 physical test suite: **19 / 19 PASS**, following correction of one negative fixture that unintentionally contained a real next-bar breakout. Final real-source replay exit **0**.
- Invariant tests cover original known-right pivot, no future updates, entry at next open, W2 pre-entry invalidation, no Spot shorts, guaranteed worse stop on gaps, stop-first OHLC ambiguity, normal stop vs dual-hit distinction, fee stress, cash overlap rejection, impossible future timestamps, physical OHLC source errors, right-censoring and no Trading API import.
- Historical outcome is **not robust or profitable**, despite a technically correct lookahead-free executable model. Four losses are a small dataset, not a statistical estimate of a universal Elliott edge. Do not retune the Wave1 breakout confirmation, Wave2 stop, target multiplier or 240-minute horizon against these inspected bars to convert the result into a success claim.
- **Reject promotion**. Owner 500 USDT Demo remains untouched; no Bybit real execution, no change to V52 or frozen V117, no Live connector. Future economic improvement requires a *distinct ex-ante mechanism* with independent timestamp/source fill QA and genuinely subsequent market data, rather than looping variations on this already-inspected path.

`paper_eligible=false`; `live_enabled=false`; automatic Demo promotion=false.
