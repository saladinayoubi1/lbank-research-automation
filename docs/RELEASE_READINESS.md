# Release readiness gate

## Verified automatically

A candidate release bundle must contain:

- `artifact-manifest.json` with safe relative paths, SHA-256 and byte size;
- `sbom.cdx.json` in CycloneDX JSON form;
- `provenance.json` binding every artifact digest to a source commit and builder;
- every artifact referenced by the manifest.

`scripts/release_gate.py` fails closed for missing, malformed, duplicated, path-traversing, size-mismatched, digest-mismatched or provenance-mismatched evidence. CI runs positive and negative verification on Linux, Windows and macOS.

## Production blockers

The following are intentionally not auto-created or approved:

- signing identity, trust root, key custody, rotation and revocation policy;
- protected production environment and human approval authority;
- production credentials or external storage credentials;
- paid artifact retention, backup or disaster-recovery infrastructure;
- irreversible release promotion.

Production mode therefore fails closed even when signature files exist until an approved signer identity policy is implemented.

## Evidence still required before release

- two clean builds from the same commit with byte-identical artifacts and manifests;
- tested rollback to the immediately previous immutable artifact;
- backup and restore drill with measured RPO/RTO;
- disaster-recovery exercise from an independently stored backup;
- target-side verification after restore and after rollback;
- explicit production approval recorded outside mutable commit metadata.

## Rollback

This change is isolated to the release gate, its tests, documentation and workflow. Rollback is a normal revert of the branch commit or PR; it does not modify datasets, credentials, releases or external systems.
