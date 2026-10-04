"""Fail-closed cleanup for self-hosted Windows research workspaces.

Only paths inside the current checkout are eligible. Cleanup retries transient Windows
sharing violations/AV scans, clears read-only attributes, and fails if any requested
path still exists. Never silently converts cleanup failure into success.
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import time
from pathlib import Path
from typing import Iterable


class CleanupError(RuntimeError):
    pass


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _checked_stat(path: Path) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or (
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    ):
        raise CleanupError(f"refusing symlink/reparse cleanup path: {path}")
    return info


def _check_components(root: Path, target: Path) -> None:
    current = root
    _checked_stat(current)
    for part in target.relative_to(root).parts:
        current = current / part
        _checked_stat(current)


def _make_writable(path: Path) -> None:
    info = _checked_stat(path)
    if info is None:
        return
    try:
        path.chmod(info.st_mode | stat.S_IWRITE | stat.S_IREAD)
    except (FileNotFoundError, PermissionError, OSError):
        pass


def _clear_readonly_tree(path: Path) -> None:
    if _checked_stat(path) is None:
        return

    def raise_walk_error(error: OSError) -> None:
        raise error

    # Validate every entry before changing attributes. os.walk must never follow
    # a junction or directory symlink to another research/owner tree.
    entries = [path]
    for current, directories, files in os.walk(
        path, followlinks=False, onerror=raise_walk_error
    ):
        _checked_stat(Path(current))
        for name in directories + files:
            item = Path(current) / name
            _checked_stat(item)
            entries.append(item)
    for item in entries:
        _make_writable(item)


def remove_tree_verified(
    path: Path,
    *,
    workspace: Path | None = None,
    attempts: int = 12,
    delay_seconds: float = 1.0,
) -> None:
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    if delay_seconds < 0:
        raise ValueError("delay_seconds must be >= 0")

    requested_root = (workspace or Path.cwd()).absolute()
    _checked_stat(requested_root)
    root = requested_root.resolve()
    # Keep the requested path lexical until each component has been checked.
    # Resolving first would hide a link and delete its destination instead.
    target = root / path if not path.is_absolute() else path
    if ".." in path.parts:
        raise CleanupError(f"cleanup target outside workspace: {target}")
    if target == root or not _inside(root, target):
        raise CleanupError(f"cleanup target outside workspace: {target}")

    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            _check_components(root, target)
            if _checked_stat(target) is None:
                return
            _clear_readonly_tree(target)
            shutil.rmtree(target)
            if _checked_stat(target) is None:
                return
        except (PermissionError, OSError) as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(delay_seconds)

    detail = f": {last_error}" if last_error is not None else ""
    raise CleanupError(
        f"cleanup verification failed after {attempts} attempts; path still exists: {target}{detail}"
    )


def cleanup_many(
    paths: Iterable[Path],
    *,
    workspace: Path | None = None,
    attempts: int = 12,
    delay_seconds: float = 1.0,
) -> None:
    errors: list[str] = []
    for path in paths:
        try:
            remove_tree_verified(
                path,
                workspace=workspace,
                attempts=attempts,
                delay_seconds=delay_seconds,
            )
        except (CleanupError, OSError) as exc:
            errors.append(str(exc))
    if errors:
        raise CleanupError("; ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--attempts", type=int, default=12)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    args = parser.parse_args()
    try:
        cleanup_many(
            args.paths,
            attempts=args.attempts,
            delay_seconds=args.delay_seconds,
        )
    except (CleanupError, ValueError) as exc:
        print(f"nexus_windows_cleanup=FAIL reason={exc}", file=os.sys.stderr)
        return 2
    print("nexus_windows_cleanup=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
