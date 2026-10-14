# Actual Windows CMD fixture repair — 2026-10-14

The failed hosted Windows job115581495218 ran parent 192bbcfd44c8fa0af2c0fd178de26f23fd1ae243; both new subtests failed exit1 while3813 suite tests passed. Native investigation on DESKTOP-F4SA4VL reproduced the failure and captured stderr: Python's sequence-to-command-line conversion put literal backslash-escaped quotes around the spaced CMD fixture path, and CMD did not recognize that path. No fixture child ran in either failing case.

The direct CMD command-line form reaches the same parent and child batches with spaces. The unchanged baseline exits7 after one CHILD_RUN and zero RECOVERED markers. The CALL-corrected fixture exits0 after exactly two CHILD_RUN and two RECOVERED markers. Both direct-form cases have empty stderr. The corrected test retains all three existing exit/count assertions, adds stderr diagnostics and requires empty stderr. No skip, tolerance or behavior expectation was weakened.

Native verification: all4 tests PASS, no skip; actual child and PowerShell exits0. Local Linux verification:3 PASS and the existing actual-Windows test explicitly skipped. This is native Windows fixture evidence, not hosted CI or native launcher deployment.

Source binding:
- unchanged helper Git blob:5b9206e4e8f3484c8b7deaec81fa90d9e31ea605
- unchanged helper byte SHA256:3f79acdc3ea2f4140f6bd167b17e0385215945b14c6d552b1fa8a47f0b426b27
- tested corrected test Git blob:01ca4b5dff3959b3c45750ba1c0ef26ccf83096a
- tested corrected test byte SHA256:35114bfda50998e3543d0696d0eead47c8ec7f8673d02dee5f31ba53b464326f
- parent source:192bbcfd44c8fa0af2c0fd178de26f23fd1ae243; corrected test is bound by the above blob/bytes, not relabeled as a preexisting committed head.
- native fixture root:E:\\NEXUS-QA\\rdc-cmd-fixture-20261014T0030Z
- exact received diagnostic and terminal native-test results are preserved in the adjacent JSON files.

Both RDC devices were freshly Online0.3.0 and pinged at2026-10-14T00:23:23.637Z (Laptop2) and00:23:23.892Z (Laptop1). Laptop2's existing five-line launcher still lacks CALL; its Startup wrapper still points to that existing launcher. Deployment was not performed. The active remote was not stopped, another remote client was not started, and no credentials, recovery tasks, Research producer, owner Paper state or Live setting were changed.

Laptop1's sanitized existing CJS was read through RDC without WMI. It rejects an alive lock PID, validates entry/state, spawns one remote child, and exits when the child exits; it contains no in-process heartbeat/hang timer. Its exit handler propagates child code or zero, so previously observed task restart-on-failure settings alone do not establish recovery from a clean exit or hang. No such failure was induced and no Laptop1 change was made.

Pending: hosted Windows CI for the committed corrected source; guarded Laptop2 backup/apply/readback and unchanged Startup verification; current-process adoption remains a separate limitation. Old failed hosted CI and new local/native receipts are preserved rather than overwritten. Remote stability, native deployment, source merge and long-term connectivity are not claimed complete.
