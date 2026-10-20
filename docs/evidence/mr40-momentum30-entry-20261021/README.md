# MR40 momentum30 entry-admission replay

Candidate: mean_reversion_40_m2_momentum30_entry_v1.
Exactly one change: admit an original long-target episode only if the 30-day close return known at its first decision is nonnegative. Reject the whole episode otherwise; no late entry. Retain the original exit. No cap40.

Classification: exploratory, post-hoc hypothesis on already-seen data. No independent economic qualification, prospective/OOS claim, auto Demo or orders.
All values are USDT; all candle/fill times UTC. Initial capital: 10,000 independently for each of six cohorts and four profiles.

Recorded result digest: 959832aa111ba6bbab7a899547a7d4e031a0f3cd0a283de30397635f1ba5f118
Code commit: 40b751d0b0466ef0ccc3ba4807a2e2ceeabbf147
Pre-execution contract commit: df21c2657e8a8811035b55b463cf8e315bd3ab62

Python 3.11+ standard library only. Extract the ZIP to a fresh directory and run:

    python verify_replay.py

The verifier hashes all inventory files, runs 14 admission regressions, then replays all 24 cases in a temporary directory. It compares summary, fills, positions, equity, monthly attribution and entry-admission CSVs byte-for-byte, and results semantically. Execution timestamp, worker hostname and the resulting digest may differ.

recorded_results contains all candidate outputs. baseline contains the exact original engine, prepared inputs, contract, accepted results and full equity CSV used for the 24 original-path equality controls. research also includes a duplicate exact baseline engine for isolated unit-test imports.

MR40_MOMENTUM30_ENTRY_20261021_FA.md contains the complete findings. Normal 42-month net PnL is +3980.1087652016868 USDT with 21.455007625514998% close drawdown; stress net PnL is +1445.939521527369. Forty trades replace 81. These historical results do not qualify the strategy for deployment.
