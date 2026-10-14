# Guarded Laptop2 launcher application precheck — 2026-10-14
Change: Apply the previously prepared CALL-only helper to the existing Laptop2 remote-supervisor.cmd after actual Windows CI verification.
System Map node(s): OBS-80, REL-90, SYS-00. RUNTIME-60/PAPER-62 unchanged.
Existing component being changed: C:\Users\afaq\AppData\Local\NEXUS-Research\remote-supervisor.cmd; Startup remains unchanged.
Why existing component cannot already satisfy the need: Existing npx.cmd invocation lacks CALL, so future child exit loses the parent recovery loop.
Primary runner / execution lane: Laptop2 existing remote lane; Laptop2 Research primary and Laptop1 single Paper owner preserved.
Data source and provenance: Source98112d355f6de5e2da3ef472a7eb8395e5813019; exact unchanged helper blob5b9206e4e8f3484c8b7deaec81fa90d9e31ea605 and byte SHA2563f79acdc3ea2f4140f6bd167b17e0385215945b14c6d552b1fa8a47f0b426b27. Existing AGENTS/Master System Map read; only test/evidence changed since their read.
Upstream dependencies: Existing Python312/Node/npx/authentication, physical host and exact observed native launcher; no network/credential substitution.
Downstream consumers: Future invocations of the existing launcher; current-process adoption is not provided by this file edit.
Authority level: One-shot reversible local file repair; no runtime/control/trading authority.
Paper/Live boundary: Bybit Demo/Paper only, Live=false; owner500 USDT journal/profile/install/checkpoints untouched. L2 failover tasks stay disabled.
Duplicate-work check: Before state has one remote client, one npm launcher, one MCP child, one Runner.Listener and zero Worker. No client/daemon/task/service/Research producer is launched.
Failure mode: Wrong host/source hash/launcher hash/Startup hash or unexpected content blocks apply; backup verified before atomic replacement; concurrent edit rejected.
Rollback: Restore helper's byte-verified remote-supervisor.cmd.before from its new timestamped E:\NEXUS-QA\rdc-return-* evidence directory.
Tests: Hosted Test38490483262/windows job115614237862 PASS; Windows suite3813 passed and259 subtests; four native behavior/backup tests previously PASS. All five latest distinct PR workflows success; older Map run467 cancelled and superseded by success468, not represented as PASS.
Independent QA required: Existing hosted Windows lane verifies source with current main; native readback/hash/backup/exit and fresh pings verify the limited operation. No strategy QA claim.
Deployment/cutover impact: Only add CALL in the existing five-line launcher; retain all other bytes. Do not stop/restart/adopt the active client. No credential/Startup/task/WMI/Windows update or failover change.
Evidence required to declare DONE: Host/source/helper hashes, true child/wrapper exit0, exact backup and after bytes, unchanged Startup, same client PID/process roles and disabled tasks, fresh connection. Merge/current-process adoption/long-term stability remain separate.

Fresh native preconditions:
{
  "worker_count": 0,
  "listener_count": 1,
  "observed_utc": "2026-10-14T00:44:35.6454985Z",
  "node_roles": [
    {
      "pid": 8520,
      "ppid": 8864,
      "role": "npm_launcher"
    },
    {
      "pid": 10416,
      "ppid": 5520,
      "role": "remote_client"
    },
    {
      "pid": 9292,
      "ppid": 10416,
      "role": "local_mcp_child"
    }
  ],
  "host": "DESKTOP-F4SA4VL",
  "staged_helper_sha256": "3F79ACDC3EA2F4140F6BD167B17E0385215945B14C6D552B1FA8A47F0B426B27",
  "failover_tasks": [
    {
      "name": "NEXUS-Local-Failover-Autostart",
      "enabled": false,
      "state": 1
    },
    {
      "name": "NEXUS-Bybit-Failover-Autostart",
      "enabled": false,
      "state": 1
    }
  ],
  "launcher_sha256": "64EA0262D57F43D2C55DDC995C0D492F0EDEF8380F8E2C7FBCF5C6D770BF3C03",
  "startup_sha256": "0A4030BFC1FBBE7E8027850001F9498342278EC796A042D6CE82DA3B298BAFAC"
}
