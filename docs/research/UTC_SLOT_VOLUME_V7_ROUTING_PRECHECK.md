# UTC-slot v7 frontier-routing correction precheck

Recorded before correction on 2026-10-13. Current main remains ed2f16b6aabe7d0d97562fd64bb4e3609dc51b32; Master System Map/AGENTS rules already read and unchanged. Affected preparation source: a4a296182768e17ca45a0f7d3be9a137a7a96f29 (PR2636).

Change: Put the new v7 contract in its own final frontier tier; complete the generic signal test fixture with reviewed v6/v7 inputs.
System Map node(s): RES-30, RES-31, VAL-40, QA-41.
Existing component being changed: Existing _frontier_configs_to_screen routing and generic test fixture.
Why existing component cannot already satisfy the need: CI proves v7 fell into the fixed bucket and preempted historical generated/reviewed tiers. The signal fixture also omits v6 shock/previous-close and v7 clock-volume fields.
Primary runner / execution lane: Hosted/scratch targeted regression and existing GitHub CI; Laptop2 remains later native Research primary. Both laptops Offline; no failover or native workload.
Data source and provenance: No market data inspected or downloaded. Prior frozen v7 contract and terminal v6 ledger retained; actual Ubuntu/macOS CI source/job evidence.
Upstream dependencies: Prior fixed/generated/v5/v6 tier ordering, canonical factory specs/configs and immutable candidate contract.
Downstream consumers: Existing training-only frontier tournament and unit/contract CI.
Authority level: Reversible Research correctness fix only.
Paper/Live boundary: Research-only; Live=false, owner Demo admission=false, auto-Demo=false; no owner 500 USDT profile/install/journal or registry changes.
Duplicate-work check: No completed v5/v6 producer/numeric/Decimal job repeated; preserve original freeze d5d0e8c4f8f78632afa321bbf23ce84ac988827b03b7890575f7277f05b491d4 and candidate digest/fingerprint. Do not change feature math, thresholds, risk rules or selection by outcome.
Failure mode: Any earlier unscreened frontier contract defers v7. Missing/altered required feature or contract digest remains fail closed; tests supply the required reviewed fixture fields.
Rollback: Revert only tier addition/test fixture correction; retain original failures and freeze evidence.
Tests: Re-run actual four failed frontier/generator test functions plus prior v6/v7 regression suites and a new every-prior-tier precedence check. Full hosted CI remains independent and must report actual status.
Independent QA required: Hosted full-suite status remains separate; native strategy evidence and independent numeric/accounting/leakage gates are still unexecuted.
Deployment/cutover impact: Research draft only; no workflows, runner roles or runtime state changes.
Evidence required to declare DONE: Source-bound targeted tests and subsequent exact-head hosted CI; native market research still blocked on physical availability. This fix grants no profitability or qualification.

Observed CI: run38440142955, Ubuntu job115444283825 (4 failed /3685 passed/39 skipped/155 subtests) and macOS job115444283768 (4 failed/3665 passed/59 skipped/155 subtests). Three failures expose tier routing. The fourth exposes missing feature fields in the generic v6/v7 signal fixture; do not weaken factory validation.
