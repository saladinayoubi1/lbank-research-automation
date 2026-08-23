# Security gate closure checkpoint (2026-08)

This checkpoint maps Issues #43, #58, and #64 to the controls and evidence now
present on `main`. It does **not** authorize production release or live trading.

## Verified controls

| Requirement | Control or evidence |
| --- | --- |
| Bound release manifest, SBOM, and provenance | `release-readiness.yml`, `release_gate.py`, `verify_sbom.py`, ADR-0012 and ADR-004 |
| Two isolated reproducible builds | `reproducibility-proof.yml` creates two clean jobs and compares final bundle and manifest bytes |
| Rollback rejection and previous-valid recovery | `nonproduction_rollback_drill.py` corrupts and quarantines a candidate, then verifies restored previous-valid bytes |
| Keyless build-evidence identity | `reproducibility-proof.yml` attests the complete proof set with GitHub OIDC after successful comparison and rollback drill |
| Cross-platform release verification | `release-readiness.yml` runs the fail-closed gate on Ubuntu, Windows, and macOS |
| Clean Windows DR execution | `windows-dr-keyless.yml` runs on the self-hosted Windows service runner, revalidates the generated evidence, and uploads one bounded bundle |
| Keyless DR identity | the separate `keyless-attestation` job attests the Windows evidence bundle with GitHub OIDC |
| Production and live-trading denial | recovery and release records require production authorization to be false; these workflows contain no live-trading or promotion step |

## Concrete operational evidence

Windows DR and keyless attestation passed in GitHub Actions run
`32673271821` on commit `5577d6a9ff4456570da6948aa11de962c601baef`.
The retained `windows-dr-evidence` artifact was recorded with SHA-256
`7ad22567071b785537946d8b81079e2b775c7efaecc7d7391b29dc5bead9580d`.

## Residual production boundary

Issue #43 remains the canonical production-release block. Production approval,
environment protection, external immutable storage, credential custody, billing,
and irreversible promotion remain manual and outside repository authority. A
green workflow must never be interpreted as production or live-trading approval.

Issues #58 and #64 may be closed as implementation gaps because their bounded
reproducibility, rollback, clean-environment DR, binding, and keyless identity
controls now have executable evidence. Any production-readiness claim remains
blocked by Issue #43 and requires a separate protected human decision.
