from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import start_local_dashboard as launcher


def _configure_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path
    integration_root = root / "data" / "integrations"
    legacy_root = root / "integrations"
    reference_json = root / "references" / "crypto-fx-library.json"
    zotero_report = integration_root / "zotero_metadata_report_v2.json"

    integration_root.mkdir(parents=True)
    reference_json.parent.mkdir(parents=True)
    reference_json.write_text("[]\n", encoding="utf-8")

    monkeypatch.setattr(launcher, "ROOT", root)
    monkeypatch.setattr(launcher, "INTEGRATION_ROOT", integration_root)
    monkeypatch.setattr(launcher, "LEGACY_INTEGRATION_ROOT", legacy_root)
    monkeypatch.setattr(launcher, "REFERENCE_JSON", reference_json)
    monkeypatch.setattr(launcher, "ZOTERO_REPORT", zotero_report)
    return reference_json, zotero_report


def test_zotero_findings_exit_code_writes_valid_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, report_path = _configure_paths(monkeypatch, tmp_path)
    payload = '{"finding_count": 2, "item_count": 3, "schema_version": "2.0"}\n'

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["check"] is False
        return subprocess.CompletedProcess(args[0], 1, stdout=payload, stderr="")

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    launcher.ensure_zotero_report()

    assert report_path.read_text(encoding="utf-8") == payload


def test_zotero_execution_failure_still_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_paths(monkeypatch, tmp_path)

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args[0], 2, stdout="", stderr="invalid export")

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        launcher.ensure_zotero_report()

    assert exc_info.value.returncode == 2


def test_empty_zotero_output_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_paths(monkeypatch, tmp_path)

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="")

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="no JSON report"):
        launcher.ensure_zotero_report()
