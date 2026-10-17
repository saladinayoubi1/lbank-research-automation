# Elliott V63 — ETH first-leg child-pivot physical forensics (historical)

**Audit completed:** 2026-10-16 UTC. **Scope:** isolated Laptop2 research, Draft PR #2673, Bybit ETHUSDT Spot **2026-10-10** using the **previously inspected** and independently source-audited V45 1-minute archive. This is not prospective V52 scoring, not an executable entry or Paper/Demo result and not evidence of a profitable strategy.

## Objective and frozen method

V48 found one bounded bullish impulse + ABC *parent geometry* in the historical Oct08–12 BTC/ETH window; BTC had none. V49's 1-minute fixed-degree and V50's **15m/5 = 3m** deterministic child-degree checks both rejected this ETH parent because the first impulse leg showed **six** independently strict interior child extrema, versus **four** required by its fixed five-swing internal witness.

V63's one-shot reproduction `research/elliott_v63_historical_child_forensics/forensics_v63.py` **does not change any wave rules**. It reopened the SHA256-pinned physical ETH Parquet from V45, asserted exactly 7,200 consecutive UTC 1m candles between Oct08 inclusive and Oct13 exclusive, reread the frozen V48 nine-parent source-bound minute pivots, rebuilt 3m high/low, selected only strict width-one 3m pivots that map uniquely to strict width-three physical V49 1m pivots, and restricted the child interior to the first actual parent leg.

Original first parent low **2492.76 at 2026-10-10 08:45 UTC**, original next parent high **2498.71 at 09:31 UTC**, net parent price delta **+5.95 USD/ETH** (not any trade profit).

| First-leg interior sequence | Kind | ETH price (USD) | 1m center open UTC | Fully right-confirmed close UTC |
|---:|---|---:|---|---|
| 1 | High | 2496.32 | 08:53 | 08:57 |
| 2 | Low | 2495.33 | 09:02 | 09:06 |
| 3 | High | 2498.50 | 09:12 | 09:18 |
| 4 | Low | 2496.03 | 09:18 | 09:24 |
| 5 | High | 2497.78 | 09:22 | 09:27 |
| 6 | Low | 2496.65 | 09:27 | 09:33 |

All UTC timestamps are on **2026-10-10**. Each confirmation is the later of the 3m strict right-neighbor bar close and the 1m width-three source confirmation close; neither relies on incomplete future candles. The sixth interior low becomes structurally confirmed by **09:33 UTC**, after the next parent high's *center timestamp* but before that parent's strict 1m right-hand close **09:35 UTC**. This is permissible as pivot-center order (sixth center 09:27 precedes next high center 09:31) and does not validate execution time or market quote availability.

Consecutive endpoint-to-endpoint price changes (USD/ETH): `+3.56, -0.99, +3.17, -2.47, +1.75, -1.13, +2.06`. Minimum absolute adjacent swing amplitude **0.99 USD/ETH**. All six interior pivots alternate high/low, so V50's deterministic same-kind replacement cannot remove any; **raw count = selected count = 6**. A conventional 5-segment impulse subdivided by this fixed rule requires **4** interior changes. The price differences can be observed as real short-scale market reversals under these exact rules; this audit does **not** establish whether they represent another Elliott degree or profitable wave.

## Cross-validation and final disposition

- Physical V45 ETH 1m Parquet SHA256 `fbdad48b85ff5ada62c2e12e3321413fdf60ddf5b5655df68d5b60e98c1cdfcf` verified immediately before reconstruction.
- V48 original parent endpoint evidence and exact minute grid checked. The V63 independently reproduced count **6** and asserted equality with V50's `per_leg_raw=[6]` and `per_leg_selected=[6]`.
- **Fixed-degree decision:** `REJECT_DEGREE_COUNT_MISMATCH_6_VS_4`.
- No selective pivot deletion, no timeframe switch based on the inspected failure, no retrospective threshold tuning, no positive signal, no filled trade and no P/L.
- Physical receipt `E:\NEXUS-QA\elliott-v63-child-forensics-20261016\V63_FIRST_LEG_PHYSICAL_CHILD_FORENSICS.json`, SHA256 `51d742a3a487e1a416e79e8319df87b2a954075f77d4a455b43a5c67bbac1585`.
- Reproduction script is Laptop2-specific historical research with explicit pinned local paths and writes the receipt once, refusing any overwrite. **It is not part of the live runtime or prospective V52 score path**.

**Interpretation:** The observed rejection is due to the fixed candidate degree cardinality, not to two evidently duplicate or unconfirmed pivots. Removing the two "inconvenient" pivots would invalidate the predeclared source-only research method. A materially different hierarchical Elliott classifier would need a **separate, prospectively registered hypothesis and holdout** before evaluation; the frozen Oct18+ V52 protocol cannot be retuned in response to this historical sample.

**Safety:** Bybit only. Demo/Paper untouched, Live disabled, Laptop1 and VPS unchanged.
