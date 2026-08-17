# ADR-015 — AI Chat Room and Deterministic Control Plane

Status: Accepted for Phase 4 Gate 10
Parent: #510

## Decision
The AI Chat Room is a bounded proposal subsystem. It is not a shell and it is not an execution authority.

The control path is:

`Session -> deterministic intent classification -> fresh context check -> structured model proposal -> policy/authority gate -> registered tool route or owner escalation -> audit decision`

The control plane returns a decision. It does not itself execute the routed tool.

## Session and context identity
Every decision binds session ID, conversation ID, actor ID and turn ID. Working context and durable Project Memory use separate identities, versions and digests. Context must bind the same conversation, carry provenance, be unexpired, and have a clear conflict state. Stale, conflicting or cross-conversation context fails closed.

Raw chat is not added to durable Project Memory by this gate. The current message is used only for deterministic intent classification; the audit decision stores identity and digests rather than transcript content.

## Intent and structured output
The model cannot define its own authority. A deterministic coarse classifier derives one of:

- `observe` -> L0 maximum;
- `propose` -> L1 maximum;
- `paper_action` -> L2 maximum;
- `workflow` -> L3 maximum;
- `owner_sensitive` -> L4 / human required.

Model output must match an exact schema for intent, action, tool, parameters, requested authority, retry count, timeout, delegation depth and cancellation. A claimed intent that disagrees with deterministic classification is blocked. Unknown fields, malformed output and sensitive/live fields fail closed.

## Authority model
L0/L1 may observe or propose without a tool route. They may not smuggle a tool call.

L2/L3 require an enabled registered tool, an allowed intent, a reversible capability, a tool-specific authority cap and timeout cap, and explicit authorization by the active policy version. L4, owner-sensitive intent, and policy-declared human-required actions always escalate to `owner_required`.

AI, models, tools and agents cannot self-promote authority.

## Bounded execution envelope
Policy and tool contracts bound retry count, timeout and delegation depth. Cancellation is terminal and audit-visible. Blanket retry is not allowed. Gate 10 only selects a validated route; subsequent gates retain tool execution, mission ownership, risk and event-store authority.

## Audit
Each decision records a deterministic digest over actor/session/turn identity, context and Project Memory identity, provider/model/version, policy version, proposal digest, decision/reason, selected route, authority level, evaluation time and correlation ID.

Model/provider identity is therefore explicit per decision. Deterministic reason codes include stale/conflicting context, intent mismatch, self-promotion, retry/timeout/delegation limits, cancellation, unregistered/disabled tool, tool policy denial, non-reversible tool denial, human-required escalation and malformed/ambiguous input.

## Security boundary
No exchange credential, private key, live order, withdrawal, production promotion, billing or signing parameter is accepted. This gate introduces no exchange adapter, production mutation, merge authority, billing authority or irreversible action.
