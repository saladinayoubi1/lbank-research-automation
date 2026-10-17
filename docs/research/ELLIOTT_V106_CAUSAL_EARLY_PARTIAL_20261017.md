# NEXUS Elliott V106 — first genuinely *early observable* two-wave partial hypothesis

**Research-only, synthetic-only, no market source fetched or any orders.** The V105 end-of-pattern diagnostic required a confirmed wave 5; it could never justify an earlier wave 2 or 3 order. V106 changes the *research hypothesis*, not the immutable V101 Wave 5 grammar: it inspects a possible Wave 1 and Wave 2 **immediately at confirmation of Wave 2** without accessing any future Waves 3–5. Passing this screen is NOT an Elliott wave certification, proven reversal, profitable trading system or actionable Demo signal.

## Locked lineage and future data

- Upstream V105 immutable Git source: commit `6d860b9aaffb7297f1f31dade5381650ac603fa0`, V105 manifest SHA256 `40d2b2d582a782205e115ddceacc07342f69c41111b6f6f4681785798f343e24`. V106 checks the exact Git object and verifies its source-only and no-orders invariants *before freezing*.
- Original untouched proposed future market source: **Bybit public Spot BTCUSDT/ETHUSDT, 1-minute, Nov 16 00:00 through Nov 30 00:00 UTC 2026 exclusive**, from V101. The future window has NOT been observed, requested, scored, or retuned for V106. V52's Oct 18–Nov 15, 2026 prospective installation and Laptop1 demo remain unchanged.
- V99 scale-3 (fine) and scale-8 (coarse) *close-confirmed* direction-change observers remain frozen. V100 handles strict source minute index/timestamps, event order, physical split, and full, unpruned fine pivots with no lookahead; coarse/fine degree remains a research convention, NOT actual Elliott degree.

## The V106 earlier-than-Wave-5 hypothesis

The input is **six consecutive coarse confirmed pivots**, from the predecision observer's original sequence: three historically prior context extrema, followed by candidate Wave 0 origin, Wave 1 end, Wave 2 end. The decision as-of instant must equal the *right-confirmation* of the Wave 2 pivot, **never its past center** and never a later hindsight instant. The pure primitive assumes a caller has verified source-derived consecutiveness; **it does not independently prove completeness of arbitrary user-supplied arrays**. This verification remains a future adapter/source provenance gate.

A narrow hypothetical bullish reversal requires prior `HIGH,LOW,HIGH,LOW,HIGH,LOW`, with the second preceding high strictly lower than the first high and proposed Wave 0 lower than the prior low. Bearish is the price-direction mirror. Wave 1 must advance in the proposed trend; Wave 2 must be a strict retracement that **does not touch or breach** Wave 0. Both original physical coarse boundaries must match independently confirmed fine swings of the same source-center, direction and close price. The exact **unpruned** scale-3 interior count for Wave 1 is 4, for Wave 2 is 2; later fine confirmations at a constituent right boundary are refused. **No favorable swings are skipped, removed, or introduced post hoc.**

The result always records all original coarse/fine SHA digests and exact decision time, with explicit hard rejection codes. It invariably sets `full_five_wave_observed=false`, `elliott_degree_certified=false`, `market_wave_position_proven=false`, `entry_signal=false`, `paper_eligible=false`, `live_enabled=false`, `net_pnl=null`. A valid partial 1–2 contour does **not** demonstrate that waves 3–5 will ever develop, and its false-positive rate is unknown.

## Non-executable first-bar stop/target diagnostics

V106 adds a **synthetic first postconfirmation closed 1m OHLC** test to avoid reporting impossible entry/exit success. It projects the *historical OPEN of the just-closed bar* as a hypothetical reference ONLY; this is **not an actual filled price** and not available with the bar's high/low until the bar closes. The hypothetical defensive reference is the already confirmed Wave 0 origin; a wrong-side/open-at-stop condition must abstain. An arbitrary, fixed **2R** level illustrates potential target distance; this is **not an optimized Elliott take-profit**.

A bar hitting BOTH hypothetical stop and target is assumed to hit the **stop first** due to unknown intrabar high/low order. Stop-only, target-only and no-touch outcomes are separately labeled **illustrative**, with no recorded P/L, orders, spread, fees, slippage, price impact, or open-position lifecycle. No favorable first-bar result ever becomes a Demo entry signal. Full multi-bar conservative fills and Bybit execution costs would require later separately frozen research and untouched market evaluation.

## Scientific and release status

- Code: `research/elliott_v106_early_partial/early_v106.py`; synthetic tests: `tests/test_nexus_elliott_v106_early_partial.py`.
- Frozen write-only research manifest: `docs/evidence/elliott-v106-early-partial-20261017/V106_FROZEN_EARLY_PARTIAL.json`; SHA256 **`b5621cc22df287ea16e1cbcfaf0b94da4a6bb0a682b9ed3962ec69f08508b948`**, `V106_FREEZE_EXIT=0`, **0 market source rows and 0 actual positions**.
- Positive synthetic mirrored Up/Down Wave 1–2 contour passes the **necessary** grammar but cannot claim complete Elliott. Negative controls reject old trend context failure, wave 2 breach, absent/fake fine boundaries, missing or added pivots, future coarse/fine confirmations, forged source-time indexing, backdated or delayed decisions, impossible bar use, wrong-side opening gap, simultaneous stop/target profit bias, and hidden broker paths.
- The repeatedly inspected July 2024 historical data were **not used** to tune the V106 contour or choose profitable variants. The only prospective test window remains uninspected and protected. PR #2673 stays Draft/unmerged, Bybit only for any future explicitly permitted Demo/Paper, Live disabled.
- Next scientific challenge: create a source-backed **event-by-event prefix enumerator** that enforces *every* six-consecutive-coarse window, captures future Week/Day false positives and abstentions, then assesses true pattern position, fees, slippage and complete conservative exit metrics after independent future data collection. No retrospective validation on July 2024 is presented as prospective performance.

## Completed source / CI-quality audit

- Dedicated synthetic V106 QA: **27/27 PASS**, original native `V106_DEDICATED_EXIT=0`. As expected, an earlier draft suite rejected both pruned and forged source pivots through a stricter upstream primitive first; the two test expectations were corrected and the entire suite subsequently rerun cleanly. No unverified market outcome was accepted.
- Full Elliott Laptop2 suite: **971/971 PASS** (`Ran 971 tests in 71.858s`, `OK`), native `V106_FULL_EXIT=0`. The local full regression evidence file `$env:TEMP\V106_FULL_ELLIOTT_REGRESSION.txt` SHA256 is `6463a2c38e41cec302e0379e28c20e48717f1ad11b7db2a826c2c83a9388b316`.
- The future V106 frozen rulebook is byte-verified SHA256 `b5621cc22df287ea16e1cbcfaf0b94da4a6bb0a682b9ed3962ec69f08508b948`; nothing was fetched or traded.
- Predecessor V105 GitHub Workflow Permissions Policy, Research Evidence Refresh and Test all **SUCCESS** for commit `6d860b9aaffb7297f1f31dade5381650ac603fa0`. V106 GitHub CI is a separate post-push gate, not implied by local regression.
