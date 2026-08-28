from __future__ import annotations

from copy import deepcopy

import nexus_demo_regime_lifecycle_replay as replay_mod
import nexus_regime_selected_exposure_increase as increase_mod
import nexus_regime_selected_position_rebalance as rebalance_mod


SOURCE_SHA = "a" * 40


def _valid_snapshot() -> dict:
    core = {
        "schema_version": replay_mod.SCHEMA,
        "source_sha": SOURCE_SHA,
        "archive_sha256": replay_mod.ARCHIVE_SHA256,
        "regime_cycle_digest": "1" * 64,
        "rebalance_digest": "2" * 64,
        "increase_digest": "3" * 64,
        "risk_reducing_rebalance_operational": True,
        "exposure_increase_operational": True,
        "fresh_deterministic_risk_required": True,
        "unauthorized_exposure_increase": False,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }
    return {**core, "replay_digest": replay_mod._digest(core)}


def test_archive_fetch_scope_binds_both_lifecycle_bridges_and_restores() -> None:
    previous_rebalance = rebalance_mod.fetch_bind_bybit_dataset
    previous_increase = increase_mod.fetch_bind_bybit_dataset

    def archive_fetcher(**_kwargs):
        return {"archive": True}

    with replay_mod._archive_fetch_scope(archive_fetcher):
        assert rebalance_mod.fetch_bind_bybit_dataset is archive_fetcher
        assert increase_mod.fetch_bind_bybit_dataset is archive_fetcher

    assert rebalance_mod.fetch_bind_bybit_dataset is previous_rebalance
    assert increase_mod.fetch_bind_bybit_dataset is previous_increase


def test_archive_fetch_scope_restores_after_failure() -> None:
    previous_rebalance = rebalance_mod.fetch_bind_bybit_dataset
    previous_increase = increase_mod.fetch_bind_bybit_dataset

    def archive_fetcher(**_kwargs):
        return {"archive": True}

    try:
        with replay_mod._archive_fetch_scope(archive_fetcher):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert rebalance_mod.fetch_bind_bybit_dataset is previous_rebalance
    assert increase_mod.fetch_bind_bybit_dataset is previous_increase


def test_lifecycle_replay_verifier_rejects_authority_or_digest_tamper() -> None:
    snapshot = _valid_snapshot()
    assert replay_mod.verify_demo_regime_lifecycle_replay(snapshot)["decision"] == "pass"

    widened = deepcopy(snapshot)
    widened["live_trading_authority"] = True
    unsigned = dict(widened)
    unsigned.pop("replay_digest")
    widened["replay_digest"] = replay_mod._digest(unsigned)
    assert replay_mod.verify_demo_regime_lifecycle_replay(widened)["decision"] == "reject"

    tampered = deepcopy(snapshot)
    tampered["increase_digest"] = "f" * 64
    assert replay_mod.verify_demo_regime_lifecycle_replay(tampered)["decision"] == "reject"


def test_lifecycle_replay_verifier_rejects_unauthorized_increase_claim() -> None:
    snapshot = _valid_snapshot()
    snapshot["unauthorized_exposure_increase"] = True
    unsigned = dict(snapshot)
    unsigned.pop("replay_digest")
    snapshot["replay_digest"] = replay_mod._digest(unsigned)
    assert replay_mod.verify_demo_regime_lifecycle_replay(snapshot)["decision"] == "reject"
