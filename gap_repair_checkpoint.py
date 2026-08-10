from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = 1


class CheckpointError(ValueError):
    """Raised when a persisted checkpoint is malformed or does not match identity."""


@dataclass(frozen=True)
class GapRepairCheckpoint:
    schema_version: int
    symbol: str
    timeframe: str
    gap_set_digest: str
    cursor: int


def gap_set_digest(gap_starts: Iterable[str]) -> str:
    """Bind checkpoint identity to the authoritative ordered gap sequence."""
    canonical = "\n".join(str(value) for value in gap_starts).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_checkpoint(*, symbol: str, timeframe: str, gap_starts: Iterable[str], cursor: int) -> GapRepairCheckpoint:
    values = list(gap_starts)
    if not symbol or not timeframe:
        raise CheckpointError("checkpoint identity must include symbol and timeframe")
    if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0:
        raise CheckpointError("cursor must be a non-negative integer")
    if values and cursor >= len(values):
        raise CheckpointError("cursor is outside the active gap set")
    if not values and cursor != 0:
        raise CheckpointError("empty gap set requires cursor zero")
    return GapRepairCheckpoint(SCHEMA_VERSION, symbol, timeframe, gap_set_digest(values), cursor)


def write_checkpoint(path: Path, checkpoint: GapRepairCheckpoint) -> None:
    """Atomically replace one checkpoint file without weakening prior state on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    payload = json.dumps(asdict(checkpoint), sort_keys=True, separators=(",", ":")) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_checkpoint(path: Path, *, symbol: str, timeframe: str, gap_starts: Iterable[str]) -> GapRepairCheckpoint:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CheckpointError("checkpoint is unreadable or malformed") from exc
    required = {"schema_version", "symbol", "timeframe", "gap_set_digest", "cursor"}
    if not isinstance(payload, dict) or set(payload) != required:
        raise CheckpointError("checkpoint schema fields are invalid")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise CheckpointError("checkpoint schema version is unsupported")
    if payload["symbol"] != symbol or payload["timeframe"] != timeframe:
        raise CheckpointError("checkpoint identity does not match requested series")
    values = list(gap_starts)
    expected_digest = gap_set_digest(values)
    if payload["gap_set_digest"] != expected_digest:
        raise CheckpointError("checkpoint gap-set identity is stale, reordered, or substituted")
    cursor = payload["cursor"]
    if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0:
        raise CheckpointError("checkpoint cursor is invalid")
    if values and cursor >= len(values):
        raise CheckpointError("checkpoint cursor is outside the active gap set")
    if not values and cursor != 0:
        raise CheckpointError("empty gap set requires cursor zero")
    return GapRepairCheckpoint(SCHEMA_VERSION, symbol, timeframe, expected_digest, cursor)
