# RDC stability inspection — partial repair prepared, native deployment blocked

Both devices were Online0.3.0 at the first inspection. Laptop2's Startup wrapper targets its existing remote-supervisor.cmd. The five-line supervisor invokes npx.cmd without CALL; its parent recovery loop cannot resume after a child batch exits. Three Node processes were an npm launcher, one remote client and its local MCP child, not three independent remote clients.

Laptop1's existing NEXUS-Remote-Commander-Recovery task was verified through Schedule.Service COM: enabled, last result0, no execution-time limit, 99 restart attempts at one-minute intervals, allowed on battery. Its Startup VBS targets the existing desktop-commander-remote/remote-supervisor.cjs. The full CJS/recovery logic could not be read before RDC access failed; no stability guarantee is inferred from task settings. WMI/CIM inspection on Laptop1 returned Not found; no WMI reset, Windows update or unrelated repair was performed.

Later RDC calls reported no online devices and then INVALID_ARGUMENT, including list_devices. A later successful inventory confirmed both devices Offline. The native PRECHECK write was rejected; no native repair is claimed. GitHub reads/writes remained available. Existing main-only Local/DR workflows were inspected and are not generic remote-repair executors; protected routing was not bypassed.

The repair helper changes only CALL on the exact observed Laptop2 launcher, preserves every other byte, refuses unexpected/auth-bearing content, retains a verified backup and never stops/restarts an active remote, changes credentials or starts another client. It affects future launcher invocations only. Existing-source/host binding and atomic replacement remain required when applying it after reconnection.

Local verification: three checks PASS, one actual Windows CMD behavioral regression explicitly skipped on Linux. The existing Test workflow has Ubuntu/Windows/macOS coverage and will run the real nested-batch failure/return regression after this draft PR is opened. Hosted tests are not proof of laptop deployment.

Deployment performed=false. Credentials/profile/install/owner500 USDT journal/checkpoints/research retained; no new scheduled task/service, Paper writer, failover activation or ChatGPT monitoring automation. Live=false.
