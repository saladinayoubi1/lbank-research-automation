# Fixed latest-day Momentum30 research test

Code/protocol committed at `8d4415fbd4750243e0d1c9e07d07019224733357` before acquiring October 20 raw Spot trades. This is retrospective evidence, with one added source day and no new strategy trades. It is not a running demo or independent economic qualification.

`results.json` contains the complete four 10,000-unit engine results, the 500-unit normalized accounts, all equity/fill/position/monthly ledgers, six new bars, raw audit and HTTPS receipt. `execution.json` records actual native Windows source identities, timestamps and successful execution; `tests-executed.txt` is the native four-test transcript. `independent_qa.json` verifies accounts/ledgers on the local Python 3.12.14 host without reprocessing raw trades or claiming external provider attestation. `api_preflight.json` records the observed Laptop2 public kline 403 and the scope of that observation.

Reuse unchanged `frozen/prepared_inputs.json` and `frozen/october_input_extension.json` from the previously recorded continuous bundle (ZIP SHA256 `836c57c0704cfc319973beb5868758ae2416deaacdfa1ec8edc91a0973e7788b`). No second copy of those inputs or the raw 7 MB source is committed here.

Account replay, from the repository root:

```sh
python research/verify_mr40_momentum30_newday_v1.py --source . --evidence docs/evidence/mr40-momentum30-newday-20261021 --prefix /path/to/frozen/prepared_inputs.json --october /path/to/frozen/october_input_extension.json --output /new/path/independent_qa.json
```

The output must not exist. Its canonical bytes match the recorded QA. Fresh acquisition uses the new study driver with `--root` pointing to a new directory containing an exact LF copy of `research/mean_reversion_40_m2_momentum30_newday_v1.json` named `study_contract.json`; pass the same source/prefix/october paths, `--protocol-sha ec755a2e31407f5a183d869be5d15a62a37a385fa1cc8bd7b1e6203e713ca4b3` and `--source-commit 8d4415fbd4750243e0d1c9e07d07019224733357`. It refuses an existing result. Normal API access is not required for the archive-based research test, but is still blocked for this attempted demo startup.

Live=false, exchange orders=0, owner Paper mutations=0, scheduling=false. The 500-unit calculations do not model venue lot rounding, minimum fees/orders or live order-book execution.
