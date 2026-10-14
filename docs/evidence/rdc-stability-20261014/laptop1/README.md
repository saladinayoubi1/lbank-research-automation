# Laptop1 current RDC recovery: source preparation

The enabled `NEXUS-Remote-Commander-Recovery` task points to the retired 0.2.48 PowerShell watchdog. The intentional `LEGACY_DISABLED.flag` exits that script before its watchdog body. A successful task result therefore does not prove recovery of the authenticated 0.3.0 client.

The current CJS supervisor reports a child clean exit or signal as parent success through `process.exit(code||0)`. The proposed helper changes that expression to `process.exit(code === null || code === 0 ? 1 : code)`, preserving nonzero child exit codes and existing runtime/authentication guards. It verifies the entire observed source digest and physical host, creates a byte-verified backup, compares the source immediately before replacement, and verifies the result. It does not retarget a task or start/stop a remote client.

Seven tests passed locally and on actual Windows Laptop2 (native PID 9304, actual process exit 0). Real harmless Node children demonstrated original clean exit 0 versus repaired exit 1, unchanged failure exit 7, and missing persisted auth exit 22 without spawning a child. The signal test invokes the exact callback in a Node VM; it is not an actual Windows signal test. Byte tests cover exact replacement, idempotence, backup preservation and incompatible-source refusal. Native evidence binds the exact helper, tests and observed CJS bytes by SHA256.

No Laptop1 file/task/client was changed in this stage. The observed CJS lock is absent; its current process ancestry is not verified. A fresh CIM process query returned `Not found`. The unrelated Adobe CCXProcess Node must be preserved. Native process paths and start times alone do not authorize terminating an RDC client.

The next deployment must first pass the hosted matrix. The future-only file repair can then be applied independently of active adoption. Task migration additionally requires a verified independent execution route, exact old-client identity and positive exit, original task XML backup, retargeting the same existing task to the current CJS, and separate proof of one owned client and fresh ping. Preserve the legacy guard. No new persistent supervisor/task or Paper writer is needed.

This evidence does not establish full Laptop1 recovery, hang recovery, sustained remote uptime, fresh market data, or VPS kernel health. Demo/Paper owner 500 USDT, Live=false, journals/checkpoints/research and disabled Laptop2 failover remain unchanged.
