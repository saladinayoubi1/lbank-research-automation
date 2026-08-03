from __future__ import annotations

import json

import pandas as pd
import pytest

import benchmark_v1


def test_buy_and_hold_targets_are_fully_long():
    frame = pd.DataFrame({"close": [1, 2, 3]})
    targets = benchmark_v1.build_target_exposures(
        frame, {"strategy_id": "buy_and_hold", "parameters": {}}
    )
    assert targets.tolist() == [1.0, 1.0, 1.0]


def test_sma_targets_are_long_only_after_warmup():
    frame = pd.DataFrame({"close": [1, 2, 3, 4, 5, 6]})
    targets = benchmark_v1.build_target_exposures(
        frame,
        {
            "strategy_id": "sma_long_flat",
            "parameters": {"fast_window": 2, "slow_window": 3},
        },
    )
    assert targets.iloc[:2].tolist() == [0.0, 0.0]
    assert targets.iloc[2:].tolist() == [1.0, 1.0, 1.0, 1.0]


def test_sma_rejects_invalid_windows():
    frame = pd.DataFrame({"close": [1, 2, 3]})
    with pytest.raises(benchmark_v1.BenchmarkError, match="fast < slow"):
        benchmark_v1.build_target_exposures(
            frame,
            {
                "strategy_id": "sma_long_flat",
                "parameters": {"fast_window": 3, "slow_window": 3},
            },
        )


def test_unknown_strategy_is_rejected():
    with pytest.raises(benchmark_v1.BenchmarkError, match="Unsupported strategy"):
        benchmark_v1.build_target_exposures(
            pd.DataFrame({"close": [1]}), {"strategy_id": "unknown"}
        )


def test_suitability_fails_on_low_venue_coverage():
    summary = {
        "overall_ready_ratio": 4 / 21,
        "selected_series_found": 4,
        "selected_series_ready": 4,
        "selected_series": 4,
        "total_duplicate_timestamps": 0,
        "total_off_grid_timestamps": 0,
    }
    policy = {
        "minimum_overall_ready_ratio": 0.8,
        "require_all_selected_series_ready": True,
        "require_all_benchmark_runs_successful": True,
        "maximum_total_duplicate_timestamps": 0,
        "maximum_total_off_grid_timestamps": 0,
        "next_venue_on_failure": "bybit",
    }
    decision = benchmark_v1.evaluate_suitability(summary, 16, 16, policy)
    assert decision["suitable_as_primary_research_venue"] is False
    assert decision["next_venue"] == "bybit"
    assert decision["failed_checks"] == ["overall_ready_ratio"]
    assert decision["profitability_used_as_venue_criterion"] is False


def test_suitability_passes_when_all_predeclared_checks_pass():
    summary = {
        "overall_ready_ratio": 0.9,
        "selected_series_found": 4,
        "selected_series_ready": 4,
        "selected_series": 4,
        "total_duplicate_timestamps": 0,
        "total_off_grid_timestamps": 0,
    }
    policy = {
        "minimum_overall_ready_ratio": 0.8,
        "require_all_selected_series_ready": True,
        "require_all_benchmark_runs_successful": True,
        "maximum_total_duplicate_timestamps": 0,
        "maximum_total_off_grid_timestamps": 0,
        "next_venue_on_failure": "bybit",
    }
    decision = benchmark_v1.evaluate_suitability(summary, 16, 16, policy)
    assert decision["suitable_as_primary_research_venue"] is True
    assert decision["decision"] == "retain_lbank"
    assert decision["next_venue"] is None


def test_risk_metrics_are_finite_for_growing_equity():
    curve = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=5, freq="4h", tz="UTC"),
            "equity": [10000, 10100, 10050, 10200, 10300],
        }
    )
    metrics = benchmark_v1.calculate_risk_metrics(curve, "hour4", 10000)
    assert metrics["annualized_return"] is not None
    assert metrics["annualized_volatility"] is not None
    assert metrics["sharpe_like_zero_rate"] is not None


def test_load_manifest_requires_supported_schema(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
    with pytest.raises(benchmark_v1.BenchmarkError, match="missing keys"):
        benchmark_v1.load_manifest(path)


def test_render_markdown_handles_failed_run():
    report = {
        "experiment_id": "test",
        "generated_at_utc": "2026-08-03T00:00:00+00:00",
        "manifest_sha256": "abc",
        "dataset_summary": {
            "total_series": 1,
            "ready_series": 0,
            "overall_ready_ratio": 0.0,
            "selected_series_ready": 0,
            "selected_series": 1,
            "total_missing_candles": 1,
            "total_duplicate_timestamps": 0,
            "total_off_grid_timestamps": 0,
        },
        "benchmark_summary": {"expected_runs": 1, "successful_runs": 0, "failed_runs": 1},
        "suitability": {
            "suitable_as_primary_research_venue": False,
            "decision": "evaluate_secondary_venue",
            "next_venue": "bybit",
            "failed_checks": ["overall_ready_ratio"],
        },
        "runs": [{
            "symbol": "btc_usdt",
            "timeframe": "minute15",
            "strategy_id": "buy_and_hold",
            "profile_id": "frictionless",
            "success": False,
            "error": "blocked",
        }],
    }
    markdown = benchmark_v1.render_markdown(report)
    assert "evaluate_secondary_venue" in markdown
    assert "blocked" in markdown


def test_write_report_creates_four_files(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    report = {
        "experiment_id": "test",
        "generated_at_utc": "2026-08-03T00:00:00+00:00",
        "manifest_sha256": "abc",
        "dataset_summary": {
            "total_series": 0,
            "ready_series": 0,
            "overall_ready_ratio": 0.0,
            "selected_series_ready": 0,
            "selected_series": 0,
            "total_missing_candles": 0,
            "total_duplicate_timestamps": 0,
            "total_off_grid_timestamps": 0,
        },
        "benchmark_summary": {"expected_runs": 0, "successful_runs": 0, "failed_runs": 0},
        "suitability": {
            "suitable_as_primary_research_venue": False,
            "decision": "evaluate_secondary_venue",
            "next_venue": "bybit",
            "failed_checks": ["overall_ready_ratio"],
        },
        "runs": [],
    }
    output = tmp_path / "output"
    benchmark_v1.write_report(report, manifest, output, clean=True)
    assert {path.name for path in output.iterdir()} == {
        "_benchmark.json",
        "_benchmark.md",
        "_benchmark_runs.csv",
        "_experiment_manifest.json",
    }
