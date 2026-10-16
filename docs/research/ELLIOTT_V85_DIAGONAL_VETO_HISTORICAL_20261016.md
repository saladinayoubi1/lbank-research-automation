# NEXUS V85 — Diagonal hard-veto audit (research only)

**Purpose:** Inspect the two previously rejected V83 five-leg skeletons without retroactively declaring them profitable diagonals. This does **not** implement a leading or ending diagonal classifier. No signal, P/L, Paper promotion, V52 change, or Live access.

## Rulebook and scope
- [Elliott Wave International: Diagonals](https://www.elliottwave.com/waveopedia/elliott-wave-pattern-diagonals/): wave 4 commonly overlaps wave 1 in a diagonal; the third actionary wave **must not be shortest**; corrective waves cannot fully retrace the preceding actionary leg. An **ending** diagonal generally subdivides 3-3-3-3-3; leading diagonal subdivisions and valid pattern positions require separate evaluation.
- [EWI: Impulse](https://www.elliottwave.com/waveopedia/impulse/): wave-4 nonoverlap governs a **conventional impulse**, not all motive formations.
- This audit treats these rules as **necessary vetoes**, never sufficient evidence. Overlap alone is neither a diagonal proof nor a license to rescue an earlier losing trade.

## Physical source and temporal guarantees
- Source: Binance Spot BTCUSDT/ETHUSDT 1-minute data, 2024-03-01 to 2024-03-02 UTC. V80 official ZIP/CHECKSUM archive provenance is validated, V82 strict 15m / 3m / 1m right-confirmed center witnesses reconstructed, and V83 physical path and candidate output independently rerun.
- Before inspection the new script asserts that each re-executed V83 per-symbol result is **exactly equal** to its immutable archived V83 receipt; it refuses altered or unknown input sources.
- Standalone `evaluate_diagonal_preconditions` is a **pure geometry gate over provided source-bound records**; it cannot authenticate arbitrary price arrays alone. Source attestation is done by `run_audit`.
- Raw archive receipt download was in 2026; the **historical earliest observable close** for a pivot is a counterfactual point-in-time candle close, not evidence a trader actually received these files in 2024.

## Historical exploratory results (not a prospective score)

| Pair | V83 five-leg skeletons | V85 hard-veto result | Diagonals proven | Trades |
|---|---:|---|---:|---:|
| BTCUSDT | 1 | **Reject:** wave 3 is shortest | 0 | 0 |
| ETHUSDT | 1 | **Geometry only:** ordinary impulse overlap remains, but 3-3-3-3-3 subwaves / structural position / wedge all unverified | 0 | 0 |

The BTC diagonal hard-veto persists even if wave-4 overlap is allowed. The ETH record is **not** a confirmed diagonal, nor a reason to re-label, trade, or optimize the inspected historical structure. Neither instrument gained a valid Elliott strategy or verified profit.

## Verification and independent next gates
- Dedicated deterministic tests `tests/test_nexus_elliott_v85_diagonal_scope.py`: 13/13 PASS, covering BTC rejection, ETH abstention, bullish mirror, wave-2/wave-4 full retrace, wave-3 progress, physical invalidation, missing/duplicate center ordering, future confirmations, malformed prices, bad vertex cardinality and executable record rejection.
- **Full Elliott regression on Laptop2: 607/607 PASS, `Ran 607 tests ... OK`, native `EXIT_CODE=0`.** PowerShell `NativeCommandError` when piping Python stderr is a stream-wrapping message, not an assertion failure at exit zero.
- Source-bound result: `docs/evidence/elliott-v85-diagonal-veto-20261016/V85_DIAGONAL_SOURCE_AUDIT.json`; SHA-256 `8577e51e9f857b805d54e3ccd12e8a8471d13e05521c186ba06febb9c4f51499`; V80 and V83 input receipt hashes bind the replay. Raw data and full local test output stay on Laptop2.
- **Next step:** separately implement and preregister a full internal three-wave witness for each diagonal leg and verify potential leading/ending structural location on untouched data. Never use the already inspected ETH case to select profitability parameters.
- PR #2673 remains Draft; no Merge without explicit user authorization. Bybit only for any future Paper-Demo, with Live Trading always disabled. Laptop1 and VPS are untouched.
