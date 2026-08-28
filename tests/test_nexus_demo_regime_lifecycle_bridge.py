from __future__ import annotations

from pathlib import Path

import pytest

import nexus_demo_regime_lifecycle_bridge as bridge
import nexus_regime_selected_exposure_increase as increase_module
import nexus_regime_selected_position_rebalance as rebalance_module


SOURCE_SHA = "1" * 40


def _regime() -> dict:
    return {
        "source_sha": SOURCE_SHA,
        "archive_sha256": bridge.ARCHIVE_SHA256,
        "cycle_digest": "a" * 64,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }


def test_archive_binding_is_scoped_and_restored_on_exception():
    prior_rebalance = rebalance_module.fetch_bind_bybit_dataset
    prior_increase = increase_module.fetch_bind_bybit_dataset

    def archive_fetcher(**_kwargs):
        return {}

    with pytest.raises(RuntimeError, match="boom"):
        with bridge.bind_verified_archive_research(archive_fetcher):
            assert rebalance_module.fetch_bind_bybit_dataset is archive_fetcher
            assert increase_module.fetch_bind_bybit_dataset is archive_fetcher
            raise RuntimeError("boom")

    assert rebalance_module.fetch_bind_bybit_dataset is prior_rebalance
    assert increase_module.fetch_bind_bybit_dataset is prior_increase


def test_demo_lifecycle_reuses_existing_bridges_and_restores_network_fetchers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    prior_rebalance = rebalance_module.fetch_bind_bybit_dataset
    prior_increase = increase_module.fetch_bind_bybit_dataset

    def archive_fetcher(**_kwargs):
        return {"verified": True}

    monkeypatch.setattr(
        bridge,
        "build_archive_dataset_fetcher",
        lambda *_args, **_kwargs: archive_fetcher,
    )
    monkeypatch.setattr(bridge, "verify_cycle_snapshot", lambda _value: {"decision": "pass"})
    monkeypatch.setattr(
        bridge,
        "verify_regime_selected_rebalance",
        lambda _value: {"decision": "pass"},
    )
    monkeypatch.setattr(
        bridge,
        "verify_regime_selected_exposure_increase",
        lambda _value: {"decision": "pass"},
    )

    def fake_rebalance(**_kwargs):
        assert rebalance_module.fetch_bind_bybit_dataset is archive_fetcher
        assert increase_module.fetch_bind_bybit_dataset is archive_fetcher
        return {
            "rebalance_digest": "b" * 64,
            "risk_reducing_rebalance_operational": True,
            "exposure_increased": False,
        }

    def fake_increase(**_kwargs):
        assert rebalance_module.fetch_bind_bybit_dataset is archive_fetcher
        assert increase_module.fetch_bind_bybit_dataset is archive_fetcher
        return {
            "increase_digest": "c" * 64,
            "exposure_increase_operational": True,
            "fresh_deterministic_risk_required": True,
            "unauthorized_exposure_increase": False,
        }

    monkeypatch.setattr(bridge, "run_regime_selected_rebalance", fake_rebalance)
    monkeypatch.setattr(bridge, "run_regime_selected_exposure_increase", fake_increase)

    result = bridge.run_demo_regime_lifecycle(
        manifest={"symbols": ["BTCUSDT", "ETHUSDT"]},
        state_root=tmp_path,
        source_sha=SOURCE_SHA,
        regime_snapshot=_regime(),
        archive_root=tmp_path / "archive",
        archive_sha256=bridge.ARCHIVE_SHA256,
    )

    assert bridge.verify_demo_regime_lifecycle(result)["decision"] == "pass"
    assert result["regime_selected_rebalance_operational"] is True
    assert result["parallel_execution_engine_created"] is False
    assert rebalance_module.fetch_bind_bybit_dataset is prior_rebalance
    assert increase_module.fetch_bind_bybit_dataset is prior_increase
    assert (tmp_path / "demo" / "regime-lifecycle-bridge.json").is_file()


def test_demo_lifecycle_rejects_nonapproved_archive(tmp_path: Path):
    with pytest.raises(bridge.DemoRegimeLifecycleBridgeError, match="approved immutable"):
        bridge.run_demo_regime_lifecycle(
            manifest={},
            state_root=tmp_path,
            source_sha=SOURCE_SHA,
            regime_snapshot=_regime(),
            archive_root=tmp_path,
            archive_sha256="0" * 64,
        )
