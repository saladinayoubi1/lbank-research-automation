# NEXUS V100 — Source-bound causal coarse/fine relationship ledger

**Status: retrospective research accounting only; never Elliott certification or a trade.** This is a strict follow-up to V99's separately detected 3× and 8× trailing-volatility close-swing observers, not a completed multi-degree Elliott model. The previously inspected Binance Spot 1-minute source dates **July 1–14, 2024 UTC** are unsuitable for a new trading performance claim or future parameter selection. The only potential eventual Demo exchange is Bybit. Live is disabled; V52 future protocol, installed Laptop1 Demo, VPS and paper journals are untouched. PR #2673 remains Draft/unmerged.

## Source authority and causal contract

V100 uses V99 commit `9531efb0bdbd851e39d39322d8f37f40f92d44d6`, exact immutable Git receipt SHA256 `69a88a3e101d53ea4d84b1bad999de9482cf153fb6a9c1674cf0f40a604666a2`, and the original 28 official Binance Spot 1-minute ZIP/CHECKSUM pairs authenticated by V88/V89. The V99 closed-Close stream is replayed for 40,320 candles; recomputed scale-3 and scale-8 pivot SHA digests must exactly match the original immutable V99 output before classification.

V100's `research/elliott_v100_scale_context/context_v100.py` treats **both scale event streams as independent and complete**; the coarser series does not automatically count as higher-degree Elliott. For each adjacent pair of coarse confirmed-swing centers, the fixed center-time partition allocates *every* fine event exactly once to one of three categories:
- Strictly inside one coarse center-to-center interval, preserving **all** fine swing objects and their order; record a SHA256 for the untouched interior sequence.
- Exactly on a coarse-center boundary; record separately, never duplicate in an interior count.
- Outside the observed coarse-center range; record separately, never silently discard.

For each coarse interval, the admissible observation time is the **right coarse swing's own confirmation close** (never its historical center). Fine swings whose center is inside but which confirm **later** must remain in the full accounting and be marked `LATE_FINE_CONFIRMATION_ABSTAIN`, never retroactively available for an earlier entry. Every source event's minute index and its center/confirmation timestamp must agree on the same source epoch, with strictly alternating labels and monotone confirmation order. Prefixes through end of Week A remain identical in the full Week B replay.

Neither equal pivot centers nor common direction confirms wave degree, wave position, a nested subwave, market pattern context or profitability. **V100 issues zero certified waves or trade entries regardless of the cross-scale match count.** It does not opportunistically select a 5–3–5 set, prune extra short-scale turns, or select a family using hindsight.

## Entire original July 2024 event census (NOT backtested positions)

| Causally observed metric | BTCUSDT | ETHUSDT |
|---|---:|---:|
| Physically authenticated 1-minute historical bars | **20,160** | **20,160** |
| All scale-3 fine confirmed swings | **2,212** | **2,206** |
| All scale-8 coarse confirmed swings | **609** | **613** |
| Consecutive coarse center-to-center intervals | **608** | **612** |
| Fine swing centers on coarse boundaries | **607** | **611** |
| Fine swing centers inside coarse intervals | **1,600** | **1,588** |
| Fine swing centers outside observed coarse range | **5** | **7** |
| Coarse intervals with late fine confirmations | **0** | **0** |
| Lost/deleted fine events | **0** | **0** |
| Elliott full-pattern certificates, orders, net P/L | **0 / 0 / not evaluated** | **0 / 0 / not evaluated** |

The almost universal *center coincidence* is a descriptive result of two algorithms applied to the **same price-close stream**, not independent Elliott-pattern corroboration. The coarse stream's reduced event count is mechanical scale filtering. The 0 late-confirmation count is specific to this exact previously observed sample, not a theorem; synthetic tests include an actual future-unavailable interior event and verify mandatory abstention.

## QA and deployment prohibition

Synthetic/source-free tests verify exhaustive single-bucket allocation, no deletion, late confirmations, no access to unclosed future data, exact center/confirmation minute-index consistency, shared source epoch, untyped/nonfinite prices, duplicate or reordered events, inconsistent labels, malformed cutoffs, event SHA tampering and zero-trade flags. No GitHub CI success is asserted until independently observed for the new commit.

Report: `docs/evidence/elliott-v100-scale-context-20261017/V100_CAUSAL_CROSS_SCALE_POSITION_LEDGER.json` (exact bytes sealed in Git via `-text` attribute).

## Next gate

V101 should preregister a separate, **falsifiable** cross-scale Elliott-family/pattern-position grammar and explicit ambiguity/rejection criteria on *unseen* source periods without re-fitting on the already inspected July dataset. Before any Demo promotion, the classifier must prove confirmations are available at entry, test realistic Bybit spread/fees/slippage/latency and conservative stop/target sequencing on untouched forward data, then get explicit paper-only deployment approval. Do not enable Live or modify V52.

## Verified V100 QA and artifact identity

- Independent historical cross-scale replay **V100_FINAL_AUDIT_EXIT=0**, with complete V99 source receipts and event-stream SHA validation; all 4,418 fine events are classified exactly once across both symbols. Final research evidence SHA256: `1b77d41944b6a00b6eaf9d47e3dd7b74277989b825ad9e2e967c8623478a5547`.
- Original draft evidence was rejected after a non-economic field-name correction and preserved separately in local OS temp storage as `V100_PRE_FINAL_FIELD_NAMING_DRAFT.json` (SHA256 `8aec353684c8fd83359d29ac9ab547a6b43ed5bf4583765d856156d04da4e5dd`); only the corrected evidence is published.
- V100 adverse/synthetic dedicated QA: **20/20 PASS**, native `V100_DEDICATED_EXIT=0`; verified exact event index/time, late confirmations, source-epoch consistency, full event allocation, tampered source inputs and no trading.
- Full Elliott Laptop2 regression: **847/847 PASS** (`Ran 847 tests in 51.401s`, `OK`), native `V100_FULL_EXIT=0`. Test log SHA256: `792950783275c32ce33924319e4a6a896f1e14ea795687cfdfdad36bd12a75c9`; local location `$env:TEMP\V100_FULL_REGRESSION.txt`.
- The new V100 GitHub Windows/macOS/Ubuntu CI status must be verified separately after publication; no claim of remote CI success is made on the strength of laptop tests alone.
