# Corrected owner activation continuation — 2026-11-23

The physical Windows stage in run 45183878518, attempt 1, completed successfully on NEXUS-LOCAL-RUNNER (job 137724345591). The original private continuation then stopped before owner mutation: the operational driver's function H was shadowed by PowerShell's built-in h/Get-History alias. Its error handler hit the same alias, so no rollout receipt was produced. The subsequent Local Autonomy job cleaned the shared Actions workspace, removing the original temporary stage evidence.

## Corrected, verified operational wiring

- The original frozen driver and activation helper were preserved.
- A corrected driver uses Get-RolloutPinnedFileSha256 and requires the exact private captured-proof filename and SHA-256.
- Actual Windows AST parsing and invocation of that pure hash function passed. The original journal and frozen activation helper hashes matched.
- Native preflight receipt: E:\NEXUS\NEXUS_OWNER_PAPER_PRIVATE\preflight-fixed-driver-20261123.json
- Corrected driver SHA-256: 23cf1117011e91ad045c346046b09ce7c3bf3f4c701ded70f067147fc2dc7e4b
- Existing activation helper SHA-256 remains 26c35eed16d56ecd93f67664c7412ab18f36a0adb434008e1bd434fdb1007086.
- Read-only physical tests and offline evidence-binding checks passed. Stale source/evidence, other runner, elevated context and Live-authority variants are rejected.

## Exactly one new verification attempt

A new one-shot continuation armed a private, byte-preserving evidence capture before requesting exactly one rerun. GitHub now reports actual run 45183878518 attempt 2 in progress at the same source 3c3461c4e39801232b64f1016cc48edc0ae6b0c5.

No source package is rebuilt and no official artifact is downloaded again. The source, artifact cache and candidate installation remain pinned. The capture copies the real PASS JSON only during the observed actual second attempt, validates its original timestamp and all host/source/artifact/authority fields, and preserves its exact bytes outside the temporary workspace.

Only after GitHub confirms the actual attempt-2 install job succeeded on NEXUS-LOCAL-RUNNER may the corrected wrapper invoke the unchanged clone/rehearsal/preflight/transaction protocol. The original account, journal, previous installation and recovery guards remain protected. There is no new financial writer, account reset, strategy admission or Live authority.

## Current receipts and inspection rules

Private root: E:\NEXUS\NEXUS_OWNER_PAPER_PRIVATE

- continue-owner-3c3461c4-20261123-v2.json — current one-shot continuation.
- rollout-3c3461c4-fixed-20261123-status.json — appears only when the corrected wrapper runs.
- captured-stage-3c3461c4-45183878518-attempt2-<sha256>.json — original captured physical evidence.
- continuation-corrected-protocol-20261123.log — private protocol output.

Never rerun or redispatch based on an old receipt. Read these files, actual GitHub attempt state and process postconditions first. The original journal SHA-256 remains d7b5f4ffefa7ac14d21f51755c42659de72f8f3c0046c97e3a8b999e48310a98. The separate NUL-filled automated portfolio and Bybit HTTP 403 were not repaired or relabelled as recovered. Owner activation and visual account readback have not yet been verified.
