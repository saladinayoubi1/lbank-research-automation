from __future__ import annotations

import logging
import time
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
TIMEFRAME_SECONDS = {
    "minute15": 15 * 60,
    "hour1": 60 * 60,
    "hour4": 4 * 60 * 60,
}

START_DATE_UTC = "2022-01-01T00:00:00Z"
OUTPUT_ROOT = Path("data/market")
REQUEST_SIZE = 2000
TIMEOUT_SECONDS = 30

# Each scheduled run advances every symbol/timeframe by several API pages.
# This keeps one GitHub Actions run short while gradually completing history.
MAX_PAGES_PER_SERIES_PER_RUN = 3
REQUEST_PAUSE_SECONDS = 0.15

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
        headers={"User-Agent": "lbank-research-automation/0.2"},
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
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame["symbol"] = symbol
    frame["timeframe"] = timeframe

    valid_ohlc = (
        frame[COLUMNS].notna().all(axis=1)
        & (frame["high"] >= frame[["open", "close", "low"]].max(axis=1))
        & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1))
        & (frame["volume"] >= 0)
    )

    invalid_count = int((~valid_ohlc).sum())
    if invalid_count:
        LOGGER.warning(
            "Skipped %s invalid candle(s) for %s %s",
            invalid_count,
            symbol,
            timeframe,
        )
        frame = frame.loc[valid_ohlc].copy()

    return (
        frame.sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .reset_index(drop=True)
    )


def read_existing(output_path: Path) -> pd.DataFrame:
    if not output_path.exists():
        return pd.DataFrame(columns=COLUMNS + ["symbol", "timeframe"])
    return pd.read_parquet(output_path)


def save_merged(
    existing: pd.DataFrame,
    incoming_frames: list[pd.DataFrame],
    output_path: Path,
) -> int:
    usable = [existing, *[frame for frame in incoming_frames if not frame.empty]]
    merged = pd.concat(usable, ignore_index=True)

    if merged.empty:
        return 0

    merged = (
        merged.sort_values("timestamp")
        .drop_duplicates(["symbol", "timeframe", "timestamp"], keep="last")
        .reset_index(drop=True)
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(output_path, index=False, compression="zstd")
    return len(merged)


def initial_cursor(existing: pd.DataFrame, timeframe: str) -> int:
    if existing.empty:
        return int(pd.Timestamp(START_DATE_UTC).timestamp())

    latest = int(pd.Timestamp(existing["timestamp"].max()).timestamp())
    return latest + TIMEFRAME_SECONDS[timeframe]


def collect_series(symbol: str, timeframe: str) -> None:
    output_path = OUTPUT_ROOT / symbol / f"{timeframe}.parquet"
    existing = read_existing(output_path)
    cursor = initial_cursor(existing, timeframe)
    now_seconds = int(pd.Timestamp.now(tz="UTC").timestamp())

    new_frames: list[pd.DataFrame] = []

    for page_number in range(1, MAX_PAGES_PER_SERIES_PER_RUN + 1):
        if cursor >= now_seconds:
            LOGGER.info("%s %s is up to date", symbol, timeframe)
            break

        LOGGER.info(
            "Collecting %s %s page %s from %s",
            symbol,
            timeframe,
            page_number,
            pd.to_datetime(cursor, unit="s", utc=True),
        )

        rows = get_klines(symbol, timeframe, cursor)
        frame = rows_to_frame(rows, symbol, timeframe)

        if frame.empty:
            LOGGER.info("No usable candles returned for %s %s", symbol, timeframe)
            break

        returned_max = int(pd.Timestamp(frame["timestamp"].max()).timestamp())
        if returned_max < cursor:
            LOGGER.warning(
                "API returned only older candles for %s %s; stopping pagination",
                symbol,
                timeframe,
            )
            break

        new_frames.append(frame)

        next_cursor = returned_max + TIMEFRAME_SECONDS[timeframe]
        if next_cursor <= cursor:
            LOGGER.warning(
                "Cursor did not advance for %s %s; stopping pagination",
                symbol,
                timeframe,
            )
            break

        cursor = next_cursor

        if len(rows) < REQUEST_SIZE:
            LOGGER.info("Reached current end for %s %s", symbol, timeframe)
            break

        time.sleep(REQUEST_PAUSE_SECONDS)

    total = save_merged(existing, new_frames, output_path)
    LOGGER.info("Saved %s total rows to %s", total, output_path)


def collect() -> None:
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            collect_series(symbol, timeframe)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    collect()
