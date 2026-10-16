# Elliott V66 — Physical 1m/3m/15m Source Reattestation and Causal Parent Timing

**Date:** 2026-10-16 UTC. **Scope:** Bybit Spot ETHUSDT, previously inspected 2026-10-08 through 2026-10-12 UTC official-trade-derived 1m source; Draft PR #2673. **Research only**; no entry, fill, paper order, P/L, Live, or deployment changes. Original frozen V52 15m/3m prospective configuration is unchanged.

## Question answered

V65 interpreted eight vertex prices of the October 10 ETH first leg as a five-wave impulse with one nested three-part A-B-C correction at either wave 2 or 4. V65 was deliberately **vertex geometry only**: it never authenticated those vertices against the real physical data or calculated when each full 15-minute parent pivot actually became knowable.

V66's `research/elliott_v66_source_bound_hierarchy/witness_v66.py` adds an independently verifiable **retrospective physical witness**, accepting only the known hash-pinned V45 Parquet (SHA256 `fbdad48b85ff5ada62c2e12e3321413fdf60ddf5b5655df68d5b60e98c1cdfcf`) and V63 immutable physical child report (SHA256 `51d742a3a487e1a416e79e8319df87b2a954075f77d4a455b43a5c67bbac1585`). The CLI explicitly requires `--source`, `--receipt`, `--output`, and refuses to overwrite its output.

The verifier separately checks:
- All **7,200** 1m source minutes from October 8 inclusive to October 13 exclusive, complete exact UTC grids, valid OHLC and source hashes.
- **Eight** strictly alternating 1m high/low vertices, with exact decimal source price, center-open time and width-three right-hand 1m confirmation.
- All **six** interior vertices are unique physical width-one strict 3m pivot extrema, matching V63 recorded 1m/3m right-confirmation closes exactly. Neither arbitrary pivot deletion nor shifting by one minute is permitted.
- Both endpoint pivots are independently proven strict width-three **15m parent pivots** on reaggregated physical source data, not merely on one-minute extrema.
- The already-published V65 strict five-parent-wave + either-wave-2-or-4 downward zigzag grammar is applied *without changing or deleting any vertices*.

## Evidence and timing finding

**Real historical source-bound pivot census:** 8/8 1m vertices valid, 6/6 interior vertices valid at the fixed 3m scale, and 2/2 bounding parents valid at 15m. This is *historical authenticity of vertex points*, NOT proof that any full Elliott wave was accepted.

| Observation on Oct 10 UTC | Earliest completed-bar information time |
|---|---|
| Earliest parent 15m low (center around 08:45) fully right-confirmed | **09:45 UTC** |
| Last interior 3m child low fully right-confirmed | **09:33 UTC** |
| Parent 15m high (1m center around 09:31) fully right-confirmed | **10:30 UTC** |
| Earliest time all these pivots jointly could have been structurally known from complete bars | **10:30 UTC** |

The high's observed *minute center* at 09:31 UTC is not a legally confirmed 15m swing high then. The 15m width-three strict pivot requires three completed **following 15m candles**, so using 09:31 as a structurally validated entry time would be **look-ahead**. Even 10:30 is **not** proof a public daily archive, real-time market quote, exchange connectivity or executable fill was available then. Official public daily archives were available only after their historical day closes; this source is later-obtained retrospective data.

**Independent V65 grammar on authenticated vertices:**

| Partition | Five bullish parent legs | Nested bearish A-B-C | Accepted? |
|---|---|---|---|
| wave 2 subdivided | FAIL | FAIL | NO |
| wave 4 subdivided | PASS | FAIL | NO |

No hierarchical Elliott proof, new P/L or Demo eligibility. `geometry_state=NO_ADMISSIBLE_5_PLUS_ABC_GEOMETRY`. The cause of the wave-four alternative rejection remains the observed C low 2496.65 not extending beyond A low 2496.03. We did not redefine zigzag or remove any of the six interior pivots.

## Reproduction and mutation evidence

Isolated Laptop2 path `E:\NEXUS-QA\elliott-v66-hierarchy-source-witness-20261016\V66_SOURCE_BOUND_HIERARCHY.json`. Exact SHA256 **`c97e468c20a37fa3d6c0aa2e17bc82ac57076576001e2e179bb0f9277e6359e0`**. One-shot run printed `PASS_HISTORICAL_PHYSICAL_WITNESSES_ONLY`, exit code **0**. Four tampered reports (one interior price, one child confirmation timestamp, one endpoint price, one backdated parent-center timestamp) were all rejected by independent source/candle checks **even after bypassing the outer receipt-file hash in the test harness**.

Nine separate synthetic fail-closed regression tests passed locally before publication: fabricated flat-source pivots denied; wrong source lineage; missing minute bar; duplicate minute UTC stamp; broken OHLC bound; missing child pivot; forged report schema; naive timestamps; and no trade-permission flags. `research/elliott_v66_source_bound_hierarchy/test_witness_v66.py` and `tests/test_nexus_elliott_v66_source_bound_hierarchy.py` enroll the new checks in the native/hosted suite.

## Protocol and deployment boundaries

- **V52 protocol canonical SHA256:** `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4`, forward-score starts 2026-10-18 UTC (first two days Oct 16–17 are source/warmup only), ends Nov16 UTC exclusive. V66 neither changes V52 nor enters the prospective scorer.
- No exchanges except Bybit research data, no Live enablement, no paper journal edits, no Laptop1 installation changes, no VPS changes. Repo changes are Draft PR research modules, tests and documentation only.
- **Next step:** check the exact V66 head full native test suite and hosted Windows/macOS/Ubuntu CI. Use future truly unseen **physically complete archived** Bybit Spot days under V52's independent source and observability gates when available; do not hallucinate daily archives before publication or count historical OHLC-derived highs as filled trades.
