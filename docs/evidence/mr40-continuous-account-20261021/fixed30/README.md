# Exact 30-day fresh-account comparison

Fixed UTC window: September 20, 2026 00:00 through October 20 00:00 exclusive (30 complete days, 180 four-hour bars). Each original/Momentum30/profile account starts once at 10,000 USDT with identical complete prior history; the candidate gate initializes fresh at the first executable known decision. Four unchanged cost/lag profiles give eight account paths. No window search, strategy/data change, or independent economic qualification.

The additional 11 September days are flat cash in all eight paths. All fills/positions equal the prior October 1–19 ledger, so no new trade evidence was added. Only two market trade episodes underlie these overlapping calculations.

Use Python 3.12 from a Git checkout, with a new output directory:

```sh
python research/nexus_mr40_exact30_comparison_v1.py --archive docs/evidence/mr40-continuous-account-20261021/NEXUS_MR40_Continuous_Account_20261021.zip --output mr40-exact30-replay --source-sha 36d0e963520e7ca2b6243c6c3cf7b792e0bfafff
```

The existing parent ZIP is required, SHA256 836c57c0704cfc319973beb5868758ae2416deaacdfa1ec8edc91a0973e7788b. No downloads, credentials or additional dependencies are needed. Source was frozen before calculation. All five outputs replay byte for byte; eight independent Decimal account paths pass. See qa.json and MANIFEST.json. Research only; Live=false; orders=0; auto_demo=false. Original accepted results and data archives are preserved.
