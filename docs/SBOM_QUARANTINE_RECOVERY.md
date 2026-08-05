# SBOM quarantine and recovery runbook

## Scope

This runbook applies when SBOM or release-evidence verification fails. It does not authorize production release, signing, credential changes, or automatic downgrade.

## Failure flow

```text
candidate received
  -> verify size, JSON, schema, identities, graph, artifact/provenance binding
    -> pass: eligible for later independent gates
    -> fail: quarantine candidate
      -> preserve previous-valid evidence unchanged
      -> record bounded telemetry
      -> revalidate previous-valid in a clean environment
        -> pass: retain as recovery candidate; require explicit authorization before use
        -> fail: remain blocked and escalate
```

## Quarantine record

Record only:

- candidate SBOM SHA-256;
- related artifact and provenance digests when available;
- source commit/ref and workflow identity when available;
- verifier version and policy/ADR version;
- deterministic reason code;
- UTC observation time.

Do not record secrets, tokens, certificate private material, or unredacted environment data.

## Reason codes

- `INPUT_TOO_LARGE`
- `INVALID_JSON`
- `UNSUPPORTED_CYCLONEDX`
- `EMPTY_COMPONENTS`
- `DUPLICATE_IDENTITY`
- `MALFORMED_PURL`
- `UNKNOWN_DEPENDENCY_TARGET`
- `SELF_DEPENDENCY`
- `DEPENDENCY_CYCLE`
- `GRAPH_INCOMPLETE_OR_UNKNOWN`
- `STALE_OR_REPLAYED`
- `ARTIFACT_BINDING_MISMATCH`
- `PROVENANCE_BINDING_MISMATCH`
- `PATH_OR_ALIAS_VIOLATION`

## Previous-valid contract

A previous-valid record is a tuple of:

- artifact digest;
- SBOM digest;
- provenance digest;
- source commit;
- trusted builder/workflow identity;
- verification policy version;
- acceptance timestamp.

The record must be immutable by policy. Candidate validation must never overwrite it. Selection by filename, mutable tag, branch name, or latest timestamp alone is prohibited.

## Recovery procedure

1. Isolate the failed candidate from active release paths.
2. Preserve logs and reason codes without secrets.
3. Fetch the exact previous-valid tuple from immutable storage.
4. Re-run verification in a clean environment with the current verifier and policy.
5. Confirm source, builder, artifact, SBOM, and provenance digests exactly match the record.
6. Confirm schema and data compatibility; a boolean assertion alone is insufficient for production.
7. Require protected human authorization before any rollback or promotion.
8. Verify target-side state after the authorized action.

## Fail-closed conditions

Remain blocked when:

- previous-valid evidence is missing, mutable, stale, or fails current policy;
- provenance or trusted identity cannot be established;
- schema/data compatibility is unknown;
- the requested action is an unapproved downgrade;
- clean-environment revalidation differs from the original result;
- external storage, signing identity, credentials, or production approval are unavailable.

## Incident escalation

Escalate when the failure suggests builder compromise, evidence substitution, repeated replay, policy bypass, or inconsistent clean-room results. Freeze promotion, preserve evidence, rotate affected credentials only through authorized procedures, and open an incident record.

## Verification checklist

- [ ] Candidate quarantined
- [ ] Previous-valid unchanged
- [ ] Deterministic reason code recorded
- [ ] Secret-free telemetry preserved
- [ ] Clean-environment revalidation completed
- [ ] Exact digests and source identity matched
- [ ] Compatibility evidence reviewed
- [ ] Protected authorization obtained for any action
- [ ] Target-side result verified
- [ ] Obsolescence trigger or incident follow-up recorded
