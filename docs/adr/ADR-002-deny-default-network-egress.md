# ADR-002: Deny-by-default HTTPS egress authorization

- **Status:** accepted for bounded implementation
- **Date:** 2026-08-05
- **Owners:** NEXUS architecture
- **Review date:** 2026-11-05
- **Obsolescence triggers:** URL parser change; resolver behavior change; DNS rebinding bypass; SSRF incident; need for non-HTTPS protocols; proxy or service-mesh adoption; transport peer-verification failure

## Context and applicability

The collector requires outbound access to a small number of public market-data endpoints. Unrestricted network access would let compromised code, untrusted content, or an agent transmit repository data or reach local, private, link-local, metadata, and administrative services. This decision applies to application-level authorization of outbound HTTPS destinations. It does not claim OS-level socket confinement.

## Threat model and abuse cases

- SSRF to localhost, RFC1918, link-local, cloud metadata, multicast, or otherwise non-global addresses.
- Hostname suffix confusion, URL userinfo, fragments, alternate ports, mixed-case/trailing-dot names, and parser disagreement.
- DNS rebinding or mixed public/private DNS answers.
- Redirects from an approved endpoint to an unapproved endpoint.
- Method, content-type, request-size, or response-size escalation.
- A transport connecting to a peer not present in the authorization-time resolution set.

## Assumptions

- The caller routes every outbound request through this authorizer.
- The transport can connect to an authorized resolved address and verify the connected peer address.
- TLS hostname verification remains enabled against the approved hostname.
- Redirect following is disabled by default.
- OS sandboxing and firewall enforcement are separate controls and are not provided by this module.

## Evidence triangulation

### Authoritative standards and official guidance

1. **NIST SP 800-207, Zero Trust Architecture.** Access should be explicitly authorized for individual resources rather than inherited from network location. Applicability: outbound destinations are treated as protected resources requiring an explicit policy decision. https://doi.org/10.6028/NIST.SP.800-207
2. **NIST SP 800-207A.** Granular application- and service-identity policies should be enforced by dedicated gateways or policy enforcement infrastructure. Applicability: grants bind subject identity, destination, method, limits, purpose, and expiry. https://doi.org/10.6028/NIST.SP.800-207A
3. **OWASP SSRF Prevention Cheat Sheet.** Prefer allowlists, validate domains and resolved addresses, protect metadata services, and treat denylists as a last resort. Applicability: exact-host allowlisting and rejection of every non-global DNS answer. https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html
4. **OWASP Unvalidated Redirects Cheat Sheet.** Avoid automatic redirects or re-authorize trusted destinations. Applicability: every 3xx response requires a new authorization decision. https://cheatsheetseries.owasp.org/cheatsheets/Unvalidated_Redirects_and_Forwards_Cheat_Sheet.html

### Independent academic evidence

- Johns, Lekies, and Stock, *Eradicating DNS Rebinding with the Extended Same-origin Policy*, USENIX Security 2013. The work demonstrates that DNS-derived trust can be subverted and that then-deployed browser defenses were bypassable. Applicability: authorization validates all resolved addresses and binds the transport peer to the approved resolution set. https://www.usenix.org/conference/usenixsecurity13/technical-sessions/presentation/johns
- Jackson et al., *Protecting Browsers from DNS Rebinding Attacks*, ACM CCS 2007. The study found classic DNS pinning ineffective in modern browser contexts. Applicability: hostname validation alone is rejected. https://doi.org/10.1145/1315245.1315298

### Implementation and incident evidence

- Capital One disclosed unauthorized access in 2019 through a configuration vulnerability, demonstrating the material impact of server-side access paths into protected cloud resources. Applicability: link-local and metadata-reachable addresses are categorically denied by requiring globally routable destination addresses. https://www.investor.capitalone.com/news-releases/news-release-details/capital-one-announces-data-security-incident
- OWASP WSTG documents practical SSRF bypass classes including alternate loopback representations, URL userinfo, fragments, parser confusion, and attacker-controlled DNS. Applicability: standard-library parsing, exact normalized host comparison, userinfo/fragment rejection, fixed port, and resolved-address checks. https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/07-Input_Validation_Testing/19-Testing_for_Server-Side_Request_Forgery

### Limitations, dissent, and conflicting evidence

- Application-level checks cannot stop direct socket use by code that bypasses the authorizer; OS sandbox or firewall enforcement remains necessary.
- DNS resolution validation is not sufficient unless the transport connects to one of the validated addresses and verifies the peer after connection.
- `ipaddress.is_global` is intentionally conservative and may deny valid special-purpose networks. This is accepted for the current public-API use case.
- Exact-host allowlists reduce flexibility and require policy updates during legitimate endpoint migration.
- DNS, CA, proxy, kernel, or local trust-store compromise remain outside this control.

## Options considered

### Unrestricted HTTPS client
- **Rejected:** permits arbitrary exfiltration and SSRF.

### Hostname string allowlist only
- **Rejected:** parser confusion, DNS rebinding, private DNS answers, redirects, and alternate ports remain.

### Application authorizer plus transport binding and later OS enforcement
- **Selected:** narrow, testable, reversible, and suitable as a policy decision layer while stronger platform controls are developed.

## Decision

1. Egress defaults to deny.
2. Only HTTPS on TCP port 443 is supported.
3. Grants bind subject, purpose, exact normalized hostname, methods, content types, request/response byte limits, and expiry.
4. URL userinfo and fragments are prohibited.
5. Every resolved destination address must be globally routable; mixed public/private answer sets are denied.
6. Redirects are never followed under the original authorization.
7. The transport must connect to an authorized resolved address, verify the connected peer address, and retain TLS hostname verification.
8. Authorization does not itself open sockets, preventing accidental coupling to an unsafe redirecting client.
9. Failures deny access; there is no permissive fallback.

## Verification method

- Positive exact-host HTTPS authorization test.
- Negative tests for HTTP, suffix confusion, userinfo, fragments, alternate ports, subject/method/content-type/byte escalation, expiry, empty DNS, and invalid addresses.
- Bypass tests for loopback, private, link-local metadata, IPv6 loopback, and mixed public/private DNS answers.
- Redirect re-authorization test.
- Connected-peer binding test.
- Full repository test matrix on Ubuntu, Windows, and macOS.

## Rollback and recovery

The module is additive and not yet wired into production collection. Rollback is deletion of the module, schema, tests, and ADR. A denied destination can be restored only through an explicit, reviewed grant change; no wildcard emergency bypass is provided.

## Residual risk

Direct sockets, proxy behavior, DNS/CA compromise, transport implementation defects, side channels, and kernel compromise remain. The current confidence applies only to policy decisions, not complete network confinement.

## Confidence

**Medium.** Evidence strongly supports exact allowlisting, address validation, redirect denial, and transport binding. Confidence is limited because OS-level enforcement and a production transport adapter are not yet implemented.
