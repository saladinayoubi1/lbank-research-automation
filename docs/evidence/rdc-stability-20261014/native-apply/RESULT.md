# Laptop2 existing RDC launcher — guarded CALL application

The helper/test source is98112d355f6de5e2da3ef472a7eb8395e5813019. Hosted Test38490483262 was completed/success on Ubuntu, macOS and Windows; Windows job115614237862 ran its actual CMD behavior test, with3813 suite tests passed and259 subtests passed. Its checkout log binds PR mergefb09a185 to source98112d355f6de5e2da3ef472a7eb8395e5813019 and baseed2f16b6aabe7d0d97562fd64bb4e3609dc51b32. Five latest distinct workflows were successful; an older System Map run467 was cancelled and superseded by success468.

At2026-10-14T00:45:46.233872Z (04:15:46 Tehran), the unchanged source-bound helper ran on DESKTOP-F4SA4VL with actual Python and PowerShell exits0. It added only CALL to the existing five-line C:\\Users\\afaq\\AppData\\Local\\NEXUS-Research\\remote-supervisor.cmd. A fresh precheck and before-state record were written before application. The helper and launcher/Startup hashes were checked before invocation, including a successful read-only helper precheck.

Before byte SHA256:64ea0262d57f43d2c55ddc995c0d492f0edef8380f8e2c7fbcf5c6d770bf3c03.
After byte SHA256:8e09cb51022e86fe672920a4e5c5b960fa83966f37c6872c4685a98acf2bfa12.
Unchanged helper byte SHA256:3f79acdc3ea2f4140f6bd167b17e0385215945b14c6d552b1fa8a47f0b426b27; Git blob5b9206e4e8f3484c8b7deaec81fa90d9e31ea605.
Unchanged Startup SHA256:0a4030bfc1fbbe7e8027850001f9498342278ec796a042d6ce82da3b298bafac.
Backup:E:\\NEXUS-QA\\rdc-return-20261014T004546233872Z\\remote-supervisor.cmd.before.
Native receipt:E:\\NEXUS-QA\\rdc-return-20261014T004546233872Z\\receipt.json.

All9 independent native readback checks passed with actual verifier exit0: physical host, helper bytes, receipt source, original backup digest, corrected launcher digest, CALL-only difference, idempotence, unchanged Startup and receipt-to-byte equality. Backup bytes were read and compared; persisted receipt.json was read by the verifier. The verifier's exact executed source and terminal output are preserved here. The resulting five launcher lines are preserved in verification.json.

Fresh before/after native snapshots show the same three Node roles/PIDs: npm launcher8520, remote client10416 and local MCP child9292. One Runner.Listener and zero Worker were preserved on Laptop2; the Local and Bybit failover autostart tasks remained disabled. Post-apply RDC pings succeeded at00:47:12.112Z on Laptop2 and00:47:12.805Z on Laptop1. This proves connectivity at those times, not continuous remote availability, owner market freshness or VPS health.

The active RDC client was not stopped/restarted/adopted, and no second client, service, scheduled task, runtime supervisor, Paper writer, research producer or monitoring automation was created. Credentials, owner profile/journal/install/checkpoints and Live=false were preserved by the operation's bounded scope. No Windows update or WMI reset occurred.

**Activation boundary:** This corrects future invocations of the existing launcher. The active invocation did not gain parent-CALL semantics retroactively. A source-reviewed, separately evidenced safe cutover is still required before claiming the currently active client has the corrected recovery loop. No destructive crash/disconnection was induced. Laptop1's previously inspected clean-exit/hang limitation remains separate and unchanged.

This evidence commit preserves the native applied-source identity98112d355f6de5e2da3ef472a7eb8395e5813019; it must not relabel that receipt to a later documentation head. The PR remains unmerged until normal exact-head checks/review. Successful bounded file deployment is not a claim of merged source, active adoption, long-term stability, VPS commissioning or strategy qualification.
