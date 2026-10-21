# July frame provenance evidence

This is a bounded provenance audit of the previously reported July MR40 result.
The original 156-row report package has been recovered and authenticated against
the preserved workbook's report digests. It contains reports, not the old OHLCV
frame. Raw-archive regeneration and independent accounting reproduce the
reported +195.4101 USDT result, while original full-frame identity remains false.

The original/cached/rebuilt hashes are respectively `c75ca7e7...`, `e510acb8...`,
and `8b891500...`. Every rebuilt timestamp and OHLC string equals the accepted
cached frame; 12 volume strings differ by 1e-13 BTC. Those differences describe
rebuilt versus cached data, not the missing original frame. They do not establish
the cause of the original report hash mismatch.

Files:

- `original_reports.zip`: recovered, unchanged four-file original package;
  SHA256 `4207545c556991960d847cc96e8bf3898a2ee63c8a729c4a74863d3a5066a716`.
- `original_workbook_witness.json`: 22 cells from row 34 of `Variants 120`,
  headers, dates and source evidence. Original workbook SHA256 is included.
- `transport_receipt.json`: current official July download, matching the
  original 101,492,248-byte archive hash and all 15,348,822 trades.
- `historical_source_files.json`: exact seven legacy Git blobs / LF SHA256s.
- `original_runtime_witness.json`: original acquisition job's dependency
  versions and selected log lines. Its report-generation job succeeded; the
  downstream physical contract job failed. No entire-workflow success is claimed.
- `audit_numpy253.json`, `audit_numpy235.json`: two raw-stream computations,
  using the existing worker environment and isolated historical NumPy respectively.
- `rebuilt_july_frame.json`, `frame_differences.csv`: one shared frame and the
  complete 12-cell difference table; both computations produced identical frames.
- `hash_schema_witness.json`: actual hash expressions from both historical
  generators, executed on all rebuilt/cached rows with identical results.
- `qa_numpy253.json`, `qa_numpy235.json`: independent standard-library Decimal
  signals/accounts in the four accepted cost/lag profiles. These overlap the
  old July observations and are not new market evidence.
- `rejection_checks.json`: seven actual rejection checks, including a false
  identity claim even after recomputing its audit digest.

## Fast independent verification

From the repository root, extract the **existing** continuous-account archive
into a fresh scratch folder. It contains the pinned prepared inputs and accepted
original results; no raw trade reingestion is needed for this check.

```bash
python -m zipfile -e \
  docs/evidence/mr40-continuous-account-20261021/NEXUS_MR40_Continuous_Account_20261021.zip \
  /tmp/mr40-july-accepted-inputs

python research/verify_mr40_july_frame_identity_v1.py \
  --frame docs/evidence/mr40-continuous-account-20261021/july-identity/rebuilt_july_frame.json \
  --prepared /tmp/mr40-july-accepted-inputs/frozen/prepared_inputs.json \
  --baseline /tmp/mr40-july-accepted-inputs/frozen/original_results.json \
  --audit docs/evidence/mr40-continuous-account-20261021/july-identity/audit_numpy235.json \
  --witness docs/evidence/mr40-continuous-account-20261021/july-identity/original_workbook_witness.json \
  --original-reports docs/evidence/mr40-continuous-account-20261021/july-identity/original_reports.zip \
  --output /tmp/mr40-july-independent-qa.json
```

Expected verification digest:
`31c0391be17f337fc0f8ed07613a0e03aa92ea01b7339b3b8a9bc358dfcbd434`.
The computational checks pass; `original_full_frame_identity_proven` remains
`false`. A passing accounting verification is not a passing identity claim.

## Optional raw reconstruction

Use a separate research environment. Restore the seven legacy files listed in
`historical_source_files.json` from commit
`d60c063a2a79d2359538d48dd6088133c704eb8f` into a fresh `legacy` directory using
`git show COMMIT:FILE`. Keep the files byte-exact. The driver checks their hashes
before processing prices. The original environment pins pandas 2.3.3, NumPy
2.3.5 and pyarrow 23.0.1; requests is also required by the historical imports.

Use `https://public.bybit.com/spot/BTCUSDT/BTCUSDT-2026-07.csv.gz`, SHA256
`72612fea915ecc542c8d2683d957588e4dc5e097138d1af3cafc08a1509675db`.

```bash
python research/nexus_mr40_july_frame_identity_v1.py \
  --raw /path/to/BTCUSDT-2026-07.csv.gz \
  --legacy-root /path/to/legacy \
  --prepared-inputs /tmp/mr40-july-accepted-inputs/frozen/prepared_inputs.json \
  --output /path/to/a-fresh-output-directory
```

The adapter parses text/numeric fields per chunk, concatenates all numeric
trades in source order, and calls the unchanged historical full-month aggregation
and candle integrity gates. It does not invoke the original whole-file reader
unchanged. Both recorded computations ran on Windows/Python 3.12.10, while the
original acquisition used Ubuntu/Python 3.12.14. Remaining reader/platform
differences have not been established as the mismatch cause. Never fit rounding,
volume values, hashes, prices or thresholds to obtain the old hash.

Earlier result receipts, strategy parameters, cost profiles and accounts are
unchanged. Research only: Live=false, orders=0, auto_demo=false. No repeated
raw reconstruction is scheduled; further identity work requires new evidence.
