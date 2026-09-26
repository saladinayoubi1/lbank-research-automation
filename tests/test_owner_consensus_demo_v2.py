import json
from copy import deepcopy

import pandas as pd
import pytest

import nexus_owner_consensus_demo_v2 as demo

NOW = pd.Timestamp("2026-09-26T17:00:00Z")
SHA = "a"*40


def test_new_authorized_lane_preserves_old_contract_and_starts_in_future():
    before = demo.OLD_MANIFEST.read_bytes()
    config, frozen = demo.make_config(NOW)
    assert config["start_not_before_utc"] == "2026-09-26T20:00:00Z"
    assert frozen["strategy_id"] == "bybit_btc_eth_regime_consensus_v1"
    assert demo.OLD_MANIFEST.read_bytes() == before
    old = json.loads(before)
    for name in config["execution_profiles"]:
        assert config["execution_profiles"][name]["initial_cash"] == 500
        assert config["completion_gates"][name]["minimum_fill_count"] == 0
        assert old["completion_gates"][name]["minimum_fill_count"] == 4
    assert config["authority"]["live_trading_enabled"] is False


def test_activation_resumes_without_reset_and_rejects_contract_tampering(tmp_path):
    first = demo.initialize(tmp_path, SHA, NOW)
    assert demo.initialize(tmp_path, SHA, NOW+pd.Timedelta(days=2)) == first
    first["config"]["execution_profiles"]["conservative"]["initial_cash"] = 999
    (tmp_path / "activation.json").write_text(json.dumps(first))
    with pytest.raises(ValueError, match="contract changed"):
        demo.initialize(tmp_path, SHA, NOW)


def test_lost_state_cannot_reset_capital(tmp_path):
    demo.initialize(tmp_path, SHA, NOW)
    (tmp_path / "state.json").unlink()
    with pytest.raises(ValueError, match="refusing capital reset"):
        demo.initialize(tmp_path, SHA, NOW)


def test_waits_for_genuine_future_bar_and_never_forces_a_trade(tmp_path, monkeypatch):
    activation = demo.initialize(tmp_path, SHA, NOW)
    monkeypatch.setattr(demo.forward, "collect_observations",
                        lambda *a, **k: pytest.fail("future data requested"))
    result = demo.tick(tmp_path, activation, NOW)
    assert result["status"] == "waiting_for_closed_bar"
    assert result["completed_bars"] == 0
    assert result["profiles"]["conservative"]["wallet"] == 500
    assert result["profiles"]["conservative"]["fill_count"] == 0


def test_risk_halt_prevents_further_collection(tmp_path, monkeypatch):
    activation = demo.initialize(tmp_path, SHA, NOW)
    state = json.loads((tmp_path / "state.json").read_text())
    state["profiles"]["conservative"]["maximum_drawdown"] = .16
    core = deepcopy(state)
    core.pop("state_digest")
    state["state_digest"] = demo.forward._digest(core)
    demo.forward.save_state(tmp_path / "state.json", state)
    monkeypatch.setattr(demo.forward, "collect_observations",
                        lambda *a, **k: pytest.fail("risk-halted lane fetched data"))
    result = demo.tick(tmp_path, activation, NOW+pd.Timedelta(days=1))
    assert result["status"] == "risk_halted"


def test_single_writer(tmp_path):
    with demo.writer_lock(tmp_path):
        with pytest.raises(OSError):
            with demo.writer_lock(tmp_path):
                pass
