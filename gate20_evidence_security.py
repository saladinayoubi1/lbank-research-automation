from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from phase4_e2e import (
    Phase4E2EError,
    run_phase4_gate20,
    verify_gate20_evidence,
)

EXPECTED_PATH = [
    "validated_data",
    "qualified_strategy",
    "signal",
    "decision",
    "deterministic_risk",
    "paper_fill_position",
    "accounting",
    "dashboard",
    "event_audit",
    "restart_replay",
    "identical_valid_state",
]


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise Phase4E2EError(f"{field} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise Phase4E2EError(f"{field} must be hexadecimal") from exc
    return value.lower()


def _critical_projection(evidence: Mapping[str, Any]) -> dict[str, Any]:
    pipeline = evidence.get("pipeline")
    dashboard = evidence.get("dashboard")
    audit = evidence.get("audit")
    recovery = evidence.get("recovery")
    ai_control = evidence.get("ai_control")
    security = evidence.get("security")
    resources = evidence.get("resources")
    for field, value in (
        ("pipeline", pipeline),
        ("dashboard", dashboard),
        ("audit", audit),
        ("recovery", recovery),
        ("ai_control", ai_control),
        ("security", security),
        ("resources", resources),
    ):
        if not isinstance(value, Mapping):
            raise Phase4E2EError(f"Gate 20 {field} evidence must be an object")

    state_digest = _sha256(pipeline.get("state_digest"), "pipeline.state_digest")
    dashboard_state_digest = _sha256(dashboard.get("state_digest"), "dashboard.state_digest")
    last_event_digest = _sha256(pipeline.get("last_event_digest"), "pipeline.last_event_digest")
    _sha256(audit.get("head_event_digest"), "audit.head_event_digest")
    checkpoint_digest = _sha256(recovery.get("checkpoint_digest"), "recovery.checkpoint_digest")

    if evidence.get("path") != EXPECTED_PATH:
        raise Phase4E2EError("Gate 20 path contract mismatch")
    if state_digest != dashboard_state_digest:
        raise Phase4E2EError("Gate 20 dashboard state digest is not bound to pipeline state")
    if pipeline.get("risk_allowed") is not True or pipeline.get("risk_reason_code") != "risk_allowed":
        raise Phase4E2EError("Gate 20 deterministic Risk claim is not allowed")
    if not isinstance(pipeline.get("paper_event_count"), int) or pipeline["paper_event_count"] < 4:
        raise Phase4E2EError("Gate 20 paper event evidence is incomplete")
    if audit.get("restart_replay_identical") is not True:
        raise Phase4E2EError("Gate 20 audit replay evidence is not identical")
    if security.get("airgap_result") != "independent_paper_airgap_pass":
        raise Phase4E2EError("Gate 20 independent paper/live air-gap evidence failed")
    if ai_control.get("observe_allowed") is not True or ai_control.get("observe_authority") != 0:
        raise Phase4E2EError("Gate 20 AI observe authority claim is invalid")
    if (
        ai_control.get("workflow_allowed") is not True
        or ai_control.get("workflow_authority") != 3
        or ai_control.get("workflow_route") != "mission-runner"
    ):
        raise Phase4E2EError("Gate 20 bounded AI workflow claim is invalid")
    if (
        ai_control.get("owner_sensitive_allowed") is not False
        or ai_control.get("owner_sensitive_status") != "owner_required"
        or ai_control.get("owner_sensitive_reason_code") != "human_required"
    ):
        raise Phase4E2EError("Gate 20 owner-sensitive AI claim is invalid")

    actions = resources.get("actions")
    if not isinstance(actions, Mapping) or any(action == "deny" for action in actions.values()):
        raise Phase4E2EError("Gate 20 resource evidence contains a denied bound")

    return {
        "contract_version": evidence.get("contract_version"),
        "source_sha": evidence.get("source_sha"),
        "paper_only": evidence.get("paper_only"),
        "path": list(evidence.get("path", [])),
        "pipeline": {
            "risk_allowed": pipeline.get("risk_allowed"),
            "risk_reason_code": pipeline.get("risk_reason_code"),
            "signal_id": pipeline.get("signal_id"),
            "paper_event_count": pipeline.get("paper_event_count"),
            "last_event_digest": last_event_digest,
            "state_digest": state_digest,
            "fill_price": pipeline.get("fill_price"),
            "fee": pipeline.get("fee"),
            "realized_pnl": pipeline.get("realized_pnl"),
        },
        "dashboard": {
            "contract_version": dashboard.get("contract_version"),
            "read_only": dashboard.get("read_only"),
            "state_digest": dashboard_state_digest,
        },
        "audit": {
            "coverage_complete": audit.get("coverage_complete"),
            "event_count": audit.get("event_count"),
            "restart_replay_identical": audit.get("restart_replay_identical"),
        },
        "recovery": {
            "paper_replay_identical": recovery.get("paper_replay_identical"),
            "previous_valid_restored": recovery.get("previous_valid_restored"),
            "checkpoint_digest": checkpoint_digest,
        },
        "ai_control": {
            "observe_allowed": ai_control.get("observe_allowed"),
            "observe_authority": ai_control.get("observe_authority"),
            "workflow_allowed": ai_control.get("workflow_allowed"),
            "workflow_authority": ai_control.get("workflow_authority"),
            "workflow_route": ai_control.get("workflow_route"),
            "owner_sensitive_allowed": ai_control.get("owner_sensitive_allowed"),
            "owner_sensitive_status": ai_control.get("owner_sensitive_status"),
            "owner_sensitive_reason_code": ai_control.get("owner_sensitive_reason_code"),
        },
        "security": dict(security),
    }


def verify_gate20_evidence_strict(
    evidence: Mapping[str, Any],
    *,
    expected_source_sha: str,
    verification_workspace: Path,
) -> dict[str, Any]:
    """Verify the envelope, then independently rerun deterministic Gate 20 security claims.

    Runtime latency and audit-chain head telemetry are intentionally not compared byte-for-byte;
    all deterministic trading, recovery, authority, and air-gap claims are re-derived from the
    exact source SHA and compared fail-closed.
    """
    verified = verify_gate20_evidence(evidence, expected_source_sha=expected_source_sha)
    supplied_projection = _critical_projection(verified)

    reference = run_phase4_gate20(expected_source_sha, Path(verification_workspace))
    verify_gate20_evidence(reference, expected_source_sha=expected_source_sha)
    reference_projection = _critical_projection(reference)

    if supplied_projection != reference_projection:
        raise Phase4E2EError(
            "Gate 20 security-critical evidence does not match independent exact-SHA rerun"
        )
    return dict(verified)
