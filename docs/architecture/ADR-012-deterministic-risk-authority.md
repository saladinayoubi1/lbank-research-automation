# ADR-012: Deterministic risk is final paper-execution authority

- Status: Accepted
- Date: 2026-08-17
- Phase: 4, Gate 7

## Decision

All automatic and manual paper signals pass through `deterministic_risk.evaluate_risk`. The function accepts exact, version-bound signal/state/policy contracts and returns one immutable allow/deny decision with a stable reason code. Strategies, AI, UI, agents, and paper execution may propose actions but cannot override this result.

Checks cover freshness and duplicates, canonical symbol/timeframe, exact strategy eligibility, position and aggregate exposure, daily loss and drawdown, session bounds, protective stop/target geometry, kill switch, and data/strategy/provider circuit breakers. Decimal values reject floats, NaN, Infinity, zero, and negative quantities or prices.

## Failure boundary

Malformed or unknown contracts raise `RiskInputError`; policy denials return a deterministic denied decision. No retry changes a denial. Manual provenance uses the identical route. This module contains no exchange credentials, live-order transport, signing, withdrawals, billing, or production authority.

## Recovery

The decision function is pure and does not mutate inputs or portfolio state. Re-evaluation of the same fixed inputs, policy version, and timestamp is identical. Recovery replays the prior verified event/config state and evaluates again; ambiguity remains denied.

## Obsolescence criteria

Replace only with an independently tested deterministic authority that preserves every Gate 7 control, stable reason codes, exact policy provenance, and the paper/live air gap.
