# Reproducibility and rollback runbook

## Assurance states

- `OUTPUT_EQUALITY_VERIFIED`: two supplied trees have identical specified files and digests.
- `REPRODUCIBILITY_VERIFIED`: blocked until isolated builds, exact source/input/environment binding and trusted provenance are independently verified.
- `ROLLBACK_ELIGIBLE`: previous-valid evidence passes current policy and compatibility checks; execution still requires protected approval.
- `ROLLBACK_AUTHORIZED`: granted only outside mutable repository metadata by the designated production approver.
- `RECOVERY_VERIFIED`: blocked until a clean-environment restore/rollback drill and target-side checks meet documented RPO/RTO.

No lower state implies a higher state.

## Required build evidence

For each build attempt record:

- exact source commit and ref;
- build instructions and policy version;
- dependency lock and toolchain digests;
- relevant environment attributes, including platform, locale, timezone and archive tooling;
- workflow and builder identity;
- attempt identifier and UTC time;
- specified output paths, sizes and SHA-256 values;
- trusted provenance reference and freshness window.

## Candidate verification flow

```text
candidate evidence
  -> validate bounded size and structure
  -> verify source/input/environment binding
  -> verify trusted builder/workflow and freshness
  -> compare specified outputs bit-for-bit
  -> verify immutable previous-valid tuple
  -> execute compatibility tests
  -> eligible for protected approval
  -> authorized rollback/restore
  -> target-side verification
```

Any failure moves the candidate to quarantine and leaves previous-valid unchanged.

## Quarantine reason codes

- `BUILD_SOURCE_MISMATCH`
- `BUILD_INPUT_MISMATCH`
- `BUILD_ENVIRONMENT_UNKNOWN`
- `BUILDER_IDENTITY_UNTRUSTED`
- `PROVENANCE_MISSING_OR_STALE`
- `OUTPUT_FILESET_MISMATCH`
- `OUTPUT_DIGEST_MISMATCH`
- `PATH_OR_ALIAS_UNSUPPORTED`
- `PREVIOUS_VALID_MUTABLE`
- `PREVIOUS_VALID_DIGEST_MISMATCH`
- `ROLLBACK_REPLAY_OR_DOWNGRADE`
- `SCHEMA_COMPATIBILITY_UNPROVEN`
- `AUTHORIZATION_MISSING`
- `TARGET_VERIFICATION_FAILED`
- `RPO_RTO_UNPROVEN`

Telemetry must exclude secrets, tokens, private keys and unredacted environment data.

## Compatibility evidence

A boolean field is insufficient. Required evidence includes:

- migration and downgrade test identifiers;
- source and target schema versions;
- representative data fixture digest;
- test result digest and UTC time;
- destructive-change detection;
- application startup and read/write smoke tests after rollback;
- explicit handling for irreversible migrations.

## Rollback procedure

1. Freeze promotion and quarantine the failed candidate.
2. Retrieve the exact immutable previous-valid tuple by digest.
3. Revalidate artifact, SBOM, provenance, source, builder, policy and freshness in a clean environment.
4. Run schema/data compatibility tests; reject unknown or irreversible downgrade paths.
5. Obtain protected human authorization.
6. Execute the bounded rollback using exact digests.
7. Verify target-side version, artifact digest, schema, health and required data checks.
8. Record result and measured recovery duration without secrets.

## Recovery and disaster-recovery evidence

Production recovery claims require a clean-environment drill using independently retained backups. Record backup digest, storage class, retention policy, encryption/key owner, restore start/end, recovered scope, corruption and missing-backup tests, measured RPO/RTO and target-side verification.

Repository checkout alone is not backup/restore evidence.

## Bypass checklist

- [ ] stale or replayed build evidence rejected
- [ ] wrong source commit/ref rejected
- [ ] wrong builder/workflow rejected
- [ ] poisoned previous-valid record rejected
- [ ] symlink and unsupported aliasing rejected
- [ ] timestamp/order/uid/gid/locale/timezone archive variance detected
- [ ] partial and corrupt outputs rejected
- [ ] preauthorized repository rollback rejected
- [ ] schema downgrade failure rejected
- [ ] target-side verification failure leaves system blocked

## Maintenance and obsolescence

Re-review after toolchain, dependency-lock, platform, filesystem, archive, provenance, signing, schema, storage, trust-root or approval-boundary changes, and after any false-green, rollback, restore or builder-compromise incident.
