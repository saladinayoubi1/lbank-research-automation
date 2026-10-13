# RDC existing-launcher stability precheck — 2026-10-14 Asia/Tehran
Change: Correct the Laptop2 existing remote-supervisor.cmd batch-return bug, verify native crash/return behavior with harmless local fixtures, and assess Laptop1 existing recovery through a non-WMI interface.
System Map node(s): OBS-80, REL-90, SYS-00. RUNTIME-60/PAPER-62 remain unchanged.
Existing component being changed: C:\Users\afaq\AppData\Local\NEXUS-Research\remote-supervisor.cmd; existing Startup wrapper retained.
Why existing component cannot already satisfy the need: It invokes npx.cmd without CALL, transferring the parent batch context so timeout/goto recovery cannot run after exit.
Primary runner / execution lane: Each laptop's existing remote lane; Laptop2 Research primary and Laptop1 owner Runtime/Paper primary roles preserved.
Data source and provenance: Fresh RDC inventory both Online0.3.0; native sanitized scripts and process roles; L1 Schedule.Service COM recovery task enabled/PT0S/restart99x1min/battery allowed. WMI inspection fails locally on L1; no WMI-service reset or Windows update.
Upstream dependencies: Existing authenticated remote profile, installed Node/npx, existing Startup/recovery path. Authentication values are neither exported nor changed.
Downstream consumers: Existing RDC channel and future native launcher recovery. No new runtime supervisor, Paper writer or failover authority.
Authority level: Reversible local remote-launcher repair only; no trading/control authority.
Paper/Live boundary: Live=false; owner500 USDT profile/journal/install/research/checkpoints unchanged. L2 legacy Paper failover remains dormant.
Duplicate-work check: Existing launcher modified in place; no second RDC instance or redundant scheduled service. Current active connection is not killed for testing.
Failure mode: Byte precondition mismatch refuses patch. Failed fixture/exit test blocks deployment; preserve originals. External service/network failure cannot be inferred from one host process.
Rollback: Restore byte-exact local original remote-supervisor.cmd backup; no authentication deletion/re-registration.
Tests: Native CMD fixture demonstrates baseline missing-CALL exit and fixed repeated return; capture true exits, readback script/hash, check both remote pings afterward.
Independent QA required: Native behavioral fixture and raw source readback are operational verification, not strategy QA.
Deployment/cutover impact: One existing local launcher file; active remote process not forcibly restarted. Record current-process adoption/recovery limitations honestly if no safe in-place handoff exists.
Evidence required to declare DONE: Proven batch-return correction, unchanged Startup/auth/runtime roles, native test/readback receipts and fresh connectivity; no claim of failure-proof Internet or long soak.
Governance: unchanged main ed2f16b6aabe7d0d97562fd64bb4e3609dc51b32; AGENTS.md and Master System Map already read in full at that exact SHA.

Current execution boundary: RDC calls subsequently reported no online devices, then INVALID_ARGUMENT even for list_devices. The attempted native PRECHECK write was rejected and is not claimed as saved. GitHub source/evidence writes remain available. Current fixed-head source preparation is permitted; native deployment remains unverified until an independently working route exists. Existing GitHub Local/DR workflows are restricted to main and are not generic remote-repair executors; no protected workflow is changed to bypass that boundary.
