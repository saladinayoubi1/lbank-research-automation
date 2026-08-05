# ADR-0013: Reproducibility and rollback claims require bound evidence

- **Status:** Proposed
- **Version:** 1.0.0
- **Date:** 2026-08-06
- **Decision owner:** NEXUS security governance
- **Review date:** 2026-09-06
- **Related:** Issues #43 and #58; PR #57
- **Obsolescence triggers:** build toolchain or lockfile changes; supported platform or archive format changes; provenance/trust-root changes; schema migration changes; rollback, restore, false-positive reproducibility, or builder-compromise incident.

## Context

The repository can compare two supplied output trees and validate the syntax of rollback metadata. Those checks are useful bounded controls, but they do not prove that outputs came from isolated clean builds, the same trusted source, an approved builder, immutable previous-valid state, or an operationally recoverable production system.

## Trust boundaries and assets

Source revision and locked inputs -> build environment -> output trees -> manifests/provenance -> previous-valid record -> protected rollback approval -> target environment.

Assets include source-to-artifact correspondence, build independence, artifact and metadata integrity, schema/data compatibility, previous-valid immutability, authorization records, recovery evidence, and RPO/RTO claims.

## Decision

1. `compare_outputs` establishes equality of the supplied file sets only. It must not emit or support a production reproducibility claim without independently bound build evidence.
2. A reproducibility claim requires the same exact source commit, declared build instructions, locked dependencies/toolchain, recorded relevant environment, isolated clean build attempts, and bit-identical specified artifacts.
3. Build evidence must bind source commit/ref, workflow identity, builder identity, parameters, artifact digests, policy version, and freshness. Missing or untrusted fields fail closed.
4. Previous-valid state must be immutable by policy and selected by exact digests plus trusted provenance, never by mutable tag, branch, filename, or newest timestamp alone.
5. Rollback remains unauthorized by default. Approval must occur at a protected human boundary outside mutable repository metadata.
6. `schema_compatible: true` is not evidence. Production rollback requires measured migration/downgrade compatibility and target-side verification.
7. Reproducible-build, rollback-ready, restore-ready, RPO/RTO, disaster-recovery, and production-ready claims remain blocked until pipeline and drill evidence exists.

## Threat model and abuse cases

| Threat or abuse case | Required behavior |
|---|---|
| Two malicious builders produce identical malicious outputs | Equality may pass; trusted source/provenance and independent review remain required |
| Outputs originate from different source commits | Reject |
| Builder/workflow identity is missing or untrusted | Reject |
| Stale or replayed build/rollback record | Reject and quarantine |
| Previous-valid record is mutable or digest-poisoned | Reject; preserve known-good evidence |
| Symlink, hardlink, mount, case-folding, or path alias bypass | Reject or remain unsupported/blocked |
| Artifact changes between stat and hashing | Reject through immutable staging or revalidation; do not claim TOCTOU resistance otherwise |
| Archive differs by timestamps, ordering, uid/gid, locale, timezone, or compression metadata | Fail equality; normalize only through a documented build step, never post-hoc comparison masking |
| Operator preauthorizes rollback in repository data | Reject |
| Rollback is a version downgrade with unknown schema/data compatibility | Reject |
| Partial or corrupt output set | Reject and quarantine |
| Clean restore cannot meet declared RPO/RTO | Claim remains blocked |

## Evidence triangulation

### Official and authoritative

- NIST SP 800-34 Rev. 1 requires contingency requirements, recovery strategies, testing/exercises, and maintenance; documentation without tested recovery is insufficient.
- SLSA provenance separates artifact equality from trustworthy build identity and source/build-parameter binding.
- The Reproducible Builds definition requires the same source, build environment and instructions to recreate bit-for-bit identical specified artifacts.

### Independent academic evidence

Research on reproducible builds shows that environment variation, timestamps, paths, locale, dependencies and toolchains commonly create nondeterminism; therefore comparing arbitrary supplied directories is not evidence of independent reproducibility.

### Implementation and incident evidence

Debian's reproducible-builds program uses repeated rebuilds under varied environments to expose hidden inputs. Supply-chain incidents such as SolarWinds demonstrate that deterministic or signed outputs alone do not establish trustworthy source-to-binary correspondence when the builder is compromised.

### Limitation and opposing view

Byte-for-byte comparison is still a strong and inexpensive detector for accidental divergence after inputs and environments are controlled. It is not useless; its assurance boundary is equality of observed outputs, not builder trust, source authenticity, rollback safety, or recoverability.

## Verification policy

Positive tests:
- identical specified output trees pass;
- a well-formed unauthorized rollback record passes bounded structural validation.

Negative tests:
- missing, extra, changed, empty, symlinked, malformed, preauthorized, same-version, same-digest, or schema-incompatible inputs fail.

Bypass tests required before broader claims:
- stale/replayed records;
- wrong source commit, workflow, builder, parameters or policy version;
- poisoned previous-valid metadata;
- hardlink/path/case-folding/mount aliasing;
- archive metadata nondeterminism;
- partial/corrupt output sets;
- downgrade and schema migration failure;
- target-side rollback verification failure.

Green CI proves only the covered bounded properties.

## Deny-by-default policy

Remain blocked when trusted provenance, independent build evidence, immutable previous-valid storage, protected approval, compatibility evidence, backup/restore infrastructure, or clean-environment drill results are absent. Never weaken verification automatically to restore availability.

## Rollback and recovery

Rollback of this ADR requires a superseding accepted ADR with equal or stronger controls. For a failed candidate: quarantine it, preserve secret-free telemetry and exact digests, leave previous-valid unchanged, revalidate previous-valid in a clean environment under current policy, require protected authorization, then verify the target state. If any evidence is missing or incompatible, remain blocked.

## Residual risk and confidence

A trusted builder can still be compromised, two independent builders may share a compromised dependency, and bit-identical artifacts may contain deterministic malicious behavior. Confidence is high that this policy prevents overstated claims; confidence in production recovery remains low until real drills and protected infrastructure exist.

## References

- NIST SP 800-34 Rev. 1, Contingency Planning Guide for Federal Information Systems.
- SLSA v1.0 Provenance.
- Reproducible Builds, Definitions and variation-testing guidance.
- Debian reproducible-builds implementation evidence.
- SolarWinds supply-chain incident analyses.
