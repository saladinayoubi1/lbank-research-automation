"""Research-only v5 causal factory extension; preserve older novelty receipts."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import nexus_composite_strategy_research as research
import nexus_mechanism_factory as factory


def test_v5_is_additive_and_reviewed_without_rewriting_prior_generations():
    extension = research.REVIEWED_EXTENSION_SPECS
    assert set(extension) == {
        "factory_peer_lead_beta_failure_reclaim",
        "factory_entropy_volcluster_break",
    }
    assert len(research.FIXED_FACTORY_SPECS) == 12
    assert len(research.GENERATED_FACTORY_SPECS_V2) == 24
    assert len(research.GENERATED_FACTORY_SPECS_V3) == 36
    assert len(research.GENERATED_FACTORY_SPECS_V4) == 15
    assert set(extension).isdisjoint(research.FIXED_FACTORY_SPECS)
    assert set(extension).isdisjoint(research.GENERATED_FACTORY_SPECS)
    assert len({s["topology_digest"] for s in research.FACTORY_SPECS.values()}) == len(
        research.FACTORY_SPECS
    )
    assert research.PEER_MECHANISMS & set(extension) == {
        "factory_peer_lead_beta_failure_reclaim"
    }
    assert research.FRONTIER_CONFIGS[-2:] == factory.factory_configs(extension)
    assert all(
        config["risk_variant"] == 0
        and config["entry_model"] == "closed_4h_1h_15m_next_open"
        and config["factory_contract_digest"] == extension[config["mechanism"]]["contract_digest"]
        for config in research.FRONTIER_CONFIGS[-2:]
    )


def test_exact_historical_exhaustion_routes_only_new_contracts_without_cursor_reset():
    ledger = research.empty_ledger()
    ledger["mechanisms_evaluated"] = list(research.MECHANISMS)
    ledger["frontier_screened_mechanisms"] = [
        ident for ident in research.FRONTIER_MECHANISMS
        if ident not in research.REVIEWED_EXTENSION_MECHANISMS
    ]
    choices = research._frontier_configs_to_screen(ledger)
    assert {choice["mechanism"] for choice in choices} == set(
        research.REVIEWED_EXTENSION_MECHANISMS
    )
    assert research.research_mode(ledger) == "frontier_tournament"
    assert research.FIXED_FACTORY_MECHANISMS == tuple(research.FIXED_FACTORY_SPECS)
    assert not any(c["mechanism"] in ledger["frontier_screened_mechanisms"] for c in choices)


def test_peer_lead_residual_reclaim_has_exact_source_bound_long_flat_signal():
    ident = "factory_peer_lead_beta_failure_reclaim"
    spec = research.REVIEWED_EXTENSION_SPECS[ident]
    frame = pd.DataFrame({
        "h4_range": [1, 1, 1],
        "h1_vol_ok": [1, 1, 1],
        "lagged_peer_lead_corr_96": [0.35, np.nan, 0.35],
        "peer_beta_lagged": [0.5, 0.5, 0.5],
        "lagged_peer_beta_residual": [-0.031, -0.031, -0.031],
        "peer_beta_residual_scale": [0.02, 0.02, 0.02],
        "lagged_directional_entropy_64": [0.9, 0.9, 0.9],
        "low": [98.0, 98.0, 100.0],
        "prior_lo": [99.0, 99.0, 99.0],
        "close": [101.0, 101.0, 101.0],
        "open": [100.0, 100.0, 100.0],
        "close_location": [0.8, 0.8, 0.8],
        "rel_vol": [1.0, 1.0, 1.0],
    })
    signals = factory.factory_signal(
        frame, ident, specs=research.FACTORY_SPECS,
        expected_contract_digest=spec["contract_digest"],
    )
    assert signals.dtype == bool
    assert signals.tolist() == [True, False, False]
    with pytest.raises(factory.MechanismFactoryError, match="digest mismatch"):
        factory.factory_signal(
            frame, ident, specs=research.FACTORY_SPECS,
            expected_contract_digest="0" * 64,
        )
    with pytest.raises(factory.MechanismFactoryError, match="feature missing"):
        factory.factory_signal(
            frame.drop(columns=["lagged_peer_lead_corr_96"]), ident,
            specs=research.FACTORY_SPECS,
            expected_contract_digest=spec["contract_digest"],
        )


def test_volatility_entropy_break_is_distinct_and_fail_closed_on_missing_history():
    ident = "factory_entropy_volcluster_break"
    spec = research.REVIEWED_EXTENSION_SPECS[ident]
    frame = pd.DataFrame({
        "h4_up": [1, 1, 1],
        "h1_vol_ok": [1, 1, 1],
        "lagged_directional_entropy_64": [0.48, 0.72, 0.48],
        "lagged_abs_return_autocorr_48": [0.3, 0.3, 0.3],
        "lagged_volume_return_corr_64": [0.22, 0.22, np.nan],
        "close": [101.0, 101.0, 101.0],
        "prior_hi": [100.0, 100.0, 100.0],
        "open": [100.0, 100.0, 100.0],
        "close_location": [0.8, 0.8, 0.8],
        "rel_vol": [1.4, 1.4, 1.4],
    })
    assert factory.factory_signal(
        frame, ident, specs=research.FACTORY_SPECS,
        expected_contract_digest=spec["contract_digest"],
    ).tolist() == [True, False, False]


def test_extension_refuses_tampering_and_remains_research_only(tmp_path: Path):
    original = Path(__file__).resolve().parents[1] / "research" / "mechanism_factory_v5.json"
    payload = json.loads(original.read_text(encoding="utf-8"))
    assert payload["selection_basis"] == "training_partition_only"
    assert payload["no_minimum_trade_count_gate"] is True
    assert payload["auto_demo_promotion"] is False
    assert payload["live_trading_authority"] is False
    payload["candidates"][0]["context"][2]["field"] = "current_peer_return"
    copy = tmp_path / "tampered.json"
    copy.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(factory.MechanismFactoryError, match="context field"):
        factory.load_factory_contract(copy)
