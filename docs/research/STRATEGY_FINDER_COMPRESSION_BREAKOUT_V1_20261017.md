# NEXUS Strategy Finder — compression breakout exploratory frontier (17 Oct 2026)

**Mode:** separate source-pinned research prototype, not an approved or deployed Strategy Finder family. No existing rotation cursor, Demo installation, Paper position, order adapter, risk gate, or Live permission is changed.

## Root cause and precise scope

The scheduled Strategy Finder rotation returned `NEEDS_NEW_REVIEWED_MECHANISM` / `all_exact_reviewed_frontiers_terminal`, despite its controller inventory listing ready workflow files. The existing two rotation-eligible mechanism fingerprints were already resolved. Dispatching the same proposal under a new name or replaying exhausted evidence is prohibited.

This change supplies a **genuinely distinct research hypothesis** without modifying the original three-family 9-cell multipair contracts, which are shared by Demo and downstream workflow proofs.

## Frozen source and mechanical signal

Input is *already inspected* Bybit Spot 15-minute BTCUSDT/ETHUSDT, Dec 1 2022–Jul 31 2026, 128,544 continuous closed bars per symbol. It must physically match the original recorded parquet bytes:

- BTC file SHA256 `c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226`
- ETH file SHA256 `ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1`

The signal checks whether the **preceding** N-bar high/low width is below a predeclared fraction of the preceding 80-bar width. Enter long on a closed candle above the preceding N-bar high. Exit on a closed candle below the preceding 8- or 10-bar low. Research executions use the *next candle open*, never that candle's close, and close any remaining synthetic position at the end of each partition. No intrabar stop/target simulation, no short, no leverage, no live broker or Demo submission.

Predeclared arms: entry 12 or 20 bars; width ratios 0.38 or 0.55; base 80 bars; exits 8 or 10 bars. Training-only selection of four arms at fixed 60% chronological Training / 20% Validation / 20% already-inspected Test partitions; report **all four arms**. Fee+slippage per leg: conservative 10+5 bps; stress 25+15 bps. Starting paper-reference capital is 500 USDT *for a fully isolated hypothetical calculation*; it is not the user's demo account.

## Safety and next qualification gates

This research source rejects changed raw file hashes, missing/duplicate 15-minute timestamps, modified series shape or malformed OHLC. A successful test or historical positive aggregate **must not** reset Strategy Finder exhaustion, promote a Candidate, claim unseen validation or enable Live. A separate independent dataset and review of signal causality, risk/stop policy, fill assumptions and net costs are required before a vetted workflow stage can join automatic rotation. The existing 3-family multi-pair pipeline remains frozen.

**Current status:** isolated hypothesis and adversarial tests proposed in Draft PR. Physical replay, CI and independent future sample require separate recorded results; do not infer they passed from the presence of files.
