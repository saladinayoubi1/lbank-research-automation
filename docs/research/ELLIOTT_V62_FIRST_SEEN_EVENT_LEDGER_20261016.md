# Elliott V62 — Persistent first-observed causal geometry

**Date:** 2026-10-16 UTC. **Scope:** Draft PR #2673; limited bullish impulse+ABC, strict width-3 right-confirmed 15m parent, fixed 3m child degree, Bybit public Spot BTCUSDT and ETHUSDT. Research-only; no trade execution, Paper promotion, Live, P/L or production install changes.

## Actual discovered fault

Previously the frozen V53 prospective scanner iterated all strict right-confirmed 15m pivots, compacted consecutive same-kind extrema to the more extreme pivot, then **at the end of the entire source snapshot** enumerated valid nine-parent geometries from the mutable final list. This is a look-ahead-induced reporting problem: a valid wave can first be discovered at an earlier daily decision, then be mutated by a stronger later ninth-parent low when retrospectively replaying that same day or a future day. Its fingerprint and apparent right-confirmation date change, or the originally observed candidate disappears. V54 excluded old candidates based on the *current mutable last pivot confirmation*, so a previously recorded geometry could be scored as new again after replacement.

Reproduction in V62's independent synthetic pivot-injection fixture: first bullish nine-parent geometry formed at 15m pivot-confirmation index 331 (Oct19 11:00 UTC). Later stronger same-kind ninth lows changed its final fingerprint from `1012b2469a0a760ae3ef7dac` to a different value without a new eight-parent skeleton. A late replacement in the following scoring day also caused old V53 to report a prior event as a newly scored candidate. **Three of the original four targeted regressions failed against the pre-V62 scanner**.

## Fix, without after-the-fact indicator tuning

Updated `research/elliott_v53_prospective_scan/scan_verified_v53.py` on the research branch. At **each right-confirmed parent pivot**, not just at the end of the historical window, the scanner checks whether the last nine accepted pivots first satisfy the existing geometric conditions. It stores an immutable snapshot and first knowable confirmation timestamp in a per-scan `first_seen` event ledger:

- Identity = the first **eight** immutable parent anchors' (index, kind, price). The ninth same-kind parent is mutable and may be replaced by a more extreme extremum; its replacements **cannot erase or re-date** the previously observed nine-parent candidate or spuriously create extra signals.
- If the first ninth pivot fails original geometry, a later more extreme ninth pivot can establish a valid structure **only when its own full right-hand confirmation is observable**. Nothing is backdated to the earlier invalid pivot.
- Every already-observed candidate is retained for daily V54 first-time-only date classification even if subsequent pivot compaction alters the final present-day accepted list. Older event fingerprints and first timestamps remain intact.
- Parent geometry restrictions (`5-3-5-3-5` plus `5-3-5` ABC), width-3 confirmation, frozen 15m/3m/1m degrees, proof gating, V52 study dates and score embargo remain **unchanged**. The result is still `entry_signal=false`, `paper_eligible=false`, `live_enabled=false`, no realized or hypothetical P/L.

This first-observed event ledger is deterministic within each full verified source-day replay, **not** a persistent external database or worker. The stable identity policy intentionally recognizes additional variants of the same eight-anchor wave as one research candidate; this is a conservative duplicate-prevention rule, not new optimizer parameters.

## Evidence

V62 six targeted synthetic adversarial tests (1) original event fingerprint remains after last ninth pivot replacement; (2) multiple replacements never multiply or re-date it; (3) replacement after the first scored day cannot cause another daily score; (4) original unchanged event remains eligible once; (5) an initially invalid ninth pivot becomes valid only after the later replacement's confirmation; (6) a repeat next day retains once-only accounting. **6/6 PASS** after fix. The pre-fix version failed **3/4** original tests.

The unchanged V53/V54 baseline suite also passed against isolated modified scanner: **19/19 PASS**. Both results were verified on isolated Laptop2 QA (`E:\NEXUS-QA\elliott-v62-first-seen-ledger-20261016`). Native discovery `tests/test_nexus_elliott_v62_first_seen.py`.

No claim of a newly profitable or complete Elliott pattern is made. V61 on the **previously inspected** Oct08–12 physical BTC/ETH archives found no BTC nine-parent geometry, and one historical ETH parent candidate first observable Oct10 23:45 UTC, but V49/V50 strict child-degree witnesses still reject its first leg (six interior sub-extrema against the four required). These historical observations are **not** untouched forward data.

## Next gate

Verify all native Elliott tests, the full hosted Windows/Linux/macOS CI matrix on the exact branch head, and—only when whole UTC future-day public Bybit Spot archive data have physically arrived—use V58 TLS capture, V55/V52 independent OHLCV, V59 raw-to-minute chain, V60 availability lag, and the corrected V53/V54 first-observed score ledger. A daily raw archive received after its decision instant must remain **retrospective structural research**, not a real-time trade.
