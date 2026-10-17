# Strategy Finder — six raw source hashes + actual 500-USDT shared wallet research pilot (18 Oct 2026)

## Decision

**Reject the measured `structural_pullback` candidate in this fixed historical window.** This is not a discovery of a new strategy or an unseen forward test. The shared-wallet simulation works on actual, independently byte-pinned **Bybit Spot** OHLCV archives, but the pre-existing reviewed historical candidate is cost-negative in **all three Q1 2025 partitions**.

## Why this patch was necessary

The base PR #2715 (merged to `main` as `e9fa9cf7ad703465f23fbc6cedceb9e1c68abc82`) introduced a real single-wallet 500-USDT research simulator and an adapter for the old 10k-per-symbol Strategy Finder reviewed grammar. The adapter only compared a user-supplied `ARCHIVE_SHA256` to a constant before calling `load_verified_archive_frame`. The underlying `nexus_demo_archive_replay._load_frame` checks parquet schema, timestamps, cadence, metadata and OHLC validation through other research functions, but **does not check the individual physical parquet bytes against immutable file digests**. A valid caller-provided *semantic* archive identity is not proof that the local source bytes were never replaced.

This patch closes that gap. `scripts/nexus_strategy_finder_shared_cash_eval.py` now hashes and checks **all six** exact original Bybit raw source blobs before the reviewed signal and feature adapter can run. It disallows symlinks, unexpected/missing data, oversized files, altered raw bytes or modified representation without a new review. This supplements rather than replaces original field-level schema/continuity checks. No authenticated source, no research report.

### Actual original per-file SHA256 observations (Laptop2 only)

| Source cell | Raw parquet SHA256 |
|---|---|
| BTCUSDT Spot 15m | `c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226` |
| BTCUSDT Spot 1h | `f8f2236785c036fe40808809397d47729b3add4c8f0b9e19c77d3b771f8e6847` |
| BTCUSDT Spot 4h | `e0d019a76882a02dc463a34d1d9375841f81d412b9a3310d9e21c2d7b2738dc6` |
| ETHUSDT Spot 15m | `ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1` |
| ETHUSDT Spot 1h | `ba0743588c5089e6a6b250b4ebb029a43fea57d0a020df5ab1316c34efdcd88a` |
| ETHUSDT Spot 4h | `292005e091d914fbb9d108c3d8d65e93785cc32b9c73e07ea02e0d44cf7da65b` |

Approx. 14.08 MiB compressed raw files combined, all six matched their declared exact SHA256 before market data were accepted.

## One real-archive, bounded, fixed economic pilot

- Mechanism: **already reviewed** `structural_pullback`, originally frozen Strategy Finder `risk_variant=0`, with exact reviewed config fingerprint bound to the original `nexus_demo_archive_replay.ARCHIVE_SHA256`. No training-only winner selection, no retrospective tuning, no new strategy name masquerading as novelty.
- Source warmup: 2024-12-01 until 2025-01-01 UTC. Source evaluation: 2025-01-01 through end of 2025-03-31 UTC, 8,641 completed 15m `decision_at` observations per symbol for three independent 60/20/20 temporal partitions. **Previously inspected historical data**, not fresh held-out Bybit bars.
- Loaded six original pinned byte-exact source frames, limited each time-aligned frame to 121-day bounded source context *after independently checking every raw archive file*, and then rebuilt original `nexus_composite_strategy_research.build_features` point-in-time peer + completed 1h/4h and 15m features. Both coins independently calculated original fixed `signal_for` logic on **identical UTC closed 15m grid**. BTC emitted 150 boolean source signals, ETH 125, total 275, before any cash collision or risk decision.
- Exact physical shared 500-USDT BTC/ETH book per partition; one active long, deterministic simultaneous BTC-first admission, min(250 USDT gross, 2.5 USDT gapless nominal downside, available shared cash) no borrow/short, original Strategy Finder fixed 1.5×ATR stop and 2R target, 64-bar timeout, next-open entry only. Stop-first intrabar, worse open if gap through protective stop. Conservative assumed 10bps commission + 5bps slippage **per side**; stress 25bps commission + 15bps slippage per side. Real Bybit depth/queue/matching not attested; quantity step is a simulator value, not actual exchange lot step.
- Three disjoint partitions **each** reset to 500 USDT initial cash; do **NOT** sum the resulting P/L as if one continuously reinvested portfolio. Friction changes sizing and realized holding/collateral paths; cost profiles are independent simulations with potentially different trade counts.
- No minimum trade-count filter; all source signals and peer denials accounted. **All segments cost-negative**.

| Historical segment | Conservative trades | Conservative positive | Conservative net USDT | Mean/trade USDT | Stress trades | Stress net USDT |
|---|---:|---:|---:|---:|---:|---:|
| Train | 83 | 20 | **−73.61856402** | −0.88697065 | 85 | **−162.26967951** |
| Validation (preinspected) | 21 | 9 | **−5.49062743** | −0.26145845 | 20 | **−20.91352813** |
| Historical test (preinspected) | 27 | 6 | **−23.52712337** | −0.87137494 | 33 | **−69.35777911** |

Conservative max equity drawdown respectively **14.899%, 1.960%, 4.886%** of each independent 500-USDT book; stress **32.454%, 4.502%, 13.917%**. Training conservative exit reasons: 61 structural stops, 20 targets, 1 true same-bar stop-first and 1 timeout. Historical test: 19 structural stops, 7 targets and 1 timeout. The risk geometry is not financially robust even before requiring a novel genuinely independent future window.

## Accounting, original evidence and deployment boundary

- `docs/evidence/strategy-finder-2025q1-shared-cash-20261018/structural-pullback-rejected.json`: six pinned source identities, original reviewed mechanism fingerprint, original raw ledger SHA/digest, train/validation/test conservative+stress P/L, win/trade counts, exit reasons, denied peer signals, verified 60/20/20 monthly ledgers. **Each of all six partition/profile cells separately reconciled** trade count and financial ledger P/L to monthly totals within 1e-5 USDT.
- Full local physical ledger only on isolated Laptop2: `E:\NEXUS-QA\finder-shared-cash-gate-20261018\real-bybit-2025q1-structural-pullback-500shared.json`, SHA256 `a9b0cb3872a503e370c0fef1f1439721be7b4ca59951f58ae976c899665c093e`, canonical result digest `bb8e9bfd2d3cfa2092373a4d051b97a765121fc8456336b43b78a7e1b14aab72`. Raw ledger **not** misrepresented as uploaded to GitHub; compact authoritative evidence summary SHA256 on Laptop2 `6a1b01444c9eb0e6c82843b35a933f3df5da68faaf8a3d589179022c8dba785d`.
- Original current-`main` source modules imported from a read-only isolated QA snapshot; installed owner Laptop1 and both installed NEXUS apps, paper account, journal, strategies, runner and trading keys were not changed. Fixed scope 2025Q1 prevented resource pressure on 4GB Laptop2; no attempt to run full 2022–2026 2-asset/3-TF source feature build.
- **31/31 native Laptop2 pytest pass** after adding three physical-byte-tamper/untrusted-root tests to the original 28. Real physical six-input source and bounded 2025Q1 replay script exit 0, Python-native monthly conservation exit 0. Hosted CI runs independently.
- The adapter still requires an exact original reviewed mechanism/fingerprint and `risk_variant=0`. It **never** auto-qualifies a strategy or dispatches research from terminal frontiers. `paper_eligible=false`, `qualified=false`, `live_enabled=false`, no real exchange order, no change to protected V117 future Bybit window. No claim of a pristine holdout or profitable alpha.

**Next**: retain this as a negative dedup and cash-accounting calibration example, do not tune `structural_pullback` on the same historical period, and perform a separate preregistered *materially different* mechanism and future-independent validation before contemplating even Demo admission. Current Strategy Finder exhaustion of credible independent candidates remains unresolved by better accounting alone.
