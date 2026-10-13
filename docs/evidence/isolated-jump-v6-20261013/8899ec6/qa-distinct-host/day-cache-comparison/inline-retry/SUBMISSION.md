# Native comparison retry with same-process regression

Producer source remains8899ec6bec4927fc39795f2867be91e2431178c6; reviewed verification source remains9144f888306e12a86fb4812896b137c13a6adeb9 and engine blob4c4fc599bf5dabe6c67136dcb4d711f6f47d2610. The day-cache source is unchanged in this retry.

First day-cache worker failed at2026-10-13T12:15:44.283027Z, elapsed65.328seconds, because its child unittest process exceeded60seconds. No native-regression receipt or numeric comparison proof was produced;0cells completed. Native process-exit.txt directly read NATIVE_EXIT=1. The child timeout's partial unit output was not persisted by that worker; it must not be inferred as PASS or a mathematical mismatch. The failed root is preserved.

One materially different retry uses unittest in the same interpreter, live per-test logs/status and a90-second unit deadline with a native thread stack. The overall comparison remains240seconds, and each compared cell is saved atomically. The launcher refuses a nonempty root/log path or Python processes remaining in the prior attempt's launch-time window. It observed prior_window_python_count=0 before submission. Win32_Process CIM queries returned Not found in this session and were not used to claim process absence; the corrected guard used Get-Process and timestamps.

Retry root: E:\NEXUS-QA\jump-v6-day-cache-qa-inline-20261013. Worker SHA-256:f140eaf247239ef5810be80100633d8131ef3be18f7fd25b8e59bbea0412b08d. Launcher completed exit0 at2026-10-13T12:28:54.1874803Z and returned childPID2728. Native first checkpoint at2026-10-13T12:29:17.036585Z: RUNNING_NATIVE_DAY_CACHE_TEST, original scalar golden-metrics test,0comparison cells. No native unit completion or16-cell proof is claimed at this checkpoint.

Exact Git-blob overlay, original data/producer identities, prohibition of producer/full-tournament entry points, no old v5 jobs, and Demo=false/Live=false/officialCoordinator=false remain enforced. Independent Decimal accounting remains incomplete. Original negative study results and unqualified status are unchanged.

Continue only this retry root. Read status.json, native-regression.stderr.log, native-unit-deadline-stack.txt, native-regression-receipt.json, cell-*.json, qa-evidence.json and process-exit.txt. Do not relaunch either failed full verifier/producer or another native unit/comparison attempt. If this retry fails, use its actual per-test/stack evidence or a different safe research task; do not extend limits blindly.
