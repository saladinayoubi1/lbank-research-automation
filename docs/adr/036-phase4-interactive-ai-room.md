# ADR-036 — Interactive AI Room on the Phase 4 secure gateway

Status: Accepted for Gate 20 candidate
Parent: #510

## Decision

The Phase 4 browser AI Room is interactive, but it is not an execution endpoint. The browser may POST exactly one bounded JSON request shape to `/api/ai-room/message`:

`session_id + conversation_id + turn_id + message`

The server owns model identity, policy, tool registry, requested authority, timeout, retry and delegation values. Client-supplied authority/tool/action fields are rejected by exact-schema validation.

The route is:

`Browser turn -> bounded request parser -> repository Project Memory + read-only Mission Control projection -> deterministic intent -> Gate 10 AI control plane -> proposal/route decision -> browser response`

No call from this endpoint reaches Paper Execution, Risk mutation, Event Store mutation, Mission Queue mutation, exchange APIs or an external AI provider.

## Write-method exception

Gate 14 remains read-only for dashboard/project state. The secure gateway continues to deny POST/PUT/PATCH/DELETE/OPTIONS generally. `POST /api/ai-room/message` is a narrowly scoped message-evaluation operation and returns `executed=false` and `state_mutation=false`. It is therefore input to the control plane, not a state-mutation API.

The endpoint inherits the Gate 14 Host/Origin/authentication/rate-limit/security-header boundary. Requests require JSON, explicit bounded Content-Length, no transfer encoding, no query parameters and the exact AI Room request schema.

## Context and privacy

Repository `docs/project_memory/STATE.json` remains the durable Project Memory source and must declare that chat is not source of truth and secrets are not allowed. The raw message is never written into Project Memory or returned by the API. A SHA-256 digest of the raw message is bound into the working-context digest so the decision is cryptographically tied to the browser turn without persisting transcript content.

Browser history is bounded to the current `sessionStorage` session. The AI Room endpoint performs no external-provider egress.

## Persian intent binding

The interactive room adds a deterministic Persian intent vocabulary for owner-sensitive, workflow, paper-action and proposal requests. Gate 10 still independently re-classifies a canonical intent sentinel. The original Persian message is bound by digest to working context, preventing the UI layer from granting its own authority while avoiding raw-transcript persistence.

## Authority behavior

- L0 observe: no tool route.
- L1 propose: no tool route.
- L2 paper action: may only stage the reversible `paper-signal-proposal` route; no simulated order is executed by chat.
- L3 workflow: may only stage the reversible `mission-runner` route; no mission state is mutated by chat.
- L4 / owner-sensitive: `owner_required`, no route.

All real paper-state changes, if later requested through an authorized execution surface, must still traverse deterministic Risk and Paper Execution. Live/real trading remains unavailable.

## Failure behavior

Missing/unsafe Project Memory, malformed request JSON, unknown request fields, oversized bodies, query smuggling, stale/invalid control-plane inputs or authority violations fail closed. Mission Control report unavailability degrades the read-only operational projection but does not grant additional authority.
