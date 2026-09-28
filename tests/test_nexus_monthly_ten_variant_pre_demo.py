"""Ten-variant evidence envelope: no optimizer, no implicit Demo promotion."""
from __future__ import annotations

import copy
import pandas as pd
import pytest

import nexus_monthly_four_pair_pre_demo as monthly
import nexus_monthly_ten_variant_pre_demo as variants
import nexus_multitimeframe_strategy_discovery as sim
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES


SOURCE = "d" * 40


def _frames():
    frames = {}
    step = {"minute15": "15min", "hour1": "1h", "hour4": "4h"}
    for tf in TIMEFRAMES:
        ticks = pd.date_range(monthly.START_DATE, periods=monthly.EXPECTED_ROWS[tf],
                              freq=step[tf], tz="UTC")
        for idx, symbol in enumerate(SYMBOLS):
            center = 100 + 11 * idx
            values = [center + n / 300 + (n % 27) / 100 for n in range(len(ticks))]
            frames[(symbol, tf)] = pd.DataFrame({
                "timestamp": ticks, "open": values,
                "high": [x + 1 for x in values], "low": [x - 1 for x in values],
                "close": [x + .2 for x in values],
                "volume": [5.0] * len(values),
                "symbol": [symbol] * len(values), "timeframe": [tf] * len(values),
            })
    return frames


def _base(frames):
    report = monthly.calculate(frames, source_sha=SOURCE)
    report["archive_sources"] = [
        {"symbol": symbol, "url": f"https://public.bybit.com/spot/{symbol}/{symbol}-2026-07.csv.gz",
         "sha256": str(i+1) * 64}
        for i, symbol in enumerate(SYMBOLS)
    ]
    report["source_manifest_sha256"] = monthly._digest(report["archive_sources"])
    report["result_sha256"] = monthly._digest(report)
    return report


def test_all_ten_preregistered_generators_are_supported_and_distinct():
    assert len(variants.VARIANTS) == 10
    assert len({name for name, _, _ in variants.VARIANTS}) == 10
    assert len({monthly._digest(args) for _, _, args in variants.VARIANTS}) == 10
    frame = _frames()[(SYMBOLS[0], "hour4")]
    for name, family, config in variants.VARIANTS:
        generated = sim.generate_targets(frame, family, config)
        assert len(generated) == len(frame), name
        assert generated.isin((0., 1.)).all(), name


def test_120_isolated_research_rows_never_auto_promote(monkeypatch):
    frames = _frames()
    report = _base(frames)
    def deterministic_sim(frame, target, start, end, profile, *, bars_per_year):
        assert target.iloc[start:end].isin((0., 1.)).all()
        assert end <= len(frame) and end > start
        return {"total_return": 0.01, "max_drawdown": 0.03,
                "fill_count": 8, "sharpe": 1.2}
    monkeypatch.setattr(variants.sim, "_simulate", deterministic_sim)
    result = variants.calculate_variants(frames, source_sha=SOURCE, base=report)
    assert len(result["rows"]) == 120
    assert len({(r["symbol"], r["timeframe"], r["strategy_id"]) for r in result["rows"]}) == 120
    assert all(r["bars"] == monthly.EXPECTED_ROWS[r["timeframe"]] for r in result["rows"])
    assert all(r["full_month_proven"] and r["holdout_not_used_for_selection"] for r in result["rows"])
    assert all(not r["demo_promoted"] and not r["live_enabled"] for r in result["rows"])
    assert result["strategy_selection_performed"] is False
    assert result["independent_runtime_qualification"] is False
    assert result["demo_promotions"] == 0


def test_source_digest_and_month_cannot_be_substituted(monkeypatch):
    frames = _frames()
    report = _base(frames)
    bad = copy.deepcopy(report)
    bad["rows"][0]["frame_sha256"] = "0" * 64
    with pytest.raises(monthly.MonthlyResearchError):
        variants.calculate_variants(frames, source_sha=SOURCE, base=bad)
    bad = copy.deepcopy(report)
    bad["source_manifest_sha256"] = "0" * 64
    bad["result_sha256"] = monthly._digest({
        k: v for k, v in bad.items() if k != "result_sha256"
    })
    with pytest.raises(monthly.MonthlyResearchError):
        variants.calculate_variants(frames, source_sha=SOURCE, base=bad)
    with pytest.raises(monthly.MonthlyResearchError):
        variants.calculate_variants(frames, source_sha="a"*40, base=report)


def test_changed_frame_fails_even_when_source_receipt_stays_valid(monkeypatch):
    frames = _frames()
    base = _base(frames)
    tampered = copy.deepcopy(frames)
    first = tampered[(SYMBOLS[0], "hour4")].copy()
    first.loc[50, "close"] += 10
    tampered[(SYMBOLS[0], "hour4")] = first
    with pytest.raises(monthly.MonthlyResearchError, match="digest changed"):
        variants.calculate_variants(tampered, source_sha=SOURCE, base=base)
