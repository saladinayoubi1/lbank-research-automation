# First v7 native source gate — completed, not a market backtest

Computation source: 7cab4f0368823ef3dd9dec79f572bd05721e2316.
Native host: DESKTOP-F4SA4VL (Laptop2 Research primary).
Native receipt: 2026-10-13T21:40:57.667634+00:00; actual process exit 0.
30 targeted tests passed; no failures/errors; 11.141 seconds. Runtime and exact source/input bindings are in native-source-binding.json.

The four original pure frontier regressions and 26 causal suites ran from the frozen harness. The wrapper built the suite without calling the harness's output-writing main(), preserving the old copied routing evidence. This is producer-host source QA; no independent strategy QA, market backtest, profitability or Demo qualification is claimed.

The first native stage failed before market execution because the frozen terminal-ledger fixture hash described CRLF bytes, while the exact GitHub blob is LF. Eight other source-file hashes matched. Reconstructing only CRLF yields the original frozen hash; the declared and independently calculated canonical ledger digest are both 18675234ad8c981be8f8c5e348c1a39737a9c3fc4ca09ba0ae9532c8a59b567a. The exact LF fixture's Git blob 9d3f376bc4be787db7b0fa0cd5ee793197b55e70 was read from GitHub and matches the native source archive.

A pre-execution serialization binding records both byte forms; it changes neither the fixture bytes, code, thresholds, risk rules, ledger semantics nor candidate/config. The original study freeze, routing amendment, failed stage and diagnostic are retained. The continuation verified one new candidate and the unchanged native terminal v6 ledger before tests.

Native artifact retrieval verified all 11 source-gate/role receipts against their native SHA256, preserving actual CRLF and BOM bytes. Receipt -> binding, status -> receipt, binding -> amendment and receipt -> stdout links match. Readback ran no tests or backtests.

## Laptop2 role hold

Initial remote inventory observed both Research and Local Failover listeners. By the guarded backup phase the old watchdog had already returned the Local Failover listener to idle/absent; before.json faithfully records only Research PID3952. No claim is made that PID6508 was killed by this hold.

The separate legacy Startup Local/Bybit watchdog wrappers could still start failover from missing/offline GitHub samples despite disabled scheduled autostart tasks. Both exact watchdog processes (7920 and 8880) were stopped; their Startup wrappers were renamed .disabled with originals/backups and matching hashes preserved. Research PID3952 remained unchanged. Native readback found no failover watchdogs, no running WSL distributions, one Research listener and both tasks Disabled.

Two file-based PowerShell invocations failed before mutation (execution policy then parser format); direct guarded cmdlets performed the hold. The later original precheck, before/after receipts and direct command are retained. This hold grants no takeover/fencing or Paper authority. Restore only after real fencing and reviewed activation.

## Next gate

Locate and verify the existing approved Bybit archive root and six raw-file identities, then run one bounded first v7 producer using the terminal v6 ledger. Completed v5/v6 producers, numeric/Decimal jobs and native day-cache units must not be rerun. Distinct-host numeric/Decimal/leakage evidence and unseen prospective data remain separate gates. Live=false; owner state/install/profile/journal preserved.
