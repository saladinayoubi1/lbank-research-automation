from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

import nexus_verified_perpetual_positioning as p
from bybit_derivatives_core_v1 import InstrumentSpec


class FakeClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, path, params):
        self.calls.append((path, dict(params)))
        if not self.pages:
            raise AssertionError("unexpected extra request")
        return self.pages.pop(0)


def oi_payload(rows, cursor=""):
    return {
        "result": {
            "list": rows,
            "nextPageCursor": cursor,
        }
    }


def oi_row(ts, single="100", bilateral="200"):
    return {
        "timestamp": str(int(pd.Timestamp(ts).timestamp() * 1000)),
        "singleOpenInterest": single,
        "openInterest": bilateral,
    }


def test_fetch_open_interest_paginates_and_requires_single_side_field():
    start = int(pd.Timestamp("2026-07-03T00:00:00Z").timestamp() * 1000)
    end = int(pd.Timestamp("2026-07-03T03:00:00Z").timestamp() * 1000)
    client = FakeClient([
        oi_payload(
            [
                oi_row("2026-07-03T02:00:00Z", "103", "206"),
                oi_row("2026-07-03T01:00:00Z", "102", "204"),
            ],
            "next",
        ),
        oi_payload([oi_row("2026-07-03T00:00:00Z", "101", "202")]),
    ])
    frame = p.fetch_open_interest(client, "BTCUSDT", start, end)
    assert frame["single_open_interest"].tolist() == [101.0, 102.0, 103.0]
    assert client.calls[1][1]["cursor"] == "next"

    bad = FakeClient([oi_payload([{
        "timestamp": str(start),
        "openInterest": "200",
    }])])
    with pytest.raises(p.PositioningDataError, match="single-sided OI"):
        p.fetch_open_interest(bad, "BTCUSDT", start, end)


def test_oi_grid_is_exact_causal_and_post_change():
    start = pd.Timestamp("2026-07-03T00:00:00Z")
    end = pd.Timestamp("2026-07-03T03:00:00Z")
    frame = pd.DataFrame({
        "timestamp": pd.date_range(start, periods=3, freq="1h"),
        "single_open_interest": [100.0, 101.0, 102.0],
        "bilateral_open_interest": [200.0, 202.0, 204.0],
    })
    out = p.verify_open_interest_grid(frame, "BTCUSDT", start, end)
    assert out["available_at"].tolist() == (
        out["timestamp"] + pd.Timedelta(hours=1)
    ).tolist()
    assert set(out["oi_methodology"]) == {"post_2026_06_11_single_sided"}

    missing = frame.iloc[[0, 2]].copy()
    with pytest.raises(p.PositioningDataError, match="incomplete exact 1h OI grid"):
        p.verify_open_interest_grid(missing, "BTCUSDT", start, end)


def test_funding_requires_exact_settlement_grid_and_finite_values():
    start = pd.Timestamp("2026-07-03T00:00:00Z")
    end = pd.Timestamp("2026-07-04T00:00:00Z")
    frame = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-07-03T00:00:00Z",
            "2026-07-03T08:00:00Z",
            "2026-07-03T16:00:00Z",
        ]),
        "funding_rate": [0.0001, -0.0001, 0.0],
    })
    out = p.verify_funding(frame, "BTCUSDT", start, end, 480)
    assert len(out) == 3
    assert out["available_at"].equals(out["timestamp"])

    bad = frame.copy()
    bad.loc[2, "funding_rate"] = float("inf")
    with pytest.raises(p.PositioningDataError, match="non-finite"):
        p.verify_funding(bad, "BTCUSDT", start, end, 480)


def test_build_rejects_pre_methodology_change_before_any_network(monkeypatch, tmp_path):
    class NeverClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("network client must not be created")

    monkeypatch.setattr(p, "Client", NeverClient)
    with pytest.raises(p.PositioningDataError, match="methodology boundary"):
        p.build(
            "2026-06-10T00:00:00Z",
            "2026-06-12T00:00:00Z",
            tmp_path,
            ["https://api.bybit.com"],
        )


def test_build_emits_digest_bound_non_trading_capabilities(monkeypatch, tmp_path):
    start = pd.Timestamp("2026-07-03T00:00:00Z")
    end = pd.Timestamp("2026-07-04T00:00:00Z")

    monkeypatch.setattr(p, "Client", lambda *_args, **_kwargs: object())
    spec = InstrumentSpec(
        symbol="BTCUSDT",
        tick_size=0.1,
        quantity_step=0.001,
        minimum_quantity=0.001,
        minimum_notional=5.0,
        maximum_market_quantity=1000.0,
        maximum_leverage=100.0,
        funding_interval_minutes=480,
    )
    monkeypatch.setattr(
        p,
        "fetch_instrument",
        lambda _client, symbol: replace(spec, symbol=symbol),
    )

    oi = pd.DataFrame({
        "timestamp": pd.date_range(start, end, freq="1h", inclusive="left"),
        "single_open_interest": range(24),
        "bilateral_open_interest": range(0, 48, 2),
    })
    funding = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-07-03T00:00:00Z",
            "2026-07-03T08:00:00Z",
            "2026-07-03T16:00:00Z",
        ]),
        "funding_rate": [0.0001, -0.0001, 0.0],
    })
    monkeypatch.setattr(p, "fetch_open_interest", lambda *_args, **_kwargs: oi.copy())
    monkeypatch.setattr(p, "fetch_funding", lambda *_args, **_kwargs: funding.copy())

    proof = p.build(
        start.isoformat(),
        end.isoformat(),
        tmp_path,
        ["https://api.bybit.com"],
    )
    p.verify_proof(proof)
    assert proof["capabilities"] == [
        "verified_perpetual_funding",
        "verified_perpetual_oi",
    ]
    assert proof["credentials_used"] is False
    assert proof["derivatives_execution_authority"] is False
    assert proof["automatic_strategy_promotion"] is False
    assert proof["live_trading_authority"] is False
    assert proof["oi_rows"] == {"BTCUSDT": 24, "ETHUSDT": 24}
    assert proof["funding_rows"] == {"BTCUSDT": 3, "ETHUSDT": 3}

    widened = dict(proof)
    widened["derivatives_execution_authority"] = True
    with pytest.raises(p.PositioningDataError, match="integrity or authority"):
        p.verify_proof(widened)
