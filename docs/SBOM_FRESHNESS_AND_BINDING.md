# SBOM freshness and provenance binding

## Scope

The release gate treats SBOM and provenance evidence as bounded, offline consistency controls. Passing these checks does not establish publisher identity, vulnerability absence, dependency reachability, or production approval.

## Required binding

A candidate bundle is rejected unless:

- the SBOM has a valid UUID URN serial number;
- the SBOM metadata timestamp and provenance issuance time are RFC3339 timestamps with timezones;
- neither timestamp is older than 24 hours or more than 5 minutes in the future;
- SBOM and provenance timestamps differ by no more than 5 minutes;
- provenance records the exact SBOM serial number and SHA-256 digest;
- source commit is a lowercase 40-character Git SHA and may be pinned by the caller;
- builder identity may be pinned by the caller;
- provenance subjects exactly equal the manifest artifact set, with no duplicates or extras.

## Threats addressed

| Threat | Denial behavior |
|---|---|
| stale SBOM or provenance replay | reject evidence older than 24 hours |
| future-dated evidence | reject timestamps beyond 5-minute clock skew |
| SBOM substitution | reject SBOM digest mismatch |
| serial-number replay or mix-and-match | reject serial mismatch |
| wrong source revision | reject expected source-commit mismatch |
| untrusted workflow identity | reject expected builder mismatch |
| hidden or duplicate provenance subject | require exact subject-set equality |

## Residual risk

Unsigned JSON can still be forged by an actor controlling the bundle. A deterministic malicious builder can produce internally consistent evidence. Trusted issuer verification, signing identity, immutable transparency records, protected production approval, and target-side verification remain blocked and must be implemented separately.

## Rollback and recovery

On any failure, quarantine the entire bundle and retain the deterministic failure reason. Do not partially reuse evidence files. Recovery requires regeneration from the expected source commit and builder in a clean environment, followed by full revalidation. Previous-valid evidence must not be overwritten by a failed candidate.

## Obsolescence triggers

Review this policy when CycloneDX timestamp or serial semantics change, provenance format changes, the trusted builder identity changes, clock synchronization guarantees change, release latency exceeds 24 hours, signing or transparency-log verification is introduced, or Git object identifiers move beyond SHA-1.
