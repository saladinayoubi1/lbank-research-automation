# Laptop1 RDC exit-status repair installed

PR2643 source `45d881fcede297f91f69069d173d676e98cfb8c0` passed all 11 hosted checks, including the Windows, macOS and Ubuntu test jobs. It was merged normally at `db52c90e3e68ff33e905fbd3b6a35101aa5e87ad`. The helper retrieved from the exact source commit matched native SHA256 `c8e31dfcb584c23189087c540b966aabc89fabb978498c94df0236ead1a7da6c`.

A native read-only invocation on Laptop1 exited 0 and verified that the observed full source required the repair. The helper was then applied exactly once: native PID 5128, actual process exit 0, receipt time 2026-10-14T03:48:09.153080Z. Source SHA in the receipt remains the actual code source; this later evidence commit does not relabel it.

| Item | Verified value |
| --- | --- |
| Original CJS SHA256 | `6518fd61948239a6434a5569a5aaad87fc163cce7596377283e02d0889d05083` |
| Installed CJS SHA256 | `d762b259a74aa0b31188dcc02e259bbf9f2c7cd61952bc858297554c2412e35d` |
| Exact original backup | `E:\NEXUS-QA\rdc-l1-exit-20261014T034809153080Z\remote-supervisor.cjs.before` |
| Recovery task XML SHA256, unchanged | `284b39bd04f936372d30f42c798bae76382882b8b84cea22b7338a5ebb8e2c74` |
| Existing Startup SHA256, unchanged | `a8fdc21df5a315308768376cc22f704b316101016e2445abbdd6ccd4b3b29887` |
| Intentional legacy guard SHA256, unchanged | `862595a01549b7b44a920a99670fd99d996584bbae3e44d868efc530c5195944` |

Separate native inspection at 03:50:44Z verified both file hashes and that the only content change was `process.exit(code||0)` to `process.exit(code === null || code === 0 ? 1 : code)`. Task XML, Startup, legacy guard and all four Node PID/path/start-time tuples matched the preinstall snapshot. The existing three Runner.Listener processes and one Runner.Worker remained observed; their lane mapping is not inferred from counts, and none was stopped.

The supplemental process-discovery command failed before its Python discovery body ran because of PowerShell quoting. Its actual exit 1 and output remain recorded. One corrected read-only file invocation (PID 10168, actual exit 0) independently verified the installed/backup hashes and snapshot comparisons. It reported psutil absent, so it does not prove current-client ancestry. The installed helper was not reapplied.

The current authenticated client was not stopped or adopted. The existing Recovery task still invokes the intentionally disabled retired watchdog. This installation affects future CJS invocations; it does not complete automatic recovery or add hang detection. Same-task migration still requires verified independent execution, exact current-client identity, positive old-client exit, one-client adoption, actual restart behavior and fresh ping. Preserve the legacy guard and the task XML backup.

The original prospective architecture precheck is in the parent Laptop1 evidence directory, committed before the repair implementation. Native deployment preconditions and before/after proof are in `native-deployment.json`. Bybit Demo/Paper, owner 500 USDT, Live=false and journal/checkpoint/research state remain outside the operation.
