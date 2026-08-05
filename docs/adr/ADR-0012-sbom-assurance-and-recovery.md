# ADR-0012: SBOM assurance is bounded, explicit, and recoverable

- **Status:** Proposed
- **Version:** 1.0.0
- **Date:** 2026-08-06
- **Decision owner:** NEXUS security governance
- **Review date:** 2026-09-06
- **Related:** Issues #42 and #43; PR #56
- **Obsolescence triggers:** CycloneDX profile changes; provenance format or trust root changes; packaging or schema changes; a false-negative, stale-SBOM, graph-truncation, parser-bypass, quarantine, or recovery incident; supported platform changes.

## Context

The repository has a fail-closed structural SBOM verifier. Structural validity is useful, but it does not prove publisher identity, artifact authenticity, graph completeness, vulnerability absence, reachability safety, or source-to-binary correspondence.

## Trust boundaries

Producer/build workflow -> SBOM document -> release gate -> quarantine/previous-valid state -> downstream analysis or release decision.

Assets include artifact identity, component inventory, dependency relationships, provenance bindings, previous-valid evidence, and the integrity of downstream security conclusions.

## Decision

1. SBOM outcomes are reported as bounded structural evidence only.
2. Graph completeness is explicit: `complete`, `incomplete`, or `unknown`; absence defaults to `unknown`.
3. Reachability and vulnerability-cleared conclusions are denied unless graph completeness is `complete` and trusted provenance independently binds the SBOM and artifact.
4. Declared component hashes remain declarations until independently verified against the corresponding artifact or package.
5. Missing, malformed, oversized, stale, replayed, path-aliased, cyclic, self-referential, orphan-heavy, or provenance-mismatched evidence fails closed.
6. A rejected candidate is quarantined. It must not overwrite previous-valid evidence or become an input to release, rollback, or security-cleared decisions.
7. Previous-valid evidence is immutable by policy and selected only by exact digest plus trusted provenance. Automatic downgrade is prohibited.
8. Artifact verification, SBOM structural verification, trusted provenance, signing, vulnerability analysis, and release approval remain separate controls.

## Threat and abuse cases

| Case | Required behavior |
|---|---|
| Forged component hash | Treat as unverified declaration; deny authenticity claim |
| Empty or truncated graph | Mark incomplete/unknown; deny reachability conclusion |
| Malicious or malformed purl | Reject deterministically |
| Unknown dependency target | Reject |
| Multi-node cycle or self-edge | Reject |
| Stale or replayed SBOM | Quarantine unless freshness and source binding pass |
| Oversized input/resource exhaustion | Reject before unbounded parsing |
| Valid SBOM for wrong artifact | Reject on provenance/artifact binding mismatch |
| Candidate failure after previous-valid exists | Preserve previous-valid; quarantine candidate |
| Operator attempts downgrade | Require explicit protected authorization and compatibility evidence |
| Consumer equates structural validity with security | Documentation and machine output must state bounded scope |

## Evidence basis

- CycloneDX specification defines document and dependency semantics but does not by itself establish producer identity or artifact authenticity.
- CISA/NTIA SBOM guidance treats SBOMs as inventory evidence and emphasizes minimum elements and operational use.
- SLSA provenance separates build provenance from inventory structure.
- Independent empirical studies report incomplete and inconsistent real-world SBOMs, supporting deny-by-default treatment of missing graph evidence.
- Supply-chain incidents such as SolarWinds and Log4Shell show that inventory without trustworthy provenance, freshness, and dependency context is insufficient.

## Verification

Positive tests cover accepted CycloneDX versions, unique component identities, valid dependency targets, explicit completeness state, bounded size, and deterministic re-validation.

Negative and bypass tests cover empty inventories, duplicate identities, malformed purls, unknown targets, self-edges, cycles, sparse/orphan graphs, oversized input, path/canonicalization ambiguity, stale/replayed documents, and artifact/provenance mismatch.

CI must remain cross-platform where filesystem or path behavior is relevant. Green tests prove only the documented bounded properties.

## Quarantine and recovery

- Store rejected evidence outside the active release-evidence path.
- Record a non-sensitive reason code, candidate digest, source reference, verifier version, and timestamp.
- Never mutate or replace previous-valid evidence during candidate validation.
- Recovery selects the last previous-valid tuple of artifact digest, SBOM digest, provenance digest, source commit, and verifier policy version.
- Revalidate previous-valid evidence in a clean environment before reuse.
- If no previous-valid evidence passes current policy, remain blocked; do not weaken policy automatically.

## Rollback

Rollback of this ADR requires a superseding accepted ADR with equal or stronger controls. Code rollback may revert verifier changes, but production/security claims remain blocked until the current policy is satisfied.

## Residual risk

A structurally complete graph can still be malicious or wrong. Trusted builders can be compromised. Ecosystem metadata may be ambiguous. Vulnerability intelligence can be stale. Therefore SBOM evidence remains one input in a layered assurance model.

## Confidence

High for preventing unsupported claims from structural validation alone. Medium for completeness detection because completeness ultimately depends on producer and provenance quality.

## References

- CycloneDX Specification Overview.
- CISA, Software Bill of Materials guidance.
- SLSA v1.0 Provenance.
- NIST SP 800-53 Rev. 5, SI-7 and CM-3.
