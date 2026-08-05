# NEXUS Security Baseline

## Purpose

This baseline converts recognized security frameworks into practical engineering requirements for NEXUS. It is not a substitute for penetration testing or legal review; it is the minimum architecture and verification floor.

## Reference Frameworks

- NIST Cybersecurity Framework 2.0 for governance, identification, protection, detection, response, and recovery.
- NIST SP 800-207 for zero-trust access decisions and resource-centric protection.
- CIS Controls v8.1 for prioritized, measurable safeguards.
- OWASP ASVS Level 2 as the default application-security target.
- OWASP MASVS for Android/mobile controls.
- OWASP TCASVS for Windows desktop and locally executed clients.
- OWASP SCVS for software supply-chain assurance.
- OWASP AI/LLM security verification guidance for model, prompt, tool, agent, and data-flow controls.

## Required Security Architecture

### 1. Zero Trust

- No trust based on device location, local network, process ancestry, plugin identity, or provider identity.
- Every access request must identify actor, action, resource, purpose, scope, and expiry.
- Authorization is evaluated at the secure broker for every sensitive operation.
- Permissions are deny-by-default, least-privilege, time-bounded, revocable, and non-transitive.

### 2. File and Resource Isolation

- Only explicitly approved paths may be accessed.
- Read, analyze, write, create, rename, delete, export, upload, and execute are independent permissions.
- Canonical paths must be resolved before authorization.
- Symlinks, junctions, shortcuts, mount points, archives, hard links, traversal sequences, alternate data streams, and race-condition path swaps must not expand scope.
- Restricted files may not be indirectly read through shell commands, helper processes, indexing, OCR, screenshots, previews, caches, backups, plugins, logs, or external tools.

### 3. Process and Command Isolation

- Agents and plugins have no unrestricted CMD, PowerShell, Terminal, Bash, scripting, WMI, registry, ADB, or process-injection access.
- Approved operations use narrow typed broker APIs instead of arbitrary command strings.
- Child processes inherit no additional permissions.
- Executables, scripts, libraries, and plugins require allowlisting and integrity verification.

### 4. Network Security

- Network egress is deny-by-default.
- Destinations, protocols, ports, providers, data classes, rate limits, and expiration are explicitly allowed.
- Local-file read permission never implies network-send permission.
- TLS certificate validation, secure DNS behavior, request timeouts, retry limits, and payload limits are mandatory.
- Private IP ranges, local services, metadata endpoints, loopback, and internal control planes are protected against SSRF and unauthorized discovery.

### 5. Authentication and Authorization

- Strong local authentication is required before privacy settings or elevated permissions change.
- Sensitive actions require step-up confirmation.
- Tokens and sessions are short-lived, scoped, securely stored, rotated, and revocable.
- Authorization decisions are centralized, testable, and auditable.

### 6. Data Protection

- Collect and retain the minimum data necessary.
- Encrypt sensitive data at rest and in transit using maintained platform cryptography.
- Secrets never enter source code, prompts, telemetry, crash reports, screenshots, or normal logs.
- Redaction occurs before data leaves the trusted boundary.
- Memory, history, profiles, and exports are visible, editable, portable, and deletable by the user.

### 7. Prompt Injection and Phishing Resistance

- Files, websites, messages, model output, plugins, and retrieved documents are untrusted data, not authority.
- Untrusted content cannot grant permissions, disable controls, change system policy, reveal secrets, or trigger external actions.
- URLs, downloads, attachments, login requests, QR codes, and payment instructions receive risk checks and clear origin display.
- Credential entry is restricted to trusted native surfaces; models and web content cannot request raw credentials.
- Suspicious redirects, lookalike domains, hidden links, encoded instructions, and mismatched display targets are blocked or require explicit confirmation.

### 8. Secure Development Lifecycle

- Threat modeling is required for new trust boundaries and sensitive features.
- Security acceptance criteria are part of each mission.
- Code review, static analysis, dependency scanning, secret scanning, tests, and artifact verification run in CI.
- Critical findings block merge or release unless a documented risk exception is approved.
- Security regressions receive dedicated automated tests.

### 9. Supply Chain Security

- Dependencies are pinned or locked, inventoried, reviewed, and updated deliberately.
- Builds produce an SBOM where practical.
- CI actions and build tools use pinned trusted versions.
- Release artifacts include hashes and provenance metadata where supported.
- Plugins are signed or integrity-verified and execute in isolated permission domains.

### 10. Logging, Detection, and Incident Response

- Security-relevant grants, denials, policy changes, exports, uploads, plugin actions, and elevated operations are logged.
- Logs minimize sensitive content and are tamper-evident where practical.
- Repeated denied access, unusual egress, privilege changes, and integrity failures trigger alerts and protective throttling.
- Incident response includes containment, credential revocation, evidence preservation, recovery, and user notification rules.

### 11. Recovery and Resilience

- Security systems fail closed.
- Configuration is versioned and rollback-capable.
- Backups are encrypted, integrity-checked, scoped, and restorable.
- Provider, network, or plugin failure causes graceful degradation rather than permission expansion.

## Verification Target

NEXUS targets OWASP ASVS Level 2 for application services, with additional high-assurance controls for the permission broker, secret handling, update channel, plugin system, privacy sandbox, and autonomous actions.

A security control is not considered implemented until it has:

1. a documented requirement;
2. an enforceable technical mechanism;
3. an automated or repeatable verification method;
4. a failure-mode definition;
5. an audit signal;
6. a rollback or recovery path where applicable.

## Implementation Order

1. Secure permission broker and canonical path enforcement.
2. Deny-by-default network egress broker.
3. Secret storage and redaction.
4. Prompt-injection trust-boundary enforcement.
5. Plugin and process isolation.
6. CI security gates and supply-chain controls.
7. Audit, alerting, incident response, and recovery testing.
8. Independent security review and penetration testing before production use.
