# Isolated MR40 improvement study

The user requested separate strategy development and backtests. The active
500-USDT local LBank Paper trial retains its pinned execution files and policy.

- Protocol commit: `4b741bd0480ef9cf754f71a27826b06e999566a0`.
- Code frozen before evaluation: `f36ff34e2f84f697f89d9771abc80a6debc3376e`.
- Eight fixed paths: baseline, six proposed variants, and a 50%-allocation control.
- 432 independently replayed ledgers, nine synthetic tests, 24 prefix checks.
- Training-only selection retained the baseline; no stable improvement qualified.
- Confirm3 improved the recent LBank sample but had lower full-history normal
  profit and higher drawdown. Full results, including weaker variants, are kept.

`results.json` contains every window/profile/capital metric and walk-forward
selection. `lbank_history_rejection.json` records why the attempted long LBank
history was excluded. No rejected candle was repaired, dropped, or imputed.

Download and extract `NEXUS_MR40_Isolated_Improvement_20261022.zip`, then run
`python verify_replay.py` using Python 3.12+. The ZIP contains pinned inputs,
all source dependencies, tests, every deduplicated fill ledger, equity witnesses,
and the recorded results. Replay needs no network, third-party packages or keys.

`replay-verification.txt` records the actual extracted-ZIP verification.
`equity_drawdown.png` plots continuous full-history accounts with normal costs.
The ZIP and duplicate figure are excluded only from the bounded runtime source
archive; they remain in Git and in this evidence directory.
