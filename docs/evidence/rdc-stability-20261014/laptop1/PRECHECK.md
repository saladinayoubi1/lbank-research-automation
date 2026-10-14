# Laptop1 current recovery preparation — 2026-10-14
Change: Prepare a source-bound current CJS exit-status repair and stage the actual Recovery-task migration contract. No active client/task cutover in this preparation.
System Map node(s): OBS-80, REL-90, SYS-00.
Existing component being changed: Existing C:\Users\afaq\AppData\Local\NEXUS\desktop-commander-remote\remote-supervisor.cjs and existing NEXUS-Remote-Commander-Recovery task, in separate gated stages.
Why existing component cannot already satisfy the need: The enabled task points to the retired 0.2.48 watchdog and returns immediately when the intentional LEGACY_DISABLED.flag exists. The current CJS also maps child clean exit/signal to successful parent exit, so restart-on-failure cannot recover those outcomes after retargeting.
Primary runner / execution lane: Laptop1 existing remote recovery lane; single Paper owner preserved. Laptop2 remains Research primary and its merged active RDC loop was pinged successfully.
Data source and provenance: Main 3546f22f4eae5c1265326b740a80208fc6b7e934; unchanged/read AGENTS blob 8f43b238b18c4cc6a60ad99266cc36e88ebe5a99 and Master Map blob c616e8081848a0856f620c7866cc000648b490c9. Actual current CJS byte SHA256 6518fd61948239a6434a5569a5aaad87fc163cce7596377283e02d0889d05083; current cache is 0.3.0 and persisted session/refresh presence true, values never exported.
Upstream dependencies: Existing current cache entry, Node, same owner session/profile, source-bound helper and native behavior proof.
Downstream consumers: Future current-CJS invocations; later migration of the SAME existing task, only after positive old-client exit and safe independent execution proof.
Authority level: Reversible remote maintenance only, no trading/dispatch/failover authority.
Paper/Live boundary: Demo/Paper 500 USDT, Live=false; writer/journal/checkpoints/research preserved.
Duplicate-work check: Legacy guard stays; no new task/service/supervisor/client is created. Adobe node 11624 is unrelated and must never be treated as a duplicate RDC. Current authenticated remote is not interrupted by these tests.
Failure mode: Wrong host/hash/content blocks apply; an immediately-before-replace source comparison rejects an observed concurrent edit. This comparison is not an atomic file lock. Missing runtime/auth remains guarded. Never retarget or enable a current-CJS task while an unowned manual client could race it.
Rollback: Byte-verified CJS backup; preserve existing task XML and legacy guard before any later task change.
Tests: Harmless Node child fixtures validate original clean exit versus repaired failure status, unchanged nonzero exit, signal callback, guarded missing auth and byte/backup/incompatible-source boundaries. Fixtures use isolated paths and no real SDK/auth session.
Independent QA required: Existing hosted Windows matrix and actual native Node behavior; native task/ancestry/ping evidence remains a separate rollout gate.
Deployment/cutover impact: Preparation only; future-only code repair does not retarget the task or adopt the currently active manual invocation.
Evidence required to declare DONE: Source/host/backup/readback binding, green Windows behavior, positively stopped old client, same current task routed to same current CJS with one owner, fresh ping. This preparation does not claim complete Laptop1 recovery or hang detection.
