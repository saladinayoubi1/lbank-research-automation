# PR2640 Windows fixture investigation — 2026-10-14
Change: Diagnose the failed actual CMD regression and correct its invocation quoting only after native baseline evidence.
System Map node(s): OBS-80, REL-90, SYS-00.
Existing component being changed: tests/test_nexus_rdc_batch_return.py in existing draft PR2640; repair helper remains source-exact.
Why existing component cannot already satisfy the need: Both baseline and corrected CMD subprocesses return exit1 in hosted Windows job115581495218; stderr was absent from assertions.
Primary runner / execution lane: Existing Laptop2 remote lane; harmless short-lived local fixtures only. No Research/Paper workflow dispatch.
Data source and provenance: GitHub head192bbcfd44c8fa0af2c0fd178de26f23fd1ae243; native DESKTOP-F4SA4VL launcher hash64ea0262d57f43d2c55ddc995c0d492f0edef8380f8e2c7fbcf5c6d770bf3c03; both current RDC pings.
Upstream dependencies: Existing Windows CMD/Python312; AGENTS.md and Master System Map read at the exact head.
Downstream consumers: Existing hosted cross-platform Test workflow; later guarded launcher repair.
Authority level: Test correction and evidence only until exact-head Windows behavior passes.
Paper/Live boundary: Demo/Paper only; no owner state writes; Live=false.
Duplicate-work check: No new RDC client, service, scheduled task, listener, daemon or producer replay. No current-client termination.
Failure mode: Unexpected result/stderr blocks deployment; no changed tolerance or skipped Windows regression.
Rollback: Git parent retains original test; temporary fixtures clean up automatically. Existing native launcher unchanged in this investigation.
Tests: Capture failed list-form and direct CMD command-line baseline/fixed exits and exact child/recovery counts; preserve all original assertions and improve diagnostics.
Independent QA required: Existing hosted Windows lane must verify the committed head; local Windows checks do not claim hosted CI PASS.
Deployment/cutover impact: No launcher application before original PR exact-head hosted Windows behavior gate succeeds.
Evidence required to declare DONE: Correctly bound test/helper blobs, native failure reason, corrected baseline7/1/0 and fixed0/2/2, green hosted Windows behavior at committed head; native application separately recorded.
