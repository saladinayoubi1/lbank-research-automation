# ADR-025 — Phase 4 Full E2E and Final Same-SHA Evidence

Status: Gate 20 candidate
Parent: #510
Contract: `nexus.phase4-e2e.v1`

## Decision

Phase 4 exits only through one evidence-producing E2E harness bound to an exact Git commit SHA. The harness runs the actual deterministic Phase 4 modules rather than replacing them with mocks.

The accepted path is:

`Validated data -> Qualified strategy -> Signal -> Decision -> Deterministic Risk -> Paper fill/position -> Accounting -> Read-only Dashboard -> Event/Audit -> Restart/Replay -> identical valid state`

The same run also proves AI-control, paper/live air-gap, recovery and resource-bound invariants.

## Actual components exercised

`phase4_e2e.run_phase4_gate20()` invokes:

- `automated_signal_pipeline.run_automated_signal_pipeline()`;
- deterministic Risk and Paper Execution through the pipeline;
- `paper_event_store.replay()` against the complete initial + generated event chain;
- `observability_audit.AuditJournal` and Gate 15 complete coverage validation;
- `ai_control_plane.evaluate_ai_action()` for observe, bounded L3 orchestration and owner-sensitive denial;
- `paper_live_airgap.independent_airgap_check()`;
- `recovery_chaos.AtomicRecoveryStore` / `RecoverySupervisor`;
- `web_dashboard.dispatch_get('/api/mission-control')` through the read-only dashboard contract;
- `resource_bounds` complete Gate 19 measurement/evidence validation.

## AI authority proof

The AI Chat/control path is allowed to:

- inspect current paper status at L0 with no tool route;
- route a bounded reversible workflow through the registered `mission-runner` at L3.

An owner-sensitive production-promotion request is deterministically returned as `owner_required`. The AI path never becomes Risk authority and never directly mutates Paper Execution or accounting state.

## State identity and recovery

The final paper state is projected canonically and SHA-256 bound. Replaying the full paper event chain must produce the identical `PortfolioState`. A simulated post-valid-state mutation followed by process-crash recovery must restore the exact previous-valid checkpoint digest.

The audit journal is persisted to bounded JSONL, read again, hash-chain verified and required to be byte-semantically equivalent at the event-object level.

The dashboard must expose the same final paper state digest and must declare `read_only: true`.

## Security and resource evidence

The final paper command is rechecked by the independent Gate 18 air-gap. Evidence records that live authority is unavailable.

Gate 19 resource evidence is complete for the frozen metric inventory. Runtime/dashboard/replay measurements and configured bounded envelopes must remain below hard denial limits. Soft-limit degradation is acceptable; hard-limit denial fails the E2E run.

## Exact-SHA artifact

`scripts/phase4_gate20_evidence.py` generates canonical JSON evidence, verifies it, and writes a digest-bound artifact containing:

- source Git SHA;
- paper/Risk/fill/accounting state digests;
- dashboard state binding;
- audit head digest and replay identity;
- recovery checkpoint identity;
- AI authority decisions;
- paper/live air-gap result;
- complete resource evidence.

The verifier rejects a source-SHA mismatch, evidence tampering, writable dashboard, incomplete audit/resources, non-identical recovery or any claim that live authority is available.

## Cross-platform and real Windows evidence

The normal test matrix runs Gate 20 on Linux, macOS and Windows GitHub-hosted runners as part of the complete repository suite.

The existing `NEXUS Runtime Worker` PR path is extended without increasing permissions. Its `windows-candidate-validation` job runs on `[self-hosted, Windows, X64]`, executes the Gate 20 E2E test, generates evidence using the exact PR head SHA, and uploads `phase4-gate20-windows-evidence-<head-sha>` with 14-day retention.

This is the required real Windows runtime evidence for the final Phase 4 candidate; it is not a simulated hosted-Windows substitute.

## Test composition

Gate 20 relies on the complete same-head suite from Gates 0–19 for unit, contract, property/adversarial, mutation/bypass, replay/recovery, concurrency and browser/read-only UI invariants. `tests/test_phase4_gate20_e2e.py` adds the final integration/E2E binding and evidence mutation/source-SHA checks.

A Gate 20 candidate is mergeable only when:

1. Workflow Permissions Policy is green;
2. NEXUS Cloud Fallback is green;
3. complete cross-platform Test is green;
4. NEXUS Build Verification is green, including the independent Gate 18 air-gap check;
5. NEXUS Runtime Worker `preflight` is green;
6. self-hosted Windows `windows-candidate-validation` is green and produces exact-head evidence;
7. PR head remains unchanged from the evidence SHA.

## Authority effect

None beyond the already-frozen Phase 4 paper/workflow authority. Gate 20 proves existing behavior; it does not add live exchange credentials, real-order endpoints, withdrawal, production, billing or signing authority.

## Rollback and Phase 4 exit

If Gate 20 fails, Phase 4 remains open and previous-valid `main` is retained. No partial evidence can satisfy the exit criteria.

After exact-head green evidence and merge, Phase 4 may be declared complete only after confirming `main` contains the Gate 20 merge and Issue #510 reflects the fixed acceptance evidence. Live trading remains a separate future scope and is not authorized by Phase 4 completion.
