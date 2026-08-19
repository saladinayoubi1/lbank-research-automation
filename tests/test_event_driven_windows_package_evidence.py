from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus-event-driven-failure-triage.yml"


def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_windows_package_workflow_is_allowlisted_without_new_job_or_permissions() -> None:
    body = text()
    assert "- Build NEXUS Desktop Windows" in body
    assert "github.event.workflow_run.name == 'Build NEXUS Desktop Windows'" in body

    permissions = re.search(
        r"(?ms)^permissions:\n(?P<body>(?:  [^\n]+\n)+)\nconcurrency:", body
    )
    assert permissions, "permissions block not found"
    permission_lines = {
        line.strip()
        for line in permissions.group("body").splitlines()
        if line.strip()
    }
    assert permission_lines == {
        "contents: read",
        "actions: read",
        "issues: write",
    }

    jobs = re.findall(r"(?m)^  ([A-Za-z0-9_-]+):\n    (?:if:|runs-on:)", body)
    assert jobs == ["triage"]


def test_exact_main_package_evidence_is_strict_and_fail_closed() -> None:
    body = text()
    for marker in (
        "const packageWorkflow = 'Build NEXUS Desktop Windows';",
        "const packageArtifactName = 'NEXUS_PERSONAL_PRO_FINAL_MISSION_CONTROL_WINDOWS_5_1_0';",
        "<!-- nexus-windows-main-package:${sha} -->",
        "run.event !== 'push'",
        "run.head_branch !== defaultBranch",
        "const expectedRunUrl = `https://github.com/${owner}/${repo}/actions/runs/${run.id}`;",
        "artifact?.name === packageArtifactName",
        "artifact?.expired === false",
        "artifact.id > 0",
        "artifact.size_in_bytes > 0",
        "const artifactVerified = matches.length === 1;",
        "const success = run.conclusion === 'success' && artifactVerified;",
        "An exact-main Windows package is **not** claimed for this SHA.",
        "It does **not** prove execution on the owner laptop, autostart installation, reboot/resume, or complete Phase 7 acceptance.",
    ):
        assert marker in body


def test_package_evidence_binds_to_exact_commit_and_phase7_issue() -> None:
    body = text()
    assert "const installIssueNumber = 702;" in body
    assert "github.rest.repos.getCommit({ owner, repo, ref: run.head_sha })" in body
    assert "commit?.sha !== run.head_sha" in body
    assert "github.rest.actions.listWorkflowRunArtifacts" in body
    assert "github.rest.issues.createComment" in body
    assert "github.rest.issues.updateComment" in body


def test_existing_zero_touch_install_evidence_contract_is_preserved() -> None:
    body = text()
    for marker in (
        "const installWorkflow = 'NEXUS Local Runner';",
        "const installCommitMarker = '[install-autostart]';",
        "<!-- nexus-zero-touch-install:${sha} -->",
        "const expectedArtifactName = `nexus-zero-touch-install-${run.id}`;",
        "Physical installation is **not** claimed",
    ):
        assert marker in body
