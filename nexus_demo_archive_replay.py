"""Deterministic gradual replay over the verified immutable Bybit archive."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

from market_data_provenance_manifest import build_provenance_manifest
from phase5_data_binding import bind_canonical_dataset


ARCHIVE_SHA256 = "5f1173467c2296201940c3b7786b7cc3e5442244e07289769ab4867ace41d668"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMEFRAMES = {
    "minute15": ("15", "15m", 900_000),
    "hour1": ("60", "1h", 3_600_000),
    "hour4": ("240", "4h", 14_400_000),
}
_SYMBOLS = {
    "BTCUSDT": ("btc_usdt", "BTC/USDT"),
    "ETHUSDT": ("eth_usdt", "ETH/USDT"),
}
_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]


class DemoArchiveReplayError(RuntimeError):
    pass


def _archive_path(root: Path, symbol: str, timeframe: str) -> Path:
    try:
        archive_symbol, _canonical = _SYMBOLS[symbol]
        _interval, _manifest_timeframe, _step_ms = _TIMEFRAMES[timeframe]
    except KeyError as exc:
        raise DemoArchiveReplayError("unsupported archive replay cell") from exc
    path = root.resolve() / "bybit_market" / archive_symbol / f"{timeframe}.parquet"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
        raise DemoArchiveReplayError("verified archive series is unavailable or unsafe")
    return path


def _load_frame(root: Path, symbol: str, timeframe: str) -> pd.DataFrame:
    frame = pd.read_parquet(_archive_path(root, symbol, timeframe))
    if frame.columns.tolist() != _COLUMNS:
        raise DemoArchiveReplayError("archive series schema mismatch")
    archive_symbol, _canonical = _SYMBOLS[symbol]
    if set(frame["symbol"].astype(str)) != {archive_symbol}:
        raise DemoArchiveReplayError("archive symbol identity mismatch")
    if set(frame["timeframe"].astype(str)) != {timeframe}:
        raise DemoArchiveReplayError("archive timeframe identity mismatch")
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    open_ms = (timestamps.astype("int64") // 1_000_000).astype("int64")
    _interval, _manifest_timeframe, step_ms = _TIMEFRAMES[timeframe]
    if (
        open_ms.duplicated().any()
        or not open_ms.is_monotonic_increasing
        or (open_ms % step_ms != 0).any()
        or not (open_ms.diff().dropna() == step_ms).all()
    ):
        raise DemoArchiveReplayError("archive candle chronology mismatch")
    result = frame.copy()
    result["open_time_ms"] = open_ms
    return result


def next_replay_now_ms(
    archive_root: str | Path,
    symbol: str,
    timeframe: str,
    previous_open_ms: int,
    history_limit: int,
) -> int:
    """Return a clock immediately after the next replay candle has closed."""
    frame = _load_frame(Path(archive_root), symbol, timeframe)
    _interval, _manifest_timeframe, step_ms = _TIMEFRAMES[timeframe]
    first_eligible = int(frame["open_time_ms"].iloc[history_limit - 1])
    target_open = first_eligible if previous_open_ms < first_eligible else previous_open_ms + step_ms
    if target_open > int(frame["open_time_ms"].iloc[-1]):
        raise DemoArchiveReplayError("verified archive replay is exhausted")
    return target_open + step_ms


def build_archive_dataset_fetcher(
    archive_root: str | Path,
    *,
    archive_sha256: str = ARCHIVE_SHA256,
) -> Callable[..., Mapping[str, Any]]:
    root = Path(archive_root).resolve()
    archive_sha256 = str(archive_sha256).lower()
    if not _SHA256_RE.fullmatch(archive_sha256) or archive_sha256 != ARCHIVE_SHA256:
        raise DemoArchiveReplayError("archive digest is not the approved immutable dataset")

    def fetcher(
        *,
        canonical_symbol: str,
        source_symbol: str,
        interval: str,
        now_ms: int,
        start_time_ms: int,
        end_time_ms: int,
        limit: int,
        **_kwargs: Any,
    ) -> Mapping[str, Any]:
        symbol = str(source_symbol).upper()
        timeframe = next((name for name, spec in _TIMEFRAMES.items() if spec[0] == interval), None)
        if timeframe is None or symbol not in _SYMBOLS or _SYMBOLS[symbol][1] != canonical_symbol:
            raise DemoArchiveReplayError("archive fetch namespace mismatch")
        _source_interval, manifest_timeframe, step_ms = _TIMEFRAMES[timeframe]
        if end_time_ms + step_ms > now_ms:
            raise DemoArchiveReplayError("archive replay requested an unclosed candle")
        frame = _load_frame(root, symbol, timeframe)
        window = frame[
            (frame["open_time_ms"] >= start_time_ms)
            & (frame["open_time_ms"] <= end_time_ms)
        ].copy()
        expected = list(range(start_time_ms, end_time_ms + 1, step_ms))
        actual = window["open_time_ms"].astype(int).tolist()
        if len(window) != limit or actual != expected:
            raise DemoArchiveReplayError("archive replay window is incomplete")
        rows = [{
            "open_time_ms": int(row.open_time_ms),
            "open": str(row.open),
            "high": str(row.high),
            "low": str(row.low),
            "close": str(row.close),
            "volume": str(row.volume),
        } for row in window.itertuples(index=False)]
        endpoint_contract = (
            f"/v5/market/kline?category=spot&symbol={symbol}&interval={interval}"
        )
        manifest = build_provenance_manifest(
            source="Bybit",
            market_type="spot",
            source_symbol=symbol,
            canonical_symbol=canonical_symbol,
            timeframe=manifest_timeframe,
            endpoint_contract=endpoint_contract,
            mapping_policy_version="1.0.0",
            retrieval_start_ms=start_time_ms,
            retrieval_end_ms=end_time_ms,
            candles=rows,
            metadata={
                "collector": "verified_immutable_archive_replay",
                "closed_only": True,
                "archive_sha256": archive_sha256,
            },
        )
        return bind_canonical_dataset(manifest, rows)

    return fetcher
