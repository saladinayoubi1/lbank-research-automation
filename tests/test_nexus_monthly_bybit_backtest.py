from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import nexus_monthly_bybit_backtest as month

SHA = "a" * 40
START = int(datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp() * 1000)
END = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)
NOW = int(datetime(2026, 9, 15, tzinfo=timezone.utc).timestamp() * 1000)


def synthetic_fetcher(symbol, interval, *, now_ms, start_time_ms, end_time_ms, limit, timeout_seconds):
    step = month.INTERVAL_MS[interval]
    assert limit == (end_time_ms - start_time_ms) // step + 1
    assert timeout_seconds > 0
    return [
        {
            "source": "Bybit", "market_type": "spot", "symbol": symbol,
            "interval": interval, "open_time_ms": t,
            "close_time_ms": t + step - 1, "open": "100",
            "high": "103", "low": "99", "close": "101",
            "volume": "1000", "turnover": "100000", "closed": True,
        }
        for t in range(start_time_ms, end_time_ms + 1, step)
    ]


def test_month_window_rejects_partial_or_unclosed_month() -> None:
    assert month.month_window("2026-08-01", "2026-09-01", NOW) == (START, END)
    for a, b in (
        ("2026-08-02", "2026-09-01"),
        ("2026-08-01", "2026-08-31"),
        ("2026-08-01", "2026-10-01"),
        ("2026-08-01", "2026-08-01"),
    ):
        with pytest.raises(month.MonthlyMatrixError):
            month.month_window(a, b, NOW)
    with pytest.raises(month.MonthlyMatrixError):
        month.month_window("2026-08-01", "2026-09-01", START)


def test_full_month_15m_requires_six_complete_pages_and_exact_bound_registry() -> None:
    calls = []
    def traced(*args, **kwargs):
        calls.append((args, kwargs))
        return synthetic_fetcher(*args, **kwargs)
    dataset, pages = month.acquire_month("BTCUSDT", "15", START, END, NOW, fetcher=traced)
    assert dataset["source"] == "Bybit"
    assert dataset["source_symbol"] == "BTCUSDT"
    assert dataset["row_count"] == 31 * 96
    assert len(pages) == 6 == len(calls)
    assert sum(p["rows"] for p in pages) == 31 * 96
    assert all(p["rows"] <= 500 for p in pages)
    assert dataset["rows"][0]["open_time_ms"] == START
    assert dataset["rows"][-1]["open_time_ms"] == END - 900_000
    assert len({p["page_sha256"] for p in pages}) == len(pages)


def test_partial_or_substituted_bybit_month_fails_closed() -> None:
    def gap(*args, **kwargs):
        return synthetic_fetcher(*args, **kwargs)[:-1]
    with pytest.raises(month.MonthlyMatrixError, match="incomplete"):
        month.acquire_month("SOLUSDT", "60", START, END, NOW, fetcher=gap)
    def swapped(*args, **kwargs):
        rows = synthetic_fetcher(*args, **kwargs)
        rows[0]["source"] = "Binance"
        return rows
    with pytest.raises(month.MonthlyMatrixError, match="namespace"):
        month.acquire_month("XRPUSDT", "240", START, END, NOW, fetcher=swapped)
    with pytest.raises(month.MonthlyMatrixError):
        month.acquire_month("DOGEUSDT", "60", START, END, NOW, fetcher=synthetic_fetcher)


def test_full_month_roundtrip_stats_use_closed_exposure_episodes_not_fill_count() -> None:
    frames = pd.DataFrame([
        {"quantity_change": 2.0, "notional": 200.0, "fee": 1.0},
        {"quantity_change": -0.5, "notional": 55.0, "fee": 0.2},
        {"quantity_change": -1.5, "notional": 165.0, "fee": 0.8},
        {"quantity_change": 1.0, "notional": 120.0, "fee": 1.0},
        {"quantity_change": -1.0, "notional": 110.0, "fee": 1.0},
    ])
    stats = month.closed_round_trips(frames)
    assert stats["closed_trades"] == 2
    assert stats["win_rate_pct"] == 50.0
    assert stats["profit_factor"] == pytest.approx(18 / 12, abs=0.00001)
    no_trades = month.closed_round_trips(pd.DataFrame(columns=frames.columns))
    assert no_trades["closed_trades"] == 0
    assert no_trades["win_rate_pct"] is None


def test_fail_closed_output_and_owner_review_gate(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(month, "PAIRS", ("BTCUSDT",))
    monkeypatch.setattr(month, "INTERVALS", {"4h": "240"})
    monkeypatch.setattr(month, "STRATEGY_PRESETS", {"momentum": {"lookback": 12}})
    def fake_cell(dataset, symbol, timeframe, family, sha):
        assert dataset["row_count"] == 31 * 6
        return {"symbol": symbol, "timeframe": timeframe, "strategy": family,
                "dataset_binding_sha256": dataset["binding_sha256"],
                "source_sha": sha, "auto_paper": False}
    monkeypatch.setattr(month, "run_cell", fake_cell)
    out = tmp_path / "monthly"
    result = month.run_month(
        start="2026-08-01", end_exclusive="2026-09-01",
        output=out, source_sha=SHA, now_ms=NOW, fetcher=synthetic_fetcher,
    )
    assert result["exact_canonical_months"] == 1
    assert result["strategy_cells"] == 1
    assert result["no_demo_or_live_execution"] is True
    assert result["owner_review_required_before_any_new_demo"] is True
    assert len(list((out / "datasets").glob("*.json"))) == 1
    assert json.loads((out / "summary.json").read_text())["code_sha"] == SHA
    with pytest.raises(month.MonthlyMatrixError):
        month.run_month(start="2026-08-01", end_exclusive="2026-09-01",
                        output=out, source_sha=SHA, now_ms=NOW,
                        fetcher=synthetic_fetcher)


def test_monthly_research_source_does_not_grant_trading_or_private_transport() -> None:
    source = Path(month.__file__).read_text()
    workflow = Path(".github/workflows/nexus-monthly-bybit-pre-demo.yml").read_text()
    for forbidden in ("submit_paper_order", "auto_paper(", "execute_live_order", "requests.post("):
        assert forbidden not in source
    assert "owner_review_required_before_any_new_demo" in source
    assert "NEXUS_SOURCE_SHA" in workflow
    assert "contents: read" in workflow
    assert "github.actor == github.repository_owner" in workflow
    assert "NEXUS_BYBIT_PUBLIC_REGION: GLOBAL" in workflow
