# Elliott V65 — Falsification of a nested corrective-wave explanation

**Research date:** 2026-10-16 UTC. **Repository:** Draft PR #2673. **Scope:** isolated Bybit BTCUSDT/ETHUSDT historical research; no orders, quotes, fills, P/L, live or Demo changes. This is **post-hoc EXPLORATORY** work, not an independently predeclared V52 strategy.

## The question

V63's already-inspected physical ETH Spot history (2026-10-10, 08:45–09:31 UTC) contains a parent upward leg with **seven strictly alternating elementary price moves** and six verified interior 3m/1m extremal witnesses. The frozen V40/V50 child model demanded five moves / four interior pivots and therefore rejected it. A legitimate *hypothesis* worth separately falsifying is whether five higher-degree impulse legs could contain one three-elementary-segment downward A-B-C zigzag correction (either wave 2 or wave 4). Five top-level legs with one corrective leg replaced by three primitives yields seven elementary moves. This is a **new conditional grammar** developed after examining historical failures, not a rescue of V52's frozen 3m degree.

## Exactly two fixed partitions — no cherry picking

Represent observed eight consecutive alternating (low/high) vertices as indices `0...7`. Both, and only both, correction placements are evaluated:

| Alternative | Five-wave parent indices | Strict downward A-B-C correction indices |
|---|---|---|
| Corrective wave 2 subdivided | `[0,1,4,5,6,7]` | `[1,2,3,4]` |
| Corrective wave 4 subdivided | `[0,1,2,3,6,7]` | `[3,4,5,6]` |

The `research/elliott_v65_hierarchical_geometry/grammar_v65.py` function accepts all **eight** (not a hand-selected subset) strictly alternating chronologically ordered vertices. It invokes the existing V40 strict bullish non-diagonal `_price_geometry_5(...,1)` for the five parent wave endpoints and V40's downward `_price_geometry_3(...,-1)` for the nested zigzag. Only simultaneous success counts as a geometric match. Zero successes means rejection. Two successes are explicitly **ambiguous and fail-closed**, rather than selecting whichever variant fits past returns. One success still means *geometry only*, **not** recursive Elliott completion or trade eligibility.

**Deliberate limitation:** the V65 grammar is only a vertex geometry interpreter. It has **no independent file/timestamp/source SHA validation** and returns `source_authenticated=False`, `forward_validated=False`, `entry_signal=False`, `paper_eligible=False`, `live_enabled=False`. Historical V63 provenance can supply a previously checked example, but is not a substitute for a new source-bound prospective gate. It is not imported by the V53/V62 scanner, V52 or the product runtime.

## Previously inspected ETH candidate evaluated by both partitions

The actual eight historical vertices from V63, in USD/ETH, were:

`2492.76 → 2496.32 → 2495.33 → 2498.50 → 2496.03 → 2497.78 → 2496.65 → 2498.71`

Independent deterministic strict V40 geometry calculations on all eight vertices:

| Partition | Five-wave bullish parent | Strict bearish zigzag | Joint acceptance |
|---|---|---|---|
| Expanded correction 2 | **FAIL** | **FAIL** | **REJECT** |
| Expanded correction 4 | PASS | **FAIL** | **REJECT** |

For expanded fourth correction, the proposed bearish A-B-C sequence is `2498.50 → 2496.03 → 2497.78 → 2496.65`. Its C low `2496.65` fails to extend beyond A low `2496.03` under the strict V40 zigzag condition. **Do not change the zigzag rule to flatter this example.** Alternative flat, diagonal, or other complex corrective-wave grammars remain *unproven ideas*, not labels to attach after this observed rejection.

**Decision:** `NO_ADMISSIBLE_5_PLUS_ABC_GEOMETRY` for the historical ETH leg, **zero** admissible versions under this grammar. There is no newly validated Elliott wave or profit.

## Tests and operational status

Seven deterministic focused regression cases were authored in `research/elliott_v65_hierarchical_geometry/test_grammar_v65.py` and native discovery in `tests/test_nexus_elliott_v65_hierarchical.py`. They cover: inspected ETH rejection; one clearly valid synthetic expanded-wave-2 construction; one valid synthetic expanded-wave-4 construction; no dropping pivots; duplicate/out-of-order centers; wrong alternating kind; and read-only non-trading flags. The two positive synthetic constructions show the grammar is not hardwired to reject all waves.

The geometric outcomes above were separately recalculated independently of the Laptop2 test runner. **Important verification disclosure:** at V65 authoring time the remote shell/process start tool began rejecting commands; so the new tests were **not yet executed on Laptop2** before GitHub submission. CI at exact new branch HEAD must be checked before describing V65 as passing. Earlier V64 complete native **441/441** and prior V63 GitHub CI success remain valid only for those corresponding earlier commits.

**Frozen original:** V52 SHA256 `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4`, first two days 2026-10-16/17 warmup, future scored window Oct18 to Nov16 UTC exclusive, original 15m parent/3m child, unchanged. No change to any V52 protocol, user journals, laptop1 or VPS.

## Next gate

Obtain native/hosted test evidence for this exact new HEAD, then perform independent new-data (not Oct10) tests before deciding whether *any* alternative nested grammar warrants a separately preregistered prospective study. Never promote a geometrically convenient retrospective example into Demo or claim a filled long entry from raw daily OHLC archives.
