# NEXUS Elliott V69 — End-to-end physical source arrival time gate

**Date:** 2026-10-16 UTC. **Scope:** Bybit Spot BTCUSDT/ETHUSDT, research-only Draft PR #2673. No demo/paper installation, live orders, entry/exit signals, fills or new P/L.

## Scientific problem

The strict right-hand 15m parent pivot can be *geometrically knowable from completed bars* at a certain UTC close. The public daily trade archive used to reconstruct those bars cannot be known or retrieved before the end of its respective source day, and may only be physically received and verified later. V60 already computes archive receipt availability lag, but a separate V53/V57 scanner report could be wrongly presented as an **as-of score** unless the associated V59/TLS and V60 source-stage chronology are checked together.

## V69 gate — fail-closed and not an entry strategy

`research/elliott_v69_source_asof_gate/source_asof_v69.py` provides `audit_scanned_daily_source_availability`. It deliberately does **not** change the V52/V53 scoring algorithm. It performs, in order:

1. Recheck the frozen V52 protocol.
2. Invoke V59 `scan_tls_bound_physical_source` from supplied physical V58 TLS and V56 minute-intake receipt file paths. V59 independently reopens and rehashes original source gzip and minute Parquet through V57/V52, reruns the V53 bounded Elliott *research* scanner, and checks recorded source/TLS identity. The TLS-origin claim remains local/forgeable, not exchange-signed.
3. Invoke V60 `audit_source_observability` on those same receipt files and V59's exact fingerprints, check ordered receipt counts, date and source-stage coherence.
4. Reconcile exact symbol, day count and UTC decision of V59, V57, V53 and V60. If evidence stages are contradictory, label `BLOCK_INVALID_SOURCE_STAGE_CHRONOLOGY`. If archive or minute source was ready only *after* the claimed scoring decision, label `BLOCK_RETROSPECTIVE_SOURCE_ARRIVED_AFTER_DECISION`. If timely but synthetic, label `SYNTHETIC_SOURCE_ONLY_NO_REAL_SCORE`. Only independently reverified **real** source physically accessible at/before decision gets `PHYSICAL_SOURCE_READY_BY_DECISION_RESEARCH_ONLY`, which still **never authorizes trading or proves market quotes**.

For every outcome `entry_signal=false`, `exit_signal=false`, `paper_eligible=false`, `live_enabled=false`, `fill_confirmed=false`, `pnl=null`. Synthetic mode can never set `research_asof_reporting_eligible=true`. Real mode forbids injected wall-clock time. There is no background scheduler, source capture, exchange order, paper position or candidate promotion in V69.

## Synthetic source fixtures and test obligations

V69's native `tests/test_nexus_elliott_v69_source_asof.py` imports the five focused cases from `research/elliott_v69_source_asof_gate/test_source_asof_v69.py`. These use V59's **physical two-day gzip/Parquet synthetic fixture under OS temporary files**, with a mocked TLS transport, not actual Bybit trades:

- Invalid stage order → block report.
- Archive minute receipt 180 seconds after UTC decision → block as retrospective.
- Capture and receipt completed exactly at UTC boundary → synthetic only, not real-world score or exchange provenance.
- Invalid recorded HTTP status → V59 rejects physical chain before V60 scoring label.
- Synthetic receipt falsely represented as production using injected wall clock → reject.

**Verification disclosure:** the first local test-launch command failed before importing tests because the temporary PowerShell `PYTHONPATH` was incorrectly constructed. One corrected retry attempt was blocked by the remote tooling; **neither was a code-regression failure and the authored V69 tests have not yet been proven locally successful**. Exact GitHub HEAD hosted CI must run before calling V69 tests green. V68's prior Windows/macOS/Ubuntu CI and 478/478 native tests were independently verified at earlier SHA `604bee71f5e5b005698d67f11af8ad696bd328ac`; that does not by itself verify this new commit.

## Frozen study boundaries

The original immutable V52 protocol SHA256 `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4` specifies source 2026-10-16 onward, warmup Oct16–17, scored period **Oct18–Nov16 UTC end-exclusive**, and original 15m parent/3m child. At today's Oct16 UTC the **first complete daily Oct16 archive cannot yet have arrived**. Do not assign any real V52 future score or infer contemporaneous entries on Oct16 from a later downloaded daily archive. Archived proof only supports retrospective bounded geometry research.

No differences to V52, existing demo/Paper systems, laptop1 runtime, journal, or paused VPS.
