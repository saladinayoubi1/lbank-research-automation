"""File-only disposable-profile snapshot tests; NO real owner process or profile access."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "nexus_disposable_profile_snapshot.py"
spec = importlib.util.spec_from_file_location("nexus_disposable_profile_snapshot_tests", SCRIPT)
assert spec and spec.loader
snapshot_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = snapshot_module
spec.loader.exec_module(snapshot_module)

SOURCE = "e" * 40
JOURNAL = b'{"event":"paper-original-500-usdt"}\n'


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def ctx(tmp_path: Path) -> dict:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    original = tmp_path / "original-owner-profile"
    original.mkdir()
    (original / "do-not-modify.txt").write_text("original stays intact", encoding="utf-8")
    src = scratch / "activation-clone-fixture"
    for name, data in {
        "Local State": b"{}",
        "Preferences": b"{}",
        "Local Storage/leveldb/CURRENT": b"MANIFEST-000001",
        "Session Storage/CURRENT": b"fixture",
        "Network/Cookies": b"SQLite-disposable-cookie-fixture",
        "product-data/product_runtime/paper-events.jsonl": JOURNAL,
        "Cache/transient": b"exclude only transient cache",
    }.items():
        p = src / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    proof = tmp_path / "outside-clone-proof.json"
    proof.write_text(json.dumps({
        "decision": "PASS_CLONE_ONLY",
        "source_sha": SOURCE,
        "owner_journal_sha256": hashlib.sha256(JOURNAL).hexdigest(),
        "owner_activated": False,
        "original_owner_processes_preserved": True,
        "original_owner_shortcuts_preserved": True,
        "original_global_paper_sync_preserved": True,
    }), encoding="utf-8")
    return {
        "scratch_root": scratch, "source": src,
        "destination": scratch / (src.name + "-verified-fullsnapshot"),
        "owner_profile": original, "clone_proof": proof,
        "expected_proof_sha256": hash_file(proof),
        "expected_source_sha": SOURCE,
        "expected_journal_sha256": hashlib.sha256(JOURNAL).hexdigest(),
        "report": scratch / "snapshot-evidence.json",
    }


def run(ctx: dict) -> dict:
    return snapshot_module.snapshot(**ctx)


def test_complete_disposable_clone_copy_includes_cookies_and_journal(ctx):
    original_marker = (ctx["owner_profile"] / "do-not-modify.txt").read_bytes()
    result = run(ctx)
    assert result["decision"] == "PASS_DISPOSABLE_FILE_INTEGRITY_ONLY"
    assert result["cookies_included"] is True
    assert result["file_count"] == 6
    assert result["owner_activation_authorized"] is False
    assert result["real_owner_full_profile_copied"] is False
    assert result["disposable_clone_process_quiescence_independently_proven"] is False
    assert "Cache/transient" not in {x["relative"] for x in result["file_manifest"]}
    for entry in result["file_manifest"]:
        target = ctx["destination"] / entry["relative"]
        assert hash_file(target) == entry["sha256"]
    assert json.loads(ctx["report"].read_text()) == result
    assert original_marker == (ctx["owner_profile"] / "do-not-modify.txt").read_bytes()


@pytest.mark.parametrize("change,error", [
    ("bad_pin", "INDEPENDENT_CLONE_PROOF_SHA_MISMATCH"),
    ("false_owner", "CLONE_PROOF_BOUNDARY_REFUSED"),
    ("missing_cookie", "PERSISTENT_PROFILE_COVERAGE_INCOMPLETE"),
    ("missing_session", "SESSION_STORAGE_COVERAGE_INCOMPLETE"),
    ("journal_changed", "ORIGINAL_PAPER_JOURNAL_MISMATCH"),
])
def test_untrusted_or_incomplete_source_refuses_before_copy(ctx, change, error):
    if change == "bad_pin":
        ctx["expected_proof_sha256"] = "0" * 64
    elif change == "false_owner":
        proof = json.loads(ctx["clone_proof"].read_text())
        proof["original_owner_processes_preserved"] = False
        ctx["clone_proof"].write_text(json.dumps(proof))
        ctx["expected_proof_sha256"] = hash_file(ctx["clone_proof"])
    elif change == "missing_cookie":
        (ctx["source"] / "Network" / "Cookies").unlink()
    elif change == "missing_session":
        (ctx["source"] / "Session Storage" / "CURRENT").unlink()
    else:
        (ctx["source"] / "product-data/product_runtime/paper-events.jsonl").write_bytes(
            b"altered journal"
        )
    with pytest.raises(ValueError, match=error):
        run(ctx)
    assert not ctx["destination"].exists()
    assert not ctx["report"].exists()


def test_refuse_actual_owner_profile_even_if_named_disposable(ctx):
    ctx["owner_profile"] = ctx["source"]
    with pytest.raises(ValueError, match="DISPOSABLE_SCRATCH_BOUNDARY_REFUSED"):
        run(ctx)
    assert not ctx["destination"].exists()


def test_partial_copy_failure_quarantines_incomplete_and_never_claims_success(
    ctx, monkeypatch
):
    original_copy = shutil.copy2

    def fail_cookie(src, dst, *args, **kwargs):
        if Path(src).name == "Cookies":
            raise PermissionError(32, "fixture sharing lock")
        return original_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(snapshot_module.shutil, "copy2", fail_cookie)
    with pytest.raises(PermissionError):
        run(ctx)
    pending = ctx["destination"].with_name(ctx["destination"].name + ".INCOMPLETE")
    assert pending.is_dir()
    assert not ctx["destination"].exists()
    assert not ctx["report"].exists()
    assert (ctx["owner_profile"] / "do-not-modify.txt").read_text() == "original stays intact"


def test_midcopy_source_mutation_fails_closed(ctx, monkeypatch):
    real_copy = shutil.copy2

    def alter_cookie(src, dst, *args, **kwargs):
        result = real_copy(src, dst, *args, **kwargs)
        if Path(src).name == "Cookies":
            with Path(src).open("ab") as stream:
                stream.write(b"source modified during copy")
        return result

    monkeypatch.setattr(snapshot_module.shutil, "copy2", alter_cookie)
    with pytest.raises(ValueError, match="SOURCE_CHANGED_DURING_SNAPSHOT"):
        run(ctx)
    assert not ctx["destination"].exists()
    assert not ctx["report"].exists()


def test_existing_destination_or_incomplete_copy_cannot_be_overwritten(ctx):
    ctx["destination"].mkdir()
    with pytest.raises(ValueError, match="DISPOSABLE_SCRATCH_BOUNDARY_REFUSED"):
        run(ctx)
    ctx["destination"].rmdir()
    ctx["destination"].with_name(ctx["destination"].name + ".INCOMPLETE").mkdir()
    with pytest.raises(ValueError, match="DISPOSABLE_SCRATCH_BOUNDARY_REFUSED"):
        run(ctx)


def test_persistent_symlink_is_rejected_without_traversal(ctx):
    link = ctx["source"] / "Network" / "original-owner-leak"
    try:
        link.symlink_to(ctx["owner_profile"], target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted in this CI environment")
    with pytest.raises(ValueError, match="REPARSE_POINT_REFUSED"):
        run(ctx)
    assert not ctx["destination"].exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing lock test")
def test_windows_exclusive_cookie_handle_fails_closed(ctx):
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    cookie = ctx["source"] / "Network" / "Cookies"
    handle = kernel.CreateFileW(str(cookie), 0x80000000, 0, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        with pytest.raises((OSError, PermissionError)):
            run(ctx)
        assert not ctx["destination"].exists()
        assert not ctx["report"].exists()
    finally:
        assert kernel.CloseHandle(handle)


@pytest.mark.skipif(os.name != "nt", reason="NTFS junction test")
def test_windows_ntfs_junction_is_rejected_without_touching_owner(ctx):
    import subprocess

    link = ctx["source"] / "Network" / "junction-to-original-owner"
    created = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(link), str(ctx["owner_profile"])],
        capture_output=True, text=True,
    )
    if created.returncode:
        pytest.skip("test environment does not permit disposable junction fixture")
    try:
        with pytest.raises(ValueError, match="REPARSE_POINT_REFUSED"):
            run(ctx)
        assert not ctx["destination"].exists()
        assert not ctx["report"].exists()
        assert (ctx["owner_profile"] / "do-not-modify.txt").read_text() == (
            "original stays intact"
        )
    finally:
        link.rmdir()


def test_script_exposes_no_process_control_or_real_owner_install_path():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "owner_activation_authorized" in text
    assert "real_owner_full_profile_copied" in text
    for forbidden in ("Stop-Process", "CloseMainWindow", "Restart-Computer",
                      "os.kill(", "subprocess.", "shutil.rmtree("):
        assert forbidden not in text
