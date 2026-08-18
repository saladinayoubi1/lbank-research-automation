from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping

import pandas as pd

import phase6_research_pipeline as research
from deterministic_risk import evaluate_risk
from paper_event_store import GENESIS_DIGEST, build_event, replay
from paper_execution import execute_paper_command
from performance_metrics import calculate_performance_metrics

SCHEMA = "nexus.phase7-e2e-proof.v1"
START = 1_700_000_100_000
STEP = 900_000


class Phase7ProofError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _source_sha(value: str) -> str:
    if not isinstance(value, str) or len(value) != 40 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
        raise Phase7ProofError("source_sha must be a 40-character Git SHA")
    return value.lower()


def _iso_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _candles(count: int = 90) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(count):
        if index < count // 2:
            price = 100.0 - index * 0.8
        else:
            price = 64.0 + (index - count // 2) * 1.4
        rows.append(
            {
                "source": "Bybit",
                "market_type": "spot",
                "symbol": "BTCUSDT",
                "interval": "15",
                "open_time_ms": START + index * STEP,
                "close_time_ms": START + (index + 1) * STEP - 1,
                "open": f"{price:.8f}",
                "high": f"{price * 1.01:.8f}",
                "low": f"{price * 0.99:.8f}",
                "close": f"{price:.8f}",
                "volume": "10",
                "turnover": f"{price * 10:.8f}",
                "closed": True,
            }
        )
    return rows


def _paper_state(*, occurred_at: str, provenance: dict[str, Any]):
    now = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    account_at = (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    session_at = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    first = build_event(
        event_id="phase7-proof:account:1",
        event_type="demo_account_opened",
        aggregate_id="phase7-proof-paper",
        sequence=1,
        occurred_at=account_at,
        correlation_id="phase7-proof-setup",
        causation_id="phase7-proof-account",
        provenance=provenance,
        previous_event_digest=GENESIS_DIGEST,
        payload={"currency": "USDT", "opening_cash": "10000"},
    )
    second = build_event(
        event_id="phase7-proof:account:2",
        event_type="session_boundary_recorded",
        aggregate_id="phase7-proof-paper",
        sequence=2,
        occurred_at=session_at,
        correlation_id="phase7-proof-setup",
        causation_id="phase7-proof-session",
        provenance=provenance,
        previous_event_digest=first["event_digest"],
        payload={"boundary": "open"},
    )
    return replay([first, second]).state


def build_proof(source_sha: str) -> dict[str, Any]:
    source_sha = _source_sha(source_sha)
    candles = _candles()
    dataset = research.bind_bybit_closed_dataset(
        candles,
        canonical_symbol="BTC/USDT",
        source_symbol="BTCUSDT",
        interval="15",
    )
    pipeline = research.run_research_job(
        dataset,
        hypothesis="long-flat momentum avoids the falling regime and participates in the rising regime",
        family="momentum",
        strategy_version="phase7-proof-momentum-v1",
        strategy_config={"lookback": 3, "entry_threshold": 0.0},
        code_sha=source_sha,
        cost_model={
            "fee_bps": 10.0,
            "slippage_bps": 5.0,
            "stress_fee_bps": 20.0,
            "stress_slippage_bps": 10.0,
        },
        kill_criteria={
            "min_robustness_score": -1.0,
            "max_cost_stress_loss_pct": 100.0,
            "min_walk_forward_score": -1.0,
            "min_oos_score": -1.0,
            "max_drawdown_pct": 100.0,
            "min_regime_pass_ratio": 0.0,
            "max_failure_mode_severity": 10.0,
        },
    )
    qualification = pipeline["qualification"]
    handoff = pipeline["paper_candidate_handoff"]
    if qualification.get("status") != "paper_candidate" or not isinstance(handoff, Mapping):
        raise Phase7ProofError("research did not produce a deterministic Paper Candidate")

    source_time = _iso_from_ms(int(candles[-1]["close_time_ms"]))
    evaluated = datetime.fromisoformat(source_time.replace("Z", "+00:00")) + timedelta(minutes=5)
    evaluated_at = evaluated.isoformat().replace("+00:00", "Z")
    reference = Decimal(candles[-1]["close"])
    stop = reference * Decimal("0.98")
    target = reference * Decimal("1.04")
    strategy_id = pipeline["experiment"]["experiment_id"]
    strategy_version = qualification["strategy_version"]
    signal_id = "phase7-proof-signal-1"
    decision_id = _digest(
        {
            "pipeline_digest": pipeline["pipeline_digest"],
            "qualification_digest": qualification["qualification_digest"],
            "signal_id": signal_id,
        }
    )
    signal = {
        "signal_id": signal_id,
        "symbol": "BTCUSDT",
        "timeframe": "minute15",
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "side": "long",
        "quantity": "1",
        "reference_price": str(reference),
        "stop_price": str(stop),
        "target_price": str(target),
        "source_timestamp": source_time,
        "correlation_id": pipeline["pipeline_digest"],
        "causation_id": qualification["qualification_digest"],
        "provenance_kind": "automatic",
    }
    risk_state = {
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
    risk_policy = {
        "policy_id": "phase7-paper-risk",
        "policy_version": "1.0.0",
        "max_position_fraction": "0.10",
        "max_aggregate_fraction": "0.30",
        "max_daily_loss_fraction": "0.03",
        "max_drawdown_fraction": "0.05",
        "max_signals_per_session": 10,
        "max_signal_age_seconds": 900,
        "min_stop_distance_fraction": "0.005",
        "max_stop_distance_fraction": "0.05",
        "min_target_distance_fraction": "0.01",
        "supported_symbols": ["BTCUSDT"],
        "supported_timeframes": ["minute15"],
        "eligible_strategies": [{"id": strategy_id, "version": strategy_version}],
    }
    risk = evaluate_risk(signal, risk_state, risk_policy, evaluated_at=evaluated_at)
    if not risk.allowed:
        raise Phase7ProofError(f"deterministic Risk rejected proof signal: {risk.reason_code}")

    provenance = {
        "kind": "automatic",
        "source_id": dataset["binding_sha256"],
        "source_timestamp": source_time,
        "received_timestamp": source_time,
        "timeframe": "minute15",
        "confidence": "1.0",
        "strategy_version": strategy_version,
        "policy_version": risk.policy_version,
    }
    paper_state = _paper_state(occurred_at=evaluated_at, provenance=provenance)
    command = {
        "operation": "open",
        "symbol": "BTCUSDT",
        "side": "long",
        "quantity": "1",
        "reference_price": str(reference),
        "stop_price": str(stop),
        "target_price": str(target),
        "fee_rate": "0.001",
        "slippage_bps": "10",
        "currency": "USDT",
    }
    execution = execute_paper_command(
        command=command,
        state=paper_state,
        risk_decision=risk,
        occurred_at=evaluated_at,
        provenance=provenance,
        correlation_id=decision_id,
        causation_id=signal_id,
    )
    final_equity = float(execution.state.equity)
    drawdown = min(0.0, final_equity / 10000.0 - 1.0)
    later = (evaluated + timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
    performance = calculate_performance_metrics(
        pd.DataFrame(
            [
                {"timestamp": source_time, "equity": 10000.0, "drawdown": 0.0},
                {"timestamp": evaluated_at, "equity": final_equity, "drawdown": drawdown},
                {"timestamp": later, "equity": final_equity, "drawdown": drawdown},
            ]
        )
    )

    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "paper_only": True,
        "profitability_claim": False,
        "live_trading_authority": False,
        "canonical_data": {
            "source": dataset["source"],
            "source_role": dataset["source_role"],
            "instrument": dataset["instrument"],
            "timeframe": dataset["manifest_timeframe"],
            "finality": dataset["finality"],
            "row_count": dataset["row_count"],
            "binding_sha256": dataset["binding_sha256"],
        },
        "data_intelligence_regime": {
            "regime_pass_ratio": pipeline["evidence"]["regime_pass_ratio"],
            "oos_score": pipeline["evidence"]["oos_score"],
            "walk_forward_score": pipeline["evidence"]["walk_forward_score"],
            "robustness_score": pipeline["evidence"]["robustness_score"],
            "benchmark_score": pipeline["evidence"]["benchmark_score"],
        },
        "strategy": {
            "family": qualification["family"],
            "strategy_version": strategy_version,
            "experiment_id": strategy_id,
            "qualification_status": qualification["status"],
            "qualification_digest": qualification["qualification_digest"],
            "pipeline_digest": pipeline["pipeline_digest"],
            "handoff_digest": handoff["handoff_digest"],
        },
        "decision": {
            "decision_id": decision_id,
            "signal_id": signal_id,
            "side": signal["side"],
            "quantity": signal["quantity"],
            "reference_price": signal["reference_price"],
            "causation_id": signal["causation_id"],
        },
        "risk": {
            "allowed": risk.allowed,
            "reason_code": risk.reason_code,
            "policy_id": risk.policy_id,
            "policy_version": risk.policy_version,
            "proposed_notional": str(risk.proposed_notional),
            "resulting_exposure": str(risk.resulting_exposure),
        },
        "paper": {
            "event_count": len(execution.events),
            "event_digests": [event["event_digest"] for event in execution.events],
            "fill_price": str(execution.fill_price),
            "fee": str(execution.fee),
            "slippage_cost": str(execution.slippage_cost),
            "ending_equity": str(execution.state.equity),
            "open_positions": len(execution.state.positions),
        },
        "performance_drift": {
            "metrics": performance,
            "equity_drift_fraction": drawdown,
            "drift_status": "OBSERVED_BOUNDED_PAPER_COST" if drawdown < 0 else "NO_NEGATIVE_DRIFT",
        },
    }
    return {**core, "proof_digest": _digest(core)}


def validate_proof(proof: Mapping[str, Any], *, expected_source_sha: str) -> None:
    if not isinstance(proof, Mapping) or proof.get("schema_version") != SCHEMA:
        raise Phase7ProofError("Phase 7 proof schema mismatch")
    if proof.get("source_sha") != _source_sha(expected_source_sha):
        raise Phase7ProofError("Phase 7 proof source SHA mismatch")
    if proof.get("paper_only") is not True or proof.get("live_trading_authority") is not False:
        raise Phase7ProofError("Phase 7 proof widened authority")
    if proof.get("strategy", {}).get("qualification_status") != "paper_candidate":
        raise Phase7ProofError("Phase 7 proof lacks Paper Candidate")
    if proof.get("risk", {}).get("allowed") is not True:
        raise Phase7ProofError("Phase 7 proof lacks deterministic Risk approval")
    if int(proof.get("paper", {}).get("event_count", 0)) < 1:
        raise Phase7ProofError("Phase 7 proof lacks Paper execution evidence")
    core = dict(proof)
    claimed = core.pop("proof_digest", None)
    if not isinstance(claimed, str) or len(claimed) != 64 or _digest(core) != claimed:
        raise Phase7ProofError("Phase 7 proof digest mismatch")
