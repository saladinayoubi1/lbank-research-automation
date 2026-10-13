# Distinct-host v6 verification launch

Executed research source: 8899ec6bec4927fc39795f2867be91e2431178c6.
Research lease: isolated-jump-v6-20261013-8899ec6.
QA host: DESKTOP-1R1081M; producer host: DESKTOP-F4SA4VL.
New isolated root: E:\NEXUS-QA\jump-v6-independent-20261013-verify8899.
Existing environment and canonical files are reused read-only. No package install, owner replacement or completed v5 job was performed.

The PowerShell launcher completed with exit 0 and returned child PID 13076 at 2026-10-13T11:18:46.0483457Z. The venv Python worker's own launch receipt records PID 8788. These are launcher/worker identities for the same submission.
The transferred worker SHA-256 ba5226d96e52079f192355727543f3b642aad2aab6bbd4dca19beab8adfc53cf was checked before submission.

First observed native status: STAGING_EXACT_SOURCE at 2026-10-13T11:18:58.681107+00:00, after six raw Parquet checks, runtime-pin checks and the immutable prior-ledger byte check. The source fetch is bounded to 90 seconds and the complete job to 600 seconds. The worker is guarded against reexecution and blocks sockets for the numerical verification.

No numerical replay completion or source checkout completion was observed at this checkpoint. Do not report independent numerical or Decimal accounting PASS from this launch record. After staging, the existing nexus_agent_composite_runtime.verify_independently API recomputes the new v6 result only to compare report and ledger; it does not create a new producer lease or rerun any v5 job. Older receipts, official frontier and owner journal remain untouched. Original producer evidence flags remain immutable snapshots.

Both v6 hypotheses remain negative on training costs and unqualified. Demo admission, Live authority and official Coordinator advancement remain false. The accounting oracle is a separate outstanding gate.

Read status.json, verification-receipt.json and producer/qa-evidence.json from this same root on continuation; if the job is pending or failed, inspect its existing evidence rather than submitting it again.
