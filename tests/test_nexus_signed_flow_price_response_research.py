from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

import nexus_signed_flow_price_response_research as a6
from nexus_verified_signed_trade_flow import build_proof, write_proof


def make_dataset(root):
    days = pd.date_range("2026-07-03", "2026-08-01", freq="1D")
    index = pd.date_range("2026-07-03T00:00:00Z", periods=30 * 96, freq="15min")
    all_flows = []
    records = []
    for symbol_i, symbol in enumerate(("BTCUSDT", "ETHUSDT")):
        canonical = symbol[:-4].lower() + "_usdt"
        base = 100.0 + symbol_i * 50.0
        wave = np.sin(np.arange(len(index)) / 17.0)
        close = base + np.arange(len(index)) * 0.002 + wave * 0.3
        open_ = close - np.where(np.arange(len(index)) % 9 == 0, 0.15, 0.01)
        high = np.maximum(open_, close) + 0.08
        low = np.minimum(open_, close) - 0.08
        candles = pd.DataFrame({
            "timestamp": index,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 10.0,
            "symbol": canonical,
            "timeframe": "minute15",
        })
        folder = root / canonical
        folder.mkdir(parents=True)
        candles.to_parquet(folder / "minute15.parquet", index=False)

        imbalance = np.where(np.arange(len(index)) % 32 < 4, 0.65, 0.02)
        total = np.full(len(index), 10_000.0)
        signed = total * imbalance
        flow = pd.DataFrame({
            "timestamp": index,
            "available_at": index + pd.Timedelta(minutes=15),
            "buy_base_volume": 60.0,
            "sell_base_volume": 40.0,
            "buy_notional": (total + signed) / 2.0,
            "sell_notional": (total - signed) / 2.0,
            "total_base_volume": 100.0,
            "total_notional": total,
            "trade_count": 100,
            "signed_notional": signed,
            "signed_notional_imbalance": imbalance,
            "vwap": close,
            "symbol": canonical,
            "timeframe": "minute15",
            "source_archive_sha256": "a" * 64,
            "source_side_semantics": "bybit_public_trade_taker_side_buy_sell",
            "research_only": True,
            "automatic_strategy_promotion": False,
            "live_trading_authority": False,
        })
        flow.to_parquet(folder / "signed_trade_flow_15m.parquet", index=False)
        all_flows.append(flow)

        for day in days:
            sha = hashlib.sha256(f"{symbol}-{day.date()}".encode()).hexdigest()
            records.append({
                "symbol": symbol,
                "audit_date": day.strftime("%Y-%m-%d"),
                "sha256": sha,
                "url": f"https://public.bybit.com/spot/{symbol}/{day:%Y-%m-%d}.csv.gz",
                "valid_trade_rows": 1000,
                "invalid_side_rows": 0,
                "duplicate_trade_id_count": 0,
                "archive_ok": True,
            })

    proof = build_proof(
        pd.concat(all_flows, ignore_index=True),
        records,
        "2026-07-03",
        "2026-08-01",
        ("BTCUSDT", "ETHUSDT"),
    )
    write_proof(root / "_signed_trade_flow_proof.json", proof)




def test_prepare_symbol_canonicalizes_equivalent_parquet_datetime_resolutions(tmp_path):
    make_dataset(tmp_path)
    flow_path = tmp_path / "btc_usdt" / "signed_trade_flow_15m.parquet"
    flow = pd.read_parquet(flow_path)
    flow["timestamp"] = flow["timestamp"].astype("datetime64[us, UTC]")
    flow["available_at"] = flow["available_at"].astype("datetime64[us, UTC]")

    prepared = a6.prepare_symbol(tmp_path, "btc_usdt", flow)

    assert len(prepared) == 30 * 96
    assert str(prepared["timestamp"].dtype) == "datetime64[ns, UTC]"


def test_training_threshold_cannot_be_changed_by_validation_or_test():
    n = 1000
    frame = pd.DataFrame({"flow_1h": np.linspace(0.01, 0.8, n)})
    before = a6.training_threshold(frame, 600)
    frame.loc[600:, "flow_1h"] = 1.0
    after = a6.training_threshold(frame, 600)
    assert before == after


def test_signal_is_closed_bar_causal():
    frame = pd.DataFrame({
        "flow_1h": [0.1, 0.8, 0.7, 0.6],
        "price_return_1h": [0.0, -0.01, 0.01, 0.01],
        "open": [100.0, 100.0, 100.0, 100.0],
        "high": [100.5, 100.5, 101.0, 101.5],
        "close": [100.0, 100.0, 101.2, 101.6],
        "atr": [1.0, 1.0, 1.0, 1.0],
    })
    signal = a6.build_signal(frame, 0.5)
    assert signal.tolist() == [False, False, True, False]
    frame.loc[3, "close"] = 1000.0
    assert a6.build_signal(frame, 0.5)[2]


def test_simulator_fills_signal_at_next_open():
    frame = pd.DataFrame({
        "decision_at": pd.date_range("2026-07-03T00:15:00Z", periods=3, freq="15min"),
        "open": [100.0, 200.0, 200.0],
        "high": [101.0, 201.0, 201.0],
        "low": [99.0, 198.0, 199.0],
        "close": [100.0, 200.0, 200.0],
        "atr": [1.0, 1.0, 1.0],
        "flow_1h": [0.5, 0.5, -0.1],
    })
    result = a6.simulate(
        frame, np.array([True, False, False]), fee_bps=0.0, slip_bps=0.0
    )
    assert result["closed_trades"] == 1
    assert result["ending_cash_usdt"] < 10_000.0


def test_full_research_run_is_30_day_source_bound_and_non_promoting(tmp_path):
    make_dataset(tmp_path)
    report = a6.run(tmp_path, tmp_path / "out", "b" * 40)
    assert report["mechanism"] == "signed_flow_price_response"
    assert report["research_only"] is True
    assert report["paper_only"] is True
    assert report["automatic_strategy_promotion"] is False
    assert report["live_trading_authority"] is False
    assert report["qualification"] == "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT"
    assert len(report["rows"]) == 12
    assert all(row["trade_count_limit"] is None for row in report["rows"])
