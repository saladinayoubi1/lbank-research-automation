"""Typed composite case of QUAL-42; independent numerical review is not Demo admission.

Keep composite producer/task/receipt schemas intact. No synthetic simple-family
pipeline or proposal identities are invented to make the generic gate accept them.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from nexus_composite_evidence_adequacy import assess
from nexus_composite_runtime_independent_qa import digest, validate_task, verify_receipt

SCHEMA = "nexus.composite-strategy-qualification-gate.v1"
VERIFY_SCHEMA = "nexus.composite-strategy-qualification-verification.v1"
WAITING = frozenset({"PENDING", "READY", "LEASED", "RUNNING", "VERIFYING"})
REJECTED = frozenset({"BLOCKED", "QUARANTINED"})


class CompositeQualificationError(ValueError):
    pass


def evaluate(manager_task: Mapping[str, Any]) -> dict[str, Any]:
    """Admit only an exact DONE QA lease to a non-activating research registry record."""
    if not isinstance(manager_task, Mapping):
        raise CompositeQualificationError("composite Agent Manager task is missing")
    handoff = manager_task.get("qa_handoff_task")
    if not isinstance(handoff, Mapping):
        raise CompositeQualificationError("composite QA handoff is missing")
    try:
        task = validate_task(handoff, str(handoff.get("source_sha", "")))
        # Recompute chronology/accounting even for a self-consistent old task.
        # The original v1 validator alone does not repeat this issuance check.
        observation = assess(task["producer"])
    except (ValueError, KeyError, TypeError) as exc:
        raise CompositeQualificationError("composite QA source/evidence verification failed") from exc
    if observation["decision"] != "READY_FOR_INDEPENDENT_QA_ONLY":
        raise CompositeQualificationError("composite observation coverage is insufficient")
    authority = manager_task.get("authority")
    status = manager_task.get("status")
    if (
        manager_task.get("id") != task["id"]
        or manager_task.get("qa_verifier_only") is not True
        or manager_task.get("qa_dispatch_enabled") is not True
        or manager_task.get("required_verifier") != "qa-verifier-agent"
        or type(authority) is not int or not 0 <= authority <= 2
        or manager_task.get("producer") not in (None, "")
        or not isinstance(status, str)
        or status not in WAITING | REJECTED | {"DONE"}
    ):
        raise CompositeQualificationError("composite Agent Manager QA boundary is invalid")

    producer = task["producer"]
    candidate = producer["candidate"]
    config = deepcopy(producer["strategy_config"])
    core = {
        "schema_version": SCHEMA,
        "system_map_node": "QUAL-42",
        "strategy_kind": "composite_mechanism",
        "strategy_qa_task_id": task["id"],
        "qa_task_status": status,
        "qa_task_digest": task["task_digest"],
        "qa_handoff_task": deepcopy(task),
        "source_sha": task["source_sha"],
        "candidate_source_sha": producer["candidate_source_sha"],
        "candidate_digest": task["candidate_digest"],
        "research_report_digest": candidate["research_report_digest"],
        "research_producer_receipt_digest": candidate["producer_receipt_digest"],
        "producer_workflow_run_id": task["producer_workflow_run_id"],
        "requalification_digest": task["requalification_digest"],
        "requalification_verification_digest": task["requalification_verification_digest"],
        "runtime_as_of_ms": task["runtime_as_of_ms"],
        "family": producer["mechanism"],
        "mechanism": producer["mechanism"],
        "timeframe": producer["timeframe"],
        "variant_id": producer["config_fingerprint"],
        "config_fingerprint": producer["config_fingerprint"],
        "strategy_config": config,
        "strategy_config_digest": digest(config),
        # Native two-symbol, three-timeframe, two-cost evidence, never relabeled
        # as a simple-family pipeline/qualification receipt.
        "runtime_evidence": deepcopy(producer["evaluations"]),
        "runtime_evidence_digest": producer["evaluations_digest"],
        "observation_adequacy": observation,
        "registration_scope": "INDEPENDENT_NUMERICAL_RESEARCH_CANDIDATE_ONLY",
        "economic_edge_established": False,
        "pristine_prospective_evidence_present": False,
        "owner_shared_500_portfolio_verified": False,
        "owner_demo_admission_allowed": False,
        "no_minimum_trade_count_gate": True,
        "paper_only": True,
        "registry_mutation_performed": False,
        "runtime_activation_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    lease, receipt = None, None
    if status == "DONE":
        lease = manager_task.get("lease_id")
        receipt = manager_task.get("verification_evidence")
        if (
            manager_task.get("verifier") != "qa-verifier-agent"
            or manager_task.get("assigned_worker") not in (None, "qa-verifier-agent")
            or not isinstance(lease, str) or not lease or len(lease) > 160
            or not isinstance(receipt, Mapping)
            or not verify_receipt(receipt, task, lease_id=lease,
                                  execution_source_sha=task["source_sha"])
        ):
            raise CompositeQualificationError("DONE composite QA lacks the exact verifier receipt")
        decision, reasons = "QUALIFIED_FOR_REGISTRY", ["INDEPENDENT_COMPOSITE_QA_VERIFIED"]
    elif status in REJECTED:
        decision, reasons = "REJECTED", ["INDEPENDENT_QA_" + status]
    else:
        decision, reasons = "WAITING_FOR_QA", ["INDEPENDENT_QA_INCOMPLETE"]
    core.update({
        "decision": decision,
        "qualified": status == "DONE",
        "registry_admission_allowed": status == "DONE",
        "reason_codes": reasons,
        "qa_lease_id": lease,
        "qa_receipt": deepcopy(dict(receipt)) if receipt is not None else None,
        "qa_receipt_digest": receipt["qa_receipt_digest"] if receipt is not None else None,
    })
    return {**core, "qualification_digest": digest(core)}


def verify(value: Mapping[str, Any]) -> dict[str, Any]:
    """Reconstruct the native contract, including receipt and observation checks."""
    checks = {"schema": False, "digest": False, "binding": False}
    try:
        core = dict(value)
        claimed = core.pop("qualification_digest", None)
        checks["schema"] = core.get("schema_version") == SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == digest(core)
        status = core.get("qa_task_status")
        manager = {
            "id": core.get("strategy_qa_task_id"),
            "status": status,
            "authority": 2,
            "qa_verifier_only": True,
            "qa_dispatch_enabled": True,
            "required_verifier": "qa-verifier-agent",
            "qa_handoff_task": core.get("qa_handoff_task"),
            "verifier": "qa-verifier-agent" if status == "DONE" else None,
            "lease_id": core.get("qa_lease_id"),
            "verification_evidence": core.get("qa_receipt"),
        }
        checks["binding"] = dict(value) == evaluate(manager)
    except (ValueError, KeyError, TypeError):
        pass
    result = {
        "schema_version": VERIFY_SCHEMA,
        "decision": "pass" if all(checks.values()) else "reject",
        "checks": checks,
        "qualification_digest": value.get("qualification_digest"),
    }
    return {**result, "verification_digest": digest(result)}
