# MR40 Momentum30: fixed-path robustness audit, 2026-10-21

Unchanged candidate: `mean_reversion_40_m2_momentum30_entry_v1`, BTCUSDT Spot, Bybit, four-hour bars, 10,000 USDT per evaluation account. All market times are UTC. Research only; Live=false; orders=0; auto_demo=false. No application, Paper profile, journal, scheduler, or ownership changes.

This is an already-seen historical stress audit. It is not independent economic qualification, a new strategy, or a prospective test. October has only 19 complete days and two closed positions. October prices were previously used in other NEXUS research. Cohorts overlap or use separate account resets and must not be pooled as independent observations.

## Frozen scope

- Protocol committed before new economic calculations: `0f58362edf77b9484466a4a49d2b6a754c777b9e`.
- Executable and synthetic tests committed before scoring: `205e99a38a7d50e564b22202166e5cbdbac4590f`.
- Source candidate: `764d544af246769ffae0c6aca00d02c00fb34078`; source follow-up: `6d9d0ad3908236ec9c16c4f05fad06c59c38042a`.
- Parent archive SHA256: `22b7580cd5ecb73c55ef279846841178e360377faf75ff681de88577ee958730`.
- Recorded result digest: `a2458859f9462208a6127d738e4a104de6dc066342436692394bc9048d12591b`.

Six baseline curves are reproduced exactly: three cohorts times normal (10 bps fee, 5 bps slippage) and stress (25/15), all per side with one-bar execution lag. Twelve predefined omissions, three fixed extra-cost cases (25/20), and six analytic break-even validations produce 27 accounting paths. No entry/exit/lookback/gate changes, parameter search, or new market data.

Missed winners are selected ex post using positive net percentage returns, descending, with earliest entry as the tie-breaker. The whole selected episode is skipped; the account stays in cash; all later retained entry and exit times remain fixed. Later positions are resized from the resulting cash balance. This is a stress exercise, not an executable selection rule or a probability forecast.

At frozen entry/exit references, final cash equals `10000 * product(exit_reference/entry_reference) * Q**N`, where `Q=((1-f)/(1+f))*((1-s)/(1+s))`. Fees and slippage are fractions per side. Break-even roots are analytic, not a threshold grid. The exact effective combined per-side cost is `(f+s)/(1+f*s)`, not a simple sum. The model does not reproduce order-book depth, partial fills, or exchange quantity rounding.

## Offline replay

Extract the ZIP into a new directory and use Python 3.12 (tested 3.12.14):

```sh
python verify_replay.py
```

No network, account credentials, market-data downloads, or extra packages are required. The verifier checks every inventoried file, runs seven synthetic unit tests, repeats all 27 accounting paths, compares Decimal equity and independent multiplicative final cash, validates six exact baseline curves and six zero-PnL roots, and compares all six output CSV files byte for byte. Result metadata for time and worker is ignored only for semantic replay; economic results and recorded file hashes remain checked.

`recorded_results/` includes full marked equity paths, fills, closed positions, monthly attribution, summary, and cost boundaries. `inputs/` contains exact parent prices, source ledgers, unchanged engine/candidate code, original study contracts, and the October source manifest. `input_manifest.json` pins their bytes and the six parent curve digests. Inputs in this archive are derived only from the hash-verified parent archive; no raw data were redownloaded for this audit.

The prior July cold-start replay near +195.41 USDT belongs to the original MR40 model; exact data identity with the legacy execution remains unresolved because the legacy full-frame hash differs. Numerical agreement is not identity proof. Momentum30 is a separate, later historical candidate. Neither that monthly number nor this audit demonstrates a repeatable monthly income.
