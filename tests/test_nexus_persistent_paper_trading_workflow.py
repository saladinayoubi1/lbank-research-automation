from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_persistent_paper_trading_loop.yml")


def test_persistent_loop_runs_on_closed_candle_cadence_and_restores_state() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'cron: "7,22,37,52 * * * *"' in text
    assert "workflow_dispatch:" in text
    assert "STATE_ARTIFACT: nexus-persistent-paper-trading-state" in text
    assert "Restore newest persistent Paper state" in text
    assert "actions/artifacts?name=$STATE_ARTIFACT" in text
    assert "Advance public closed-candle Paper portfolio loop" in text
    assert "python nexus_persistent_paper_trading_loop.py" in text
    assert "nexus-persistent-paper-trading-state" in text
    assert "if: always()" in text


def test_persistent_loop_is_public_data_not_historical_archive_replay() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "8867026863",
        "5f1173467c2296201940c3b7786b7cc3e5442244e07289769ab4867ace41d668",
        "BYBIT_full_history_2022-12-01_to_2026-07-31.zip",
        "--replay-archive-root",
        "--archive-sha256",
        "NEXUS_OFFLINE_COURIER_KEY",
    ):
        assert forbidden not in text
    assert 'assert snapshot["data_mode"] == "public_bybit_closed_candles"' in text


def test_persistent_loop_permissions_are_read_only_and_authority_is_fail_closed() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    permission_block = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in permission_block
    assert "actions: read" in permission_block
    assert "write" not in permission_block
    for marker in (
        'assert snapshot["paper_only"] is True',
        'assert snapshot["live_trading_authority"] is False',
        'assert snapshot["private_credentials_used"] is False',
        'assert snapshot["automatic_strategy_promotion"] is False',
        'assert snapshot["deterministic_risk_final_authority"] is True',
        'assert snapshot["trading_engine_complete"] is False',
    ):
        assert marker in text


def test_persistent_loop_contract_suite_covers_selection_risk_paper_and_discovery() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for test_path in (
        "tests/test_nexus_persistent_paper_trading_loop.py",
        "tests/test_nexus_demo_strategy_matrix.py",
        "tests/test_nexus_demo_paper_position_maintenance.py",
        "tests/test_nexus_demo_paper_performance_refresh.py",
        "tests/test_nexus_demo_regime_cycle.py",
        "tests/test_nexus_regime_paper_lane.py",
        "tests/test_nexus_regime_strategy_selector.py",
        "tests/test_nexus_regime_strategy_runtime.py",
        "tests/test_nexus_strategy_paper_supervisor.py",
        "tests/test_nexus_strategy_discovery_controller.py",
    ):
        assert test_path in text
