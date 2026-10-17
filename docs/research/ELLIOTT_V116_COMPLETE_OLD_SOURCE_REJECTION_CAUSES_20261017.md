# NEXUS Elliott V116 — source-locked necessary-screen rejection taxonomy

**Research-only. No real orders, trading P/L, certified Elliott waves, threshold changes or Demo promotion.** This audit explains why the unchanged V106/V107 Wave1–2 necessary grammar rejects most six-consecutive-coarse-pivot windows in an already inspected July 2024 Binance Spot dataset. It does not show that rejected windows were market losers or that relaxing criteria would be profitable.

## Original source / immutability

- Canonical repository: `saladinayoubi1/lbank-research-automation`; branch `codex/elliott-causal-quality-research-20261015`; Draft PR **#2673**, unmerged.
- Parent V115 commit `b33faed4036f6bf0f5b10887333233ee49d3beb9`. Frozen upstream V115 rulebook SHA256: `5f4947ff76bcb4888e0591940fb1346906a3808d9c804f84f4ea08043b74332a`. Published measured V115 evidence SHA256: `0889548b2b4e713e618115345e76e467f7114a8f2ed762083bf208d2f099a1e9`; both validated before source-event reenactment.
- Preinspected historical **Binance Spot** BTCUSDT and ETHUSDT closed one-minute data, 2024-07-01 UTC through 2024-07-15 exclusive: **28 original daily ZIPs and official checksum receipts**, **20,160 minutes per symbol**, **40,320 total**. Reparsed physical source and V99 fine/coarse event digests must reproduce V115 per-symbol hashes. Neither a Bybit source nor an independent forward holdout.
- Original V106 and V107 are unchanged. The prior trend must satisfy strict geometry, Wave2 must not touch/breach Wave0, and original Wave1 and Wave2 require *exactly four and two* unpruned fine pivots respectively. All originally rejected windows remain in the denominator. No posthoc optimization, filtering, exclusion, prediction-precision claim or complete Elliott certificate.
- V116 source: `research/elliott_v116_failure_taxonomy/taxonomy_v116.py`. Tests: `tests/test_nexus_elliott_v116_failure_taxonomy.py`. Frozen rules: `docs/evidence/elliott-v116-rejection-taxonomy-20261017/V116_FROZEN_REJECTION_CAUSES_RULEBOOK.json`, SHA256 `0dab31a3f68086ae7c31fe880eae1543db081312afb03cb32c8b562ebf71bbe7`. Measured historical causes: `docs/evidence/elliott-v116-rejection-taxonomy-20261017/V116_MEASURED_OLD_BINANCE_REJECTION_TAXONOMY.json`, SHA256 `2b0cc31b788510c58425635cf3bdfff391f6e2a5fc9ab437c25debac1c9d70e3`.

## Exhaustive original census

| Original six-pivot window | BTCUSDT | ETHUSDT | Combined |
|---|---:|---:|---:|
| All original windows | 604 | 608 | **1,212** |
| Pass V106 necessary Wave1/2 screen (not trade) | 4 | 5 | **9** |
| Rejected by original necessary Wave1/2 screen | 600 | 603 | **1,203** |
| Original full Elliott degree certificates | 0 | 0 | **0** |

### First rejection reason (mutually exclusive, in original fixed evaluation order)

| Original first failure code | BTC | ETH | Total |
|---|---:|---:|---:|
| `PRIOR_TREND_LOWER_HIGH_NOT_ATTESTED` | 282 | 281 | **563** |
| `PRIOR_TREND_LOWER_LOW_NOT_ATTESTED` | 132 | 129 | **261** |
| `WAVE1_UNPRUNED_FINE_COUNT_NOT_PREDECLARED` | 92 | 85 | **177** |
| `WAVE2_BREACHES_OR_TOUCHES_WAVE0_ORIGIN` | 77 | 93 | **170** |
| `WAVE2_UNPRUNED_FINE_COUNT_NOT_PREDECLARED` | 17 | 15 | **32** |
| **All first-failure-only windows** | **600** | **603** | **1,203** |

The first failure is **determined by the order of original tests**, not a unique attribution of causation. A later unexamined-looking failure may also be present in the same candidate.

### Any failure in each fixed group (overlapping counts)

| Group, counted once per rejected window | BTC | ETH | Combined |
|---|---:|---:|---:|
| **Exact fine-pivot counts (Wave1=4, Wave2=2)** | 576 | 583 | **1,159** |
| **Prior trend context/geometry** | 414 | 410 | **824** |
| **Wave price geometry, including Wave2 origin breach** | 281 | 283 | **564** |
| **Causal coarse/fine pivot-boundary mismatches** | 6 | 6 | **12** |

**Caution:** groups overlap; their sum is **not** the 1,203 source denominator. The 1,159 indicates that 1,159 rejected windows also failed *at least one* exact fine-count constraint, but does not mean every one of those windows would otherwise have passed. Fine-count failures at the individual reason level are Wave1 **1,015** and Wave2 **905**, whose overlap makes the per-group unique count 1,159. Strict Wave2 origin breach was observed in **564** rejected windows. Causal boundary mismatches appear in **12**, overlapping other criteria; that rarity alone cannot validate Elliott degrees.

## Interpretation, controls and scientific limits

The **largest descriptive failure category** is the locked exact 4+2 fine pivot count. The next major constraint is prior trend context. This is a **methodological clue** for future predeclared, independently evaluated research—**not permission to relax either rule on the July 2024 data**, and not proof that an alternate grammar improves entry/exit quality, net returns or signal precision. Nine necessary passes are not nine proved five-wave impulses and are not economic trades.

V115's separate source-to-cash bridge classified these nine pass windows further as **four bullish hypothetical reference proposals**, **four bearish Spot-short abstentions**, and **one bullish first-two-minute barrier abstention**. Thus the number four in V115 is a later hypothetical cash-reference screen, whereas nine in V116 is the earlier necessary structural screen; they must not be conflated.

Every candidate's original ordinal, its closed-time decision cutoff, locked coarse SHA, predecision fine SHA, all fixed failure codes and original pass flag contribute to a no-price individual-row evidence digest. The V107 source totals (both first-reason and overlapping reason counts) are compared against V116 reconstruction. Synthetic adversarial tests reject missing/reordered candidates, duplicate/unknown failure codes, changed pass flags, fabricated Elliott certification and modified original source summaries.

The entire frozen **future Bybit public Spot period, 2026-11-16 through 2026-11-30 UTC exclusive**, remains untouched and unobserved today. This descriptive audit only uses already examined Binance historical bars. There are **zero actual Bybit fills, no trade win rate, no net P/L and no order adapters**. Laptop1's V52 protected installation, both laptops' Demo configuration, user journals and GitHub draft status remain unchanged. The correct next research gate is a separately predeclared comparison tested on genuinely untouched data after the period concludes, with realistic broker fees, spreads, source provenance and cash overlap accounting—never an ex-post reclassification of old winners.

## Verified V116 local QA and research delivery

- **15/15 dedicated adversarial unit tests PASS**, `V116_UNIT_EXIT=0`, on Laptop2. The full Elliott suite was re-executed after adding immutable V115 measured-file source SHA validation and concluded **1166/1166 PASS**, `Ran 1166 tests in 65.587s`, `OK`, `V116_FINAL_FULL_EXIT=0`. Windows TEMP log `V116_FULL_ELLIOTT_REGRESSION.txt` SHA256: `7febb2f329776f8764d50d54793d5df79ae1f52752ccd925f761484f8c4a4d8b`.
- The original two-symbol V116 historical replay completed with **1,212 original windows / 9 necessary passes**, `V116_OLD_SOURCE_EXIT=0`, original measured-output SHA256 `2b0cc31b788510c58425635cf3bdfff391f6e2a5fc9ab437c25debac1c9d70e3`. It did not measure actual Bybit market profit. The frozen taxonomy contract SHA256 is `0dab31a3f68086ae7c31fe880eae1543db081312afb03cb32c8b562ebf71bbe7`.
- Parent V115 GitHub remote commit `b33faed4036f6bf0f5b10887333233ee49d3beb9` had **Test**, **Research Evidence Refresh**, and **Workflow Permissions Policy** all **SUCCESS**, Draft PR #2673 unmerged. V116 remote CI must be separately checked after push.
