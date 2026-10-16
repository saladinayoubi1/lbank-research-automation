# Elliott V67 — False entry/exit and retrospective timing veto

**Date:** 2026-10-16 UTC. **Scope:** Draft PR #2673, isolated Bybit ETHUSDT historical research. No exchange orders, Demo/Paper promotion, profit calculation, Live, Laptop1 install, or VPS change.

## What this gate prevents

V66 physically reattested eight historical ETH pivot vertices from the already-inspected Oct08–12 minute source and pinned the earliest completed-bar confirmation of the two bounding strict 15m parent pivots at **2026-10-10 10:30 UTC**. The subsequent 09:31 UTC source-minute high *center* is an observation of price, **not** a right-confirmed Elliott 15m swing at 09:31. The 15m high requires three completed following 15m bars, ending 10:30.

Furthermore, V45/V66's **full** five-day Oct08–12 archived minute corpus could not have existed until **2026-10-13 00:00 UTC at the earliest**, and the individual Oct10 public daily archive cannot exist as a full-day archive until at least Oct11 UTC. Those are **not actual verified publication times**. Real acquisition may be substantially later, as V60 physical TLS/receipt arrival auditing distinguishes.

The newly isolated `research/elliott_v67_false_entry_exit_veto/veto_v67.py` is a deliberately **non-executing secondary reporting layer**: it accepts a metadata-shaped V66 retrospective report, checks expected provenance hashes and eight/6/2 source-confirmed pivot counts, requires the known V66 10:30 structural clock, and insists that both the historical nested-wave alternatives remain rejected. Any invented executable quote, new P/L, live/trade flag, or retimed parent confirmation is refused.

Its `audit_retrospective_claim` classifies hypothetical backdated entries **without ever granting order authority**:

| Hypothetical claimed entry UTC | Outcome |
|---|---|
| Oct10 09:31, at the source-minute high center | `REJECT_BACKDATED_BEFORE_PARENT_RIGHT_CONFIRMATION` |
| Oct10 10:29:59 | `REJECT_BACKDATED_BEFORE_PARENT_RIGHT_CONFIRMATION` |
| Oct10 10:30, right at full strict parent confirmation | `REJECT_UNFINISHED_HISTORICAL_ARCHIVE_AS_INTRADAY_SOURCE` |
| Oct13 00:00, theoretical earliest point entire five-day corpus could be closed | `REJECT_UNVALIDATED_WAVE_WITH_NO_EXECUTABLE_QUOTE_OR_FILL` |
| Exit at or earlier than claimed entry | `INVALID_ENTRY_EXIT_CHRONOLOGY` |
| No entry claimed | `NO_TRADE_CLAIM` |

The ordering distinction is intentional. An otherwise past-confirmed structural wave **does not become** an archive-time-known wave, and an archived structure **does not become** an executable quote or a filled trade. For all outcomes, `entry_signal=False`, `exit_signal=False`, `paper_eligible=False`, `live_enabled=False`, `fill_confirmed=False`, `pnl=None`. A hypothetically chronological exit never yields a computed gain.

## Threat model and limits

This module checks a V66 **metadata-shaped retrospective claim** only, without opening or cryptographically hashing the underlying archive. A malicious caller could forge a dictionary including claimed hashes. Thus, **it is not a new independent source-authentication oracle**; actual original V66 `--source` + `--receipt` + V45/V63 pinned-byte physical verification and V60 actual-stage capture chain must precede any credible source conclusion. V67 remains a **veto**; never an order-admission interface. It does not touch V53/V62 prospective scanner.

A historical source file being fully closed by a given date does **not** establish the official archive was published by that date. It also does not prove a continuous executable orderbook was visible, spreads, fee, slippage, or market liquidity. There are no real entries/exits or realised P/L to report.

## Regressions and deployment boundary

`research/elliott_v67_false_entry_exit_veto/test_veto_v67.py` contains **14 tests**, with native suite registration `tests/test_nexus_elliott_v67_false_entry_exit.py`. They cover source-minute/15m confirmation difference, UTC second-before cutoff, source corpus availability, post-archive no-fill rule, invalid exits, unverified chronological exits, missing entry, naive timezone, forged hashes, forged trading/P&L claims, rewritten structural clock, timezone offset equivalence and research-only flags.

The original V52 canonical protocol SHA256 `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4`, 15m parent/3m child, source start Oct16 UTC, warmup Oct16–17, score Oct18–Nov16 UTC exclusive, remains unmodified. V65 and V66 report no verified nested-wave acceptance. The V67 module intentionally does not turn V65 geometry into a Demo strategy.

**Verification:** The V67 tests were authored on the Draft PR branch. They must be confirmed by hosted GitHub Test matrix on the exact V67 commit before describing them as passing. No Laptop2 native run has been claimed during this operation.

**Next scientific decision:** preserve the frozen prospective score protocol and accumulate physically verified unseen daily source evidence as it actually becomes available. Explore alternative wave hierarchies only as separate preregistered hypotheses, not by backdating or deleting inconvenient pivots.
