from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)")


def requirement_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def package_name(line: str) -> str:
    match = NAME_PATTERN.match(line)
    if match is None:
        raise AssertionError(f"Cannot parse requirement: {line}")
    return match.group(1).lower().replace("_", "-")


def test_runtime_lock_uses_exact_versions() -> None:
    lines = requirement_lines(ROOT / "requirements.lock")

    assert lines
    assert all("==" in line for line in lines)
    assert all(not line.startswith("-r ") for line in lines)


def test_declared_runtime_dependencies_are_in_lock() -> None:
    declared = {
        package_name(line)
        for line in requirement_lines(ROOT / "requirements.txt")
    }
    locked = {
        package_name(line)
        for line in requirement_lines(ROOT / "requirements.lock")
    }

    assert declared <= locked


def test_development_lock_includes_runtime_lock_and_exact_test_versions() -> None:
    lines = requirement_lines(ROOT / "requirements-dev.lock")

    assert lines[0] == "-r requirements.lock"
    assert all("==" in line for line in lines[1:])
    assert "pytest" in {package_name(line) for line in lines[1:]}


def test_automation_uses_lock_files() -> None:
    collect = (ROOT / ".github/workflows/collect.yml").read_text(encoding="utf-8")
    tests = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
    snapshot = (ROOT / ".github/workflows/export_snapshot.yml").read_text(
        encoding="utf-8"
    )
    partitioned = (ROOT / ".github/workflows/export_partitioned.yml").read_text(
        encoding="utf-8"
    )

    assert "-r requirements.lock" in collect
    assert "-r requirements-dev.lock" in tests
    assert "-r requirements.lock" in snapshot
    assert "-r requirements.lock" in partitioned
