"""Trusted Multi-Pair Research surface derived from the validated Demo matrix v2."""
from __future__ import annotations

from pathlib import Path

from nexus_multipair_demo_strategy_matrix import load_manifest


MATRIX_MANIFEST = Path(__file__).resolve().parent / "config" / "nexus-demo-strategy-matrix-v2.json"


def load_trusted_surface() -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    manifest = load_manifest(MATRIX_MANIFEST)
    symbols = tuple(str(value) for value in manifest["symbols"])
    timeframes = tuple(str(value) for value in manifest["timeframes"])
    families = tuple(str(value) for value in manifest["families"])
    if len(symbols) * len(timeframes) != 12 or len(families) != 3:
        raise RuntimeError("trusted Multi-Pair matrix surface is not the accepted 12-cell/36-lane contract")
    return symbols, timeframes, families


SYMBOLS, TIMEFRAMES, FAMILIES = load_trusted_surface()
