# Laptop2 dormant-failover restoration precheck

Recorded before mutation on 2026-10-14 (Asia/Tehran); governance main ed2f16b6aabe7d0d97562fd64bb4e3609dc51b32.

Change: Restore the already-required dormant Local/Bybit failover state on Laptop2; preserve the Research primary.
System Map node(s): OBS-80, CTRL-11; PAPER-62/PAPER-63/SAFE-64 authority unchanged.
Existing component being changed: Two existing NEXUS Startup watchdog wrappers and their exact approved watchdog processes; only idle listener(s) from the two failover roots.
Why existing component cannot already satisfy the need: Scheduled failover autostart tasks are disabled, but separate legacy Startup watchdogs still run. The Local watchdog launches a failover after three unhealthy/missing GitHub status samples without fencing evidence.
Primary runner / execution lane: DESKTOP-F4SA4VL; keep C:\Users\afaq\actions-runner-nexus-research listener active.
Data source and provenance: Current native listener executable paths, .runner agentName fields only, no Runner.Worker observed, disabled task states, and the two reviewed existing Startup/script files. No secrets, owner journal or market outcomes.
Upstream dependencies: Existing user-owned Startup files and current process identity; unchanged role contract and source.
Downstream consumers: Existing Research lane and dormant failover registrations.
Authority level: Reversible hold only; no takeover or workload dispatch.
Paper/Live boundary: Live=false; Laptop1 remains the only owner Paper writer; owner 500 USDT state and install/profile/journal content preserved.
Duplicate-work check: No new watchdog/task/runner/scheduler. Stop only exact failover paths and exact watchdog scripts; do not touch primary Research or completed v5/v6 producers/audits.
Failure mode: Any active Runner.Worker, changed process identity or conflicting backup/disabled destination aborts before mutation. Unknown health cannot grant failover. No broad process kills.
Rollback: Preserve original bytes and paths in E:\NEXUS-QA\role-hold-20261014-0042; wrappers can be restored after real fencing and a separately reviewed activation. Do not automatically reactivate this unfenced path.
Tests: Native readback must show one Research listener, zero failover listeners/watchdogs, both failover tasks disabled, and exact original wrapper/script hashes retained.
Independent QA required: Git-recorded native before/after receipt; later real failure/fencing test before any failover activation.
Deployment/cutover impact: Disable only the legacy failover Startup paths and stop their idle processes. No installation, remote agent, Windows/kernel/VPS or Paper writer change.
Evidence required to declare DONE: Actual successful hold/readback with Research primary present and immutable rollback/evidence files. This is not a failover qualification or proof of VPS health.
