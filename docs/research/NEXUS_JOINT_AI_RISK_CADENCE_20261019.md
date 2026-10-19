# Joint AI review: fixed risk-cadence falsification

The owner authorized Codex to work with the three already connected external
AI conversations on finding or improving the trading system on 19 October
2026. This is a new bounded historical research contract in the
`strategy-factory` lane, preserving the completed Phase 7 accounting and
qualification boundaries. It does not reopen the exhausted factory frontier.

## Recorded before this candidate's economic run

Source main: `7383788754e1f7bef8e70e7df0c765b40e49e6ff`.
Original baseline: `dual_rotation/b4e4a2c33304aec1`.
New contract canonical SHA256:
`f909e7dc8beb34bac0efe13cbb9c8dc128996d42b305089ecae25d7cd39604bf`.

DeepSeek rejected another purported novel momentum/volatility strategy;
Perplexity suggested extra volatility-based de-risking. Codex observed that
the original already volatility-targets at 30%, so an additional multiplier
alone is not evidence of an independent mechanism. A separate timing
hypothesis was sent back for critique: retain weekly entries and winner,
but ratchet the **target** downward at completed UTC day closes. DeepSeek
accepted it as a testable timing hypothesis, not new alpha, and requested
comparison with unchanged and 0.75-scaled baseline. Claude's current page
explicitly said `You are out of free messages until 10:50 PM`; it produced
no fresh strategy answer. Its earlier economic review remains prior input,
not fabricated participation in this round. No quota was bypassed.

One candidate only. No parameter grid, no later threshold changes. Use the
six byte-pinned original Bybit Spot files, ending before 2026-08-01. This is
already inspected history and cannot become fresh out-of-sample evidence.
All frozen future windows and V52/V101/V117/failed Elliott studies stay
unchanged. No account orders, automatic promotion, or new scheduler.

## Rules and planned falsification

Weekly original 42-bar reviews reset winner and target. Between them, at
the close of the 20:00-open UTC 4h candle, cap the previous held target by
the original 30% / 30-day annualized volatility calculation with original
0.25 rounding. No increase or new winner between weekly reviews. Missing
volatility means cash. Weekly reset wins a simultaneous review. New target
executes at the next 00:00 open, through the unchanged original account
engine. No daily target-drift rebalance and no DD20 overlay are added.

For all three fixed cost profiles, the candidate must retain at least 90%
of baseline continuous net profit, reduce DD by at least 3 percentage
points in **each** of the three previously negative reset regimes, and
exceed 0.75-scaled baseline continuous return/DD. These are engineering
falsification hurdles chosen before this run, not significance tests or
investment suitability criteria. Failure means reject this fixed
hypothesis without retuning. A pass would still mean diagnostic-only.

Target state is not inventory: next-open gaps can make a lower target
generate a purchase. The study explicitly audits and rejects historical
daily-reduction buys. An adversarial gap unit witness already demonstrates
that this target-only design cannot guarantee sell-only behavior in general.
It cannot be admitted as a hard risk controller even if that witness does
not occur in this historical sample.

The original engine's `average_exposure` is target mean. The new report also
reconstructs actual marked inventory/equity exposure. Every observed fill
is independently replayed for cash, inventory, fees, adverse fill price,
timestamps and terminal P/L. This corrects reporting interpretation without
changing the pinned baseline implementation.

## Initial technical validation

11 standard-library unittest cases passed locally before economic replay:
daily close/next-open timing; no daily entry/switch; one-way target and weekly
reset; collision priority; missing volatility; malformed inputs; no-change
parity; adverse gap buy witness; corrupted equity rejection; locked contract;
and full future-tail mutation preserving prior features, targets, fills and
equity marks. Existing all-NaN warmup warnings are from the unchanged engine.

Economic results will be appended after the single physical Laptop2 replay.
