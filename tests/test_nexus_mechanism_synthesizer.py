from __future__ import annotations

import json
from pathlib import Path

import pytest

import nexus_mechanism_factory as factory
import nexus_composite_strategy_research as research


def _variant(tmp_path: Path, mutate):
    raw = json.loads(factory.DEFAULT_SYNTH_CONTRACT.read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / "synth.json"
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return path


def test_checked_in_synthesizer_generates_deterministic_unseen_contracts():
    static = factory.load_factory_contract()
    first = factory.synthesize_factory_contracts(existing=static)
    second = factory.synthesize_factory_contracts(existing=static)
    assert first == second
    assert len(first) == 29
    assert tuple(first) == research.SYNTH_FACTORY_MECHANISMS
    assert not (set(first) & set(static))
    assert len({row["topology_digest"] for row in first.values()}) == len(first)
    assert len({row["contract_digest"] for row in first.values()}) == len(first)
    assert all(key.startswith("synth_") for key in first)
    assert all(len(row["contract_digest"]) == 64 for row in first.values())


def test_synthesizer_peer_contracts_are_derived_not_declared_by_id():
    static = factory.load_factory_contract()
    synth = factory.synthesize_factory_contracts(existing=static)
    peers = factory.factory_peer_ids(synth)
    assert len(peers) == 11
    assert all(synth[key]["peer_required"] is True for key in peers)
    assert all(
        any(
            cond["field"] in factory.PEER_FIELDS
            or cond.get("other") in factory.PEER_FIELDS
            for cond in synth[key]["context"]
        )
        for key in peers
    )


def test_synthesizer_rejects_current_bar_context_leakage(tmp_path: Path):
    path = _variant(
        tmp_path,
        lambda raw: raw["contexts"][0]["conditions"][0].update({"field": "close"}),
    )
    with pytest.raises(factory.MechanismFactoryError, match="context field"):
        factory.synthesize_factory_contracts(path, existing=factory.load_factory_contract())


def test_synthesizer_rejects_unknown_compatibility_target(tmp_path: Path):
    path = _variant(
        tmp_path,
        lambda raw: raw["contexts"][0]["compatible_entries"].append("not_reviewed"),
    )
    with pytest.raises(factory.MechanismFactoryError, match="compatibility"):
        factory.synthesize_factory_contracts(path, existing=factory.load_factory_contract())


def test_synthesizer_rejects_peer_flag_mismatch(tmp_path: Path):
    path = _variant(
        tmp_path,
        lambda raw: raw["contexts"][5].update({"peer_required": False}),
    )
    with pytest.raises(factory.MechanismFactoryError, match="peer_required"):
        factory.synthesize_factory_contracts(path, existing=factory.load_factory_contract())


def test_synthesizer_contract_mutation_changes_candidate_digest(tmp_path: Path):
    static = factory.load_factory_contract()
    base = factory.synthesize_factory_contracts(existing=static)
    path = _variant(
        tmp_path,
        lambda raw: raw["entries"][0]["conditions"][-1].update({"value": 0.80}),
    )
    changed = factory.synthesize_factory_contracts(path, existing=static)
    ident = "synth_efficient_up_mid_reclaim"
    assert changed[ident]["contract_digest"] != base[ident]["contract_digest"]


def test_research_engine_binds_synthesized_contract_digest():
    ident = "synth_efficient_up_mid_reclaim"
    config = next(row for row in research.FRONTIER_CONFIGS if row["mechanism"] == ident)
    assert config["factory_contract_digest"] == research.SYNTH_FACTORY_SPECS[ident]["contract_digest"]
    assert config["risk_variant"] == 0
    assert ident in research.ALL_MECHANISMS
