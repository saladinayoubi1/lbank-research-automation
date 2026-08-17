# ADR-023 — Phase 4 Security, Privacy and Paper/Live Air Gap

Status: Gate 18 candidate
Parent: #510

## Decision

Phase 4 remains structurally paper/demo only. Security is enforced by multiple independent layers instead of relying on a UI label or one policy decision.

1. Existing capability and network brokers are deny-by-default, bounded and least-privilege.
2. Existing provider pre-egress policy classifies/redacts outbound advisory payloads and rejects secrets/private transcript material.
3. `paper_live_airgap.py` recursively validates structured proposals/contracts and rejects credential, live-order, withdrawal, production, billing, signing and raw-transcript capability fields.
4. `ToolAllowlist` permits only explicit bounded public/research/risk/paper/read operations; private exchange, live exchange, withdrawal, production, billing, signing and shell namespaces are denied.
5. `scripts/independent_phase4_airgap_gate.py` independently inspects the frozen decision/risk/paper contract key sets and the critical deterministic trading modules. It rejects forbidden authority fields and rejects network/private-exchange client imports in `automated_signal_pipeline.py`, `deterministic_risk.py`, `paper_execution.py` and `paper_event_store.py`.
6. `.github/workflows/phase4-paper-airgap.yml` executes that independent gate and the adversarial Gate 18 tests on every PR/push to `main` with read-only repository permission.

An upstream `allowed=True` cannot bypass the independent contract/tool re-evaluation.

## Privacy and pre-egress

Secret-like fields and values are rejected before structured paper contracts are accepted. Free text is checked for private-key material, bearer authorization, common API-key/token forms and GitHub token prefixes. `redact_for_egress()` removes explicitly supplied secrets and known secret patterns before a final secret scan.

Unnecessary raw chat/conversation transcript fields are forbidden in paper contracts. Existing DeepSeek egress policy separately rejects raw transcript material and redacts user paths/email addresses before provider egress.

## Bounded parsing

Structured contract validation is recursive but bounded by maximum depth, item count, key length and string bytes. Binary floating-point values are rejected so financial structured values remain explicit/canonical.

## Paper/live authority boundary

The independent gate verifies the actual exported key sets used by:

- automated decision input;
- deterministic Risk signal/state/policy;
- paper execution command.

Critical deterministic trading modules are additionally prohibited from importing ambient network/private-exchange client libraries. Therefore the automatic path can transform validated public data into deterministic paper events but cannot acquire a socket/private-exchange order path through its critical authority modules.

## Independent control

Gate 18 has a separate CI workflow with `contents: read` only. The workflow invokes an independent architectural scanner plus adversarial tests. Disabling the runtime trusted gate is itself a hard failure. Existing Workflow Permissions Policy remains a separate repository-wide control over workflow privilege.

## Tests

`tests/test_paper_live_airgap.py` covers:

- valid paper contract and validated paper tool;
- nested credential/live/real-order/withdrawal/billing/signing/production/raw-transcript rejection;
- live/ambiguous mode and false paper-only assertion;
- secret material detection and pre-egress redaction;
- explicit tool allowlist and forbidden authority namespaces;
- attempted custom allowlist smuggling;
- independent gate disable/bypass attempts;
- excessive nesting, unsupported values and binary-float rejection.

## Authority effect

None. This Gate only denies unsafe capabilities and validates air-gap invariants. It cannot approve a strategy, Risk decision, paper fill, provider spend or production action.

## Rollback and recovery

Rollback of this feature cannot introduce live authority: the frozen Phase 4 contract and existing exact-schema Risk/Paper Execution modules remain paper-only. Any future removal or weakening of the independent workflow/scanner is observable as a security-boundary change and must pass the remaining independent workflow-permission/build/test controls.

## Residual risk / next gates

Gate 19 measures performance/resource limits without weakening these controls. Gate 20 must prove the final same-SHA E2E path passes the independent paper/live air-gap workflow and contains no live, credential, withdrawal, production, billing or signing authority.
