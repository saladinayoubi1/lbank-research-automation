from __future__ import annotations

from copy import deepcopy

import pytest

from nexus_research_missions import attested_predecessor, attested_research_task
from nexus_composite_validation_candidate import (
    CompositeValidationCandidateError,
    build_candidate,
    digest,
    verify_candidate,
)

SOURCE = "a" * 40
RECEIPT = "b" * 64
LEDGER = "c" * 64
PRIOR = "d" * 64
CONFIG = "e" * 64
QA = "f" * 64
REPORT = "1" * 64
MECHANISM = "factory_gen_deep_drawdown_recovery_vwap_reclaim"
ARCHIVE = "2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422"
LEASE = "producer-lease"


def _config():
    return {
        "mechanism": MECHANISM,
        "risk_variant": 0,
        "entry_model": "closed_4h_1h_15m_next_open",
        "factory_contract_digest": "2" * 64,
    }


def _fingerprint():
    return digest({
        "config": _config(),
        "dataset": ARCHIVE,
        "contract": "nexus.automatic-composite-research.v1",
    })


def _receipt():
    core = {
        "schema": "nexus.agent-composite-execution.v1",
        "lease_id": LEASE,
        "source_sha": SOURCE,
        "archive_sha256": ARCHIVE,
        "prior_ledger_digest": PRIOR,
        "ledger_digest": LEDGER,
        "report_digest": REPORT,
        "report_file_sha256": "3" * 64,
        "ledger_file_sha256": "4" * 64,
        "prior_ledger_file_sha256": "5" * 64,
        "mechanism": MECHANISM,
        "config_fingerprint": _fingerprint(),
        "validation": [],
        "research_only": True,
        "auto_demo_promotion": False,
        "live_enabled": False,
        "independent_qa_complete": False,
    }
    return {**core, "receipt_digest": digest(core)}


def _manager():
    receipt = _receipt()
    production = {
        "executor": "nexus-real-composite-backtest",
        "workload_id": "P7-RESEARCH-COMPOSITE-015",
        "source_sha": SOURCE,
        "receipt_digest": receipt["receipt_digest"],
        "ledger_digest": LEDGER,
        "prior_ledger_digest": PRIOR,
        "config_fingerprint": _fingerprint(),
        "mechanism": MECHANISM,
        "independent_qa_complete": False,
        "qualification_authority": False,
        "auto_demo_promotion": False,
        "live_enabled": False,
    }
    qa = {
        "executor": "nexus-independent-composite-numeric-qa",
        "producer_receipt_digest": receipt["receipt_digest"],
        "producer_lease_id": LEASE,
        "source_sha": SOURCE,
        "qa_digest": QA,
        "independent_qa_complete": True,
        "qualification_authority": False,
        "auto_demo_promotion": False,
        "live_enabled": False,
    }
    return {
        "id": "P7-RESEARCH-COMPOSITE-015",
        "status": "DONE",
        "producer": "research-agent",
        "verifier": "qa-verifier-agent",
        "research_producer_lease_id": LEASE,
        "result_evidence": production,
        "verification_evidence": qa,
    }


def _row(symbol, profile, trades, value):
    return {
        "symbol": symbol,
        "timeframe": "minute15_with_completed_1h_4h",
        "mechanism": MECHANISM,
        "risk_variant": 0,
        "config_fingerprint": _fingerprint(),
        "part": "validation",
        "profile": profile,
        "bars": 25000,
        "first_closed_utc": "2025-02-01 00:00:00+00:00",
        "last_closed_utc": "2025-11-01 00:00:00+00:00",
        "net_return_pct": value,
        "net_pnl_usdt": value * 100,
        "max_drawdown_pct": 0.4,
        "closed_round_trips": trades,
        "win_rate_pct": 50.0 if trades else None,
        "profit_factor": 1.2 if trades else None,
        "profit_factor_status": "AVAILABLE" if trades else "NOT_AVAILABLE_NO_REALIZED_LOSSES",
        "turnover_usdt": 1000.0 if trades else 0.0,
        "exposure_bar_ratio": 0.01 if trades else 0.0,
        "halted_on_drawdown": False,
        "fee_bps": 25.0 if profile == "stress" else 10.0,
        "slippage_bps": 15.0 if profile == "stress" else 5.0,
        "trade_count_limit": None,
        "concurrent_risk_model": "one_collateral_backed_net_long_per_symbol;10pct_position_budget",
    }


def _report(values=(0.20, 0.12, 0.24, 0.03), trades=(1, 1, 2, 2)):
    validation = [
        _row("BTCUSDT", "conservative", trades[0], values[0]),
        _row("BTCUSDT", "stress", trades[1], values[1]),
        _row("ETHUSDT", "conservative", trades[2], values[2]),
        _row("ETHUSDT", "stress", trades[3], values[3]),
    ]
    selected = {**_config(), "fingerprint": _fingerprint()}
    screening = {
        "schema": "nexus.frontier-train-screen.v6",
        "basis": "training_partition_only_no_validation_or_historical_test_ranking",
        "candidate_count": 12,
        "shortlist_size": 3,
        "shortlist": [MECHANISM],
        "selected_mechanism": MECHANISM,
        "screened_mechanisms": [MECHANISM],
        "no_minimum_trade_count_gate": True,
        "validation_used_for_selection": False,
        "historically_inspected_test_used_for_selection": False,
        "ranking": [],
    }
    core = {
        "schema": "nexus.automatic-composite-research.v1",
        "source_sha": SOURCE,
        "archive_sha256": ARCHIVE,
        "status": "EVALUATED_RESEARCH_ONLY",
        "selection_basis": "frontier_training_only_tournament_then_full_replay",
        "selected": selected,
        "distinct_mechanisms_tested_cumulative": 1,
        "parameter_configs_tested_cumulative": 1,
        "historical_test_pristine": False,
        "independent_future_data_required": True,
        "risk_assumptions": {
            "initial_cash_usdt_per_isolated_run": 10000.0,
            "max_position_fraction": 0.10,
            "max_daily_loss_fraction": 0.05,
            "max_drawdown_fraction": 0.10,
            "maximum_trades_per_strategy": None,
        },
        "research_only": True,
        "auto_demo_promotion": False,
        "live_enabled": False,
        "qualification": "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT",
        "rows": validation,
        "ledger_digest": LEDGER,
        "frontier_screening": screening,
    }
    # receipt/report must bind exact report digest
    return {**core, "report_digest": digest(core)}


def _bound_inputs(report):
    receipt = _receipt()
    receipt_core = dict(receipt)
    receipt_core.pop("receipt_digest")
    receipt_core["report_digest"] = report["report_digest"]
    receipt = {**receipt_core, "receipt_digest": digest(receipt_core)}
    manager = _manager()
    manager["result_evidence"]["receipt_digest"] = receipt["receipt_digest"]
    manager["verification_evidence"]["producer_receipt_digest"] = receipt["receipt_digest"]
    return manager, receipt


def test_positive_exercised_validation_forwards_without_minimum_trade_count_gate():
    report = _report(trades=(1, 1, 1, 1))
    manager, receipt = _bound_inputs(report)
    candidate = build_candidate(manager, receipt, report)
    assert candidate["decision"] == "FORWARD_TO_VAL40"
    assert candidate["eligible_for_fresh_runtime_requalification"] is True
    assert candidate["total_validation_round_trips"] == 4
    assert candidate["no_minimum_trade_count_gate"] is True
    assert candidate["strategy_config"] == _config()
    assert candidate["research_task"]["verification_evidence"]["qa_digest"] == QA
    assert candidate["producer_receipt"]["receipt_digest"] == receipt["receipt_digest"]
    assert candidate["research_report"]["report_digest"] == report["report_digest"]
    assert verify_candidate(candidate)["decision"] == "pass"


def test_zero_activity_is_rejected_without_creating_a_minimum_trade_gate():
    report = _report(values=(0.0, 0.0, 0.0, 0.0), trades=(0, 0, 0, 0))
    manager, receipt = _bound_inputs(report)
    candidate = build_candidate(manager, receipt, report)
    assert candidate["decision"] == "REJECTED_RESEARCH_VALIDATION"
    assert candidate["reason_codes"] == ["ZERO_ACTIVITY"]
    assert candidate["eligible_for_fresh_runtime_requalification"] is False
    assert candidate["no_minimum_trade_count_gate"] is True


def test_any_non_positive_validation_cell_is_rejected():
    report = _report(values=(0.20, -0.01, 0.24, 0.03))
    manager, receipt = _bound_inputs(report)
    candidate = build_candidate(manager, receipt, report)
    assert candidate["decision"] == "REJECTED_RESEARCH_VALIDATION"
    assert candidate["reason_codes"] == ["NON_POSITIVE_VALIDATION_CELL"]


def test_config_fingerprint_or_training_only_selection_tamper_fails_closed():
    report = _report()
    manager, receipt = _bound_inputs(report)
    tampered = deepcopy(report)
    tampered["selected"]["risk_variant"] = 1
    core = dict(tampered)
    core.pop("report_digest")
    tampered["report_digest"] = digest(core)
    receipt_core = dict(receipt)
    receipt_core.pop("receipt_digest")
    receipt_core["report_digest"] = tampered["report_digest"]
    bad_receipt = {**receipt_core, "receipt_digest": digest(receipt_core)}
    manager["result_evidence"]["receipt_digest"] = bad_receipt["receipt_digest"]
    manager["verification_evidence"]["producer_receipt_digest"] = bad_receipt["receipt_digest"]
    with pytest.raises(CompositeValidationCandidateError, match="fingerprint"):
        build_candidate(manager, bad_receipt, tampered)

    report = _report()
    manager, receipt = _bound_inputs(report)
    bad_selection = deepcopy(report)
    bad_selection["frontier_screening"]["validation_used_for_selection"] = True
    core = dict(bad_selection)
    core.pop("report_digest")
    bad_selection["report_digest"] = digest(core)
    receipt_core = dict(receipt)
    receipt_core.pop("receipt_digest")
    receipt_core["report_digest"] = bad_selection["report_digest"]
    receipt = {**receipt_core, "receipt_digest": digest(receipt_core)}
    manager["result_evidence"]["receipt_digest"] = receipt["receipt_digest"]
    manager["verification_evidence"]["producer_receipt_digest"] = receipt["receipt_digest"]
    with pytest.raises(CompositeValidationCandidateError, match="selection/provenance"):
        build_candidate(manager, receipt, bad_selection)


def test_candidate_tamper_is_detected():
    report = _report()
    manager, receipt = _bound_inputs(report)
    candidate = build_candidate(manager, receipt, report)
    tampered = deepcopy(candidate)
    tampered["promotion_authority"] = True
    assert verify_candidate(tampered)["decision"] == "reject"

    redigested = deepcopy(candidate)
    redigested["mechanism"] = "factory_gen_fake_mechanism"
    redigested["strategy_config"]["mechanism"] = "factory_gen_fake_mechanism"
    core = dict(redigested)
    core.pop("candidate_digest", None)
    redigested["candidate_digest"] = digest(core)
    assert verify_candidate(redigested)["decision"] == "reject"

    proof_tamper = deepcopy(candidate)
    proof_tamper["research_task"]["verification_evidence"]["qa_digest"] = "0" * 64
    core = dict(proof_tamper)
    core.pop("candidate_digest", None)
    proof_tamper["candidate_digest"] = digest(core)
    assert verify_candidate(proof_tamper)["decision"] == "reject"


def test_terminal_composite_research_task_is_attested_for_val40_but_not_as_successor_predecessor():
    report = _report(trades=(1, 1, 1, 1))
    manager, receipt = _bound_inputs(report)
    manager["id"] = "P7-RESEARCH-COMPOSITE-019"
    manager["result_evidence"]["workload_id"] = manager["id"]

    attested = attested_research_task(manager)
    assert attested["research_predecessor_source_sha"] == SOURCE
    assert attested["research_predecessor_receipt_digest"] == receipt["receipt_digest"]
    assert attested["research_predecessor_qa_digest"] == QA
    assert attested["research_predecessor_ledger_digest"] == LEDGER
    assert attested["research_predecessor_mechanism"] == MECHANISM

    candidate = build_candidate(manager, receipt, report)
    assert candidate["research_task_id"] == "P7-RESEARCH-COMPOSITE-019"
    assert verify_candidate(candidate)["decision"] == "pass"

    # Terminal task 019 must not become a predecessor in the Research DAG merely
    # because its own proof is valid.
    with pytest.raises(ValueError, match="previous real Research"):
        attested_predecessor(manager)


def test_generic_research_attestation_still_rejects_wrong_worker_or_receipt():
    manager = _manager()
    manager["producer"] = "qa-verifier-agent"
    with pytest.raises(ValueError, match="Research\+independent-QA"):
        attested_research_task(manager)

    manager = _manager()
    manager["verification_evidence"]["producer_receipt_digest"] = "0" * 64
    with pytest.raises(ValueError, match="Research\+independent-QA"):
        attested_research_task(manager)
