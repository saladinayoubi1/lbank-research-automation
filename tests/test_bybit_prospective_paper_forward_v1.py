from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

import bybit_prospective_paper_forward_v1 as forward


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments/bybit_prospective_paper_forward_v1.json"
ENGINE_SHA = "a" * 64
SOURCE_SHA = "b" * 40


def observation(
    execution_utc: str = "2026-08-26T04:00:00Z",
    *,
    target_changed: bool = True,
) -> dict[str, object]:
    specs = [
        {
            "symbol": symbol,
            "tick_size": 0.1,
            "quantity_step": 0.001,
            "minimum_quantity": 0.001,
            "minimum_notional": 5.0,
            "maximum_market_quantity": 100.0,
            "maximum_leverage": 100.0,
            "funding_interval_minutes": 480,
        }
        for symbol in forward.SYMBOLS
    ]
    tier = {
        "risk_limit_value": 1_000_000.0,
        "maintenance_margin_rate": 0.005,
        "initial_margin_rate": 0.01,
        "maintenance_margin_deduction": 0.0,
        "maximum_leverage": 100.0,
    }
    minute_windows = {
        symbol: {
            "conservative": [{"volume": 100.0, "turnover": 1_000_000.0}],
            "stress": [{"volume": 100.0, "turnover": 1_000_000.0}],
        }
        for symbol in forward.SYMBOLS
    }
    return {
        "execution_utc": execution_utc,
        "signal_close_utc": execution_utc,
        "target_weights": [0.1, -0.1] if target_changed else [0.0, 0.0],
        "target_changed": target_changed,
        "trade": [{"open": 10_000.0, "close": 10_100.0}] * 2,
        "mark": [
            {"open": 10_000.0, "high": 10_200.0, "low": 9_900.0, "close": 10_100.0}
        ] * 2,
        "funding_rates": [[], []],
        "expected_funding_events": [0, 0],
        "minute_windows": minute_windows if target_changed else {},
        "instrument_specs": specs,
        "risk_tiers": [[tier], [tier]],
        "public_data_only": True,
    }


def test_contract_binds_frozen_strategy_and_paper_only_authority() -> None:
    config, frozen = forward.load_contract(MANIFEST)

    assert config["strategy_id"] == "bybit_btc_eth_regime_consensus_v1"
    assert frozen["strategy_id"] == config["strategy_id"]
    assert config["authority"] == {
        "paper_only": True,
        "live_trading_enabled": False,
        "private_credentials_allowed": False,
        "automatic_live_promotion": False,
    }


def test_workflow_uses_redundant_polling_without_parallel_state_writers() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "bybit_prospective_paper_forward_v1.yml"
    ).read_text(encoding="utf-8")
    assert 'cron: "17 */2 * * *"' in workflow
    assert 'cron: "17 */4 * * *"' not in workflow
    assert "group: bybit-prospective-paper-forward-v1" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "advances only previously unseen closed bars" in workflow


def test_frozen_manifest_digest_is_newline_portable(tmp_path: Path) -> None:
    lf = tmp_path / "manifest-lf.json"
    crlf = tmp_path / "manifest-crlf.json"
    content = '{\n  "strategy_id": "portable"\n}\n'
    lf.write_bytes(content.encode("utf-8"))
    crlf.write_bytes(content.replace("\n", "\r\n").encode("utf-8"))

    assert forward._file_sha(lf) == forward._file_sha(crlf)  # noqa: SLF001


def test_state_and_event_digest_chain_survive_one_paper_bar() -> None:
    config, _ = forward.load_contract(MANIFEST)
    state = forward.new_state(
        config, engine_sha256=ENGINE_SHA, source_sha=SOURCE_SHA, run_id=0
    )

    updated = forward.apply_observations(
        state, [observation()], config, source_sha=SOURCE_SHA, run_id=1
    )

    forward.verify_state(updated, config, ENGINE_SHA)
    assert updated["completed_bar_count"] == 1
    assert updated["status"] == "COLLECTING"
    assert updated["paper_only"] is True
    assert updated["live_trading_enabled"] is False
    assert len(updated["events"]) == 1
    assert updated["events"][0]["previous_event_digest"] == "0" * 64
    assert all(profile["fill_count"] == 2 for profile in updated["profiles"].values())


def test_state_tampering_and_engine_change_fail_closed() -> None:
    config, _ = forward.load_contract(MANIFEST)
    state = forward.new_state(
        config, engine_sha256=ENGINE_SHA, source_sha=SOURCE_SHA, run_id=0
    )

    tampered = deepcopy(state)
    tampered["live_trading_enabled"] = True
    with pytest.raises(forward.ProspectivePaperError, match="digest mismatch"):
        forward.verify_state(tampered, config, ENGINE_SHA)
    with pytest.raises(forward.ProspectivePaperError, match="contract rejected"):
        forward.verify_state(state, config, "c" * 64)

    updated = forward.apply_observations(
        state, [observation()], config, source_sha=SOURCE_SHA, run_id=1
    )
    inconsistent = deepcopy(updated)
    inconsistent["events"] = []
    unsigned = dict(inconsistent)
    unsigned.pop("state_digest")
    inconsistent["state_digest"] = forward._digest(unsigned)  # noqa: SLF001
    with pytest.raises(forward.ProspectivePaperError, match="event count"):
        forward.verify_state(inconsistent, config, ENGINE_SHA)


def test_pre_cutoff_out_of_order_and_reused_run_id_are_rejected() -> None:
    config, _ = forward.load_contract(MANIFEST)
    state = forward.new_state(
        config, engine_sha256=ENGINE_SHA, source_sha=SOURCE_SHA, run_id=0
    )

    with pytest.raises(forward.ProspectivePaperError, match="pre-cutoff"):
        forward.apply_observations(
            state,
            [observation("2026-08-25T20:00:00Z")],
            config,
            source_sha=SOURCE_SHA,
            run_id=1,
        )

    updated = forward.apply_observations(
        state, [observation()], config, source_sha=SOURCE_SHA, run_id=1
    )
    with pytest.raises(forward.ProspectivePaperError, match="run ID"):
        forward.apply_observations(
            updated, [], config, source_sha=SOURCE_SHA, run_id=1
        )
    with pytest.raises(forward.ProspectivePaperError, match="strictly increasing"):
        forward.apply_observations(
            updated, [observation()], config, source_sha=SOURCE_SHA, run_id=2
        )


def test_collection_before_first_prospective_bar_initializes_without_market_calls() -> None:
    config, frozen = forward.load_contract(MANIFEST)
    state = forward.new_state(
        config, engine_sha256=ENGINE_SHA, source_sha=SOURCE_SHA, run_id=0
    )

    class UnexpectedClient:
        def get(self, _path: str, _params: dict[str, object]) -> dict[str, object]:
            raise AssertionError("pre-cutoff initialization must not query market data")

    assert forward.collect_observations(
        config,
        frozen,
        state,
        now_utc="2026-08-25T22:11:00Z",
        client=UnexpectedClient(),  # type: ignore[arg-type]
    ) == []


def test_completed_forward_requires_review_and_never_enables_live() -> None:
    config, _ = forward.load_contract(MANIFEST)
    config = deepcopy(config)
    config["minimum_observation_days"] = 0
    config["minimum_completed_bars"] = 1
    for gate in config["completion_gates"].values():
        gate["minimum_total_return"] = -1.0
        gate["maximum_drawdown"] = 1.0
        gate["minimum_fill_count"] = 0
        gate["minimum_asset_fill_count"] = 0
        gate["minimum_funding_coverage"] = 0.0
        gate["minimum_execution_coverage"] = 0.0
        gate["maximum_margin_utilization"] = 1.0
        gate["maximum_risk_tier_utilization"] = 1.0
    state = forward.new_state(
        config, engine_sha256=ENGINE_SHA, source_sha=SOURCE_SHA, run_id=0
    )

    updated = forward.apply_observations(
        state,
        [observation(target_changed=False)],
        config,
        source_sha=SOURCE_SHA,
        run_id=1,
    )

    assert updated["status"] == "COMPLETE_REVIEW_REQUIRED"
    assert updated["decision"] == "paper_forward_passed_requires_separate_owner_review"
    assert updated["automatic_live_promotion"] is False
    assert updated["live_trading_enabled"] is False


def test_mark_price_rows_do_not_require_volume_columns() -> None:
    class FakeClient:
        def get(self, _path: str, _params: dict[str, object]) -> dict[str, object]:
            return {
                "result": {
                    "list": [["1787692800000", "100", "101", "99", "100.5"]]
                }
            }

    frame = forward._fetch_klines(  # noqa: SLF001 - focused parser contract test
        FakeClient(),  # type: ignore[arg-type]
        category="linear",
        endpoint="/v5/market/mark-price-kline",
        symbol="BTCUSDT",
        start_ms=1787692800000,
        end_ms=1787707200000,
    )

    assert list(frame.columns) == ["timestamp", "open", "high", "low", "close"]


def test_incomplete_public_grid_and_execution_window_fail_closed() -> None:
    incomplete = pd.DataFrame({
        "timestamp": pd.to_datetime(
            ["2026-08-26T00:00:00Z", "2026-08-26T08:00:00Z"], utc=True
        )
    })
    with pytest.raises(forward.ProspectivePaperError, match="incomplete"):
        forward._require_complete_grid(  # noqa: SLF001
            incomplete,
            start_ms=1787702400000,
            end_ms=1787745600000,
            label="test",
        )

    class PartialMinuteClient:
        def get(self, _path: str, params: dict[str, object]) -> dict[str, object]:
            start = int(params["start"])
            return {
                "result": {
                    "list": [[str(start), "1", "1", "1", "1", "1", "1"]]
                }
            }

    assert forward._minute_window(  # noqa: SLF001
        PartialMinuteClient(),  # type: ignore[arg-type]
        "BTCUSDT",
        pd.Timestamp("2026-08-26T04:00:00Z"),
        3,
    ) == []


def test_order_above_exchange_risk_limit_is_rejected() -> None:
    config, _ = forward.load_contract(MANIFEST)
    state = forward.new_state(
        config, engine_sha256=ENGINE_SHA, source_sha=SOURCE_SHA, run_id=0
    )
    row = observation()
    for group in row["risk_tiers"]:  # type: ignore[union-attr]
        group[0]["risk_limit_value"] = 1.0

    updated = forward.apply_observations(
        state, [row], config, source_sha=SOURCE_SHA, run_id=1
    )

    assert all(
        profile["margin_rejections"] == 2
        and profile["fill_count"] == 0
        and profile["positions"] == [
            {"quantity": 0.0, "average_entry": 0.0},
            {"quantity": 0.0, "average_entry": 0.0},
        ]
        for profile in updated["profiles"].values()
    )
