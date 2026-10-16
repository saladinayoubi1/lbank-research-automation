# Elliott V57 — Independent reattestation before a prospective daily scan

**Research scope:** BTCUSDT and ETHUSDT public Bybit Spot daily source verification in Draft PR #2673. No entry signals, demo promotion, orders, Live, or P/L.

## Audit gap resolved

The lower-level V53 scanner previously accepted `VerifiedDay` values constructed by its caller. This is suitable for synthetic unit tests and internal computation but, by itself, **does not prove that the original trade archive or prior V55 receipt still exists or matches its published SHA**. A forged or stale `VerifiedDay` object could therefore be mistaken for source evidence.

V57 introduces `research/elliott_v57_attested_scan/fully_attested_v57.py` as the **production-facing read-only adapter**. It accepts original V56 transactional V55 receipt-file paths, not caller-built `VerifiedDay` objects. Before allowing V53 to inspect a single minute it requires:

1. Exact chronologically ordered completed UTC days, under the immutable Oct16–Nov16 protocol, with no early scoring before Oct18 00:00 UTC or future daily decision.
2. Existing physical V56 transactional receipt and non-symlink raw and final-minute files. A synthetically produced receipt is allowed only under a separately labelled OS-temp test mode; it is **not** a production source-day proof.
3. Exact expected public Spot filename/declared source URL, SHA-256 field consistency, production/synthetic status and research-only flags.
4. A **fresh second V52 full raw gzip-to-1minute physical oracle run** on every day: source/archive SHA, all 1,440 UTC minutes, 7,200 numeric OHLCV fields and 1,440 trade-count checks. Result must match the embedded old independent receipt exactly.
5. Only those freshly reverified `VerifiedDay` records are then passed to the unchanged V53 limited parent/child research scanner.

Every successful read-only adapter result retains `source_remote_origin_authenticated=false` because V55/V57 cannot authenticate where an offline archive originally came from: an expected official URL string is **not** network-capture proof. Distinguish this local-data guarantee from remote original-source provenance. The adapter never runs a downloader, modifies Demo, or places trades.

## Adversarial regression evidence

**11/11 V57 unit tests passed on Laptop2** after an initial test assertion was corrected to isolate the fixture-status rejection from the earlier future-clock rejection. Tests use two fully synthetic, explicitly labelled physical gzip trade-day archives and V55's transactional producer: a normal, re-oracled synthetic scan; forged embedded trade counts; modified physical raw file; modified physical minute file; altered source URL; forged fixture-to-production status; rejected synthetic receipts in real mode; future-clock decisions; duplicate/missing days; swapped days; and old/nontransactional schema.

**No new complete post-registration official market archive was present or accepted during this test.** No bounded real Elliott candidate, P/L, or signal resulted. Existing Laptop1 Demo, paper ledger and paused VPS remain unchanged; Live stays disabled.

Keep the lower-level V53 scanner as an internal deterministic evaluator and use the V57 adapter for future research evidence admissions. Once complete physical daily official archives actually exist, separately authenticate their remote capture origin; then repeat V55→V52→V57 and only score under V52/V54 frozen daily rules.
