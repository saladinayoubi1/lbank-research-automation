# Elliott V14 — full frozen-archive as-of audit (2026-10-15)

**Native outcome:** `PASS_NARROW_ALL_ARCHIVED_BARS_ASOF_QA`, **0 mismatches of 1,028,352 feature comparisons**.

## Read-only execution and data binding

- Performed on research Laptop2 `DESKTOP-F4SA4VL` using the existing Python 3.12.10 virtual environment and an isolated output folder `E:\NEXUS-QA\elliott-v14-full-asof-qa-20261015`.
- Frozen existing Bybit archive `C:\NEXUS\research-cache\replay-canonical-37681826492\archive`. Six raw file SHA-256 identities are checked against the earlier frozen five-swing market invocation.
- Per symbol (BTCUSDT and ETHUSDT): **128,544 completed 15m bars**, 32,136 completed 1h bars and 8,034 completed 4h bars.
- Independently regrouped 15m prices/volume by UTC into 1h/4h OHLCV and checked against the original hash-bound 1h/4h parquet. No aggregate mismatches above documented numerical tolerance.
- Independently computed all four flags from reaggregated OHLCV and resolved the **last completed higher-timeframe candle for each 15m decision** by binary search on source CLOSE. Independently compared every resulting `h1_vol_ok`, `h1_compression`, `h4_up`, and `h4_range` against the frozen engine's **read-only** `_closed_asof` transform, using its original formulas. All four features were checked at **all 128,544 decision timestamps for both symbols**.
- Per symbol first 3 decisions have no completed 1h bar, and first 15 have no completed 4h bar. The expected NaN absence is preserved. Every subsequent available flag matched exactly. This also includes the first historical rolling-warmup period omitted in the earlier 60,160-check sample.
- **Independent future-tail invariance and closed-bar synthetic checks:** eight new dedicated native tests passed, including nullable aggregated `Float64` warmup. No simulator or economic evaluation invoked.

## Initial failed auditor attempt and correction

The first full-archive attempt reported **1,344 differences** (BTC 672, ETH 672). This was traced to an *auditor-only* pandas nullable `Float64` comparison behavior: warmup comparisons propagated `<NA>` rather than the historical engine's explicit nonnullable-float `False` values. Confirmed on Laptop2 by examining indices 3, 15 and early rolling windows. Corrected the independent script with an explicit nonnullable numeric cast **before** indicator arithmetic, without filling or modifying any input prices, costs, underlying engine code or time decisions. The second full-archive run: **1,028,352/1,028,352 matched**. Failed and corrected evidence remain separate on Laptop2.

## Limits and gates

This establishes the **entire archived source/transform as-of comparison for four 1h/4h flags**, against the unchanged source-frozen `_closed_asof` implementation. It does **not** rerun full `build_features` on all 257,088 15m candles; direct `build_features` was independently checked in selected windows in the earlier [60,160-comparison audit](RESULTS.md). The underlying formulas themselves are not a proof of predictive edge.

**Still not qualified:** recursive true Elliott wave-degree/subwave classification, independent complete original 7-pivot OHLC verification at every event, actual next-open fills and gap/structural stops, positive prospective net expectancy and clean unseen future holdout. This archive is historically inspected. Do not claim a fresh forward backtest or monthly earnings.

**Authority:** Research-only, no producer/backtest/strategy signal, no factory admission, `Live=false`, automatic Demo=false, installed Laptop1/Paper journal untouched, VPS paused. Draft PR #2673 only.

## Reproduction

- Tool source: [full_history_asof_qa.py](full_history_asof_qa.py).
- Unit tests: `tests/test_nexus_elliott_full_history_asof_qa.py`.
- Laptop2 corrected physical `result-v2.json`, `stdout-v2.txt`, `stderr-v2.txt` and `exit-v2.txt`; original first-run evidence `result.json` and `stdout.txt` kept separately.
- Verified source audit engine SHA256 `9931aaeb51a25fb0fbeb5f3b5384ddc8d15eff5b3ccbfc10dd7161ca4b40d2b7`.
