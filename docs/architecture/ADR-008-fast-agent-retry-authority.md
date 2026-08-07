# ADR-008: Fast Agent automatic-retry authority

Status: Proposed

## Context

The Fast Agent coordinator may request a GitHub Actions rerun after a failed workflow. Repository-local state is not authoritative across fresh hourly/scheduled coordinator processes, so using a remembered run ID as the retry-once guard can permit repeated reruns of the same failed execution. The coordinator state schema also advances from version 2 to version 3 to record GitHub `run_attempt` and retry reason evidence.

Automatic rerun is an orchestration capability only. It must not turn an ambiguous or deterministic test failure into a false-green path, and it must never authorize production, credentials, live trading, billing, or risk-policy changes.

## Decision

1. GitHub Actions run metadata is the authoritative source for automatic-retry identity and attempt count.
2. Retry eligibility is bound to workflow name, run ID, head SHA, conclusion, and `run_attempt`.
3. Only first-attempt `timed_out` and `startup_failure` conclusions are automatically retryable. Generic `failure`, cancelled/stale runs, missing identity, missing attempt history, attempt >1, and coordinator self-observation fail closed.
4. Immediately before requesting a rerun, the coordinator must re-read the run from GitHub and reject any identity, conclusion, or attempt drift.
5. If authoritative history cannot be read, automatic retry is disabled for that run; the coordinator must not infer eligibility from local state.
6. Retry decisions emit deterministic reason codes and record run/head/attempt evidence.
7. State schema version 3 adds `run_attempt` and retry-reason evidence. Version-2 state remains readable because new fields are additive/optional to readers; no production data migration is performed.
8. A successful rerun is not independent authorization evidence for merge or release. Merge still requires fixed-head green checks, mergeability, review-thread closure, and the repository's normal change-control gates.

## Alternatives considered

### Persist a local `last_auto_retry_run_id`

Rejected because independent fresh coordinators do not share a trustworthy durable retry history.

### Automatically rerun all failed checks

Rejected because deterministic test failures and policy failures would be retried without evidence that the failure is transient.

### Guess retry eligibility during GitHub API failure

Rejected. Missing authoritative evidence fails closed.

## Compatibility

Schema version 3 is additive for stored coordinator observations: existing version-2 state remains readable, and missing `run_attempt` values disable automatic retry rather than causing an unsafe fallback. No market-data, strategy, broker/exchange, execution, or production schema changes are introduced.

## Threats and failure modes

- stale/out-of-order run listings;
- two fresh coordinators observing the same failed run;
- run-attempt advancement between listing and rerun request;
- head SHA or run identity changing between observations;
- GitHub API timeout/unavailability;
- malformed or incomplete run metadata;
- accidental coordinator self-rerun;
- ambiguous deterministic test failure being treated as transient;
- stale success from a different head SHA.

All ambiguous identity/history cases must fail closed.

## Rollback and recovery

Revert the bounded retry-authority change and this ADR. Until the revert SHA is green, run the coordinator with automatic retry disabled. Do not restore local-state-only retry authorization as a recovery shortcut. Existing state files may retain version-3 additive fields; readers must tolerate them.

## Observability and evidence

Record workflow name, run ID, head SHA, run attempt, retry decision reason, request outcome, and exact evaluation time. For merge/release evidence, use the exact candidate head SHA and repository check results; retry logs alone are insufficient.

## Residual risk

GitHub remains the authority for run metadata and may expose delayed observations. The design reduces duplicate reruns but cannot provide transactional exclusion across two coordinators racing between the final authoritative read and the rerun API call. This residual race must remain bounded by GitHub `run_attempt` semantics and should be revisited if stronger distributed locking or an idempotent rerun API becomes available.

## Obsolescence triggers

Revisit this ADR if GitHub changes `run_attempt` or rerun semantics, the coordinator becomes multi-writer with stronger distributed state, retryable failure classification expands, state persistence becomes production-critical, or an external control plane provides atomic retry authorization.

## Related work

- Issue #114 — durable retry-once defect
- PR #116 — authoritative retry evidence implementation
- Issue #106 — independent control-plane authorization
