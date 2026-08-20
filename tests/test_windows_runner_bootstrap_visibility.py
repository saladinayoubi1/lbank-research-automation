from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "desktop" / "nexus-product" / "bootstrap-main.js"
PRELOAD = ROOT / "desktop" / "nexus-product" / "preload.js"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_runner_bootstrap_evidence_reader_is_bounded_local_and_secret_free() -> None:
    text = read(ENTRY)
    for marker in (
        "RUNNER_STATE_CHANNEL = 'nexus:runner-bootstrap:get'",
        "RUNNER_EVIDENCE_MAX_BYTES = 64 * 1024",
        "process.env.LOCALAPPDATA",
        "path.resolve(localAppData, 'NEXUS')",
        "'GuiRunnerBootstrap', 'evidence.json'",
        "fs.lstatSync(target)",
        "stat.isSymbolicLink()",
        "stat.size > RUNNER_EVIDENCE_MAX_BYTES",
        "EVIDENCE_FILE_REJECTED",
        "EVIDENCE_SCHEMA_REJECTED",
        "EVIDENCE_STATUS_REJECTED",
        "EVIDENCE_NOT_PRESENT",
        "EVIDENCE_READ_FAILED",
        "safeRunnerText(payload.error, 240)",
    ):
        assert marker in text
    lowered = text.casefold()
    assert ".credentials" not in lowered
    assert "readdirsync" not in lowered
    assert "glob" not in lowered
    assert "runner_root:" not in text


def test_runner_bootstrap_evidence_reader_tolerates_windows_powershell_utf8_bom() -> None:
    text = read(ENTRY)
    assert "function parseRunnerEvidenceJson(raw)" in text
    assert "text.charCodeAt(0) === 0xFEFF ? text.slice(1) : text" in text
    assert "parseRunnerEvidenceJson(fs.readFileSync(target, 'utf8'))" in text


def test_runner_state_ipc_is_loopback_only_and_returns_whitelisted_projection() -> None:
    text = read(ENTRY)
    assert "trustedRunnerStateSender" in text
    assert r"/^http:\/\/127\.0\.0\.1:\d+\//" in text
    assert "if (!trustedRunnerStateSender(event)) throw new Error('untrusted NEXUS runner-state sender')" in text
    for key in (
        "available:",
        "status,",
        "source_sha:",
        "generated_at:",
        "agent_name:",
        "service_name:",
        "service_state:",
        "fallback_transport:",
        "error:",
    ):
        assert key in text


def test_preload_surfaces_runner_state_without_continuous_polling_or_html_injection() -> None:
    text = read(PRELOAD)
    for marker in (
        "runner: 'nexus:runner-bootstrap:get'",
        "getRunnerBootstrapState: () => ipcRenderer.invoke(CHANNELS.runner)",
        "RUNNER READY",
        "RUNNER BLOCKED",
        "RUNNER UNKNOWN",
        "document.getElementById('runnerBootstrapState')",
        "document.createElement('span')",
        "label.textContent",
        "setTimeout(() => { void refreshRunnerBadge(); }, 32000)",
        "window.addEventListener('focus'",
    ):
        assert marker in text
    lowered = text.casefold()
    assert "innerhtml" not in lowered
    assert "setinterval" not in lowered
    assert "require('fs')" not in lowered
    assert "require('path')" not in lowered


@pytest.mark.parametrize("path", [ENTRY, PRELOAD])
def test_runner_visibility_javascript_parses(path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is unavailable")
    result = subprocess.run(
        [node, "--check", str(path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
