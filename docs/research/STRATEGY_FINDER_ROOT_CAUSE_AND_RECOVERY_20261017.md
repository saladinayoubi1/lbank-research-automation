# NEXUS — Strategy Finder root-cause audit and guarded recovery (2026-10-17)

## Proven independent observations

1. Source code: `scripts/nexus_strategy_discovery_controller.py` inventories 8 search stages: 6 historical validation stages (explicitly not autonomous rotation-eligible) and 2 frontier dispatch workflows. It reads `research/strategy_family_catalog.json` with 15 research families. `nexus_multitimeframe_strategy_discovery.py` and `nexus_multipair_strategy_discovery.py` implement exactly three tested families (`momentum`, `trend_breakout`, `mean_reversion`). **A catalog family is not executable strategy code.**
2. Prior main workflow run 39012597910 (Oct 17, 2026) emitted `nexus.strategy-discovery-blocked.v1`, `NEEDS_NEW_REVIEWED_MECHANISM`, `all_exact_reviewed_frontiers_terminal`; reviewed workflow dispatch was skipped. Multiple green rotation workflow runs do not mean strategy production succeeded.
3. `nexus_strategy_discovery_rotation.build_plan` correctly avoids redispatching successful exact terminal/exhausted experiment fingerprints. Failed/unavailable evidence may retry under a separate policy. It will not auto-replay legacy validation or arbitrarily add new unreviewed variants. This constraint prevents false discovery and must **not** be removed to improve activity counts.
4. `research/reviewed_composite_mechanisms_v1.json` contains 29 *design contracts* with structural novelty topology and input requirements. The separate `nexus_strategy_research_feedback.py` produces an unexecuted hypothesis design only from a certified exact-source exhaustion and novelty ledger, not code, proof of profitability or automatic runtime promotion. When no new exhaustion source is emitted, this stage cannot repeatedly claim new discoveries.
5. Economic evidence is a separate failure: earlier Elliott V70 conservative aggregate `-16.6141 USDT` across 10 already-inspected simulated trades; V115–V117 necessary wave filter yielded 9/1212 structurally passing first-stage candidates, with no fully independently certified wave. The isolated, source-pinned compression breakout study in draft PR #2702 was negative on all four prespecified arms across historical Training, Validation and already-inspected Test under fees and slippage; the training-selected arm lost `-866.97/-549.66/-681.17 USDT` in the respective partitions (combined BTC+ETH independent 500 USDT simulations). Never relabel preinspected test as forward/unseen.

## Actual defect fixed in this patch

**Disagreement between controller and dispatch truth:** the code-only controller advertised both stages `READY_FOR_RESEARCH_DISPATCH` after successful **terminal feedback** had already retired their exact fingerprints. A user-facing monitor could therefore report `8 ready` while the rotation honestly refused to run another research experiment. In addition, terminal daily schedule emitted no structured recovery implementation intake; the certified proposal-design pipeline was tied only to newly produced exhaustion receipts.

**Changes in draft PR #2704:** controller accepts optional integrity-verified feedback, marks exact terminal frontier stages separately, preserves six legacy gates, and exposes the actionable `design_and_independently_review_new_mechanism` state. Daily rotation now supplies feedback to the controller and, on a bound blocked receipt, runs `scripts/nexus_strategy_discovery_recovery.py`, emitting a digest-bound reviewed-design *intake artifact*. It lists 29 research designs with input-provenance gaps and marks novelty and implementation unverified. It preserves feedback/dispatch cursor, disallows automated dispatch, promotion and live authority. A design-list record is not a new backtest or permission to skip validation.

## What is NOT solved by these changes

- No reliable, positive-net, independently validated new mechanism exists from this audit alone.
- New hypotheses still require semantic novelty versus the **exact evaluated ledger**, reviewed executable implementation, source-bound independent Bybit historical/forward data, causal next-open and intrabar-stop execution checks, fee/slippage stress, numerical verification and later Demo admission. A catalog row cannot be auto-deployed.
- The new recovery plan does not magically convert 15 documented families or 29 design contracts into trained executable strategies. It repairs the misleading operational status and supplies an explicit review backlog, not an alpha breakthrough.
- No changes to Laptop1, owner Demo/Paper journal/profile/install, Bybit credentials, runner runtime, virtual private server, Elliott V117 research branch, real orders or Live authority.

## Acceptance gates for end-to-end resolution

1. Exact-source evidence: independently verified input/candle timestamps, dataset and previous evaluated-ledger identity.
2. Unique mechanism contract: semantic new topology, not a name/parameter hash relabel; signed/reviewed implementation and no cross-family data leakage.
3. Causal physical producer: confirmed signal timestamp, next-open fill; both stop-first ambiguity and realistic fees/slippage with bounded exposure.
4. Walk-forward validation with untouched future holdout (historical already observed only exploratory); publish trades, aggregate/mean PNL, drawdown, fees and baseline including negative outcomes. **Do not require arbitrary minimum number of trades.**
5. Independent QA and explicit Paper/Demo qualification gate; Live always disabled.
6. Only then register one genuinely new reviewed frontier for autonomous discovery; until then emit terminal design-review state, not false success.

## Repro / CI

The relevant GitHub PR contract job for PR #2704 / commit `d52040f55cf928c8c08553b5d3cffab0c0f817a2` completed successfully: `119 passed, 128 subtests passed`. Other GitHub checks may finish separately. Main deployment is **not** implied by a passing draft PR.
