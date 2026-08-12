from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, Iterator

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


def initialized_marker(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".initialized")


def lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


def _fsync_parent_directory(path: Path) -> None:
    """Persist directory-entry mutations where the platform exposes directory fsync.

    Windows does not provide the same portable directory-fsync contract through
    Python's os module, so the stronger crash-durability claim remains explicitly
    unproven there rather than being simulated with a weaker operation.
    """
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path.parent, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def checkpoint_lock(path: Path) -> Iterator[None]:
    """Acquire exclusive cross-process ownership for one series checkpoint.

    Orphaned locks are deliberately not broken automatically. A pre-existing lock is
    ambiguous after process failure, so repair fails closed rather than risking a
    non-monotonic cursor update.
    """
    lock = lock_path(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise CheckpointError("checkpoint ownership is locked or recovery is required") from exc
    try:
        os.write(fd, str(os.getpid()).encode("ascii", "strict"))
        os.fsync(fd)
        os.close(fd)
        fd = -1
        _fsync_parent_directory(lock)
        yield
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            lock.unlink()
        except FileNotFoundError:
            pass
        else:
            _fsync_parent_directory(lock)


def write_checkpoint(path: Path, checkpoint: GapRepairCheckpoint) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    payload = json.dumps(asdict(checkpoint), sort_keys=True, separators=(",", ":")) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_parent_directory(path)
        with path.open("r+b") as handle:
            os.fsync(handle.fileno())
        marker = initialized_marker(path)
        marker_existed = marker.exists()
        with marker.open("ab") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        if not marker_existed:
            _fsync_parent_directory(marker)
    finally:
        if temporary.exists():
            temporary.unlink()
            _fsync_parent_directory(temporary)


def read_checkpoint(path: Path, *, symbol: str, timeframe: str, gap_starts: Iterable[str]) -> GapRepairCheckpoint:
    if not path.exists() and initialized_marker(path).exists():
        raise CheckpointError("checkpoint missing after prior initialization")
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
