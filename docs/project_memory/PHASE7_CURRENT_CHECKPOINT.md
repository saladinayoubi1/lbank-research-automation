# NEXUS Phase 7 current checkpoint — 2026-08-20

Status: ACTIVE until superseded by newer exact-repository evidence.

## Exact repository state

- repository: `saladinayoubi1/lbank-research-automation`
- observed `main`: `a64d65717b248dfc8fdc4e10423f690c071224dc`
- latest integrated change: PR #860 — `Windows: persist owner autostart before runtime hydration`
- open implementation PRs observed before this checkpoint branch: none
- authority boundary: Research / Backtest / Paper only; Live/L4, private exchange credentials, withdrawals, signing, billing and production promotion remain unauthorized.

## Phase 7 issue state

- #696 Phase 7 parent: OPEN pending final fixed-SHA Gate 6 / E2E physical acceptance.
- #697 Lane A / AI Control Plane and Resource Manager: OPEN pending final real-allocation/physical convergence evidence.
- #698 Lane B / Data Intelligence: CLOSED / completed.
- #699 Lane C / Strategy Factory: CLOSED / completed.
- #700 Lane D / realistic Paper execution: CLOSED / completed.
- #701 Gate 0 inventory: CLOSED / completed.
- #702 E2E Proof Mission: OPEN and fail-closed until physical owner-autostart plus returned/offline/reboot proof is complete.

## Current physical evidence

The configured self-hosted Windows runner has accepted real work. The most recent inspected owner-autostart proof before PR #860 was workflow run `32375561620`, artifact `9412772355`, digest `sha256:4a6f68d83e3f9ceb6aa52a205600db420ccdb68f27fb0e59d2765621d2e00a0d`.

That proof failed read-only with:

`scheduled task query failed for NEXUS-ZeroTouch-Autopilot ... The system cannot find the file specified.`

The evidence recorded verifier identity `NT AUTHORITY\\NETWORK SERVICE`, `task_registration_modified=false`, `runner_registration_modified=false`, `live_trading_authority=false`, and `paper_only=true`. This is evidence of a missing owner task, not permission to install it from service context.

PR #860 repairs the discovered bootstrap defect by making `NEXUS-ZeroTouch-Autopilot` persistence independent of first-run Python/venv hydration. Runtime hydration remains daemon-managed/retryable. Physical success is not claimed until the exact package is launched in the owner session and the read-only verifier passes.

## Exact-main Windows package prepared for acceptance

Trusted main-push build:

- workflow run: `32393875911`
- source SHA: `a64d65717b248dfc8fdc4e10423f690c071224dc`
- artifact: `NEXUS_PERSONAL_PRO_FINAL_MISSION_CONTROL_WINDOWS_5_1_0`
- artifact id: `9415985338`
- artifact digest: `sha256:fc71de412e5ce27e029ce110f642da89fa95c9b1512c058f30f2261143948edb`
- Portable SHA-256: `b7fc2bb22e53eff92dfcce545a2870770281290d4f6604a93c13c12056874d9d`
- Setup SHA-256: `ceab3e20a36b6a00500b2bb623fffa49c4f8e78f98ed6027e7421c466c3afb5e`

The artifact is exact-main build evidence only. It does not by itself prove execution, owner task installation, reboot/resume or offline Phase 7 acceptance.

## Next deterministic acceptance sequence

1. Launch the exact `a64d657...` Portable normally in the owner Windows session so the repaired owner-user persistence path can run without service-identity authority expansion.
2. After that physical launch, bind `.nexus/owner-autostart-proof-target.txt` to the exact installed package source SHA and trigger the existing trusted-main read-only owner proof; collect exact run/artifact/digest evidence.
3. Re-run the physical sidecar compatibility proof on the same trusted final SHA and require success.
4. Only after owner-autostart proof succeeds, perform the required reboot/offline/resume/returned-proof acceptance and close #702/#697/#696 if all Gate 6 criteria are satisfied.

Do not work around the owner-session boundary by allowing `NT AUTHORITY\\NETWORK SERVICE` or another service identity to register owner tasks. Do not weaken the verifier, CI, deterministic Risk, or the Research/Backtest/Paper-only boundary to obtain green evidence.
