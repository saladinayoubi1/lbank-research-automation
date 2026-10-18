# Source-defined failure-test execution and bounded economic QA

## Concrete problem and implementation

The first complete-system Developer receipt proved artifact reproduction, with
no market replay. Its fixed 1.5-range stop did not implement the failure candle's
invalidation point. The actual shared-cash executor now supports the separately
selected `signal_bar_low_v1` policy. Existing calls retain the original range
policy and numerical execution behavior. Additional ledger fields expose raw
price PNL, slippage, both fees and total friction.

The single candidate's raw DSL bytes and nine signal equations are unchanged.
The new full specification freezes the stop before any financial evaluation of
this complete system. A later loss must remain negative evidence; do not widen
the stop, alter filters, change the window or restart exhausted studies.

## Primary source and operational choices

Primary author: Adam H Grimes, [The Failure Test, 11 November 2014](https://www.adamhgrimes.com/failure-test-2/),
read on 18 October 2026. The committed source note is a short paraphrase, not an
authenticated provider payload. Hashes bind the note's identity only.

The source supplies a failed support test with recovery and a stop at the
failure extreme. The previous completed UTC-day low, next-open execution,
lagged peer filters, higher-timeframe gates, 2R target, 64-bar timeout, two cost
profiles and cash/risk limits are NEXUS research extensions. No website supplied
or endorsed this entire combined system. This is not an Elliott wave counter.

| Component | Frozen executable rule | Attribution |
| --- | --- | --- |
| Context | Existing completed 4h range, completed 1h volatility, positive lagged peer beta residual, lagged downside variance share >0.5 | Research extension |
| Entry | Existing prior-day-low sweep and close above that low/open; close location >=0.6 and relative volume >=1; next open only | Failure-test concept plus explicit research choices |
| Stop | Previous completed signal candle's low, no adjustable buffer | Source-defined invalidation mapping |
| Exit | Worse-open gap stop, timeout at open, stop first on ambiguous intrabar hits, 2R target, final partition close | Source stop plus research execution/exit choices |
| Sizing | Shared 500 USDT; one BTC/ETH position; BTC collision priority; gross <=250; cost-aware nominal gapless loss <=2.5; quantity floored to 8 decimals | Research extension; gaps can exceed nominal loss |
| No trade | No signal, occupied shared book, next open <= signal low, invalid geometry, unavailable cash/risk capacity | Explicit complete-system execution policy |

The existing research diagnostic has no portfolio drawdown kill or venue lot-size
execution adapter. It reports drawdown, fills are historical hypothetical fills,
and its partition end liquidation is explicit. Intrabar exits are bounded to a
15-minute bar, not claimed tick timestamps. Structural-policy gap/timeout exit
events use the actual observable open, with the source bar close recorded
separately. The passive benchmark starts at the same first permitted next open,
not the preceding source bar's open. It cannot qualify a production system.

## Separate source/code overlap review

Reviewer: Codex source/code review, separate from the prior Developer compiler
output. Isolated QA equations and counterexamples corroborate the bounded review.
This is not a claimed outside human review, publisher authentication, global
semantic novelty proof or independent feature-engine implementation.

The reviewed intake's coarse topology signature has no identical factory alias.
That alone is insufficient. The original Python families were also inspected:

| Existing family | Known relationship to the frozen hypothesis |
| --- | --- |
| `failed_range_break_reversal` | Same broad failed-breakout family. Uses rolling `prior_lo`; does not require the previous UTC-day anchor, positive lagged peer residual and downside-variance gate. Two physically possible counterexamples prove neither condition implies the other. |
| `relative_weakness_exhaustion_rebound` | Rolling-low recovery with prior relative weakness and own return gates, rather than the frozen prior-day support and positive residual conjunction. |
| `peer_beta_residual_reclaim` | Requires a sufficiently negative residual and rolling midpoint reclaim; the proposal requires positive residual and previous-day-low failure. |
| `prior_day_breakout_continuation` | Prior-day high continuation in an up regime, rather than failure below the previous day's low in a range. |
| Generated factory combinations | Existing exact qualitative signatures reject metadata/threshold aliases. The proposed conjunction is not an exact signature match; generated legacy executions are included in the 114-mechanism event audit. |

Earlier signal observations found 15 events, 10 shared with the legacy union and
5 unmatched within the already inspected historical window. These observations
do not establish a new strategy family or an edge. The numerical QA worker
recomputes all 114 legacy signal overlaps over the frozen window, without
retuning or running their economic backtests. Its independent nine equations
must match the producer's signals, including finite-value denials.

The separate exact permit approves one falsification of this previously
unevaluated complete structural-stop system. It does not reset the old frontier,
claim that failure tests are novel, or authorize replay of V118/V119, structural
pullback, V52/V101/V117 protocols or earlier economic failures.

## Actual Research execution and numerical QA

The existing `nexus_multitimeframe_strategy_discovery.yml` runs the Research
producer and a separate QA process within its existing approved `discover` job.
The frozen permission policy permits that existing job inventory; no new jobs
or token scopes are added. It reuses the original immutable Bybit archive
restore. Ordinary source pushes still run contracts only. An explicit
`[source-system-evaluation]` merge marker launches the one committed SHA-bound
economic request on main after contracts. Every old discovery/frontier step
still requires manual main dispatch, so this task does not replay the exhausted
discovery. The exact economic worker and its supporting code/dependency locks
are pinned in addition to the six existing executor files.

The actual existing `evaluate_approved` intake is the Research producer. It
checks the candidate, reviewed full specification, implementation hashes,
source notes, frozen window and all six physical Bybit file SHAs before replay.
The window remains warmup 2024-12-01, trial 2025-01-01 through 2025-04-01
exclusive. Every 60/20/20 segment resets one shared 500-USDT book and is labeled
already inspected. No future/OOS or prospective claim is made.

A separate QA process reads the exact completed producer result, independently
authenticates and reloads the six original source files, and checks its own explicit
signal equations and event/cash reference. This reference does not call
`factory_signal`, `replay_shared_cash` or `sidecar_summary`. It checks every
closed trade, entry/exit event, stop/target, quantity, denial, cost, gross/net PNL,
monthly book, average closed-position result, ending cash and drawdown. It also
reports cash-only and equal-budget BTC/ETH buy-and-hold comparisons under the
same costs. Features still use the original shared feature engine; that limit
is declared in the QA receipt.

Each task has a stable `SYSTEM-ECON-...` identity. Its started receipt is uploaded
before market execution, and its completed Research result before QA. A retry
reuses a finished result; a prior started task without a finished artifact stops
for reconciliation instead of silently replaying markets. A committed completed
result can preserve this behavior beyond artifact expiry. QA retries do not
rerun the producer's market evaluation.

Zero trades mean no execution evidence, not a losing system. Negative historical
PNL remains a negative disposition. Historical positive PNL still needs future
evidence and all downstream qualification gates. There is no arbitrary trade
count threshold, automatic promotion, broker order, Paper/Demo admission or
Live authority. All receipts retain `paper_eligible=false`, `live_enabled=false`.

These workflow task receipts are not an Agent Manager numerical-DONE record.
The existing Manager's earlier DONE record covers artifact development only.
Issue #2007 remains open for the broader full-system and Elliott objectives.

## Verification and recoverability

Native synthetic tests exercise the source stop without a range proxy, invalid
opening gaps, adverse later gaps, stop/target ambiguity, shared-book collisions,
timeout, cost stress, exact signal equations, independent QA fault injection,
and zero-activity disposition. Workflow event-matrix tests prevent code-only
or untrusted branch events from running the experiment. Existing complete-system
and physical-engine tests remain required. Real task/result IDs and numerical
outcomes are recorded only after the main workflow actually finishes.

A scoped revert removes the bounded request/permit and restores the original
model path. Historical artifacts, owner apps, journals, profiles, datasets,
frozen observation protocols, credentials, paused VPS and Live flag are untouched.
