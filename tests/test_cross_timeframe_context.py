from copy import deepcopy

import pytest

from cross_timeframe_context import CrossTimeframeContextError, build_cross_timeframe_context
from data_intelligence import classify_canonical_regimes
from phase6_research_pipeline import bind_bybit_closed_dataset


AS_OF = 1_700_020_800_000  # aligned to 4h, therefore also 1h and 15m
INTERVALS = {
    "15": (900_000, "15m"),
    "60": (3_600_000, "1h"),
    "240": (14_400_000, "4h"),
}


def candles(
    interval: str,
    *,
    count: int = 30,
    slope: str = "up",
    symbol: str = "BTCUSDT",
    last_open_offset: int = 1,
):
    step, _ = INTERVALS[interval]
    last_open = AS_OF - step * last_open_offset
    start = last_open - (count - 1) * step
    rows = []
    for index in range(count):
        if slope == "up":
            price = 100 + index
        elif slope == "down":
            price = 140 - index
        elif slope == "range":
            price = 100 + (index % 2) * 0.1
        else:
            raise AssertionError("unsupported fixture slope")
        rows.append(
            {
                "source": "Bybit",
                "market_type": "spot",
                "symbol": symbol,
                "interval": interval,
                "open_time_ms": start + index * step,
                "close_time_ms": start + (index + 1) * step - 1,
                "open": f"{price:.8f}",
                "high": f"{price * 1.003:.8f}",
                "low": f"{price * 0.997:.8f}",
                "close": f"{price:.8f}",
                "volume": "10",
                "turnover": f"{price * 10:.8f}",
                "closed": True,
            }
        )
    return rows


def evidence(
    interval: str,
    *,
    slope: str = "up",
    canonical_symbol: str = "BTC/USDT",
    source_symbol: str = "BTCUSDT",
    last_open_offset: int = 1,
):
    ds = bind_bybit_closed_dataset(
        candles(
            interval,
            slope=slope,
            symbol=source_symbol,
            last_open_offset=last_open_offset,
        ),
        canonical_symbol=canonical_symbol,
        source_symbol=source_symbol,
        interval=interval,
    )
    return classify_canonical_regimes(ds)


def test_three_timeframe_alignment_is_deterministic_and_canonical():
    evidences = [evidence("240"), evidence("15"), evidence("60")]
    first = build_cross_timeframe_context(evidences, as_of_ms=AS_OF)
    second = build_cross_timeframe_context(deepcopy(evidences), as_of_ms=AS_OF)
    assert first == second
    assert first["alignment"] == "ALIGNED_UP"
    assert first["reason_codes"] == ["MTF_DIRECTION_UP_ALIGNED"]
    assert [item["timeframe"] for item in first["timeframes"]] == ["15m", "1h", "4h"]
    assert first["paper_only"] is True
    assert first["lookahead_control"] is True
    assert len(first["context_sha256"]) == 64


def test_mixed_direction_is_explicit_not_discretionary():
    result = build_cross_timeframe_context(
        [evidence("15", slope="up"), evidence("60", slope="down")],
        as_of_ms=AS_OF,
    )
    assert result["alignment"] == "MIXED"
    assert result["reason_codes"] == ["MTF_MIXED_REGIMES"]


def test_future_bearing_snapshot_is_rejected_instead_of_backselecting_old_record():
    future = evidence("15", last_open_offset=0)
    with pytest.raises(CrossTimeframeContextError, match="future-bearing"):
        build_cross_timeframe_context([future, evidence("60")], as_of_ms=AS_OF)


def test_stale_timeframe_is_rejected():
    stale = evidence("15", last_open_offset=4)
    with pytest.raises(CrossTimeframeContextError, match="stale"):
        build_cross_timeframe_context([stale, evidence("60")], as_of_ms=AS_OF)


def test_tampered_regime_evidence_digest_is_rejected():
    tampered = deepcopy(evidence("15"))
    tampered["current_regime"]["regime"] = "RANGE"
    with pytest.raises(CrossTimeframeContextError, match="digest"):
        build_cross_timeframe_context([tampered, evidence("60")], as_of_ms=AS_OF)


def test_duplicate_timeframe_and_namespace_mismatch_fail_closed():
    with pytest.raises(CrossTimeframeContextError, match="duplicate"):
        build_cross_timeframe_context([evidence("15"), evidence("15")], as_of_ms=AS_OF)

    eth = evidence(
        "60",
        canonical_symbol="ETH/USDT",
        source_symbol="ETHUSDT",
    )
    with pytest.raises(CrossTimeframeContextError, match="namespace mismatch"):
        build_cross_timeframe_context([evidence("15"), eth], as_of_ms=AS_OF)


def test_unknown_authority_field_is_rejected_by_exact_evidence_schema():
    widened = deepcopy(evidence("15"))
    widened["live_order"] = True
    with pytest.raises(CrossTimeframeContextError, match="schema mismatch"):
        build_cross_timeframe_context([widened, evidence("60")], as_of_ms=AS_OF)


@pytest.mark.parametrize("bad_as_of", [-1, True, "1700020800000"])
def test_invalid_as_of_fails_closed(bad_as_of):
    with pytest.raises(CrossTimeframeContextError, match="as_of_ms"):
        build_cross_timeframe_context([evidence("15"), evidence("60")], as_of_ms=bad_as_of)
