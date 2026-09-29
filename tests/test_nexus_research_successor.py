"""Adversarial tests for automatic, independently QA-bound Research continuation."""
from __future__ import annotations

import base64
import json
from copy import deepcopy
from pathlib import Path

import pytest

import agent_manager as am
import agent_manager_runner as runner
import agent_transport
import nexus_agent_research_prepare as prepare
import nexus_composite_strategy_research as search
from nexus_research_missions import (
    FIRST, SECOND, THIRD, FOURTH, ANCESTRY, attested_predecessor, validate_ancestry,
)
from scripts.agent_task_executor import decode_payload, deterministic_execution

OLD_SOURCE = "a" * 40
NEW_SOURCE = "b" * 40


def prior(*, mechanism="bar_proxy_vwap_reclaim"):
    return {
        "id": FIRST,
        "status": "DONE",
        "producer": "research-agent",
        "verifier": "qa-verifier-agent",
        "research_producer_lease_id": "producer-original",
        "result_evidence": {
            "executor": "nexus-real-composite-backtest",
            "source_sha": OLD_SOURCE,
            "lease_id": "producer-original",
            "receipt_digest": "1" * 64,
            "prior_ledger_digest": "2" * 64,
            "ledger_digest": "3" * 64,
            "config_fingerprint": "4" * 64,
            "mechanism": mechanism,
            "independent_qa_complete": False,
            "auto_demo_promotion": False,
            "live_enabled": False,
        },
        "verification_evidence": {
            "executor": "nexus-independent-composite-numeric-qa",
            "source_sha": OLD_SOURCE,
            "producer_lease_id": "producer-original",
            "producer_receipt_digest": "1" * 64,
            "qa_digest": "5" * 64,
            "independent_qa_complete": True,
            "auto_demo_promotion": False,
            "live_enabled": False,
        },
    }


def child():
    return {
        "id": SECOND, "status": "PENDING", "phase": 7, "gate": 17, "priority": 90,
        "dependencies": [FIRST], "authority": 2,
        "required_capabilities": ["data_validation"],
        "preferred_resources": ["github-cloud"],
        "required_resources": ["github-cloud"],
        "acceptance": ["different causal mechanism"],
    }


def linked(monkeypatch):
    monkeypatch.setattr(am, "emit", lambda *args, **kwargs: None)
    template = am.load_config(Path("config/nexus-agent-manager.json"))
    config = {"schema_version": 1, "phase": 4, "tasks": [prior(), child()],
              "workers": template["workers"], "policy": template["policy"]}
    assert runner.bind_qa_attested_successor(config) == "QA_attested_successor_bound"
    return config


def payload_for(task, worker="research-agent", verifying=False):
    if verifying:
        task = deepcopy(task)
        task.update({
            "status": "VERIFYING", "assigned_worker": worker,
            "lease_id": "successor-qa", "research_producer_lease_id": "successor-original",
            "result_evidence": {
                "receipt_digest": "8" * 64, "source_sha": NEW_SOURCE,
                "independent_qa_complete": False, "auto_demo_promotion": False,
                "live_enabled": False,
            },
        })
    else:
        task = deepcopy(task)
        task.update({
            "status": "LEASED", "assigned_worker": worker,
            "lease_id": "successor-lease",
        })
    env = agent_transport.envelope_for(task)
    return env


def encoded(payload):
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def test_successor_requires_complete_independent_QA_and_not_a_green_test():
    task = prior()
    proof = attested_predecessor(task)
    assert proof["research_predecessor_ledger_digest"] == "3" * 64
    assert proof["research_predecessor_qa_digest"] == "5" * 64
    for change in (
        lambda t: t["verification_evidence"].update(independent_qa_complete=False),
        lambda t: t["verification_evidence"].update(producer_lease_id="unrelated"),
        lambda t: t["verification_evidence"].update(producer_receipt_digest="9" * 64),
        lambda t: t.update(status="VERIFYING"),
        lambda t: t.update(verifier="research-agent"),
        lambda t: t["result_evidence"].update(auto_demo_promotion=True),
        lambda t: t["result_evidence"].update(executor="bounded-pytest"),
    ):
        broken = deepcopy(task)
        change(broken)
        with pytest.raises(ValueError):
            attested_predecessor(broken)


def test_bound_ancestry_survives_repeated_runner_cycles(monkeypatch):
    conf = linked(monkeypatch)
    ancestry = {key: conf["tasks"][1][key] for key in ANCESTRY}
    assert runner.bind_qa_attested_successor(conf) == "QA_attested_successor_unchanged"
    assert {key: conf["tasks"][1][key] for key in ANCESTRY} == ancestry
    template = {"schema_version": 1, "workers": [], "tasks": [prior(), child()]}
    runtime = {"schema_version": 1, "tasks": [prior(), conf["tasks"][1]]}
    merged = runner.merge_definition(template, runtime)
    assert {key: merged["tasks"][1][key] for key in ANCESTRY} == ancestry


def test_changed_predecessor_can_never_rewrite_leased_successor(monkeypatch):
    conf = linked(monkeypatch)
    conf["tasks"][0]["result_evidence"]["ledger_digest"] = "9" * 64
    with pytest.raises(ValueError, match="changed"):
        runner.bind_qa_attested_successor(conf)


def test_same_mechanism_second_producer_rejected_before_independent_QA(monkeypatch):
    conf = linked(monkeypatch)
    task = conf["tasks"][1]
    task.update(status="RUNNING", assigned_worker="research-agent",
                lease_id="successor-lease")
    with pytest.raises(ValueError, match="different"):
        am.record_result(conf, SECOND, "research-agent", "success", {
            "receipt_digest": "8" * 64,
            "mechanism": "bar_proxy_vwap_reclaim",
            "prior_ledger_digest": "3" * 64,
            "independent_qa_complete": False,
            "auto_demo_promotion": False,
            "live_enabled": False,
        })
    assert task["status"] == "RUNNING"


def test_valid_distinct_second_producer_still_requires_independent_QA(monkeypatch):
    conf = linked(monkeypatch)
    task = conf["tasks"][1]
    task.update(status="RUNNING", assigned_worker="research-agent",
                lease_id="successor-lease")
    monkeypatch.setattr(am, "emit", lambda *args, **kwargs: None)
    am.record_result(conf, SECOND, "research-agent", "success", {
        "receipt_digest": "8" * 64, "source_sha": NEW_SOURCE,
        "mechanism": "failed_range_break_reversal",
        "prior_ledger_digest": "3" * 64,
        "independent_qa_complete": False,
        "auto_demo_promotion": False, "live_enabled": False,
    })
    assert task["status"] == "VERIFYING"
    assert task["verifier"] == "qa-verifier-agent"
    assert task["research_producer_lease_id"] == "successor-lease"
    with pytest.raises(ValueError):
        am.record_result(conf, SECOND, "qa-verifier-agent", "success", {
            "independent_qa_complete": True,
            "producer_receipt_digest": "0" * 64,
            "producer_lease_id": "successor-lease",
            "source_sha": NEW_SOURCE, "qa_digest": "a" * 64,
            "auto_demo_promotion": False, "live_enabled": False,
        })
    assert task["status"] == "VERIFYING"
    am.record_result(conf, SECOND, "qa-verifier-agent", "success", {
        "independent_qa_complete": True,
        "producer_receipt_digest": "8" * 64,
        "producer_lease_id": "successor-lease",
        "source_sha": NEW_SOURCE, "qa_digest": "a" * 64,
        "auto_demo_promotion": False, "live_enabled": False,
    })
    assert task["status"] == "DONE"


def test_exact_successor_envelope_binds_predecessor_producer_and_QA(monkeypatch):
    conf = linked(monkeypatch)
    producer = payload_for(conf["tasks"][1])
    assert producer["task_id"] == SECOND
    assert producer["research_predecessor_receipt_digest"] == "1" * 64
    assert set(producer).issuperset(ANCESTRY)
    assert decode_payload(encoded(producer)) == producer
    qa = payload_for(conf["tasks"][1], "qa-verifier-agent", verifying=True)
    assert qa["research_producer_receipt_digest"] == "8" * 64
    assert qa["research_predecessor_qa_digest"] == "5" * 64
    assert decode_payload(encoded(qa)) == qa


def test_malformed_or_unapproved_followon_envelope_fails_closed(monkeypatch):
    conf = linked(monkeypatch)
    p = payload_for(conf["tasks"][1])
    for changed in [
        {k: v for k, v in p.items() if k != "research_predecessor_qa_digest"},
        {**p, "research_predecessor_source_sha": "z" * 40},
        {**p, "research_predecessor_ledger_digest": "3" * 63},
        {**p, "free_shell_command": "ignored"},
    ]:
        with pytest.raises(ValueError):
            decode_payload(encoded(changed))
    with pytest.raises(ValueError):
        validate_ancestry({"unexpected": "unsafe"})


def test_successor_fails_closed_without_approved_cache(monkeypatch, tmp_path):
    conf = linked(monkeypatch)
    p = payload_for(conf["tasks"][1])
    monkeypatch.setenv("NEXUS_TASK_PAYLOAD_B64", encoded(p))
    monkeypatch.setenv("GITHUB_SHA", NEW_SOURCE)
    monkeypatch.setenv("GITHUB_REPOSITORY", prepare.REPO)
    assert prepare._classify("inspect")[1] == "producer"
    monkeypatch.setattr(prepare, "DATA_CACHE", tmp_path / "missing")
    with pytest.raises(prepare.ResearchPreparationError):
        prepare.prepare("producer", tmp_path / "stage")


def test_successor_requires_EXACT_prior_QA_ledger_and_different_mechanism(monkeypatch, tmp_path):
    # Mock the slow official archive validator, NOT the actual novelty-ledger logic.
    old = search.empty_ledger()
    # Run through existing grammar in deterministic order. Last selected
    # mechanism represents the independently verified original QA.
    unseen_mechanism = search.CONFIGS[-1]["mechanism"]
    for c in [x for x in search.CONFIGS
              if x["risk_variant"] == 0 and x["mechanism"] != unseen_mechanism]:
        old["config_fingerprints_evaluated"].append(
            search.digest({"config": c, "dataset": search.ARCHIVE_SHA256,
                           "contract": search.SCHEMA})
        )
        old["mechanisms_evaluated"].append(c["mechanism"])
    unsigned = {k: v for k, v in old.items() if k != "ledger_digest"}
    unsigned["mechanisms_evaluated"] = sorted(set(unsigned["mechanisms_evaluated"]))
    old = {**unsigned, "ledger_digest": search.digest(unsigned)}
    monkeypatch.setattr(prepare, "DATA_CACHE", tmp_path)
    (tmp_path / "previous-ledger.json").write_text(json.dumps(old))
    (tmp_path / prepare.REPLAY_NAME).write_bytes(b"mock official archive")
    manifest = {
        "schema": "nexus.real-research-transport.v1",
        "source_sha": NEW_SOURCE,
        "archive_sha256": search.ARCHIVE_SHA256,
        "replay_zip_sha256": "a" * 64,
        "prior_ledger_digest": old["ledger_digest"],
        "research_only": True,
        "auto_demo_promotion": False,
        "live_enabled": False,
    }
    (tmp_path / "manifest.json").write_text(json.dumps({
        **manifest, "manifest_digest": search.digest(manifest)
    }))
    monkeypatch.setattr(prepare, "validate_candidate", lambda *a, **k: (
        tmp_path / prepare.REPLAY_NAME, {}
    ))
    monkeypatch.setattr(prepare, "sha256_file", lambda *_: "a" * 64)
    monkeypatch.setattr(prepare, "safe_extract", lambda _archive, root: root.mkdir(parents=True, exist_ok=True))
    ancestor = {"research_predecessor_ledger_digest": old["ledger_digest"],
                "research_predecessor_mechanism": "failed_range_break_reversal"}
    # Keep one reviewed family untouched: a successor may consume it exactly once.
    selected = search.select_next(old)
    assert selected["mechanism"] == unseen_mechanism
    assert selected is not None
    ancestor["research_predecessor_mechanism"] = selected["mechanism"]
    with pytest.raises(prepare.ResearchPreparationError, match="different"):
        prepare._verified_input_bundle(tmp_path / "denied", NEW_SOURCE, ancestor)
    ancestor["research_predecessor_mechanism"] = (
        "bar_proxy_vwap_reclaim" if selected["mechanism"] != "bar_proxy_vwap_reclaim"
        else "failed_range_break_reversal"
    )
    report = prepare._verified_input_bundle(tmp_path / "approved", NEW_SOURCE, ancestor)
    assert report["prior_ledger_digest"] == old["ledger_digest"]
    ancestor["research_predecessor_ledger_digest"] = "f" * 64
    with pytest.raises(prepare.ResearchPreparationError, match="prior QA"):
        prepare._verified_input_bundle(tmp_path / "wrong", NEW_SOURCE, ancestor)

    # Once every family has been evaluated, select_next intentionally offers
    # risk-variant robustness. Real successor leases MUST NOT call it novelty.
    exhausted_core = {k: deepcopy(v) for k, v in old.items() if k != "ledger_digest"}
    last = next(c for c in search.CONFIGS
                if c["mechanism"] == unseen_mechanism and c["risk_variant"] == 0)
    exhausted_core["config_fingerprints_evaluated"].append(search.digest({
        "config": last, "dataset": search.ARCHIVE_SHA256, "contract": search.SCHEMA
    }))
    exhausted_core["mechanisms_evaluated"] = sorted(
        {*exhausted_core["mechanisms_evaluated"], unseen_mechanism}
    )
    exhausted = {**exhausted_core, "ledger_digest": search.digest(exhausted_core)}
    assert search.select_next(exhausted)["mechanism"] in exhausted["mechanisms_evaluated"]
    (tmp_path / "previous-ledger.json").write_text(json.dumps(exhausted))
    manifest["prior_ledger_digest"] = exhausted["ledger_digest"]
    (tmp_path / "manifest.json").write_text(json.dumps({
        **manifest, "manifest_digest": search.digest(manifest)
    }))
    ancestor["research_predecessor_ledger_digest"] = exhausted["ledger_digest"]
    ancestor["research_predecessor_mechanism"] = unseen_mechanism
    with pytest.raises(prepare.ResearchPreparationError, match="no new reviewed"):
        prepare._verified_input_bundle(tmp_path / "exhausted", NEW_SOURCE, ancestor)


def test_cold_successor_remains_parked_until_new_exact_source_cache_is_ready(monkeypatch):
    config = linked(monkeypatch)
    task = config["tasks"][1]
    assert runner.apply_research_input_gate(config, ready=False) == "parked_waiting_cache"
    assert task["status"] == "BLOCKED"
    assert task["blocked_reason"] == runner.RESEARCH_WAIT
    am.cycle(config)
    assert task["status"] == "BLOCKED"
    assert runner.bind_qa_attested_successor(config) == "QA_attested_successor_unchanged"
    assert runner.apply_research_input_gate(config, ready=True) == "ready_for_producer_lease"
    am.cycle(config)
    assert task["status"] == "LEASED"
    assert task["assigned_worker"] == "research-agent"
    assert task["lease_id"]
    assert task["research_predecessor_qa_digest"] == "5" * 64


def test_untrusted_original_QA_cannot_release_successor(monkeypatch):
    config = linked(monkeypatch)
    config["tasks"][0]["verification_evidence"]["producer_receipt_digest"] = "f" * 64
    assert runner.bind_qa_attested_successor(config) == "untrusted_prior_QA"
    assert config["tasks"][1]["status"] == "BLOCKED"
    assert runner.apply_research_input_gate(config, ready=True) == "successor_QA_not_attested"


def test_research_unavailable_never_routes_real_work_to_generic_QA(monkeypatch):
    config = linked(monkeypatch)
    for worker in config["workers"]:
        if worker["id"] == "research-agent":
            worker["enabled"] = False
    runner.apply_research_input_gate(config, ready=True)
    am.cycle(config)
    task = config["tasks"][1]
    assert task["status"] == "READY"
    assert not task.get("assigned_worker")


def test_designated_independent_numerical_QA_is_required_not_any_verifier(monkeypatch):
    config = linked(monkeypatch)
    for worker in config["workers"]:
        if worker["id"] == "qa-verifier-agent":
            worker["enabled"] = False
    task = config["tasks"][1]
    task.update(status="RUNNING", assigned_worker="research-agent",
                producer="research-agent", lease_id="second-producer")
    am.record_result(config, SECOND, "research-agent", "success", {
        "receipt_digest": "8" * 64, "source_sha": NEW_SOURCE,
        "mechanism": "failed_range_break_reversal",
        "prior_ledger_digest": "3" * 64,
        "independent_qa_complete": False,
        "auto_demo_promotion": False, "live_enabled": False,
    })
    assert task["status"] == "BLOCKED"
    assert task["blocked_reason"] == "independent verifier unavailable"


def second_done():
    one = prior()
    two = child()
    two.update({
        "status": "DONE", "producer": "research-agent",
        "verifier": "qa-verifier-agent",
        "research_producer_lease_id": "real-second-producer",
        "result_evidence": {
            "executor": "nexus-real-composite-backtest",
            "source_sha": NEW_SOURCE, "lease_id": "real-second-producer",
            "receipt_digest": "6" * 64,
            "prior_ledger_digest": "3" * 64,
            "ledger_digest": "7" * 64,
            "config_fingerprint": "8" * 64,
            "mechanism": "failed_range_break_reversal",
            "independent_qa_complete": False,
            "auto_demo_promotion": False,
            "live_enabled": False,
        },
        "verification_evidence": {
            "executor": "nexus-independent-composite-numeric-qa",
            "source_sha": NEW_SOURCE,
            "producer_lease_id": "real-second-producer",
            "producer_receipt_digest": "6" * 64,
            "qa_digest": "9" * 64,
            "independent_qa_complete": True,
            "auto_demo_promotion": False,
            "live_enabled": False,
        },
    })
    # A genuinely completed second mission MUST already preserve its own
    # first-producer+QA ancestry; a DONE task without it is invalid runtime.
    two.update(attested_predecessor(one))
    three = child()
    three.update(id="P7-RESEARCH-COMPOSITE-003", dependencies=[SECOND])
    return {"tasks": [one, two, three]}


def test_third_lease_inherits_exact_second_independent_QA_and_cold_restart(monkeypatch):
    conf = second_done()
    monkeypatch.setattr(am, "emit", lambda *args, **kwargs: None)
    assert runner.bind_qa_attested_successor(conf) == "QA_attested_successor_bound"
    third = conf["tasks"][2]
    assert third["research_predecessor_ledger_digest"] == "7" * 64
    assert third["research_predecessor_receipt_digest"] == "6" * 64
    assert third["research_predecessor_qa_digest"] == "9" * 64
    assert third["research_predecessor_mechanism"] == "failed_range_break_reversal"
    assert runner.bind_qa_attested_successor(conf) == "QA_attested_successor_unchanged"
    assert runner.apply_research_input_gate(conf, ready=False) == "parked_waiting_cache"
    assert third["status"] == "BLOCKED"
    assert runner.apply_research_input_gate(conf, ready=True) == "ready_for_producer_lease"
    assert third["status"] == "READY"
    template = {"schema_version": 1, "workers": [], "tasks": [prior(), child(), {
        **child(), "id": "P7-RESEARCH-COMPOSITE-003", "dependencies": [SECOND]}]}
    runtime = {"schema_version": 1, "tasks": conf["tasks"]}
    merged = runner.merge_definition(template, runtime)
    assert merged["tasks"][2]["research_predecessor_qa_digest"] == "9" * 64
    assert merged["tasks"][2]["research_predecessor_ledger_digest"] == "7" * 64


def test_third_rejects_stale_peer_frontier_and_same_predecessor_mechanism(monkeypatch):
    conf = second_done()
    monkeypatch.setattr(am, "emit", lambda *a, **kw: None)
    runner.bind_qa_attested_successor(conf)
    third = conf["tasks"][2]
    env = payload_for(third)
    assert decode_payload(encoded(env)) == env
    assert env["research_predecessor_receipt_digest"] == "6" * 64
    assert env["research_predecessor_qa_digest"] == "9" * 64
    for changed in (
        {**env, "research_predecessor_ledger_digest": "a" * 63},
        {**env, "research_predecessor_qa_digest": None},
        {**env, "research_predecessor_source_sha": "z" * 40},
    ):
        with pytest.raises(ValueError):
            decode_payload(encoded(changed))
    third.update(status="RUNNING", assigned_worker="research-agent",
                 lease_id="third-producer")
    with pytest.raises(ValueError, match="different"):
        am.record_result(conf, third["id"], "research-agent", "success", {
            "receipt_digest": "a" * 64,
            "source_sha": NEW_SOURCE,
            "prior_ledger_digest": "7" * 64,
            "mechanism": "failed_range_break_reversal",
            "independent_qa_complete": False,
            "auto_demo_promotion": False,
            "live_enabled": False,
        })
    assert third["status"] == "RUNNING"
    with pytest.raises(ValueError, match="different"):
        am.record_result(conf, third["id"], "research-agent", "success", {
            "receipt_digest": "a" * 64, "source_sha": NEW_SOURCE,
            "prior_ledger_digest": "f" * 64,
            "mechanism": "cross_pair_relative_reclaim",
            "independent_qa_complete": False,
            "auto_demo_promotion": False, "live_enabled": False,
        })
    assert third["status"] == "RUNNING"


def test_new_mechanism_preferred_to_prior_risk_variant_with_second_QA_frontier():
    previous = search.empty_ledger()
    core = {k: v for k, v in previous.items() if k != "ledger_digest"}
    for cfg in search.CONFIGS:
        if cfg["mechanism"] == "cross_pair_relative_reclaim":
            continue
        if cfg["risk_variant"] == 0 or cfg["mechanism"] == "failed_range_break_reversal":
            core["config_fingerprints_evaluated"].append(
                search.digest({"config": cfg, "dataset": search.ARCHIVE_SHA256,
                               "contract": search.SCHEMA})
            )
            core["mechanisms_evaluated"].append(cfg["mechanism"])
    core["mechanisms_evaluated"] = sorted(set(core["mechanisms_evaluated"]))
    old = {**core, "ledger_digest": search.digest(core)}
    chosen = search.select_next(old)
    assert chosen["mechanism"] == "cross_pair_relative_reclaim"
    assert chosen["fingerprint"] not in core["config_fingerprints_evaluated"]


def test_changed_second_QA_receipt_cannot_rebind_third_even_if_first_done(monkeypatch):
    conf = second_done()
    monkeypatch.setattr(am, "emit", lambda *a, **kw: None)
    runner.bind_qa_attested_successor(conf)
    third = conf["tasks"][2]
    bound = {key: third[key] for key in ANCESTRY}
    conf["tasks"][1]["verification_evidence"]["qa_digest"] = "f" * 64
    with pytest.raises(ValueError, match="changed"):
        runner.bind_qa_attested_successor(conf)
    assert {key: third[key] for key in ANCESTRY} == bound


def third_done_for_fourth():
    """Verified mock first->second->third lineage; not real evidence."""
    conf = second_done()
    third = conf["tasks"][2]
    third.update({
        "status": "DONE", "producer": "research-agent",
        "verifier": "qa-verifier-agent",
        "research_producer_lease_id": "third-producer-original",
        "result_evidence": {
            "executor": "nexus-real-composite-backtest", "source_sha": "c" * 40,
            "lease_id": "third-producer-original", "receipt_digest": "a" * 64,
            "prior_ledger_digest": "7" * 64, "ledger_digest": "d" * 64,
            "config_fingerprint": "e" * 64, "mechanism": "cross_pair_relative_reclaim",
            "independent_qa_complete": False, "auto_demo_promotion": False,
            "live_enabled": False,
        },
        "verification_evidence": {
            "executor": "nexus-independent-composite-numeric-qa",
            "source_sha": "c" * 40, "producer_lease_id": "third-producer-original",
            "producer_receipt_digest": "a" * 64, "qa_digest": "f" * 64,
            "independent_qa_complete": True, "auto_demo_promotion": False,
            "live_enabled": False,
        },
    })
    third.update(attested_predecessor(conf["tasks"][1]))
    fourth = child()
    fourth.update(id=FOURTH, priority=88, dependencies=[THIRD])
    conf["tasks"].append(fourth)
    template = am.load_config(Path("config/nexus-agent-manager.json"))
    conf.update(schema_version=1, phase=4, workers=template["workers"],
                policy=template["policy"])
    return conf


def test_fourth_exact_qa_bound_cold_restart_and_no_duplicate_lease(monkeypatch):
    conf = third_done_for_fourth()
    monkeypatch.setattr(am, "emit", lambda *args, **kwargs: None)
    assert runner.bind_qa_attested_successor(conf) == "QA_attested_successor_bound"
    fourth = conf["tasks"][3]
    assert fourth["research_predecessor_source_sha"] == "c" * 40
    assert fourth["research_predecessor_receipt_digest"] == "a" * 64
    assert fourth["research_predecessor_qa_digest"] == "f" * 64
    assert fourth["research_predecessor_ledger_digest"] == "d" * 64
    assert fourth["research_predecessor_mechanism"] == "cross_pair_relative_reclaim"
    assert runner.bind_qa_attested_successor(conf) == "QA_attested_successor_unchanged"
    assert runner.apply_research_input_gate(conf, ready=False) == "parked_waiting_cache"
    assert runner.apply_research_input_gate(conf, ready=True) == "ready_for_producer_lease"
    assert fourth["status"] == "READY"
    env = payload_for(fourth)
    assert decode_payload(encoded(env)) == env
    assert env["research_predecessor_qa_digest"] == "f" * 64
    for changed in (
        {**env, "research_predecessor_qa_digest": None},
        {**env, "research_predecessor_ledger_digest": "z" * 64},
        {**env, "free_command": "git push --force"},
    ):
        with pytest.raises(ValueError):
            decode_payload(encoded(changed))
    template = deepcopy(conf)
    template["tasks"][3] = {key: val for key, val in child().items()
                            if key not in ANCESTRY}
    template["tasks"][3].update(id=FOURTH, dependencies=[THIRD])
    merged = runner.merge_definition(template, {"schema_version": 1, "tasks": conf["tasks"]})
    assert merged["tasks"][3]["research_predecessor_qa_digest"] == "f" * 64
    assert merged["tasks"][3]["research_predecessor_ledger_digest"] == "d" * 64


def test_fourth_rejects_same_causal_mechanism_wrong_frontier_and_stale_third_QA(monkeypatch):
    conf = third_done_for_fourth()
    monkeypatch.setattr(am, "emit", lambda *args, **kwargs: None)
    runner.bind_qa_attested_successor(conf)
    fourth = conf["tasks"][3]
    fourth.update(status="RUNNING", assigned_worker="research-agent",
                  lease_id="fourth-producer")
    evidence = {
        "receipt_digest": "1" * 64, "source_sha": "b" * 40,
        "mechanism": "lagged_peer_impulse_confirmation",
        "prior_ledger_digest": "d" * 64,
        "independent_qa_complete": False,
        "auto_demo_promotion": False, "live_enabled": False,
    }
    for changes in (
        {"mechanism": "cross_pair_relative_reclaim"},
        {"prior_ledger_digest": "0" * 64},
    ):
        with pytest.raises(ValueError, match="different"):
            am.record_result(conf, FOURTH, "research-agent", "success",
                             {**evidence, **changes})
        assert fourth["status"] == "RUNNING"
    am.record_result(conf, FOURTH, "research-agent", "success", evidence)
    assert fourth["status"] == "VERIFYING"
    assert fourth["research_producer_lease_id"] == "fourth-producer"
    verifier_evidence = {
        "independent_qa_complete": True, "source_sha": "b" * 40,
        "producer_lease_id": "fourth-producer",
        "producer_receipt_digest": "1" * 64, "qa_digest": "2" * 64,
        "auto_demo_promotion": False, "live_enabled": False,
    }
    with pytest.raises(ValueError):
        am.record_result(conf, FOURTH, "qa-verifier-agent", "success",
                         {**verifier_evidence, "producer_receipt_digest": "3" * 64})
    assert fourth["status"] == "VERIFYING"
    am.record_result(conf, FOURTH, "qa-verifier-agent", "success", verifier_evidence)
    assert fourth["status"] == "DONE"
    assert fourth["verification_evidence"]["independent_qa_complete"] is True
    prior_qa = conf["tasks"][2]["verification_evidence"]
    prior_qa["qa_digest"] = "0" * 64
    with pytest.raises(ValueError, match="changed"):
        runner.bind_qa_attested_successor(conf)


def test_fourth_never_replays_third_as_risk_parameter_variant():
    previous = search.empty_ledger()
    core = {key: value for key, value in previous.items() if key != "ledger_digest"}
    for cfg in search.CONFIGS:
        if cfg["mechanism"] == "lagged_peer_impulse_confirmation" or cfg["risk_variant"] != 0:
            continue
        core["config_fingerprints_evaluated"].append(search.digest({
            "config": cfg, "dataset": search.ARCHIVE_SHA256, "contract": search.SCHEMA,
        }))
        core["mechanisms_evaluated"].append(cfg["mechanism"])
    core["mechanisms_evaluated"] = sorted(set(core["mechanisms_evaluated"]))
    selected = search.select_next({**core, "ledger_digest": search.digest(core)})
    assert selected is not None
    assert selected["mechanism"] == "lagged_peer_impulse_confirmation"
    assert selected["risk_variant"] == 0
