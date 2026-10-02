from pathlib import Path

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
