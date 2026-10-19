# Native source-system economic result — 18 October 2026

Task `SYSTEM-ECON-9ad802095258f36a509347c3` finished Research execution and orthogonal numerical QA on main.
Disposition: **HISTORICAL_NEGATIVE_DO_NOT_RETUNE**. This is historical research; economic edge, Paper/Demo admission and Live remain false.

Source: `8bfe55c5fec22a1ba29e6c1dddd9f37b90368961`; [PR2733](https://github.com/saladinayoubi1/lbank-research-automation/pull/2733); [actual workflow run](https://github.com/saladinayoubi1/lbank-research-automation/actions/runs/39107550009).

Each row begins with one shared 500-USDT BTC/ETH cash book. The chronological 60/20/20 segments reset cash separately and are already-inspected history. Their ending cash values are not three simultaneous accounts or one concatenated capital curve. All monetary columns are USDT; drawdown is a percentage.

| Historical segment | Cost | Closed positions | Gross price PNL | Fees | Slippage | Net PNL | Max DD % | Mean closed PNL | Ending cash | Passive BTC/ETH PNL |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| training | conservative | 9 | 6.03853112 | 3.88381091 | 1.94190696 | 0.21281324 | 1.80718159 | 0.02364592 | 500.21281324 | -34.00767845 |
| training | stress | 9 | 5.28103258 | 7.98944981 | 4.79368178 | -7.50209900 | 2.09960382 | -0.83356656 | 492.49790100 | -36.33184748 |
| validation_already_inspected | conservative | 2 | -0.98626235 | 0.81010429 | 0.40505190 | -2.20141854 | 0.83173588 | -1.10070927 | 497.79858146 | -125.33126660 |
| validation_already_inspected | stress | 2 | -0.72286375 | 1.44244669 | 0.86546639 | -3.03077682 | 0.80808213 | -1.51538841 | 496.96922318 | -127.20002496 |
| historical_test_already_inspected | conservative | 1 | 0.82253957 | 0.50057074 | 0.25028557 | 0.07168326 | 0.25512221 | 0.07168326 | 500.07168326 | -2.64096618 |
| historical_test_already_inspected | stress | 1 | 0.71117410 | 1.08199158 | 0.64919655 | -1.02001403 | 0.26886742 | -1.02001403 | 498.97998597 | -5.12156547 |

The conservative model assumes 10-bps fees and 5-bps slippage per side; stress assumes 25 and 15 bps. These are frozen research assumptions, not verified current Bybit fee quotes. The strategy generates 15 signals and closes 12 simulated positions per cost profile: 9 in training, 2 in validation and 1 in historical test. Three signals are rejected because the single shared position is occupied. Counting both cost scenarios does not create 24 independent observations.

Economic interpretation: conservative training gross PNL of 6.03853112 is reduced by 5.82571787 of fees and slippage, leaving 0.21281324. Validation is already negative before costs. The historical test has just one closed position and 0.07168326 net under conservative costs; stress makes every segment negative. These observations do not establish a robust economic edge. No minimum-trade-count rejection is being added.

The passive comparison uses a 250-USDT budget for each asset (500 total), while the strategy has one position with a 250-USDT gross cap. It starts at the same first permitted next open and pays the same modeled costs. It is a descriptive comparison, not risk matched and not used for strategy selection. Cash-only net PNL is zero.

Raw closed-bar signals: `{"BTCUSDT": 7, "ETHUSDT": 8}`. The QA compares 114 original mechanisms without replaying their economic backtests. Event overlap is not proof of global novelty.

Source concept: [Adam H Grimes, The Failure Test](https://www.adamhgrimes.com/failure-test-2/). The previous UTC-day anchor, peer/regime filters, next-open entry, target, timeout and cash limits are declared research extensions. This does not implement Elliott wave counting or automatic website interpretation.

QA uses separate signal equations and event/cash arithmetic and independently authenticates the original market files. It shares the existing feature engine with the producer. It is a distinct process in the existing approved Research job, not an Agent Manager numerical-DONE record or an outside human/source attestation.

## Immutable evidence

- Complete-system raw SHA256: `4301bb8bd33db3c4f706c7d5ee2c610c3c40da5ef0ed254ccce2845ee30f9550`.
- Producer result digest: `9bcae5e9fd401a8dd08c74e89b37af219325e03a824d3d1a56e8bf9a29c5f45a`.
- QA receipt digest: `e2c06a2764b60878c1554a1f37dbb25975fa92aa46ef718b599dc9921a262ffd`.
- Research artifact: `12128189465`; downloaded ZIP SHA256 `8102602e6d527d7904c3e006f697cb63ff9221535b86698980285702ea756303`.
- QA artifact: `12128882380`; downloaded ZIP SHA256 `b29ae0c559fc9395a88c0ceb113762481ca1ab9cfd750129c5e4bb3ec7b6022a`.
- Native final source tests: 116 passed and 144 subtests passed in 16.47 seconds, plus 6 original-signal evidence integrity tests. Exact-head required CI passed on Linux (4089 tests), Windows (4114) and macOS (4069), together with audit and trusted guard.

No arbitrary minimum trade count is imposed. Zero activity is no execution evidence. A negative result must remain negative; do not retune this frozen historical experiment.

Remaining system gaps: the Elliott implementation remains in draft PR2673 rather than main; the numerical receipt here is not an Agent Manager numerical-DONE/qualification/registry admission trace; no untouched future evidence establishes profitability. This negative candidate is not eligible for promotion to obtain such a trace. Research execution is now evidenced, but the broader Elliott/full-system and future qualification objectives remain open in #2007.
