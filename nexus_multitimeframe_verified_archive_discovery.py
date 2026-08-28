"""Bind multi-timeframe discovery to the verified immutable Bybit archive.

The discovery core intentionally works on normalized BTCUSDT/ETHUSDT labels. The
immutable archive stores the same series under its historical btc_usdt/eth_usdt
namespace. This adapter reuses the already-audited Demo archive loader to verify
path, raw identity, schema and candle chronology before normalizing only the
symbol metadata for the discovery core. OHLCV and timestamps are not rewritten.

Authority remains Research/Paper-only. This adapter cannot promote a strategy,
execute a trade, use private credentials or grant Live/L4 authority.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import nexus_demo_archive_replay as archive
import nexus_multitimeframe_strategy_discovery as discovery


class VerifiedArchiveDiscoveryError(RuntimeError):
    pass


def load_verified_archive_frame(
    root: str | Path, symbol: str, timeframe: str
) -> pd.DataFrame:
    """Return one archive-verified frame using discovery's normalized symbol label."""
    if symbol not in discovery.APPROVED_SYMBOLS or timeframe not in discovery.APPROVED_TIMEFRAMES:
        raise VerifiedArchiveDiscoveryError("archive request is outside approved discovery scope")
    try:
        raw = archive._load_frame(Path(root), symbol, timeframe)
    except Exception as exc:
        raise VerifiedArchiveDiscoveryError(
            f"verified immutable archive frame rejected: {symbol}/{timeframe}: {exc}"
        ) from exc

    # _load_frame has already verified the historical archive namespace and
    # chronology. Drop its derived open_time_ms helper and normalize metadata only.
    frame = raw[discovery.REQUIRED_COLUMNS].copy()
    frame["symbol"] = symbol

    if len(frame) < 160:
        raise VerifiedArchiveDiscoveryError(
            f"archive history is insufficient: {symbol}/{timeframe}"
        )
    numeric = frame[["open", "high", "low", "close", "volume"]].astype(float)
    if (
        not np.isfinite(numeric.to_numpy()).all()
        or (numeric[["open", "high", "low", "close"]] <= 0).any().any()
        or (numeric["volume"] < 0).any()
    ):
        raise VerifiedArchiveDiscoveryError(
            f"archive contains invalid market values: {symbol}/{timeframe}"
        )
    if set(frame["symbol"].astype(str)) != {symbol} or set(frame["timeframe"].astype(str)) != {timeframe}:
        raise VerifiedArchiveDiscoveryError(
            f"normalized archive identity mismatch: {symbol}/{timeframe}"
        )
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise VerifiedArchiveDiscoveryError(
            f"archive chronology changed after verification: {symbol}/{timeframe}"
        )
    return frame


def load_verified_manifest(path: str | Path) -> dict[str, Any]:
    manifest = discovery.load_manifest(path)
    claimed = manifest["dataset"]["archive_sha256"]
    if claimed != archive.ARCHIVE_SHA256:
        raise VerifiedArchiveDiscoveryError(
            "discovery manifest is not bound to the approved immutable Bybit archive"
        )
    return manifest


def run(
    manifest_path: str | Path,
    output_root: str | Path,
    *,
    source_sha: str,
) -> dict[str, Any]:
    """Run the existing discovery core through the verified archive loader."""
    load_verified_manifest(manifest_path)
    original_loader = discovery.load_frame
    discovery.load_frame = load_verified_archive_frame
    try:
        result = discovery.run(manifest_path, output_root, source_sha=source_sha)
    finally:
        discovery.load_frame = original_loader

    if result.get("dataset_archive_sha256") != archive.ARCHIVE_SHA256:
        raise VerifiedArchiveDiscoveryError("discovery result lost immutable archive binding")
    if (
        result.get("research_only") is not True
        or result.get("paper_only") is not True
        or result.get("live_trading_authority") is not False
        or result.get("automatic_strategy_promotion") is not False
        or result.get("automatic_paper_forward_started") is not False
    ):
        raise VerifiedArchiveDiscoveryError("discovery result exceeded Research/Paper authority")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("experiments/nexus_multitimeframe_strategy_discovery_v1.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/nexus_multitimeframe_strategy_discovery"),
    )
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    result = run(args.manifest, args.output, source_sha=args.source_sha)
    print(json.dumps({
        "research_proposal_count": result["research_proposal_count"],
        "discovery_digest": result["discovery_digest"],
        "archive_sha256": result["dataset_archive_sha256"],
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
