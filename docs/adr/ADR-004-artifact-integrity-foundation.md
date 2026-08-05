# ADR-004: Deterministic artifact integrity manifests

- **Status:** accepted for bounded implementation
- **Date:** 2026-08-05
- **Owners:** NEXUS architecture
- **Review date:** 2026-11-05
- **Obsolescence triggers:** signing service adoption; SLSA provenance rollout; digest algorithm deprecation; artifact verification bypass; release incident; reproducible-build support

## Context and applicability

NEXUS produces desktop, Android, dataset, and documentation artifacts in CI. A consumer or later pipeline stage needs a deterministic way to detect accidental or unauthorized byte changes. This decision applies to repository-owned build outputs and exported research artifacts. It does not establish publisher identity, trusted provenance, or source-to-binary reproducibility.

## Assumptions

- The manifest is generated in the same authorized CI job as the artifact.
- SHA-256 remains suitable for collision-resistant integrity checking.
- The verifier receives the expected manifest through a controlled channel.
- Signing keys and production release approval are not currently available.

## Evidence triangulation

### Authoritative standards and official guidance

- NIST SP 800-218 SSDF v1.1 recommends protecting software and release integrity and preserving provenance: https://doi.org/10.6028/NIST.SP.800-218
- SLSA provenance describes verifiable information about where, when, and how an artifact was produced: https://slsa.dev/spec/v1.1/provenance

**Applicability:** deterministic manifests provide a reversible first integrity gate while stronger signed provenance is not yet available.

### Independent academic evidence

- Fourné et al., *It’s like flossing your teeth: On the Importance and Challenges of Reproducible Builds for Software Supply Chain Security*, IEEE Symposium on Security and Privacy, 2023. The work supports independent artifact comparison while documenting adoption and reproducibility challenges.
- Lew et al., *Distributed Software Build Assurance for Software Supply Chain Integrity*, Applied Sciences 14(20), 2024, DOI 10.3390/app14209262. The implementation combines artifact digests, SBOMs, and reproducible builds to detect changes across build and distribution stages.

**Applicability:** digest comparison is useful but becomes substantially stronger when paired with independent reproduction and provenance.

### Implementation and incident evidence

- The SolarWinds SUNBURST compromise demonstrated that trusted build and distribution paths can deliver modified artifacts. Artifact verification must therefore be explicit rather than inferred from repository access or transport security.

### Limitations and conflicting evidence

- A digest manifest generated beside a compromised artifact can faithfully describe malicious bytes.
- Reproducible builds remain difficult because timestamps, toolchains, packaging, and platform metadata introduce nondeterminism.
- SHA-256 integrity does not authenticate the publisher and does not replace signature verification or independent provenance.

## Options considered

### No manifest

Rejected: consumers cannot deterministically detect modification or truncation.

### Unsigned SHA-256 manifest

Selected as the current bounded control: dependency-free, reversible, cross-platform, and immediately testable.

### Signed provenance and reproducible builds

Preferred target state but deferred because signing identity, key custody, production approval, and deterministic cross-platform builds require separate evidence and operational decisions.

## Decision

NEXUS will generate a versioned, canonical JSON manifest containing the relative path, byte size, and SHA-256 digest of every declared artifact. Verification is fail-closed and rejects missing files, modified bytes, noncanonical paths, duplicate entries, path escape, symlinks, unsupported schemas, and unsupported algorithms.

The manifest must never be presented as proof of publisher identity or trusted build provenance. Release workflows must label it as byte-integrity evidence only.

## Verification

- Positive: deterministic output and create/verify round trip.
- Negative: modified, missing, malformed, duplicate, escaped, and symlink artifacts are rejected.
- Recovery: an authorized rebuild requires generation of a new manifest; stale evidence remains invalid.
- Cross-platform: repository tests run on Ubuntu, Windows, and macOS.
- CI gate: complete test suite and build verification must remain green.

## Rejected alternatives

- MD5 or SHA-1: rejected due to collision weaknesses.
- Trusting artifact storage checksums alone: rejected because verification would remain platform-specific and detached from repository policy.
- Immediate custom signing infrastructure: rejected pending key-management, rotation, recovery, and production-approval decisions.

## Residual risk

A compromised CI environment can generate a valid manifest for malicious output. Storage, workflow, dependency, runner, and credential compromise remain outside this control. Independent provenance, signing, SBOM verification, and reproducible-build validation remain required for high-assurance releases.

## Confidence

**Medium.** The control reliably detects post-manifest byte changes and common path bypasses. Confidence is limited because the manifest and artifact currently share a trust domain.

## Rollback

Remove the manifest-generation and verification steps and revert this module. Existing artifacts are unchanged. No user data or release keys are modified.
