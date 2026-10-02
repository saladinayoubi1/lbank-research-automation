from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import nexus_verified_perpetual_positioning as positioning


class FakeClient:
    def __init__(
        self,
        start_ms: int,
        end_ms: int,
        *,
        oi_gap: bool = False,
        funding_gap: bool = False,
        bad_contract: bool = False,
    ) -> None:
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.oi_gap = oi_gap
        self.funding_gap = funding_gap
        self.bad_contract = bad_contract

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        symbol = str(params.get("symbol", ""))
        if path == "/v5/market/instruments-info":
            return {
                "result": {
                    "category": "linear",
                    "list": [
                        {
                            "symbol": symbol,
                            "contractType": "LinearFutures" if self.bad_contract else "LinearPerpetual",
                            "status": "Trading",
                            "baseCoin": symbol.removesuffix("USDT"),
                            "quoteCoin": "USDT",
                            "settleCoin": "USDT",
                            "deliveryTime": "0",
                            "fundingInterval": 480,
                        }
                    ],
                }
            }
        if path == "/v5/market/open-interest":
            hours = list(range(self.start_ms, self.end_ms, 3_600_000))
            if self.oi_gap:
                hours.pop(len(hours) // 2)
            offset = int(params.get("cursor") or 0)
            page = hours[offset : offset + 200]
            next_offset = offset + len(page)
            return {
                "result": {
                    "category": "linear",
                    "symbol": symbol,
                    "list": [
                        {"timestamp": str(stamp), "openInterest": str(1000.0 + i)}
                        for i, stamp in enumerate(page, start=offset)
                    ],
                    "nextPageCursor": str(next_offset) if next_offset < len(hours) else "",
                }
            }
        if path == "/v5/market/funding/history":
            interval = 8 * 60 * 60 * 1000
            end = int(params["endTime"]) + 1
            stamps = [
                stamp
                for stamp in range(self.start_ms, self.end_ms, interval)
                if stamp < end
            ]
            if self.funding_gap and len(stamps) > 4:
                stamps.pop(len(stamps) // 2)
            stamps = list(reversed(stamps[-200:]))
            return {
                "result": {
                    "category": "linear",
                    "list": [
                        {
                            "symbol": symbol,
                            "fundingRate": "0.0001",
                            "fundingRateTimestamp": str(stamp),
                        }
                        for stamp in stamps
                    ],
                }
            }
        raise AssertionError(path)


def window(days: int = 30) -> tuple[int, int]:
    start = int(pd.Timestamp("2026-07-03T00:00:00Z").timestamp() * 1000)
    return start, start + days * 24 * 60 * 60 * 1000


def test_open_interest_cursor_pagination_returns_exact_hourly_grid():
    start, end = window(10)
    client = FakeClient(start, end)
    frame = positioning.fetch_verified_open_interest(client, "BTCUSDT", start, end)
    assert len(frame) == 10 * 24
    assert frame["timestamp"].is_monotonic_increasing
    assert frame["open_interest"].ge(0).all()


def test_open_interest_gap_fails_closed():
    start, end = window(3)
    client = FakeClient(start, end, oi_gap=True)
    with pytest.raises(positioning.PositioningCapabilityError, match="OI coverage"):
        positioning.fetch_verified_open_interest(client, "BTCUSDT", start, end)


def test_funding_gap_fails_closed():
    start, end = window(5)
    client = FakeClient(start, end, funding_gap=True)
    with pytest.raises(positioning.PositioningCapabilityError, match="funding interval gap"):
        positioning.fetch_verified_funding(client, "BTCUSDT", start, end, 480)


def test_wrong_contract_type_is_rejected():
    start, end = window()
    client = FakeClient(start, end, bad_contract=True)
    with pytest.raises(positioning.PositioningCapabilityError, match="unsupported perpetual identity"):
        positioning.collect(client, "2026-07-03T00:00:00Z", "2026-08-02T00:00:00Z", Path("unused"))


def test_full_capability_is_source_bound_and_non_authoritative(tmp_path):
    start, end = window()
    client = FakeClient(start, end)
    proof = positioning.collect(
        client,
        "2026-07-03T00:00:00Z",
        "2026-08-02T00:00:00Z",
        tmp_path,
    )
    verified = positioning.verify_output(tmp_path)
    assert proof == verified
    assert proof["capabilities"] == [
        "verified_perpetual_funding",
        "verified_perpetual_oi",
    ]
    assert proof["research_only"] is True
    assert proof["paper_only"] is True
    assert proof["spot_long_hypothesis_only"] is True
    assert proof["derivatives_execution_authority"] is False
    assert proof["automatic_strategy_promotion"] is False
    assert proof["live_trading_authority"] is False
    assert all(row["open_interest_rows"] == 30 * 24 for row in proof["symbol_proofs"])
    assert all(row["funding_rows"] == 30 * 3 for row in proof["symbol_proofs"])

    path = tmp_path / "_perpetual_positioning_proof.json"
    tampered = json.loads(path.read_text())
    tampered["live_trading_authority"] = True
    path.write_text(json.dumps(tampered))
    with pytest.raises(positioning.PositioningCapabilityError, match="integrity or authority"):
        positioning.verify_output(tmp_path)
