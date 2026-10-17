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

## Physically measured, reviewed historical result (Laptop2)

The original identical 15m Parquet source SHA256s were reopened and verified on DESKTOP-F4SA4VL. Five adversarial tests passed locally (5/5, exit 0). The physical archive replay exited 0 and emitted four complete, mutually comparable arms.

| Arm (entry bars, compression ratio) | Training net, both symbols, conservative | Validation net, both symbols, conservative | Inspected test net, both symbols, conservative |
|---|---:|---:|---:|
| 12, 0.38 | -984.80 USDT | -760.16 USDT | -814.14 USDT |
| 12, 0.55 | -986.36 USDT | -807.78 USDT | -847.22 USDT |
| **20, 0.38 (training selected)** | **-866.97 USDT** | **-549.66 USDT** | **-681.17 USDT** |
| 20, 0.55 | -937.28 USDT | -676.21 USDT | -757.61 USDT |

Each symbol has its own isolated synthetic 500 USDT account, **so the combined 1,000 USDT in the table is not the shared 500 USDT NEXUS Demo paper balance**. The selected arm's combined conservative closed roundtrips: training 1,427; validation 438; inspected test 434. Stress costs worsen each period (training -996.24; validation -849.34; test -892.44 USDT, respectively). The apparent high trade count and severe losses mean the new idea is **not an economic strategy candidate**. There are no untouched future results and no stop-first intrabar fill modeling.

- Native full research JSON: `docs/evidence/strategy-finder-compression-20261017/V1_MEASURED_PREINSPECTED_REPLAY.json`.
- Original computed canonical result digest: `a7d0c44de9bdcdf375dd70a22f5f42c18a29f31c5524119795103423db39cfa8`.
- Original Laptop2 output-file bytes SHA256: `72893679ae762d1a548ecd3a3a4e469f67a0fbd19b4cdb0510521913d8adea1a` (Windows local newline presentation, not asserted to equal Git text blob).
- Verdict: `REJECT_NEW_MECHANISM_NEGATIVE_INSPECTED_HISTORY`, do not enqueue this evaluated fingerprint in autonomous rotation. Keep all tested arms and losses, avoid posthoc threshold tuning.

A genuinely different preregistered hypothesis and independent prospective validation are required to resolve the rotation's exhausted frontier without repeating old research. GitHub CI and independent market-source validation are separate from the completed local tests.
