from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

BASE_URL = "https://api.lbkex.com"
SYMBOLS = [
    "btc_usdt",
    "eth_usdt",
    "aero_usdt",
    "agt_usdt",
    "layer_usdt",
    "pbu_usdt",
    "udoge_usdt",
]
TIMEFRAMES = ["minute15", "hour1", "hour4"]
START_DATE_UTC = "2022-01-01T00:00:00Z"
OUTPUT_ROOT = Path("data/market")
REQUEST_SIZE = 2000
TIMEOUT_SECONDS = 30
COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

LOGGER = logging.getLogger("lbank_collector")


class LBankError(RuntimeError):
    pass


@retry(
    retry=retry_if_exception_type((requests.RequestException, LBankError)),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def get_klines(
    symbol: str,
    timeframe: str,
    start_time_seconds: int,
) -> list[list[Any]]:
    response = requests.get(
        f"{BASE_URL}/v2/kline.do",
        params={
            "symbol": symbol,
            "size": REQUEST_SIZE,
            "type": timeframe,
            "time": str(start_time_seconds),
        },
        timeout=TIMEOUT_SECONDS,
        headers={"User-Agent": "lbank-research-automation/0.1"},
    )
    response.raise_for_status()
    payload = response.json()

    result = payload.get("result")
    success = result is True or str(result).lower() == "true"
    if not success:
        raise LBankError(
            f"LBank request failed: error_code={payload.get('error_code')}, "
            f"msg={payload.get('msg')}"
        )

    data = payload.get("data")
    if not isinstance(data, list):
        raise LBankError("Invalid LBank response: data is not a list")

    return data


def rows_to_frame(
    rows: list[list[Any]],
    symbol: str,
    timeframe: str,
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=COLUMNS + ["symbol", "timeframe"])

    frame = pd.DataFrame(rows, columns=COLUMNS)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="s", utc=True)

    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise")

    frame["symbol"] = symbol
    frame["timeframe"] = timeframe

    if not (frame["high"] >= frame[["open", "close", "low"]].max(axis=1)).all():
        raise ValueError(f"Invalid OHLC data for {symbol} {timeframe}")
    if not (frame["low"] <= frame[["open", "close", "high"]].min(axis=1)).all():
        raise ValueError(f"Invalid OHLC data for {symbol} {timeframe}")
    if (frame["volume"] < 0).any():
        raise ValueError(f"Negative volume for {symbol} {timeframe}")

    return frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")


def merge_and_save(frame: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        previous = pd.read_parquet(output_path)
        frame = pd.concat([previous, frame], ignore_index=True)

    frame = (
        frame.sort_values("timestamp")
        .drop_duplicates(["symbol", "timeframe", "timestamp"], keep="last")
        .reset_index(drop=True)
    )
    frame.to_parquet(output_path, index=False, compression="zstd")


def collect() -> None:
    initial_timestamp = int(pd.Timestamp(START_DATE_UTC).timestamp())

    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            output_path = OUTPUT_ROOT / symbol / f"{timeframe}.parquet"
            start_timestamp = initial_timestamp

            if output_path.exists():
                existing = pd.read_parquet(output_path, columns=["timestamp"])
                if not existing.empty:
                    start_timestamp = int(
                        pd.Timestamp(existing["timestamp"].max()).timestamp()
                    )

            LOGGER.info("Collecting %s %s", symbol, timeframe)
            rows = get_klines(symbol, timeframe, start_timestamp)
            frame = rows_to_frame(rows, symbol, timeframe)
            merge_and_save(frame, output_path)
            LOGGER.info("Saved %s", output_path)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    collect()
