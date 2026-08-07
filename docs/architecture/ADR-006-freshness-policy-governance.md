# ADR-006: Freshness policy governance

Status: Proposed
Version: 1.0.0

## Context

Research readiness depends on bounded market-data freshness thresholds. Free-form runtime overrides, non-finite numbers, silent widening, or unversioned policy changes can make stale data appear research-ready and make historical decisions non-reproducible.

## Decision

Freshness thresholds are a versioned safety policy. The active policy is immutable at runtime, deny-by-default, and identified by a canonical SHA-256 digest. Readiness artifacts record the evaluation timestamp, policy version, and policy digest.

The registered v1.0.0 limits are:

- minute15: 1 hour
- hour1: 3 hours
- hour4: 8 hours

Unknown timeframe keys, missing keys, booleans, non-numeric values, NaN, infinities, zero/negative limits, or limits wider than the approved maxima fail closed. Production evaluation does not accept ad-hoc runtime limit overrides.

## Authority and compatibility

Callers may evaluate data under the active registered policy but may not synthesize or widen thresholds. A policy change requires a version change, review of downstream report compatibility, regression evidence, rollback instructions, and updated digest evidence.

## Threat model and abuse cases

Threat actors/failures include mistaken maintainers, compromised automation, test-only overrides leaking into normal execution, malformed numeric configuration, semantic policy downgrade, historical replay under changed defaults, and future consumers treating readiness as stronger authority than research gating.

Rejected cases include:

- `NaN`, positive infinity, or negative infinity;
- an extremely large finite value that widens the stale-data window;
- an unknown or missing timeframe key;
- a runtime override that changes any threshold;
- a policy change whose provenance is absent from generated reports.

## Verification

Positive tests cover normal registered limits, fixed-time evaluation, and report provenance. Negative/bypass tests cover non-finite values, invalid numeric types, widening, unknown keys, and runtime overrides.

## Rollback and recovery

Rollback is a clean revert of the policy-governance change while retaining the earlier stale-data rejection introduced by PR #101. If a false-green policy incident is detected, quarantine affected readiness artifacts, restore the previous-valid bounded policy implementation, regenerate reports from unchanged canonical status data using fixed evaluation timestamps where replay is required, and rerun the complete test suite on one stable head SHA.

## Residual risk

A code-embedded version and digest provide deterministic provenance for this repository revision but are not an external attestation. This control does not authenticate the market-data producer, verify wall-clock trust, or authorize trading. Research readiness remains separate from execution authority.

## Obsolescence triggers

Revisit this ADR when a timeframe or collector cadence changes, timestamp source or clock semantics change, the policy becomes externally configured, report schemas change, Python/pandas numeric or timestamp semantics materially change, or a stale-data/false-green incident occurs.

## Safety boundary

Research and reporting only. No credentials, exchange/broker access, real orders, billing, production promotion, or live-trading authority are introduced.

Refs #102 #101
