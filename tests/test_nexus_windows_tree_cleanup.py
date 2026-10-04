import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from scripts.nexus_windows_tree_cleanup import CleanupError, cleanup_many, remove_tree_verified


def test_cleanup_removes_tree_and_verifies_absence(tmp_path: Path):
    target = tmp_path / "build" / "state"
    target.mkdir(parents=True)
    (target / "_archive_plan.json").write_text("{}", encoding="utf-8")

    remove_tree_verified(Path("build/state"), workspace=tmp_path, attempts=2, delay_seconds=0)

    assert not target.exists()


def test_cleanup_missing_tree_is_success(tmp_path: Path):
    remove_tree_verified(Path("build/missing"), workspace=tmp_path, attempts=1, delay_seconds=0)


def test_cleanup_refuses_workspace_and_escape(tmp_path: Path):
    with pytest.raises(CleanupError, match="outside workspace"):
        remove_tree_verified(Path("."), workspace=tmp_path, attempts=1, delay_seconds=0)

    with pytest.raises(CleanupError, match="outside workspace"):
        remove_tree_verified(Path("../outside"), workspace=tmp_path, attempts=1, delay_seconds=0)


def test_cleanup_retries_transient_windows_style_delete_failure(tmp_path: Path, monkeypatch):
    target = tmp_path / "build" / "state"
    target.mkdir(parents=True)
    (target / "_archive_plan.json").write_text("{}", encoding="utf-8")

    import scripts.nexus_windows_tree_cleanup as cleanup

    real_rmtree = cleanup.shutil.rmtree
    calls = {"count": 0}

    def flaky_rmtree(path):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError("sharing violation")
        real_rmtree(path)

    monkeypatch.setattr(cleanup.shutil, "rmtree", flaky_rmtree)
    remove_tree_verified(Path("build/state"), workspace=tmp_path, attempts=2, delay_seconds=0)

    assert calls["count"] == 2
    assert not target.exists()


def test_cleanup_fails_closed_when_tree_survives_all_attempts(tmp_path: Path, monkeypatch):
    target = tmp_path / "build" / "state"
    target.mkdir(parents=True)
    (target / "_archive_plan.json").write_text("{}", encoding="utf-8")

    import scripts.nexus_windows_tree_cleanup as cleanup

    monkeypatch.setattr(
        cleanup.shutil,
        "rmtree",
        lambda path: (_ for _ in ()).throw(PermissionError("sharing violation")),
    )

    with pytest.raises(CleanupError, match="path still exists"):
        remove_tree_verified(Path("build/state"), workspace=tmp_path, attempts=2, delay_seconds=0)

    assert target.exists()


def test_cleanup_many_reports_any_surviving_tree(tmp_path: Path, monkeypatch):
    good = tmp_path / "build" / "good"
    bad = tmp_path / "build" / "bad"
    good.mkdir(parents=True)
    bad.mkdir(parents=True)

    import scripts.nexus_windows_tree_cleanup as cleanup

    real_rmtree = cleanup.shutil.rmtree

    def selective_rmtree(path):
        if Path(path).name == "bad":
            raise PermissionError("sharing violation")
        real_rmtree(path)

    monkeypatch.setattr(cleanup.shutil, "rmtree", selective_rmtree)

    with pytest.raises(CleanupError):
        cleanup_many(
            [Path("build/good"), Path("build/bad")],
            workspace=tmp_path,
            attempts=1,
            delay_seconds=0,
        )

    assert not good.exists()
    assert bad.exists()


def test_a7_a9_workflows_use_verified_cleanup_without_silent_success():
    a7 = Path(".github/workflows/nexus_multipair_archive_snapshot.yml").read_text(encoding="utf-8")
    a9 = Path(".github/workflows/nexus_a9_positioning_research.yml").read_text(encoding="utf-8")

    assert "scripts/nexus_windows_tree_cleanup.py build\\a7-recent-state build\\a7-recent-cache" in a7
    assert "scripts/nexus_windows_tree_cleanup.py build\\a9-spot-state build\\a9-spot-cache build\\a9-positioning" in a9

    a7_raw = a7.split("- name: Remove raw A7 source state", 1)[1].split("- name: Clean isolated Python", 1)[0]
    a9_raw = a9.split("- name: Remove raw Research state", 1)[1].split("- name: Clean isolated Python", 1)[0]
    assert "rmdir /s /q" not in a7_raw
    assert "rmdir /s /q" not in a9_raw
    assert "exit /b 0" not in a7_raw
    assert "exit /b 0" not in a9_raw
    assert "if errorlevel 1 exit /b %errorlevel%" in a7_raw
    assert "if errorlevel 1 exit /b %errorlevel%" in a9_raw


def _symlink(source: Path, destination: Path, *, directory: bool = False):
    try:
        source.symlink_to(destination, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")


@pytest.mark.parametrize("requested", ["link", "link/child"])
def test_cleanup_refuses_link_target_and_link_ancestor(tmp_path: Path, requested: str):
    destination = tmp_path / "keep" / "child"
    destination.mkdir(parents=True)
    marker = destination / "_archive_plan.json"
    marker.write_text("preserve", encoding="utf-8")
    _symlink(tmp_path / "link", destination.parent, directory=True)

    with pytest.raises(CleanupError, match="symlink/reparse"):
        remove_tree_verified(Path(requested), workspace=tmp_path, attempts=1, delay_seconds=0)

    assert marker.read_text(encoding="utf-8") == "preserve"
    assert (tmp_path / "link").is_symlink()


def test_cleanup_refuses_dangling_link(tmp_path: Path):
    link = tmp_path / "dangling"
    _symlink(link, tmp_path / "missing", directory=True)

    with pytest.raises(CleanupError, match="symlink/reparse"):
        remove_tree_verified(Path("dangling"), workspace=tmp_path, attempts=1, delay_seconds=0)

    assert link.is_symlink()


def test_cleanup_refuses_nested_link_without_changing_external_file(tmp_path: Path):
    workspace = tmp_path / "workspace"
    target = workspace / "build" / "state"
    target.mkdir(parents=True)
    external = tmp_path / "external"
    external.write_text("preserve", encoding="utf-8")
    external.chmod(stat.S_IREAD)
    before = external.stat().st_mode
    _symlink(target / "linked-file", external)
    try:
        with pytest.raises(CleanupError, match="symlink/reparse"):
            remove_tree_verified(Path("build/state"), workspace=workspace, attempts=1, delay_seconds=0)
        assert external.read_text(encoding="utf-8") == "preserve"
        assert external.stat().st_mode == before
        assert target.exists()
    finally:
        external.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_cleanup_retries_failure_during_attribute_scan(tmp_path: Path, monkeypatch):
    import scripts.nexus_windows_tree_cleanup as cleanup

    target = tmp_path / "build" / "state"
    target.mkdir(parents=True)
    real_clear = cleanup._clear_readonly_tree
    calls = []

    def transient_scan(path):
        calls.append(path)
        if len(calls) == 1:
            raise PermissionError("transient scan lock")
        real_clear(path)

    monkeypatch.setattr(cleanup, "_clear_readonly_tree", transient_scan)
    remove_tree_verified(Path("build/state"), workspace=tmp_path, attempts=2, delay_seconds=0)
    assert len(calls) == 2
    assert not target.exists()


def test_cleanup_rejects_silent_delete_failure(tmp_path: Path, monkeypatch):
    import scripts.nexus_windows_tree_cleanup as cleanup

    target = tmp_path / "state"
    target.mkdir()
    monkeypatch.setattr(cleanup.shutil, "rmtree", lambda path: None)
    with pytest.raises(CleanupError, match="path still exists"):
        remove_tree_verified(Path("state"), workspace=tmp_path, attempts=1, delay_seconds=0)
    assert target.exists()


@pytest.mark.skipif(os.name != "nt", reason="requires a native Windows sharing violation")
def test_windows_locked_archive_plan_fails_cli_then_recovers(tmp_path: Path):
    target = tmp_path / "build" / "state"
    target.mkdir(parents=True)
    plan = target / "_archive_plan.json"
    plan.write_text("{}", encoding="utf-8")
    script = Path("scripts/nexus_windows_tree_cleanup.py").resolve()

    with plan.open("rb"):
        result = subprocess.run(
            [sys.executable, str(script), "build/state", "--attempts", "2", "--delay-seconds", "0"],
            cwd=tmp_path, capture_output=True, text=True, check=False,
        )
        assert result.returncode == 2
        assert "nexus_windows_cleanup=FAIL" in result.stderr
        assert plan.exists()

    remove_tree_verified(Path("build/state"), workspace=tmp_path, attempts=1, delay_seconds=0)
    assert not target.exists()


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows read-only attributes")
def test_windows_readonly_archive_plan_is_removed(tmp_path: Path):
    target = tmp_path / "build" / "state"
    target.mkdir(parents=True)
    plan = target / "_archive_plan.json"
    plan.write_text("{}", encoding="utf-8")
    plan.chmod(stat.S_IREAD)

    remove_tree_verified(Path("build/state"), workspace=tmp_path, attempts=1, delay_seconds=0)
    assert not target.exists()


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows directory junctions")
@pytest.mark.parametrize("location", ["target", "ancestor", "nested"])
@pytest.mark.parametrize("external", [False, True])
def test_windows_junction_refused_and_destination_preserved(tmp_path: Path, location: str, external: bool):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    destination = (tmp_path if external else workspace) / "keep"
    destination.mkdir()
    child = destination / "child"
    child.mkdir()
    marker = child / "_archive_plan.json"
    marker.write_text("preserve", encoding="utf-8")
    state = workspace / "build" / "state"
    state.mkdir(parents=True)
    junction = state / "linked" if location == "nested" else workspace / "build" / "link"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(destination)],
                   capture_output=True, text=True, check=True)
    requested = Path("build/state") if location == "nested" else junction.relative_to(workspace)
    if location == "ancestor":
        requested /= "child"
    try:
        with pytest.raises(CleanupError, match="symlink/reparse"):
            remove_tree_verified(requested, workspace=workspace, attempts=1, delay_seconds=0)
        assert marker.read_text(encoding="utf-8") == "preserve"
        assert junction.exists()
    finally:
        os.rmdir(junction)
