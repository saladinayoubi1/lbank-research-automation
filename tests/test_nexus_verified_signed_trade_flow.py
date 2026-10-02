from __future__ import annotations

import hashlib

import pandas as pd
import pytest

import nexus_verified_signed_trade_flow as flow


def trades_for_day(day: str = "2026-08-01") -> pd.DataFrame:
    times = pd.date_range(pd.Timestamp(day, tz="UTC"), periods=24 * 60, freq="1min")
    return pd.DataFrame({
        "trade_id": [str(i + 1) for i in range(len(times))],
        "timestamp": times,
        "side": ["Buy", "Sell"] * (len(times) // 2),
        "size": [1.0] * len(times),
        "price": [100.0 + i / 1000.0 for i in range(len(times))],
    })


def source_sha() -> str:
    return hashlib.sha256(b"official-bybit-archive-fixture").hexdigest()


def test_aggregate_day_emits_complete_causal_15m_grid_without_raw_rows():
    out = flow.aggregate_day(trades_for_day(), "BTCUSDT", "2026-08-01", source_sha())
    assert len(out) == 96
    assert (out["available_at"] - out["timestamp"] == pd.Timedelta(minutes=15)).all()
    assert out["signed_notional_imbalance"].between(-1, 1).all()
    assert set(out["source_side_semantics"]) == {"bybit_public_trade_taker_side_buy_sell"}
    assert "trade_id" not in out.columns
    assert out["research_only"].all()
    assert not out["automatic_strategy_promotion"].any()
    assert not out["live_trading_authority"].any()
def test_future_trade_change_cannot_modify_prior_completed_bucket():
    before = flow.aggregate_day(trades_for_day(), "BTCUSDT", "2026-08-01", source_sha())
    altered = trades_for_day()
    altered.loc[len(altered) - 1, "price"] = 1_000_000.0
    after = flow.aggregate_day(altered, "BTCUSDT", "2026-08-01", source_sha())
    pd.testing.assert_frame_equal(before.iloc[:-1], after.iloc[:-1])
    assert before.iloc[-1]["vwap"] != after.iloc[-1]["vwap"]


def test_unknown_taker_side_and_duplicate_trade_id_fail_closed():
    bad_side = trades_for_day()
    bad_side.loc[0, "side"] = "Unknown"
    with pytest.raises(flow.SignedTradeFlowError, match="taker side"):
        flow.aggregate_day(bad_side, "BTCUSDT", "2026-08-01", source_sha())

    duplicate = trades_for_day()
    duplicate.loc[1, "trade_id"] = duplicate.loc[0, "trade_id"]
    with pytest.raises(flow.SignedTradeFlowError, match="duplicate trade IDs"):
        flow.aggregate_day(duplicate, "BTCUSDT", "2026-08-01", source_sha())


def test_missing_15m_bucket_fails_closed():
    frame = trades_for_day()
    frame = frame.loc[
        ~((frame["timestamp"] >= pd.Timestamp("2026-08-01T12:00:00Z"))
          & (frame["timestamp"] < pd.Timestamp("2026-08-01T12:15:00Z")))
    ]
    with pytest.raises(flow.SignedTradeFlowError, match="incomplete 15m"):
        flow.aggregate_day(frame, "BTCUSDT", "2026-08-01", source_sha())
def test_proof_is_source_bound_and_rejects_authority_widening():
    btc = flow.aggregate_day(trades_for_day(), "BTCUSDT", "2026-08-01", source_sha())
    eth_sha = hashlib.sha256(b"eth-official-archive").hexdigest()
    eth = flow.aggregate_day(trades_for_day(), "ETHUSDT", "2026-08-01", eth_sha)
    combined = pd.concat([btc, eth], ignore_index=True)
    records = [
        {
            "symbol": "BTCUSDT", "audit_date": "2026-08-01", "sha256": source_sha(),
            "url": "https://public.bybit.com/spot/BTCUSDT/example.csv.gz",
            "valid_trade_rows": 1440, "invalid_side_rows": 0,
            "duplicate_trade_id_count": 0, "archive_ok": True,
        },
        {
            "symbol": "ETHUSDT", "audit_date": "2026-08-01", "sha256": eth_sha,
            "url": "https://public.bybit.com/spot/ETHUSDT/example.csv.gz",
            "valid_trade_rows": 1440, "invalid_side_rows": 0,
            "duplicate_trade_id_count": 0, "archive_ok": True,
        },
    ]
    proof = flow.build_proof(
        combined, records, "2026-08-01", "2026-08-01", ("BTCUSDT", "ETHUSDT")
    )
    flow.verify_proof(combined, proof)
    assert proof["capability"] == "verified_signed_trade_flow"
    assert proof["raw_trade_rows_published"] is False

    widened = dict(proof)
    widened["live_trading_authority"] = True
    with pytest.raises(flow.SignedTradeFlowError, match="integrity or authority"):
        flow.verify_proof(combined, widened)
