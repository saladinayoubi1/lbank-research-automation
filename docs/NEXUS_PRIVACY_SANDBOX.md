# NEXUS Privacy Sandbox and File Access Policy v1.0

## Objective

NEXUS must be technically unable—not merely instructed—not to access files, commands, applications, accounts, sensors, or network destinations outside explicitly granted scopes.

This policy uses defense in depth. No single prompt, model instruction, plugin rule, or UI toggle is considered sufficient protection.

## Core Rule: Deny by Default

All filesystem, process, shell, network, clipboard, camera, microphone, notification, contact, account, and device capabilities are denied unless a narrowly defined permission is granted.

A denied resource must remain inaccessible through every route, including direct file APIs, command shells, scripting engines, child processes, symbolic links, shortcuts, archives, temporary copies, search indexes, thumbnails, caches, recent-file databases, logs, backups, OCR, screenshots, plugins, external applications, and model-generated commands.

## File Scope Model

Each workspace receives an explicit allowlist of approved roots and optional approved files.

Permissions are separate and never implied:

- list directory
- read metadata
- read content
- create file
- modify file
- rename or move
- delete
- export
- upload or transmit
- index or embed
- share with a model or plugin

Access to one file does not grant access to its parent, siblings, backups, hidden files, or linked targets.

## Canonical Path Enforcement

Before every operation, the trusted broker must:

1. resolve the canonical path;
2. reject `..` traversal and malformed paths;
3. reject symlink, junction, shortcut, mount-point, hard-link, and alias escapes;
4. verify the final target still belongs to an approved root;
5. verify the requested operation is allowed for that exact target;
6. re-check immediately before use to reduce time-of-check/time-of-use attacks.

Archive entries must be validated individually. Extraction outside an approved destination is prohibited.

## No Direct Shell Access

AI models, agents, and plugins must not receive unrestricted CMD, PowerShell, Terminal, Bash, shell, scripting host, package manager, registry editor, ADB, device bridge, or process-spawning access.

When command execution is required, it must pass through a constrained command broker with:

- an allowlist of executable identities and signed hashes;
- fixed argument schemas rather than arbitrary command strings;
- a fixed working directory inside the workspace;
- sanitized environment variables;
- no shell expansion, pipes, redirects, command substitution, globbing, macros, or script evaluation;
- no inherited file handles or elevated privileges;
- restricted child-process creation;
- bounded time, memory, CPU, output, and retry limits;
- complete audit records with secret redaction.

Commands that can read arbitrary files, inspect credentials, capture screens, enumerate user data, alter security settings, or launch another interpreter are denied by default.

## OS-Level Isolation

Application policy must be reinforced by operating-system controls.

### Windows

Use a restricted app identity, low-integrity or AppContainer-style isolation where feasible, explicit filesystem ACLs, restricted tokens, job objects, process mitigation policies, and a broker process that alone holds scoped file handles. The renderer and AI-facing processes must not inherit broad user permissions.

### Android

Use Android application sandboxing, Storage Access Framework or user-selected document grants, scoped storage, per-URI permissions, and no broad storage permission unless absolutely unavoidable. Persisted access must remain visible and revocable.

### Other Platforms

Use the strongest available sandbox, entitlements, containers, capabilities, and user-consent file pickers. A platform without enforceable isolation must run in reduced-capability mode.

## Trusted Broker Architecture

Only a small, reviewed, non-AI broker may perform sensitive operations. Models and agents submit structured requests; the broker validates them against policy and returns only the minimum required result.

The broker must never accept free-form commands as authority. Model output is untrusted input.

Policy checks must apply equally to first-party agents, third-party plugins, imported workflows, automation tasks, and recovery tools.

## Network and Exfiltration Controls

Reading a file and sending it are separate permissions.

Network access is deny-by-default and destination-scoped. Each provider or integration requires an explicit allowlist covering domain, protocol, purpose, data class, and retention policy.

Before transmission:

- verify that the source data is approved for export;
- minimize and redact personal or secret content;
- show or record the destination and purpose;
- block hidden uploads, telemetry, crash attachments, DNS-based exfiltration, webhook substitution, URL redirects to unapproved hosts, and covert transmission through logs or analytics;
- require explicit approval for highly sensitive data.

A plugin with network permission does not automatically receive file-read permission, and a plugin with file-read permission does not automatically receive network permission.

## Anti-Phishing and Untrusted Content

All external text, web pages, emails, documents, archives, QR codes, links, model responses, and plugin outputs are untrusted data—not instructions.

NEXUS must:

- separate system policy from document content;
- ignore prompt-injection attempts embedded in files or pages;
- prevent content from granting itself permissions;
- display the true destination before opening links or sending data;
- block look-alike domains, credential requests, executable attachments, and silent redirects where detectable;
- never request passwords, seed phrases, recovery codes, authentication cookies, or one-time codes through generated forms or chats;
- require trusted UI confirmation for account, payment, credential, or sharing actions.

## Clipboard, Screen, Camera, Microphone, and Sensors

These capabilities are individually permissioned and off by default.

Clipboard reading must be user-initiated or time-limited. Background clipboard monitoring is prohibited.

Screen capture, accessibility APIs, notification access, camera, microphone, location, contacts, call logs, and similar high-sensitivity capabilities require explicit, visible, revocable consent and must not be combined silently to infer restricted information.

## Secrets and Credentials

Secrets must be stored using platform secure storage or an external secret manager. Models, prompts, logs, crash reports, analytics, generated code, and plugins must receive opaque handles rather than raw secrets whenever possible.

Secret retrieval is purpose-bound, time-limited, audited, and inaccessible to unrelated agents.

## Logging and Observability

Every denied and permitted sensitive operation must produce a tamper-resistant audit event containing actor, mission, capability, target category, policy decision, timestamp, and result—without recording secret content.

Users must be able to inspect and revoke active grants. Hidden permissions are prohibited.

## Safe Failure

If policy validation, canonicalization, sandboxing, broker availability, or audit logging fails, the operation fails closed. NEXUS must not fall back to broader access for convenience.

## Updates and Plugins

Plugins execute in isolated processes or equivalent sandboxes with declared capability manifests. Permission changes require review and cannot be hidden inside an update.

Updates must be signed or integrity-verified, preserve policy settings, and never silently broaden access.

## Testing Requirements

Before release, automated and adversarial tests must cover:

- path traversal;
- symlink, junction, shortcut, and hard-link escapes;
- shell and scripting bypasses;
- archive extraction escapes;
- inherited handle and child-process escapes;
- prompt injection from documents and web content;
- plugin privilege escalation;
- network redirection and covert exfiltration;
- clipboard, screenshot, and sensor misuse;
- race conditions around path validation;
- permission persistence and revocation;
- fail-closed behavior.

Security boundaries are not considered complete solely because normal tests pass. They require platform-specific threat modeling and independent review before high-trust deployment.

## User Guarantees

The user can always see:

- which files and folders are authorized;
- which operation types are authorized;
- which agents and plugins hold access;
- which network destinations can receive data;
- when each permission was used;
- how to revoke access immediately.

Revocation takes effect before the next sensitive operation and terminates active leases where feasible.

## Non-Bypass Principle

A restriction applies to the information and capability itself, not merely to one API route. If direct reading is denied, deriving the same content through CMD, PowerShell, indexing, screenshots, OCR, caches, previews, plugins, child processes, backups, or another model is also denied.

Any newly discovered alternate route is treated as a security defect, blocked by default, documented, tested, and fixed before expansion of autonomy.
