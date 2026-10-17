# Elliott V60 — Archive observation latency and false-real-time prevention

**Research timestamp:** 2026-10-16 UTC. **Repository:** Draft PR #2673. **Devices:** research Laptop2 only. **Trading:** Live permanently disabled; no automated Demo, orders, or new P/L.

## Problem found

V52–V59 enforce a frozen causal candle/pivot definition and strong local source provenance. However, the raw daily trade archive used to reconstruct the candles can only be captured **after** the complete UTC source day has closed, and its actual publication/receipt may be later. A structural Elliott candidate whose confirming parent pivot completed at time T is not necessarily one that NEXUS could have known at time T.

Specifically, the V59 two-day mocked physical evidence fixture stamped each physical TLS archive capture at **2026-10-18 00:02 UTC**, two minutes after its nominal Oct18 00:00 daily decision. V55's test-run minute receipt, however, was timestamped with the host's current actual time on Oct16, **before** the mocked future capture. This is an impossible artifact chronology in the synthetic fixture, which V59 previously did not diagnose. Neither condition means a genuine market signal existed.

## Read-only V60 source observability gate

Added `research/elliott_v60_observability/observability_v60.py` as a separate post-V59 analysis. It requires a verified V59 result, exact physical V58/V55 receipt names and byte hashes tied to that result, and timezone-aware timestamp evidence for every verified source day. It recomputes:

- Latest recorded physical TLS archive capture timestamp.
- Latest recorded completed 1m minute-source evidence receipt creation timestamp.
- Earliest physical availability bound as **max(TLS capture, minute evidence creation)**.
- Signed seconds from nominal daily decision to physically available source evidence.
- Timestamp consistency: independent 1m evidence must not exist *before* its underlying captured original raw file.
- Non-executable classification: `INVALID_EVIDENCE_STAGE_CHRONOLOGY`, `RETROSPECTIVE_ARCHIVE_AVAILABLE_AFTER_DECISION`, or `PHYSICAL_SOURCE_AVAILABLE_BY_DECISION_ONLY`.

**Important:** Even `PHYSICAL_SOURCE_AVAILABLE_BY_DECISION_ONLY` is strictly a *data-source timing* observation. It does not establish that historical bars were received as live ticks, that quoted bid/ask were available, that orders could be filled, or that a profitable entry existed. V60 explicitly sets `executable_quote_proof=false` and `publication_time_known=false`. The first publish time at Bybit cannot be inferred from a download timestamp; the bound represents this system's own observed arrival, not Bybit's first publication.

The protected V52 wave cardinalities, 15m parent, 3m child, 1m provenance and holdout start **Oct18 00:00 UTC** remain completely unchanged. Historical market evidence inspected before the freeze cannot retroactively become untouched prospective proof.

## Verified adversarial tests

**9/9 isolated V60 regressions PASS** on Laptop2. Full physical V59 mock capture and V55/V52/V57 reaggregation chain underpins the tests. Cases check impossible minute-before-capture timeline, post-decision receipt lag (**+180 seconds** in a corrected synthetic fixture), forged receipt modifications after V59 attestation, receipt disappearance/swaps, missing/naive timestamps, exactly-at-decision data-only availability and a source captured before its own UTC day ends (rejected by V59). No real forward-day market archive was downloaded or admitted.

Isolated evidence: `E:\NEXUS-QA\elliott-v60-observability-20261016\V60_STANDALONE_9_TESTS.txt` (9 tests, exit 0). Native discovery via `tests/test_nexus_elliott_v60_observability.py`.

## Original CI run status

The previous V59 GitHub hosted Test workflow had a single Windows-only `WinError 10053` connection abort in **product AI Advisory HTTP** (1 failed, 4407 passed, 20 skipped; Ubuntu and macOS passed). GitHub rerun of that particular Windows job subsequently returned **success**, with no changes needed to Elliott code. This should be classified as a transient Windows test failure, not evidence of a successful original run or a discovered Elliott defect.

## Next scientific gate

For any true upcoming daily source archive, insist on V58 TLS capture + V55 physical minute build + V52 independent oracle + V59 physical chain, then always add V60's actual availability/chronology label before reporting timing-dependent Elliott outcomes. **Never use a later-downloaded daily archive to claim an actionable signal at its earlier candle close**. Genuine future observations and executable quotes require a separate streaming evidence mechanism and do not arise from the daily archive alone.

Live disabled; Demo, Paper journals, Laptop1 and the paused VPS unchanged.
