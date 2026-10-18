"""Full native contracts with synthetic economics; never a market-profit result.

Reuse the upstream producer fixtures, with no validator or receipt verifier mocked.
Both the Research proof and fresh runtime proof pass their actual validators.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

import nexus_composite_runtime_independent_qa as qa
import nexus_composite_runtime_requalification as rq
from nexus_composite_validation_candidate import build_candidate, verify_candidate
from nexus_strategy_qualification_gate import (
    StrategyQualificationError, evaluate_qualification, verify_qualification,
)
from scripts.nexus_strategy_admission_reviews import build_reviews, persist_reviews
from strategy_registry import (
    StrategyRegistryError, build_qualified_strategy_record, verify_qualified_strategy_record,
    evaluate_strategy_health, build_runtime_candidate_view,
)
from test_nexus_composite_validation_candidate import _report, _bound_inputs
from test_nexus_composite_runtime_independent_qa import _rows

SOURCE = "a" * 40
ASOF = 1_900_000_000_000


def manager(status="DONE", *, now_ms=ASOF):
    report = _report(trades=(1, 1, 1, 1))
    research_task, receipt = _bound_inputs(report)
    candidate = build_candidate(research_task, receipt, report)
    assert verify_candidate(candidate)["decision"] == "pass"

    def evaluate(cand, source, asof, root):
        rows = _rows(asof)
        for row in rows:
            row["strategy_config"] = deepcopy(cand["strategy_config"])
            for timeframe, dataset in row["datasets"].items():
                count = 3072 if timeframe == "minute15" else 1000
                dataset["row_count"] = count
                dataset["first_open_time_ms"] = (
                    dataset["last_open_time_ms"] - (count - 1) * rq.TIMEFRAME_STEP_MS[timeframe]
                )
            for profile in row["profiles"]:
                profile["closed_round_trips"] = 1  # No arbitrary minimum count.
        return rows

    def replay(cand, verification, source, asof, root):
        return rq.build_requalification(cand, verification, source_sha=source,
                                       now_ms=asof, state_root=root, evaluator=evaluate)

    producer = replay(candidate, verify_candidate(candidate), SOURCE, now_ms, Path("."))
    task = qa.build_task(producer, rq.verify_requalification(producer),
                         producer_workflow_run_id=123456)
    proof = qa.run_independent_qa(task, lease_id="independent-qa-lease",
                                execution_source_sha=SOURCE, state_root=".", replay=replay)
    return {
        "id": task["id"], "status": status, "authority": 2,
        "qa_verifier_only": True, "qa_dispatch_enabled": True,
        "required_verifier": "qa-verifier-agent", "qa_handoff_task": task,
        "verifier": "qa-verifier-agent", "assigned_worker": "qa-verifier-agent",
        "lease_id": "independent-qa-lease", "verification_evidence": proof,
    }


def test_native_research_to_qa_to_qualification_to_registry_retains_complete_proof():
    task = manager()
    qualification = evaluate_qualification(task)
    verification = verify_qualification(qualification)
    assert verification["decision"] == "pass"
    assert qualification["decision"] == "QUALIFIED_FOR_REGISTRY"
    assert qualification["qa_handoff_task"] == task["qa_handoff_task"]
    assert qualification["qa_receipt"] == task["verification_evidence"]
    record = build_qualified_strategy_record(qualification, verification)
    assert verify_qualified_strategy_record(record)["decision"] == "pass"
    assert record["config"] == task["qa_handoff_task"]["producer"]["strategy_config"]
    assert {"mechanism", "risk_variant", "entry_model", "factory_contract_digest"} == set(record["config"])
    assert record["candidate_source_sha"] == task["qa_handoff_task"]["producer"]["candidate_source_sha"]
    assert record["runtime_evidence"] == task["qa_handoff_task"]["producer"]["evaluations"]
    assert all(set(row["datasets"]) == {"minute15", "hour1", "hour4"}
               for row in record["runtime_evidence"])
    for flag in ("economic_edge_established", "pristine_prospective_evidence_present",
                 "owner_shared_500_portfolio_verified", "owner_demo_admission_allowed",
                 "demo_matrix_member", "runtime_activation_authority", "paper_execution_authority",
                 "automatic_strategy_promotion", "live_execution_allowed"):
        assert record[flag] is False
    assert record["observation_adequacy"]["historical_minimum_trade_count"] is None
    assert "proposal_digest" not in qualification
    health = evaluate_strategy_health(record, {
        "data_eligible": True, "performance_drop_pct": 0.,
        "execution_cost_increase_pct": 0., "regime_mismatch": False,
        "correlation_shift_pct": 0.,
    })
    view = build_runtime_candidate_view(record, health)
    assert view["lifecycle_state"] == "CANDIDATE"
    assert view["live_trading_authority"] is False


@pytest.mark.parametrize("status", ["PENDING", "READY", "LEASED", "RUNNING", "VERIFYING",
                                    "BLOCKED", "QUARANTINED"])
def test_incomplete_or_failed_qa_cannot_register_even_when_old_receipt_is_present(status):
    value = evaluate_qualification(manager(status))
    assert value["qualified"] is False and value["qa_receipt"] is None
    verification = verify_qualification(value)
    assert verification["decision"] == "pass"
    with pytest.raises(StrategyRegistryError, match="does not authorize"):
        build_qualified_strategy_record(value, verification)


@pytest.mark.parametrize("mutation", ["no_receipt", "wrong_lease", "wrong_source",
                                      "producer_role", "wrong_id", "wrong_verifier"])
def test_missing_or_mismatched_qa_state_fails_before_admission(mutation):
    task = manager()
    if mutation == "no_receipt":
        task.pop("verification_evidence")
    elif mutation == "wrong_lease":
        task["lease_id"] = "another-lease"
    elif mutation == "wrong_source":
        task["qa_handoff_task"]["source_sha"] = "9" * 40
    elif mutation == "producer_role":
        task["producer"] = "research-agent"
    elif mutation == "wrong_id":
        task["id"] += "bad"
    else:
        task["verifier"] = "research-agent"
    with pytest.raises(StrategyQualificationError):
        evaluate_qualification(task)


@pytest.mark.parametrize("field,value", [
    ("candidate_source_sha", "9" * 40), ("config_fingerprint", "9" * 64),
    ("runtime_evidence_digest", "9" * 64), ("qa_lease_id", "another-lease"),
    ("economic_edge_established", True), ("owner_demo_admission_allowed", True),
    ("paper_execution_authority", True),
])
def test_rehashing_a_changed_qualification_does_not_hide_broken_provenance(field, value):
    result = evaluate_qualification(manager())
    result[field] = value
    core = dict(result); core.pop("qualification_digest")
    result["qualification_digest"] = qa.digest(core)
    assert verify_qualification(result)["decision"] == "reject"
    with pytest.raises(StrategyRegistryError):
        build_qualified_strategy_record(result, verify_qualification(result))


def test_native_composite_is_not_relabelled_as_simple_family():
    task = manager()
    task["qa_handoff_task"]["schema_version"] = "nexus.strategy-review-qa-task.v1"
    with pytest.raises(StrategyQualificationError):
        evaluate_qualification(task)


def test_registry_tamper_cannot_change_native_dataset_or_execution_authority():
    result = evaluate_qualification(manager())
    record = build_qualified_strategy_record(result, verify_qualification(result))
    for field in ("dataset", "paper_execution_authority", "owner_shared_500_portfolio_verified"):
        changed = deepcopy(record)
        if field == "dataset":
            changed["runtime_evidence"][0]["datasets"]["hour4"]["binding_sha256"] = "9" * 64
        else:
            changed[field] = True
        core = dict(changed); core.pop("record_digest")
        changed["record_digest"] = qa.digest(core)
        assert verify_qualified_strategy_record(changed)["decision"] == "reject"


def test_existing_self_consistent_short_observation_is_not_grandfathered():
    task = manager()
    native = task["qa_handoff_task"]
    producer = native["producer"]
    for row in producer["evaluations"]:
        dataset = row["datasets"]["minute15"]
        dataset["row_count"] = 1000
        dataset["first_open_time_ms"] = dataset["last_open_time_ms"] - 999 * 900_000
    producer["evaluations_digest"] = rq.digest(producer["evaluations"])
    producer["fresh_history_limit_per_timeframe"] = 1000
    core = dict(producer); core.pop("requalification_digest")
    producer["requalification_digest"] = rq.digest(core)
    assert rq.verify_requalification(producer)["decision"] == "pass"
    native["producer_verification"] = rq.verify_requalification(producer)
    for key in ("requalification_digest", "evaluations_digest"):
        native[key] = producer[key]
    native["requalification_verification_digest"] = native["producer_verification"]["verification_digest"]
    native["id"] = qa.task_id(producer["requalification_digest"])
    core = dict(native); core.pop("task_digest")
    native["task_digest"] = qa.digest(core)
    task["id"] = native["id"]
    task["verification_evidence"] = qa.run_independent_qa(
        native, lease_id=task["lease_id"], execution_source_sha=SOURCE,
        state_root=".", replay=lambda *args: deepcopy(producer),
    )
    with pytest.raises(StrategyQualificationError, match="coverage"):
        evaluate_qualification(task)


def test_coordinator_review_store_is_idempotent_and_distinguishes_waiting(tmp_path):
    runtime = {"schema_version": 1, "tasks": [manager(), manager("READY", now_ms=ASOF + 3_600_000)]}
    first = persist_reviews(runtime, tmp_path / "reviews")
    second = persist_reviews(runtime, tmp_path / "reviews")
    assert first["new_evidence_files"] == 2 and second["new_evidence_files"] == 0
    assert first["registry_candidate_records"] == 1
    assert {row["decision"] for row in first["tasks"]} == {"QUALIFIED_FOR_REGISTRY", "WAITING_FOR_QA"}
    assert len(list((tmp_path / "reviews").glob("*.json"))) == 2
    assert first["paper_execution_performed"] is False
    assert build_reviews({"schema_version": 1, "tasks": []}) == []


def test_invalid_or_duplicate_batch_never_writes_partial_admissions(tmp_path):
    task = manager()
    for tasks in ([task, deepcopy(task)], [task, {"qa_verifier_only": True}]):
        store = tmp_path / "reviews"
        with pytest.raises(ValueError):
            persist_reviews({"schema_version": 1, "tasks": tasks}, store)
        assert not store.exists()


def test_admission_cli_reads_actual_runtime_file_and_reuses_exact_evidence(tmp_path):
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps({"schema_version": 1, "tasks": [manager()]}), encoding="utf-8")
    summary = tmp_path / "summary.json"
    # The coordinator installs no third-party packages. Prove the COMPLETE
    # positive admission path works with Python's standard library alone.
    cmd = [sys.executable, "-S", str(Path(__file__).resolve().parents[1] / "scripts/nexus_strategy_admission_reviews.py"),
           "--runtime", str(runtime), "--store", str(tmp_path / "reviews"), "--summary", str(summary)]
    for expected_new in (1, 0):
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
        assert result.returncode == 0, result.stderr
        value = json.loads(summary.read_text(encoding="utf-8"))
        assert value["new_evidence_files"] == expected_new
        assert value["registry_candidate_records"] == 1


def test_failed_cli_replaces_a_stale_success_summary(tmp_path):
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps({"schema_version": 1, "tasks": [{"qa_verifier_only": True}]}))
    summary = tmp_path / "summary.json"
    summary.write_text('{"status":"QA_REVIEWS_EVALUATED"}')
    cmd = [sys.executable, "-S", str(Path(__file__).resolve().parents[1] / "scripts/nexus_strategy_admission_reviews.py"),
           "--runtime", str(runtime), "--store", str(tmp_path / "reviews"), "--summary", str(summary)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode != 0
    assert json.loads(summary.read_text())["status"] == "ADMISSION_REVIEW_FAILED"
    assert not (tmp_path / "reviews").exists()


def test_coordinator_invokes_admission_after_existing_dispatch_and_watchdogs():
    path = Path(__file__).resolve().parents[1] / ".github/workflows/fast-agent-coordinator.yml"
    text = path.read_text(encoding="utf-8")
    assert "scripts/nexus_strategy_admission_reviews.py" in text
    assert text.index("Dispatch newly leased tasks") < text.index("Persist independently verified QUAL-42")
    assert text.index("prospective_paper_schedule_watchdog.py") < text.index("Persist independently verified QUAL-42")
