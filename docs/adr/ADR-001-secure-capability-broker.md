# ADR-001: Secure capability broker for files, processes, network, and AI tools

- **Status:** accepted for implementation
- **Date:** 2026-08-05
- **Owners:** NEXUS architecture
- **Review date:** 2026-11-05
- **Obsolescence triggers:** material OS sandbox changes; new prompt-injection bypass evidence; broker escape; privilege-escalation incident; policy-language change; unsupported platform behavior

## Context

NEXUS agents may analyze files, edit project artifacts, invoke tools, and communicate with external providers. The primary risk is a confused-deputy path in which untrusted content, a plugin, an LLM output, or an indirect command causes access beyond the user's explicit grant. A textual prohibition is insufficient because the same resource could be reached through shell commands, helper processes, symlinks, archives, network upload, OCR, screenshots, caches, or alternate APIs.

Protected assets include personal files, secrets, credentials, source code, private prompts, local memory, clipboard, screen, camera, microphone, contacts, and outbound data. The broker boundary applies to every agent, model, plugin, helper process, and tool adapter.

## Assumptions

- The host operating system can enforce process and filesystem isolation.
- NEXUS can run agents without administrator/root privileges.
- All privileged operations can be routed through a small broker API.
- Platform-specific sandboxes differ; identical guarantees cannot be assumed across Windows, Android, Linux, and macOS.
- LLM classifiers and prompt filters can be bypassed and therefore cannot be the authorization boundary.

## Evidence triangulation

### Authoritative standards and official guidance

1. **NIST SP 800-207, Zero Trust Architecture** — protects individual resources rather than trusting network location and requires explicit authentication and authorization before access. https://doi.org/10.6028/NIST.SP.800-207
2. **NIST SP 800-207A** — recommends granular application- and service-identity policies enforced by dedicated policy enforcement infrastructure. https://doi.org/10.6028/NIST.SP.800-207A
3. **OWASP Injection Prevention Cheat Sheet** — recommends allowlist validation, canonicalization, and safe APIs that avoid interpreters. https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html
4. **OWASP LLM Prompt Injection Prevention Cheat Sheet** — documents indirect injection, data exfiltration, tool manipulation, least privilege, remote-content sanitization, output validation, and human control. https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html

### Independent academic evidence

1. Saltzer and Schroeder, *The Protection of Information in Computer Systems*, Proceedings of the IEEE 63(9), 1975, DOI 10.1109/PROC.1975.9939. The design principles directly relevant here are fail-safe defaults, complete mediation, economy of mechanism, separation of privilege, least privilege, and least common mechanism.
2. Liu et al., *Formalizing and Benchmarking Prompt Injection Attacks and Defenses*, 2023. The study evaluates multiple attacks and defenses and supports treating prompt injection as a system problem rather than relying on one filter. https://arxiv.org/abs/2310.12815

### Implementation, vulnerability, and incident evidence

- Path traversal and interpreter injection classes repeatedly show that validating only the user-visible path or command is inadequate. Canonical resolution, descriptor-based access, and avoiding general-purpose interpreters are required.
- Agentic systems can turn untrusted document or web content into tool calls. Therefore content-derived instructions must never carry authority; only broker-issued capabilities may authorize operations.

### Limitation and conflicting evidence

- Prompt-injection defenses are not complete. Recent work demonstrates that guardrail and detector systems can be bypassed, so model-based detection is defense in depth only, never an authorization control. See Hackett et al., *Bypassing Prompt Injection and Jailbreak Detection in LLM Guardrails*, 2025: https://arxiv.org/abs/2504.11168
- Zero Trust is an architectural model, not a proof of non-bypass. Correct OS enforcement, broker implementation, testing, and operational configuration remain necessary.
- Mobile and desktop operating systems expose different sandbox primitives. A single implementation cannot claim equal isolation without platform-specific verification.

## Options considered

### A. Prompt-only restrictions
- **Benefits:** simple and fast.
- **Risks:** bypassable through indirect prompt injection, alternate tools, shell access, plugins, or helper processes.
- **Decision:** rejected.

### B. Application-level path allowlist only
- **Benefits:** easy to explain and implement.
- **Risks:** vulnerable to symlink/junction substitution, path traversal, race conditions, archive extraction, alternate APIs, and inherited process privileges.
- **Decision:** rejected as sole control.

### C. OS sandbox plus narrow capability broker
- **Benefits:** separates authority from model output, supports complete mediation, least privilege, auditing, revocation, and fail-closed behavior.
- **Risks:** greater implementation complexity and platform-specific work.
- **Decision:** selected.

## Decision

NEXUS will use a **deny-by-default, capability-based security broker** as the only route to protected resources.

1. Agents and plugins run without ambient filesystem, shell, network, clipboard, screen, camera, microphone, contacts, or credential access.
2. The broker exposes narrow operations such as `read_file`, `write_file`, `create_file`, `list_directory`, `send_https`, and approved process tasks. No unrestricted shell API is exposed.
3. Each capability binds: subject identity, exact operation, canonical resource identity, purpose, maximum bytes, destination where applicable, expiry, invocation count, and audit correlation ID.
4. Read, analyze, modify, delete, execute, and transmit are separate permissions. Read permission never implies upload permission.
5. Every access is mediated at execution time. Authorization is not cached beyond the capability lifetime.
6. Paths are canonicalized and resolved beneath an approved root. Symlinks, junctions, hard links, mount changes, alternate data streams, and path reparse behavior are rejected or safely resolved using platform-appropriate descriptor/handle checks.
7. File identity is revalidated after opening to reduce time-of-check/time-of-use races.
8. Archive extraction is brokered, size-limited, depth-limited, and prevented from escaping the destination root.
9. Network egress is deny-by-default. Destinations, protocol, method, content type, byte limit, and data classification must be explicitly allowed. Redirects require re-authorization.
10. Untrusted content is data, never authority. Text inside files, webpages, emails, images, metadata, tool output, or model output cannot grant or expand permissions.
11. Prompt-injection detection, malware scanning, and content sanitization are additional controls only. A detector result cannot authorize access.
12. Broker or policy failure denies the operation. There is no permissive fallback.
13. Privileged overrides require explicit human approval, clear scope and expiry, and immutable audit evidence.

## Verification plan

### Positive tests
- Authorized file can be read and edited only for the granted operation and byte range.
- Approved HTTPS destination receives only explicitly authorized data.
- Capability expiry and use-count limits work.

### Negative tests
- Sibling, parent, hidden, temporary, backup, and unrelated files are denied.
- Read-only grants cannot modify, delete, execute, or transmit.
- Network redirects to unapproved destinations are denied.
- Shell, PowerShell, CMD, Bash, interpreters, and process-spawn attempts are denied unless a separately approved fixed task exists.

### Bypass and abuse tests
- `..`, mixed separators, Unicode normalization, case folding, short names, device paths, UNC paths, symlinks, junctions, hard links, bind mounts, race swaps, archive traversal, nested archives, alternate data streams, clipboard copy, screenshot/OCR, plugin delegation, and helper-process delegation.
- Direct, indirect, encoded, multimodal, persistent, and tool-output prompt injection.
- Attempts to convert content instructions into permissions or to leak data through error messages, logs, DNS, URLs, headers, or telemetry.

### Cross-platform tests
- Windows: restricted token/AppContainer or equivalent, ACL and reparse-point behavior, named pipes, PowerShell/CMD denial.
- Android: scoped storage, app sandbox, URI grants, content-provider boundaries, intent restrictions.
- Linux: namespaces, seccomp, AppArmor/SELinux where available, descriptor-based path enforcement.
- macOS: App Sandbox or equivalent entitlement restrictions and bookmark validation where applicable.

### CI evidence
- Policy-schema validation.
- Unit tests for authorization decisions.
- Property/fuzz tests for path normalization and capability parsing.
- Integration tests using isolated temporary roots.
- Secret, dependency, static-analysis, and artifact-integrity checks.

### Recovery and rollback
- Revoking all active capabilities immediately blocks new operations.
- Broker update can roll back without changing user policy data.
- Audit trail permits reconstruction without storing protected file content.

## Residual risk

- Kernel or sandbox vulnerabilities can bypass user-space controls.
- Accessibility APIs, screen capture, and platform integrations may expose additional channels if enabled.
- Side channels and covert channels cannot be fully eliminated on general-purpose devices.
- User-approved broad capabilities can still create excessive exposure.
- Platform differences may temporarily produce weaker guarantees; unsupported guarantees must be shown explicitly to the user.

## Confidence

**Medium-high.** The architecture follows long-standing protection principles, current NIST guidance, OWASP implementation guidance, and academic evidence that prompt-level controls alone are insufficient. Confidence remains below high until bypass tests and platform-specific enforcement are implemented and independently reviewed.

## Consequences

- More implementation effort and platform-specific adapters.
- Reduced agent convenience because arbitrary shell and ambient file access are prohibited.
- Stronger privacy guarantees, clearer audits, narrower blast radius, and easier revocation.
- Security claims must be capability- and platform-specific rather than universal.

## Exceptions

Exceptions must identify the exact resource, operation, subject, reason, expiry, approver, monitoring, and remediation issue. Permanent wildcard exceptions are prohibited.
