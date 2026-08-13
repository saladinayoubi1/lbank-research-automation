# Strategy Activity Sufficiency Gate v1

Status: research/backtest/paper-only. This document does not authorize live trading or financial execution.

## Purpose

A strategy must not be considered research-ready merely because a very small number of historical decisions produced attractive aggregate performance. Activity sufficiency is a separate evidence requirement from profitability.

## Deterministic measurements

For an evaluation series of target exposures, exclude the final target because it has no following bar and therefore cannot execute under the repository next-bar convention. Measure:

- executable bars;
- active bars and active fraction;
- entries: zero exposure to non-zero exposure;
- exits: non-zero exposure to zero exposure;
- direct sign reversals;
- target-change/rebalance count;
- bars per entry.

End-of-test liquidation is not an entry and must not be used to inflate strategy activity.

## Policy

Activity thresholds must be preregistered for each experiment and dataset horizon. They must not be chosen after observing PnL. At minimum, every candidate must state a minimum entry count and minimum rebalance count. Where the research objective requires regular opportunity generation, it must also state a maximum bars-per-entry threshold.

Failure codes are:

- `INSUFFICIENT_ENTRIES`;
- `INSUFFICIENT_REBALANCES`;
- `SIGNAL_FREQUENCY_TOO_LOW`.

A candidate failing activity sufficiency remains exploratory even if return, Sharpe, or drawdown metrics look favorable.

## Statistical interpretation

Activity sufficiency is not proof of edge. More trades do not make a weak strategy valid, and serially correlated trades are not independent observations. This gate only rejects candidates with obviously inadequate opportunity/sample generation before more expensive walk-forward, robustness, and uncertainty analysis.

## Phase 3 acceptance criterion

For each promoted research candidate, the experiment record must contain the preregistered activity thresholds, measured activity statistics for every out-of-sample window, and explicit failure reasons. Aggregate performance may not override a failed activity gate.

## Safety boundary

Research, backtest, and paper evaluation only. No live orders, credentials, signing, billing changes, production deployment, or personalized financial advice.