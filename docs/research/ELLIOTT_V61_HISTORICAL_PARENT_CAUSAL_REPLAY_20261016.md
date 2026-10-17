# Elliott V61 — Source-bound historical parent-pivot prefix replay

**Date:** 2026-10-16 UTC. **Scope:** retrospective research, 2026-10-08 00:00 through 2026-10-13 00:00 UTC, Bybit public Spot BTCUSDT/ETHUSDT. This is **previously inspected data**, neither untouched prospective holdout nor evidence of profitability. PR #2673 remains Draft. Laptop1 Demo, VPS and paper ledger unchanged; Live disabled.

## Question

Can the same-kind pivot-replacement rule or appending later 15-minute candles retroactively create a convincing 9-parent Elliott impulse+ABC pattern? V48's frozen historical scan produced no BTC geometries and one ETH geometry. V51 earlier confirmed only one ETH 9-parent sample with limited as-of snapshots. V61 independently replays **every single closed 15-minute decision step** for five historical source days, using actual SHA-pinned, independently trade-source-audited V45 1-minute files.

## Actual replay and source integrity

The isolated Laptop2 script `research/elliott_v61_parent_prefix_replay/replay_parent_v61.py` loaded frozen receipts V45 and V48, checked actual Parquet SHA-256 for both assets, verified **7,200 contiguous UTC 1-minute candles each**, reconstructed exactly **480 closed 15-minute candles per symbol**, and applied the original strict width-3 `_confirmed_pivot` at each successive completed 15-minute decision. For consecutive same-kind pivots, the script used the **same deterministic more-extreme replacement** as V53, without optimizing widths, geometry, P/L or order timing. It captured the **first observed** valid 9-parent geometry at each step, then independently compared the full-period 9-parent center lists and parent-count census against the frozen V48 receipt. The replay **raises if source hashes, counts or pattern centers differ**; all comparisons passed.

| Historical QA | BTCUSDT | ETHUSDT |
|---|---:|---:|
| Physical SHA-pinned V45 1-minute bars | 7,200 | 7,200 |
| Closed 15m decisions replayed | 480 | 480 |
| Final alternating accepted parent pivots | 76 | 79 |
| Deterministic same-kind replacements observed | 11 | 5 |
| Distinct geometry candidates ever first observed | 0 | 1 |
| Geometry candidates in frozen V48 full-period census | 0 | 1 |
| Differences from frozen V48 candidate centers | 0 | 0 |

The **one ETH historical parent geometry** has 15m center indices `[227,230,234,250,260,270,273,279,283]`. Its earliest *geometry-observable* closed-bar decision was **2026-10-10 23:45 UTC** after the 15m right-hand pivot confirmation. No BTC nine-parent geometry appeared. Every observed geometry was confirmed on time; later candles did not change the identity of this ETH parent candidate in the completed V48 period.

**Crucial limit:** the accepted ETH parent is a **geometric research-only candidate**. V49/V50's independent strict 1m/3m child wave cardinality checks previously rejected its first leg: required four internal child extrema, observed six. Thus **zero full bounded one-child-degree wave proofs**, zero new entries, fills, profitable outcomes, hypothetical P/L additions or Paper promotion follow from this new replay. Full recursively complete Elliott remains unproven. The 23:45 UTC confirmation was a **historical bar-observation time**, NOT proof an official daily trade archive could be downloaded or a trade executed then. V60's post-publication physical availability rule still blocks any retrospective real-time inference.

## Reproducibility and receipt

Original physical SHA-256 V45 BTC Parquet: `85cac2a559b6bc1294dc9750ee621e645c90eb7625d267a5940476f5fe5f19c7`.

Original physical SHA-256 V45 ETH Parquet: `fbdad48b85ff5ada62c2e12e3321413fdf60ddf5b5655df68d5b60e98c1cdfcf`.

Local immutable execution receipt: `E:\NEXUS-QA\elliott-v61-parent-replay-20261016\V61_REAL_HISTORY_CAUSAL_REPLAY.json`. SHA-256 `82c91d981538d2ef68e0a21eea492f9237a779f3211be97273e82cb997706435`.

`replay_parent_v61.py` is a **Laptop2-specific, one-shot reproducibility script** with explicit receipt/file paths; it is not imported into product runtime, CI or the frozen V52 prospective scoring module and refuses to overwrite the receipt. No trading code or Demo binary is modified.

## Next scientific implication

Do **not** treat the stable historical parent as a profitable wave. The known blocker remains first-leg child-degree oversegmentation: V49 and V50 both found six alternating strict interior extrema where V40 requires four. It is inappropriate to skip inconvenient pivots or cherry-pick a new timeframe after observing the failure. Evaluate a preregistered *new* degree hierarchy only in fresh, real, source-authenticated future evidence and keep outcome reporting strictly structural until independent quote/execution accounting exists. The forward source-day gate remains UTC Oct18+ only; Oct16–17 are unscored warm-up.
