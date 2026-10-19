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

## Physical historical result: reject this hypothesis

Frozen implementation commit: `e8ef58e450f604e3a8a70e5fe5044b972ce3a2df`.
11/11 tests passed on physical Laptop2 (native exit 0). A bare Python launch
had no NumPy; the existing research virtual environment was used. An initial
research launch stopped during imports before loading prices; the existing
source dependency path was then supplied. Exactly one economic completion,
no candidate or threshold changes, native exit 0, 8034 aligned 4h rows per
asset. All six original source hashes were rechecked before feature loading.

84 account replays = 7 reporting windows x 4 books x 3 cost profiles, **not**
84 independent strategy trials. Each used 500 USDT, sell-before-buy next-open
execution, both-side costs and terminal liquidation. All 84 independent
ledger reconstructions passed; maximum numerical error 4.55e-13 USDT.

Continuous, conservative costs, 2023-09-01 through 2026-08-01 exclusive:

| Book | Net P/L USDT | Maximum DD | Fill events | Actual mean gross exposure |
|---|---:|---:|---:|---:|
| Original fixed rotation | +343.66115 | 34.43365% | 106 | 38.03948% |
| Daily downward target ratchet | +317.41034 | 35.13268% | 119 | 36.90612% |
| Original targets x 0.75 | +255.12463 | 26.92952% | 108 | 28.53484% |
| Passive BTC | +702.11338 | 53.44398% | 2 | 99.96870% |

The candidate lost 26.25081 USDT relative to baseline and increased continuous
DD by 0.69902 percentage points, despite lower mean exposure. 13 extra daily
target reduction events occurred in the continuous window; all were real
next-open sells in this particular sample. The synthetic gap counterexample
still invalidates any universal sell-only guarantee. Fill events are not
independent round-trip trades.

| Reset regime | Original P/L | Candidate P/L | Original DD | Candidate DD |
|---|---:|---:|---:|---:|
| 2023_09_to_2024_03 | +230.86441 | +237.03716 | 14.10073% | 13.47241% |
| 2024_03_to_2024_09 | -60.31239 | -45.31549 | 26.95903% | 21.68379% |
| 2024_09_to_2025_03 | +184.72125 | +184.86224 | 8.87230% | 8.87230% |
| 2025_03_to_2025_10 | +158.98839 | +118.67991 | 12.54529% | 15.29100% |
| 2025_10_to_2026_04 | -46.45443 | -51.28981 | 20.14991% | 21.00122% |
| 2026_04_to_2026_08 | -99.58194 | -99.58194 | 20.99465% | 20.99465% |

The 2024 losing slice improved DD by 5.27524 points, the late-2025/early-2026
slice worsened by 0.85131 points, and the last slice was unchanged. The
candidate therefore fails the pre-recorded each-negative-regime hurdle. It
also underperforms the fixed 0.75 control on continuous total-return/DD.
It retains 90% of original net profit, so **that** particular hurdle passes;
rejection is not manufactured by changing its cutoff afterwards.

| Cost profile | Original net P/L | Candidate net P/L | Candidate DD |
|---|---:|---:|---:|
| conservative | +343.66115 | +317.41034 | 35.13268% |
| severe | +285.97596 | +260.88524 | 35.44383% |
| stress | +320.11395 | +294.33162 | 35.24516% |

Final fixed verdict in all profiles:
`REJECT_FIXED_HYPOTHESIS_NO_RETUNE`. This is a failed fixed risk-cadence
improvement, not proof that all risk timing, cash policies or crypto
strategies fail. Neither the baseline nor the 0.75 comparator is newly
qualified by this diagnostic. Historical passive BTC's larger raw return
carries larger drawdown and different exposure; no equal-risk dominance or
future profitability follows.

The useful system improvement is **observable accounting/risk evidence**:
actual inventory/equity exposure is now reported alongside original target
mean, with a fill-by-fill independent wallet observer and a causal
future-tail mutation test. The pinned original engine and its old field
remain unchanged. This is research tooling, not a deployed Paper risk fix.

Evidence: `docs/evidence/joint-ai-risk-cadence-20261019/result.json`.
Canonical result digest:
`1ad241bf96ee678ee67d7ff1a0311820df98ac6a7fffd5e11f1b1f66204dfe37`.
Full four-book conservative fill/equity traces remain under
`E:\NEXUS-QA\joint-risk-cadence-20261019\results-fixed-v1` on Laptop2;
individual fills/equity canonical digests are in the committed result.

Replay from a normal repository checkout with its locked dependencies:

```sh
python -m unittest discover -s tests -p test_nexus_portfolio_risk_cadence_diagnostic.py -v
python -m scripts.nexus_portfolio_risk_cadence_diagnostic --archive-root <six-pinned-original-archive> --output-dir <new-result-directory>
```

Background checked: Moskowitz, Ooi and Pedersen's 2012 *Time Series Momentum*
original author page describes 58 futures/forward contracts, not this
BTC/ETH Spot rule. It is mechanism context, never evidence that an extra
volatility multiplier or this timing overlay improves NEXUS:
https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum.


## Returned external verdict and Codex corrections

Both available external models received the actual physical result and
returned rejection. Final DeepSeek answer SHA256
`b57d17c2524b7001e6c249846527cae8b54371262ad045a7443f3184bc4ad333`;
Perplexity `c7920aa7bb5781a85ead8caefd9dcf9ae54c79e37d2522fbe786a9a5e093b183`.
Their agreement is commentary, not independent execution or statistical
replication. Exact final answers and methodological corrections are in
`docs/evidence/joint-ai-risk-cadence-20261019/ai-review.json`.

Codex retained the actual hurdle result: 90% profit retention passed. It
rejected claims that every losing regime worsened or that extra fill count
explains the entire loss. Actual fees rose by only 0.54999 USDT; the full
26.25081-USDT P/L difference cannot all be attributed to that fee difference.
No new parameter values or substitute candidate was selected after rejection.
