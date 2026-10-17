# Elliott V44 — causal 15m parent pivot origin verified against 1m source

**Research date:** 2026-10-16. **Runner:** Laptop2 `DESKTOP-F4SA4VL`. **Branch:** Draft PR #2673, research-only. No automatic strategy registration, no Demo/Live authority and no Paper/VPS changes.

## Scope and source boundary

This is a bounded forensic review over **2026-10-13 through 2026-10-14 UTC** for BTCUSDT and ETHUSDT Bybit public Spot. It uses the V33 independent 15m source and the V41b independently V43-audited minute-OPEN source. The V42 SHA-bound as-of loader ensures that, at the decision time `2026-10-15T00:00:00Z`, only fully completed 1m bars are accessible.

Using the **unchanged width-3 strict local 15m pivot** rule, each accepted 15m high/low was mapped to the actual one-minute source bar inside its original 15-minute interval. An admitted mapping requires (a) exactly one minute with the same observed price, (b) strict non-tied/non-double extrema versus the 3 minutes either side, (c) 1m confirmation that occurred before the decision, and (d) preserved 15m confirmation timing. Ambiguous or unsupported mappings are explicitly rejected.

| Fixed, untuned evidence | BTCUSDT | ETHUSDT |
|---|---:|---:|
| Accepted 15m parent pivots | 25 | 32 |
| Unambiguously source-bound strict 1m pivots | 23 | 28 |
| Ambiguous minute extrema | 1 | 4 |
| Not strict / dual 1m extremum | 1 | 0 |
| Nine alternating accepted 15m parent anchor groups | 9 | 12 |
| Groups meeting this V40 bounded impulse and zigzag ABC parent geometry | **0** | **0** |
| Independently verified complete child subwave witnesses | **0** | **0** |

All accepted 15m pivots were accounted for in the mutually exclusive origin classification, with 25/25 and 32/32 reconciled. The mapped pivots do **not** prove a full recursive Elliott count; zero parent geometry matches in this sample does **not** prove there are no valid Elliott patterns in another market interval.

## Audited local receipt

`E:\NEXUS-QA\elliott-v44-parent-minute-origin-20261016\PARENT_MINUTE_ORIGIN_QA.json`  
SHA-256: `0b5e3a016e8efff1a5b73c9825b144ce63ada0b8a2c35976a8328831c5f286c7`

The audit script `parent_origin_qa.py` and JSON remain on the research laptop. This GitHub page is a finding/provenance index, **not** a claim that raw local receipts were uploaded as repository assets.

## Next safe gate

A full 1m child-wave proposal is still absent. Build candidate generation only once the parent anchors can be independently and prospectively established from enough completed multi-timeframe context. Derive children from **source-verified** minute pivots, not from retrospective hand-labelled wave structure; invoke V40 as a strict checker, and reject ambiguous, overlapped, future-confirmed or missing ABC subdivisions. Use a predeclared fixed protocol on unseen data for economic inference.

**Current admission state:** `entry_signal=false`, `paper_eligible=false`, `auto_demo=false`, `live_enabled=false`, `new_pnl=null`.
