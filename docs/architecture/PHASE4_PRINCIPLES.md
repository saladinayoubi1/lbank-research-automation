# NEXUS Phase 4 Implementation Principles

Parent: #510

1. Root-cause fixes over patch accumulation.
2. Determinism before autonomy.
3. Versioned contracts before stateful implementation.
4. Previous-valid state before availability pressure.
5. Explicit provenance before downstream authority.
6. No silent fallback.
7. One authority owner per state transition.
8. AI proposes/orchestrates; deterministic policy validates/authorizes.
9. UI is an adapter, not domain authority.
10. Evidence proves the fixed revision; evidence alone does not create a new revision.
11. Fail closed on ambiguity, stale/conflicting state, unknown schema or incomplete evidence.
12. Recovery, rollback, observability and obsolescence triggers are part of implementation, not afterthoughts.
