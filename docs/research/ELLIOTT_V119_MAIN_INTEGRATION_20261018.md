# Frozen Elliott V119: main research view and independent recorded-path QA

V119's unchanged Wave2 support retest implementation, its original full trade
ledger and an independent accounting audit now feed the existing Research Reports
API/UI and Strategy Workspace catalog. The previous product view only exposed
A6/A7/A9 and incorrectly described every research capital basis as 10,000 USDT.
The Elliott study uses **one shared 500 USDT BTC/ETH Spot cash book**, reset for
each historical partition and cost scenario. Existing A6/A7/A9 evidence and their
10,000 USDT historical reference remain unchanged.

This is a transfer of a completed, rejected study, **not a new historical backtest**.
No signals were regenerated, parameters selected or old frontier cycles reset.

## Source identities

- Original draft commit: `1b8066939d3790cb3dd558946e5f19b25a96d646` (PR #2673).
- Unchanged engine SHA256: `c19d49e644fe0067e405b5cc25366f54b33d403c5445bd9dd56d7210c9de1672`.
- Original full ledger, now persisted as `product_ui/research-reports/elliott-v119-completed-study.json`:
  111,981 bytes; raw SHA256 `46be9c744f14d73d0be391f3b164d127ef93e5bcc80f701225b34ab8838e2546`;
  canonical result digest `bd27b37d66caabfd79e7d19ad158bdf665e0efce51772167e98ea05957f90fb8`.
- Independent fixed-path QA digest: `4b3f45e619c1e3814a9b60400e58127673af3ffb6b69a30589bbeda1c967dd0a`.
- Bybit archived BTC source SHA256: `c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226`.
- Bybit archived ETH source SHA256: `ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1`.

Each asset has 128,544 aligned 15-minute bars, 2022-12-01 through 2026-07-31 UTC.
The matching immutable sources were found on Laptop2 at
`C:\NEXUS\research-cache\replay-canonical-37681826492\archive\bybit_market`.
Other older caches had different hashes and were not substituted.

## What the independent audit established

`nexus_elliott_v119_accounting_qa.py` never imports the strategy engine. It checks
only the fixed, already recorded trade paths with Decimal arithmetic against the
two byte-pinned physical sources: next-open prices, entry slippage and fees,
quantity, shared cash, notional/risk bounds, first physical stop/target/timeout,
exit-bar timestamp, cash proceeds, net PnL and monthly reconciliation. The
predeclared timeout/partition-end OPEN exit precedes that bar's intrabar bracket;
on other bars stops precede targets and gaps use the worse physical open.

Laptop2 execution in `E:\NEXUS-QA\elliott-main-integration-20261018` exited 0:
six partition/cost cells, 154 costed rows for **77 unique recorded paths**, and
74 monthly rows checked with 0.000001 USDT absolute reconciliation tolerance.
Gross, fees and slippage below describe those same recorded paths and quantities;
they are not separately selected zero-cost backtests.

| Historical partition | Cost | Trades | Gross USDT | Fees USDT | Slippage USDT | Net USDT |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Training | Conservative | 42 | 6.69930255 | 19.66829789 | 9.83415062 | -22.80314596 |
| Training | Stress | 42 | 4.68625400 | 37.32705680 | 22.39624462 | -55.03704742 |
| Inspected validation | Conservative | 19 | -7.68363982 | 8.17188627 | 4.08594121 | -19.94146730 |
| Inspected validation | Stress | 19 | -6.11574788 | 15.00473800 | 9.00282904 | -30.12331491 |
| Inspected historical test | Conservative | 16 | 4.63565234 | 7.36229142 | 3.68114687 | -6.40778594 |
| Inspected historical test | Stress | 16 | 2.91548355 | 13.58327049 | 8.14996885 | -18.81775580 |

Different cost scenarios change risk-constrained quantities; counts are not added
across scenarios. Partition cash resets also prohibit treating their totals as
one continuous portfolio. Of 1,109 original signals, 894 failed the fixed
reward/risk gate; conservative fills closed at 48 stops, 26 targets and 3 timeouts.
These original funnel counts are preserved, not independently regenerated.

## Existing consumers and authority

- `ResearchReportStore.snapshot()` publishes a fourth hash-verified report through
  the existing `/api/product/research/reports` endpoint; missing or modified ledger
  or QA evidence rejects only that report. The UI shows six rows, monthly results,
  reference capital, gross/friction/net/mean and fixed context/entry/exit/sizing/
  no-trade rules. Missing equity drawdown stays null/—; closed-cash drawdown is
  explicitly a different metric.
- Strategy Workspace adds `research:elliott_wave2_support_v119` as an archived,
  historically rejected research focus. Its selection cannot run a legacy preset
  and cannot qualify or promote a strategy. Existing owner proposals and journals
  retain their storage and behavior.
- Disposition: **HISTORICAL_NEGATIVE_DO_NOT_RETUNE**. Paper eligibility, automatic
  Demo promotion and Live remain false. No user application was installed or
  restarted; this change updates source and the existing API/UI implementation.

## Limits and remaining work

This is a frozen three-pivot Wave0/1/2-like structural mechanism, **not full
recursive Elliott wave counting**, degree/alternative-count resolution, a full
regime framework or a profitable comprehensive trading system. All validation and
historical test data were already inspected; there is no pristine future holdout.
The original ledger lacks pivot/retest/reclaim signal indices, so this new audit
does **not** independently certify signal-to-entry causality or pivot identity.
The unchanged original 17 unit tests check synthetic chronology and mechanics;
they do not replace that missing source-level signal trace. Exchange lot/tick
rules, bid/ask fills and live order behavior are not established.

No Elliott Manager execution/QA receipt, QUAL-42 admission or REG-50 candidate is
invented by projecting these files. The wider task in #2672/#2007 remains open.
V52/V101/V117 future freezes and their data gates are untouched. This negative
V119 outcome must not be retuned or replayed on the inspected historical windows.

## Validation

- Laptop2 focused tests: **30 passed in 3.59 seconds**, including the unchanged
  original 17 and 13 projection, tamper, cash/selection and physical-exit checks.
  Native staging bundle SHA256: `f7a5e4ce9726dc88acf11f3b66739ac0a0c894cc3c26fa7a98d9ad4017ea6d4f`.
- Node behavior check: existing research-data script now checks correct 500 USDT
  Elliott capital, six-cell historical data, monthly rendering, missing drawdown,
  isolation from A6's data claims and HTML escaping. Both changed UI scripts parse.
- Existing report HTTP and Strategy Workspace HTTP tests cover the fourth report
  and rejection of Elliott execution without any Paper journal mutation. Full
  repository checks run on the exact PR head before merge.
