# NEXUS Phase 4 Security Boundary

Parent: #510
Version: `phase4-security/v1`

## Paper/live air gap
Phase 4 contracts reject private exchange credentials, real-order endpoints, withdrawals, production promotion/deployment, signing authority, billing changes and live financial execution.

## AI/tool boundary
AI and agents operate with least privilege, explicit capability allowlists, bounded inputs/outputs, provider/model identity, pre-egress classification/redaction and durable audit evidence. AI output is never sufficient by itself to authorize paper execution or risk-policy change.

## Data/report boundary
External/API/report inputs are untrusted. Unknown schema, stale/future timestamps, malformed or oversized inputs, path ambiguity, provenance mismatch and semantic uncertainty fail closed.

## Dashboard boundary
Default exposure is local/loopback. Host validation, DNS-rebinding defenses, safe response headers, bounded request/report parsing and no direct state mutation are required before stronger control surfaces are considered complete.

## Independent safety gate
A change that weakens policy, validator and tests together must still be caught by an independent/trusted control. No component may self-authorize by modifying all of its own enforcement/evidence paths in the same trust domain.

## Secret boundary
Credentials, tokens, authorization headers and unnecessary raw private transcripts must not enter repository state, Project Memory, reports, logs or AI provider payloads. Missing proof of safe handling fails closed for the affected action.
