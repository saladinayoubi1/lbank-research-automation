# Composite QA → QUAL-42 → REG-50 admission repair

Refs: #2007, #2453. Base: `14b73ea5f873782fa54727592b16d47f91dd09f1`.

## Fault and resulting behavior

The composite runtime producer already had its own validated QA task and
independent replay receipt. The public qualification entry point accepted only
the three simple-family task contracts. In addition, the qualification and
modern registry functions had no production caller: their only calls were in
tests. A green coordinator could therefore leave this stage completely idle.

The existing `evaluate_qualification` and `verify_qualification` entry points now
recognize a distinct native composite contract. The existing registry builder,
verifier, health classifier and non-activating candidate projection recognize
the corresponding typed registry record. The generic task validator and its
family allowlist are unchanged. No composite receipt is relabeled as a
simple-family receipt, and no pipeline/proposal digest is invented.

The composite case retains the full selected mechanism, risk variant, entry
model and factory contract identity; Research source/candidate/report/receipt
identities; physical producer workflow/source/as-of; all six dataset bindings;
both cost profiles; independent QA task/lease/receipt; and the original nested
producer proof. It independently repeats the existing 30-day observation and
cash-arithmetic screen. Self-consistent older short-window QA receipts cannot
be grandfathered into admission. There is no new minimum-trade-count rule.

## Actual coordinator consumer

`scripts/nexus_strategy_admission_reviews.py` reads the persisted Agent Manager
runtime, evaluates its materialized QA tasks and writes immutable, verified
research review artifacts into the coordinator's existing bounded
cache/artifact transport. Each review includes the native qualification and,
only after a valid DONE QA receipt, a non-activating REG-50 candidate record.
Waiting and rejected tasks have no registry record. Empty queues explicitly
report `NO_QA_TASKS`.

The existing Fast Agent Coordinator calls this script after dispatch and both
Paper schedule watchdogs. A failed admission check therefore cannot prevent
those independent operations. It publishes a failure summary and fails its
step, instead of leaving a restored success summary visible. Existing cache
save/artifact export still run under their original `always()` conditions.
No new workflow, monitoring automation, provider, permission or executor is
introduced. Modern admission runs with Python's standard library only; legacy
data-binding imports are deferred until legacy registry functions are called.

## Meaning and limits of registration

`QUALIFIED_FOR_REGISTRY` here means an independently reproduced numerical
**research candidate**, not economic or prospective qualification. The native
record explicitly retains:

- `economic_edge_established=false`;
- `pristine_prospective_evidence_present=false`;
- `owner_shared_500_portfolio_verified=false`;
- `owner_demo_admission_allowed=false`;
- no Demo membership, runtime activation, Paper execution or Live authority.

The existing isolated 10,000-USDT composite evidence is not relabeled as the
owner's shared 500-USDT portfolio. Separate source-bound prospective/economic,
portfolio, Runtime/Risk and reviewed Demo admission remain required. No new
profitable producer, complete website-to-Developer execution, or real accepted
composite registry trace is claimed by this change. The production executable
intake allowlist and its pending semantic review are untouched.

## Validation

Native Python 3.12 on Laptop2, isolated directory
`E:\NEXUS-QA\composite-admission-20261018\source`: **103 tests passed** across the
new full-contract admission tests and existing generic qualification, registry,
composite candidate, runtime requalification, QA and observation suites.
Upstream fixture inputs are synthetic; no candidate, task, qualification or
receipt validator is mocked in the new integration trace. The injected
deterministic synthetic evaluator exercises protocol and accounting checks,
not a physical market study or proof of alpha.

Coverage includes native full-contract success, pending/failed QA, missing or
wrong lease/source/receipt/verifier, relabeled schemas, rehashed provenance and
authority tampering, old 1,000-bar coverage rejection, immutable/idempotent
persistence, real CLI file consumption, failure-summary replacement and
candidate-only projection. The complete positive CLI path is also run with
`python -S`, excluding third-party site packages as in a clean coordinator.
Seventy-one unchanged local input files were byte-verified against the pinned
main tree before native testing. No historical market study was rerun.

Hosted exact-head CI and code review remain separate from these native checks.
Rollback is the scoped commit revert. No installed app, profile, shared journal,
frozen Elliott protocol, Paper writer, exchange credentials or orders changed.
