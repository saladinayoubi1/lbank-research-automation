import json
from pathlib import Path

import pandas as pd
import pytest

from phase6_research_pipeline import bind_bybit_closed_dataset
from scripts import nexus_monthly_archive_matrix as monthly


def public_fixture(**kwargs):
    step = 3_600_000
    first, end = kwargs["start_time_ms"], kwargs["end_time_ms"]+step
    rows = []
    for i, ms in enumerate(range(first, end, step)):
        price = 100+i/10
        rows.append({"source": "Bybit", "market_type": "spot", "symbol": "BTCUSDT",
                     "interval": "60", "closed": True, "open_time_ms": ms,
                     "open": str(price), "high": str(price+1), "low": str(price-1),
                     "close": str(price+0.5), "volume": "100"})
    return bind_bybit_closed_dataset(rows, canonical_symbol="BTC/USDT",
                                     source_symbol="BTCUSDT", interval="60")


def test_full_month_uses_warmup_but_counts_only_next_open_month_trades():
    data, frame = monthly.month_dataset(public_fixture, pd.Timestamp("2026-06-01", tz="UTC"),
                                        "BTCUSDT", "hour1")
    row = monthly.cell_result(data, frame, "2026-06", "BTCUSDT", "hour1",
                              "ema20_50", "conservative")
    assert row["bars_in_month"] == 30*24
    assert row["trade_count"] == 1
    assert row["forced_terminal_exits"] == 1
    assert row["sum_net_pnl_usdt"] == pytest.approx(row["mean_net_pnl_per_trade_usdt"])
    assert row["automatic_paper_admission"] is False
    assert row["live_trading_authority"] is False


def test_zero_trades_has_no_invented_mean_or_minimum_count_gate():
    data, frame = monthly.month_dataset(public_fixture, pd.Timestamp("2026-06-01", tz="UTC"),
                                        "BTCUSDT", "hour1")
    row = monthly.cell_result(data, frame, "2026-06", "BTCUSDT", "hour1",
                              "rsi14_30_50", "conservative")
    assert row["trade_count"] == 0
    assert row["sum_net_pnl_usdt"] == 0
    assert row["mean_net_pnl_per_trade_usdt"] is None
    assert monthly.plan("a"*40, "2026-06-01", "2026-08-01")["minimum_trade_count_gate"] is None


@pytest.mark.parametrize("start,end", [("2026-06-02", "2026-07-01"),
    ("2026-07-01", "2026-06-01"), ("2025-01-01", "2026-02-01")])
def test_partial_reverse_or_unbounded_windows_fail(start, end):
    with pytest.raises(ValueError):
        monthly.months_between(start, end)


def test_gapped_month_or_short_warmup_is_rejected():
    def truncated(**kwargs):
        result = public_fixture(**kwargs)
        result["rows"].pop()
        return result
    with pytest.raises(ValueError):
        monthly.month_dataset(truncated, pd.Timestamp("2026-06-01", tz="UTC"), "BTCUSDT", "hour1")


def test_recomputed_content_must_match_the_supplied_replay_manifest(tmp_path, monkeypatch):
    claimed = {"semantic_dataset_sha256": monthly.ARCHIVE_SHA256, "files": ["original"]}
    (tmp_path / "REPLAY_DATASET_MANIFEST.json").write_text(json.dumps(claimed))
    monkeypatch.setattr(monthly, "build_manifest", lambda root: {**claimed, "files": ["tampered"]})
    with pytest.raises(ValueError, match="recomputed"):
        monthly.verify_archive(tmp_path)


def test_concurrent_stage_does_not_remove_an_existing_lock(tmp_path):
    with monthly.stage_lock(tmp_path):
        with pytest.raises(ValueError, match="already active"):
            with monthly.stage_lock(tmp_path):
                pytest.fail("a duplicate producer entered")
        assert (tmp_path / ".stage-lock").exists()
    assert not (tmp_path / ".stage-lock").exists()


def test_resume_is_source_bound_and_qa_recomputes_then_rejects_numeric_tampering(tmp_path, monkeypatch):
    monkeypatch.setattr(monthly, "verify_archive", lambda root: {})
    monkeypatch.setattr(monthly, "build_archive_dataset_fetcher", lambda root: public_fixture)
    monkeypatch.setattr(monthly.engine, "CONTRACT", {"symbols": ["BTCUSDT"], "timeframes": ["hour1"]})
    monkeypatch.setattr(monthly.engine, "STRATEGIES", ("ema20_50",))
    output = tmp_path / "producer"
    args = (tmp_path, output, "a"*40, "2026-06-01", "2026-07-01")
    first = monthly.run_stage(*args)
    monkeypatch.setattr(monthly, "cell_result", monthly.cell_result)
    assert monthly.run_stage(*args) == first
    with pytest.raises(ValueError, match="different source"):
        monthly.run_stage(tmp_path, output, "b"*40, "2026-06-01", "2026-07-01")
    report = output / "report.json"
    qa = tmp_path / "qa"
    assert monthly.run_stage(tmp_path, qa, "a"*40, "2026-06-01", "2026-07-01", report) == first
    assert monthly.read_sealed(qa / "qa-evidence.json")["verified_cells"] == 2
    calls = []
    calculate = monthly.cell_result
    def observed(*a, **k):
        calls.append(1)
        return calculate(*a, **k)
    monkeypatch.setattr(monthly, "cell_result", observed)
    altered = {k: v for k, v in first.items() if k != "digest"}
    altered["cells"][0]["trade_count"] += 1
    monthly.engine.write_json(report, monthly.sealed(altered))
    with pytest.raises(ValueError, match="differs from producer"):
        monthly.run_stage(tmp_path, tmp_path / "qa-tampered", "a"*40,
                          "2026-06-01", "2026-07-01", report)
    assert len(calls) == 2
