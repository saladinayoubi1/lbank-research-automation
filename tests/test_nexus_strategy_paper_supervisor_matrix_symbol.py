from __future__ import annotations

from pathlib import Path

import pytest

from nexus_strategy_paper_supervisor import StrategyPaperSupervisorError, run_once


def test_eth_matrix_cell_uses_eth_canonical_dataset_binding(tmp_path: Path) -> None:
    captured = {}

    def stop_after_capture(**kwargs):
        captured.update(kwargs)
        raise OSError("stop after canonical binding capture")

    with pytest.raises(StrategyPaperSupervisorError, match="dataset unavailable"):
        run_once(
            source_sha="a" * 40,
            state_root=tmp_path,
            symbol="ethusdt",
            timeframe="hour1",
            families=("momentum",),
            now_ms=1_800_000_000_000,
            dataset_fetcher=stop_after_capture,
        )
    assert captured["canonical_symbol"] == "ETH/USDT"
    assert captured["source_symbol"] == "ETHUSDT"
    assert captured["interval"] == "60"
    step_ms = 3_600_000
    expected_end = ((1_800_000_000_000 - step_ms) // step_ms) * step_ms
    assert captured["end_time_ms"] == expected_end
    assert captured["start_time_ms"] == expected_end - 239 * step_ms
    assert captured["end_time_ms"] + step_ms - 1 < captured["now_ms"]


def test_unknown_matrix_symbol_fails_before_market_fetch(tmp_path: Path) -> None:
    called = False

    def fetcher(**_kwargs):
        nonlocal called
        called = True

    with pytest.raises(
        StrategyPaperSupervisorError,
        match="unsupported or non-canonical matrix symbol/timeframe",
    ):
        run_once(
            source_sha="a" * 40,
            state_root=tmp_path,
            symbol="DOGEUSDT",
            timeframe="minute15",
            families=("momentum",),
            now_ms=1_800_000_000_000,
            dataset_fetcher=fetcher,
        )
    assert called is False
