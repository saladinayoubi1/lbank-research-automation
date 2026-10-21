# MR40 recovery-risk supplement, 2026-10-21

This is a descriptive analysis of six frozen baseline curves, not a new backtest or independent economic qualification. It uses the exact previous research ZIP, SHA256 `074ebdd7ca7712498194817d949b3c712884c9c0efff5d9d8fa4d6a677b11226`. The original ZIP and publication receipt remain unchanged.

Equal peaks recover. Duration begins at the last equal peak before a decline and ends at recovery or sample end. An unfinished episode is right-censored; future recovery time is unknown. Observation shares are close-sample fractions, not intrabar wall time or losing-position percentages. Profitable final capital can remain below a previous peak. Market timestamps are UTC.

From a Git checkout, with Python 3.12 and a new output directory:

```sh
python research/nexus_mr40_underwater_diagnostic_v1.py --archive docs/evidence/mr40-fixed-path-robustness-20261021/NEXUS_MR40_Robustness_20261021.zip --output mr40-underwater-replay --source-sha b60757effe9bb04d4ea3a9f225d0c1431bb99ae6
```

No additional dependencies, network, credentials or data download are needed. Source and definitions were committed before calculation. The three output files reproduce byte for byte. Seven new synthetic tests, six parent curve hashes and six independent Decimal run detectors pass. Result digest: `8cc9d653995eb55d6f1dd848b8d4548e6bf0e5137d34a69f15090750d4755196`.

The separately pinned parent research ZIP remains in Git and is excluded only from runtime `git archive` transport. The existing 8 MiB size limit and required runtime files are preserved; the regression also verifies that the research ZIP remains tracked. See `qa.json` and `docs/research/MR40_RECOVERY_RISK_20261021_FA.md`.

Research only; Live=false; orders=0; auto_demo=false. No installed app, Paper, journal, scheduler or owner changes.
