# Laptop1 detached execution drill — 2026-10-14

Change: Prove one native Python child can continue outside a disposable job after its own diagnostic parent exits abruptly. Add the completed PR2646 native identity result as append-only evidence.
System Map node(s): OBS-80, REL-90, SYS-00.
Existing component being changed: Execution-route verification for the existing Laptop1 Recovery-task migration. No real RDC/task/runtime configuration is changed by the drill.
Why existing component cannot already satisfy the need: CIM route is unavailable. Native identity query succeeded, but process fingerprints and a normal caller exit do not alone prove survival of job cleanup during a later handoff.
Primary runner / execution lane: Laptop1 same-owner/session one-shot diagnostics; Laptop2 Research primary and Laptop1 single Paper owner retained.
Data source and provenance: Main 7a97b473aa6e41562f30bce64ed59c63ecfaec14; PR2646 native source 306645a71f6c7061402d3a7b3239a0ae26b90733, probe SHA256 7cc6893ebb6e7e149e699f4c7e1e4c28278dc6140f08732f668aab811994eb7e, actual install/query exits 0. Isolated psutil 7.2.2 native DLL SHA256 0035450801bd7d938e9e146c5ec28e619cb5a5f4a18cdc53ac7e9734c7f94f78.
Upstream dependencies: Existing Python 3.12 amd64, verified isolated psutil target, typed Win32 APIs and immutable prospective drill source. No new package or global site-package change.
Downstream consumers: Later bounded same-task handoff only after exact identity/hash/owner/session/positive exit checks. The drill is not client cutover authority.
Authority level: Create only two harmless diagnostic Python processes and a private unnamed job object; assign only the diagnostic parent itself. No real SDK/client/runner termination.
Paper/Live boundary: Bybit Demo/Paper 500 USDT, Live=false; credentials/profile/journal/checkpoint/research/install remain outside scope.
Duplicate-work check: Exclusive evidence directory, one launch, no task/service/daemon/watchdog/client/writer. Adobe and runner processes are preserved. No WMI reset or Windows update.
Failure mode: Wrong host/bits/dependency hash or preexisting run directory fails closed. Parent/worker waits bounded. Failed drill blocks handoff. Parent is the only process deliberately exited; no arbitrary PID termination API exists in this source.
Rollback: Diagnostic parent exits; private job is destroyed; detached diagnostic child is bounded and exits after writing its receipt. Evidence retained.
Tests: Native job layout 144 bytes, parent in private KILL_ON_JOB_CLOSE/BREAKAWAY_OK job, child created with BREAKAWAY+DETACHED and no inherited handles, child verifies same owner/session and positive parent-handle exit before terminal PASS. No actual external worker exit code is claimed without capture.
Independent QA required: Native source-bound worker terminal plus separate actual parent exit and preserved RDC ping; hosted source checks before use in any mutating controller.
Deployment/cutover impact: Diagnostic fixture only; current authenticated client and old guarded task remain untouched.
Evidence required to declare DONE: Parent actual exit 0, worker outside every job, same owner/session, positive old diagnostic parent exit and terminal proof after that exit. Full task recovery remains separate.

Primary API references:
https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information
https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information
https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags
