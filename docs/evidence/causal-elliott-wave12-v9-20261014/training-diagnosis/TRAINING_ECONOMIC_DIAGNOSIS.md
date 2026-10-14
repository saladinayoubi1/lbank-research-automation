# Elliott v9 Training-only economic diagnosis

The conservative Training paths have almost no positive price contribution to pay for their transaction burden. Algebraically removing the recorded entry/exit price multipliers on the same executed quantities/reference levels gives about -0.20 USDT per BTC round trip and +0.02 per ETH round trip; fees plus slippage are about 2.88 USDT per round trip in each path. Both stress paths hit the existing drawdown guard. This version stays unselected for Demo.

This analysis consumes only the four previously completed Training rows from the byte-verified source-bound native report. Training coverage is 2022-12-01 00:15 through 2025-02-11 09:30 UTC. No new market computation, strategy rerun, parameter sweep or new Validation/final-fold selection was performed. The historical archive and already inspected later folds remain nonpristine; restricting this arithmetic to Training does not restore unseen holdout status.

## Accounting decomposition

The shared engine liquidates every terminal position. Aggregate quote turnover V is executed entry E plus executed exit X. Net closed P/L N includes both entry/exit fees at fixed rate f. Entry is multiplied by 1+s and exit by 1-s for the recorded fixed slippage rate s. Therefore:

$$F=fV,\qquad G=N+F,\qquad E=(V-G)/2,\qquad X=(V+G)/2.$$

$$H=\frac{X}{1-s}-\frac{E}{1+s}=\frac{N+(f+s)V}{1-s^2},\qquad S=H-G,\qquad N=H-S-F.$$

H is a reconstruction on the same executed quantities, decision path and pre-exit-multiplier execution-reference levels. It is not a fee-free or slippage-free strategy simulation: costs change entry bases, stop/target levels, fills, quantity, cash and guard timing. Do not call H a counterfactual strategy return.

| Asset | Cost profile | Closed trips | Net P/L (USDT) | Fee component (USDT) | Fixed-path slip component (USDT) | Fixed-path H (USDT) | H/trip (USDT) | Costs/trip (USDT) | Drawdown halt |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| ETHUSDT | stress | 129 | -996.29 | 608.68 | 365.21 | -22.40 | -0.17 | 7.55 | True |
| ETHUSDT | conservative | 236 | -674.11 | 453.00 | 226.50 | 5.39 | 0.02 | 2.88 | False |
| BTCUSDT | stress | 143 | -1011.25 | 674.87 | 404.92 | 68.55 | 0.48 | 7.55 | True |
| BTCUSDT | conservative | 257 | -790.07 | 493.16 | 246.58 | -50.33 | -0.20 | 2.88 | False |

Conservative BTC: fees about 493.16 USDT and fixed-path slippage about 246.58 contribute to net loss 790.07; fixed-path H is -50.33. Conservative ETH: fees about 453.00 and fixed-path slippage about 226.50 contribute to net loss 674.11; H is only +5.39. Those fee burdens alone are 62.42% and 67.20% of the respective net losses, rounded for description. High activity is present; a minimum-trade rejection is irrelevant to this outcome.

Stress costs/trip are about 7.55 USDT, with fewer trades and drawdown halts. Stress and conservative counts/reference levels differ; they are separate paths and must not be paired, pooled or treated as a fee subtraction on identical transactions. The halt is the configured protection operating, not a missing-entry repair target.

## Evidence and limits

Exact source: `8c06ca692a06611431730e4aeb822b1d9f47f30d`; existing result head: `92f6b4639f5cbc6883683bd184f8d69b52f910eb`. Raw report SHA256 `26bd16779f583d43c8407c65f0830fcccd4700c8b09a0f1cd1e00c5fd087f53d`, report digest `979f39c6848f946deb8765885849c86da2c26702f2789b7b56c62534ed832e0b`. Report Git blob `48de0e4cbb3bbb97414deed5c285905e86a5aabc` was read back at the current head. The helper checks the exact engine component hash and preserved backtest AST-source digest `e44e2bada1efbf2427edfee224d75e96067bfcf1e3fa07b79fa39a09782b9bfb` before using the fixed cost conventions.

The inverse identities are independently checked against two hand-specified closed fills (including a loss) at both frozen cost profiles. Decimal is used for this summary arithmetic only. The available net/turnover outputs are already rounded and accumulated by the original floating-point engine; the recorded display-rounding sensitivity does not certify those engine computations. No independent fill-ledger Decimal/numeric/leakage audit is completed.

Aggregates cannot identify stop/target/time-exit frequencies, late entry, adverse excursion, wave scale, regime failure or full Elliott counting quality. Those are unmeasured causal questions. This diagnosis establishes an observed fixed-path accounting cost burden and very weak reconstructed price contribution; it does not establish which signal microstructure caused it. No claim that all Elliott methods fail is made.

## Concrete next work

Before preregistering one genuinely new hypothesis, check its causal lifecycle against the 121-mechanism/94-contract inventory to avoid duplication. Require an explicit decision-time cost budget and a structural move with room to cover conservative and stress costs; do not relax the fixed risk or cost rules to improve old results. A cost budget is a necessary admission consideration, not evidence of a profitable edge. No numerical gate or new runtime candidate is chosen by this diagnosis.

For the next fresh hypothesis run, prepare source-bound prospective Training fill diagnostics: decision/fill/exit times, raw versus slipped prices, quantities, both fees, exit reason, stop/target/ATR, setup confirmation and completed context. Verify these diagnostics preserve the simulator metrics and execution order. Do not replay completed v9 merely to fill the missing trace, and do not change old signed economic parameters.

Preserve the complete terminal v9 ledger as the exact predecessor: digest `b784b409c16b77fa5d6dd5d65b7f8ed67e13e65aa6d230a74e843f9e63720e8f`, file SHA256 `14cc329d8acd02fbc3a13268826446f44d05dcf9eb299a6c13738558342f401c`. No v8/v9 market replay or observed Validation/final-fold retuning.

Research-only; Live, automatic Demo admission and failover remain disabled. Laptop1 remains sole Paper writer. No owner installation, profile, journal, authentication, Windows recovery or VPS change. System Map nodes: DATA-21 / RES-30 / RES-31 / RES-32 / VAL-40 / QA-41.
