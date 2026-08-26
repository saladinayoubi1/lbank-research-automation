from __future__ import annotations

import nexus_paper_performance_pipeline as pipeline
from nexus_paper_performance_pipeline import (
    _journal_paper_acceptance,
    build_paper_performance_projection,
)
from paper_event_store import GENESIS_DIGEST, build_event


AT = "2026-08-25T04:00:00Z"


def _journal():
    events = []
    previous = GENESIS_DIGEST

    def append(kind, payload, correlation="paper-open"):
        nonlocal previous
        event = build_event(
            event_id=f"event-{len(events) + 1}",
            event_type=kind,
            aggregate_id="paper-momentum",
            sequence=len(events) + 1,
            occurred_at=AT,
            correlation_id=correlation,
            causation_id=f"cause-{len(events) + 1}",
            provenance={
                "kind": "automatic" if kind not in {"demo_account_opened", "session_boundary_recorded"} else "manual",
                "source_id": "Bybit" if kind not in {"demo_account_opened", "session_boundary_recorded"} else "bootstrap",
                "source_timestamp": AT,
                "received_timestamp": AT,
                "timeframe": "minute15" if kind not in {"demo_account_opened", "session_boundary_recorded"} else "session",
                "confidence": "1",
                "strategy_version": "momentum-v1" if kind not in {"demo_account_opened", "session_boundary_recorded"} else "bootstrap-v1",
                "policy_version": "paper-v1",
            },
            previous_event_digest=previous,
            payload=payload,
        )
        previous = event["event_digest"]
        events.append(event)

    append("demo_account_opened", {"currency": "USDT", "opening_cash": "10000"}, "bootstrap")
    append("session_boundary_recorded", {"boundary": "open"}, "bootstrap")
    append("signal_recorded", {
        "symbol": "BTCUSDT", "timeframe": "minute15", "side": "long",
        "quantity": "1", "reference_price": "100",
    })
    append("risk_decision_recorded", {"decision": "allow", "reason_code": "risk_allowed"})
    append("position_opened", {
        "symbol": "BTCUSDT", "side": "long", "quantity": "1", "entry_price": "100",
    })
    return events


def _task(status="no_open_signal"):
    return {
        "task_id": "task-1",
        "family": "momentum",
        "status": status,
        "worker_id": "strategy-worker-momentum",
        "research_result": {
            "strategy_record": {
                "lifecycle_state": "CANDIDATE",
                "strategy_version": "momentum-v1",
                "record_digest": "a" * 64,
            },
            "qualification": {
                "status": "paper_candidate",
                "qualification_digest": "b" * 64,
            },
        },
    }


def test_reconstructs_paper_acceptance_from_automatic_open_and_verifier() -> None:
    acceptance = _journal_paper_acceptance(
        events=_journal(),
        task=_task(),
        supervisor_verification={
            "verification_digest": "c" * 64,
            "verifier": "strategy-paper-independent-verifier",
        },
    )
    assert acceptance is not None
    assert acceptance["risk_gate_allowed"] is True
    assert acceptance["replay_verified"] is True
    assert len(acceptance["paper_execution_evidence_sha256"]) == 64
    assert acceptance["independent_verifier_evidence_sha256"] == "c" * 64


def test_flat_no_open_signal_keeps_verified_paper_history_in_projection(monkeypatch) -> None:
    ledger = {"tasks": [_task("no_open_signal")]}
    monkeypatch.setattr(pipeline, "verify_ledger", lambda _ledger: {
        "decision": "pass",
        "verification_digest": "c" * 64,
        "verifier": "strategy-paper-independent-verifier",
    })
    observed = {}

    def fake_evaluate(**kwargs):
        observed.update(kwargs)
        return {
            "strategy_id": "strategy-current-record",
            "status": "INSUFFICIENT_EVIDENCE",
            "lifecycle_state": "PAPER",
            "closed_trade_count": 0,
            "analytics": {},
            "monitor_digest": "d" * 64,
        }

    monkeypatch.setattr(pipeline, "evaluate_paper_drift", fake_evaluate)
    projection = build_paper_performance_projection(
        supervisor_ledger=ledger,
        journals_by_family={"momentum": _journal()},
        baselines_by_family={"momentum": {"expectancy": "0", "fee_per_trade": "0"}},
    )

    assert projection["strategy_count"] == 1
    assert projection["strategies"][0]["lifecycle_state"] == "PAPER"
    assert projection["strategies"][0]["status"] == "INSUFFICIENT_EVIDENCE"
    assert observed["paper_acceptance"] is not None
