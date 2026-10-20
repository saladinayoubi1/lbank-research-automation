# MR40 cap40 diagnostic replay — 2026-10-21

Study: mean_reversion_40_m2_cap40_v1. One fixed cap of 40 original-target bars (160h under complete next-open fills); no reentry until the original signal resets flat.

Exploratory analysis of already-seen data. This is not independent OOS qualification or prospective evidence. No orders or live/paper integration.

Recorded result digest: c3fd7abbd94ed7a5e938fcbf001f9be144da10f0322c23437f7b43b4e3948a4e
Pinned baseline result digest: 44ea00e4528ccbe3e420bd999152a36b58450565f8a45bb9489a3c79fe4b4514
Input digest: fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe
Executed code commit: 0bd7a1ede39aec7e7ef64b65b96cf4ba02b37555
Preregistered contract commit: 7cd60d917f0bfbc1e0121ef35aa08f10c8da988f

Python 3.11+ standard library only. All candles and fills use UTC. Units: USDT.
Read MR40_TIME_CAP_20261021_FA.md for the complete findings and limits.

## Offline verification and replay

Extract this ZIP to a fresh directory, then run:

    python verify_replay.py

This checks every inventory member, runs the 11 cap regressions, replays all 24 cases in a temporary directory, and compares all five CSV files byte-for-byte and results semantically against the recorded output. Execution timestamp, worker hostname and the derived result digest may differ.

The verifier does not modify recorded results. It uses aggregated inputs, not network requests. Baseline raw-trade ingestion is documented in the baseline report and is not re-executed.

## Files

- research/: candidate module plus exact pinned baseline engine for unit-test imports.
- tests/: 11 cap regressions including exact engine-byte check.
- study_contract.json: fixed policy, authority and seen-data classification.
- baseline/: prepared 8,400-bar input, original study contract, pinned baseline engine, accepted baseline results and full equity curve.
- recorded_results/: all 24 case results, summary, full fills, closed positions, monthly attribution and full equity curve.
- INVENTORY.json: byte lengths, SHA256 and Git blob identifiers for all other bundle files.
- tests-executed.txt: physical regression run log.
- verify_replay.py: offline verifier and exact CSV/semantic replay check.

Recorded source-files hashes must match Git commit 0bd7a1ede39aec7e7ef64b65b96cf4ba02b37555. Bundled baseline engine must remain byte-identical (SHA256 e9b898040d4680f128da330177df84e2fcc4ba1e2f70f467cf5455d685247b27).

Main result: 42-month net PnL worsened from -1122.7878418296914 to -2022.77140544161 USDT at normal costs. Normal close drawdown fell from 41.20001279316119% to 35.887911864887435%, but stress-cost drawdown worsened. The candidate is not approved for promotion.
