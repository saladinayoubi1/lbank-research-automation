# Elliott V56 — Transactional immutable source publication

**Date:** 2026-10-16 UTC. **Scope:** Draft PR #2673, BTC/ETH Bybit public Spot trade-data research. Live disabled, Paper/Demo and VPS untouched.

## Actual failure mode found

The prior V55 daily source converter created its final evidence directory **before** the separately written V52 raw-to-1minute oracle completed. A mid-pipeline exception (invalid independent OHLCV comparison, failed output write, altered raw archive) could leave an incomplete folder at the final destination. An external consumer could mistake folder existence for verified evidence.

## V56 change

The same source validation and fixed prospective timing requirements remain unchanged. Data are now written to an isolated new temporary sibling directory on the same filesystem. All steps below must succeed **before publishing**:

1. Full source gzip read/validation with all 1,440 original trade-bearing UTC minutes.
2. Parquet write, new physical SHA-256, and the entirely independent V52 original-archive-to-minute verification.
3. Confirmation of exact source-trade count agreement between producer and independent verifier.
4. Creation of the complete source receipt, containing the verified final target path, source SHA-256 and physical minute SHA-256.
5. Last-moment refusal of a pre-existing destination, then filesystem rename from verified temporary directory into previously unused final output directory.

If any pre-publication step fails, the temporary tree is cleaned up and the authoritative final destination does not exist. The archived original gzip is unchanged. The final directory cannot be rewritten by repeated runs. On Windows, same-parent directory rename and rollback behavior was exercised with synthetic source files on the real laptop.

## Evidence and tests

V55 existing **12/12** synthetic/adversarial cases pass against the V56 implementation. V56 adds **6/6** independent fault tests covering producer-to-oracle mismatch rejection, source mutation after initial hashing, failed Parquet write, failed evidence receipt write, concurrent target directory creation and verified normal publication. Combined isolated run: **18/18 PASS**.

GitHub code: `research/elliott_v55_source_intake/build_official_day_v55.py` (transactional implementation), `research/elliott_v56_atomic_source/test_atomic_v56.py` and native discovery `tests/test_nexus_elliott_v56_atomic_intake.py`.

This is a **crash-consistent publication enhancement**, not absolute protection against every hardware/power or filesystem journaling failure. A lost raw archive or tampered raw source cannot be recovered from SHA alone. The module remains offline and does not itself fetch or authenticate remote Bybit URLs, start automation, access Demo or place orders.

**Invariant:** prospective source-day scoring only under SHA-frozen V52 protocol starting Oct 18 UTC after source completion; no new real Oct16 source-day success/PNL is claimed by these synthetic regressions.
