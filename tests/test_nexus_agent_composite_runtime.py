"""Safety and evidence contracts of the real leased Research Agent workload.

Numerical engine tests separately exercise real causal features and fills.
These tests keep the API boundary deterministic and verify independent QA
actually re-executes rather than trusting producer signatures alone.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

import agent_manager as manager
import nexus_agent_composite_runtime as runtime
import nexus_agent_research_prepare as prepare
import nexus_composite_strategy_research as research


SOURCE = "a" * 40
LEASE = "lease-composite-001"


def _previous(path: Path) -> dict:
    previous = research.empty_ledger()
    research.safe_write(path, previous)
    return previous


def _fake_engine(monkeypatch, *, modifier=None):
    calls = []

    def execute(archive_root, output, source_sha, prior):
        calls.append((archive_root, prior))
        old = research.load_ledger(prior)
        nxt = research.select_next(old)
        core = {k: v for k, v in old.items() if k != "ledger_digest"}
        core["config_fingerprints_evaluated"] = [
            *core["config_fingerprints_evaluated"], nxt["fingerprint"],
        ]
        core["mechanisms_evaluated"] = sorted(
            set([*core["mechanisms_evaluated"], nxt["mechanism"]]),
        )
        updated = {**core, "ledger_digest": research.digest(core)}
        rows = [
            {
                "symbol": symbol, "part": part, "profile": profile,
                "timeframe": "minute15_with_completed_1h_4h",
                "mechanism": nxt["mechanism"],
                "config_fingerprint": nxt["fingerprint"],
                "closed_round_trips": 13,
                "net_return_pct": -1.25,
                "max_drawdown_pct": 3.0,
                "win_rate_pct": 38.0,
                "profit_factor": 0.73,
                "trade_count_limit": None,
                "fee_bps": 10 if profile == "conservative" else 25,
                "slippage_bps": 5 if profile == "conservative" else 15,
                "bars": 100,
            }
            for symbol in research.SYMBOLS
            for part in ("train", "validation", "historically_inspected_test")
            for profile in ("conservative", "stress")
        ]
        if modifier:
            modifier(rows, len(calls))
        report = {
            "schema": research.SCHEMA, "source_sha": source_sha,
            "archive_sha256": research.ARCHIVE_SHA256,
            "status": "EVALUATED_RESEARCH_ONLY",
            "historical_test_pristine": False,
            "independent_future_data_required": True,
            "research_only": True,
            "auto_demo_promotion": False,
            "live_enabled": False,
            "qualification": "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT",
            "selected": nxt,
            "rows": rows,
            "ledger_digest": updated["ledger_digest"],
        }
        report["report_digest"] = research.digest(report)
        research.safe_write(output / "research-report.json", report)
        research.safe_write(output / "novelty-ledger.json", updated)
        return report

    monkeypatch.setattr(research, "run", execute)
    return calls


def test_real_lease_executes_engine_and_qa_replays_on_independent_worker(tmp_path, monkeypatch):
    old = tmp_path / "prior.json"
    _previous(old)
    calls = _fake_engine(monkeypatch)
    result_dir = tmp_path / "proof"
    evidence = runtime.run_lease(
        archive_root=tmp_path / "archive", previous_ledger=old,
        source_sha=SOURCE, lease_id=LEASE, output_dir=result_dir,
    )
    assert len(calls) == 1
    assert evidence["independent_qa_complete"] is False
    assert evidence["auto_demo_promotion"] is False
    assert evidence["live_enabled"] is False
    assert len(evidence["validation"]) == 4
    assert (result_dir / "previous-ledger.json").is_file()
    qa = runtime.verify_independently(
        archive_root=tmp_path / "archive",
        previous_ledger=result_dir / "previous-ledger.json",
        source_sha=SOURCE, lease_id=LEASE, result_dir=result_dir,
        output=result_dir / "qa.json",
    )
    assert len(calls) == 2
    assert qa["independent_replay_matches"] is True
    assert qa["auto_demo_promotion"] is False


def test_independent_qa_rejects_numerically_different_rerun(tmp_path, monkeypatch):
    old = tmp_path / "prior.json"
    _previous(old)
    calls = _fake_engine(
        monkeypatch,
        modifier=lambda rows, n: rows[0].__setitem__("net_return_pct", -3.0)
        if n == 2 else None,
    )
    result_dir = tmp_path / "proof"
    runtime.run_lease(
        archive_root=tmp_path, previous_ledger=old,
        source_sha=SOURCE, lease_id=LEASE, output_dir=result_dir,
    )
    with pytest.raises(runtime.RealResearchError, match="independent numerical replay"):
        runtime.verify_independently(
            archive_root=tmp_path,
            previous_ledger=result_dir / "previous-ledger.json",
            source_sha=SOURCE, lease_id=LEASE, result_dir=result_dir,
            output=tmp_path / "qa.json",
        )
    assert len(calls) == 2


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("lease_id", "forged-lease"),
        ("source_sha", "b" * 40),
        ("report_file_sha256", "0" * 64),
    ],
)
def test_qa_rejects_producer_receipt_tamper(tmp_path, monkeypatch, field, replacement):
    old = tmp_path / "prior.json"
    _previous(old)
    _fake_engine(monkeypatch)
    output = tmp_path / "proof"
    runtime.run_lease(
        archive_root=tmp_path, previous_ledger=old,
        source_sha=SOURCE, lease_id=LEASE, output_dir=output,
    )
    receipt = json.loads((output / "agent-receipt.json").read_text())
    receipt[field] = replacement
    research.safe_write(output / "agent-receipt.json", receipt)
    with pytest.raises(runtime.RealResearchError, match="receipt"):
        runtime.verify_independently(
            archive_root=tmp_path,
            previous_ledger=output / "previous-ledger.json",
            source_sha=SOURCE, lease_id=LEASE, result_dir=output,
            output=tmp_path / "qa.json",
        )


def test_real_lease_never_resets_missing_ledger(tmp_path, monkeypatch):
    calls = _fake_engine(monkeypatch)
    with pytest.raises(runtime.RealResearchError, match="regular file"):
        runtime.run_lease(
            archive_root=tmp_path, previous_ledger=tmp_path / "missing",
            source_sha=SOURCE, lease_id=LEASE, output_dir=tmp_path / "proof",
        )
    assert calls == []


def test_real_lease_rejects_recycled_risk_variant_without_spending_backtest(tmp_path, monkeypatch):
    # The standalone grammar is allowed to revisit robustness variants.
    # The autonomous Research Agent successor must introduce an unseen family.
    old = research.empty_ledger()
    core = {k: v for k, v in old.items() if k != "ledger_digest"}
    for cfg in research.CONFIGS:
        if cfg["risk_variant"] != 0:
            continue
        core["config_fingerprints_evaluated"].append(research.digest({
            "config": cfg, "dataset": research.ARCHIVE_SHA256,
            "contract": research.SCHEMA,
        }))
        core["mechanisms_evaluated"].append(cfg["mechanism"])
    core["mechanisms_evaluated"] = sorted(set(core["mechanisms_evaluated"]))
    # The new broad frontier has also been training-screened.  Only now is the
    # agent truly out of novel causal work; it must not fall back to legacy
    # risk-variant cycling.
    core["frontier_screening_version"] = research.FRONTIER_SCREEN_VERSION
    core["frontier_screened_mechanisms"] = sorted(research.FRONTIER_MECHANISMS)
    prior = tmp_path / "all-reviewed.json"
    research.safe_write(prior, {**core, "ledger_digest": research.digest(core)})
    loaded = research.load_ledger(prior)
    assert research.select_next(loaded) is not None
    assert research.research_mode(loaded) == "exhausted"
    calls = _fake_engine(monkeypatch)
    with pytest.raises(runtime.RealResearchError, match="no new reviewed"):
        runtime.run_lease(
            archive_root=tmp_path, previous_ledger=prior,
            source_sha=SOURCE, lease_id=LEASE, output_dir=tmp_path / "blocked",
        )
    assert calls == []
    assert not (tmp_path / "blocked").exists()


def test_real_lease_rejects_incomplete_backtest_grid(tmp_path, monkeypatch):
    old = tmp_path / "prior.json"
    _previous(old)
    _fake_engine(monkeypatch, modifier=lambda rows, _: rows.pop())
    with pytest.raises(runtime.RealResearchError, match="two-symbol"):
        runtime.run_lease(
            archive_root=tmp_path, previous_ledger=old,
            source_sha=SOURCE, lease_id=LEASE, output_dir=tmp_path / "proof",
        )


def test_preparer_nonresearch_dispatch_never_fetches_data(tmp_path, monkeypatch):
    payload = {
        "schema_version": 2, "task_id": "P7-CLOUD-VERIFY",
        "lease_id": LEASE, "correlation_id": "c", "dispatch_id": "d",
        "worker_id": "cloud-worker", "transport": "github-cloud",
        "phase": 7, "gate": 1, "title": "normal", "required_capabilities": [],
        "acceptance": [], "authority": 1, "attempt": 1,
    }
    monkeypatch.setenv("NEXUS_TASK_PAYLOAD_B64", base64.urlsafe_b64encode(json.dumps(payload).encode()).decode())
    assert prepare.prepare("producer", tmp_path / "stage") == {"research_task": False}
    assert not (tmp_path / "stage").exists()


def test_invalid_real_research_worker_never_fetches_archive(tmp_path, monkeypatch):
    payload = {
        "schema_version": 2, "task_id": prepare.TASK_ID,
        "lease_id": LEASE, "correlation_id": "c", "dispatch_id": "d",
        "worker_id": "qa-verifier-agent", "transport": "github-cloud",
        "phase": 7, "gate": 1, "title": "research", "required_capabilities": [],
        "acceptance": [], "authority": 2, "attempt": 1,
    }
    monkeypatch.setenv("NEXUS_TASK_PAYLOAD_B64", base64.urlsafe_b64encode(json.dumps(payload).encode()).decode())
    monkeypatch.setenv("GITHUB_REPOSITORY", prepare.REPO)
    monkeypatch.setenv("GITHUB_SHA", SOURCE)
    with pytest.raises(ValueError, match="producer binding absent"):
        prepare.prepare("producer", tmp_path / "stage")
    assert not (tmp_path / "stage").exists()


def test_manager_routes_production_research_to_dedicated_agent_and_separate_qa():
    config = manager.load_config()
    spec = next(t for t in config["tasks"] if t["id"] == prepare.TASK_ID)
    workers = manager.workers_from(config)
    production = manager.rank_worker_candidates(spec, workers)
    assert production[0]["worker_id"] == "research-agent"
    assert production[0]["eligible"]
    spec["producer"] = "research-agent"
    verification = manager.rank_worker_candidates(spec, workers, verifier_only=True)
    assert verification[0]["worker_id"] == "qa-verifier-agent"
    assert verification[0]["eligible"]



def test_research_receipt_survives_independent_agent_manager_verification(tmp_path, monkeypatch):
    import agent_transport
    monkeypatch.setattr(manager, "EVENT_PATH", tmp_path / "manager-events.jsonl")
    cfg = manager.load_config()
    task = next(t for t in cfg["tasks"] if t["id"] == prepare.TASK_ID)
    task.update(status="RUNNING", assigned_worker="research-agent",
                producer="research-agent", lease_id=LEASE, attempt=1)
    producer = {
        "receipt_digest": "b" * 64,
        "source_sha": SOURCE,
        "independent_qa_complete": False,
        "auto_demo_promotion": False,
        "live_enabled": False,
    }
    manager.record_result(cfg, task["id"], "research-agent", "success", producer)
    assert task["status"] == "VERIFYING"
    assert task["research_producer_lease_id"] == LEASE
    assert task["assigned_worker"] == "qa-verifier-agent"
    assert task["lease_id"] != LEASE
    envelope = agent_transport.envelope_for(task)
    assert envelope["research_producer_lease_id"] == LEASE
    assert envelope["research_producer_receipt_digest"] == "b" * 64
    assert envelope["research_producer_source_sha"] == SOURCE
    from scripts.agent_task_executor import decode_payload
    assert decode_payload(base64.urlsafe_b64encode(json.dumps(envelope).encode()).decode()) == envelope
    forged = {
        "producer_receipt_digest": "c" * 64,
        "producer_lease_id": LEASE,
        "source_sha": SOURCE,
        "qa_digest": "d" * 64,
        "independent_qa_complete": True,
        "auto_demo_promotion": False,
        "live_enabled": False,
    }
    with pytest.raises(ValueError, match="independent Research QA"):
        manager.record_result(cfg, task["id"], "qa-verifier-agent", "success", forged)
    assert task["status"] == "VERIFYING"
    valid = {**forged, "producer_receipt_digest": "b" * 64}
    manager.record_result(cfg, task["id"], "qa-verifier-agent", "success", valid)
    assert task["status"] == "DONE"
    assert task["verification_evidence"]["qa_digest"] == "d" * 64


def test_research_qa_payload_rejects_missing_producer_provenance():
    from scripts.agent_task_executor import decode_payload
    payload = {
        "schema_version": 2, "task_id": prepare.TASK_ID,
        "lease_id": "fresh-qa-lease", "correlation_id": "c", "dispatch_id": "d",
        "worker_id": "qa-verifier-agent", "transport": "github-cloud",
        "phase": 7, "gate": 17, "title": "research", "required_capabilities": ["data_validation"],
        "acceptance": ["independent replay"], "authority": 2, "attempt": 1,
    }
    with pytest.raises(ValueError, match="producer binding absent"):
        decode_payload(base64.urlsafe_b64encode(json.dumps(payload).encode()).decode())


def test_real_cloud_executor_invocation_requires_verified_staged_data(tmp_path):
    import os
    import subprocess
    import sys
    payload = {
        "schema_version": 2, "task_id": prepare.TASK_ID,
        "lease_id": LEASE, "correlation_id": "c", "dispatch_id": "d",
        "worker_id": "research-agent", "transport": "github-cloud",
        "phase": 7, "gate": 17, "title": "real research",
        "required_capabilities": ["data_validation"],
        "acceptance": ["verified numeric report"], "authority": 2, "attempt": 1,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    output = tmp_path / "real-agent-result.json"
    env = {**os.environ, "GITHUB_SHA": SOURCE}
    finished = subprocess.run(
        [
            sys.executable, "scripts/agent_task_executor.py",
            "--payload-b64", encoded, "--transport", "github-cloud",
            "--output", str(output),
        ],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=35, check=False,
    )
    assert finished.returncode == 2, finished.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["outcome"] == "failure"
    assert result["evidence"]["failure_class"] == "verified_research_execution_failed"
    assert result["evidence"]["auto_demo_promotion"] is not True


@pytest.mark.parametrize("invalid_original_lease", ["lease\nresearch_role=producer", "../other", "bad lease"])
def test_qa_lease_identity_cannot_inject_workflow_outputs_or_cache_key(
    tmp_path, monkeypatch, invalid_original_lease,
):
    payload = {
        "schema_version": 2, "task_id": prepare.TASK_ID,
        "lease_id": "qa-valid-lease", "correlation_id": "c", "dispatch_id": "d",
        "worker_id": "qa-verifier-agent", "transport": "github-cloud",
        "phase": 7, "gate": 17, "title": "qa",
        "required_capabilities": ["data_validation"], "acceptance": [],
        "authority": 2, "attempt": 1,
        "research_producer_lease_id": invalid_original_lease,
        "research_producer_receipt_digest": "b" * 64,
        "research_producer_source_sha": SOURCE,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    monkeypatch.setenv("NEXUS_TASK_PAYLOAD_B64", encoded)
    monkeypatch.setenv("GITHUB_REPOSITORY", prepare.REPO)
    monkeypatch.setenv("GITHUB_SHA", SOURCE)
    with pytest.raises(prepare.ResearchPreparationError, match="untrusted"):
        prepare.prepare("inspect", tmp_path / "never-created")
    assert not (tmp_path / "never-created").exists()
