# Reviewed day-cache comparison submission

Original study/producer source: 8899ec6bec4927fc39795f2867be91e2431178c6. Reviewed verification source: 9144f888306e12a86fb4812896b137c13a6adeb9. Engine Git blob: 4c4fc599bf5dabe6c67136dcb4d711f6f47d2610. The report and receipts retain their original source identity.

The original600-second full verifier and the120-second cProfile diagnostic expired; both immutable failure records are retained. The latter decoded inputs, built features and frozen signals, and stopped in the scalar Timestamp.floor day call in the backtest. Timing under instrumentation does not establish an uninstrumented speedup.

The change computes timezone-aware calendar-day keys once, preserves scalar object conversion and empty-frame handling, and changes no feature, signal, selector, fill, cost or risk constants. AST comparison confirmed every other source node unchanged. Local isolated regression:4tests,20golden original-scalar scenarios and6timezone/DST forms; NumPy2.3.5/Pandas2.2.3. Native exact-blob tests remain a separate gate.

Laptop1 comparison root: E:\NEXUS-QA\jump-v6-day-cache-qa-20261013. Worker SHA-256:8d9d8ad88bf12d4ecfc84657edb889e3debf1ee8ffcdeab2a19e1cb0d5ccbe13. A single launcher completed exit0 at2026-10-13T12:14:34.6790993Z with childPID14132. First native status at2026-10-13T12:14:43.946842Z: RUNNING_NATIVE_DAY_CACHE_REGRESSION; six raw files verified and0comparison cells completed.

The source layout is an exact Git-blob engine/test overlay over unchanged dependencies at Git HEAD8899ec6. Native source-binding.json explicitly identifies this layout and both commits; it does not claim the baseline Git checkout is9144f888. The new v5/v6 declarative contract files are copied with Git-blob checks for their unchanged paths.

After native tests pass, this240-second bounded worker compares the12recorded winner-grid rows and4additional challenger training cells, reconstructs the original Training-only rank, and saves each cell atomically. It prohibits producer/tournament/run entry points. Original producer, novelty ledger, owner install/journal and completed v5 jobs are untouched. A new comparison attestation explicitly records reviewed verification source9144f888, original producer source8899ec6 and original_source_full_replay_complete=false; it must not be mislabeled as the original strict verifier's proof.

No native tests, cell equality or final numeric comparison are claimed complete at this first checkpoint. Independent Decimal accounting remains incomplete. Original v6 negative results and lack of pristine future holdout remain unchanged: Demo=false, Live=false, official Coordinator advanced=false.

On continuation read this same root's status.json, native-regression-receipt.json, source-binding.json, cell-*.json, qa-evidence.json and process-exit.txt. If pending, do not resubmit; if expired, preserve completed digest-bound cells for a bounded continuation.
