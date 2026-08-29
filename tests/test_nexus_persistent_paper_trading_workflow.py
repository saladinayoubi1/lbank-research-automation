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


def test_public_bybit_collector_changes_retrigger_and_are_contract_tested() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count('"bybit_public_klines.py"') >= 2
    assert text.count('"tests/test_bybit_public_klines.py"') >= 2
    assert "tests/test_bybit_public_klines.py" in text.split(
        "Verify persistent Trading Engine contracts", 1
    )[1]


def test_network_eligible_runner_is_pinned_and_fail_closed() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    paper = text.split("  paper-loop:", 1)[1]
    assert "runs-on: nexus-bybit-network" in paper
    assert "vars.NEXUS_BYBIT_NETWORK_RUNNER_ENABLED" not in paper
    assert "ubuntu-latest" not in paper
    assert "Enforce eligible Bybit network execution plane" in paper
    assert "runner.environment" in paper
    assert "self-hosted" in paper
    assert "runner.os" in paper
    assert "Linux" in paper
    assert "bybit_network_execution_plane=self-hosted:nexus-bybit-network" in paper
    assert "proxy" not in paper.lower()
    assert "vpn" not in paper.lower()


def test_wsl1_node20_compatibility_exception_is_scoped_to_physical_paper_job() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    contract, paper = text.split("  paper-loop:", 1)

    # GitHub-hosted contract validation stays on the current Node-24 action pins.
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in contract
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in contract
    assert "ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION" not in contract

    # The physical WSL1 plane uses the immutable pre-Node24 pins recovered from
    # the repository's own pre-#1052 state. The opt-out must not escape this job.
    assert 'ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION: "true"' in paper
    assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in paper
    assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" in paper
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in paper
    assert "Node 24 Linux binaries fail with Exec format error on WSL1" in paper


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
        'assert isinstance(snapshot["regime_selected_rebalance_operational"], bool)',
        'assert isinstance(snapshot["performance_health_feedback_operational"], bool)',
        'assert isinstance(snapshot["strategy_discovery_health_trigger_requested"], bool)',
    ):
        assert marker in text


def test_persistent_loop_contract_suite_covers_full_lifecycle_risk_health_and_discovery() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for test_path in (
        "tests/test_bybit_public_klines.py",
        "tests/test_nexus_persistent_paper_trading_loop.py",
        "tests/test_nexus_regime_selected_position_rebalance.py",
        "tests/test_nexus_regime_selected_exposure_increase.py",
        "tests/test_nexus_strategy_discovery_health_trigger.py",
        "tests/test_nexus_demo_strategy_matrix.py",
        "tests/test_nexus_demo_paper_position_maintenance.py",
        "tests/test_nexus_demo_paper_lifecycle_persistence.py",
        "tests/test_nexus_paper_performance_pipeline.py",
        "tests/test_nexus_demo_regime_cycle.py",
        "tests/test_nexus_regime_paper_lane.py",
        "tests/test_nexus_regime_strategy_selector.py",
        "tests/test_nexus_regime_strategy_runtime.py",
        "tests/test_nexus_strategy_paper_supervisor.py",
        "tests/test_nexus_strategy_discovery_controller.py",
    ):
        assert test_path in text


def test_lifecycle_implementation_paths_retrigger_the_persistent_runtime() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for path in (
        '"bybit_public_klines.py"',
        '"nexus_regime_selected_position_rebalance.py"',
        '"nexus_regime_selected_exposure_increase.py"',
        '"nexus_strategy_discovery_health_trigger.py"',
    ):
        assert text.count(path) >= 2
