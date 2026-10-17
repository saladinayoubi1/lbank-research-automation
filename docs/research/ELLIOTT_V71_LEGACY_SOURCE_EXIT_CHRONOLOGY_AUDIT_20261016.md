# Elliott V71 — Archived source bar validation of legacy entry and exit times

**Date:** 2026-10-16 UTC. **Research-only:** isolated Laptop2, Draft PR #2673. **Not** a new strategy, source-forward V52 validation, executable quote, real filled trade, or financial return. Bybit only, Live disabled, Demo/Paper unchanged.

## Question and controls

V70 rechecked historical monetary reconciliation of the original Elliott five-swing simulator, finding training-positive but validation- and test-negative economics. This does not alone prove that its **entry and exit prices came from the correct completed 15-minute market bars**. A handwavy next-open rule or a retrospective profit target might misrepresent the opportunity.

V71 independently reopens the **original frozen Bybit 15-minute market archive** using the original verified-archive loader, then compares the previously SHA-pinned observed simulator `actual-fill-trace.json` against **each original OHLC source bar**. It is a retrospective anti-backdating audit of the original simulation, not a different trading model.

### Grounded physical corpus and hash pins

- Original 15m market frame for BTCUSDT: 128,544 bars, from **2022-12-01 00:00 UTC** through **2026-07-31 23:45 UTC**; ETHUSDT: same number and range. Both re-opened by the pre-existing verified archive loader, which verifies the bound historical archive source namespace.
- Legacy observed event-trace SHA256 `c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c`; legacy result SHA256 `02f96ca942091d882be7ba87547cd0b6f9c2e3e440fe4cc6e98b3e010332d2fc`; frozen independent V37 summary SHA256 `96d0322e416e1e7eb5587e08af8dff8b2e8590b677869808ff56d50b6548a024`.
- The audit uses the time-index of original OHLC rather than trusting the names `actual-fill-trace` or `fill` in the JSON as evidence of an exchange execution. Those are **simulated** fills.

## Results — actual archived OHLC versus simulated event traces

| Invariant | Checked result |
|---|---|
| Distinct original historical simulated trades | **10** |
| Profile-specific simulated trade records (conservative + stress) | **20** |
| Entry at exactly the OPEN price of index `decision+1` | **20/20 verified** |
| Decision bar CLOSE UTC equals following fill bar OPEN UTC | **20/20 verified** |
| Exit index, complete bar chronology and original exit reference | **20/20 verified** |
| Exit at original source-bar stop/target vs scheduled liquidation priority | **20/20 verified** |
| Stop and target both reached within a terminal exit bar | **0/20** |
| Source-derived exit classifications (per profile) | **12 stop, 8 target** |
| New positive nested Elliott forward signal or real exchange fill | **None** |

The frozen simulator implements the conservative convention: if a 15m bar's LOW reaches the stop, close at `min(bar_open, stop)`, even when its HIGH also touches the target. Only when the stop is not touched does a target-High touch settle at target. If neither is reached, time/terminal close is used. Separate targeted synthetic tests confirm stop-first dual-touch priority, adverse gap-through-stop, target-only, time/terminal exit, and chronology failure.

The source OHLC comparison cannot establish *intrabar tick ordering*, venue liquidity or bid/ask spread; nor does it independently verify whether the original historical **feature construction** was free of look-ahead. The old first-market numerical QA explicitly states `raw_market_leakage_independent_audit_completed=False`, and V71 preserves `independent_feature_leakage_audit_complete=False`. Without a tick/orderbook execution receipt, the pseudo-fill is not a real order.

## Execution evidence

Local isolated read-only script `research/elliott_v71_legacy_entry_exit_source/audit_legacy_entries_v71.py` can be invoked only with explicit archive, trace, result, V37 and output paths; it refuses overwriting the immutable output. Its original adapter loader is imported **inside the physical-audit function**, keeping pure regression tests independent of any private Windows checkout path. No change to the legacy simulator, V52/V69 scanner, existing demo or VPS.

First independent physical one-shot receipt `E:\NEXUS-QA\elliott-v71-entry-exit-source-check-20261016\V71_VERIFIED_ENTRY_EXIT_REPLAY.json` produced **20/20** match; the final source-refactored replay `E:\NEXUS-QA\elliott-v71-entry-exit-source-check-20261016\V71_FINAL_PHYSICAL_REPLAY.json` SHA256 **`e7b84a47c3094ccb6188a2c051d47da08777445087f828fdb32ffa2bd74c96d6`** reproduced the same 20/20, 12 stop + 8 target, zero dual-touch.

Eight separately authored and locally run regression tests PASS: dual stop/target stop-first, stop gap, target-only, time/terminal close, 15m source UTC clock, physical hash mismatch, invalid OHLC, non-trading flags. They are in `research/elliott_v71_legacy_entry_exit_source/test_legacy_entries_v71.py`, registered via `tests/test_nexus_elliott_v71_entry_exit.py`. **The exact-GitHub-head native full suite and hosted Windows/macOS/Ubuntu CI must be confirmed after publication before claiming full suite PASS for this commit.**

## Consequences

The already-observed **legacy** Elliott losses are not explained by a gross one-bar entry backdate or incorrect recorded exit reference on these 10 simulated trades, but the economic generalization deficit remains: V70's conservative profile training +7.9633 USDT, validation -17.6745, inspected test -6.9029 and total -16.6141; with stress friction total -56.4680. Data snooping, strategy efficacy, execution realism, spread and independent feature look-ahead remain open scientific limitations.

**Decision: do not promote Elliott legacy to Demo.** Await actually physically complete Bybit public Spot daily archives in the predeclared original V52 protocol: Oct16–17 source/warmup only, scoring Oct18–Nov16 UTC exclusive. V52 original child 3m and parent 15m and its SHA256 `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4` are not modified. No new P/L is claimed.
