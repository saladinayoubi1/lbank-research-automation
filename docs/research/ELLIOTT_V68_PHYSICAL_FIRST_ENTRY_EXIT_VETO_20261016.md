# Elliott V68 — Physical-first retrospective entry/exit veto

**Date:** 2026-10-16 UTC. **Scope:** Draft PR #2673; isolated Laptop2 research, Bybit Spot ETHUSDT previously inspected Oct08–12, 2026. No orders, demo changes, live execution, filled trades or P/L.

## Problem and fix

The V67 historical Elliott backdating gate correctly rejects unconfirmed-wave timestamps, but consumes a metadata-shaped V66 report. It has **no ability to authenticate that dictionary against the physical source**. V68 addresses that *integration* gap only, without changing the V52 frozen protocol, wave-count criteria or retrospective wave rejection.

The standalone `research/elliott_v68_physical_first_veto/physical_veto_v68.py` calls V66 `audit_files(source,receipt)` **before** evaluating an entry or exit. That function independently hashes the previously attested V45 physical ETH minute Parquet and the V63 child witness receipt, reconstitutes 1m/3m/15m source-pinned strictly right-confirmed pivots, and checks the V65 nested-wave geometry. V68 requires **7,200** consecutive completed minutes, **8** confirmed 1m vertices, **6** verified 3m child pivots and **2** confirmed 15m bounding parents. Only after those file-level checks does V68 build V67 metadata for `audit_retrospective_claim`.

V68 never authorizes an order, entry or exit. The API returns `entry_signal=false`, `exit_signal=false`, `paper_eligible=false`, `live_enabled=false`, `fill_confirmed=false`, and `pnl=null`; archive timestamps and historical OHLC extrema never demonstrate public intraday archive availability or executable bid/ask quotes. It is not a second raw-gzip trade aggregation oracle; that earlier source lineage was established in V45/V46. V68 is not connected to the V52 prospectively scored scanner.

## Physical historical replays on Laptop2

All three historical entry claims were independently reattested against the hash-pinned real V45 source and original V63 receipt before the V67 time gate. UTC times:

| Hypothetical claimed entry | Hypothetical claimed exit | Final veto |
|---|---|---|
| Oct 10 09:31 | Oct 10 10:00 | `REJECT_BACKDATED_BEFORE_PARENT_RIGHT_CONFIRMATION` |
| Oct 10 10:30 | Oct 11 10:00 | `REJECT_UNFINISHED_HISTORICAL_ARCHIVE_AS_INTRADAY_SOURCE` |
| Oct 13 00:00 | Oct 14 00:00 | `REJECT_UNVALIDATED_WAVE_WITH_NO_EXECUTABLE_QUOTE_OR_FILL` |

Strict 15m right-hand parent high confirmation was only **Oct 10 10:30 UTC**; the Oct 10 09:31 center is not confirmed as a completed-bar 15m swing when formed. The five-day Oct08–12 minute corpus could not have been fully closed before Oct 13 00:00 UTC, and even then no valid nested-wave pattern, actual archive publication timestamp, executable quote or filled order was proved.

**Immutable local physical audit receipts:** `E:\NEXUS-QA\elliott-v68-physical-first-20261016`:

- `V68_FALSE_EARLY_ENTRY.json`, SHA256 `ebe2c0d149645f90219693d8f33e3fd624c1b41c4f6cabc707d139e77cafa14e`
- `V68_AT_CONFIRMATION.json`, SHA256 `11a95e86df869b8f529e2082fe113f0490e458f85cc79488bf5c5796dad86b4d`
- `V68_AFTER_FULL_CORPUS.json`, SHA256 `d630cec333efe058a1eb91c3e30ee473310e3785b0b3c8f7e9e23654b26c66da`

Inputs: V45 ETH 1m Parquet SHA256 `fbdad48b85ff5ada62c2e12e3321413fdf60ddf5b5655df68d5b60e98c1cdfcf`; V63 child witness SHA256 `51d742a3a487e1a416e79e8319df87b2a954075f77d4a455b43a5c67bbac1585`.

## Regressions and honest scope

A local first-pass version executed **9/9 isolated tests** on Laptop2, checking control-flow and veto behavior. A separately packaged **seven-test portable suite**, `research/elliott_v68_physical_first_veto/test_physical_veto_v68.py`, is registered via `tests/test_nexus_elliott_v68_physical_first.py`. **The seven-test published version must be checked against exact GitHub HEAD before it can be claimed as passing**; 9 earlier tests are not proof of its execution. Unit-test mocks prove that the V66-first guard is called before V67, while the physical Laptop2 receipts independently prove actual SHA-backed source processing. Neither proves a profitable Elliott entry.

The original frozen V52 SHA256 `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4`, Bybit BTC/ETH 15m parent and 3m child, UTC Oct16–17 warmup and Oct18–Nov16 exclusive scored window remain unchanged. Paper/demo journal, laptop1 installed application and VPS remain untouched. Live disabled, PR remains Draft/unmerged.
