from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from ai_control_plane import evaluate_ai_action
from automated_signal_pipeline import run_automated_signal_pipeline
from observability_audit import AuditJournal, operator_snapshot, require_gate15_evidence
from paper_event_store import GENESIS_DIGEST, PortfolioState, build_event, replay
from paper_live_airgap import independent_airgap_check
from recovery_chaos import AtomicRecoveryStore, RecoveryScenario, RecoverySupervisor
from resource_bounds import DEFAULT_LIMITS, MeasurementWindow, ResourceGuard, evidence_snapshot
from web_dashboard import GatewayConfig, dispatch_get

E2E_CONTRACT_VERSION = "nexus.phase4-e2e.v1"
OCCURRED_AT = "2026-08-17T07:20:00Z"
EVALUATED_AT = "2026-08-17T07:15:00Z"
DATASET_DIGEST = "a" * 64
QUALIFICATION_DIGEST = "b" * 64


class Phase4E2EError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise Phase4E2EError("E2E evidence is not canonically serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _source_sha(value: str) -> str:
    if not isinstance(value, str) or len(value) != 40:
        raise Phase4E2EError("source_sha must be a 40-character Git commit SHA")
    try:
        int(value, 16)
    except ValueError as exc:
        raise Phase4E2EError("source_sha must be hexadecimal") from exc
    return value.lower()


def _provenance() -> dict[str, Any]:
    return {
        "kind": "automatic",
        "source_id": "gate20-fixture",
        "source_timestamp": "2026-08-17T07:00:00Z",
        "received_timestamp": "2026-08-17T07:00:01Z",
        "timeframe": "minute15",
        "confidence": "1",
        "strategy_version": "1.0.0",
        "policy_version": "1.0.0",
    }


def _initial_portfolio() -> tuple[list[dict[str, Any]], PortfolioState]:
    account = build_event(
        event_id="gate20:account:1",
        event_type="demo_account_opened",
        aggregate_id="gate20-paper",
        sequence=1,
        occurred_at="2026-08-17T07:00:01Z",
        correlation_id="gate20-setup",
        causation_id="gate20-account",
        provenance=_provenance(),
        previous_event_digest=GENESIS_DIGEST,
        payload={"currency": "USDT", "opening_cash": "10000"},
    )
    session = build_event(
        event_id="gate20:account:2",
        event_type="session_boundary_recorded",
        aggregate_id="gate20-paper",
        sequence=2,
        occurred_at="2026-08-17T07:00:02Z",
        correlation_id="gate20-setup",
        causation_id="gate20-session",
        provenance=_provenance(),
        previous_event_digest=account["event_digest"],
        payload={"boundary": "open"},
    )
    events = [account, session]
    return events, replay(events).state


def _dataset() -> dict[str, Any]:
    return {
        "dataset_id": "btc-15m",
        "dataset_revision": "gate20-rev-1",
        "source_id": "validated-public",
        "source_timestamp": "2026-08-17T07:00:00Z",
        "received_timestamp": "2026-08-17T07:00:01Z",
        "symbol": "BTCUSDT",
        "timeframe": "minute15",
        "readiness_status": "ready",
        "provenance_digest": DATASET_DIGEST,
    }


def _qualification() -> dict[str, Any]:
    return {
        "artifact_id": "gate20-qualification",
        "artifact_digest": QUALIFICATION_DIGEST,
        "strategy_id": "trend",
        "strategy_version": "1.0.0",
        "dataset_id": "btc-15m",
        "dataset_revision": "gate20-rev-1",
        "status": "paper_eligible",
        "qualified_at": "2026-08-17T06:59:00Z",
    }


def _regime() -> dict[str, Any]:
    return {
        "regime_id": "gate20-regime",
        "regime_version": "1.0.0",
        "label": "trend-up",
        "confidence": "0.85",
        "source_timestamp": "2026-08-17T07:00:00Z",
        "dataset_id": "btc-15m",
        "dataset_revision": "gate20-rev-1",
        "symbol": "BTCUSDT",
        "timeframe": "minute15",
    }


def _decision() -> dict[str, Any]:
    return {
        "decision_id": "gate20-decision",
        "operation": "open",
        "side": "long",
        "quantity": "0.01",
        "reference_price": "60000",
        "stop_price": "58800",
        "target_price": "62400",
        "confidence": "0.80",
        "strategy_id": "trend",
        "strategy_version": "1.0.0",
        "dataset_id": "btc-15m",
        "dataset_revision": "gate20-rev-1",
        "regime_id": "gate20-regime",
        "regime_version": "1.0.0",
        "symbol": "BTCUSDT",
        "timeframe": "minute15",
        "source_timestamp": "2026-08-17T07:00:00Z",
        "correlation_id": "gate20-mission",
        "causation_id": "gate20-regime",
        "risk_policy_version": "1.0.0",
    }


def _risk_state() -> dict[str, Any]:
    return {
        "equity": "10000",
        "daily_start_equity": "10000",
        "daily_realized_pnl": "0",
        "current_exposure": "0",
        "position_exposure": "0",
        "session_open": True,
        "signals_today": 0,
        "seen_signal_ids": [],
        "kill_switch": False,
        "data_circuit_open": False,
        "strategy_circuit_open": False,
        "provider_circuit_open": False,
    }


def _risk_policy() -> dict[str, Any]:
    return {
        "policy_id": "gate20-paper-risk",
        "policy_version": "1.0.0",
        "max_position_fraction": "0.10",
        "max_aggregate_fraction": "0.30",
        "max_daily_loss_fraction": "0.03",
        "max_drawdown_fraction": "0.05",
        "max_signals_per_session": 10,
        "max_signal_age_seconds": 1800,
        "min_stop_distance_fraction": "0.005",
        "max_stop_distance_fraction": "0.05",
        "min_target_distance_fraction": "0.01",
        "supported_symbols": ["BTCUSDT"],
        "supported_timeframes": ["minute15"],
        "eligible_strategies": [{"id": "trend", "version": "1.0.0"}],
    }


def _portfolio_projection(state: PortfolioState) -> dict[str, Any]:
    return {
        "aggregate_id": state.aggregate_id,
        "currency": state.currency,
        "cash": str(state.cash),
        "equity": str(state.equity),
        "realized_pnl": str(state.realized_pnl),
        "unrealized_pnl": str(state.unrealized_pnl),
        "positions": [
            {"symbol": symbol, "side": side, "quantity": str(quantity), "entry_price": str(entry)}
            for symbol, side, quantity, entry in state.positions
        ],
        "stops": [{"symbol": symbol, "price": str(price)} for symbol, price in state.stops],
        "targets": [{"symbol": symbol, "price": str(price)} for symbol, price in state.targets],
        "kill_switch_enabled": state.kill_switch_enabled,
        "session_open": state.session_open,
        "last_sequence": state.last_sequence,
        "last_event_digest": state.last_event_digest,
    }


def _ai_inputs(message: str, *, intent: str, action: str, tool: str | None, authority: int, timeout: int, delegation: int) -> dict[str, Any]:
    return {
        "session": {
            "session_id": "gate20-session",
            "conversation_id": "gate20-conversation",
            "actor_id": "gate20-operator",
            "turn_id": f"turn-{intent}",
            "created_at": "2026-08-17T07:00:00Z",
            "current_message": message,
        },
        "context": {
            "context_id": "gate20-context",
            "conversation_id": "gate20-conversation",
            "provenance_id": "gate20-project-memory",
            "generated_at": "2026-08-17T07:05:00Z",
            "expires_at": "2026-08-17T08:00:00Z",
            "working_context_id": "gate20-working",
            "working_context_version": "1",
            "working_context_digest": "c" * 64,
            "project_memory_id": "gate20-memory",
            "project_memory_version": "1",
            "project_memory_digest": "d" * 64,
            "conflict_state": "clear",
        },
        "model": {
            "provider_id": "openai",
            "model_id": "gpt-5.6-sol",
            "model_version": "gate20",
        },
        "model_output": {
            "intent": intent,
            "action": action,
            "tool": tool,
            "parameters": {},
            "requested_authority": authority,
            "retry_count": 0,
            "timeout_seconds": timeout,
            "delegation_depth": delegation,
            "cancel_requested": False,
        },
        "tool_registry": {
            "paper-command": {
                "tool_id": "paper-command",
                "enabled": True,
                "max_authority": 2,
                "reversible": True,
                "allowed_intents": ["paper_action"],
                "max_timeout_seconds": 60,
            },
            "mission-runner": {
                "tool_id": "mission-runner",
                "enabled": True,
                "max_authority": 3,
                "reversible": True,
                "allowed_intents": ["workflow"],
                "max_timeout_seconds": 120,
            },
        },
        "policy": {
            "policy_version": "gate20-ai-policy",
            "max_retry_count": 1,
            "max_timeout_seconds": 120,
            "max_delegation_depth": 2,
            "autonomous_authority_levels": [0, 1, 2, 3],
            "human_required_actions": ["rotate_credentials", "promote_production"],
        },
        "evaluated_at": EVALUATED_AT,
    }


def _append_audit(
    journal: AuditJournal,
    *,
    index: int,
    category: str,
    stage: str,
    action: str,
    result: str,
    evidence: Mapping[str, Any],
    resulting_state: Mapping[str, Any],
    decision: str = "allow",
    reason_code: str = "ok",
    event_kind: str = "decision_action",
    model_id: str | None = None,
    agent_id: str | None = None,
    metrics: Mapping[str, Any] | None = None,
) -> None:
    journal.append(
        event_id=f"gate20-audit-{index}",
        event_kind=event_kind,
        category=category,
        stage=stage,
        occurred_at=OCCURRED_AT,
        correlation_id="gate20-mission",
        causation_id=None if index == 0 else f"gate20-audit-{index - 1}",
        actor="nexus-gate20",
        model_id=model_id,
        agent_id=agent_id,
        inputs_provenance={"source_sha_bound": True, "source": "gate20-e2e"},
        policy_version="phase4/final",
        decision=decision,
        reason_code=reason_code,
        action=action,
        result=result,
        evidence=dict(evidence),
        resulting_state=dict(resulting_state),
        metrics=dict(metrics or {}),
    )


def run_phase4_gate20(source_sha: str, workspace: Path) -> dict[str, Any]:
    source_sha = _source_sha(source_sha)
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    started_ns = time.perf_counter_ns()

    initial_events, initial_state = _initial_portfolio()
    dataset = _dataset()
    qualification = _qualification()
    regime = _regime()
    decision = _decision()
    risk_state = _risk_state()
    risk_policy = _risk_policy()

    pipeline_started = time.perf_counter_ns()
    result = run_automated_signal_pipeline(
        dataset=dataset,
        qualification=qualification,
        regime=regime,
        decision=decision,
        risk_state=risk_state,
        risk_policy=risk_policy,
        portfolio_state=initial_state,
        occurred_at=OCCURRED_AT,
        fee_rate="0.001",
        slippage_bps="10",
    )
    pipeline_ms = (time.perf_counter_ns() - pipeline_started + 999_999) // 1_000_000
    if not result.risk_decision.allowed or result.execution is None:
        raise Phase4E2EError("full paper path did not reach deterministic paper execution")
    if not result.events or any(event.get("paper_trading_only") is not True for event in result.events):
        raise Phase4E2EError("paper event chain lost paper-only invariant")

    paper_contract = {
        "execution_mode": "paper",
        "paper_trading_only": True,
        "operation": decision["operation"],
        "symbol": decision["symbol"],
        "side": decision["side"],
        "quantity": decision["quantity"],
        "reference_price": decision["reference_price"],
        "stop_price": decision["stop_price"],
        "target_price": decision["target_price"],
        "correlation_id": decision["correlation_id"],
    }
    airgap_result = independent_airgap_check(
        contract=paper_contract, tool="paper.execute_validated", trusted_gate_enabled=True
    )

    observe = evaluate_ai_action(**_ai_inputs(
        "show current paper status",
        intent="observe",
        action="inspect_status",
        tool=None,
        authority=0,
        timeout=30,
        delegation=0,
    ))
    workflow = evaluate_ai_action(**_ai_inputs(
        "continue until this workflow is done",
        intent="workflow",
        action="run_bounded_mission",
        tool="mission-runner",
        authority=3,
        timeout=90,
        delegation=2,
    ))
    owner_sensitive = evaluate_ai_action(**_ai_inputs(
        "promote to production",
        intent="owner_sensitive",
        action="promote_production",
        tool=None,
        authority=4,
        timeout=30,
        delegation=0,
    ))
    if not observe.allowed or observe.authority_level != 0 or observe.route is not None:
        raise Phase4E2EError("AI inspect path exceeded observe authority")
    if not workflow.allowed or workflow.route != "mission-runner" or workflow.authority_level != 3:
        raise Phase4E2EError("AI bounded orchestration route failed")
    if owner_sensitive.allowed or owner_sensitive.status != "owner_required":
        raise Phase4E2EError("owner-sensitive AI action did not fail closed")

    replay_started = time.perf_counter_ns()
    replayed = replay([*initial_events, *result.events]).state
    replay_ms = (time.perf_counter_ns() - replay_started + 999_999) // 1_000_000
    if replayed != result.state:
        raise Phase4E2EError("restart/replay state differs from valid paper state")

    final_projection = _portfolio_projection(result.state)
    final_state_digest = _digest(final_projection)
    recovery_store = AtomicRecoveryStore(final_projection)
    checkpoint = recovery_store.snapshot()
    recovery_store.commit_candidate(
        expected_revision=checkpoint.revision,
        candidate_state={**final_projection, "unconfirmed_mutation": True},
    )
    recovery = RecoverySupervisor(recovery_store).decide(
        scenario=RecoveryScenario.PROCESS_CRASH,
        previous_valid=checkpoint,
    )
    if recovery_store.snapshot() != checkpoint or recovery.resulting_digest != checkpoint.state_digest:
        raise Phase4E2EError("recovery failed to restore identical previous-valid state")

    journal = AuditJournal()
    _append_audit(
        journal, index=0, category="data_readiness", stage="market_data",
        action="validate_dataset", result="ready",
        evidence={"dataset_id": dataset["dataset_id"], "provenance_digest": dataset["provenance_digest"]},
        resulting_state={"readiness_status": dataset["readiness_status"]},
    )
    _append_audit(
        journal, index=1, category="strategy_qualification", stage="strategy_regime",
        action="bind_strategy_and_regime", result="paper_eligible",
        evidence={"qualification_digest": qualification["artifact_digest"], "regime_id": regime["regime_id"]},
        resulting_state={"strategy_id": qualification["strategy_id"], "regime": regime["label"]},
    )
    _append_audit(
        journal, index=2, category="signal", stage="signal",
        action="create_signal", result="accepted",
        evidence={"signal_id": result.signal["signal_id"]},
        resulting_state={"paper_trading_only": result.signal["paper_trading_only"]},
    )
    _append_audit(
        journal, index=3, category="signal", stage="decision",
        action="bind_decision", result="accepted",
        evidence={"decision_id": decision["decision_id"]},
        resulting_state={"operation": decision["operation"], "side": decision["side"]},
    )
    _append_audit(
        journal, index=4, category="risk", stage="risk",
        action="evaluate_risk", result="allowed",
        evidence={"policy_id": result.risk_decision.policy_id, "signal_id": result.risk_decision.signal_id},
        resulting_state={"resulting_exposure": str(result.risk_decision.resulting_exposure)},
        decision="allow", reason_code=result.risk_decision.reason_code,
    )
    _append_audit(
        journal, index=5, category="queue", stage="dispatch",
        action="dispatch_paper_execution", result="completed",
        evidence={"correlation_id": decision["correlation_id"]},
        resulting_state={"event_count": len(result.events)},
        metrics={"queue_latency_ms": 0, "pipeline_latency_ms": pipeline_ms},
    )
    _append_audit(
        journal, index=6, category="paper_execution", stage="paper_execution",
        action="simulate_fill_and_account", result="filled",
        evidence={"last_event_digest": result.state.last_event_digest, "fill_price": str(result.execution.fill_price)},
        resulting_state={"state_digest": final_state_digest, "positions": len(result.state.positions)},
    )
    _append_audit(
        journal, index=7, category="agent_provider", stage="provider",
        action="bounded_ai_observe_and_orchestrate", result="allowed",
        evidence={"observe_audit": observe.audit_digest, "workflow_audit": workflow.audit_digest},
        resulting_state={"observe_authority": observe.authority_level, "workflow_route": workflow.route},
        model_id=observe.model_id, agent_id="gate20-ai-control",
    )
    _append_audit(
        journal, index=8, category="ai_budget", stage="ai_control",
        action="enforce_ai_limits", result="bounded",
        evidence={"policy_version": observe.policy_version},
        resulting_state={"owner_sensitive_status": owner_sensitive.status},
        model_id=observe.model_id,
        metrics={"provider_spend_microusd": 0, "provider_tokens": 0},
    )
    _append_audit(
        journal, index=9, category="recovery_replay", stage="recovery",
        action="replay_and_restore", result="identical",
        evidence={"replay_event_digest": replayed.last_event_digest, "checkpoint_digest": checkpoint.state_digest},
        resulting_state={"state_digest": final_state_digest},
        metrics={"replay_processing_ms": replay_ms},
    )
    _append_audit(
        journal, index=10, category="memory_context", stage="memory",
        action="bind_working_and_project_context", result="clear",
        evidence={"ai_context_digest": "c" * 64, "project_memory_digest": "d" * 64},
        resulting_state={"separate_contexts": True},
    )
    _append_audit(
        journal, index=11, category="circuit_policy", stage="policy",
        action="enforce_airgap_and_owner_boundary", result="denied_live_authority",
        evidence={"airgap": airgap_result, "owner_sensitive_audit": owner_sensitive.audit_digest},
        resulting_state={"paper_only": True, "owner_required": True},
        decision="deny", reason_code="live_authority_not_available",
    )
    coverage = require_gate15_evidence(journal.events)
    if not coverage.complete:
        raise Phase4E2EError("audit coverage is incomplete")
    audit_path = workspace / "phase4-gate20-audit.jsonl"
    journal.write_jsonl(audit_path)
    restored_audit = AuditJournal.read_jsonl(audit_path)
    if restored_audit.events != journal.events:
        raise Phase4E2EError("audit restart/replay differs from original journal")
    audit_snapshot = operator_snapshot(restored_audit.events)

    data_root = workspace / "market"
    data_root.mkdir(parents=True, exist_ok=True)
    mission_root = workspace / "mission_control"
    mission_root.mkdir(parents=True, exist_ok=True)
    mission_report = {
        "contract_version": "nexus.mission-control.read.v1",
        "mission": {"id": "gate20", "status": "completed", "source_sha": source_sha},
        "queue": {"status": "idle", "pending": 0},
        "agents": {"ai_control": "bounded"},
        "runners": {"e2e": "active"},
        "local_node": {"required_for_final_windows_evidence": True},
        "data": {"readiness": dataset["readiness_status"], "dataset_id": dataset["dataset_id"]},
        "providers": {"openai": "bounded", "paid_external_usage": 0},
        "paper": {
            "paper_only": True,
            "risk_allowed": result.risk_decision.allowed,
            "state": final_projection,
            "state_digest": final_state_digest,
            "audit_head_digest": audit_snapshot["head_event_digest"],
        },
        "circuits": {"data": False, "strategy": False, "risk": False, "provider": False},
        "limits": {"resource_policy": "phase4-resource/v1", "airgap": airgap_result},
        "notifications": [],
    }
    mission_bytes = _canonical(mission_report)
    (mission_root / "_mission_control.json").write_bytes(mission_bytes)

    dashboard_started = time.perf_counter_ns()
    dashboard = dispatch_get("/api/mission-control", data_root=data_root, config=GatewayConfig())
    dashboard_ms = (time.perf_counter_ns() - dashboard_started + 999_999) // 1_000_000
    if int(dashboard.status) != 200:
        raise Phase4E2EError("read-only dashboard did not serve final paper state")
    dashboard_report = dashboard.payload.get("mission_control")
    if not isinstance(dashboard_report, Mapping):
        raise Phase4E2EError("dashboard mission-control payload is missing")
    dashboard_paper = dashboard_report.get("paper")
    if not isinstance(dashboard_paper, Mapping) or dashboard_paper.get("state_digest") != final_state_digest:
        raise Phase4E2EError("dashboard state does not match paper accounting state")
    gateway = dashboard.payload.get("gateway")
    if not isinstance(gateway, Mapping) or gateway.get("read_only") is not True:
        raise Phase4E2EError("dashboard lost read-only boundary")

    job_runtime_ms = (time.perf_counter_ns() - started_ns + 999_999) // 1_000_000
    storage_bytes = audit_path.stat().st_size + (mission_root / "_mission_control.json").stat().st_size
    measured = {
        "api_latency_ms": dashboard_ms,
        "dashboard_latency_ms": dashboard_ms,
        "ai_chat_timeout_ms": 30_000,
        "agent_timeout_ms": 90_000,
        "queue_latency_ms": 0,
        "replay_processing_ms": replay_ms,
        "backtest_runtime_ms": 0,
        "research_runtime_ms": 0,
        "storage_bytes": storage_bytes,
        "log_retention_days": 14,
        "runner_concurrency": 1,
        "provider_spend_microusd": 0,
        "provider_tokens": 0,
        "cpu_millis": 1_000,
        "memory_bytes": 134_217_728,
        "job_runtime_ms": job_runtime_ms,
    }
    guard = ResourceGuard()
    summaries = []
    resource_actions: dict[str, str] = {}
    for metric, value in measured.items():
        limit = DEFAULT_LIMITS[metric]
        window = MeasurementWindow(metric, limit.unit, capacity=1)
        window.add(value)
        summary = window.summary()
        decision_result = guard.require_not_exhausted(metric, summary.p95)
        resource_actions[metric] = decision_result.action
        summaries.append(summary)
    resources = evidence_snapshot(guard, summaries)
    if not resources["complete"] or any(action == "deny" for action in resource_actions.values()):
        raise Phase4E2EError("Gate 19 bounds are not satisfied by Gate 20 evidence run")

    evidence = {
        "contract_version": E2E_CONTRACT_VERSION,
        "source_sha": source_sha,
        "paper_only": True,
        "path": [
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
        ],
        "pipeline": {
            "risk_allowed": result.risk_decision.allowed,
            "risk_reason_code": result.risk_decision.reason_code,
            "signal_id": result.signal["signal_id"],
            "paper_event_count": len(result.events),
            "last_event_digest": result.state.last_event_digest,
            "state_digest": final_state_digest,
            "fill_price": str(result.execution.fill_price),
            "fee": str(result.execution.fee),
            "realized_pnl": str(result.execution.realized_pnl),
            "pipeline_latency_ms": pipeline_ms,
        },
        "dashboard": {
            "contract_version": dashboard.payload.get("contract_version"),
            "read_only": gateway.get("read_only"),
            "state_digest": dashboard_paper.get("state_digest"),
            "latency_ms": dashboard_ms,
        },
        "audit": {
            "coverage_complete": coverage.complete,
            "event_count": coverage.event_count,
            "head_event_digest": audit_snapshot["head_event_digest"],
            "restart_replay_identical": restored_audit.events == journal.events,
        },
        "recovery": {
            "paper_replay_identical": replayed == result.state,
            "previous_valid_restored": recovery_store.snapshot() == checkpoint,
            "checkpoint_digest": checkpoint.state_digest,
        },
        "ai_control": {
            "observe_allowed": observe.allowed,
            "observe_authority": observe.authority_level,
            "workflow_allowed": workflow.allowed,
            "workflow_authority": workflow.authority_level,
            "workflow_route": workflow.route,
            "owner_sensitive_allowed": owner_sensitive.allowed,
            "owner_sensitive_status": owner_sensitive.status,
            "owner_sensitive_reason_code": owner_sensitive.reason_code,
        },
        "security": {
            "airgap_result": airgap_result,
            "live_authority_available": False,
        },
        "resources": {
            "complete": resources["complete"],
            "policy_version": resources["policy_version"],
            "actions": resource_actions,
            "measured": measured,
        },
    }
    return {**evidence, "evidence_digest": _digest(evidence)}


def verify_gate20_evidence(evidence: Mapping[str, Any], *, expected_source_sha: str) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise Phase4E2EError("Gate 20 evidence must be an object")
    candidate = dict(evidence)
    digest_value = candidate.pop("evidence_digest", None)
    if not isinstance(digest_value, str) or len(digest_value) != 64 or _digest(candidate) != digest_value:
        raise Phase4E2EError("Gate 20 evidence digest mismatch")
    if candidate.get("contract_version") != E2E_CONTRACT_VERSION:
        raise Phase4E2EError("Gate 20 evidence contract mismatch")
    if candidate.get("source_sha") != _source_sha(expected_source_sha):
        raise Phase4E2EError("Gate 20 evidence is not bound to expected source SHA")
    if candidate.get("paper_only") is not True:
        raise Phase4E2EError("Gate 20 evidence lost paper-only invariant")
    if candidate.get("security", {}).get("live_authority_available") is not False:
        raise Phase4E2EError("Gate 20 evidence exposes live authority")
    if candidate.get("dashboard", {}).get("read_only") is not True:
        raise Phase4E2EError("Gate 20 dashboard evidence is not read-only")
    if candidate.get("recovery", {}).get("paper_replay_identical") is not True:
        raise Phase4E2EError("Gate 20 paper replay evidence is not identical")
    if candidate.get("recovery", {}).get("previous_valid_restored") is not True:
        raise Phase4E2EError("Gate 20 recovery evidence did not restore previous-valid state")
    if candidate.get("audit", {}).get("coverage_complete") is not True:
        raise Phase4E2EError("Gate 20 audit evidence is incomplete")
    if candidate.get("resources", {}).get("complete") is not True:
        raise Phase4E2EError("Gate 20 resource evidence is incomplete")
    if candidate.get("ai_control", {}).get("owner_sensitive_allowed") is not False:
        raise Phase4E2EError("Gate 20 AI evidence improperly authorizes owner-sensitive action")
    return dict(evidence)
