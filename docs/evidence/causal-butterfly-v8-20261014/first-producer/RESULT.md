# Butterfly v8 first market producer — completed, outside Demo

The fixed causal bullish Butterfly was executed once on Laptop2. Validation was negative for BTC and ETH under both cost scenarios; the final historically inspected partition produced zero closed round trips in all four cells. Small conservative Training gains disappeared under stress costs. This is evidence about this preregistered implementation on already inspected history, not a general verdict on every harmonic strategy.

Computational source: `2b89f6e89abdacc16b3288b9fd9ebcb3bdea7e69`. Prospective invocation commit: `2c1ecb6bb46311f8dfbccc9b3c7dbbdfccad6e02`. The recording commit and staging helper are not computational source.

Native completion: 2026-10-14T14:36:31.981753+00:00; producer true child OS exit 0; parent 3896 true OS exit 0 at 2026-10-14T14:36:32.361809+00:00. Child 3100, Windows host DESKTOP-F4SA4VL. Producer elapsed 54.657s; parent elapsed 55.719s. Deadline 600 s did not fire. One candidate, four Training screening cells, twelve locked diagnostic rows. Existing39 unique native semantic/compatibility tests reused; exact preproducer head729aa656af699bf806dd8c274f2d7401305b239e had seven successful hosted checks and discover intentionally skipped.

## Results

Each asset/partition/cost cell starts with an isolated 10000 USDT simulation. Owner reference remains 500 USDT. Rows and cost scenarios are separate simulations and should not be added as one shared-wallet portfolio. Figures below cover full partitions, not monthly returns.

| Asset | Partition | Cost | Closed round trips | Net USDT | Mean USDT/trade | Net % | Max DD % | PF |
|---|---|---|---:|---:|---:|---:|---:|---:|
| ETHUSDT | Training | conservative | 1 | 3.17782063 | 3.17782063 | 0.03177821 | 0.02962752 | n/a |
| ETHUSDT | Training | stress | 1 | -9.30331001 | -9.30331001 | -0.09303310 | 0.09303310 | 0 |
| ETHUSDT | Validation | conservative | 1 | -8.86436476 | -8.86436476 | -0.08864365 | 0.08864365 | 0 |
| ETHUSDT | Validation | stress | 1 | -12.81565421 | -12.81565421 | -0.12815654 | 0.12815654 | 0 |
| ETHUSDT | Historically inspected test | conservative | 0 | 0.00000000 | n/a | 0.00000000 | 0.00000000 | n/a |
| ETHUSDT | Historically inspected test | stress | 0 | 0.00000000 | n/a | 0.00000000 | 0.00000000 | n/a |
| BTCUSDT | Training | conservative | 2 | 5.40321599 | 2.70160799 | 0.05403216 | 0.02460823 | n/a |
| BTCUSDT | Training | stress | 2 | -2.61528927 | -1.30764463 | -0.02615289 | 0.06782463 | 0 |
| BTCUSDT | Validation | conservative | 1 | -6.52019211 | -6.52019211 | -0.06520192 | 0.12700646 | 0 |
| BTCUSDT | Validation | stress | 1 | -10.48317320 | -10.48317320 | -0.10483173 | 0.14157581 | 0 |
| BTCUSDT | Historically inspected test | conservative | 0 | 0.00000000 | n/a | 0.00000000 | 0.00000000 | n/a |
| BTCUSDT | Historically inspected test | stress | 0 | 0.00000000 | n/a | 0.00000000 | 0.00000000 | n/a |

Coverage uses closed-bar UTC timestamps: Training 2022-12-01T00:15 through 2025-02-11T09:30, 77126 bars; Validation 2025-02-11T09:45 through 2025-11-06T04:45, 25709 bars; historically inspected test 2025-11-06T05:00 through 2026-08-01T00:00, 25709 bars. The last 15m candle opens on 2026-07-31T23:45 and closes on 2026-08-01T00:00.

Conservative fee/slippage 10/5 bps per leg; stress 25/15 bps. Same long-only, next-open, stop-first, 1.5 ATR/2R/64 bar exit, 10% cash cap and 0.1% stop risk rules. No minimum trade-count or maximum-trades filter added. The low activity is reported rather than used as an arbitrary minimum-count rejection. Profit factor is unavailable in no-realized-loss or zero-trade cells, not infinity.

## Verification and preserved identities

Report canonical digest: `21be76c6f276c0d71ed4f87a2a045eee7ee9050d4d789ee1a862be8ad333c4c0`.
Ledger canonical digest: `9199c1d27e28bdc2de7f068dd1f99efa7d6315c793265d1c3215a860344b152c`.
Producer receipt canonical digest: `b3fdbcffe79390b62331951b1ba4e9184f8ba57aaf9c25e3b9da5ae7bab0279f`.

Native wrapper verified 25 staged source components, six raw Parquet files, ZIP/manifest, unchanged predecessor ledger and invocation files before/after. ZIP members matched raw bytes; no download or replacement. Exactly one Butterfly fingerprint was appended while prior evaluated/screened history was retained. Four screening metrics match their repeated Training diagnostic rows; fixed configuration, costs, risk assumptions, twelve distinct cells and source/authority contracts matched.

Local read-only artifact verification independently validated report/ledger/receipt canonical digests and matched native SHA256 for the copied report, ledger, receipt and summary. Report/ledger original CRLF bytes are preserved to retain their exact native byte identities; receipt/summary LF bytes are preserved. Parent submission/exit, staging receipt and status are RDC JSON text transcriptions; their original native byte identities were not separately attested. This artifact-integrity check is not an independent numeric, Decimal, signal, leakage or market-data replay.

The bootstrap staged the remaining exact frozen files together, submitted parent 3896 once, owned its Popen lifetime and captured its actual exit. Permanent source-gate/run/launch locks remain. Terminal 9252 corresponds to the RDC PowerShell launcher, while bootstrap Python PID 8380 is recorded in the native submission. No market retry or old v5/v6/v7 replay occurred.

## Decision and next boundary

Keep this implementation outside Demo. Live=false; auto_demo_promotion=false; owner admission=false; official Coordinator advancement=false. Independent numeric/Decimal/market leakage QA and unseen future data remain uncompleted separate gates. Negative diagnostics do not require retuning the observed partitions.

No owner installation/profile/journal/checkpoint/authentication, Paper writer/failover, remote recovery task, Windows update or VPS modification. Laptop1 remains the sole owner Paper writer. Map nodes DATA-21 / RES-30 / RES-31 / RES-32 / VAL-40 / QA-41.

Do not rerun this completed producer. A next causal Elliott hypothesis needs its own prospective preregistration, deterministic rules and source gate before any market test.
