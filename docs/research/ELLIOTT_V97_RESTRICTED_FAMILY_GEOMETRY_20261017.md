# NEXUS Elliott V97 — independent restricted Impulse / Zigzag / Flat geometry

**Scope:** additive read-only research on an ALREADY INSPECTED historical universe. New *post-hoc diagnostics*, not preregistered performance evidence, a recursive wave certificate, a paper signal or economic backtest. PR #2673 Draft/unmerged, Bybit Demo/Paper only in any future deployment, Live disabled, V52 Oct 18–Nov 15 prospective holdout untouched. No laptop installation changed.

## Source integrity and design

V97 verifies source ancestry and exact Git bytes for V96 (commit `c633fffd6daccfa6b56e5227bfbc16198a30b3f1`; SHA256 `cfc29e8ed2cac611ffb09d0bf9847894dc4e935daacc2d6ae4c379c8dda78a01`), unchanged V90 candidate receipt, and V89 official ZIP/CHECKSUM archives locked before collection by V88. All **40,320 Binance Spot 1m historical observations** are reloaded on Laptop2. V82 source witnesses, V90 original 490 parent intervals and exact original candidate ordering/decision timestamps are checked. 8 previously identified five-leg Impulse and 23 previously identified three-leg correction candidates are examined, **without retroactively adding, dropping, relabeling or selecting pivots**.

The new `research/elliott_v97_family_geometry/family_v97.py` independently checks source-bound price vertices, right-confirmation timestamps, 1m physical wick values, original interval ordering, positive directed movement and conservative per-leg physical high/low envelopes.

Three **explicitly restricted geometry definitions**, not universal Elliott grammar:

- **Impulse:** conventional, non-diagonal, non-truncated 5-leg outer price geometry; Wave 2 cannot violate origin; Wave 3 beyond Wave 1; Wave 4 does not overlap Wave 1; Wave 5 extends beyond Wave 3; Wave 3 is not the shortest positive motive leg. Cross-checked against V83's earlier necessary hard geometry as a source-regression invariant.
- **Zigzag:** restricted A-B-C outer geometry: Wave B reverses A but does not cross A's start, and C passes A's endpoint; all price extrema sourced to fully closed original 1m wicks. Merely passing this price geometry says **nothing** about internal 5-3-5.
- **Flat:** restricted regular/expanded subset: Wave B retraces at least 90% of A, and C passes A's endpoint; all prices and candles sourced. The 90% condition is a clearly disclosed classical subset boundary, **not optimized from July** and it excludes other corrective possibilities. Merely passing it says **nothing** about internal 3-3-5.

If both Zigzag and Flat restricted geometry pass, the case is **AMBIGUOUS_FAMILIES_NO_SELECTION**; V97 never chooses a favorable family.

## Actual old-July diagnostic outcome (NOT performance)

| Source hypothesis | BTCUSDT | ETHUSDT | Combined |
|---|---:|---:|---:|
| Original 5-leg impulse candidate intervals | 6 | 2 | **8** |
| Conventional impulse necessary outer geometry pass | **1** | 0 | **1** |
| Original 3-leg correction candidate intervals | 9 | 14 | **23** |
| Restricted Zigzag **outer** price geometry passes | **7** | **12** | **19** |
| Restricted Flat **outer** price geometry passes | 0 | **1** | **1** |
| Correction candidates matching both outer geometry subsets | 0 | **1** | **1** |
| Fully proven recursive Impulse/Zigzag/Flat | **0** | **0** | **0** |
| Certified entries, Demo positions, costed historical trades | 0 | 0 | **0** |

These subsets overlap: one ETH correction satisfies *both* outer price tests. Thus there are **19 distinct correction cases** with at least one restricted outer geometry pass, not 20 distinct certified patterns. V87 fixed-width source-replay had already found **no full 5-3-5 Zigzag or 3-3-5 Flat subwave certificates**, and V96 had found **no complete fixed-degree Impulse witness**. V97 changes neither finding. A source-valid outer zigzag-like contour is **not** a Zigzag pattern proof, trading signal or positive P/L.

## QA correction found and preserved

Initial local V97 run had the Wave-C outer-extreme comparison reversed in both correction-family implementations. Synthetic tests correctly failed five cases, identifying the bug *before any publication or trading use*. That first output was explicitly marked **INVALID**, retained **locally only** at `$env:TEMP\nexus-elliott-v97-research\V97_INVALID_FIRST_RUN_C_DIRECTION.json` with SHA256 `f2e719262b3049b838ff26988260da083b2aaf1f7bf54b3c1877199e3bf27e63`. The two comparison operators were corrected and 21/21 dedicated tests passed. A new corrected and separately SHA-pinned report was generated: `docs/evidence/elliott-v97-restricted-family-geometry-20261017/V97_FAMILY_GEOMETRY_DIAGNOSTIC.json`, SHA256 `672af410f645ca9e9430558dace50a1c3476a2ed62c97235b6c76f1de3320fcb`. The invalid earlier output is not the published source of claims.

## Remaining scientific and deployment gates

All results are constrained by a **previously inspected** July 2024 cohort. Do not use this dataset to choose a family for trading, measure expectancy, or move any July-discovered variant into Demo. V97 has no executable entry trigger, no stop/target, no Bybit fee/spread/slippage evidence, no order adapter and **no profit number**. Higher-degree recursion, certified wave-degree relationships, C/A internal grammar, beginning-of-pattern context, alternative wave families, robust lookahead-free price detection and realistic execution remain independently unproven.

**Next independent research:** freeze a fully source-backed degree-1 A/B/C wave geometry validator for Zigzag and Flat, including a separately predeclared lower-degree witness model and explicit ambiguous-case abstentions. After a valid coherent classifier exists, test only on genuinely untouched data and impose Bybit-compatible costs and Demo admission gates. Live never enabled.

## Verified test outcome

- Synthetic V97 price, timestamp, wick-envelope and family-ambiguity tests: **21/21 PASS**. These include up/down conventional Impulse, Wave-3 shortest, Wave-4 overlap, Zigzag A/B/C, Flat B 90% retracement, simultaneous family-fit abstention, source price tampering, future confirmation, source gaps and an invalid pre-fix Wave-C comparison.
- Complete Laptop2 Elliott regression: **791/791 PASS**, `Ran 791 tests in 50.703s`, `OK`, native `V97_FULL_EXIT=0`. Log SHA256 `83e061f81997b378b7a95aecbdb460a1e4060627ea4d339429a02e4e0ab0958b`, locally at `E:\NEXUS-QA\elliott-v96-degree-bridge-20261017\V97_FULL_REGRESSION.txt`.
- Corrected historical evidence SHA256 `672af410f645ca9e9430558dace50a1c3476a2ed62c97235b6c76f1de3320fcb`. Invariant: **only 31 previously seen source hypotheses were reviewed; none was retroactively promoted as a full Elliott count or executable trade**.
- GitHub CI for the new V97 commit is a separate remote gate; no success is claimed before it runs.
