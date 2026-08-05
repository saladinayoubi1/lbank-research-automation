# Capability Broker Threat Model

## Scope

This implementation mediates repository-owned local file reads, writes, creates, and directory listings. It does not claim to sandbox arbitrary processes, provide network egress, or replace operating-system isolation. Those controls remain future platform adapters under ADR-001.

## Assets

- Repository source and research data.
- Credentials or unrelated files adjacent to an approved root.
- Capability tokens and audit correlation identifiers.
- Integrity of policy and audit evidence.

## Trust boundaries

```text
Untrusted caller / model output
        |
        | token + subject + narrow operation
        v
CapabilityBroker (authorization and canonical path checks)
        |
        | descriptor-based file operation
        v
Approved repository-owned root
```

Untrusted text, model output, filenames, and file contents are data only. They cannot issue or expand a capability.

## Abuse cases and controls

| Abuse case | Control | Automated verification |
|---|---|---|
| Unknown caller attempts ambient access | Unknown tokens are denied | `test_default_deny_unknown_token` |
| Read grant reused for modification | Operations are distinct | `test_operation_separation_read_does_not_imply_write` |
| `..` or absolute sibling path escapes root | Canonical containment check | `test_parent_traversal_and_sibling_escape_denied` |
| Symlink redirects to an unrelated file | Resolution must remain beneath root; no-follow open where supported | `test_symlink_escape_denied` |
| Oversized read or write causes unintended disclosure/change | Per-capability byte limits | `test_byte_limits_fail_closed` and create/write test |
| Stolen capability reused indefinitely | Subject, expiry, and use-count binding | expiry/subject/use-limit test |
| Emergency revocation fails | `revoke_all` denies subsequent operations | recovery test |
| Audit evidence is casually altered | SHA-256 hash chain, no file content logged | audit-chain tests |
| Existing file is overwritten through create | Exclusive create | create/write test |
| Broad shell or wildcard policy is introduced | Schema enum excludes shell and wildcard operations | schema test |

## Deny-by-default policy

A request is denied when the token is unknown, revoked, expired, exhausted, bound to another subject, bound to another operation, outside the approved root, not the expected resource type, or above its byte limit. Broker errors do not fall back to direct filesystem access.

## Verification boundary and limitations

- CI runs on Ubuntu, Windows, and macOS to detect platform-specific path and descriptor behavior.
- Windows symlink creation may be unavailable to an unprivileged test process; the test records this as a skip rather than claiming coverage.
- User-space canonicalization cannot defeat a compromised kernel or every filesystem race.
- The current broker does not mediate network, process, clipboard, screen, camera, microphone, or mobile URI access.
- Hash chaining detects many modifications but is not an externally signed immutable log.

## Rollback and recovery

The implementation is additive. Rollback removes `capability_broker.py`, its policy schema, tests, and this document without changing market data. Runtime recovery uses `revoke_all`; the test suite verifies that newly attempted operations fail after revocation.

## Review

- Review date: 2026-11-05
- Reopen on: bypass test failure, filesystem semantic change, unsupported runner behavior, broker escape, new high-quality contradictory evidence, or expansion to process/network/mobile capabilities.
