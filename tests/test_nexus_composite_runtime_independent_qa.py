from __future__ import annotations

from copy import deepcopy

import pytest

import nexus_composite_runtime_independent_qa as qa
import nexus_composite_runtime_requalification as rq


SOURCE = "a" * 40
RUN_ID = 123456


def _candidate():
    return {
        "schema_version": "nexus.composite-validation-candidate.v2",
        "system_map_node": "VAL-40",
        "decision": "FORWARD_TO_VAL40",
        "eligible_for_fresh_runtime_requalification": True,
        "requires_fresh_runtime_data": True,
        "candidate_digest": "b" * 64,
        "source_sha": "c" * 40,
        "archive_sha256": "d" * 64,
        "mechanism": "factory_gen_deep_drawdown_recovery_vwap_reclaim",
        "timeframe": "minute15_with_completed_1h_4h",
        "strategy_config": {
            "mechanism": "factory_gen_deep_drawdown_recovery_vwap_reclaim",
            "risk_variant": 0,
            "entry_model": "closed_4h_1h_15m_next_open",
            "factory_contract_digest": "e" * 64,
        },
        "config_fingerprint": "f" * 64,
        "no_minimum_trade_count_gate": True,
        "research_only": True,
        "paper_only": True,
        "candidate_state_created": False,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }


def _verification():
    return {
        "schema_version": "nexus.composite-validation-candidate-verification.v2",
        "decision": "pass",
        "checks": {"proof": True},
        "candidate_digest": "b" * 64,
        "verification_digest": "1" * 64,
    }


def _dataset(tf, suffix, asof):
    step = rq.TIMEFRAME_STEP_MS[tf]
    last_open = ((asof - step) // step) * step
    return {
        "timeframe": tf,
        "binding_sha256": suffix * 64,
        # Synthetic 30-day+ canonical aggregation for QA; live public fetch
        # remains capped at 1000 and is NOT yet sufficient for QA admission.
        "row_count": 3000 if tf == "minute15" else 1000,
        "first_open_time_ms": last_open - (
            (3000 if tf == "minute15" else 1000) - 1
        ) * step,
        "last_open_time_ms": last_open,
    }


def _profile(name):
    return {
        "profile": name,
        "net_return_pct": 0.2,
        "net_pnl_usdt": 20.0,
        "max_drawdown_pct": 0.4,
        "closed_round_trips": 2,
        "win_rate_pct": 50.0,
        "profit_factor": 1.2,
        "profit_factor_status": "AVAILABLE",
        "turnover_usdt": 1000.0,
        "exposure_bar_ratio": 0.02,
        "halted_on_drawdown": False,
        "fee_bps": 10.0 if name == "conservative" else 25.0,
        "slippage_bps": 5.0 if name == "conservative" else 15.0,
        "trade_count_limit": None,
        "concurrent_risk_model":
            "one_collateral_backed_net_long_per_symbol;10pct_position_budget",
    }


def _rows(asof):
    suffix = {
        "BTCUSDT": {"minute15": "2", "hour1": "3", "hour4": "4"},
        "ETHUSDT": {"minute15": "5", "hour1": "6", "hour4": "7"},
    }
    rows=[]
    for symbol in rq.SYMBOLS:
        rows.append({
            "symbol": symbol,
            "mechanism": _candidate()["mechanism"],
            "strategy_config": _candidate()["strategy_config"],
            "datasets": {tf:_dataset(tf,suffix[symbol][tf],asof) for tf in rq.TIMEFRAMES},
            "peer_symbol": None,
            "peer_minute15_binding_sha256": None,
            "profiles": [_profile("conservative"),_profile("stress")],
            "deterministic_replay_verified": True,
            "data_origin": "canonical_public_bybit_runtime",
            "closed_candle_finality_verified": True,
            "paper_only": True,
            "candidate_state_created": False,
            "qualification_authority": False,
            "registry_mutation_authority": False,
            "paper_execution_authority": False,
            "automatic_strategy_promotion": False,
            "live_trading_authority": False,
        })
    return rows


def _producer(monkeypatch):
    asof=1_900_000_000_000
    monkeypatch.setattr(rq,"verify_candidate",lambda value:_verification())
    return rq.build_requalification(
        _candidate(),_verification(),source_sha=SOURCE,now_ms=asof,state_root=".",
        evaluator=lambda *args: deepcopy(_rows(asof)),
    )


def test_qualified_physical_producer_builds_verifier_only_task(monkeypatch):
    producer=_producer(monkeypatch)
    task=qa.build_task(producer,rq.verify_requalification(producer),producer_workflow_run_id=RUN_ID)
    assert task["id"]=="COMPOSITE-QA-"+producer["requalification_digest"]
    assert task["required_verifier"]=="qa-verifier-agent"
    assert task["system_map_node"]=="QA-41"
    assert task["qualification_authority"] is False
    assert task["paper_execution_authority"] is False
    assert task["live_trading_authority"] is False
    assert qa.validate_task(task,SOURCE)==task


def test_rejected_physical_producer_never_enters_qa(monkeypatch):
    producer=_producer(monkeypatch)
    producer["decision"]="REJECTED"
    producer["qualified_for_review"]=False
    core=dict(producer); core.pop("requalification_digest",None)
    producer["requalification_digest"]=rq.digest(core)
    with pytest.raises(qa.CompositeRuntimeQaError,match="not eligible"):
        qa.build_task(producer,rq.verify_requalification(producer),producer_workflow_run_id=RUN_ID)


def test_independent_replay_receipt_binds_exact_window_and_lease(monkeypatch,tmp_path):
    producer=_producer(monkeypatch)
    verification=rq.verify_requalification(producer)
    task=qa.build_task(producer,verification,producer_workflow_run_id=RUN_ID)
    receipt=qa.run_independent_qa(
        task,lease_id="qa-lease",execution_source_sha=SOURCE,state_root=tmp_path,
        replay=lambda candidate,candidate_verification,source_sha,now_ms,state_root: deepcopy(producer),
    )
    assert receipt["producer_requalification_digest"]==producer["requalification_digest"]
    assert receipt["runtime_as_of_ms"]==producer["runtime_as_of_ms"]
    assert receipt["independent_qa_complete"] is True
    assert receipt["qualification_authority"] is False
    assert receipt["paper_execution_authority"] is False
    assert qa.verify_receipt(receipt,task,lease_id="qa-lease",execution_source_sha=SOURCE)


def test_source_or_replay_tamper_fails_closed(monkeypatch,tmp_path):
    producer=_producer(monkeypatch)
    task=qa.build_task(producer,rq.verify_requalification(producer),producer_workflow_run_id=RUN_ID)
    with pytest.raises(qa.CompositeRuntimeQaError,match="identity or authority"):
        qa.run_independent_qa(
            task,lease_id="qa-lease",execution_source_sha="9"*40,state_root=tmp_path,
            replay=lambda *args: deepcopy(producer),
        )

    bad=deepcopy(producer)
    bad["evaluations"][0]["profiles"][0]["net_return_pct"] += 0.1
    core=dict(bad); core.pop("requalification_digest",None)
    bad["evaluations_digest"]=rq.digest(bad["evaluations"])
    core=dict(bad); core.pop("requalification_digest",None)
    bad["requalification_digest"]=rq.digest(core)
    with pytest.raises(qa.CompositeRuntimeQaError,match="differs"):
        qa.run_independent_qa(
            task,lease_id="qa-lease",execution_source_sha=SOURCE,state_root=tmp_path,
            replay=lambda *args: bad,
        )


def test_task_redigest_does_not_widen_authority(monkeypatch):
    producer=_producer(monkeypatch)
    task=qa.build_task(producer,rq.verify_requalification(producer),producer_workflow_run_id=RUN_ID)
    tampered=deepcopy(task)
    tampered["paper_execution_authority"]=True
    core=dict(tampered); core.pop("task_digest",None)
    tampered["task_digest"]=qa.digest(core)
    with pytest.raises(qa.CompositeRuntimeQaError,match="identity or authority"):
        qa.validate_task(tampered,SOURCE)


def _redigest_producer(producer):
    producer["evaluations_digest"] = rq.digest(producer["evaluations"])
    core = dict(producer)
    core.pop("requalification_digest", None)
    producer["requalification_digest"] = rq.digest(core)
    return producer


def test_ten_day_profitable_replay_cannot_issue_new_qa_task(monkeypatch):
    producer = _producer(monkeypatch)
    for row in producer["evaluations"]:
        info = row["datasets"]["minute15"]
        info["row_count"] = 1000
        info["first_open_time_ms"] = info["last_open_time_ms"] - 999 * 900_000
    _redigest_producer(producer)
    assert producer["decision"] == "QUALIFIED_FOR_REVIEW"
    assert rq.verify_requalification(producer)["decision"] == "pass"
    with pytest.raises(qa.CompositeRuntimeQaError, match="INSUFFICIENT_OBSERVATION_COVERAGE"):
        qa.build_task(
            producer, rq.verify_requalification(producer),
            producer_workflow_run_id=RUN_ID,
        )


def test_physically_redigested_accounting_fraud_is_independently_rejected(monkeypatch):
    producer = _producer(monkeypatch)
    # Existing VAL-40 structure verifies types and source/hash but does not
    # independently reconcile isolated capital versus percentages.
    producer["evaluations"][0]["profiles"][0]["net_pnl_usdt"] = 900.0
    _redigest_producer(producer)
    assert rq.verify_requalification(producer)["decision"] == "pass"
    with pytest.raises(qa.CompositeRuntimeQaError, match="chronology/accounting"):
        qa.build_task(
            producer, rq.verify_requalification(producer),
            producer_workflow_run_id=RUN_ID,
        )
