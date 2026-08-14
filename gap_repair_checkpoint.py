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


def _reject_symlink(path: Path, *, label: str) -> None:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    for component in (candidate, *candidate.parents):
        if component.is_symlink():
            raise CheckpointError(f"{label} path substitution is not allowed")


def _canonical_path(path: Path, *, label: str) -> Path:
    """Return one canonical lexical/real path after rejecting symlink substitution.

    Every checkpoint, marker and lock operation is derived from this canonical path,
    so relative paths, ``..`` aliases and platform case-normalization cannot create
    separate ownership/checkpoint identities for the same filesystem location.
    """
    _reject_symlink(path, label=label)
    expanded = os.path.expanduser(os.fspath(path))
    absolute = os.path.abspath(expanded)
    real = os.path.realpath(absolute)
    normalized = os.path.normcase(os.path.normpath(real))
    return Path(normalized)


def _fsync_parent_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path.parent, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _replace_durable(source: Path, destination: Path) -> None:
    """Atomically replace destination and request durable directory-entry commit.

    POSIX persists the rename by fsyncing the parent directory. Windows has no
    portable directory-fsync primitive in Python, so use the documented
    MOVEFILE_WRITE_THROUGH flag together with replacement semantics instead of
    silently weakening the durability contract.
    """
    if os.name != "nt":
        os.replace(source, destination)
        _fsync_parent_directory(destination)
        return

    import ctypes
    from ctypes import wintypes

    move_file_ex = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    move_file_ex.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    move_file_ex.restype = wintypes.BOOL
    MOVEFILE_REPLACE_EXISTING = 0x1
    MOVEFILE_WRITE_THROUGH = 0x8
    flags = MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH
    if not move_file_ex(str(source), str(destination), flags):
        error = ctypes.get_last_error()
        raise OSError(error, "MoveFileExW durable replacement failed", str(destination))


def _acquire_os_lock(handle) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError) as exc:
        raise CheckpointError("checkpoint ownership is active in another process") from exc


def _release_os_lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def checkpoint_lock(path: Path) -> Iterator[None]:
    """Hold cross-process ownership using a kernel-managed file lock.

    The coordination file is intentionally persistent. Kernel locks are released when
    a process exits, including abnormal termination, so stale metadata cannot create
    an orphan-lock deadlock. The file itself is never used as proof of ownership.
    """
    checkpoint = _canonical_path(path, label="checkpoint")
    lock = lock_path(checkpoint)
    _reject_symlink(lock, label="checkpoint lock")
    lock.parent.mkdir(parents=True, exist_ok=True)

    created = not lock.exists()
    with lock.open("a+b") as handle:
        if created:
            handle.write(b"0")
            handle.flush()
            os.fsync(handle.fileno())
            _fsync_parent_directory(lock)
        elif lock.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
            os.fsync(handle.fileno())

        _acquire_os_lock(handle)
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()).encode("ascii", "strict"))
            handle.flush()
            os.fsync(handle.fileno())
            yield
        finally:
            _release_os_lock(handle)


def _write_fsynced_text(path: Path, payload: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def write_checkpoint(path: Path, checkpoint: GapRepairCheckpoint) -> None:
    path = _canonical_path(path, label="checkpoint")
    marker = initialized_marker(path)
    _reject_symlink(marker, label="checkpoint marker")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    marker_temporary = marker.with_name(f".{marker.name}.tmp")
    _reject_symlink(temporary, label="checkpoint temporary")
    _reject_symlink(marker_temporary, label="checkpoint marker temporary")
    payload = json.dumps(asdict(checkpoint), sort_keys=True, separators=(",", ":")) + "\n"
    try:
        _write_fsynced_text(temporary, payload)
        _replace_durable(temporary, path)
        with path.open("r+b") as handle:
            os.fsync(handle.fileno())

        if not marker.exists():
            _write_fsynced_text(marker_temporary, "initialized\n")
            _replace_durable(marker_temporary, marker)
        else:
            with marker.open("r+b") as handle:
                os.fsync(handle.fileno())
    finally:
        if temporary.exists():
            temporary.unlink()
            _fsync_parent_directory(temporary)
        if marker_temporary.exists():
            marker_temporary.unlink()
            _fsync_parent_directory(marker_temporary)


def read_checkpoint(path: Path, *, symbol: str, timeframe: str, gap_starts: Iterable[str]) -> GapRepairCheckpoint:
    path = _canonical_path(path, label="checkpoint")
    marker = initialized_marker(path)
    _reject_symlink(marker, label="checkpoint marker")
    if not path.exists() and marker.exists():
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
