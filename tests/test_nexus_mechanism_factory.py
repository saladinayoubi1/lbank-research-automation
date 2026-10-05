from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import nexus_mechanism_factory as factory
import nexus_composite_strategy_research as research


def test_checked_in_factory_contract_is_bounded_and_research_only():
    specs = factory.load_factory_contract()
    assert len(specs) == 12
    assert tuple(specs) == research.FACTORY_MECHANISMS
    assert len({row["contract_digest"] for row in specs.values()}) == len(specs)
    assert len({row["topology_digest"] for row in specs.values()}) == len(specs)
    assert all(len(row["contract_digest"]) == 64 for row in specs.values())
    assert factory.factory_peer_ids(specs) == {
        "factory_peer_residual_vwap_reclaim",
        "factory_peer_residual_range_break",
        "factory_peer_volatility_midpoint_catchup",
        "factory_relative_momentum_vwap_reclaim",
    }


def test_factory_configs_bind_exact_contract_digest():
    specs = factory.load_factory_contract()
    configs = factory.factory_configs(specs)
    assert len(configs) == len(specs)
    assert {row["mechanism"] for row in configs} == set(specs)
    for row in configs:
        assert row["risk_variant"] == 0
        assert row["entry_model"] == "closed_4h_1h_15m_next_open"
        assert row["factory_contract_digest"] == specs[row["mechanism"]]["contract_digest"]


def _write_variant(tmp_path: Path, mutate):
    raw = json.loads(factory.DEFAULT_CONTRACT.read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / "factory.json"
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return path


def test_factory_rejects_unapproved_context_field(tmp_path: Path):
    path = _write_variant(
        tmp_path,
        lambda raw: raw["candidates"][0]["context"][0].update({"field": "close"}),
    )
    with pytest.raises(factory.MechanismFactoryError, match="context field"):
        factory.load_factory_contract(path)


def test_factory_rejects_unapproved_operator(tmp_path: Path):
    path = _write_variant(
        tmp_path,
        lambda raw: raw["candidates"][0]["entry"][0].update({"op": "cross_magic"}),
    )
    with pytest.raises(factory.MechanismFactoryError, match="field/operator"):
        factory.load_factory_contract(path)


def test_factory_rejects_peer_flag_mismatch(tmp_path: Path):
    path = _write_variant(
        tmp_path,
        lambda raw: raw["candidates"][8].update({"peer_required": False}),
    )
    with pytest.raises(factory.MechanismFactoryError, match="peer_required"):
        factory.load_factory_contract(path)


def test_contract_mutation_changes_digest(tmp_path: Path):
    base = factory.load_factory_contract()
    path = _write_variant(
        tmp_path,
        lambda raw: raw["candidates"][0].update({
            "hypothesis": raw["candidates"][0]["hypothesis"] + " Pre-registered extension."
        }),
    )
    changed = factory.load_factory_contract(path)
    ident = "factory_efficiency_midpoint_reclaim"
    assert changed[ident]["contract_digest"] != base[ident]["contract_digest"]


def test_factory_signal_requires_exact_digest_and_emits_boolean():
    specs = factory.load_factory_contract()
    ident = "factory_efficiency_midpoint_reclaim"
    frame = pd.DataFrame({
        "h4_up": [1, 1],
        "h1_vol_ok": [1, 1],
        "trend_efficiency_16": [0.6, 0.2],
        "trend_direction_16": [0.01, 0.01],
        "low": [99.0, 99.0],
        "close": [101.0, 101.0],
        "prior_range_mid": [100.0, 100.0],
        "open": [100.0, 100.0],
        "close_location": [0.8, 0.8],
        "rel_vol": [1.0, 1.0],
    })
    signal = factory.factory_signal(
        frame,
        ident,
        specs=specs,
        expected_contract_digest=specs[ident]["contract_digest"],
    )
    assert signal.dtype == bool
    assert signal.tolist() == [True, False]
    with pytest.raises(factory.MechanismFactoryError, match="digest mismatch"):
        factory.factory_signal(
            frame,
            ident,
            specs=specs,
            expected_contract_digest="0" * 64,
        )


def test_research_signal_uses_factory_contract_and_atr_gate():
    config = next(
        row for row in research.FRONTIER_CONFIGS
        if row["mechanism"] == "factory_efficiency_midpoint_reclaim"
    )
    frame = pd.DataFrame({
        "h4_up": [1, 1], "h1_vol_ok": [1, 1],
        "trend_efficiency_16": [0.6, 0.6], "trend_direction_16": [0.01, 0.01],
        "low": [99.0, 99.0], "close": [101.0, 101.0],
        "prior_range_mid": [100.0, 100.0], "open": [100.0, 100.0],
        "close_location": [0.8, 0.8], "rel_vol": [1.0, 1.0],
        "atr": [1.0, float("nan")],
    })
    assert research.signal_for(frame, config).tolist() == [True, False]
    bad = dict(config)
    bad["factory_contract_digest"] = "f" * 64
    with pytest.raises(research.CompositeResearchError, match="factory mechanism contract"):
        research.signal_for(frame, bad)


def test_factory_engine_never_evaluates_contract_as_python_code():
    source = Path("nexus_mechanism_factory.py").read_text(encoding="utf-8")
    assert "eval(" not in source
    assert "exec(" not in source
