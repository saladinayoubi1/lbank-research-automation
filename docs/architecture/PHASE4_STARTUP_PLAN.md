# NEXUS Phase 4 Startup Execution Plan

Parent: #510

## Ordered start
1. Merge Gate 0/1 contract baseline after exact-head CI/review.
2. Build Gate 2 UI/site shell against versioned read-only API contracts; no trading-state authority.
3. In parallel only where file ownership does not overlap, audit Gate 3 data authority and Gate 5 event-domain prerequisites.
4. Do not implement Risk/Paper Execution until Event Store and config/version contracts are stable.
5. Do not enable AI action authority until the AI Control Plane, authority matrix, audit path and deterministic command validators exist.

## Parallelism rule
Parallel work is allowed only for independent modules with non-overlapping authority/state ownership. Shared schema/policy files have a single active owner at a time.

## Merge discipline
One PR should close one coherent defect or Gate slice. Do not replay changes merely because main advanced; rebase/update only when the actual branch requires it. Historical green CI is evidence, not authority for a changed head.

## Initial next slices
- Gate 2: responsive UI/site shell + navigation + global health states + versioned read-only API stubs.
- Gate 5 prerequisite: deterministic event/domain schema from #93.
- Gate 3 audit: classify current data-authority blockers by whether they invalidate Phase 4 canonical inputs.

These slices must not introduce live trading, credentials, production, billing or signing authority.
