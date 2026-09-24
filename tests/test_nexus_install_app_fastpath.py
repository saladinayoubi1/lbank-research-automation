from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus-install-app-fastpath.yml"
POLICY = ROOT / "security" / "workflow-permissions-policy-v1.json"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_fastpath_is_exact_source_and_has_no_external_actions() -> None:
    workflow = text(WORKFLOW)
    assert "uses:" not in workflow
    assert "actions/" not in workflow
    assert "https://codeload.github.com/$env:GITHUB_REPOSITORY/zip/$env:GITHUB_SHA" in workflow
    assert "tar.exe -xf $sourceZip" in workflow
    assert "resolve_nexus_persistent_artifact.ps1" in workflow
    assert "download_github_actions_artifact_http11.ps1" in workflow
    assert "install_and_smoke_nexus_personal_pro.ps1" in workflow
    assert "steps.artifact.outputs.source_sha" in workflow
    assert "steps.package.outputs.inner_sha256" in workflow
    assert "DESKTOP-1R1081M" in workflow
    assert "NEXUS-LOCAL-RUNNER" in workflow


def test_fastpath_has_no_stale_installer_or_artifact_pins() -> None:
    workflow = text(WORKFLOW)
    for stale in (
        "20205aa4411857844f1a42616267e34b6ffc5e91",
        "10469382268",
        "3173e960705831c04b5b9255c643ce0fd72d2e92",
        "7288452fb90dfeb4ba9863a3a7596af4c8b9187eede354b002210d303c3b4f1f",
        "verified_local_artifact_cache",
    ):
        assert stale not in workflow


def test_fastpath_persists_fail_closed_physical_evidence() -> None:
    workflow = text(WORKFLOW)
    for marker in (
        "Physical install evidence is missing.",
        "Physical install evidence is not PASS",
        "Physical install evidence source SHA mismatch.",
        "Physical install evidence widened trading authority.",
        "Physical install evidence target mismatch.",
        "NEXUS\\evidence\\windows-app-install",
        "NEXUS_INSTALL_FASTPATH=PASS",
        "GITHUB_STEP_SUMMARY",
    ):
        assert marker in workflow


def test_fastpath_permissions_are_read_only_and_policy_bound() -> None:
    workflow = yaml.safe_load(text(WORKFLOW))
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    policy = json.loads(text(POLICY))
    rule = policy["workflows"][".github/workflows/nexus-install-app-fastpath.yml"]
    assert rule["workflow_permissions"] == {"actions": "read", "contents": "read"}
    assert "write" not in rule["workflow_permissions"].values()
