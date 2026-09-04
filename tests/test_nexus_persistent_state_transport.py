from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from scripts import nexus_persistent_state_handoff as handoff
from scripts import nexus_persistent_state_transport as transport


def test_state_handoff_round_trip_is_digest_checked_and_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "state"
    (state / "demo").mkdir(parents=True)
    (state / "demo" / "snapshot.json").write_text('{"paper_only":true}\n', encoding="utf-8")
    (state / "matrix-state.json").write_text('{"cells":{}}\n', encoding="utf-8")
    archive = tmp_path / "handoff.zip"
    result = handoff.pack_state(state, archive)
    assert result["file_count"] == 2
    assert 1 <= len(result["chunks"]) <= handoff.MAX_CHUNKS

    monkeypatch.setenv("STATE_ARCHIVE_CHUNK_COUNT", str(len(result["chunks"])))
    monkeypatch.setenv("STATE_ARCHIVE_B64_LEN", str(result["b64_len"]))
    monkeypatch.setenv("STATE_ARCHIVE_SHA256", str(result["sha256"]))
    for index in range(handoff.MAX_CHUNKS):
        value = result["chunks"][index] if index < len(result["chunks"]) else ""
        monkeypatch.setenv(f"STATE_ARCHIVE_CHUNK_{index}", value)

    rebuilt = tmp_path / "rebuilt.zip"
    extracted = tmp_path / "extracted"
    verification = handoff.rehydrate_from_environment(rebuilt)
    handoff.extract_validated(rebuilt, extracted)
    assert verification["sha256"] == result["sha256"]
    assert (extracted / "demo" / "snapshot.json").read_text(encoding="utf-8") == '{"paper_only":true}\n'
    assert (extracted / "matrix-state.json").is_file()


def test_state_handoff_rejects_symlink_source(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    target = state / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    link = state / "link.json"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unsupported")
    with pytest.raises(handoff.PersistentStateHandoffError, match="symlink"):
        handoff.pack_state(state, tmp_path / "bad.zip")


def test_restore_transport_rejects_path_traversal_zip(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.json", "{}")
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(transport.PersistentStateTransportError, match="unsafe"):
            transport._safe_members(archive)


def test_restore_transport_skips_network_when_external_state_already_present(
    tmp_path: Path
) -> None:
    state = tmp_path / "external"
    state.mkdir()
    (state / "matrix-state.json").write_text("{}\n", encoding="utf-8")
    result = transport.restore_latest(
        repository="owner/repo",
        artifact_name="nexus-persistent-paper-trading-state",
        destination=state,
        token="not-used-because-skip",
        work_root=tmp_path / "work",
        only_if_empty=True,
    )
    assert result == {
        "decision": "skip",
        "reason": "external_state_already_present",
        "artifact_id": None,
    }
