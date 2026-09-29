"""Four-pair full-month causal research: adversarial source/peer/authority gates."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pandas as pd
import pytest

import nexus_monthly_four_pair_composite_pre_demo as four
import nexus_monthly_four_pair_pre_demo as month
import nexus_composite_strategy_research as composite
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES

SOURCE_SHA = "a" * 40
FIRST = pd.Timestamp("2026-07-01T00:00:00Z")
FREQ = {"minute15": "15min", "hour1": "1h", "hour4": "4h"}
FAMILY = {"momentum", "trend_breakout", "mean_reversion"}


@pytest.fixture(scope="module")
def inputs():
    frames = {}
    for index, symbol in enumerate(SYMBOLS):
        for tf in TIMEFRAMES:
            n = month.EXPECTED_ROWS[tf]
            times = pd.date_range(start=FIRST, periods=n, freq=FREQ[tf])
            prices = pd.Series(range(n), dtype="float64") / 800 + 100 + index * 50
            frames[(symbol, tf)] = pd.DataFrame({
                "timestamp": times,
                "open": prices + .1, "high": prices + 2,
                "low": prices - 2, "close": prices + .2,
                "volume": pd.Series(range(n)) % 18 + 100,
                "symbol": symbol[:-4] + "/USDT",
                "timeframe": tf,
            })
    rows = []
    for (symbol, tf), df in frames.items():
        for family in sorted(FAMILY):
            rows.append({
                "symbol": symbol, "timeframe": tf, "family": family,
                "bars": month.EXPECTED_ROWS[tf],
                "frame_sha256": four._frame_digest(df),
                "monthly_coverage": True,
                "source_sha": SOURCE_SHA,
                "demo_promoted": False, "live_enabled": False,
                "qualification": "RESEARCH_ONLY_REQUIRES_INDEPENDENT_REQUALIFICATION",
            })
    baseline = {
        "contract": "nexus.bybit-monthly-pre-demo-table.v1",
        "source_sha": SOURCE_SHA, "period": "2026-07",
        "origin": "official_public_bybit_spot_trade_archive_aggregated",
        "research_only": True, "automatic_paper_promotion": False,
        "live_trading_authority": False, "bars_per_cadence": month.EXPECTED_ROWS,
        "verified_three_month_source_manifest_sha256": "c" * 64,
        "archive_sources": [{"symbol": s} for s in SYMBOLS],
        "rows": rows,
    }
    baseline["source_manifest_sha256"] = month._digest(baseline["archive_sources"])
    baseline["result_sha256"] = month._digest(baseline)
    return frames, baseline


def _fast_backtest(*args, fee_bps, slip_bps, risk_variant):
    return {
        "net_return_pct": 0.0, "closed_round_trips": 0,
        "fee_bps": fee_bps, "slippage_bps": slip_bps,
        "trade_count_limit": None, "risk_variant_seen": risk_variant,
    }


def test_full_reviewed_12_config_fourpair_288_row_matrix(inputs, monkeypatch):
    frames, baseline = inputs
    monkeypatch.setattr(composite, "backtest", _fast_backtest)
    report = four.calculate(frames, baseline, SOURCE_SHA)
    assert report["source_sha"] == SOURCE_SHA
    assert report["rows_count"] == 288
    assert report["reviewed_distinct_mechanisms"] == 6
    assert len(report["configurations"]) == 12
    assert len({row["config_fingerprint"] for row in report["rows"]}) == 12
    assert len({row["symbol"] for row in report["rows"]}) == 4
    assert len({row["part"] for row in report["rows"]}) == 3
    assert len({row["profile"] for row in report["rows"]}) == 2
    assert all(row["entry_timeframe"] == "15m" and
               row["context_timeframes"] == ["completed_1h", "completed_4h"]
               for row in report["rows"])
    assert all(row["auto_demo_promotion"] is False and
               row["live_enabled"] is False and
               row["trade_count_limit"] is None
               for row in report["rows"])
    assert report["independent_concurrent_multi_asset_portfolio_tested"] is False
    assert report["historical_test_pristine"] is False
    assert report["report_digest"] == composite.digest(
        {k: v for k, v in report.items() if k != "report_digest"}
    )
    cross = [v for v in report["rows"] if v["mechanism"] == "cross_pair_relative_reclaim"]
    assert {v["peer"] for v in cross if v["symbol"] == "BTCUSDT"} == {"ETHUSDT"}
    assert {v["peer"] for v in cross if v["symbol"] == "XRPUSDT"} == {"BTCUSDT"}
    lagged = [v for v in report["rows"] if v["mechanism"] == "lagged_peer_impulse_confirmation"]
    assert len(lagged) == 48
    assert {v["peer"] for v in lagged if v["symbol"] == "ETHUSDT"} == {"BTCUSDT"}


def test_nonmatching_monthly_data_or_authority_fails_closed(inputs):
    frames, baseline = inputs
    for mutation in (
        lambda x: x["rows"][0].update(frame_sha256="f" * 64),
        lambda x: x["rows"][0].update(demo_promoted=True),
        lambda x: x.update(result_sha256="1" * 64),
        lambda x: x.update(period="2026-08"),
        lambda x: x.update(source_sha="f" * 40),
        lambda x: x.update(automatic_paper_promotion=True),
        lambda x: x.update(verified_three_month_source_manifest_sha256="bad"),
    ):
        damaged = deepcopy(baseline)
        mutation(damaged)
        with pytest.raises(four.FourPairCompositeError):
            four._baseline_frames(damaged, frames, SOURCE_SHA)


def test_peer_time_alignment_rejects_injected_future_candle(inputs, monkeypatch):
    frames, baseline = inputs
    corrupted = {key: frame.copy() for key, frame in frames.items()}
    peer = corrupted[("BTCUSDT", "minute15")]
    peer.loc[950, "timestamp"] += pd.Timedelta(minutes=15)
    adjusted = deepcopy(baseline)
    # Simulate a newly signed but chronology-malformed input: a digest alone
    # cannot make an asynchronous peer candle legal.
    for item in adjusted["rows"]:
        if item["symbol"] == "BTCUSDT" and item["timeframe"] == "minute15":
            item["frame_sha256"] = four._frame_digest(peer)
    adjusted["result_sha256"] = month._digest(
        {k: v for k, v in adjusted.items() if k != "result_sha256"}
    )
    monkeypatch.setattr(composite, "backtest", _fast_backtest)
    with pytest.raises((composite.CompositeResearchError,
                        four.FourPairCompositeError), match="peer|same closed UTC|chronology"):
        four.calculate(corrupted, adjusted, SOURCE_SHA)


def test_numerical_replay_rejects_changed_rows_even_if_digest_resigned(inputs, monkeypatch, tmp_path):
    frames, baseline = inputs
    monkeypatch.setattr(composite, "backtest", _fast_backtest)
    monkeypatch.setattr(four, "_source_state_verified", lambda *args: None)
    monkeypatch.setattr(month, "_load_full_month", lambda *args: frames)
    b = tmp_path / "baseline.json"
    b.write_text(json.dumps(baseline), encoding="utf-8")
    produced = tmp_path / "result"
    report = four.run(state=tmp_path, baseline_file=b, source_sha=SOURCE_SHA, output=produced)
    assert (produced / "composite-table.csv").is_file()
    with pytest.raises(four.FourPairCompositeError, match="overwrite"):
        four.run(state=tmp_path, baseline_file=b, source_sha=SOURCE_SHA, output=produced)
    proof = four.replay_verify(
        state=tmp_path, baseline_file=b, report_file=produced/"composite-report.json",
        source_sha=SOURCE_SHA, output=tmp_path/"proof",
    )
    assert proof["full_288_cell_numerical_replay_matches"] is True
    assert proof["independent_model_qa_claimed"] is False
    assert proof["qa_digest"] == composite.digest(
        {k: v for k, v in proof.items() if k != "qa_digest"}
    )
    tampered = deepcopy(report)
    tampered["rows"][3]["net_return_pct"] = 1000
    tampered["report_digest"] = composite.digest({
        k: v for k, v in tampered.items() if k != "report_digest"
    })
    bad = tmp_path / "resigned-but-false.json"
    bad.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(four.FourPairCompositeError, match="did not match"):
        four.replay_verify(
            state=tmp_path, baseline_file=b, report_file=bad, source_sha=SOURCE_SHA,
            output=tmp_path/"bad-proof",
        )


def test_missing_official_source_state_fails_closed(tmp_path):
    with pytest.raises(four.FourPairCompositeError, match="verified original"):
        four._source_state_verified(
            tmp_path, {"verified_three_month_source_manifest_sha256": "f" * 64}
        )


def test_reviewed_signal_and_real_next_open_engine_are_invoked(inputs):
    frames, _ = inputs
    own = {tf: frames[("SOLUSDT", tf)] for tf in TIMEFRAMES}
    peer = frames[("BTCUSDT", "minute15")]
    f = composite.build_features(own, peer_15m=peer)
    c = next(c for c in composite.CONFIGS
             if c["mechanism"] == "cross_pair_relative_reclaim"
             and c["risk_variant"] == 0)
    signal = composite.signal_for(f, c)
    result = composite.backtest(
        f.iloc[:700].reset_index(drop=True), signal[:700],
        fee_bps=composite.ENTRY_FEE_BPS, slip_bps=composite.ENTRY_SLIP_BPS,
        risk_variant=0,
    )
    assert len(signal) == month.EXPECTED_ROWS["minute15"]
    assert result["trade_count_limit"] is None
    assert result["fee_bps"] == composite.ENTRY_FEE_BPS
    assert result["slippage_bps"] == composite.ENTRY_SLIP_BPS
