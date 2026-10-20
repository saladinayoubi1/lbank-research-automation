# Fixed forward portfolio: native Windows verification

The native Laptop2 gate for PR2762 is complete. All **22 synthetic test
methods passed in 27.173 seconds**, native exit=0, on DESKTOP-F4SA4VL.
This supersedes the pending-native status recorded in the initial executor
document and initial local verification receipt; those original files remain
unchanged as evidence of their publication snapshot.

The tested source is commit `bc9c128d02e9cb0970441ef4df74a5aa9f5a3b24`.
All eight original published blobs matched the local source snapshot before
staging. The isolated Windows harness rehashed all 16 required source,
contract and test inputs both before and after execution. Every hash remained
identical, including the original portfolio engine and new independent QA.
This evidence update changes none of those executable or test files.

The first launcher selected the global Python interpreter, which lacked
NumPy, and stopped before any test started. The successful run used the
existing `E:\NEXUS-QA\pytest-env\Scripts\python.exe`: Python 3.12.10,
NumPy 2.5.3 and pandas 2.3.3. No dependencies were installed or updated.
The retained native log includes dependency deprecation warnings; the full
22-method suite and actual-current-time status both returned exit=0.

Native evidence is retained under
`E:\NEXUS-QA\portfolio-forward-executor-20261020-bc9c128d`.
The original global-interpreter setup failure is separately retained there
as `initial-launch-setup-failure.json`. The successful receipt and complete
test stderr have been copied byte-for-byte to:

- `docs/evidence/portfolio-forward-executor-20261020/native-verification.json`
- `docs/evidence/portfolio-forward-executor-20261020/native-tests.log`

The native receipt's canonical digest was independently reproduced after
transfer: `cb3aa3d746118662d2d20f3cc338b8dff81a9a62d9a71dc74c138f3ab002254f`.
The complete stderr hash and harness hash also matched. The receipt binds the
16 input hashes, exact interpreter/environment, command, test exit codes,
actual UTC times and actual status output. All market values were artificial;
the 18-cell producer/independent-QA matrix was covered by the same tests.

The actual native status still reports full_horizon_elapsed=false,
source_prices_read=false and financial_result_ready=false. The frozen
2026-10-19 through 2027-01-17-exclusive scoring period has not been read or
backtested. The preparation row remains BLOCKED; no independent worker
lease, economic edge, Manager dispatch or Paper admission is implied.
Bybit only; Laptop1 remains the sole Paper writer; Live=false; orders=0.

The original tested head's latest hosted checks all succeeded. Normal CI
on the evidence-update head remains required before merge. There is no
installed application, journal, profile, workflow, schedule, monitor, VPS or
runtime configuration change in this verification.
