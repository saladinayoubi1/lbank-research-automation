from __future__ import annotations

import pandas as pd

from research_data import validate_research_frame


def test_validate_research_frame_normalizes_microsecond_timestamp_units() -> None:
    timestamps = pd.Series(
        pd.date_range("2022-12-01", periods=4, freq="15min", tz="UTC")
    ).astype("datetime64[us, UTC]")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [101.0, 102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0, 102.0],
            "close": [100.5, 101.5, 102.5, 103.5],
            "volume": [1.0, 1.0, 1.0, 1.0],
            "symbol": ["btc_usdt"] * 4,
            "timeframe": ["minute15"] * 4,
        }
    )

    validated = validate_research_frame(frame, "btc_usdt", "minute15")

    assert str(validated["timestamp"].dtype) == "datetime64[ns, UTC]"
    assert validated["timestamp"].tolist() == pd.date_range(
        "2022-12-01", periods=4, freq="15min", tz="UTC"
    ).tolist()
