# MR40: one continuous account, January 2023–October 19, 2026

One 10,000 USDT account per strategy/profile, started once on January 1, 2023, with December 2022 warmup. End is October 20, 2026 exclusive: 8,328 four-hour bars, 1,388 days, 45 full months plus 19 October days. All market timestamps are UTC. No monthly/account-boundary reset, terminal liquidation at intermediate study ends, or restart of the admission state.

Unchanged strategies: original `mean_reversion_40_m2` and historical candidate `mean_reversion_40_m2_momentum30_entry_v1`. Four frozen profiles: normal 10/5 bps fee/slippage; stress 25/15; zero 0/0; normal costs with one additional complete four-hour execution lag. All costs are per side. All-cash long/flat, quote-currency fees, no leverage, book depth, partial fills, or quantity-rounding model. No minimum-trade gate, optimization, new strategy/data, or independent qualification. All data were previously used; candidate selection was historical. No promotion or trading API exists in this study.

The original 42-month sample ended while the original strategy held a position and tagged a forced close. This extended account carries that position forward. The original prefix's last mark is therefore checked against the recorded pre-terminal mark, with natural fills unchanged. All four Momentum30 prefix curves already ended flat and remain fully exact. Eight prior prefix controls and eight independent Decimal full-equity paths are checked, alongside the independent admission and recovery oracles. July/August also includes a real carried episode: July 31 16:00 to August 3 16:00 UTC in the candidate. Stitched reset accounts are not equivalent.

`monthly_attribution.csv` separates marked monthly equity PnL from the sum and mean of closed-position PnL. A trade spanning month-end contributes unrealized marks before it closes. A final forced close, if any, is tagged and attributed to the final observed month. This actual dataset ends flat in all eight cases.

## Offline replay

Extract the ZIP and use Python 3.12 (tested 3.12.14):

```sh
python verify_replay.py
```

No downloads, credentials, network or additional packages are needed. The verifier checks every inventoried file, runs seven synthetic tests, recreates the eight complete accounts and prefix controls, and compares results.json and all seven CSVs byte for byte. Full equity, fills, positions, monthly PnL, admissions and drawdown episodes are included. Frozen input files, source ledgers/contracts and modules are independently pinned by input_manifest.json. The archive derives only from the prior October bundle SHA256 `22b7580cd5ecb73c55ef279846841178e360377faf75ff681de88577ee958730`.

Protocol committed before calculation: `b71e99fc4c4a5a8e98aea37ab15d5719c3729b62`. Executable committed before scoring: `3d454b5aee5b4fadd424408be91eb3d87e77311f`. Result digest: `dee122e30911d815f426cef84bb9fa6f5a870291b94240a8265733e57c151bba`.

The earlier July cold control is a 31-day July replay near +195.41 USDT, with a separate 10,000 USDT account and one tagged terminal close. Legacy full-frame identity still differs; numerical agreement is not proof of identity with the original old execution. Neither that result nor this continuous already-seen study establishes a repeatable monthly income.

Research only; Live=false; orders=0; auto_demo=false. Existing apps, Paper profile/journal, scheduling and Laptop1 ownership are preserved. The separately retained research ZIP is export-ignored only for bounded runtime transport; it remains in Git.
